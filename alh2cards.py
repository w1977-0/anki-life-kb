#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""awesome-lifehacks → Anki 卡片（中文版），确定性批量生成。

v2（2026-09-26 重写，取代旧英文版）：
- 语言：全中文翻译（用户拍板），出处保留英文原名便于溯源
- 形式：全部通读型（自测=空）、统一风格 kaiwu、不轮换（用户拍板）
- 结构修复（旧版三处内容丢失/损坏）：
  1. 支持多 H1（Eating.md 有 Eating/Dieting/Drinking 三节）：H1 引言不再被粘进上一张卡
  2. H1 下、首个 H2 之前的引言 → 独立「引言」卡（旧版静默丢弃）
  3. 无 H2 的整篇文件（OneWheel/Plants）→ 整篇一张（旧版整篇跳过）
- md→HTML：段落/列表/引用/**H4 子标题**/代码块/图片/外链；内部链接转纯文字
- 翻译表内嵌：解析出的每个小节必须在翻译表里有条目，缺一条立即报错（绝不静默放英文）

用法：
  python3 alh2cards.py --repo /tmp/awesome-lifehacks --out /tmp/alh_all.json
  python3 alh2cards.py --repo /tmp/awesome-lifehacks --dry-run 5
"""
import argparse
import datetime
import glob
import json
import os
import re

ROOT = "20：在用::20.14：生活技巧"
SRC_NOTE = "（来源：awesome-lifehacks，无 LICENSE 文件，仅供个人自用）"
TODAY = "%d年%d月%d日" % (datetime.date.today().year,
                          datetime.date.today().month,
                          datetime.date.today().day)

# ═══════════════════════════════════════════════════════════════════
# 翻译表：(文件名, 小节键) → (中文出处, 中文正文 markdown)
#   小节键：H2 小节 = (文件, H2标题, H3标题或None)；引言/整篇 = (文件, H1标题)
#   解析时缺键 = 报错；表里多余键 = 警告（防手滑写错键）
# ═══════════════════════════════════════════════════════════════════
TRANSLATIONS = {
    # ── AI ──
    ("AI", "AI"): (
        "AI · 引言（Intro）",
        "在 AI 领域，我觉得有件事没被大家重视：为了效率而效率，纯粹是浪费精力。\n\n人必须永远先问「人这个因素关心什么」，而不是把精力花在对任何人都没有影响的事情上。\n\n技术不是文化。为了技术而技术，没有意义。",
    ),
    ("AI", "Risk, Security and Cost", None): (
        "风险、安全与成本（Risk, Security and Cost）",
        "我的 Google Cloud API 密钥泄露，仅仅是因为我挂了一个地图——密钥的权限是开放的。有人用它创建了多个自主运行的 AI，烧掉了我不少钱。\n\n我立刻把一切都锁死，并创建了权限极其受限的全新密钥。\n\n使用 AI 时，你不应该默认信任它。你应该把沙盒环境与日常使用环境隔离开，不要把机器和你的日常环境共用。如果让 AI 参与进来，就要对它的每一个动作做同行评审，并假设它会抓住一切机会把事情搞砸。\n\n> 对 AI 保持健康的戒心。",
    ),
    ("AI", "Shrink the Context and Scope", None): (
        "压缩上下文与范围（Shrink the Context and Scope）",
        "要获得最高质量的结果，就要始终专注于压缩你交给 AI 的任务的「上下文」和「范围」。\n\n我所说的**上下文**，指的是你提供给 AI 查阅的信息网络或集合。与其说得模糊笼统，不如给出具体的文件、行号和 API 名称。\n\n我所说的**范围**，指的是交给 AI 的任务的复杂度。给它极其明确的指令，明确说出你想要什么，你获得高质量结果的概率就会提高。避免负面表述——AI 没有「正与负」的概念，你只是在往 token 里引入更多会影响它模式识别的噪音。把你提交的 token 用来聚焦于「什么是正确的」，并且要具体。",
    ),
    ("AI", "Planning and Compression", None): (
        "规划与压缩（Planning and Compression）",
        "Cursor IDE 里最初叫「planning（规划）」的功能，让你可以先花一个阶段，和 AI 聊天机器人纯粹以对话的方式讨论你想让它完成的任务。它让 AI 能先做研究、整理思路、预判它可能会遇到的问题，从而提示你如何最好地解决这些问题，而不是在改动文件的中途自己想出一个方案。\n\n当你和 agent 聊天时，它会沉淀出一份包含讨论内容和关键交付项的 markdown 文件。这在 AI 圈里被称为**压缩（compression）**——它让你可以缩短对话，把总结出的结果作为一个新对话线程的起点，让 agent 在这个新线程里执行真正的改动，也许还能在更长时间里自主运行、无需你干预。",
    ),

    # ── Cleaning ──
    ("Cleaning", "Clean Top to Bottom", None): (
        "从上往下打扫（Clean Top to Bottom）",
        "从高处开始打扫，让污垢落到下一个台面上。\n\n最后所有灰尘都会落在地板上——这时我强烈推荐一台带自清洁/自动集尘底座的扫拖机器人。",
    ),
    ("Cleaning", "Dishwasher", "Hand Washing"): (
        "洗碗机 / 手洗（Hand Washing）",
        "如果你更愿意手洗，考虑只重点手洗你的核心锅具，把常见餐具交给机器：\n- 餐盘餐具\n- 结构复杂的物品\n- 顽固污渍的物品\n\n如果你打算等机器攒满再跑完整的洗涤程序，可以先用「漂洗（Rinse）」程序，防止脏碗碟在隔夜后干结。",
    ),
    ("Cleaning", "Dishwasher", "Look at how you load the machine"): (
        "洗碗机 / 看看你是怎么摆放的（Look at how you load the machine）",
        "你应该检查一下碗架，确认油污最重的餐具能接触到喷淋水流。\n\n把更脏的物品放得离喷头更近（通常在中间位置）。\n\n说真的，去找个 [YouTube 视频](https://youtu.be/jHP942Livy0?si=IuwhrM9RhbpwHqQq)看看。\n\n#### 关掉「加强烘干」模式（Disable the \"Extra Dry\" Mode）\n如果你夜间烘干或者没有水渍问题，考虑关掉「Extra Dry」之类的功能。这类模式通常在洗涤结束时有一个加热风干环节，会影响餐具的使用寿命。\n\n#### 试试「快速」模式（Consider \"Express\" Mode）\n如果你的餐具日常使用后本来就能被有效洗净，可以试试「Express」快速模式——它可能降低用水量、最高温度和洗涤时长，效果却未必打折扣。",
    ),
    ("Cleaning", "Washing Machine", "Place heavier items in the bottom of the washer"): (
        "洗衣机 / 把较重的衣物放桶底（Place heavier items in the bottom of the washer）",
        "如果你的洗衣机是顶开门（竖筒）式，把最重的衣物（牛仔裤、毛巾）放在底部，可以防止负载不均。这样重心更低，也能减少晃动撞击。\n\n把这些较长的衣物团成一个松散的球也有帮助，免得它们缠绕中心柱、卡住滚筒转动。",
    ),
    ("Cleaning", "Washing Machine", "Turn jeans/pants inside-out when washing"): (
        "洗衣机 / 洗牛仔裤和长裤时翻面（Turn jeans/pants inside-out when washing）",
        "这样口袋和里衬能干得更快。",
    ),
    ("Cleaning", "Washing Machine", "Turn some shirts/jackets inside-out to prevent pilling"): (
        "洗衣机 / 衬衫夹克翻面洗可防起球（Turn some shirts/jackets inside-out to prevent pilling）",
        "衣服洗过几次后你看到的那些小纤维球，是洗涤时衣物与其他衣物摩擦产生的。把衣服翻面洗能减少摩擦，因为面料主要是在和自己摩擦。",
    ),
    ("Cleaning", "Washing Machine", "Dryer decreases lifespan"): (
        "洗衣机 / 烘干机缩短衣物寿命（Dryer decreases lifespan）",
        "大部分衣物考虑用「轻柔（delicate）」档。把干得快的化纤衣物提前拿出来。衬衫类（扣上扣子）挂晾——我通常直接把它们挂上衣架晾在架子上。",
    ),

    # ── Coding ──
    ("Coding", "Work Life Balance", None): (
        "工作与生活的平衡（Work Life Balance）",
        "在会议和代码评审之间来回切换时很难专心写代码。有些难题需要时间去消化、需要反馈。最大的障碍往往是「缺知识」和「缺决策」。\n\n疫情时大多数商店只在下午开门，这逼着我远程开会的同时把家务一起做了。我会把编程推迟到日程里一个单独的时段。我经常刻意好几天不碰编程，专注于开会、做家务、打磨计划。等你真正坐下来写代码时，你会感激之前提前做好的研究、需求收集和头脑风暴。\n\n主动评审队友的工作时，多提问、记笔记、做研究，让他们不被卡住。专注于评审和队友的推进速度。等计划就绪，拿出一整块时间与世隔绝，纯粹专注于编程（或者专心处理邮件）。\n\n我发现效率提升之后，每周只需要一两次编程时段就够了。重要的是创造出能让你心无旁骛、不受打扰地专注手头任务的情境。当计划和研究都清晰时，代码自然流淌。\n\n一天结束时，你只能要求自己完成一件事。推动事情往前走。把球打回别人的场地——不是每个球、每个场地，而是给自己设一个能达到的最低目标，看看你的势头能带你走多远。",
    ),
    ("Coding", "Anti-Patterns", None): (
        "反模式（Anti-Patterns）",
        "代码模式只是工具。它们本身没有绝对的好坏，只是我们可以选择利用、或者刻意避开的工具。反之，在新信息出现时，要永远保持开放、随时愿意改变自己的观点。",
    ),
    ("Coding", "Code Debt and Refactorability", None): (
        "代码债与可重构性（Code Debt and Refactorability）",
        "「R」字（Refactor，重构）并不是个脏字，虽然很多管理者听到它的反应像听到了脏话。\n\n探索代码债的 spike（突击调研）虽然常常不完整，但仍然极其有用。我留了好几年的 DRAFT 草稿，总能回头重新拾起这些知识。与其逼团队接受又大又痛苦的改动，不如把你的草稿切成小块，让它们变成修复浮现出来的 bug 的补丁。这样能让这项工作真正为用户和产品经理创造价值。\n\n写代码时要抱着将来会重构的意图。预判行为演变的未来需求，试着采纳相关的范式和模式，但不要过早增加复杂度。把简单的东西变复杂，永远比把复杂的东西变简单容易。\n\n调研 spike 虽然可能带来洞见，但有时成本高昂、难以合入。一个让代码债有机会被处理并合入的办法，是把代码债与 bug 修复和性能改进的机会绑定（当然要记在项目管理工具里），这样你的经理和团队就能更清楚地看到这项工作的价值和取舍。\n\n过早优化就像其他所有「过早」的事一样……让人难堪。\n- 佚名",
    ),
    ("Coding", "80/20 Rule", None): (
        "二八法则（80/20 Rule）",
        "把精力集中在能覆盖 80% 结果/用户的 20% 工作上。然后在安排剩余工作时，找出最高频的触点优先处理。",
    ),
    ("Coding", "Peer Review", None): (
        "同行评审（Peer Review）",
        "提交到生产的每一行代码，都应该至少经过另外一个人的评审。哪怕是实习生和初级工程师也行。AI 提供的是想法，不是安全。",
    ),
    ("Coding", "Interface Design", None): (
        "界面设计（Interface Design）",
        "「先斩后奏 vs 请求许可」（Forgiveness vs Permission）。\n\n极简主义（聚焦）与拟物化（易上手）。",
    ),
    ("Coding", "Terminal", None): (
        "终端（Terminal）",
        "在终端里按 `ctrl + R` 可以搜索你的命令历史。",
    ),
    ("Coding", "JavaScript", None): (
        "JavaScript",
        "**Inverted Switch（反向 switch）**\n```javascript\nswitch (true) {\n  case  x > 0:\n  case  x < 0:\n  case  x == 0:\n}\n```\n\n**Parallel Await（并行 await）**\n```javascript\nawait Promise.all( collection.map( item => doAsyncOperation(item) ) )\n```\n\n**indexOf Found（indexOf 判断存在）**\n```javascript\nif ( ~foo.indexOf(bar) )\n```",
    ),

    # ── Cooking ──
    ("Cooking", "Boneless, Skinless Chicken Thighs", None): (
        "去骨去皮鸡腿肉（Boneless, Skinless Chicken Thighs）",
        "这块肉比鸡胸更容易煎出多汁鲜嫩的效果。试着在你大部分的鸡肉菜里用它替代鸡胸，你会发现自己对这块健康美味的肉上瘾。",
    ),
    ("Cooking", "Mayonnaise Marinade", None): (
        "蛋黄酱腌料（Mayonnaise Marinade）",
        "把任何干料腌料或你喜欢的香料混合料变成腌料——加点蛋黄酱就行。把香料均匀拌进蛋黄酱，确保食材表面裹匀。不用担心残留蛋黄酱味，因为大部分油脂会在烹饪中化掉。",
    ),
    ("Cooking", "Mushrooms", None): (
        "蘑菇（Mushrooms）",
        "蘑菇要用大火炒。盐要到最后再放，否则蘑菇会缩水、流失汁水。\n\n如果你打算加洋葱，等蘑菇开始变得油亮时再放。",
    ),
    ("Cooking", "Watermelons", None): (
        "西瓜（Watermelons）",
        "挑选好瓜的*正确*方法：挑同体积下最重的那个。如果超市有秤，尽量用一下——更多的汁水会让瓜在同等大小下更重。\n\n如果瓜切了一半，剩下的半块有时可以放进带盖的大搅拌碗里冷藏。\n\n*聚会吃法：*\n1. 把瓜切成两半\n2. 把半个瓜切面朝下放在有凹槽的砧板上\n3. 按 1–2 英寸的间隔切出一排排瓜条\n4. 转 90 度再切一遍\n5. 直接把瓜放在砧板上端上桌，让大家捏着瓜皮当把手拿\n\n> *注意：* 旁边最好放一个方便拿取的垃圾桶或大碗装瓜皮。\n\n*日常吃法：*\n1. 把瓜切成两半\n2. 把半个瓜切面朝下放在有凹槽的砧板上\n3. 花几分钟用快刀削掉所有瓜皮。你应该得到半个鲜红的瓜肉\n4. 按 1–2 英寸的间隔切出一排排瓜条\n5. 转 90 度再切一遍\n6. 拿一个大搅拌碗倒扣在半个瓜上\n7. 按住砧板和碗，把整个东西翻过来\n8. 发牙签或叉子，让大家从碗里取瓜条\n9. 盖上碗，方便冷藏保存、下次再吃。",
    ),
    ("Cooking", "Garlic", None): (
        "大蒜（Garlic）",
        "试过各种方案之后，OXO 大蒜压榨器是最可靠、最快、最好清洗的，而且不用剥皮。",
    ),
    ("Cooking", "Eggs", None): (
        "鸡蛋（Eggs）",
        "煮蛋器。\n\nTODO：待补充说明。",
    ),
    ("Cooking", "Coffee", None): (
        "咖啡（Coffee）",
        "星巴克和 Dunkin 用的都是糖浆。\n\nTODO：待补充 option-o mini、nanofoamer 和 flair 80 的说明。",
    ),

    # ── Dating ──
    ("Dating", "Standing Out", None): (
        "脱颖而出（Standing Out）",
        "把进化抽丝剥茧到最底层，就是竞争。从纯粹的概率上讲，你不可能在每个房间里都是最聪明/最健壮/最火辣的那个。但同样从概率上讲，要做到「不是最差的那个」其实很容易——因为大多数普通人要么根本不在乎，要么维持不下去。而那些把「出众」当成首要目标的人，往往会牺牲掉自己生活中其他的价值。\n\n与其如此，不如有意识地生活，把自己的存在最大化。无论你追求什么，都要带着信念和乐观去做。如果你像其他人一样「随波逐流」地活着——在 Netflix 刷剧和刷帖之间消磨时间——你就永远无法出众。不要为了追求而活着，而是去追求自我提升，看看谁欣赏你、谁能接住你创造出的能量。",
    ),
    ("Dating", "Meeting Someone New", "Archive Conversations"): (
        "认识新朋友 / 归档对话（Archive Conversations）",
        "当我们急切地等某人回消息时，有时会变得焦躁。为了帮助自己保持耐心，试试在你最后一条未收到回复的消息之后把对话归档。这样你就不会每次打开应用都被提醒「对方还没回」。眼不见，心不烦。",
    ),
    ("Dating", "Meeting Someone New", "Be Positive"): (
        "认识新朋友 / 保持积极（Be Positive）",
        "约会有时会让人沮丧。当你认识新的人时，试着让你的介绍和描述都积极一些。如今人们面对的选择实在太多了，他们不想把时间花在一个看起来无法立刻给生活带来快乐的人身上。\n\n不要把负能量带到约会或关系里去寻求解决。理解过去、做出明智的决定很重要；但执着于过去、让它影响你当下的情绪，没有好处。",
    ),
    ("Dating", "Meeting Someone New", "It's only a problem if you make it a problem"): (
        "认识新朋友 / 你不当它是问题，它就不是问题（It's only a problem if you make it a problem）",
        "人们常常为自己身上那些觉得别人可能不喜欢的特质或习惯而忧虑——体重、身高等等。如果你感兴趣的人没有把它当问题提出来，你也不该提。否则你只会把一个负面想法塞进对方脑子里，而对方可能压根从没想过这件事。",
    ),
    ("Dating", "Meeting Someone New", "Patience"): (
        "认识新朋友 / 耐心（Patience）",
        "大家都有自己的生活。当对方回到对话里时，最不想看到的就是一堵满是自我怀疑和神经质的墙——何况对方本来就没有恶意。记住，尽量永远保持积极。",
    ),
    ("Dating", "Relationships", None): (
        "亲密关系（Relationships）",
        "每个人都值得一个支持和鼓励自己的伴侣。但最能起作用的还是黄金法则：你希望世界给你什么，就先给出什么。不要等着你的伴侣或任何人来主动改善你的人生——那么多人都还在自顾不暇地打理自己的生活。",
    ),
    ("Dating", "Relationships", "Facts vs Feelings"): (
        "亲密关系 / 事实 vs 感受（Facts vs Feelings）",
        "我们吵架时，脱口而出的往往是情绪化的反应，事后又后悔。但真相是：不说话也是一个有效的回应。花时间思考、把话组织好再说出口，能让你把情绪化的反应沉淀下来，让你有机会审视和识别情绪反应中「为什么这件事会触动我」的部分，从而跨过「对方做错了什么」——那已经是无法改变的过去，只能被考虑，无法被改写。",
    ),
    ("Dating", "Relationships", "Win the fight, lose the relationship"): (
        "亲密关系 / 吵赢了架，输掉了感情（Win the fight, lose the relationship）",
        "吵架时试着提醒自己更大的目标是什么。重点不是吵赢，而是让这段关系走下去。最好的办法是提醒自己：你在这段关系里真正想要的是什么，而不只是此刻的感受。试着尽快、有意识地「输掉」这场架，你会发现你和对方都能更容易地化解问题。",
    ),

    # ── Drugs（文件标题实为 Humans and Chemicals）──
    ("Drugs", 'First episode of "Midnight Gospel" on Netflix', None): (
        "《午夜福音》第一集（First episode of \"Midnight Gospel\" on Netflix）",
        "[《午夜福音》第一集（Netflix）](https://www.netflix.com/title/80987903)\n\n「世上没有好毒品和坏毒品之分。有的只是化学物质——天然存在或人工合成的——以及我们的身体如何与它们相互作用。\n\n手术前打麻醉药：非常非常好。喝酒后打麻醉药再开车回家：非常非常糟。」\n- Dr Drew Pinsky 医生",
    ),
    ("Drugs", 'Movie "Limitless"', None): (
        "电影《永无止境》（Movie \"Limitless\"）",
        "这部电影讲的基本就是阿得拉（Adderall）。被宠坏的富家子弟把它当糖豆一样吃和卖——那不如了解一下它到底是什么。\n\n另外，Adderall 本质上就是缓释版的安非他命（冰毒）。",
    ),
    ("Drugs", "What If I Have a Bad Trip?", None): (
        "如果我有一次糟糕的体验（「坏旅程」）怎么办？（What If I Have a Bad Trip?）",
        "去探索它。\n\n这些感受和情绪自有其来源，你越用力抗拒它们、越想控制自己的念头，就越难受、越沮丧。记住「这一切终将过去」，把时间交给它，顺着这些感受走，把它们当作一次由内而外审视自己的机会去探索。\n\n情绪和念头没有重量。它们来了又走。它们不是好也不是坏，只是对刺激的反应。",
    ),

    # ── Eating（多 H1：Eating / Dieting / Drinking）──
    ("Eating", "Eating"): (
        "饮食 · 引言（Intro）",
        "食物是我们体验文化的方式。",
    ),
    ("Eating", "American Portions", None): (
        "美国菜量（American Portions）",
        "美国餐馆的菜量巨大，让控制饮食变得困难。两个人用餐时，与其各点一份主菜，不如点一份单人套餐分着吃。这样你们每人吃一半的量，还能增加菜品的种类。如果你没有同伴，可以考虑从一家餐厅买两份午餐和晚餐，开吃前先分出一半。",
    ),
    ("Eating", "Ordering", None): (
        "点菜（Ordering）",
        "问问店员最受欢迎的两道菜是什么。相信那些会点同一道菜两次的顾客。看看厨房，避开他们不擅长的菜。尽量选新鲜现做的食材和菜品。",
    ),
    ("Eating", "Sandwiches", None): (
        "三明治（Sandwiches）",
        "三明治有两种味道。把它翻过来吃，试试另一种风味——食材各层接触舌头的顺序不同，会形成完全不同的味觉体验。",
    ),
    ("Eating", "Sandwiches", "Eat Baklava Upside Down"): (
        "三明治 / 倒着吃果仁蜜饼（Eat Baklava Upside Down）",
        "一位厨艺惊人的大厨曾告诉我这个方法，我意识到这样能让舌头先碰到点心顶部那层精致酥脆的酥皮，而不是一开始就被坚果和糖浆淹没。",
    ),
    ("Eating", "Dieting"): (
        "节食 · 引言（Intro）",
        "我不相信人为地限制一种有觉知的生活。\n\n我践行的是适度与优先级。",
    ),
    ("Eating", "Ratatouille Diet", None): (
        "料理鼠王式饮食（Ratatouille Diet）",
        "「我不喜欢食物，我爱它。如果我不爱它，我就不咽下去。」\n- Anton Ego（《料理鼠王》2007）",
    ),
    ("Eating", "Eat Less, More Often", None): (
        "少吃多餐（Eat Less, More Often）",
        "永远点小份，把一天的摄入分散到全天，甚至分散到更多地方。\n\n有时我会断食一天，只为给消化留出更多时间——但破戒时要小心报复性地点单和进食。",
    ),
    ("Eating", "Pay Extra", None): (
        "多花点钱（Pay Extra）",
        "遗憾的是，吃得健康通常不可避免地更贵。如果你手头不紧，试试把肉换成虾，或者往沙拉里加块牛排——如果你受够了大多数店里配沙拉的那种味同纸板的鸡肉的话。",
    ),
    ("Eating", "8oz Soda cans", None): (
        "8 盎司小罐汽水（8oz Soda cans）",
        "尽量买用真糖（蔗糖）的，而不是高果糖玉米糖浆（HFCS）。",
    ),
    ("Eating", "Stop drinking sugar", None): (
        "戒掉含糖饮料（Stop drinking sugar）",
        "这是增加热量最快的方式。任何加工更少、更天然的东西都有帮助。",
    ),
    ("Eating", "Water Supplement", None): (
        "用水替代（Water Supplement）",
        "我对大多数膳食补充剂的态度很矛盾，因为效果太难衡量，而把它们不假思索地塞进你的日常又太容易——除了安慰剂效应，没有别的意义。\n\n话虽如此，少吃（不健康）食物的一个好办法就是用别的东西替代它，而水就是绝佳的选择。最重要的细节是花时间、精力和（金钱）找到一种令人愉悦的喝水方式——比如一个能保冷 24 小时、又是你最爱颜色的高级水瓶。一切能降低感知到的行动门槛、增加感知到的愉悦、或把好习惯与情感奖励挂钩的做法，都会下意识地鼓励你养成更健康的日常习惯和仪式。",
    ),
    ("Eating", "Drinking"): (
        "喝水 · 引言（Intro）",
        "一位患有胃病的工程师教你如何喝水。",
    ),

    # ── Fashion ──
    ("Fashion", "Fashion"): (
        "时尚 · 引言（Intro）",
        "美在观者眼中。",
    ),
    ("Fashion", "Life is too short for matching socks", None): (
        "人生苦短，何必袜子配对（Life is too short for matching socks）",
        "我的袜子要么全部一模一样，要么干脆全都互不配对。\n\n我还把内裤 100% 换成了健身款，这样随时准备好迎接在迪士尼乐园挥汗如雨的一天。",
    ),
    ("Fashion", "Shoe Laces", None): (
        "鞋带（Shoe Laces）",
        "我会花时间系鞋带。疫情之后，这是我愿意拥抱并享受的一种奢侈仪式。",
    ),
    ("Fashion", "Shoe Laces", "Dean's Quick Casual Hybrid"): (
        "鞋带 / Dean 的快速休闲混合系法（Dean's Quick Casual Hybrid）",
        "这种系法很适合靴子和鞋眼很多的鞋，可以和其他任何系法混用，让你能在宽松穿法和经典单结蝴蝶结之间快速切换，不用担心散开的鞋带绊倒。\n\n1. 把鞋带系到最上面，留出最后一排鞋眼不穿。\n2. 先打蝴蝶结的前半部分（交叉打结）。\n3. 不要做出蝴蝶结的耳朵并系紧，而是把鞋带从前往后穿过最后一排鞋眼。\n4. 在鞋内侧、鞋带末端处打一个单扭结，让带尾朝向脚外并塞到一侧。\n5. 想宽松穿着时，就保持当前这种状态。\n6. 想经典系法时，把所有鞋带拉紧到顶部，再完成蝴蝶结的其余部分。\n7. 从此再也不担心鞋带松开。",
    ),
    ("Fashion", "Shoe Laces", "Comfort Lacing"): (
        "鞋带 / 舒适系法（Comfort Lacing）",
        "[如何为跑步鞋系出舒适鞋带](https://www.reddit.com/r/coolguides/comments/o1jug5/how_to_lace_running_shoes/#lightbox)",
    ),
    ("Fashion", "Shoe Laces", "Creative Lacing"): (
        "鞋带 / 创意系法（Creative Lacing）",
        "[Ian 的鞋带网站——所有系法大全](https://www.fieggen.com/shoelace/index.htm)",
    ),
    ("Fashion", "Marie Kondo that shit", None): (
        "近藤麻理惠那一套（Marie Kondo）",
        "如果你的衣服不能让你「怦然心动」（通常你已经超过一年没穿它了），就捐掉。为每天都有机会主动给自己带来快乐腾出空间。",
    ),
    ("Fashion", "Fashion isn't comfortable", None): (
        "时尚本来就不舒服（Fashion isn't comfortable）",
        "这是事实。舒适度可以改善，但归根结底它是一个决定：\n\n「我在乎吗？」",
    ),
    ("Fashion", "Accessibility Inspires", None): (
        "无障碍启发灵感（Accessibility Inspires）",
        "如果你想找搭配的衣服，把视线模糊掉，把你要搭配的主件衣服拿到其他衣服旁边比——有时我会把衣服沿着衣柜横杆拖过去。当你下意识地从那些模糊不清的衣物中感到内心深处某种触动时，停下来，把那件拿出来。\n\n*去探索它。*\n\n这种感觉。",
    ),

    # ── Fitness ──
    ("Fitness", "Fitness"): (
        "健身 · 引言（Intro）",
        "我把内裤全部换成了健身平角裤，这样随时准备好迎接在迪士尼乐园挥汗如雨的一天。",
    ),
    ("Fitness", "7 Minute Workout", None): (
        "7 分钟训练（7 Minute Workout）",
        "[7 分钟训练（YouTube 播放列表）](https://youtube.com/playlist?list=PLZU1qiysdorZQe4T7ERd1xWkHB64H_wtd&si=TCKW2sNnBm0Spc7f)\n\n为什么不是 6 分钟？为什么不是 2 小时？\n\n把你一天中投入「人造活动」的时间按比例框好，把分配到的精力价值最大化。\n\n除非有人付钱让你保持身材，否则健身效果 2 天到 2 周内就会消退。你的数字不重要——你的「练习」才重要。就像医生是在「行医（practice medicine）」一样。",
    ),
    ("Fitness", "Only Compete With Yourself", None): (
        "只和昨天的自己比（Only Compete With Yourself）",
        "演员是被雇来去健身房的。我们大多数人都有自己的事业和爱好。不要拿自己和别人比，只和昨天的自己比——那是你唯一要打败的人。如果你总和别人比，最终你可能会发现自己常常是房间里最健壮、最性感、最聪明、最高或某方面最_出众_的那个。但总会有那么一个房间，你不是。所以至少，挑战自己永远不要做房间里最差的那个。要做到这一点，你只需要比平均水平多努力一点点——而今天的平均水平，是一群连下一部要追什么 Netflix 剧都懒得挑战自己的人。",
    ),
    ("Fitness", "Break the Losing Streak", None): (
        "打破连败（Break the Losing Streak）",
        "不要执着于维持「连续多少天坚持健身」的连胜纪录——这看起来极难长期维持，还会设定不切实际的期望。",
    ),
    ("Fitness", "Shifting your Breaking Point", None): (
        "移动你的极限点（Shifting your Breaking Point）",
        "如果你在一组训练中攒足了体能，可以试着提升强度、或者在最后冲一段高强度收尾。反过来，如果你感到自己撑不住了，可以降一降强度，换取更持久的舒适和耐力。",
    ),

    # ── Hygiene ──
    ("Hygiene", "Dental", "Mouthwash Cap"): (
        "牙齿 / 漱口水瓶盖（Mouthwash Cap）",
        "漱口水的瓶盖有个被大多数人忽略的双重用途：\n- **内盖**正好是一次的用量——倒到刻度线，用来漱口。\n- **外盖**（内盖外面套着的大杯）是用来之后含水漱口的。",
    ),
    ("Hygiene", "Dental", "Listerine Access Flosser"): (
        "牙齿 / Listerine Access 冲牙线（Listerine Access Flosser）",
        "一种带小储水槽的牙线棒，可以灌入漱口水，让你边剔牙边冲洗齿缝。非常适合难以坚持用牙线的人。",
    ),
    ("Hygiene", "Dental", "Burst USB-C Travel Toothbrush"): (
        "牙齿 / Burst USB-C 旅行牙刷（Burst USB-C Travel Toothbrush）",
        "[Burst](https://www.burst.com) 旅行牙刷用 USB-C 充电，附带的保护盖还能当刷头旅行盒。刷毛在包里保持干净，还能和手机共用同一根充电线随时充电。",
    ),
    ("Hygiene", "Body", "Lush Cosmetics"): (
        "身体 / Lush 洗护用品（Lush Cosmetics）",
        "[Lush](https://www.lushusa.com) 生产的固体洗发皂、护发皂和沐浴皂都是无包装的。它们比瓶装产品更耐用，减少塑料垃圾，而且过机场安检时符合随身行李要求。",
    ),
    ("Hygiene", "Body", "Dyson"): (
        "身体 / Dyson 美发工具（Dyson）",
        "[Dyson](https://www.dyson.com) 的美发工具（Airwrap 造型器、Supersonic 吹风机）比传统工具温度更低，却能做出专业效果，长期使用能显著减少热损伤。",
    ),
    ("Hygiene", "Intimate Hygiene", "Cardboard Tampon Applicators"): (
        "私密卫生 / 纸板卫生棉条导管（Cardboard Tampon Applicators）",
        "纸板导管可生物降解，相比塑料导管减少了塑料垃圾。Seventh Generation 和 Natracare 等品牌提供这种更可持续的选择。",
    ),
    ("Hygiene", "Intimate Hygiene", "Bidet Attachments"): (
        "私密卫生 / 马桶冲洗器附件（Bidet Attachments）",
        "马桶冲洗器坐垫或附件（如 [Tushy](https://hellotushy.com)、[Brondell](https://www.brondell.com)）比只用卫生纸清洁得更彻底、更卫生，能大幅减少卫生纸消耗，而且大多数标准马桶无需改动水管就能安装。",
    ),

    # ── OneWheel（整篇）──
    ("OneWheel", "OneWheel"): (
        "OneWheel（独轮电动滑板）",
        "![OneWheel 骑行姿势图](onewheel-riding-positions.svg)\n\n压低身体可以减小风阻、提高速度。把身体重心前倾到板头是不安全的，应该避免。\n\n电池剩余最后 30% 电量时，尽量避免冲到最高速度，否则有电池突然断电的风险。",
    ),

    # ── Organizing ──
    ("Organizing", "Organizing"): (
        "整理 · 引言（Intro）",
        "灵感来源：Adam Savage、Marie Kondo（近藤麻理惠）。",
    ),
    ("Organizing", "First Order Retrievability", None): (
        "一次取出原则（First Order Retrievability）",
        "[一次取出原则（YouTube 视频）](https://www.youtube.com/watch?v=vyCrHLYiGNo)\n\n你最常用的东西应该放在最容易拿到的位置。\n\n库存里的每样东西都应该一眼可见，任何东西都不应该被藏起来或塞在后面。\n\n物品应该按能独立运作的小组放置，小组本身要可移动、有条理。",
    ),
    ("Organizing", "Ask Yourself If It Sparks Joy", None): (
        "问问自己：它让你怦然心动吗（Ask Yourself If It Sparks Joy）",
        "[问问自己：它让你怦然心动吗（YouTube 视频）](https://www.youtube.com/watch?v=qo2v645STW0)\n\n就是近藤麻理惠那一套。\n\n该放手的时候，对自己诚实。杀掉你的心头好（Kill your darlings）——那些拖了太久、永远不会开花结果、只会成为情绪负担的想法。",
    ),
    ("Organizing", "Piles", None): (
        "堆成堆（Piles）",
        "把房间里所有东西都倒出来，在房间中央堆成一座山。把所有的收纳盒、包，统统清空，倒进这堆里。\n\n开始把这堆东西按用途分成小堆，把所有收纳容器放在一起、按大小排好。\n\n当你为某个用途或空间分好了一堆，就找出刚好能装下这堆所有东西的最小容器，把它们合到一起。",
    ),
    ("Organizing", "Go Bags", None): (
        "行动包（Go Bags）",
        "维护几个以任务为导向的包，装齐某项任务或活动所需的全部必备工具（运动、工作、美术等等）。\n\n不要在包之间共用物品——宁可多买几份，让每个行动包都自足完整。\n\n定期检查这些包是否有用、是否还井井有条。\n\n把「补充行动包」变成一种仪式：每次活动结束就清洗、补充、整理好，这样兴致一来，抓起包就能走。",
    ),
    ("Organizing", "Clean one thing at a time", None): (
        "一次只清理一样（Clean one thing at a time）",
        "[一次只清理一样（YouTube 视频）](https://www.youtube.com/watch?v=g82rr1AIm0Q)\n\n一次只专注一件事。\n\n给每样东西一个家。你会需要它吗？放在哪？\n\n这样你永远知道什么东西不见了。\n\n安心拥抱琐碎。不要催自己。一步一步养成更好的习惯。",
    ),

    # ── Plants（整篇）──
    ("Plants", "Plants"): (
        "植物（Plants）",
        "植物是一种很好的冥想方式。它们给你无穷的机会去培育和观察，去滋养、启发成长。\n\n照料和浇灌植物的那种缓慢而有节奏的仪式，能帮你进入冥想般的节奏。\n\n拥抱琐碎。不要急着完成。重要的不是终点，而是过程。",
    ),

    # ── Productivity ──
    ("Productivity", "Tasks", "Make Reminders to Create Todo Tasks"): (
        "任务 / 设提醒来创建待办（Make Reminders to Create Todo Tasks）",
        "如果你没时间写下新的需求、任务、待办事项及其描述，那就给自己设一个提醒，一小时后再来创建任务——那时候你总会有 5 到 10 分钟的空闲。Google、Siri 和 Slack 都支持「一小时后提醒我……」这类指令。",
    ),
    ("Productivity", "Tasks", "Frontload Your Calendar"): (
        "任务 / 把日程尽量往前排（Frontload Your Calendar）",
        "尽量把活动安排得越早越好。好处有很多：\n- 会议往后推比往前挪容易\n- 有必要时可以灵活安排后续跟进\n- 会议促进知识共享，让孤立的效率不再被阻塞",
    ),
    ("Productivity", "Tasks", "Priorities Evolve"): (
        "任务 / 优先级会演变（Priorities Evolve）",
        "- 找出那些「不做也不会怎样」的任务，考虑删除、重组或降低优先级",
    ),
    ("Productivity", "Tasks", "Battery Pomodoro"): (
        "任务 / 电池番茄钟（Battery Pomodoro）",
        "[番茄工作法](https://www.pomodorotechnique.com/)是专注完成单项任务的好方法。\n\n你的笔记本电池就是绝佳的计时器。把电充满，然后拔掉电源，去找一个适合工作的环境。试着连续工作，至少完成一项任务——越多越好——是的，整理邮件也算。一直干到电池耗尽，把它当作休息的信号。",
    ),
    ("Productivity", "Email", "Unsubscribe, Spam and Filter Effectively. Don't just Delete."): (
        "邮件 / 退订、标记垃圾、有效过滤，别只删（Unsubscribe, Spam and Filter Effectively. Don't just Delete.）",
        "删除垃圾邮件只能挡住这一封，而退订、标记垃圾邮件、设置过滤器能挡住这个发件人以后所有的垃圾邮件。是的，垃圾邮件很多，但这是一场马拉松，不是冲刺。比漫无目的地刷手机强。",
    ),
    ("Productivity", "Email", "Respond, Schedule, Prioritize"): (
        "邮件 / 回复、排程、分级（Respond, Schedule, Prioritize）",
        "邮件通常应该立即处理、排进日历、或者放进待办清单定好优先级。否则，如果你以后可能还用得上就归档，如果它已经过时、或者你能在别处可靠地查到这些信息，就删掉。",
    ),
    ("Productivity", "Email", "Declare Inbox Bankruptcy"): (
        "邮件 / 宣告收件箱破产（Declare Inbox Bankruptcy）",
        "如果你的未读邮件数已经多到离谱，没关系。你不等于你的收件箱。挑一个你觉得合理的日期，把这个日期之前的所有邮件归档或删掉就行。",
    ),
    ("Productivity", "Email", "Use Email Tags (Sub-Addresses)"): (
        "邮件 / 用邮箱标签·子地址（Use Email Tags (Sub-Addresses)）",
        "[子地址（Sub-addresses，维基百科）](https://en.wikipedia.org/wiki/Email_address#Sub-addressing)\n\n大多数邮箱服务都支持子地址——也就是能转发到主收件箱的邮箱变体（但会显示邮件实际发往的那个地址）。\n\n在大多数网站和服务注册时，我都会用注册对象给邮箱打上标签：`dean@gmail.com` 变成 `dean+bestbuy@gmail.com`。\n\n这样我就能按所用地址系统地过滤邮件，进一步验证商家是否正规，还能追踪自己的邮箱地址是如何被分享和扩散的（无论是合法还是非法途径）。\n\n最后，给每个网站或服务用不同的邮箱地址，比在多个网站用同一个地址更安全。可惜开放认证（用合作方账号登录）不支持在分享邮箱前自定义地址。\n\n当一个网站或账号被攻破时——通常是那些小型、过时或防护薄弱的老论坛之类的系统——黑客会用这套账号密码去其他热门服务上尝试，看受害者有没有在多处使用相同的凭据。虽然单纯在多个地方使用同一个邮箱地址未必不安全，但这个方法让你能更主动、更有力地控制自己的信息在网上的暴露方式。",
    ),

    # ── Professional ──
    ("Professional", "Professional"): (
        "职场 · 引言（Intro）",
        "在工作中，人们会通过一些关键特质来判断你的沟通方式。如果你主动追求成长，就要展示出你与被动的、自满的人之间的反差。",
    ),
    ("Professional", "Modes of Communication", "Complaining"): (
        "沟通模式 / 抱怨（Complaining）",
        "抱怨通常会让你看起来更不值得晋升，因为它传递的是负能量却不给出解决方案。它把注意力引向问题，却没有展现出主动性或解决问题的能力。",
    ),
    ("Professional", "Modes of Communication", "Questioning"): (
        "沟通模式 / 提问（Questioning）",
        "提问展现好奇心和学习的意愿，但它也暴露了你可能还需要提升自己获取信息的能力。",
    ),
    ("Professional", "Modes of Communication", "Requesting"): (
        "沟通模式 / 提出请求（Requesting）",
        "围绕调查发现来表述差距和问题、并导向具体解决方案，展现的是主动性和主人翁意识。",
    ),
    ("Professional", "Modes of Communication", "Resolving"): (
        "沟通模式 / 解决（Resolving）",
        "开始项目和任务很容易，把它们做完要难得多。专注于交付解决方案——无论大小、无论性质。",
    ),

    # ── Security ──
    ("Security", "Managing Passwords", None): (
        "管理密码（Managing Passwords）",
        "使用密码管理器钥匙串，比如 Apple、Google 或 OnePassword。\n\n每个网站都用不同的、随机生成的密码。你只需要自定义并记住一个密码：钥匙串的主密码。不要在任何地方与任何人重复使用或分享这个密码。任何对这个密码的数字化记录或保存，都应视为重大安全风险。\n\n作为交换，你的随机生成密码被攻破的代价可以忽略不计——你可以立刻重新登录，换一个新的随机密码。\n\n用开放认证（合作方登录）登录是安全的，因为你的密码永远不会被分享给该服务；但在邮箱被分享给合作方之前，你无法用邮箱标签自定义它。",
    ),

    # ── Social ──
    ("Social", "Eye Contact is a Tool", None): (
        "眼神接触是一种工具（Eye Contact is a Tool）",
        "把自我和眼神接触分离开，你就能从人们身上学到很多东西。\n\n这是现实中最接近「原力」的东西。关键在于意图和概率。\n\n盯着一个人看足够久，他就会动。无视眼神接触，他就会停止和你说话。动物就是这样交流的——通过非语言的意图。\n\n把它当成一个社会实验，看看生命会如何反应。你能用眼神接触实现隔空移物吗？什么是正常？什么是古怪？谁又会在乎呢？\n\n如果你生来失明、突然能看见了，你会贪婪地盯着世界的每一个细节看。Lasik（近视激光手术）带来的感觉也是如此。\n\n你的视觉是保障安全、理解世界的工具。不要因为恐惧而人为地自我审查。\n\n如果你想要点直白的建议：适度尝试[镜像（mirroring）](https://en.wikipedia.org/wiki/Mirroring)。适度、折中，通常从 50% 开始。试着关注并以某种内在的方式呼应你想互动的那个人。但为了避免尴尬，重要的是偶尔也要关照一下整个房间和当下，不要迷失在他人身上到不舒服的程度。让对话有来有往，轮流主导和跟随。不要纠结于哪些机会抓住了、哪些错过了——那些不过是转瞬即逝的片刻。相反，提醒自己：你和对方经历了多少才让你们此刻同处一室。效果因人而异。",
    ),
    ("Social", "Watergun for hot days", None): (
        "热天带把水枪（Watergun for hot days）",
        "热天随身带一把小水枪，给路边过热的狗喷喷水。前提是主人不介意。",
    ),
    ("Social", "Monday-Wednesday are Best Nights to go out", None): (
        "周一到周三是最好的出门夜（Monday-Wednesday are Best Nights to go out）",
        "虽然通常没有现场音乐，但人更少、价格更便宜。尤其是那些整周都有音乐的场子。",
    ),

    # ── Stress ──
    ("Stress", "Journaling is Cheaper than Therapy", None): (
        "写日记比看心理医生便宜（Journaling is Cheaper than Therapy）",
        "心理医生是一个你付钱来倾听你生活、并根据其他人相似处境的经历分享洞见的朋友。医生通常是你出问题时短暂互动的人——你把自己觉得相关的一大堆近期背景倒给他，他试着吐出一颗能神奇地让一切消失的药丸。\n\n不可能有人知道你生活里每一个细节、每一个背景。做自己的医生，只能靠你自己。\n\n如果你发现念头不停在脑子里打转，把它们写下来。\n\n通常我们太情绪化、或者太忙，无法用「抽离的视角」来看待自己的问题——除非真的经历了那个把思绪从身体里表达出来、落到纸上的物理过程。",
    ),
    ("Stress", "Chat with GPT", None): (
        "和 GPT 聊聊（Chat with GPT）",
        "如果你不介意一家科技公司了解你的一切，可以试试和 AI 聊天。它们擅长消化大量信息，并基于这些信息和类似场景给出建议。\n\n但它们的话应该永远被当作「可能是错的」，永远不能完全依赖它们来指引你的人生。技术总会失效或被攻破——不是「会不会」的问题，而是「什么时候」的问题。\n\n所以我们必须把技术仅仅当作又一个数据点，就像其他所有轶事性反馈、甚至一篇研究扎实的「学术」文章一样。把所有这些考量收进来，让它们慢慢炖。发送前先沉淀你的情绪反应——至少给它一个小时、最多 24 小时去沉淀。一时的情绪会消退，但情绪背后的底层原因可能会留下。用它来指引你的人生，不要给沉没成本附加情绪重量——它只是人生中的又一个数据点。",
    ),

    # ── Travel ──
    ("Travel", "Navigation", None): (
        "导航（Navigation）",
        "你的笔记本就是一块电池——USB-C 万岁。",
    ),
    ("Travel", "Navigation", "Battery Saver"): (
        "导航 / 省电模式（Battery Saver）",
        "我把手机的省电模式调成电量 75% 时自动开启（最大值）。这能减少应用在后台的活动和屏幕动画。「极限」省电模式会禁用列表之外的所有应用，并进一步压低性能来延长续航。",
    ),
    ("Travel", "Navigation", "Offline Google Maps"): (
        "导航 / Google 离线地图（Offline Google Maps）",
        "你可以下载 Google 地图的任意区域，旅行时减少流量消耗。",
    ),
    ("Travel", "Navigation", '"What\'s the most popular / your favorite x?"'): (
        "导航 / 「你们这最火/你最喜欢的是什么？」（What's the most popular / your favorite x?）",
        "如果你需要（在旅行时）和当地人交流，打开话题最简单的方式就是问他们的看法。你不必听从他们，但这是探索的好办法。",
    ),
    ("Travel", "When in Rome, do as the Romans", None): (
        "入乡随俗（When in Rome, do as the Romans）",
        "美食即文化，什么都尝一次。",
    ),
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(s):
    s = esc(s)
    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', s)  # 图片
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)                 # 加粗
    s = re.sub(r"\*([^*\s][^*]*?)\*", r"<em>\1</em>", s)                    # 斜体 *
    s = re.sub(r"_([^_\s][^_]*?)_", r"<em>\1</em>", s)                      # 斜体 _
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)                         # 行内代码
    s = re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]+\)", r"\1", s)             # 内部链接→纯文字
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)  # 外链
    return s


def md_to_html(body):
    lines = body.split("\n")
    out, buf, mode, code_buf = [], [], None, None

    def flush():
        nonlocal buf, mode
        if not buf:
            mode = None
            return
        if mode == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ol>")
        elif mode == "p":
            out.append("<p>%s</p>" % inline(" ".join(buf)))
        buf = []
        mode = None

    for s in lines:
        s = s.rstrip()
        if code_buf is not None:
            if s.strip().startswith("```"):
                out.append("<pre><code>%s</code></pre>" % esc("\n".join(code_buf)))
                code_buf = None
            else:
                code_buf.append(s)
            continue
        if s.strip().startswith("```"):
            flush()
            code_buf = []
        elif re.match(r"^#{4,}\s+", s):
            flush()
            out.append("<p><strong>%s</strong></p>" % esc(re.sub(r"^#+\s+", "", s)))
        elif re.match(r"^\s*[-*]\s+", s):
            if mode != "ul":
                flush()
                mode = "ul"
            buf.append(re.sub(r"^\s*[-*]\s+", "", s).strip())
        elif re.match(r"^\s*\d+\.\s+", s):
            if mode != "ol":
                flush()
                mode = "ol"
            buf.append(re.sub(r"^\s*\d+\.\s+", "", s).strip())
        elif s.strip().startswith(">"):
            flush()
            out.append("<blockquote>%s</blockquote>" % inline(s.strip().lstrip("> ").strip()))
        elif not s.strip():
            flush()
        else:
            if mode is None:
                mode = "p"
            buf.append(s.strip())
    if code_buf is not None:  # 未闭合的代码块兜底
        out.append("<pre><code>%s</code></pre>" % esc("\n".join(code_buf)))
    flush()
    return out


def clean_heading(s):
    """标题去掉 markdown 链接语法（只留文字），供翻译表匹配。"""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s).strip()


def parse_file(path):
    """解析单文件 → [(kind, h1, h2, h3, 正文md)]

    kind ∈ intro（H1 引言）/ section（H2/H3 小节）/ whole（整篇，无 H2）
    H1 支持多个（Eating.md 有 Eating/Dieting/Drinking 三节）。
    """
    txt = open(path, encoding="utf-8").read()
    out = []
    h1 = h2 = h3 = None
    has_h2 = False    # 整个文件是否有过任何 H2（区分「整篇」与「H1 引言」）
    intro = []        # 当前 H1 下、首个 H2 之前的引言行
    body = []         # 当前小节正文行

    def push(kind, h2_, h3_, text):
        t = "\n".join(text).strip()
        if t:
            out.append((kind, h1, h2_, h3_, t))

    for ln in txt.split("\n"):
        if ln.startswith("## "):
            push("section", h2, h3, body)
            body = []
            h2, h3 = clean_heading(ln[3:]), None
            has_h2 = True
        elif ln.startswith("### "):
            push("section", h2, h3, body)
            body = []
            h3 = clean_heading(ln[4:])
        elif ln.startswith("# "):
            push("section", h2, h3, body)
            body = []
            if h1 is not None:
                push("intro", None, None, intro)
            h1, h2, h3 = clean_heading(ln[2:]), None, None
            intro = []
        else:
            if h2 is None:
                intro.append(ln)
            else:
                body.append(ln)

    push("section", h2, h3, body)
    if h1 is not None:
        if not has_h2:
            push("whole", None, None, intro)   # 全文件无任何 H2 → 整篇一张
        else:
            push("intro", None, None, intro)   # 最后一个 H1 的引言
    return out


def build(repo):
    cards, missing, used = [], [], set()
    for f in sorted(glob.glob(os.path.join(repo, "*.md"))):
        name = os.path.splitext(os.path.basename(f))[0]
        if name == "README":
            continue
        for kind, h1, h2, h3, text in parse_file(f):
            key = (name, h1) if kind in ("intro", "whole") else (name, h2, h3)
            if key not in TRANSLATIONS:
                missing.append(key)
                continue
            used.add(key)
            title, body_md = TRANSLATIONS[key]
            html = "".join(md_to_html(body_md))
            if not html.strip():
                continue
            if kind == "intro":
                ctype = "句子"
            elif kind == "whole" and name == "Plants":
                ctype = "感悟"
            else:
                ctype = "方法"
            cards.append({
                "deck": ROOT,
                "notetype": "生活摘录",
                "fields": {
                    "正文": html,
                    "出处": title,
                    "我的话": "",
                    "类型": ctype,
                    "风格": "kaiwu",
                    "日期": TODAY,
                    "自测": "",
                    "来源": "awesome-lifehacks · %s" % name,
                    "备注": SRC_NOTE,
                },
                "tags": ["awesome-lifehacks", "主题-" + name, "中文翻译"],
            })
    if missing:
        raise SystemExit("缺少翻译条目 %d 个：\n%s" % (len(missing),
                          "\n".join("  %r" % (k,) for k in missing)))
    extra = set(TRANSLATIONS) - used
    if extra:
        print("⚠ 翻译表里有 %d 条从未被用到的条目（键写错？）：" % len(extra))
        for k in sorted(extra):
            print("  %r" % (k,))
    return cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/awesome-lifehacks")
    ap.add_argument("--out", default="/tmp/alh_all.json")
    ap.add_argument("--dry-run", type=int, default=0)
    a = ap.parse_args()

    cards = build(a.repo)
    print("生成卡片: %d 张" % len(cards))
    if a.dry_run:
        for c in cards[:a.dry_run]:
            print("\n" + "─" * 62)
            print("出处:", c["fields"]["出处"])
            print("来源:", c["fields"]["来源"])
            print("类型:", c["fields"]["类型"], "| 风格:", c["fields"]["风格"],
                  "| 日期:", c["fields"]["日期"])
            print("正文:", c["fields"]["正文"][:220])
        print("\n（仅预览，未写入）")
        return
    json.dump(cards, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→ %s" % a.out)


if __name__ == "__main__":
    main()

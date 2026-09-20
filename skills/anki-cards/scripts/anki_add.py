#!/usr/bin/env python3
"""把一段内容写成一张 Anki 卡片 —— 给 agent 用的确定性脚本。

为什么不直接让 agent 写 JSON：
  手写 heredoc JSON 是这个技能最容易出错的地方 —— 漏字段、风格拼错、
  牌组名写错（写错不会报错，会静默建出一个野牌组）。
  这些全是"确定性推导"，不该交给模型。

所以这里做完所有易错的事，并且**任何问题都用中文打到 stdout**，
让 agent 一眼知道下一步该干什么，不用去翻文件系统。

用法：
  python3 scripts/anki_add.py --deck <牌组> --type <类型> --body <正文> --source <出处>
                              [--note <我的话>] [--skin <版式>] [--tags a,b]
                              [--create-deck] [--dry-run]

依赖（都在本机，不用装）：
  /opt/anki-autocards/venv/bin/python
  /opt/anki-autocards/anki_cli.py
  /etc/anki-autocards/config.json

退出码：0 成功 / 2 参数有问题（按提示改）/ 3 写卡失败
"""
import argparse
import json
import subprocess
import sys

ANKI_CLI = "/opt/anki-autocards/anki_cli.py"
VENV_PY = "/opt/anki-autocards/venv/bin/python"
CONFIG = "/etc/anki-autocards/config.json"

TYPES = ["句子", "典故", "概念", "观点", "感悟", "方法", "场景", "事件", "里程碑"]
RECALL = {"观点", "概念", "典故"}          # 走回忆；其余走通读
SKINS = ["kaiwu", "gezhi", "paper", "memo"]
# 每种类型的版式池，按顺序轮换（同一批卡不要连续两张用同一套）
POOL = {
    "句子":     ["memo", "kaiwu", "paper"],
    "典故":     ["gezhi", "paper"],
    "概念":     ["kaiwu", "memo", "paper"],
    "观点":     ["gezhi", "paper", "kaiwu"],
    "感悟":     ["memo", "gezhi", "paper"],
    "方法":     ["kaiwu", "paper", "memo"],
    "场景":     ["paper", "gezhi", "kaiwu"],
    "事件":     ["paper", "kaiwu"],
    "里程碑":   ["kaiwu", "memo"],
}
NOTETYPE = "生活摘录"
FALLBACK_DECK = "00：系统::00.02：收件箱"
# 不能当出处的占位符 —— 出处是卡片顶部标题，写占位符显示出来毫无意义
BAD_SOURCE = {"", "一句话", "未知", "无", "none", "None", "null", "-", "??"}


def run_cli(args, stdin_data=None):
    cmd = [VENV_PY, ANKI_CLI, "--config", CONFIG] + args
    p = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True, timeout=180)
    out = p.stdout or ""
    i = out.find("{")
    if i < 0:
        return None, out + p.stderr
    try:
        return json.loads(out[i:]), out + p.stderr
    except Exception:
        return None, out + p.stderr


def fail(msg, code=2):
    print("【没写成】" + msg)
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--type", required=True)
    ap.add_argument("--body", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--skin", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--create-deck", action="store_true")
    ap.add_argument("--whole", action="store_true",
                    help="整篇保留（不拆、不拦 150 字、强制 paper 版式、自动加「完整保留」标签）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    # ── 1. 类型 ────────────────────────────────────────────
    if a.type not in TYPES:
        fail(f"类型「{a.type}」不在九个值里。只能是：{' / '.join(TYPES)}\n"
             f"      判不准就先读 references/类型与版式.md")

    # ── 1b. 出处：不能是占位符 ──────────────────────────────
    # 出处是卡片顶部的标题。历史上有 137 张卡的出处被填成了牌组名「一句话」，
    # 显示出来毫无意义 —— 所以这里拦死，逼模型写真来源。
    # 实在不知道来源就写「网络」（配合 30.05：网络碎片 牌组）。
    if (a.source or "").strip() in BAD_SOURCE:
        fail(f"出处「{a.source}」是占位符，不能当来源。\n"
             f"      出处要写真实来源：书名《…》/ 平台（知乎、B站、微博）/ 场景。\n"
             f"      实在不知道 → 写「网络」，牌组用 30：读过::30.05：网络碎片。")

    # ── 2. 牌组：必须真实存在 ──────────────────────────────
    # 写错牌组名不会报错，会静默新建一个野牌组 —— 所以这里卡死
    decks, raw = run_cli(["decks", "--all"])
    if decks is None:
        fail("读不到牌组列表。先跑一次：`{VENV_PY} {ANKI_CLI} --config {CONFIG} selftest`")
    names = [d["name"] for d in decks.get("decks", [])]
    counts = {d["name"]: d.get("cards", 0) for d in decks.get("decks", [])}

    deck = a.deck
    if deck not in names:
        near = [n for n in names if deck[:4] in n or n[:4] in deck][:5]
        hint = f"\n      最接近的现有牌组：{near}" if near else ""
        if not a.create_deck:
            fail(f"牌组「{deck}」不存在。{hint}\n"
                 f"      拿不准就用 --deck \"{FALLBACK_DECK}\"（收件箱），之后再分流。\n"
                 f"      确认真要新建（比如一本新书），加 --create-deck。")
        print(f"（将新建牌组：{deck}）")

    # ── 3. 版式：没给就按池轮换 ────────────────────────────
    # 取模轮换：同一批卡不要连续两张用同一套版式。
    # 用牌组现有卡数当计数器 —— 不需要额外状态文件，
    # 代价是删卡后会重复，但版式重复只是不好看，不是错误。
    pool = POOL[a.type]
    skin = a.skin
    if a.whole:
        # 整篇保留：强制 paper（克制横格，版心放宽，最适合长文）
        skin = "paper"
        if a.skin and a.skin != "paper":
            print(f"（--whole 时强制 paper 版式，忽略 --skin {a.skin}）")
        else:
            print("（--whole 整篇保留，强制 paper 版式）")
    elif not skin:
        n = counts.get(deck, 0)
        skin = pool[n % len(pool)]
        print(f"（版式未指定，按版式池轮换成 {skin}：{deck} 现有 {n} 张）")
    elif skin not in SKINS:
        fail(f"版式「{skin}」无效。只能是：{' / '.join(SKINS)}")

    # ── 3b. 正文过长 → 提示拆分（不拦死，让用户自己判断）────
    # --whole 跳过此检查（整篇保留是显式意图）
    if not a.whole and len(a.body) > 150:
        print(f"（提醒）正文 {len(a.body)} 字，超过 150 字上限。"
              f"一个完整意思一张卡 —— 能拆就拆成两张。"
              f"如果是整篇保留，加 --whole。")

    # ── 3c. 正文预处理：\n\n → </p><p>，自动包 <p> ───────────
    # 用户用 \n\n 分段会被 HTML 折叠成空格，所以脚本代转。
    # 已经有 <p> 标签的不动（避免双重包裹）。
    body = a.body.strip()
    if "<p>" not in body and "\n\n" in body:
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        body = "<p>" + "</p><p>".join(paras) + "</p>"
    elif "<p>" not in body:
        body = "<p>" + body + "</p>"

    # ── 4. 自测：由类型推导，不用 agent 操心 ────────────────
    self_test = "自测" if a.type in RECALL else ""

    payload = {
        "deck": deck,
        "notetype": NOTETYPE,
        "cards": [{
            "fields": {
                "正文": body, "出处": a.source, "我的话": a.note,
                "类型": a.type, "风格": skin, "日期": "", "自测": self_test,
            },
            "tags": [t for t in a.tags.split(",") if t] + (["完整保留"] if a.whole else []),
        }],
    }
    body = json.dumps(payload, ensure_ascii=False)

    if a.dry_run:
        print("【预演，没有真写】")
        print(body)
        return 0

    # ── 5. 写 ─────────────────────────────────────────────
    res, raw2 = run_cli(["add", "-"], stdin_data=body)
    if res is None:
        fail(f"CLI 返回读不懂。原始输出：\n{raw2[-800:]}", 3)

    s = res.get("summary", {})
    if s.get("added"):
        ent = res["added"][0]
        print(f"【已写入】{deck}")
        print(f"  类型 {a.type} → {'回忆' if self_test else '通读'}（自测={self_test or '空'}）| 版式 {skin}")
        if ent.get("repairs"):
            print(f"  工具补了：{ent['repairs']}  —— 要如实告诉用户")
        print(f"  笔记数 {s.get('total_notes')}，已同步")
        return 0

    if res.get("skipped"):
        why = res["skipped"][0]
        fail(f"被查重拦下：{why.get('front', '')[:40]}…\n"
             f"      这句话库里已经有了（查重是全库短语搜索，使用说明里的示例句也会命中）。\n"
             f"      确认是重复的 → 直接告诉用户「这句之前记过」，不要重试。\n"
             f"      确认不是重复 → 换一句，或让我来处理。", 3)

    if res.get("failed"):
        fail(f"写入失败：{res['failed'][0].get('reason')}\n"
             f"      看 references/排障.md", 3)

    fail("没有成功也没有报错，原始输出：\n" + raw2[-800:], 3)


if __name__ == "__main__":
    main()

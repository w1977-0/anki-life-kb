# Anki 人生知识库 · 自动制卡系统

在飞书里发一句话，卡片自动进 Anki，同步到你手机。

```
你（飞书）  →  Hermes Agent  →  Anki CLI  →  服务器 collection  →  同步服务器  →  手机 / 电脑
                   ↑
              制卡技能（Skill）
              判类型 · 定牌组 · 排版式
```

**这套东西解决的不是"怎么把文字存起来"，而是"存下来的东西还能不能用"。**

---

## 目录

- [这是什么](#这是什么)
- [三个核心设计决策](#三个核心设计决策)
- [架构](#架构)
- [30 分钟复刻清单](#30-分钟复刻清单)
- [目录结构](#目录结构)
- [日常怎么用](#日常怎么用)
- [给 Agent 的话](#给-agent-的话)

---

## 这是什么

一套**个人知识库 + 自动制卡**的完整工程，包含：

| 组成 | 作用 |
|---|---|
| **三个 Anki 笔记类型** | 生活摘录（主力）、生活挖空、生活选择（选择题） |
| **四套卡片版式** | 开务 / 格致 / 纸白 / 便签 —— 按内容性质自动轮换 |
| **十个内容类型**（含「长文」—— 整篇保留的文章，通读 + 只用 paper + 不限字数） | 决定"通读"还是"回忆"，决定用哪套版式 |
| **六区牌组体系** | 编号永不回收，名字随便改 |
| **Hermes 制卡技能** | 飞书里发一句话就能制卡（含确定性脚本） |
| **自托管同步服务器** | 数据在自己服务器上，手机电脑随时同步 |
| **审计与评估工具** | 全局审计（A–K 十一组）+ 技能评估（E1–E10 / 28 条断言） |

详细规范见 [`docs/`](docs/)，**从 `docs/00-总览.md` 读起**。

---

## 三个核心设计决策

这三条决定了整个系统的形状，改之前先想清楚。

### 1. 读书笔记 ≠ 备考卡

**备考卡的规则在这里是反的。**

| | 备考卡 | 读书笔记 |
|---|---|---|
| 正文 | 要改写、不许照抄 | **保真、不许改写** |
| 拆卡 | 拆到原子 | **一个完整意思一张，长句不拆** |
| 长文 | 拆 | **整篇保留（`--whole`）** |

原因：原句的措辞本身就是价值。改写了就只剩意思，而意思你早知道了。

### 2. 形式只有一个判据：有没有得答

| 形式 | 判据 | 表现 |
|---|---|---|
| **回忆** | 有得答 | 正面藏起来，翻面才看到 |
| **通读** | 没得答 | 正面全展开 |

金句、长文、自己的想法都属于"没得答" —— 先藏后显只是**假测试**，
翻面过了没有任何认知收益。所以它们一律走通读。

### 3. 长文是文档，不是卡片

当内容是"我要保存的整篇文章"时，**不拆**。它是一份文档，
拆了就散了。这类用 `--whole` 标记，强制用版心最宽的 `paper` 版式。

---

## 架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   飞书      │────▶│ Hermes Agent │────▶│  anki_add.py│
│  （你发话） │     │  （带技能）  │     │ （确定性脚本）│
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                                                 ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  手机/电脑   │◀────│ 同步服务器    │◀────│ collection   │
│  （Anki）   │     │ 127.0.0.1:8080│     │ （SQLite）   │
└─────────────┘     └──────────────┘     └─────────────┘
```

**七环链路**（排障时按这个顺序定位）：

| # | 环节 | 挂了的症状 |
|---|---|---|
| ① | 飞书 ↔ gateway | 消息石沉大海 |
| ② | gateway → 会话 | 收得到但不回 |
| ③ | 起回合 | 起了但不干活 |
| ④ | 技能装载 | 当普通聊天回你 |
| ⑤ | CLI 权限 | 报权限错 |
| ⑥ | 写入查重 | 说做了但库里没有 |
| ⑦ | 同步 | 服务器有了手机没有 |

详见 [`docs/06-Hermes链路.md`](docs/06-Hermes链路.md)。

---

## 30 分钟复刻清单

> 这套东西是**给 Agent 复刻**设计的。把仓库丢给一个 Agent，
> 让它按下面六步走，每一步都能验证。

### 第 0 步 · 准备（5 分钟）

需要：

- 一台 Linux 服务器（Debian 13 / Ubuntu 22.04 均可），能 sudo
- 一个域名（用于同步接口 + 状态页的 HTTPS）
- Python 3.11+
- 本地装好 Anki（桌面板即可）

**敏感信息用占位符**，别写进任何提交：
`<服务器IP>`、`<SSH用户>`、`example.com`。

### 第 1 步 · 部署同步服务器（10 分钟）

```bash
sudo bash deploy/01-deploy-syncserver.sh
```

这个脚本做四件事：

1. 建独立 venv（`/opt/anki-autocards/venv`），装 `anki` + `anki.syncserver`
2. 把 syncserver 注册成 systemd 服务，只监听 `127.0.0.1:8080`
3. 装 `anki_cli.py` 到 `/opt/anki-autocards/`
4. 建工作库 `/var/lib/anki-autocards/collection.anki2`

验证：

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/
# 期望 200
```

详细原理与手动步骤见 [`docs/07-同步服务器.md`](docs/07-同步服务器.md)。

### 第 2 步 · 装笔记类型（3 分钟）

```bash
sudo /opt/anki-autocards/venv/bin/python deploy/apply_templates.py
```

会创建三个笔记类型并写入 CSS 和模板：

| 笔记类型 | 字段 | CSS |
|---|---|---|
| 生活摘录 | 正文/出处/我的话/类型/风格/日期/**自测** | base + cloze |
| 生活挖空 | 正文/出处/我的话/类型/风格/日期 | base + cloze |
| 生活选择 | 正文/**选项**/出处/我的话/类型/风格/日期 | base + choice |

验证：

```bash
sudo /opt/anki-autocards/venv/bin/python tools/audit_system.py
# 期望 25/25
```

### 第 3 步 · 装制卡技能（2 分钟）

```bash
mkdir -p ~/.hermes/skills/note-taking/
cp -r skills/anki-cards ~/.hermes/skills/note-taking/
chmod +x ~/.hermes/skills/note-taking/anki-cards/scripts/anki_add.py
```

**改完技能必须重启 gateway**（技能提示在启动时烘进内存）：

```bash
sudo systemctl restart hermes-gateway
```

### 第 4 步 · 跑评估（1 分钟）

```bash
sudo /opt/anki-autocards/venv/bin/python tools/eval_skill.py
# 期望 25/25
```

### 第 5 步 · 发一条消息试试

在飞书发：

```
记下这段：《纳瓦尔宝典》—— 欲望就是你跟自己的约定：在得到我想要的东西之前，我拒绝快乐。
```

然后：

```bash
sudo /opt/anki-autocards/venv/bin/python tools/check_run.py
# 期望：✅ 全通，写了 1 张
```

---

## 目录结构

```
.
├── README.md                  本文件
├── docs/                      规范（从 00 读起）
│   ├── 00-README.md           文档索引 / 阅读顺序
│   ├── 00-总览.md
│   ├── 01-规范.md             三个笔记类型、字段、形式
│   ├── 02-操作.md             日常怎么跑
│   ├── 03-踩坑.md             14 个真踩过的坑
│   ├── 04-分类体系.md         六区牌组 + 判定顺序
│   ├── 05-命名规范.md         编号 / emoji / 评级
│   ├── 06-Hermes链路.md       七环链路 + 排障
│   ├── 07-同步服务器.md       自建同步服务器
│   └── 08-长文制卡.md         PDF / 长文批量制卡作业指导
├── skills/anki-cards/         制卡技能
│   ├── SKILL.md               主指令（官方五段式）
│   ├── references/            按需加载（3 个）
│   └── scripts/anki_add.py    确定性写卡脚本
├── cli/anki_cli.py            Anki 命令行工具
├── css/                       base / cloze / choice（版式样式在这里，不在模板里）
├── templates/                 模板快照（v7-templates.json）
├── deploy/                    部署脚本
└── tools/                     审计 / 评估 / 自检
```

---

## 日常怎么用

### 写一张卡

```bash
python3 ~/.hermes/skills/note-taking/anki-cards/scripts/anki_add.py \
  --deck "30：读过::30.01：书::30.01.01：《纳瓦尔宝典》" \
  --type 句子 \
  --body "欲望就是你跟自己的约定。" \
  --source "《纳瓦尔宝典》" \
  --tags "读书,纳瓦尔宝典"
```

脚本会自动：补齐 7 个字段、由类型推 `自测`、按版式池轮换版式、
**校验牌组是否存在**（写错不会静默建野牌组）。

### 整篇保留（长文不拆）

```bash
... --whole --body "$(cat article.txt)"
```

强制 `paper` 版式、自动打「完整保留」标签、不拦字数。

### 三条体检命令

```bash
# 全局审计（A–K 十一组：数据基线 / 命名 / 牌组树 / 类型 / 自测一致性 /
#           出处 / 选择题可解析 / 模板与 CSS / 真实渲染 / 同步）
sudo /opt/anki-autocards/venv/bin/python tools/audit_system.py

# 技能评估（E1–E10 十个场景、28 条断言，改完技能必跑）
sudo /opt/anki-autocards/venv/bin/python tools/eval_skill.py

# 试车自检（一条命令判断链路断在哪一环）
sudo /opt/anki-autocards/venv/bin/python tools/check_run.py
```

---

## 给 Agent 的话

如果你是接手这个项目的 Agent，按这个顺序读：

1. **`docs/00-总览.md`** —— 全貌
2. **`docs/01-规范.md`** —— 三个笔记类型、字段含义、形式判据
3. **`docs/03-踩坑.md`** —— 前人踩过的坑，能省你几小时
4. **`skills/anki-cards/SKILL.md`** —— 制技能的执行版

**改任何东西之前先跑 `tools/audit_system.py` 和 `tools/eval_skill.py`，
改完再跑一次，两边都 25/25 才算没退化。**

**改数据必须同时改规则 + 加评估** —— 只改数据不修规则，
下一次写入又会把问题造回来（这条是用 137 张卡的代价换来的）。

---

## 许可

MIT。卡片内容、牌组结构属于使用者本人。

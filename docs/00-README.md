# Anki 自动制卡 · 规范与复刻包

> 版本：v7（形式三分）　|　上一版：A（v6.1 四套版式）　|　2026-09-19
> 服务器：服务器 `<服务器IP>`（Debian 13）　|　路径 `/opt/anki-autocards/`

**这一份是唯一真相源。** 改设计改 CSS 改模板，都从这里出发；服务器上跑的东西就是从这里来的。

---

## 目录

| 文件 | 回答什么问题 |
|---|---|
| `01-规范.md` | **这套系统是什么、为什么长这样** —— 三个笔记类型、形式三分、四套版式、CSS 分层 |
| `02-操作.md` | **怎么改 / 怎么部署 / 怎么回滚** —— 路径、命令、备份、验证三数 |
| `03-踩坑.md` | **14 条踩过的坑**，按代价排序 |
| `04-分类体系.md` | **牌组怎么分** —— 六个区、完整树、借鉴了什么、现有卡怎么落进去 |
| `05-命名规范.md` | **编号 / 名字 / emoji / 评级** —— 编号永不回收，名字随便改 |
| `06-Hermes链路.md` | **飞书 → Hermes → Anki 七环** —— 每一环在哪、怎么验、断了怎么查 |
| `css/` | CSS 源（改「美」就改这里） |
| `deploy/` | 部署脚本（把 CSS 和模板写进 collection） |
| `tools/` | 本地渲染器（不连服务器就能看卡片长什么样） |
| `templates/` | 三个笔记类型当前的 qfmt / afmt 快照 |

---

## 三句话讲清这套东西

1. **形式由内容决定**，判断依据只有一个：这段内容**有没有得答**。
   有 → 回忆（先藏后显）；没有 → 通读（正面全展开）。金句、长文、自己的想法都属于后者。
2. **版式只有 4 套**，做精不做多。`kaiwu` 开务 / `gezhi` 格致 / `paper` 纸白 / `memo` 便签。
   一套新版式如果只是换个颜色，那它不配独立存在。
3. **改版式不动卡的身份**。模板 ID 和 `ord` 不变，370 张卡的复习历史一条不丢。

---

## 完整复刻：从零重建这套系统

假设服务器空了，只有这套 `docs/`：

```bash
# 1. 拼 CSS（追加层写在后面，所以它的规则赢）
BASE=$(cat css/base.css)          # 令牌层 + 容器重置 + 骨架 + 4 套版式 + 长文 + .mode-read
CLOZE=$(cat css/cloze.css)        # 挖空追加层
CHOICE=$(cat css/choice.css)      # 选择追加层

#   生活摘录 CSS = base + "\n\n" + cloze + "\n"   → 14,159 字符
#   生活挖空 CSS = 同上
#   生活选择 CSS = base + "\n\n" + choice + "\n"  → 16,244 字符

# 2. 建笔记类型：字段顺序、模板 ID、ord 必须对得上（见 templates/ 快照）
#    生活摘录 7 字段：正文 / 出处 / 我的话 / 类型 / 风格 / 日期 / 自测
#    生活挖空 6 字段：正文 / 出处 / 我的话 / 类型 / 风格 / 日期
#    生活选择 7 字段：正文 / 选项 / 出处 / 我的话 / 类型 / 风格 / 日期

# 3. 写模板 qfmt / afmt（见 templates/ 快照，或 deploy/apply_v7.py 里的 Q / A 常量）

# 4. 刷时间戳 —— 不做这一步手机看不到改动
#    notetypes.mtime_secs = now; usn = -1; col.mod = now
```

`deploy/apply_v7.py` 就是第 1–4 步的可执行版本，读它的注释最快。

---

## 改一个字要动哪些地方

| 想改什么 | 改哪 | 要不要重新部署 |
|---|---|---|
| 颜色 / 字号 / 留白 | `css/base.css` 里的 `.skin-*` | 要（跑部署脚本） |
| 加一套版式 | `css/base.css` 加一段 `.skin-新名字` | 要 |
| 长文排版（表格、列表、链接） | `css/base.css` 的长文区 | 要 |
| 挖空长什么样 | `css/cloze.css` | 要 |
| 选择题长什么样 | `css/choice.css` | 要 |
| 正面背面各显示什么 | `templates/` 快照 / 部署脚本的 Q / A | 要 |
| 哪种内容走哪种形式 | SKILL.md §1.2 + `01-规范.md` §7 | **不用**（只是规则） |

---

## 验证三数（改完必须对得上）

```
notes 3641 / cards 6829 / revlog 2232
```

`revlog` 掉了 = 卡的身份变了 = 复习历史丢了。**这是最硬的红线。**

跑一次全量自检（25 项，含用活模板渲染真卡片）：

```bash
sudo /opt/anki-autocards/venv/bin/python /opt/anki-autocards/docs/deploy/audit_system.py
```

---

## 相关位置

| 什么 | 在哪 |
|---|---|
| collection（工作库） | `/var/lib/anki-autocards/collection.anki2` |
| 同步副本 | `/var/lib/anki-autocards/sync/anki/collection.anki2` |
| CLI | `/opt/anki-autocards/anki_cli.py`（`/opt/anki-autocards/venv/bin/python`） |
| 配置 | `/etc/anki-autocards/config.json` |
| 备份 | `/var/lib/anki-autocards/backups/`（`A/` = v6.1，`B/` = v7） |
| Hermes 技能 | `/home/hermes/.hermes/skills/note-taking/anki-cards/SKILL.md` |
| 本文件 | `/opt/anki-autocards/docs/` |

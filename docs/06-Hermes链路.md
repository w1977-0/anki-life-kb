# 六、Hermes × 飞书链路 · 完整系统

> 版本：v1.0　|　2026-09-20　|　机器：服务器 `<服务器IP>`
> 这一份回答：**一条飞书消息是怎么变成一张卡的，中间哪一环会断，断了怎么查。**

---

## 1. 一张图

```
①  你  ──飞书 DM──▶  ② hermes-gateway（websocket，常驻）
                          │
                     ③ 起一个 agent 回合
                          │
                     ④ 匹配技能 → anki-cards/SKILL.md
                          │
                     ⑤ 调 CLI：anki_cli.py add
                          │
                     ⑥ 写 /var/lib/anki-autocards/collection.anki2
                          │
                     ⑦ 同步 → 127.0.0.1:8080（本机 anki-syncserver）
                          │
                     ⑧ 你的手机 / 电脑 Anki 拉取
```

**①② 是 Hermes 的事，③④ 是模型的事，⑤⑥⑦ 是 Anki 工具的事。**
三段的负责文件完全不同，排障时先定位是哪一段。

---

## 2. 七环 · 在哪 / 怎么验 / 断了什么症状

| # | 环 | 配置 / 文件 | 只读验证 | 断了会怎样 |
|---|---|---|---|---|
| ① | 飞书连接 | `hermes-gateway.service`<br>`config.yaml` → `plugins.enabled: [platforms/feishu]` | `systemctl is-active hermes-gateway`<br>`cat ~/.hermes/gateway_state.json` | 消息石沉大海，你发了没反应 |
| ② | 频道目录 | `~/.hermes/channel_directory.json` | 看里面有没有 DM `oc_ddcb…` | gateway 不知道往哪回 |
| ③ | 起回合 | `~/.hermes/runtime/active_sessions.json`<br>`logs/agent.log` | 日志里有没有非 `mem_trim` 的行 | 收得到但不回 |
| ④ | 技能装载 | `skills/note-taking/anki-cards/SKILL.md`<br>`.skills_prompt_snapshot.json` | `hermes skills list \| grep anki` | 不制卡，当普通聊天回你一句 |
| ⑤ | CLI 权限 | `/etc/anki-autocards/config.json`（`root:hermes 640`） | `sudo -u hermes … notetypes` | 报权限错 / 找不到配置 |
| ⑥ | 写入查重 | `anki_cli.py` → `cmd_add` | `stats` 前后对账 | 缺字段被跳过、重复被跳过 |

### ⑥ 有兜底（2026-09-20 加的）

`add` 现在会**自动修好三类错**，而不是让卡片失败或变白板：

| 出错 | 兜底 |
|---|---|
| 缺字段（含最常见的漏 `自测`） | 补空，不再整张 `failed` |
| `自测` 空 | 按 `类型` 推导（观点/概念/典故 → `自测`） |
| `风格` 无效或空 | 兜底成 `kaiwu` —— **这一条最要紧**，写错卡片会变白板且极难发现 |
| `出处` 空 | 占位「（未标出处）」 |

补了什么会写进返回值的 `repairs` 字段：

```json
"added": [{"index": 0, "note_id": "…", "repairs": [
  "自测：按类型「观点」补为「自测」",
  "风格：paperr → kaiwu",
  "出处：未填 → 占位「（未标出处）」"
]}]
```

**实测过**：故意发一张缺 4 个字段 + `风格: paperr` 的卡 → 成功写入并列出 3 条修补。
补丁脚本 `docs/deploy/patch_cli_autorepair.py`，备份在 `anki_cli.py.bak-autorepair-*`。
| ⑦ | 同步 | `127.0.0.1:8080`（anki-syncserver） | `anki selftest` | 服务器有了，手机看不到 |

**常用整段自检（一条命令覆盖 ⑤⑥⑦）：**

```bash
ANKI="/opt/anki-autocards/venv/bin/python /opt/anki-autocards/anki_cli.py --config /etc/anki-autocards/config.json"
sudo -u hermes $ANKI selftest
```

返回 4 项，全 `true` 才是真的通：

```
collection 可打开      ✅ notes=3641
同步服务器可达         ✅ http://127.0.0.1:8080/
同步方向安全           ✅ required=2（NORMAL_SYNC）
anki 库版本            ✅ 26.9.2
```

> `required` 的含义：`0`不用动 / `1`普通同步 / `2`全量同步 / `3`全量下载 / **`4`全量上传（危险）**。
> CLI 遇到 `4` 会抛 `SafetyError` 直接中止 —— **它保护的是你设备上的进度不被服务器覆盖**。

---

## 3. 现状实测（2026-09-20）

| 环 | 结果 | 证据 |
|---|---|---|
| ① gateway 活着 | ✅ | `active`，PID 307985，v0.21.0 |
| ① 飞书 websocket | ✅ | `feishu.state=connected`，`needs_attention=false` |
| ② 频道目录 | ✅ | DM `oc_ddcb58f40406d97a5ea4ee9369813459` + 2 个 thread |
| ③ 起回合 | ❌ **从未发生过** | 重启后 12 小时，日志只有 `mem_trim` 心跳 |
| ④ 技能装载 | ✅ | `hermes skills list` → `anki-cards … enabled` |
| ⑤ CLI 权限 | ✅ | `sudo -u hermes` 跑 `notetypes/stats/selftest` 全 ok |
| ⑥ 写入 | ✅（我自己验的） | 34 张使用说明卡写入成功，`skipped=0 failed=0` |
| ⑦ 同步 | ✅ | 同步副本 3637→3641 notes，新牌组树已到位 |

### 唯一的硬缺口：③ 从来没有电流

**每个零件都通电，但没有一次真实回合。** 最后一条飞书消息是 31 小时前。

所以现在的状态准确说是：**"装配完成，未试车"**。
⑤⑥⑦ 全绿是我一条条手动验出来的，不是 Hermes 自己跑出来的。

---

## 4. 试车程序（你发指令时，我按这个查）

**先跑这一条**，它把下面 ①②③④ 全查完并直接给结论：

```bash
sudo /opt/anki-autocards/venv/bin/python /opt/anki-autocards/docs/deploy/check_run.py
```

输出长这样：

```
① 收到消息：共 7 条，最新一条 1 分钟前      最近 1 小时有新消息：是
② 起回合：最近 60 分钟里非心跳 23 行
③ 碰到 Anki：日志命中 4 次
④ 写进去了：notes 3641 → 3643（+2）
   最近新增：
     · [30：读过::30.01：书::30.01.01：《纳瓦尔宝典》] 欲望就是你跟自己的约定…
================================================================
结论：✅ 全通。写了 2 张，去 Anki 里看卡片长什么样
================================================================
```

想手动查也行，四步在下面。

你在飞书发一句，比如：

> 记下这段：《纳瓦尔宝典》—— 欲望就是你跟自己的约定：在得到我想要的东西之前，我拒绝快乐。

我按顺序查四件事，任何一件不对就能定位到环：

```bash
# ① 有没有收到？（消息 id 有没有新增）
sudo python3 -c "import json;print(len(json.load(open('/home/hermes/.hermes/feishu_seen_message_ids.json'))['message_ids']))"

# ② 有没有起回合？（非 mem_trim 的行）
sudo grep -v mem_trim /home/hermes/.hermes/logs/agent.log | tail -20

# ③ 有没有碰到 Anki？（这是关键）
sudo grep -icE "anki|制卡|生活摘录" /home/hermes/.hermes/logs/agent.log

# ④ 写进去没有？（notes 有没有 +N）
sudo -u hermes $ANKI stats
```

| ①②③④ | 结论 |
|---|---|
| 收到 / 没起回合 / — / — | 断在 ③：gateway 收到但没派活 |
| 收到 / 起了 / **0 次** / 没增加 | 断在 ④：技能没被匹配上 |
| 收到 / 起了 / 有 / 没增加 | 断在 ⑥：写了但被跳过（看 `skipped` / `failed`） |
| 全通 | 链路成立，去看卡片长什么样 |

---

## 4.5 技能的写法（v4，2026-09-20 重写）

**核心原则：学生没学好是老师没教好。** Flash 档模型不笨，
是我们的教材把 26KB 一次性灌进它脑子里，它找不到重点才去翻文件系统。

### 渐进式披露（Hermes 官方三级加载）

| 层级 | 内容 | 我们的做法 |
|---|---|---|
| L0 索引 | 只有 `{name, description, category}` | description 里写了**正向 + 反向触发** |
| L1 触发 | 完整 SKILL.md | **4,866 字节**（原 26,193，小 81%） |
| L2 按需 | 单个 `references/*.md` | 4 份，用时才读 |

```
anki-cards/
├── SKILL.md              4.9 KB  只做导航和流程（官方五段式）
├── references/           8.2 KB  分类体系 / 命名规范 / 类型与版式 / 排障
└── scripts/anki_add.py   6.9 KB  确定性脚本，不让模型手写 JSON
```

### 官方五段式正文

`## When to Use`（含 Not for）→ `## Procedure`（编号步骤 + 决策树）
→ `## Pitfalls`（已知坑 + 怎么避）→ `## Verification`（怎么确认成功）

### 为什么必须有脚本

手写 heredoc JSON 是最容易出错的地方。脚本把这些**确定性推导**全做了：

- 补 7 个字段、由 `类型` 推 `自测`、按版式池轮换 `风格`
- **校验牌组是否存在**（写错不报错，会静默建野牌组 —— 这条最要紧）
- **出错时返回中文下一步**，让模型能自我纠正，不用去翻文件系统

```bash
python3 /home/hermes/.hermes/skills/note-taking/anki-cards/scripts/anki_add.py \
  --deck "30：读过::30.01：书::30.01.01：《纳瓦尔宝典》" --type 句子 \
  --body "…" --source "《纳瓦尔宝典》" [--note …] [--skin …] [--create-deck] [--dry-run]
```

### 改完技能必须重启 gateway

`sudo systemctl restart hermes-gateway`（详见第 5 节）

---

## 5. 技能是怎么被选中的（改 SKILL.md 必读）

**没有注册表、没有路由表。** Hermes 靠模型读 SKILL.md 的 **`description`** 语义匹配。

所以：
- `description` 写得太窄 → 你说"这段不错"它就接不住
  （v3.0.0 已把触发词扩到 16 个，并加了"查询和维护卡片体系"这类场景）
- **改完 SKILL.md 不需要重启 gateway**
- `.skills_prompt_snapshot.json` 是**变更检测缓存**（path → [mtime_ns, size]），
  记录的大小和文件对不上就会重建 —— **旧没关系，会自愈**

**改 SKILL.md 的三条提醒：**

1. 它是**执行版**，不是规范。规范在 `docs/01`–`05`，SKILL 只写"该怎么做判断"。
2. **牌组名必须跟 `04-分类体系.md` 一致** —— v2 里写的旧牌组今天已经不存在了，
   那一版会把卡塞进空气里。
3. 改完跑一次 `sudo /opt/anki-autocards/venv/bin/python docs/deploy/audit_system.py`。

---

## 6. 护栏（写进 SKILL.md 里了，这里记原因）

`config.yaml` 里 `approvals.mode: 'off'` —— Hermes **可以无人确认直接执行命令**。
这对"写卡"是好事（不然你每条都要点一下），但对"改结构"是危险的。

所以 SKILL.md 里明确要求它**先问再做**：

> 改 CSS / 改模板 / 加字段 / 迁移或删除牌组 / 动 `anki_cli.py` / 动 Hermes 配置

**写入卡片不用问。** 这是增量操作，错了删一张卡的事。

---

## 7. 排障速查

| 症状 | 先看 | 大概率 |
|---|---|---|
| 飞书发了没反应 | `systemctl is-active hermes-gateway` + `gateway_state.json` | ① |
| 回了，但只是聊天 | `hermes skills list \| grep anki` | ④ 技能没匹配 |
| 说做了卡，但 Anki 里没有 | `$ANKI stats` 前后对账 | ⑥ `failed`（常见：少写 `自测` 字段） |
| 说做了 0 张 | 看返回里的 `skipped` | ⑥ 查重命中 —— 正文前 60 字撞了 |
| 服务器有了，手机没有 | `$ANKI selftest` → `required` | ⑦ 手机端也要同步一下 |
| 卡片变白底黑字 | 笔记的 `风格` 字段 | 值不在四套版式里（跑审计会报） |

---

## 8. 相关文件一览

| 什么 | 在哪 |
|---|---|
| 主配置 | `/home/hermes/.hermes/config.yaml` |
| 服务单元 | `/etc/systemd/system/hermes-gateway.service` |
| 频道目录 | `/home/hermes/.hermes/channel_directory.json` |
| 日志 | `/home/hermes/.hermes/logs/{agent,gateway,errors}.log` |
| 技能 | `/home/hermes/.hermes/skills/note-taking/anki-cards/SKILL.md` |
| Anki CLI | `/opt/anki-autocards/anki_cli.py` |
| CLI 配置 | `/etc/anki-autocards/config.json` |
| 工作库 | `/var/lib/anki-autocards/collection.anki2` |
| 同步副本 | `/var/lib/anki-autocards/sync/anki/collection.anki2` |
| 审计脚本 | `/opt/anki-autocards/docs/deploy/audit_system.py` |

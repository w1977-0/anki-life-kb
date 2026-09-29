# Hermes Agent 实际结构说明（现状梳理，只读取证）

> 2026-09-27 · 服务器 服务器 `<服务器IP>` · Hermes Agent **v0.21.5 (2026.9.24) / code_sha e8acdc5f / 安装方式 git / 内嵌 Python 3.11.16**
> 取证方式：只读读取 `config.yaml`、`.env`（只看变量名，值一律省略）、`state.db`（三文件快照/`mode=ro`）、`cron/jobs.json`、`executions.db`、`deliveries.db`、`gateway_state.json`、`channel_directory.json`、`sessions.json`、以及 `hermes-agent/` 源码里的 profile / feishu adapter / tirith / approval 实现。原始输出：本地 `evidence/hc-20260927/round3_S_structure.txt`、`round3_T_routing.txt`、`round3_U_profile.txt`。
> 本文只描述现状，不含结论与建议。

---

## 一、Profile 清单

**实际存在的 profile：1 个，名字叫 `default`。**

证据链（四条，互相独立）：

1. `gateway_state.json`：`"multiplex_standalone_reason": "only one profile exists (nothing to multiplex)"`、`"served_profiles": []`。
2. 物理目录：`/home/hermes/.hermes/` 下**没有 `profiles/` 子目录**。按 `hermes_constants.py:319` 的定义，一个 profile 目录的识别标记是里面含有 `config.yaml / .env / SOUL.md / profile.yaml / auth.json` 这类身份文件（`_PROFILE_IDENTITY_MARKERS`）；这套身份文件当前**直接躺在 HERMES_HOME 根下**，也就是「单 profile 模式下 hermes home 本身就是 profile 根」。
3. 会话表实测：`state.db` 的 `sessions` 表有 `profile_name` 列，`select distinct profile_name from sessions` → **只有 `default` 一个值**（共 16 行会话 / 886 条消息，来源分布 `cli 10 / feishu 5 / oneshot 1`）。
4. 代码里的命名空间注释：`"""Empty/missing → "default" (single namespace for non-multiplexed gateways)."""`。

**这个 profile 负责什么**：它同时承担三件事——(a) 飞书侧的对话与制卡入口（唯一平台适配器 `platforms/feishu`）；(b) 3 个 Wallos 订阅提醒定时任务；(c) 财务侧的 MCP 工具接入（wallos）。它没有按业务拆分成「制卡 profile / 财务 profile / 运维 profile」，全部功能都在这一个 profile 里，靠**技能（skills）+ 触发词**在会话内部区分。

**Hermes 本身支持多 profile，机制是这些**（当前未使用）：`$HERMES_HOME/profiles/<name>/` 各自一套身份文件；删除时不真删而是移到 `profiles/.deleted/<name>` 并留 tombstone（`profile_tombstone_path`）；multiplex 网关按 `source.profile` 给每一轮对话打 profile 标签、共用一个 `state.db` 时用 profile 命名空间隔离话题状态（代码里引用 issue #76423）；`key_profiles_for_chat(platform, chat_id)` 支持「一个群/会话路由到多个 profile」。当前这套机制处于休眠状态。

**标记为废弃但仍留着的物件**（都不是 profile，但属同一类「残留」）：

| 物件 | 位置 | 现状 |
|---|---|---|
| 归档技能集 | `/home/hermes/.hermes/archived-skills/finance-20260907/` | 整个财务技能被移出 `skills/` 后留档 |
| 已删除的定时任务锁 | `/home/hermes/.hermes/cron/.fire-9bfa84fa0703….lock`、`.fire-a8297f7810af….lock`、`.fire-d74da22949df….lock` | 对应 jobId 已不在 `jobs.json` 里，锁文件（0 字节）留在原地，日期 09-07～09-13 |
| 教材备份 | `skills/note-taking/anki-cards/SKILL.md.bak-*` ×12（09-18～09-26，合计约 0.2MB） | 每次改教材留一份 |
| 第二套写卡脚本 | 同目录 `scripts/w_add2.py`（root:root，09-25），与 `scripts/anki_add.py`（hermes，09-26）功能重叠 | 教材指定用 `anki_add.py` |
| 记忆备份 | `memories/MEMORY.md.bak-*` ×3、`USER.md.bak-*` ×2 | 09-16～09-26 |
| 配置自动快照 | `backups/config/config.yaml.good.*` ×4（09-16、09-24） | Hermes 自己写的 |
| 运行时产物 | `runtime/finance/`（支付宝批次 summary、`account_mapping_migration.db`、`finance_imports.db`、`api_client.py`） | 财务批量导入已停用，文件仍在 |
| 旧会话转储 | `sessions/request_dump_2026-09-0*.json`、`session-backups/session-20260918_065747_9c953062-messages.json` | 会话历史现在的主存储是 `state.db`，这些是旧格式落盘件 |

---

## 二、这个 profile 的四类配置分别在哪、装的是什么

| 类别 | 文件 | 大小 / 最后修改 | 内容概要（不抄密钥） |
|---|---|---|---|
| **人设** | `/home/hermes/.hermes/SOUL.md` | 668B / 09-05 15:52（装完就没改过） | Nous Research 出厂英文人设：直接、回答长度匹配问题分量、不客套、不复述请求、不重述已说过的结论、不 narrate 工具调用、不确定就明说、"Agree because it's right, not because the user said it"。另有两份同内容副本：`hermes-agent/SOUL.md`（仓库自带默认）与 `hermes-agent/docker/SOUL.md`（镜像模板） |
| **长期记忆** | `/home/hermes/.hermes/memories/MEMORY.md` | 2377B / 09-26 18:03 | 分段的系统事实清单：① 网关以 hermes 运行 + unit 细节 + cron 存储路径 + `XDG_RUNTIME_DIR` 修复说明 + docker 组成员；② ezBookkeeping 现状（50 账户 / 6283 交易 / 139 分类 / 3 标签 / 1 用户）与 MCP 工具白名单（7 个查询类 + `add_transaction` 带 dry_run）、Wallos MCP 6 工具（含写）；③ 财务规则草案 v0.3（默认只读、写需明确批准、退款保向、余额宝收益算收入等）；④ **制卡：一律走 `scripts/anki_add.py`，绝不手写 JSON、绝不绕过脚本直连 `anki_cli.py add`**。限制由 `memory.memory_char_limit: 6000` 约束，当前用了 2377B |
| **用户信息** | `/home/hermes/.hermes/memories/USER.md` | 1205B / 09-24 13:09 | ① 沟通风格：简练、无填充、简体中文；**诊断类请求一律只读、不写、不泄露密钥/token、状态用「已配置/未配置」表示**（标注为"standing preference，适用于每一次诊断类请求"）；② 三种授权模式相互独立：Hermes / 财务 / 运维——财务会话里发现配置或缺二进制也不许顺手装，要停下来报告，运维动作需用户明说「进入运维模式」并点名对象；③ 身份：姓名、飞书 `open_id`（`ou_84ea9…`）、支付宝账号；④ 用法约定：发内容 +「记下这段/存一下」= 直接做卡，不要反问；知乎长文按主题拆多张卡。上限 `user_char_limit: 2000` |
| **运行配置** | `/home/hermes/.hermes/config.yaml` | 9646B / 09-24 20:49 | `_config_version: 46`，26 个顶层段。与结构相关的：`timezone: Asia/Shanghai`；`model`（见 §五）；`memory`（`memory_enabled: true`、`user_profile_enabled: true`、两个字数上限、`nudge_interval: 10`）；`approvals`（见 §七）；`plugins: {enabled: [platforms/feishu], disabled: []}`；`mcp_servers.wallos`（见 §五）；`platforms.feishu.home_channel`；`agent`（`max_turns: 500`、`reasoning_effort: medium`、`personalities: {}`）；`delegation.max_iterations: 250`；`skills.creation_nudge_interval: 15`；`kanban.review_dispatch: true`；`terminal.backend: local`；`session_reset: {mode: none, idle_minutes: 1440, at_hour: 4}` + `group_sessions_per_user: true`；`telemetry.shared_metrics: {enabled: false, send: false}`；`updates.pre_update_backup: false`；`compression`（阈值 0.5）、`prompt_caching.cache_ttl: 5m`、`tool_loop_guardrails`、`code_execution.timeout: 300`；`security:` 整段为注释（走默认值）；`fallback_model:` 整段为注释 |
| **凭据（环境变量形态）** | `/home/hermes/.hermes/.env` | 27740B / 09-07，权限 600 | 共 **26 个变量名**：飞书接入 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_DOMAIN`、`FEISHU_CONNECTION_MODE`、`FEISHU_HOME_CHANNEL`、`FEISHU_HOME_CHANNEL_THREAD_ID`、`FEISHU_ALLOW_ALL_USERS`、`FEISHU_ALLOWED_USERS`、`FEISHU_GROUP_POLICY`；模型 `HERMES_CUSTOM_API_SILICONFLOW_CN_API_KEY`、`GMI_SERVING_API_KEY`；财务 `WALLOS_API_KEY`、`EZBOOKKEEPING_API_TOKEN`、`EZBOOKKEEPING_MCP_TOKEN`；执行环境 `TERMINAL_ENV/TIMEOUT/LIFETIME_SECONDS/MODAL_IMAGE`；浏览器 `BROWSERBASE_*`、`BROWSER_*`；调试开关 `WEB_/VISION_/MOA_/IMAGE_TOOLS_DEBUG`。**本轮只看变量名，未读取任何值。** |
| **OAuth / 凭据池** | `/home/hermes/.hermes/auth.json` | 687B / 09-07，权限 600 | `{version:1, providers:{}, active_provider:null, credential_pool:{"custom:api.siliconflow.cn": [1 条]}, updated_at:2026-09-07}` → 没有任何 OAuth 型服务商（anthropic/nous/zai 等）接入，凭据池里只有那一条自定义 key |
| **制卡教材** | `/home/hermes/.hermes/skills/note-taking/anki-cards/SKILL.md` | 13708B / 09-26 18:03，MD5 `4bffbc73…` | 与本地 `anki-deploy/skill/SKILL.md` 同 MD5。frontmatter 的 `description` 是**触发词表**（记下这段/做成卡片/加进 Anki/帮我记这个/收藏这段/收了/存一下/摘一下/这段不错/抄下来/留着/记笔记/做成题）+ 负向边界（只想讨论/要解释/要总结就不写卡）+ 一条「本机没有 Obsidian vault，别改用 obsidian 技能」。正文是术语统一表 + 第 0～3 步流程 + 出处与牌组规则 + `--whole` 归属规则；同目录另有 `references/`（牌组与命名等）与 `scripts/`（写卡脚本） |
| **技能库** | `/home/hermes/.hermes/skills/` | 52MB / 20 个子项 | 13 个类目目录（apple、autonomous-ai-agents、creative、devops、email、finance-bookkeeping、media、note-taking、productivity、research、social-media、software-development、web），合计 **61 份 SKILL.md**；`.usage.json.lock` 记录用量 |
| **本地工具与脚本** | `local-tools/` 与 `scripts/` | 6 项 / 4 项 | `local-tools/`：`wallos_mcp.py`(12922B)、`subscription_reminders.py`(9339B)、`configure_hermes_finance.py`、`migrate_wallos_to_canonical_user.py`、`setup_wallos_subscriptions.py`。`scripts/`：`subscription_reminders.py`（与 local-tools 里那份**同名同尺寸 9339B**，即两份副本）+ `subscription_reminders_weekly.py`(229B) + `subscription_reminders_monthly.py`(237B)，后两个是薄壳：`from subscription_reminders import main; main(["--mode","weekly"])` |
| **运行时/状态** | `state.db`(6.8MB)、`cron/`、`kanban.db`(122KB)、`runtime/`、`gateway/`、`state/`、`logs/`(9MB)、`cache/` | — | 见后续小节 |

---

## 三、消息从飞书进来之后怎么路由

**是「一个统一入口再分发」，不是各 profile 各接各的。** 而且当前这个唯一入口连的是**长连接**，不是 webhook。

```
飞书开放平台（应用，app_id 见 .env；FEISHU_CONNECTION_MODE = websocket）
   │  wss://msg-frontier.feishu.cn/ws/v2?fpid=493&aid=552564&device_id=…&access_key=…&service_id=…&ticket=…
   ▼
plugins/platforms/feishu/adapter.py
   SDK 回调（后台线程）adapter.py:1994 → _submit_on_loop(...)
   → _handle_message_event_data(data)            # 2082 行，解析 message 事件
   → thread_id 判定：只有原生 thread_id 才算话题（root_id 每条都有，不作数）  # 2610
   → _handle_message_with_guards(event)           # 2492 行：准入/去重/限流护栏
   → 合成事件通道：评论、会议邀请等走 _dispatch_synthetic_event(thread_id=None)  # 2408/2455
   ▼
gateway 会话路由（真相源 = state.db 的 gateway_routing 表，主键 (scope, session_key)）
   session_key 形如  agent:main:feishu:dm:<chat_id>[:<thread_id>]
   ▼
唯一 profile = default → 技能匹配（SKILL.md 的 description 触发词）→ 制卡 / 财务 / 普通对话
```

关键事实：

1. **入口数量 = 1**。`plugins.enabled` 里只有 `platforms/feishu`，`disabled: []`；`gateway/config_env.py:463` 的注释也写明「一个直连的 adapter 会变成第二个不受管入口」→ 设计上就是单一受管入口。
2. **连接模式**：`.env` 里 `FEISHU_CONNECTION_MODE=websocket`，代码支持 `websocket | webhook` 两种（`adapter.py` 里有 "Supported modes: websocket, webhook"）。因为是长连接，**服务器上不开放任何 webhook 端口**（对外只有 22 与 Cloudflare 段内的 80/443，与此无关）。
3. **路由的真相源是 `state.db`，不是 `sessions.json`**。`sessions/sessions.json` 顶部 `_README` 自述：*"LEGACY MIRROR of the gateway routing index (the primary copy lives in the gateway_routing table in ~/.hermes/state.db)… This is NOT the session list"*。本轮实测 `gateway_routing` 表 **3 行**，`scope` 都是 `/home/hermes/.hermes/sessions`，`session_key` 分别是那条 DM、以及它的两个话题；`entry_json` 里带 `session_id / created_at / updated_at / origin / prev_session_id / suspended / resume_pending / was_auto_reset / total_tokens` 等字段（**条目里没有 profile 字段**，因为单 profile 模式不需要）。
4. **准入与去重**（`_handle_message_with_guards` + `.env`）：`FEISHU_ALLOW_ALL_USERS=false`、`FEISHU_ALLOWED_USERS` 只有一个人（即机主自己的 open_id）、`FEISHU_GROUP_POLICY=disabled`、`FEISHU_DOMAIN=feishu`；去重缓存 `feishu_seen_message_ids.json`（当前 1 条：`om_x100b6449a0c…` → 时间戳）。
5. **投递有账本**：`state.db` 里有 `delivery_obligations` 表（字段含 `obligation_id / session_key / platform / chat_id / thread_id / content / state / attempts / owner_pid / owner_started_at / last_error`），当前 **10 行，state 全部 = delivered，0 条待投递**；`gateway/delivery_ledger.py` 里有一个「♻️ Recovered reply — the gateway restarted during delivery failed, so this may be a duplicate」的重投标记前缀，用于网关重启期间漏投的恢复。
6. **重启循环检测**：`gateway/restart_loop.json` 内容 `{"boots": [1789859008.0008323]}`（一条 boot 记录，对应 09-16 03:03 UTC）。
7. `active_sessions.json` 当前是 `{"entries": []}`、`gateway_state.active_agents=0`、`active_work=null` → 没有并发会话在跑。

---

## 四、定时任务

任务表：`/home/hermes/.hermes/cron/jobs.json`（5151B）。**字段清单里根本没有 `profile` 这一项**（实测 36 个字段名：`id / name / schedule / script / no_agent / deliver / failure_deliver / origin / enabled / state / repeat / last_run_at / last_status / last_error / last_delivery_error / last_delivery_unverified / failure_streak / last_dispatch / next_run_at / model / provider / skills / skill / monitor_* / workdir / enabled_toolsets / context_from / fire_claim / paused_* / created_at / prompt / base_url / *_snapshot`）→ 3 个任务全部属于这个唯一 profile 的 cron 存储，不存在跨 profile 归属。

| 任务 | 频率（`Asia/Shanghai`） | 执行方式 | 已完成次数 | 最近一次 | 失败记录 |
|---|---|---|---|---|---|
| Wallos 飞书订阅提醒 `08f0f1ac393e` | `0 9,13,20 * * *`（每天 9/13/20 点） | `no_agent=true`，跑 `scripts/subscription_reminders.py`，stdout 直投飞书 | 58 | 2026-09-27 09:01:14 +08，`last_dispatch.kind=on_time`（迟到 51.7s） | 历史 1 次（09-22 09:01），`failure_streak=0` |
| Wallos 订阅周汇总 `cefe6ee2c62c` | `0 20 * * 0`（周日 20:00） | 同上，`subscription_reminders_weekly.py`（薄壳 → `--mode weekly`） | 2 | 2026-09-20 20:01:08 +08 | 0 次 |
| Wallos 订阅月汇总 `e4fe4c067a37` | `0 9 1 * *`（每月 1 日 09:00） | 同上，`subscription_reminders_monthly.py` | 2 | 2026-09-07（创建当天手动跑过一次） | 历史 1 次（09-07 15:52，创建瞬间），`failure_streak=0` |

`executions.db` 聚合：`08f0f1ac393e → completed 57 / failed 1`；`cefe6ee2c62c → completed 2`；`e4fe4c067a37 → completed 1 / failed 1`。**两次失败的 error 字段完全相同**：`Restart-safe cron worker dispatch failed: cannot create restart-safe systemd scope for gateway child: systemd-run --user --scope is unavailable`，时间分别是 09-07 与 09-22；`hermes-gateway.service` 在 09-24 16:44 加入 `ExecStartPre` 建 `/run/user/1001` 与 `Environment=XDG_RUNTIME_DIR` 之后未再出现。三个任务 `state` 都是 `scheduled`、`enabled: true`、`paused_at: null`。

调度器活着：`cron/ticker_heartbeat` 与 `cron/ticker_last_success`（各 18B，02:27 UTC 刚刷新）；锁文件 `.tick.lock` 0 字节正常。每轮脚本 stdout 落 `cron/output/<job_id>/<时间戳>.md`（160B 一份，最新 `2026-09-27_09-01-14.md`）。投递记录在 `cron/deliveries.db`（表 `deliveries` + `delivery_tombstones`，7 条 delivered）。`origin` 字段：周/月任务记着 `chat_id=oc_ddcb58…` 与 `user_id=ou_84ea9…`，日任务的 `origin` 为 `null`（投递走 `deliver: feishu` + home_channel）。

---

## 五、飞书群组 / 话题与 profile、消息类型的对应

实测三张表叠加出来的对应关系（`channel_directory.json` + `gateway_routing` + `sessions`）：

| 飞书侧对象 | ID | `channel_directory` 里的 type | session_key | profile | 会话历史 |
|---|---|---|---|---|---|
| DM 主会话（= `home_channel`，也是 `.env` 的 `FEISHU_HOME_CHANNEL`） | `oc_ddcb58f40406d97a5ea4ee9369813459` | `dm`，`thread_id: null` | `agent:main:feishu:dm:oc_ddcb58…` | `default` | `sessions` 表里同一 key 有 **3 条历史记录**（消息数 156 / 140 / 41），当前 `gateway_routing` 指向 `20260918_065747_9c953062`，`updated_at` 09-26 15:07 |
| 该 DM 下的话题 A | thread `omt_19f97dc3f98f9c85` | `dm`，带 `thread_id` | `…:oc_ddcb58…:omt_19f97dc3f98f9c85` | `default` | 10 条消息，最后活动 09-06 |
| 该 DM 下的话题 B | thread `om_x100b66fb1e6074a8b297f4f27286029` | `dm`，带 `thread_id` | `…:oc_ddcb58…:om_x100b66fb…` | `default` | 7 条消息，最后活动 09-06 |

要点：
1. **没有群（group/chat）参与路由**：`FEISHU_GROUP_POLICY=disabled`，`channel_directory` 里全部条目 `type="dm"`，`sessions` 里没有群会话。话题是同一个 DM 里的 thread（飞书「话题/threads」），不是独立群。
2. **对应关系是「会话/话题 → 会话状态隔离」，不是「会话 → 不同 profile」**：三条 session_key 都归 `default`；`thread_id` 只决定上下文历史彼此隔离（`config.yaml` 的 `group_sessions_per_user: true`、话题按 `thread_id` 拼进 session_key）。
3. **话题判定规则写在代码注释里**：只有消息体上原生带 `thread_id` 的才算话题；`root_id` 每条消息都有，不能拿来判话题。
4. **消息类型 ↔ profile 无关，靠触发词分流**：同一条会话里，命中制卡触发词走 anki-cards 技能，问订阅/记账走 wallos MCP 与财务技能，都不命中就是普通对话。非普通消息（文档评论、会议邀请）由 adapter 合成事件后进同一管线，`thread_id=None`。
5. `FEISHU_HOME_CHANNEL_THREAD_ID` 是空值 → home_channel 落在 DM 本体而非某个话题。

---

## 六、模型服务商

- **服务商只有 1 家：SiliconFlow（自定义 OpenAI 兼容端点）**。
  ```
  model:
    default: deepseek-ai/DeepSeek-V4-Flash
    provider: custom
    base_url: https://api.siliconflow.cn/v1
    api_key: ${HER…}      # 引用 .env 里的 HERMES_CUSTOM_API_SILICONFLOW_CN_API_KEY
  custom_providers:
    - name: Api.siliconflow.cn
      base_url: https://api.siliconflow.cn/v1
      key_env: HERMES_CUSTOM_API_SILICONFLOW_CN_API_KEY
      model: deepseek-ai/DeepSeek-V4-Flash
      models: {…}
  ```
- `custom_providers[0].models` 下**枚举了 96 个可选模型**（DeepSeek 系 V4-Flash/V4-Pro/V3.2/V3.1-Terminus/R1 及若干 `Pro/` 档、GLM-5.3/5.2/4.5、Kimi-K2.7-Code/K2.6、Qwen3.5/3.6 全系列、Qwen3-VL/Omni/ASR、MiniMax-M2.5、Nex-N2-Pro、LongCat-2.0、Step-3.5-Flash、Seed-OSS、PaddleOCR-VL、DeepSeek-OCR、bge 系列、Wan2.2/Kolors/Qwen-Image 图像与视频、CosyVoice/SenseVoice/MOSS-TTSD 语音、LoRA/* 档等）。默认值用 `deepseek-ai/DeepSeek-V4-Flash`。
- `fallback_model:` 整段是**注释状态**（模板注释里列了 openrouter / openai-codex / nous / zai / kimi / minimax / bedrock 等可选项）→ 未配置第二服务商。
- `auth.json`：`providers: {}`、`active_provider: null`、`credential_pool` 只有 `custom:api.siliconflow.cn` 一条 → 没有任何 OAuth 型服务商在用。
- 其他与模型相关的配置位置：`agent.reasoning_effort: medium`、`agent.max_turns: 500`、`agent.service_tier: ''`、`prompt_caching.cache_ttl: 5m`、`compression.*`、`stt`（local `model: base` / openai `whisper-1`）。`.env` 里另有 `GMI_SERVING_API_KEY`（已配置，未出现在 `config.yaml` 的服务商段里）。
- 目录缓存：`cache/model_catalog.json`、`cache/openrouter_curated_catalog.json`、`cache/nous_recommended_cache.json`、`cache/reasoning_caps.json`、`models_dev_cache.json` —— 是拉取到的模型目录缓存，不代表已启用这些服务商。
- MCP 只注册了 1 个服务器：`mcp_servers.wallos`（`command: hermes-agent/venv/bin/python`，`args: [local-tools/wallos_mcp.py]`，`env: WALLOS_BASE_URL=http://127.0.0.1:8282 / WALLOS_API_KEY=${WALLOS_API_KEY}`，`enabled: true`、`trust: full`、`supports_parallel_tool_calls: false`，`tools.include` 白名单 6 个：`list_subscriptions / get_subscription / get_reference_data / add_subscription / edit_subscription / deactivate_subscription`）。`config.yaml` 里**没有 ezBookkeeping 的 mcp_servers 条目**，但 `.env` 里存在 `EZBOOKKEEPING_API_TOKEN` 与 `EZBOOKKEEPING_MCP_TOKEN`（已配置），`MEMORY.md` 里也仍写着「MCP tools whitelisted (7): query_transactions…」。
- 执行侧：`terminal.backend: local`（`container_*` 那几项是 docker 后端的参数，当前后端不是 docker）、`code_execution.timeout: 300`、`delegation.max_iterations: 250`、`tool_loop_guardrails`（warn 阈值 exact_failure 2 / same_tool_failure 3 / idempotent_no_progress 2；hard_stop 5/8/5，`hard_stop_enabled: false`、`non_interactive_hard_stop_enabled: true`）。

---

## 七、待审批类机制与当前积压

配置（`config.yaml` 第 101–105 行）：
```
approvals:
  mode: 'off'                    # 交互式（飞书对话）执行不做人工确认
  cron_mode: approve             # 定时任务场景要审批
  unattended_mode: approve       # 无人值守场景要审批
  destructive_slash_confirm: false
```
代码侧的语义（`tools/approval.py`）：`mode: off` 与 `/yolo` 一样属于 **bypass 源**（`_YOLO_MODE_FROZEN or is_session_yolo_enabled(session_key) or approval_co…`）；`cron` 场景走 `cron_mode`，注释原文 "cron jobs run without a user present to approve it"；需要审批时返回的是**在-band 的 `pending_approval` 结构**（`{"approved": False, "pattern_key": …, "status": "pending_approval"}`），不是持久化队列。`security.tirith_*` 默认值在 `tools/tirith_security.py`（`tirith_enabled` 默认 true、`tirith_path` 默认 `"tirith"`、解析顺序「PATH → `$HERMES_HOME/bin/tirith`」、`tirith_fail_open` 默认 true、连续启动失败会开熔断）。

当前积压（全部实测）：

| 队列 | 位置 | 数量 |
|---|---|---|
| 待审批消息 | `/home/hermes/.hermes/pending_messages/` | **0 个文件**（目录存在，空） |
| 看板待评审任务 | `kanban.db`（`tasks` / `task_runs`） | **0 行 / 0 行**（`kanban/.dispatcher.lock` 是唯一内容物） |
| 待投递义务 | `state.db:delivery_obligations` | 10 行，`state` 全为 `delivered`，**0 条待投** |
| 活跃/挂起会话 | `runtime/active_sessions.json`、`gateway_routing.suspended` | `entries: []`，无挂起会话 |
| 审批请求本身 | 进程内存（`pending_approval` 返回值） | `approvals.mode=off` → 交互式不产生审批请求 |

**记忆写入这一类没有人工确认环节**：`memory.nudge_interval: 10`、`skills.creation_nudge_interval: 15` 是「到点自动写记忆/自动提议技能」的阈值，`MEMORY.md`/`USER.md` 由进程直接改写（这也是为什么 `memories/` 下留了 3 份 `.bak`），没有「新记忆待人工确认才生效」的队列。

---

## 八、「制作卡片」这条链路

**触发**：飞书消息命中 `SKILL.md` frontmatter 的触发词表（见 §二），且带着内容；`USER.md` 里另有一条「发内容 +『记下这段/存一下』= 直接做卡，别反问」。

**生成（SKILL 规定的 4 步，前 3 步是判断，第 4 步是确定性脚本）**：
1. 第 0 步 自检（只读，每次开工一次）；
2. 第 1 步 判类型（十个类型值：句子/典故/概念/观点/感悟/方法/场景/事件/里程碑/长文）；第 1.5 步 写**真出处**（占位符会被脚本拦，兜底 `网络` → 牌组 `30.05：网络碎片`；书名不进内容，牌组即书名）；
3. 第 2 步 定牌组（跑 `$ANKI decks --all` 核实编号，同出处只进一个牌组）；
4. 第 3 步 写卡：**必须** `python3 /home/hermes/.hermes/skills/note-taking/anki-cards/scripts/anki_add.py`（14411B），脚本内 `subprocess` 调 `/opt/anki-autocards/anki_cli.py`，`timeout=180`，错误全部中文打到 stdout。日期回填、类型→自测、版式池轮换、牌组存在性、查重都在脚本里做，`MEMORY.md` 明令「绝不手写 JSON、绝不绕过脚本直连 `anki_cli.py add`」。

**卡片数据最后落在哪（不是直接写进同步服务器的数据目录）**：
```
anki_cli.py
  读 /etc/anki-autocards/config.json → collection / endpoint / username / password / backup_dir / lock_file / backup_keep(20)
  Collection(cfg["collection"]) = /var/lib/anki-autocards/collection.anki2   ← 写入的是这里（工作库，0600 hermes:hermes）
  cmd_add:  pre = sess.sync(allow_full_download=False)   # 写前先同步一次
            add_note(...)                                 # 官方 API 写入
            post = sess.sync(allow_full_download=False)   # 写完再同步一次
  sess.sync → col.sync_collection(auth) → endpoint = http://127.0.0.1:8080（systemd 服务 anki-syncserver 进程持有）
                     │
                     ▼
        /var/lib/anki-autocards/sync/anki/  ← 同步服务器的数据目录（工作库的增量副本 + media.db + media/）
                     │
                     ▼  设备侧 https://anki.example.com（Cloudflare 隧道回注到 127.0.0.1:8080）
              手机 / 桌面 Anki
```
要点：**卡片先写工作库，再由 anki 官方同步协议增量落到同步服务器的数据目录**，两张库是「同一份逻辑库的两个物理文件」；`required=FULL_SYNC/FULL_DOWNLOAD` 时脚本抛 `SafetyError` 中止，`FULL_UPLOAD` 永不允许（14 天日志里 SAFETY_ABORT/FULL_UPLOAD 命中 0 次）。当前实测两库一致：`notes=7044 / cards=10232`，工作库与副本 `mtime` 相差 2 秒（09-26 18:15:46 / 18:15:48 UTC）。

**周边落点**：媒体写 `sync/anki/media/`（7627 个文件 / 286,696,785 字节）并登记 `media.db`；`anki_cli.py` 还有个 `online_backup(col_path, backup_dir, keep)`（`backup_keep: 20`）会在同步前做在线备份；批量导入类项目走本地脚本 → 推 JSON → 服务器上的幂等导入脚本。近 7 天网关日志里 `anki_add.py` / `anki_cli.py add` 的调用计数是 **2**（活动量很低，与 notes 增长吻合）。

---

## 九、整体结构关系

```
                     ┌──────────────────────────────────────────────────────────┐
                     │  systemd: hermes-gateway.service（User=hermes，Restart=always）│
                     │  /home/hermes/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run │
                     │  ├─ plugins/platforms/feishu  ← 唯一入口，websocket 长连接        │
                     │  ├─ local-tools/wallos_mcp.py（MCP 子进程）                     │
                     │  └─ tools/mcp_death_supervisor.py（子进程监管）                  │
                     └───────────────┬──────────────────────────────────────────┘
                                     │ HERMES_HOME=/home/hermes/.hermes
        ┌────────────────────────────┼───────────────────────────────────────────────┐
        │ 身份层（1 个 profile = default，身份文件直接放在 home 根）                     │
        │   SOUL.md（人设） · memories/MEMORY.md（系统记忆） · memories/USER.md（用户画像+授权规则） │
        │   config.yaml（26 段运行配置） · .env（26 个变量：飞书/模型/财务/终端） · auth.json（凭据池 1 条） │
        ├─────────────────────────────────────────────────────────────────────────────┤
        │ 能力层   skills/（13 类目 / 61 份 SKILL.md）                                  │
        │          └ note-taking/anki-cards/：SKILL.md（触发词+4 步流程）+ references/ + scripts/anki_add.py │
        │          archived-skills/finance-20260907/（废弃留档） · plugins 只启用 feishu  │
        │          mcp_servers.wallos → 127.0.0.1:8282（Wallos 容器）                    │
        │          tools/tirith（$HERMES_HOME/bin/tirith 0.4.1，默认启用路径）            │
        ├─────────────────────────────────────────────────────────────────────────────┤
        │ 状态层   state.db 6.8MB：sessions(16 行，profile_name 全为 default) / messages(886) │
        │          gateway_routing(3 行 = 当前会话指针) / delivery_obligations(10 delivered) │
        │          hosted_rooms* / async_delegations / gateway_heartbeats / messages_fts* │
        │          sessions.json = 旧镜像（README 自称 legacy mirror） · channel_directory.json = 频道清单 │
        │          cron/：jobs.json(3) + executions.db(60✓/2✗) + deliveries.db + ticker_* │
        │          kanban.db(0 任务) · pending_messages(空) · runtime/ · gateway/restart_loop.json │
        ├─────────────────────────────────────────────────────────────────────────────┤
        │ 模型层   唯一服务商 SiliconFlow（api.siliconflow.cn/v1），默认 DeepSeek-V4-Flash， │
        │          枚举 96 个可选模型；fallback_model 未启用；key 在 .env，由 key_env 引用   │
        ├─────────────────────────────────────────────────────────────────────────────┤
        │ 产出层（与 Anki 的接缝）                                                      │
        │   anki_add.py → anki_cli.py →（写）/var/lib/anki-autocards/collection.anki2    │
        │                  └→（sync）→ anki-syncserver @127.0.0.1:8080 → sync/anki/ 副本 + media.db/media │
        │                                    └→ 设备经 https://anki.example.com（Cloudflare 隧道）同步 │
        │   财务产出：wallos / ezBookkeeping 容器与 /srv/personal-finance（与本 profile 分离的另一套服务）│
        └─────────────────────────────────────────────────────────────────────────────┘
```

三条关系概括：**入口只有一个**（飞书 websocket 长连接 → 单一 profile → 触发词分流到技能），**状态只有一个库**（`state.db`，`sessions.json` 与 `channel_directory.json` 只是镜像与清单），**产出分两条**（对话产出回飞书；制卡产出写工作库再经同步协议到同步服务器目录，最后被设备拉走）。profile 的多路复用机制在代码与目录约定里齐备，但当前这台机器上只实例化了 `default` 一个，会话与话题只用于隔离上下文，不用于区分 profile。

---

## 附：本轮对上一版描述的三处修正

1. `tirith` 不是「未安装」——它在 `$HERMES_HOME/bin/tirith`（39MB ELF，`tirith 0.4.1`，可执行），且代码解析顺序是「PATH → `$HERMES_HOME/bin`」，默认配置即启用；但 14 天日志里 0 条 tirith 记录，无法证明它实际拦过命令。
2. 会话/路由的真相源是 `state.db` 的 `gateway_routing` 表（`sessions.json` 自己声明是 legacy mirror，且明确 "This is NOT the session list"），上一版把 `channel_directory.json`/`sessions.json` 说得过像主存储。
3. profile 归属不是靠 jobs.json 或 entry_json 的字段体现的：`jobs.json` 里**根本没有 `profile` 字段**，`gateway_routing.entry_json` 里也没有；profile 名字唯一的实测来源是 `sessions.profile_name` 列（全为 `default`）与 `gateway_state.multiplex_standalone_reason`。
4. SiliconFlow 的可选模型数是 **96**，上一版口述成「17 个」（当时只看了清单前 15 行）。

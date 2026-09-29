# 变更实录 · Hermes 多服务商接入（OpenRouter + TokenFlux）

> 2026-09-27 16:29–16:51（北京时间）　|　执行人：Qoder agent（用户指令「你来安排」）
> 目的：解决「一家 API 没钱了要换厂商，但不想 SSH」。

## 一、改了什么

**`.env`（600 hermes:hermes）新增两个变量**（值不记录在此）：
- `OPENROUTER_API_KEY` —— OpenRouter 原生服务商用的标准变量名
- `HERMES_CUSTOM_API_TOKENFLUX_DEV_API_KEY` —— 自定义服务商的 `key_env` 指向它

**`config.yaml`（600）新增三段**：

```yaml
custom_providers:
  - name: Api.siliconflow.cn          # 原有，未动
    ...
  - name: Api.tokenflux.dev           # 新增
    base_url: https://tokenflux.dev/v1
    key_env: HERMES_CUSTOM_API_TOKENFLUX_DEV_API_KEY
    model: deepseek-flash
    models:
      deepseek-flash: {}

model_aliases:                        # 新增：飞书里 /model <短名> 直接换厂商
  sf:      {model: deepseek-ai/DeepSeek-V4-Flash, provider: "custom:Api.siliconflow.cn"}
  or:      {model: nvidia/nemotron-3-ultra-550b-a55b:free, provider: openrouter}
  orpaid:  {model: deepseek/deepseek-v4.1-flash, provider: openrouter}   # 需充值后才能用
  tf:      {model: deepseek-flash, provider: "custom:Api.tokenflux.dev"}

fallback_providers:                   # 新增：主链失败时自动接管
  - provider: openrouter
    model: nvidia/nemotron-3-ultra-550b-a55b:free
```

**默认主服务商没动**：仍是 SiliconFlow 的 `deepseek-ai/DeepSeek-V4-Flash`。

**执行过的服务操作**：`systemctl restart hermes-gateway` 一次（08:35:55 UTC）——新 key 是启动时由 `load_hermes_dotenv` 加载的，不重启读不到。**实测停机到飞书重连 = 94 秒**（08:35:43 断连 → 08:37:17 重连；中间 08:36:42 有一次 `feishu connect timed out after 30s` + `Gateway started with no connected platforms`，与体检报告里记的冷启动现象一致）。

## 二、为什么这么配（两个关键事实）

1. **OpenRouter 这把 key 余额为 0**（`/api/v1/credits` → `total_credits: 0`，`is_free_tier: true`，免费模型 50 次/天）。所以容灾链**不能**指向付费模型 `deepseek/deepseek-v4.1-flash`（第一版我这么写了，是错的，已改），必须指向支持工具调用的 `:free` 模型。实测可用：`nvidia/nemotron-3-ultra-550b-a55b:free`（550B、1M 上下文、`supported_parameters` 含 `tools`），调用成功。OpenRouter 上「免费 + 支持 tools」的模型共 390 个候选中的 10 个左右，DeepSeek 系**没有免费档**。
2. **TokenFlux 有钱但身份存疑**：`/v1/usage` 返回 `balance ≈ 97.71`、`mode: auto`；站名 "tokenflux - AI API Gateway"，SPA 无正文，走 Caddy + Cloudflare，响应头带 `x-codex-primary-used-percent` 这类 Codex 配额字段（像转售 Codex/订阅额度）。**因此故意没有把它放进 `fallback_providers`**——自动容灾意味着你的对话内容会在你不知情时被送到那里。它只作为手动别名 `tf` 存在，你要用就明说 `/model tf`。要放进自动链，请明确告诉我。

## 三、验证结果（全部实测）

| 项 | 结果 |
|---|---|
| `hermes fallback list` | Primary SiliconFlow → Fallback `nvidia/nemotron-3-ultra-550b-a55b:free (openrouter)` ✅ |
| 别名端到端（`hermes chat -q`，真实请求） | `or` ✅「通了」42s；`tf` ✅「通了」；`sf` ✅「通了」（无 fallback 告警） |
| 容灾链是否真的生效 | ✅ 现场验证过一次：`tf` 首次（别名写错时）认证失败，Hermes 自动改用 OpenRouter 免费模型把回答给出 |
| 服务与飞书 | `hermes-gateway / anki-syncserver / cloudflared` 全 active；`gateway_state.feishu = connected`、`needs_attention = False` |
| 意外收获 | 重启后释放了被换出的页，可用内存从 221MB 升到 **327MB** |

## 四、以后怎么用（全在飞书里，不用 SSH）

- 换厂商/换模型：`/model tf`、`/model or`、`/model sf`（只影响当前会话）；加 `--global` 才写回默认。
- 看余额：`/usage`（服务商支持时会显示 Account limits）。OpenRouter 免费档的用量在 `GET /api/v1/key` 的 `free_model_daily_requests` 里，TokenFlux 在 `GET /v1/usage` 的 `balance`。
- 主链挂了会自动跳到 OpenRouter 免费模型（50 次/天，用完就没了——真要当备胎，OpenRouter 需要充值）。
- 再来一家活动厂商：`.env` 加一个 `HERMES_CUSTOM_API_<名>_API_KEY`，`config.yaml` 的 `custom_providers` 加一条 + `model_aliases` 加一个短名，然后重启一次网关（或在飞书里让我做）。

## 五、回滚

```bash
# 备份都在 /home/hermes/.hermes/backups/config/ 下，按时间戳选：
#   config.yaml.pre-provider-20260927-082910Z   ← 接入两家之前的原始 config
#   env.pre-provider-20260927-082910Z           ← 加 key 之前的 .env
#   config.yaml.pre-freefix-20260927-083537Z / config.yaml.tfalias-<ts>  ← 中间态
sudo cp -a /home/hermes/.hermes/backups/config/config.yaml.pre-provider-20260927-082910Z /home/hermes/.hermes/config.yaml
sudo cp -a /home/hermes/.hermes/backups/config/env.pre-provider-20260927-082910Z /home/hermes/.hermes/.env
sudo systemctl restart hermes-gateway
```

## 六、两条值得进踩坑清单的经验

1. **多个自定义服务商时，`provider` 必须写成 `custom:<name>`**。裸 `provider: custom` 只会命中 `custom_providers` 的第一条——我第一版 `tf` 写成 `provider: custom` + `base_url`，结果 Hermes 拿 TokenFlux 的 key 去请求 SiliconFlow 的地址，报 authentication failed。代码依据：`agent/agent_init.py:158` 返回 `{normalized, f"custom:{normalized}"}`，`agent/auxiliary_client.py` 注释「KEEP the full `custom:<name>` so the named arm honours the entry's …」。`model_aliases` 里的 `base_url` 字段不能替代这个限定。
2. **`hermes config set` 只能写标量**，`custom_providers` / `model_aliases` / `fallback_providers` 这类列表结构必须手改 YAML（`hermes fallback add` 是交互式选择器，非交互场景用不了）。改完用 `python3 -c "import yaml; yaml.safe_load(...)"` + `hermes fallback list` 双重校验，改前必备份（Hermes 自己也会在启动时写 `config.yaml.good.<ts>`，可作为额外兜底）。

## 七、二次复核（16:52–17:02 北京时间，独立复查我自己那次变更）

| 复核项 | 结果 |
|---|---|
| `.env` 追加是否安全 | ✅ 26→28 个变量、550→552 行；最后三行各自独立成行（原最后一个变量 `HERMES_CUSTOM_API_SILICONFLOW_CN_API_KEY` 完好）；无"一行两键"、无非规范行；`.env` 与两份备份均 600 hermes:hermes |
| `config.yaml` 结构 | ✅ diff 纯增量；顶层键无重复（`model_aliases`/`fallback_providers`/`custom_providers` 各 1 次）；`model.default` 未动；四个别名解析为 `sf→custom:Api.siliconflow.cn`、`or/orpaid→openrouter`、`tf→custom:Api.tokenflux.dev` |
| Hermes 是否接受这份配置 | ✅ 它自己在 08:48:53 又写了 `config.yaml.good.20260927-084853`（启动校验通过才会写） |
| **发现的问题** | ❌ **别名修复（08:48:50）晚于第一次重启（08:35:55）**，而 `cli.py` 里明写 config 是 "process-lifetime cache; config is read once" → 运行中的网关可能仍揣着旧 `tf` 映射，`/model tf` 有静默回落到 OpenRouter 的风险 |
| 处理 | 已做**第二次重启**（09:00:30 UTC），飞书 **63 秒**重连（这次没出现 `connect timed out` / `no connected platforms`）；现在进程启动时间 09:00:30 > 配置 mtime 08:48:50，进程与磁盘一致 |
| 停机窗口是否吞消息 | ✅ 两次重启窗口内 journal 无任何入站事件；`delivery_obligations` 10 行全 `delivered`、0 条待投；`active_work: null`、`restart_requested: false` |
| 副作用清点 | 我今天新增 6 条 `oneshot` 会话（`20260927_0841xx`–`0849xx`，都是 `hermes chat -q` 验证留下的，2 条消息/行）；OpenRouter 免费额度已用 6/50；TokenFlux 余额从 97.71 降到 97.60（测试消耗）；服务器上没有我留下的临时脚本（`/tmp/orig_excerpt.json` 是 09-19 的旧文件，不是本次产生） |
| 两次重启的实测停机 | 第一次 94 秒（含一次 30s 连接超时）、第二次 63 秒 → 印证体检报告 🟡-1：冷启动窗口不稳定，**能不重启就不重启，必须重启时预留 ≥2 分钟静默** |

**仍待你确认的两件事**：① TokenFlux 要不要进自动容灾链（现在只有手动 `/model tf`）；② OpenRouter 只有免费档 50 次/天，要不要充值，否则主链挂了它撑不了几下。

**最后一次实测请你亲手做**（这是我在服务器侧无法替走的最后一步）：在飞书里发 `/model tf` 再随便问一句，我看 journal 里那一轮实际落在哪个 provider —— 只有真实走一遍消息链路，才能证明"磁盘配置 = 运行态 = 你的体验"三者一致。

## 八、遗留与提醒

- **两把 key 曾以明文出现在这个对话里**。服务器上它们只落在 `.env`（600）与 `backups/config/env.pre-*`（600），没有进任何文档或 git。若这个会话有同步到云端，建议在服务商侧各轮换一次。
- 体检报告（docs/17、docs/18）里那条 🔴「Hermes 运行态无自动备份」仍然成立——这次改配置我是手工备份的。
- 我为了端到端验证跑了 4 次 `hermes chat -q`，会在 `hermes sessions list` / `/sessions` 里留下几条一次性 CLI 会话，无害，想清可以删。
- OpenRouter 免费档 50 次/天已被这次验证用掉 3 次（`used: 3, remaining: 47`）。

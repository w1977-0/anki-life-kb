#!/bin/bash
#
# 02-status-page.sh — 部署 Anki 同步服务器状态页
#
# 为什么需要它：
#   Anki 同步接口没有网页界面，浏览器打开 https://anki.example.com/ 只会得到 404。
#   这导致「服务器到底活着没有」变成一个看不见的问题，反复消耗沟通成本。
#   这个状态页专门回答那个问题。
#
# 安全设计：
#   - 只监听 127.0.0.1:8099，不直接暴露
#   - 完全只读：不写任何文件
#   - 与同步服务器完全隔离：不碰 8080，同步链路零影响
#   - 即使这个服务挂了，同步照常工作
#
# 幂等：可重复执行。
#
# 用法：sudo bash 02-status-page.sh
#
set -euo pipefail

ANKI_ROOT="${ANKI_ROOT:-/opt/anki-autocards}"
ANKI_USER="${ANKI_USER:-hermes}"
STATUS_PORT="${STATUS_PORT:-8099}"
PY_BIN="${PY_BIN:-/usr/bin/python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${ANKI_ROOT}/status_page.py"
UNIT="/etc/systemd/system/anki-status.service"

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$C_OK" "$1" "$C_OFF"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    %s%s%s\n' "$C_WARN" "$1" "$C_OFF"; }
die()  { printf '\n%s!!  %s%s\n' "$C_ERR" "$1" "$C_OFF" >&2; exit 1; }

# ---------------------------------------------------------------- 0. 前置检查

step "0/4  前置检查"

[[ $EUID -eq 0 ]] || die "需要 root 权限运行（sudo bash $0）"
[[ "$ANKI_ROOT" == /opt/* ]] || die "ANKI_ROOT 必须是 /opt 下的路径（当前：$ANKI_ROOT）"
id "$ANKI_USER" &>/dev/null || die "用户 $ANKI_USER 不存在"
[[ -x "$PY_BIN" ]] || die "找不到 python3：$PY_BIN"
[[ -f "${SCRIPT_DIR}/status_page.py" ]] || die "找不到 ${SCRIPT_DIR}/status_page.py"

info "目标用户：$ANKI_USER"
info "Python  ：$("$PY_BIN" --version 2>&1)"

if ss -tlnp 2>/dev/null | grep -q ":${STATUS_PORT} "; then
  HOLDER=$(ss -tlnpH "sport = :${STATUS_PORT}" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  SVC_PID=$(systemctl show -p MainPID --value anki-status.service 2>/dev/null || echo "")
  if [[ -n "$SVC_PID" && "$SVC_PID" == "$HOLDER" ]]; then
    info "端口 ${STATUS_PORT} 由本服务占用 —— 幂等重跑，正常"
  else
    die "端口 ${STATUS_PORT} 被其他进程 (pid ${HOLDER}) 占用"
  fi
else
  info "端口 ${STATUS_PORT} 空闲"
fi

# ---------------------------------------------------------------- 1. 安装脚本

step "1/4  安装状态页脚本"

install -m 0755 -o root -g root "${SCRIPT_DIR}/status_page.py" "$TARGET"
info "$TARGET"

"$PY_BIN" -m py_compile "$TARGET" || die "脚本语法错误"
info "语法检查通过"

# ---------------------------------------------------------------- 2. systemd

step "2/4  注册 systemd 服务"

cat > "$UNIT" <<UNITEOF
[Unit]
Description=Anki sync server status page (read-only, loopback only)
Documentation=file:${TARGET}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${ANKI_USER}
Group=${ANKI_USER}
ExecStart=${PY_BIN} ${TARGET}
Restart=on-failure
RestartSec=5

# 这台机器总共只有 964 MB
MemoryMax=64M
MemoryHigh=48M

# 加固：它只需要读
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable anki-status.service >/dev/null
info "服务已注册并设为开机自启（内存上限 64 MB）"

# ---------------------------------------------------------------- 3. 启动

step "3/4  启动服务"

systemctl restart anki-status.service
sleep 2

if ! systemctl is-active --quiet anki-status.service; then
  journalctl -u anki-status.service -n 30 --no-pager
  die "状态页启动失败，日志见上"
fi
info "anki-status 状态：active"
printf '    %-18s %s\n' "监听端口" "$(ss -tlnp 2>/dev/null | grep ":${STATUS_PORT} " | head -1 | awk '{print $4}')"
printf '    %-18s %s\n' "服务内存" "$(systemctl show anki-status.service -p MemoryCurrent --value | awk '{printf "%.1f MB", $1/1024/1024}')"

# ---------------------------------------------------------------- 4. 验收

step "4/4  验收"

printf '    %-26s %s\n' "GET /status" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "http://127.0.0.1:${STATUS_PORT}/status")"
printf '    %-26s %s\n' "GET /healthz" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "http://127.0.0.1:${STATUS_PORT}/healthz")"
printf '    %-26s %s\n' "GET /healthz 内容" "$(curl -s --max-time 6 "http://127.0.0.1:${STATUS_PORT}/healthz")"

echo ""
info "页面关键内容抽查："
curl -s --max-time 6 "http://127.0.0.1:${STATUS_PORT}/status" | grep -oE "服务器运行中|同步服务未响应|检查时间|已同步内容" | sort -u | sed 's/^/      /'

echo ""
info "确认同步服务器未受影响："
printf '    %-26s %s\n' "anki-syncserver" "$(systemctl is-active anki-syncserver.service)"
printf '    %-26s %s\n' "8080 端口" "$(ss -tlnp | grep -c ':8080 ')"

cat <<'NEXTEOF'

================================================================
状态页部署完成。

接下来需要人工完成两件事（这是两个不同的页面，漏掉第二步就会 NXDOMAIN）：

  第一步 · 加路由（Zero Trust）
    Zero Trust → Networks → Tunnels → （你的隧道）→ Public Hostnames
    → Add a public hostname

      Subdomain : anki-status
      Domain    : example.com
      Type      : HTTP
      URL       : 127.0.0.1:8099

  第二步 · 加 DNS 记录（DNS 页面，不是隧道页面）
    主站 → example.com → DNS → Records → Add record

      Type    : CNAME
      Name    : anki-status
      Target  : <tunnel-id>.cfargotunnel.com
      Proxy   : 已代理（橙色云）

    Target 里的 tunnel-id 在隧道页面的 Overview 里能看到。
    如果提示 "A record with that host already exists"，说明已经加过了，不用管。

  保存后访问：https://anki-status.example.com/

注意：
  - 不要挂 Cloudflare Access
  - 这条路由与同步链路完全隔离，加错了也不会影响 anki.example.com
  - 用独立子域名而不是路径（/status），因为 CF 隧道会把完整路径
    透传给后端，同域名下加路径还有路由抢占风险
  - DNS 记录建好之后，全球生效可能要十几分钟。刚建完立刻 dig 到
    NXDOMAIN 是正常现象，不代表没配上

回滚：
  sudo systemctl disable --now anki-status.service
  sudo rm /etc/systemd/system/anki-status.service
================================================================
NEXTEOF

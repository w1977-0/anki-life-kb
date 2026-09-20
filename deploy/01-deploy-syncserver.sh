#!/bin/bash
#
# 01-deploy.sh — 部署 Anki 自动制卡栈（飞书 → Hermes → Anki）
#
# 目标机：服务器 服务器 (<服务器IP> / <SSH用户> / Debian 13)
#
# 这个脚本做四件事：
#   1. 建独立 venv 装 anki 库（不碰系统 Python）
#   2. 部署 anki.syncserver 为 systemd 服务（127.0.0.1:8080）
#   3. 安装 anki-cli 制卡工具
#   4. 把制卡 skill 装进 Hermes
#
# 幂等：可重复执行。已存在的配置、数据、collection 都不会被覆盖。
#
# 用法：
#   sudo bash 01-deploy.sh
#
# 前置条件：
#   - 已由用户明确进入运维模式
#   - 磁盘可用 > 1 GB（实际约需 150 MB）
#   - 内存可用 > 250 MB，否则建议先停 Hermes
#
# 未包含（需人工）：
#   - Cloudflare Dashboard 加路由 anki.example.com -> 127.0.0.1:8080（不加 Access）
#   - 用户设备改同步地址
#   - 首次数据迁移（官方客户端 full-upload 到自建服务器）
#
set -euo pipefail

# ---------------------------------------------------------------- 配置

ANKI_ROOT="${ANKI_ROOT:-/opt/anki-autocards}"
ANKI_DATA="${ANKI_DATA:-/var/lib/anki-autocards}"
ANKI_ETC="${ANKI_ETC:-/etc/anki-autocards}"
ANKI_USER="${ANKI_USER:-hermes}"
HERMES_HOME="${HERMES_HOME:-/home/${ANKI_USER}/.hermes}"
SYNC_PORT="${SYNC_PORT:-8080}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_BIN="${ANKI_ROOT}/venv/bin/python"
CLI="${ANKI_ROOT}/anki_cli.py"
CONF="${ANKI_ETC}/config.json"
SYNC_ENV="${ANKI_ETC}/syncserver.env"

# ---------------------------------------------------------------- 输出

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$C_OK" "$1" "$C_OFF"; }
info() { printf '    %s\n' "$1"; }
warn() { printf '    %s%s%s\n' "$C_WARN" "$1" "$C_OFF"; }
die()  { printf '\n%s!!  %s%s\n' "$C_ERR" "$1" "$C_OFF" >&2; exit 1; }

# ---------------------------------------------------------------- 0. 前置检查

step "0/8  前置检查"

[[ $EUID -eq 0 ]] || die "需要 root 权限运行（sudo bash $0）"

# 路径护栏：脚本内部会对 $ANKI_ROOT/venv 做删除重建，绝不允许指向 / 或系统目录
[[ "$ANKI_ROOT" == /opt/* ]] || die "ANKI_ROOT 必须是 /opt 下的路径（当前：$ANKI_ROOT）"
[[ "$ANKI_DATA" == /var/lib/* ]] || die "ANKI_DATA 必须是 /var/lib 下的路径（当前：$ANKI_DATA）"
[[ "$ANKI_ETC" == /etc/* ]] || die "ANKI_ETC 必须是 /etc 下的路径（当前：$ANKI_ETC）"

id "$ANKI_USER" &>/dev/null || die "用户 $ANKI_USER 不存在"
info "目标用户：$ANKI_USER ($(id -u "$ANKI_USER"))"

AVAIL_MB=$(free -m | awk '/^Mem:/{print $7}')
info "可用内存：${AVAIL_MB} MB"
if (( AVAIL_MB < 250 )); then
  warn "可用内存不足 250 MB。pip 安装可能触发 OOM。"
  warn "建议先停 Hermes 释放内存：sudo systemctl stop hermes-gateway.service"
  read -r -p "    仍要继续？(y/N) " ans
  [[ "${ans:-N}" =~ ^[Yy]$ ]] || die "已取消"
fi

AVAIL_DISK=$(df -m / | awk 'NR==2{print $4}')
info "根分区可用：${AVAIL_DISK} MB"
(( AVAIL_DISK > 1000 )) || die "磁盘可用空间不足 1 GB"

# 端口占用检查：幂等重跑时，本栈自己的 anki-syncserver 会占着这个端口，那是正常的。
# 只有当占用者「不是本栈服务」时才拒绝执行。
PORT_PID=$(ss -tlnpH "sport = :${SYNC_PORT}" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [[ -n "$PORT_PID" ]]; then
  SVC_PID=$(systemctl show -p MainPID --value anki-syncserver.service 2>/dev/null || echo "")
  if systemctl is-active --quiet anki-syncserver.service && [[ -n "$SVC_PID" && "$SVC_PID" == "$PORT_PID" ]]; then
    info "端口 ${SYNC_PORT} 由本栈 anki-syncserver (pid ${PORT_PID}) 占用 —— 幂等重跑，正常"
  else
    ss -tlnp 2>/dev/null | grep ":${SYNC_PORT} " || true
    die "端口 ${SYNC_PORT} 被其他进程 (pid ${PORT_PID}) 占用，请用 SYNC_PORT=xxxx 指定其他端口"
  fi
else
  info "端口 ${SYNC_PORT} 空闲"
fi

info "Python：$(python3 --version 2>&1)"

# Debian 13 的 Python 3.13 默认不带 venv 支持包。光验证 `import venv` 成功是不够的，
# 真正决定能不能建 venv 的是 ensurepip。这里提前拦，避免跑到第 2 步才炸。
python3 -c "import ensurepip" 2>/dev/null \
  || die "系统 Python 缺少 ensurepip，无法创建 venv。请先执行：apt-get install -y python3.13-venv"
info "ensurepip 可用（venv 可创建）"

# ---------------------------------------------------------------- 1. 目录

step "1/8  创建目录结构"

install -d -m 0755 "$ANKI_ROOT"
install -d -m 0750 -o root -g "$ANKI_USER" "$ANKI_ETC"
install -d -m 0750 -o "$ANKI_USER" -g "$ANKI_USER" "$ANKI_DATA"
install -d -m 0750 -o "$ANKI_USER" -g "$ANKI_USER" "$ANKI_DATA/sync"
install -d -m 0750 -o "$ANKI_USER" -g "$ANKI_USER" "$ANKI_DATA/backups"

info "$ANKI_ROOT      代码与 venv"
info "$ANKI_DATA      collection、同步数据、备份"
info "$ANKI_ETC       配置（仅 root 可读）"

# ---------------------------------------------------------------- 2. venv

step "2/8  创建 venv 并安装 anki 库"

if [[ -x "$PY_BIN" ]] && "$PY_BIN" -c "import anki" 2>/dev/null; then
  info "venv 已存在且 anki 可用，跳过"
  info "  版本：$("$PY_BIN" -c 'import importlib.metadata as m; print(m.version("anki"))')"
else
  # 关键：venv 是否「真的能用」要看 pip，不能只看 python 可执行。
  # 上次失败留下的残缺 venv（只有 python 符号链接、没有 pip）会骗过 -x 检查，
  # 导致这里跳过重建、下一步 pip 命令直接崩。所以先验 pip，不通过就整个重建。
  if [[ -e "$ANKI_ROOT/venv" ]] && ! "$PY_BIN" -m pip --version &>/dev/null; then
    warn "检测到不可用的 venv 残留（pip 缺失），删除重建"
    rm -rf "$ANKI_ROOT/venv"
  fi
  [[ -x "$PY_BIN" ]] || python3 -m venv "$ANKI_ROOT/venv"
  info "升级 pip ..."
  "$PY_BIN" -m pip install --quiet --upgrade pip
  info "安装 anki（约 48 MB，通常 1 分钟内完成）..."
  "$PY_BIN" -m pip install --quiet anki
  info "已安装 anki $("$PY_BIN" -c 'import importlib.metadata as m; print(m.version("anki"))')"
fi

"$PY_BIN" -c "import anki.syncserver" 2>/dev/null \
  || die "anki.syncserver 模块不可用，无法继续"
info "anki.syncserver 模块可用"

# ---------------------------------------------------------------- 3. 制卡脚本

step "3/8  安装 anki-cli"

[[ -f "${SCRIPT_DIR}/anki_cli.py" ]] || die "找不到 ${SCRIPT_DIR}/anki_cli.py"
install -m 0755 -o root -g root "${SCRIPT_DIR}/anki_cli.py" "$CLI"
info "$CLI"

# 便捷包装，让 Hermes 调用更短
cat > "${ANKI_ROOT}/anki" <<WRAPPER
#!/bin/bash
exec ${PY_BIN} ${CLI} --config ${CONF} "\$@"
WRAPPER
chmod 0755 "${ANKI_ROOT}/anki"
info "${ANKI_ROOT}/anki  (包装脚本)"

# ---------------------------------------------------------------- 4. 配置

step "4/8  生成配置"

if [[ -f "$CONF" ]]; then
  info "配置已存在，保留不动：$CONF"
else
  # 密码必须"能被人手打"。openssl rand | tr -d '/+=' 会留下 1/I、O/o 这种形近字符，
  # 用户手输必错（实测踩过：32 位随机串让用户连试 4 次全被 403 拒绝）。
  # 改用无歧义字母表：排除 0 O o 1 I l i S 5，16 位约 79 bit。
  SYNC_PASS="$(python3 -c "import secrets; a='abcdefghjkmnpqrstuvwxyz2346789'; print(''.join(secrets.choice(a) for _ in range(16)))")"

  cat > "$SYNC_ENV" <<ENVEOF
SYNC_USER1=anki:${SYNC_PASS}
SYNC_BASE=${ANKI_DATA}/sync
SYNC_HOST=127.0.0.1
SYNC_PORT=${SYNC_PORT}
ENVEOF
  chmod 0600 "$SYNC_ENV"
  chown root:root "$SYNC_ENV"
  info "同步服务器凭据已生成：$SYNC_ENV（0600）"

  cat > "$CONF" <<CONFEOF
{
  "endpoint": "http://127.0.0.1:${SYNC_PORT}/",
  "username": "anki",
  "password": "${SYNC_PASS}",
  "collection": "${ANKI_DATA}/collection.anki2",
  "backup_dir": "${ANKI_DATA}/backups",
  "lock_file": "${ANKI_DATA}/.anki-cli.lock",
  "backup_keep": 20
}
CONFEOF
  chmod 0640 "$CONF"
  chown root:"$ANKI_USER" "$CONF"
  info "anki-cli 配置已生成：$CONF（0640，${ANKI_USER} 可读）"
fi

# ---------------------------------------------------------------- 5. systemd

step "5/8  部署同步服务器为 systemd 服务"

cat > /etc/systemd/system/anki-syncserver.service <<UNITEOF
[Unit]
Description=Anki self-hosted sync server
Documentation=https://docs.ankiweb.net/sync-server.html
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${ANKI_USER}
Group=${ANKI_USER}
EnvironmentFile=${SYNC_ENV}
ExecStart=${PY_BIN} -m anki.syncserver
Restart=on-failure
RestartSec=5

# 内存保护：这台机器总共只有 964 MB
MemoryMax=220M
MemoryHigh=180M

# 加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${ANKI_DATA}
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable anki-syncserver.service >/dev/null
info "服务已注册并设为开机自启（含 220 MB 内存上限）"

# ---------------------------------------------------------------- 6. 备份

step "6/8  部署每日备份"

cat > /usr/local/sbin/anki-autocards-backup <<'BKEOF'
#!/bin/bash
# Anki 制卡栈每日备份：同步服务器数据 + 本地 collection
set -euo pipefail
DATA=/var/lib/anki-autocards
DEST=${DATA}/backups
KEEP=7

mkdir -p "$DEST"
TS=$(date -u +%Y%m%dT%H%M%SZ)

# 同步服务器数据（权威副本）
if [[ -d ${DATA}/sync ]]; then
  tar czf "${DEST}/anki-sync-${TS}.tar.gz" -C "$DATA" sync 2>/dev/null || true
fi

# 本地 collection（用 sqlite 在线备份，避免 WAL 不一致）
if [[ -f ${DATA}/collection.anki2 ]]; then
  sqlite3 "${DATA}/collection.anki2" ".backup '${DEST}/collection-${TS}.anki2'" 2>/dev/null || true
fi

# 清理：同步数据保留 KEEP 天
find "$DEST" -name 'anki-sync-*.tar.gz' -mtime +${KEEP} -delete 2>/dev/null || true
find "$DEST" -name 'collection-*.anki2' -mtime +${KEEP} -delete 2>/dev/null || true

echo "anki backup done: ${TS}"
BKEOF
chmod 0755 /usr/local/sbin/anki-autocards-backup

cat > /etc/systemd/system/anki-autocards-backup.service <<'SVCEOF'
[Unit]
Description=Anki autocards daily backup

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/anki-autocards-backup
SVCEOF

cat > /etc/systemd/system/anki-autocards-backup.timer <<'TMREOF'
[Unit]
Description=Run Anki autocards backup daily

[Timer]
OnCalendar=*-*-* 18:40:00
Persistent=true

[Install]
WantedBy=timers.target
TMREOF

systemctl daemon-reload
systemctl enable --now anki-autocards-backup.timer >/dev/null
info "备份脚本 + 每日定时器已部署（UTC 18:40，保留 7 天）"

# ---------------------------------------------------------------- 7. Hermes skill

step "7/8  安装 Hermes 制卡 skill"

SKILL_SRC="${SCRIPT_DIR}/skills/anki-cards/SKILL.md"
SKILL_DST="${HERMES_HOME}/skills/note-taking/anki-cards"

if [[ -f "$SKILL_SRC" ]]; then
  install -d -m 0755 -o "$ANKI_USER" -g "$ANKI_USER" "$SKILL_DST"
  install -m 0644 -o "$ANKI_USER" -g "$ANKI_USER" "$SKILL_SRC" "${SKILL_DST}/SKILL.md"
  info "已安装：${SKILL_DST}/SKILL.md"
else
  warn "找不到 ${SKILL_SRC}，跳过 skill 安装"
fi

# ---------------------------------------------------------------- 8. 验收

step "8/8  启动并验收"

systemctl restart anki-syncserver.service
sleep 3

if ! systemctl is-active --quiet anki-syncserver.service; then
  journalctl -u anki-syncserver.service -n 30 --no-pager
  die "同步服务器启动失败，日志见上"
fi
info "anki-syncserver 状态：active"

printf '    %-22s %s\n' "监听端口" "$(ss -tlnp 2>/dev/null | grep ":${SYNC_PORT} " | head -1 | awk '{print $4}')"
printf '    %-22s %s\n' "服务内存" "$(systemctl show anki-syncserver.service -p MemoryCurrent --value | awk '{printf "%.1f MB", $1/1024/1024}')"

info "初始化本地 collection（首次会创建空库）..."
sudo -u "$ANKI_USER" "$ANKI_ROOT/anki" init 2>&1 | tail -5 || warn "init 返回非零（若服务器尚无数据属正常）"

info "只读自检："
sudo -u "$ANKI_USER" "$ANKI_ROOT/anki" selftest 2>&1 | tail -20

# ---------------------------------------------------------------- 收尾

cat <<'NEXTEOF'

================================================================
部署完成。接下来需要人工完成三件事：

1. Cloudflare Dashboard 加路由
   anki.example.com  ->  http://127.0.0.1:8080
   注意：不要挂 Cloudflare Access（Anki 客户端不支持认证）

2. 用户设备改同步地址
   Anki 桌面：偏好设置 -> 同步 -> 自定义同步服务器
   AnkiDroid：设置 -> 高级 -> 自定义同步服务器
   AnkiMobile：设置 -> 同步 -> 自定义服务器
   地址填 https://anki.example.com/
   账号密码见 /etc/anki-autocards/syncserver.env

3. 首次数据迁移（顺序很重要）
   a. 先在 Anki 桌面端完整同步一次（确保本地最新）
   b. 改同步地址为自建服务器
   c. 首次同步选「上传本地到服务器」
   d. 手机端改地址，首次同步选「下载」

回滚：
   sudo systemctl disable --now anki-syncserver.service
   sudo rm /etc/systemd/system/anki-syncserver.service
   数据都在 /var/lib/anki-autocards/，删除前请先备份
================================================================
NEXTEOF

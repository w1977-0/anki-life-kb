#!/usr/bin/env python3
"""
Anki 同步服务器状态页。

存在的理由：Anki 同步接口没有网页界面，浏览器打开根路径只会得到 404，
于是「服务器到底活着没有」变成一个看不见的问题，反复消耗沟通成本。
这个服务专门回答那个问题。

设计约束：
  - 只绑定环回地址（127.0.0.1），由 Cloudflare 隧道按路径转发
  - 完全只读：不写任何文件，不碰同步服务器的 collection（只读打开）
  - 任何一项检查失败都不能让进程崩掉，失败就显示"未响应"
"""
from __future__ import annotations

import socket
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BIND = "127.0.0.1"
PORT = 8099
SYNC_HOST = "127.0.0.1"
SYNC_PORT = 8080
DATA_DIR = Path("/var/lib/anki-autocards")
SYNC_COLLECTION = DATA_DIR / "sync" / "anki" / "collection.anki2"
STARTED = time.time()
CST = timezone(timedelta(hours=8))


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y年%m月%d日 %H:%M:%S")


def probe_sync() -> bool:
    """能不能连上同步服务器的端口。"""
    try:
        with socket.create_connection((SYNC_HOST, SYNC_PORT), timeout=2):
            return True
    except OSError:
        return False


def _unicase(a: str, b: str) -> int:
    return (a.casefold() > b.casefold()) - (a.casefold() < b.casefold())


# 每 30 秒最多真正打开一次集合数据库。
# 目的不是省 CPU，是减少持有 SQLite 句柄的次数 —— 这个页面出过一次事故。
_CACHE_TTL = 30.0
_cache: dict = {"at": 0.0, "notes": None, "cards": None}


def _read_counts() -> tuple[int | None, int | None]:
    """只读地数一下笔记和卡片数。

    三条硬约束，都是踩过坑之后加的：

    1. 连接必须关闭。曾经把 con.close() 写在 try 块里，一旦查询抛异常
       就被 except 跳过，句柄泄漏，最终把同步服务器的集合数据库锁死，
       客户端只看到「AnkiWeb 服务出现错误，请稍后重试」。
       现在关闭动作放在 finally 里，任何路径都会执行。

    2. 绝不在数据库上排队等待。同步进行中集合是写锁状态，
       timeout=1 让查询一秒内放弃，而不是把整个状态页拖住。

    3. 拿不到就退到 immutable 模式。immutable=1 完全不参与加锁、
       不碰 -wal/-shm，物理上不可能干扰同步；代价是读到的是上一次
       checkpoint 的数据，可能偏旧 —— 偏旧远好过把同步搞挂。
    """
    for uri in (
        f"file:{SYNC_COLLECTION}?mode=ro",
        f"file:{SYNC_COLLECTION}?mode=ro&immutable=1",
    ):
        con = None
        try:
            con = sqlite3.connect(uri, uri=True, timeout=1.0, isolation_level=None)
            # Anki 的表定义了自定义排序规则 unicase，不注册就连 count(*) 都查不了
            con.create_collation("unicase", _unicase)
            notes = con.execute("SELECT count(*) FROM notes").fetchone()[0]
            cards = con.execute("SELECT count(*) FROM cards").fetchone()[0]
            return notes, cards
        except Exception:
            continue
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    return None, None


def collection_info() -> dict:
    info = {"exists": False, "size": 0, "mtime": None, "notes": None, "cards": None}
    try:
        st = SYNC_COLLECTION.stat()
    except OSError:
        return info

    info["exists"] = True
    info["size"] = st.st_size
    info["mtime"] = datetime.fromtimestamp(st.st_mtime, CST)

    now = time.time()
    if now - _cache["at"] < _CACHE_TTL:
        info["notes"] = _cache["notes"]
        info["cards"] = _cache["cards"]
        return info

    notes, cards = _read_counts()
    _cache["at"] = now
    _cache["notes"] = notes
    _cache["cards"] = cards
    info["notes"] = notes
    info["cards"] = cards
    return info


def human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} 字节"


def human_uptime(sec: float) -> str:
    sec = int(sec)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d} 天 {h} 小时"
    if h:
        return f"{h} 小时 {m} 分"
    return f"{m} 分"


def render() -> str:
    alive = probe_sync()
    info = collection_info()
    up = human_uptime(time.time() - STARTED)

    if alive:
        dot, headline, tone = "ok", "服务器运行中", "ok"
        sub = "同步服务正在监听，可以正常使用。"
    else:
        dot, headline, tone = "bad", "同步服务未响应", "bad"
        sub = "同步服务没有在监听端口。请联系管理员检查。"

    def row(k: str, v: str, muted: bool = False) -> str:
        cls = "v muted" if muted else "v"
        return f'<div class="row"><span class="k">{k}</span><span class="{cls}">{v}</span></div>'

    if not info["exists"]:
        data_rows = row("同步数据", "尚未建立（还没有任何设备上传过）", muted=True)
    else:
        rows = [row("数据文件", human_size(info["size"]))]
        if info["mtime"]:
            rows.append(
                row("最近一次同步", info["mtime"].strftime("%Y年%m月%d日 %H:%M:%S"))
            )
        if info["notes"] is None:
            # 读不到不等于空 —— 同步进行中就是读不到，说成"空"会吓到人
            rows.append(row("已同步内容", "正在读取中，请稍候再刷新", muted=True))
        elif info["notes"]:
            rows.append(
                row("已同步内容", f'{info["notes"]} 条笔记 · {info["cards"]} 张卡片')
            )
        else:
            rows.append(row("已同步内容", "还没有任何设备上传过", muted=True))
        data_rows = "".join(rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anki 同步服务器 · 状态</title>
<style>
  :root {{
    --ink:#2C2C2A; --ink2:#5F5E5A; --ink3:#888780;
    --line:#E5E3DC; --bg:#FBFBF9; --card:#FFF;
    --ok:#0F6E56; --ok-bg:#E1F5EE;
    --bad:#A32D2D; --bad-bg:#FCEBEB;
    --amber:#854F0B; --amber-bg:#FAEEDA;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
    font-size:15px; line-height:1.75; -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:620px; margin:0 auto; padding:56px 24px 80px}}
  .banner{{border-radius:12px; padding:20px 24px; margin-bottom:26px;
    display:flex; align-items:center; gap:14px}}
  .banner.ok{{background:var(--ok-bg); border-left:4px solid var(--ok)}}
  .banner.bad{{background:var(--bad-bg); border-left:4px solid var(--bad)}}
  .dot{{width:11px; height:11px; border-radius:50%; flex:none}}
  .banner.ok .dot{{background:var(--ok)}}
  .banner.bad .dot{{background:var(--bad)}}
  .banner h1{{font-size:19px; font-weight:600; margin:0 0 3px}}
  .banner.ok h1{{color:var(--ok)}}
  .banner.bad h1{{color:var(--bad)}}
  .banner p{{margin:0; font-size:13.5px; color:var(--ink2)}}
  .card{{background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:6px 22px; margin-bottom:22px}}
  .row{{display:flex; justify-content:space-between; gap:18px; padding:11px 0;
    border-bottom:1px solid #F1EFE8; font-size:14px}}
  .row:last-child{{border-bottom:none}}
  .k{{color:var(--ink3); white-space:nowrap}}
  .v{{text-align:right; font-weight:500}}
  .v.muted{{color:var(--ink3); font-weight:400; font-size:13px}}
  .note{{background:var(--amber-bg); border-left:3px solid #BA7517; border-radius:8px;
    padding:14px 18px; font-size:13.5px; color:#412402}}
  .note b{{color:var(--amber)}}
  footer{{margin-top:34px; font-size:12.5px; color:var(--ink3); line-height:1.9}}
  code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px;
    background:#F1EFE8; padding:2px 6px; border-radius:4px}}
</style>
</head>
<body>
<div class="wrap">

  <div class="banner {tone}">
    <span class="dot"></span>
    <div>
      <h1>{headline}</h1>
      <p>{sub}</p>
    </div>
  </div>

  <div class="card">
    <div class="row"><span class="k">同步接口</span>
      <span class="v">{"https://anki.example.com/" if alive else "无响应"}</span></div>
    {data_rows}
    <div class="row"><span class="k">状态页运行时长</span><span class="v">{up}</span></div>
    <div class="row"><span class="k">检查时间</span><span class="v">{now_cst()}</span></div>
  </div>

  <div class="note">
    <p style="margin:0 0 8px"><b>这个页面不是给 Anki 用的。</b>Anki 客户端要填的是
    <code>https://anki.example.com/</code>，填进「自托管同步服务器」那一栏。</p>
    <p style="margin:0">你能看到这个页面，是因为它是<strong>单独的一个地址</strong>，专门用来回答
    "服务器到底活着没有"。同步接口本身没有网页界面 —— 浏览器打开
    <code>https://anki.example.com/</code> 会显示 404，<strong>那是正常的</strong>，不代表坏了。</p>
  </div>

  <footer>
    由 <code>anki-status.service</code> 提供 · 只读 · 仅监听环回地址<br>
    数据来源：同步服务的端口探测 + 同步数据文件（<code>/var/lib/anki-autocards/sync/</code>）
  </footer>

</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "anki-status/1.0"
    sys_version = ""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/", "/status"):
            self._send(200, render().encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/healthz":
            alive = probe_sync()
            body = b'{"ok":true}' if alive else b'{"ok":false}'
            self._send(200 if alive else 503, body, "application/json")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802
        self._send(200, b"", "text/html; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        pass  # 不写访问日志，避免无谓的磁盘写入


def main() -> None:
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()

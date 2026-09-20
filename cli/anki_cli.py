#!/usr/bin/env python3
"""anki-cli — 飞书 → Hermes → Anki 的无头制卡工具。

用途
----
在服务器上以 headless 方式向 Anki collection 写入卡片，并通过自建
Anki 同步服务器（`python -m anki.syncserver`）与用户的手机 / 桌面端同步。

安全设计（务必先读这一段）
--------------------------
Anki 同步协议在两端状态不一致时，会返回一个"全量同步"指令：

    0  NO_CHANGES      无需同步
    1  NORMAL_SYNC     正常增量同步
    2  FULL_SYNC       需要全量，方向待定
    3  FULL_DOWNLOAD   用服务器覆盖本地
    4  FULL_UPLOAD     用本地覆盖服务器   <-- 危险

FULL_UPLOAD 会用本地 collection 覆盖服务器。如果本地恰好是空库或过期库，
用户全部卡片会被清空，且不可恢复。

因此本工具做了三重硬防护：

  1. 结构上不可能：`full_upload_or_download()` 的 upload 参数恒为 False，
     全文件不存在传 True 的代码路径。
  2. 发生即中止：检测到服务器要求 FULL_UPLOAD 时立即抛 SafetyError，
     不执行任何写操作。
  3. 可恢复：任何全量操作前，先用 sqlite3 在线备份 API 备份本地 collection。

第 1 条是"不可能发生"，第 2 条是"发生了也停下"，第 3 条是"停下了还能恢复"。

配置
----
默认读 /etc/anki-autocards/config.json，可用 --config 或环境变量
ANKI_AUTOCARDS_CONFIG 覆盖。配置文件应为 0600，仅服务账号可读。
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 常量

DEFAULT_CONFIG = "/etc/anki-autocards/config.json"

NO_CHANGES, NORMAL_SYNC, FULL_SYNC, FULL_DOWNLOAD, FULL_UPLOAD = 0, 1, 2, 3, 4
REQ_NAME = {
    NO_CHANGES: "NO_CHANGES",
    NORMAL_SYNC: "NORMAL_SYNC",
    FULL_SYNC: "FULL_SYNC",
    FULL_DOWNLOAD: "FULL_DOWNLOAD",
    FULL_UPLOAD: "FULL_UPLOAD",
}


class SafetyError(RuntimeError):
    """触发安全护栏时抛出。调用方应把非零退出码视为硬失败。"""


class ConfigError(RuntimeError):
    pass


# ---------------------------------------------------------------- 工具


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def emit(obj: Any) -> None:
    """结果输出到 stdout（JSON），日志走 stderr，便于 Hermes 解析。"""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def load_config(path: str | None) -> dict:
    p = Path(path or os.environ.get("ANKI_AUTOCARDS_CONFIG", DEFAULT_CONFIG))
    if not p.exists():
        raise ConfigError(f"配置文件不存在: {p}")
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"配置文件不是合法 JSON: {e}") from e

    for key in ("endpoint", "username", "password", "collection"):
        if not cfg.get(key):
            raise ConfigError(f"配置缺少必填项: {key}")

    mode = p.stat().st_mode & 0o777
    # 组读是设计需要（root:hermes + 0640，让 hermes 用户能读到配置）。
    # 真正要拦的是「其他人」可访问 —— 那才意味着密码可能被无关进程读到。
    if mode & 0o007:
        log(f"警告：配置文件对其他人可访问 ({oct(mode)})，建议 chmod 640 {p}")

    cfg.setdefault("backup_dir", str(Path(cfg["collection"]).parent / "backups"))
    cfg.setdefault("lock_file", str(Path(cfg["collection"]).parent / ".anki-cli.lock"))
    cfg.setdefault("backup_keep", 20)
    return cfg


def online_backup(col_path: str, backup_dir: str, keep: int) -> str:
    """用 sqlite3 在线备份 API 复制 collection。

    不用 shutil.copy2 —— collection 处于 WAL 模式时，直接拷文件可能拿到
    不一致的快照（-wal 里的内容还没合并进主库）。
    """
    d = Path(backup_dir)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dst = d / f"collection-{ts}.anki2"

    src = sqlite3.connect(f"file:{col_path}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(str(dst))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()

    backups = sorted(d.glob("collection-*.anki2"))
    for old in backups[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError:
            pass
    return str(dst)


# ---------------------------------------------------------------- 会话


class AnkiSession:
    """持有 collection 句柄与同步凭据，串行化访问。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.col = None
        self.auth = None
        self._lock_fh = None

    # ---- 生命周期

    def __enter__(self) -> "AnkiSession":
        lock_path = Path(self.cfg["lock_file"])
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fh = open(lock_path, "w")
        try:
            fcntl.flock(self._lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SafetyError(
                "另一个 anki-cli 进程正在运行（锁被占用）。"
                "并发写入会破坏 collection，已中止。"
            )

        from anki.collection import Collection  # 延迟导入，让 --help 秒回

        col_path = self.cfg["collection"]
        Path(col_path).parent.mkdir(parents=True, exist_ok=True)
        self.col = Collection(col_path)
        log(f"collection 已打开：{col_path}（{self.col.note_count()} 条笔记）")

        self.auth = self.col.sync_login(
            self.cfg["username"], self.cfg["password"], self.cfg["endpoint"]
        )
        log(f"已登录同步服务器：{self.cfg['endpoint']}")
        return self

    def __exit__(self, *exc) -> None:
        if self.col is not None:
            try:
                self.col.close()
            except Exception:
                pass
        if self._lock_fh is not None:
            try:
                fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
                self._lock_fh.close()
            except Exception:
                pass

    # ---- 同步

    def sync(self, allow_full_download: bool = True) -> dict:
        """执行一次同步。绝不执行 FULL_UPLOAD。"""
        t0 = time.time()
        out = self.col.sync_collection(self.auth, False)
        req = out.required
        log(f"同步返回 required={req} ({REQ_NAME.get(req, '?')})")

        # ---- 护栏 1：FULL_UPLOAD 一律中止
        if req == FULL_UPLOAD:
            raise SafetyError(
                "服务器要求 FULL_UPLOAD（用本地覆盖服务器）。\n"
                "这通常意味着本地 collection 与服务器历史不一致，"
                "盲目执行会清空服务器上的全部卡片。\n"
                "已中止，未做任何写操作，本地 collection 完好。\n"
                "常见原因：服务器端 collection 被重建或损坏。\n"
                "人工处理路径：先在官方客户端（手机 / 桌面 Anki）上执行一次完整同步，"
                "把数据推送到同步服务器，然后重新运行 `anki-cli init` 拉取本地副本。"
            )

        # ---- 全量下载：安全方向，但仍先备份
        if req in (FULL_SYNC, FULL_DOWNLOAD):
            if not allow_full_download:
                raise SafetyError(
                    f"同步需要全量操作（{REQ_NAME.get(req)}），当前命令不允许。"
                    "请先单独执行 `anki-cli init`。"
                )
            bak = online_backup(
                self.cfg["collection"], self.cfg["backup_dir"], self.cfg["backup_keep"]
            )
            log(f"全量同步前已备份本地 collection -> {bak}")
            self.col.close_for_full_sync()
            # 注意：upload=False 是硬编码的，此处不存在传 True 的路径
            self.col.full_upload_or_download(auth=self.auth, server_usn=None, upload=False)
            self.col.reopen(after_full_sync=True)
            log(f"已从服务器全量拉取，现有 {self.col.note_count()} 条笔记")

        return {
            "required": req,
            "required_name": REQ_NAME.get(req, "UNKNOWN"),
            "notes": self.col.note_count(),
            "seconds": round(time.time() - t0, 3),
        }

    def establish_baseline(self) -> None:
        """两边都空时主动做一次 full-download，建立同步基线。

        背景（踩过的坑）：全新部署时服务器和本地都是空库，sync 返回
        NO_CHANGES —— 但这只表示"当前没有差异"，**不代表建立了同步基线**。
        之后本地一旦写入数据，Anki 会认为两边没有共同历史，转而要求
        FULL_UPLOAD，被护栏拦下，整个流程卡死。

        解法：主动拉一次（即使服务器是空的），让两端建立共同基线。
        拉空库不会丢失任何数据，因为本地本来就是空的。
        """
        self.col.close_for_full_sync()
        # upload=False 同样是硬编码的，此方法不可能上传
        self.col.full_upload_or_download(auth=self.auth, server_usn=None, upload=False)
        self.col.reopen(after_full_sync=True)

    # ---- 写卡片

    def add_cards(
        self, deck: str, notetype: str, cards: list[dict], default_tags: list[str] | None
    ) -> dict:
        deck_id = self.col.decks.id(deck)
        if deck_id is None:
            raise RuntimeError(f"无法创建或找到牌组: {deck}")

        nt = self.col.models.by_name(notetype)
        if nt is None:
            available = [m["name"] for m in self.col.models.all()]
            raise RuntimeError(
                f"笔记类型不存在: {notetype}\n可用类型: {', '.join(available)}"
            )

        field_names = [f["name"] for f in nt["flds"]]
        added, skipped, failed = [], [], []

        for idx, card in enumerate(cards):
            try:
                fields = self._resolve_fields(card, field_names)
                if fields is None:
                    failed.append({"index": idx, "reason": f"缺少字段，需要: {field_names}"})
                    continue

                front = next(iter(fields.values()), "")
                if self._is_duplicate(front):
                    skipped.append({"index": idx, "front": front[:60], "reason": "重复"})
                    continue

                note = self.col.new_note(nt)
                for name, value in fields.items():
                    note[name] = value
                tags = list(default_tags or []) + list(card.get("tags") or [])
                note.tags = list(dict.fromkeys(tags))

                self.col.add_note(note, deck_id)
                added.append({"index": idx, "note_id": str(note.id), "front": front[:60]})
            except Exception as e:  # 单张失败不影响其余
                failed.append({"index": idx, "reason": f"{type(e).__name__}: {e}"})

        return {"added": added, "skipped": skipped, "failed": failed}

    @staticmethod
    def _resolve_fields(card: dict, field_names: list[str]) -> dict | None:
        if isinstance(card.get("fields"), dict):
            fields = {k: str(v) for k, v in card["fields"].items()}
            missing = [f for f in field_names if f not in fields]
            if missing:
                return None
            return {f: fields[f] for f in field_names}

        # 简写形式：front / back 映射到前两个字段
        if "front" in card and "back" in card:
            if len(field_names) < 2:
                return None
            return {field_names[0]: str(card["front"]), field_names[1]: str(card["back"])}

        # cloze 简写
        if "text" in card:
            return {field_names[0]: str(card["text"])}
        return None

    def _is_duplicate(self, front: str) -> bool:
        probe = " ".join(front.split())[:60]
        if not probe:
            return False
        try:
            return bool(self.col.find_notes(f'"{probe}"'))
        except Exception:
            return False  # 搜索语法出错不应阻断写入


# ---------------------------------------------------------------- 命令


def cmd_init(sess: AnkiSession, args) -> dict:
    result = sess.sync(allow_full_download=True)

    # 全新部署的坑：两边都是空库时 sync 返回 NO_CHANGES，但这不代表
    # 建立了同步基线。之后本地一写入数据，Anki 就会要求 FULL_UPLOAD。
    # 因此只在「本地为空」时主动做一次 full-download 把基线建起来
    # （本地非空时不动，避免误覆盖）。
    if result["required"] == NO_CHANGES and sess.col.note_count() == 0:
        log("本地与服务器均为空库，主动建立同步基线 ...")
        sess.establish_baseline()
        result = sess.sync(allow_full_download=True)
        result["baseline_established"] = True
        log("基线已建立，后续可正常增量同步")

    result["action"] = "init"
    return result


def cmd_sync(sess: AnkiSession, args) -> dict:
    result = sess.sync(allow_full_download=args.allow_full_download)
    result["action"] = "sync"
    return result


def cmd_add(sess: AnkiSession, args) -> dict:
    raw = sys.stdin.read() if args.cards == "-" else Path(args.cards).read_text(encoding="utf-8")
    payload = json.loads(raw)
    cards = payload["cards"] if isinstance(payload, dict) else payload
    deck = args.deck or (payload.get("deck") if isinstance(payload, dict) else None)
    notetype = args.notetype or (
        payload.get("notetype") if isinstance(payload, dict) else None
    )
    if not deck:
        raise ConfigError("未指定牌组（--deck 或 JSON 里的 deck 字段）")
    if not notetype:
        raise ConfigError("未指定笔记类型（--notetype 或 JSON 里的 notetype 字段）")

    pre = sess.sync(allow_full_download=False)
    log(f"写入前同步完成：{pre['required_name']}")

    outcome = sess.add_cards(deck, notetype, cards, args.tag)
    log(f"写入完成：成功 {len(outcome['added'])}，跳过 {len(outcome['skipped'])}，失败 {len(outcome['failed'])}")

    post = sess.sync(allow_full_download=False)
    log(f"写入后同步完成：{post['required_name']}")

    return {
        "action": "add",
        "deck": deck,
        "notetype": notetype,
        "added": outcome["added"],
        "skipped": outcome["skipped"],
        "failed": outcome["failed"],
        "summary": {
            "added": len(outcome["added"]),
            "skipped": len(outcome["skipped"]),
            "failed": len(outcome["failed"]),
            "total_notes": post["notes"],
        },
        "sync": {"before": pre, "after": post},
    }


def cmd_decks(sess: AnkiSession, args) -> dict:
    decks = [
        {
            "name": d["name"],
            "id": str(d["id"]),
            "cards": sess.col.decks.card_count(d["id"], include_subdecks=False),
        }
        for d in sess.col.decks.all()
        if d["name"] != "Default" or args.all
    ]
    return {"action": "decks", "decks": decks}


def cmd_notetypes(sess: AnkiSession, args) -> dict:
    types = [
        {
            "name": m["name"],
            "fields": [f["name"] for f in m["flds"]],
            "templates": [t["name"] for t in m["tmpls"]],
        }
        for m in sess.col.models.all()
    ]
    return {"action": "notetypes", "notetypes": types}


def cmd_search(sess: AnkiSession, args) -> dict:
    ids = sess.col.find_notes(args.query)[: args.limit]
    notes = []
    for nid in ids:
        note = sess.col.get_note(nid)
        notes.append(
            {
                "note_id": str(note.id),
                "note_type": note.note_type()["name"],
                "fields": dict(note.items()),
                "tags": note.tags,
            }
        )
    return {"action": "search", "query": args.query, "count": len(notes), "notes": notes}


def cmd_stats(sess: AnkiSession, args) -> dict:
    decks = sess.col.decks.all()
    return {
        "action": "stats",
        "notes": sess.col.note_count(),
        "cards": sess.col.card_count(),
        "decks": len(decks),
        "collection_path": sess.cfg["collection"],
    }


def cmd_export(sess: AnkiSession, args) -> dict:
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from anki.collection import DeckIdLimit, ExportAnkiPackageOptions

    deck_id = sess.col.decks.id(args.deck)
    if deck_id is None:
        raise RuntimeError(f"牌组不存在: {args.deck}")
    sess.col.export_anki_package(
        out_path=str(out_path),
        options=ExportAnkiPackageOptions(),
        limit=DeckIdLimit(deck_id=deck_id),
    )
    size = out_path.stat().st_size
    return {
        "action": "export",
        "deck": args.deck,
        "path": str(out_path),
        "bytes": size,
        "mb": round(size / 1024 / 1024, 2),
    }


def cmd_selftest(sess: AnkiSession, args) -> dict:
    """只读自检：确认配置、连通性、安全护栏都正常。"""
    checks = []
    checks.append({"check": "collection 可打开", "ok": True, "notes": sess.col.note_count()})

    status = sess.col.sync_status(sess.auth)
    checks.append(
        {
            "check": "同步服务器可达",
            "ok": True,
            "required": status.required,
            "required_name": REQ_NAME.get(status.required, "UNKNOWN"),
        }
    )

    if status.required == FULL_UPLOAD:
        checks.append(
            {
                "check": "同步方向安全",
                "ok": False,
                "detail": "服务器要求 FULL_UPLOAD，说明本地与服务器不一致。"
                "本工具会自动中止，但建议人工排查。",
            }
        )
    else:
        checks.append({"check": "同步方向安全", "ok": True})

    # 注意：anki 包本身不暴露 __version__ 属性（实测 AttributeError），
    # 必须走 importlib.metadata 查发行版版本。
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as pkg_version

    try:
        anki_ver = pkg_version("anki")
    except PackageNotFoundError:
        anki_ver = "未知"

    checks.append({"check": "anki 库版本", "ok": True, "version": anki_ver})

    return {
        "action": "selftest",
        "all_ok": all(c["ok"] for c in checks),
        "checks": checks,
    }


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="anki-cli",
        description="飞书 → Hermes → Anki 无头制卡工具（绝不允许 FULL_UPLOAD）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", help=f"配置文件路径（默认 {DEFAULT_CONFIG}）")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="首次初始化：从同步服务器全量拉取")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("sync", help="手动同步一次")
    sp.add_argument(
        "--allow-full-download",
        action="store_true",
        help="允许全量下载（会用服务器覆盖本地，执行前自动备份）",
    )
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("add", help="写入卡片（JSON 从文件或 stdin）")
    sp.add_argument("cards", help="JSON 文件路径，或 - 表示从 stdin 读")
    sp.add_argument("--deck", help="目标牌组（JSON 里没写时使用）")
    sp.add_argument("--notetype", help="笔记类型（JSON 里没写时使用）")
    sp.add_argument("--tag", action="append", default=[], help="附加标签，可重复")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("decks", help="列出牌组")
    sp.add_argument("--all", action="store_true", help="包含默认牌组")
    sp.set_defaults(func=cmd_decks)

    sp = sub.add_parser("notetypes", help="列出笔记类型及其字段")
    sp.set_defaults(func=cmd_notetypes)

    sp = sub.add_parser("search", help="搜索笔记")
    sp.add_argument("query", help="Anki 搜索语法")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("stats", help="collection 概况")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("export", help="导出 .apkg（方案 C：直接发飞书）")
    sp.add_argument("--deck", required=True)
    sp.add_argument("--out", required=True)
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("selftest", help="只读自检")
    sp.set_defaults(func=cmd_selftest)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        with AnkiSession(cfg) as sess:
            result = args.func(sess, args)
        emit({"ok": True, **result})
        return 0
    except SafetyError as e:
        emit({"ok": False, "error": "SAFETY_ABORT", "detail": str(e)})
        log(f"安全中止：{e}")
        return 2
    except ConfigError as e:
        emit({"ok": False, "error": "CONFIG_ERROR", "detail": str(e)})
        return 3
    except Exception as e:
        emit({"ok": False, "error": type(e).__name__, "detail": str(e)})
        log(f"执行失败：{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

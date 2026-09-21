#!/usr/bin/env python3
"""把 split_vol.py 产出的 JSON 写进 Anki（在服务器上跑）

策略：按「编号」匹配已有卡片 → 更新正文；新编号 → 新建；不删任何卡（保住复习进度）
用法: python3 write_volumes.py 一 <卷一.json> 二 <卷二.json> ...
      （卷号与文件成对给；卷号是《…（X）》里的那个字）
"""
import os
import re
import sys
import json

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection

ROOT = "30：读过::30.02：文章::30.02.02：墨苍离::《致爱自己的人：你可能困惑或者被忽悠的（%s）》"
PATH = "/var/lib/anki-autocards/collection.anki2"


def num_of(src):
    m = re.match(r'^(\d+)', src or '')
    return m.group(1) if m else None


def run(deck_cn, json_path):
    cards = json.load(open(json_path, encoding="utf-8"))
    deck = ROOT % deck_cn
    c = Collection(PATH)
    did = c.decks.id(deck)

    existing = {}
    for nid in c.find_notes(f'deck:"{deck}"'):
        n = c.get_note(nid)
        k = num_of(n["出处"]) or ('0' if '目' in (n["出处"] or '') else None)
        if k:
            existing[k] = n

    add = upd = 0
    for card in cards:
        n = card["n"]
        html = card["html"]
        src = ('目录' if n == '0' else f'{n}. {card["title"]}')
        note = existing.get(n)
        if note is None:
            note = c.new_note(c.models.by_name("生活摘录")["id"])
        note["正文"] = html
        note["出处"] = src
        note["类型"] = "长文"
        note["风格"] = "paper"
        note["自测"] = ""
        note.tags = ["墨苍离", "致爱自己的人", f"（{deck_cn}）", "完整保留"]
        if note.id:
            c.update_note(note)
            upd += 1
        else:
            c.add_note(note, did)
            add += 1

    print(f'  {deck_cn}卷: 新建 {add}，更新 {upd}，共 {len(cards)} 张  牌组={deck.split("::")[-1]}')
    print('    notes 总数:', c.db.scalar("select count() from notes"))
    c.db.execute("pragma wal_checkpoint(truncate)")
    c.close()


SYNC = "/var/lib/anki-autocards/sync/anki/collection.anki2"


def refresh_sync():
    """手机同步的是副本，不刷新就永远看不到新卡。这一步必须做，别靠记性。"""
    import sqlite3
    import subprocess
    subprocess.run(["systemctl", "stop", "anki-syncserver"], check=False)
    db = sqlite3.connect(PATH)
    db.execute("pragma wal_checkpoint(truncate)")
    db.close()
    for ext in ("-wal", "-shm"):                 # 让它们重建，别一起拷（会损坏）
        if os.path.exists(SYNC + ext):
            os.remove(SYNC + ext)
    subprocess.run(["cp", PATH, SYNC], check=True)
    subprocess.run(["chown", "hermes:hermes", SYNC], check=False)
    subprocess.run(["systemctl", "start", "anki-syncserver"], check=False)

    live = sqlite3.connect(PATH)
    copy = sqlite3.connect(f"file:{SYNC}?mode=ro", uri=True)
    print("\n=== 同步副本 ===")
    ok = True
    for t in ("notes", "cards"):
        a = live.execute(f"select count() from {t}").fetchone()[0]
        b = copy.execute(f"select count() from {t}").fetchone()[0]
        ok &= (a == b)
        print(f"  {t}: 工作库 {a} / 副本 {b}  {'✅' if a == b else '❌ 差 %d' % (a - b)}")
    live.close()
    copy.close()
    print("  " + ("✅ 手机可同步" if ok else "❌ 副本与工作库不一致，检查上面"))
    return ok


def main():
    args = sys.argv[1:]
    for cn, p in zip(args[0::2], args[1::2]):
        if p and os.path.exists(p):
            run(cn, p)
        else:
            print("  跳过（无文件）:", cn, p)
    print("\n刷新同步副本（手机看的是副本，不做这步等于白写）…")
    refresh_sync()


if __name__ == "__main__":
    main()

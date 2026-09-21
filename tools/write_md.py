#!/usr/bin/env python3
"""把 md2cards.py 产出的 JSON 写进 Anki（在服务器跑）

用法: python3 tools/write_md.py <cards.json> [每批张数]
策略：牌组不存在则建；按「出处」幂等（重跑只更新不新增）；每批后回读 DB 核对条数
"""
import os
import sys
import json
import sqlite3
import time
import subprocess
import collections

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection

PATH = "/var/lib/anki-autocards/collection.anki2"
SYNC = "/var/lib/anki-autocards/sync/anki/collection.anki2"


def refresh_sync():
    subprocess.run(["systemctl", "stop", "anki-syncserver"], check=False)
    db = sqlite3.connect(PATH)
    db.execute("pragma wal_checkpoint(truncate)")
    db.close()
    for ext in ("-wal", "-shm"):
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
    return ok


def main():
    cards = json.load(open(sys.argv[1], encoding="utf-8"))
    batch = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    c = Collection(PATH)
    ntid = c.models.by_name("生活摘录")["id"]
    by_deck = collections.defaultdict(list)
    for x in cards:
        by_deck[x["deck"]].append(x)
    print("牌组数:", len(by_deck), "| 卡片数:", len(cards))

    t0 = time.time()
    done = 0
    for deck, lst in sorted(by_deck.items()):
        did = c.decks.id(deck)
        exist = {}
        for nid in c.find_notes(f'deck:"{deck}"'):
            n = c.get_note(nid)
            exist[n["出处"]] = n
        add = upd = 0
        for x in lst:
            n = exist.get(x["src"])
            if n is None:
                n = c.new_note(ntid)
            n["正文"] = x["html"]
            n["出处"] = x["src"]
            n["类型"] = "长文"
            n["风格"] = "paper"
            n["自测"] = ""
            n.tags = x["tags"]
            if n.id:
                c.update_note(n)
                upd += 1
            else:
                c.add_note(n, did)
                add += 1
            done += 1
            if done % batch == 0:
                got = c.db.scalar("select count() from notes")
                print(f"  …{done}/{len(cards)}  用时{time.time()-t0:.0f}s  notes={got}")
        # 每牌组回读核对（维度9：不信脚本自述）
        real = c.db.scalar(
            "select count() from cards where did=?", did)
        print(f"  {deck.split('::')[-1]:<12} +{add} ~{upd} → 库内实有 {real} 张"
              + ("  ✅" if real == len(lst) else f"  ⚠️ 期望{len(lst)}"))

    print(f"\n写入完成 用时 {time.time()-t0:.0f}s  notes 总数 {c.db.scalar('select count() from notes')}")
    c.db.execute("pragma wal_checkpoint(truncate)")
    c.close()
    refresh_sync()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""把 split_vol.py 产出的 JSON 写进 Anki（在服务器上跑）

策略：按「编号」匹配已有卡片 → 更新正文；新编号 → 新建；不删任何卡（保住复习进度）
用法: python3 write_volumes.py <卷四.json> <卷五.json> <卷六.json>
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


def main():
    for cn, p in zip(("四", "五", "六"), sys.argv[1:4]):
        if p and os.path.exists(p):
            run(cn, p)
        else:
            print("  跳过（无文件）:", p)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""给 q9adg 的「完全重复副本」打标签并挂起（不删卡，可逆）

规则：同一份内容（正文 MD5 相同）只留一张在复习队列里。
      主分类 = 第一个非 motions 的分类（其他分类更具体）；只在 motions 里则留 motions。
      其余副本：加标签「重复副本」+ suspend（仍在库里，可搜索、可随时恢复）。

用法: python3 tools/mark_dupes.py [--do]     # 不加 --do 只预演
"""
import sys
import re
import hashlib
import collections

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection

PATH = "/var/lib/anki-autocards/collection.anki2"
LIKE = "%30.02.03%"
MAIN_FALLBACK = "motions"          # 只在 motions 里出现时，留 motions
ORDER = ["个人成长", "亲子教育", "职业伦理", "亲密关系", "专享", "钩沉",
         "开放版权内容", "人文历史", "社区互动", "善哉集"]   # 越靠前越"主"


def main():
    c = Collection(PATH)
    rows = c.db.all(
        "select n.id, d.name, n.flds from notes n join cards cd on cd.nid=n.id "
        "join decks d on d.id=cd.did where d.name like ?", LIKE)

    groups = collections.defaultdict(list)
    for nid, dname, flds in rows:
        p = flds.split("\x1f")
        if p[1].strip() == '目录':
            continue
        cat = dname.split("\x1f")[-1]
        key = hashlib.md5(re.sub(r'\s', '', p[0]).encode()).hexdigest()
        groups[key].append((nid, cat, p[1].split(' ｜')[0]))

    keep, mark = [], []
    for key, items in groups.items():
        if len(items) == 1:
            keep.append(items[0])
            continue
        # 主分类：非 motions 且在 ORDER 里靠前的；否则 motions
        cands = [it for it in items if it[1] != MAIN_FALLBACK]
        pool = cands if cands else items
        pool.sort(key=lambda it: ORDER.index(it[1]) if it[1] in ORDER else 99)
        keep.append(pool[0])
        for it in items:
            if it[0] != pool[0][0]:
                mark.append(it)

    print(f"唯一内容 {len(groups)} 篇   保留 {len(keep)} 张   标记副本 {len(mark)} 张")
    by = collections.Counter(cat for _, cat, _ in mark)
    print("副本所在分类:", dict(by))
    if '--do' not in sys.argv:
        print("\n(dry-run，加 --do 才真做)")
        c.close()
        return

    done = 0
    for nid, cat, title in mark:
        n = c.get_note(nid)
        if '重复副本' not in n.tags:
            n.tags = list(n.tags) + ['重复副本']
        c.update_note(n)
        cids = c.db.list("select id from cards where nid=?", nid)
        if cids:
            c.sched.suspend_cards(cids)
        done += 1
    print(f"\n已处理 {done} 张（加「重复副本」标签 + 挂起）")
    print("恢复方法：去掉标签 + c.sched.unsuspend_cards(cids)")

    # 核对（维度9：不信脚本自述）
    n_susp = c.db.scalar(
        "select count() from cards where queue=-1 and nid in "
        "(select n.id from notes n join cards cd on cd.nid=n.id join decks d on d.id=cd.did "
        "where d.name like ?)", LIKE)
    n_tag = c.db.scalar(
        "select count() from notes where tags like '%重复副本%'")
    print(f"核对：库内已挂起 {n_susp} 张；带「重复副本」标签 {n_tag} 条")
    c.db.execute("pragma wal_checkpoint(truncate)")
    c.close()


if __name__ == "__main__":
    main()

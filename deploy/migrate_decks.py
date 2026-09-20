#!/usr/bin/env python3
"""牌组迁移 —— 按 04-分类体系.md 重建牌组树。

默认 **只读预览**（--dry-run），加 --apply 才真写。

做的事：
  1. 按 DECK_MAP 把每张卡挪到新牌组（只改 did，不动卡片本身）
  2. 旧牌组空了就删掉（系统默认除外）
  3. 刷 mtime / usn，让手机看得到

不动的东西（很重要）：
  - 模板 ID / ord  → 复习历史一条不丢
  - 字段内容         → 一个字不改
  - 到期日 / revlog  → 挂在卡上，跟着卡走
"""
import argparse
import collections
import json
import os
import sys
import time

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection  # noqa: E402

LIVE = "/var/lib/anki-autocards/collection.anki2"

# ── 旧牌组 → 新牌组 ────────────────────────────────────────────────
C = "C：文章保存并提炼💗"
WX = C + "::003：微信读书零散笔记💗"
NCE = C + "::001：卡霸新概念单词"
BOOK = "30：读过::30.01：书"

DECK_MAP = {
    # 30 读过 · 书
    WX + "::005：《影响力》✨✨✨✨✨🌟": BOOK + "::30.01.02：《影响力》✨✨✨✨✨🌟",
    WX + "::003：《纳瓦尔宝典》":          BOOK + "::30.01.01：《纳瓦尔宝典》",
    WX + "::001：《邓小平时代》——傅高义":  BOOK + "::30.01.03：《邓小平时代》",
    WX + "::004：《领导力》✨✨✨✨✨🌟":   BOOK + "::30.01.04：《领导力》✨✨✨✨✨🌟",
    WX + "::007：《刻意练习》":            BOOK + "::30.01.05：《刻意练习》",
    WX + "::002：《金瓶梅词话版》":        BOOK + "::30.01.06：《金瓶梅词话》",
    WX + "::006：《如何学习》":            BOOK + "::30.01.07：《如何学习》",
    WX + "::008：《被讨厌的勇气》":        BOOK + "::30.01.08：《被讨厌的勇气》",
    # 30 读过 · 文章 / 网络碎片
    C + "::002：单篇文章::知乎文章":       "30：读过::30.02：文章::30.02.01：知乎",
    C + "::002：单篇文章":                "30：读过::30.02：文章",
    C + "::002：单篇文章::一句话":         "30：读过::30.05：网络碎片",
    C + "::007：有意思的网站":             "20：在用::20.08：工具",
    # 20 在用
    C + "::008:宜人性交流的词汇变换":      "20：在用::20.02：沟通::20.02.01：情绪词汇",
    "好的历史性文章::夸奖的话":            "20：在用::20.02：沟通::20.02.02：话术",
    "好的历史性文章::提问的方式":           "20：在用::20.02：沟通::20.02.02：话术",
    "好的历史性文章":                      "20：在用::20.02：沟通::20.02.02：话术",
    # 10 在练
    "B：反复、再反复执行💗::002：行测":    "10：在练::10.02：考试::10.02.01：行测",
    "A：重要的备考经验::001：江苏经验":     "10：在练::10.02：考试::10.02.02：公考",
    "A：重要的备考经验":                   "10：在练::10.02：考试",
    "B：反复、再反复执行💗":               "10：在练",
    # 90 归档
    C + "::066：无需点开的模板":           "90：归档::90.03：模板",
    C + "::066：无需点开的模板::格致":      "90：归档::90.03：模板",
    C + "::066：无需点开的模板::示例牌组-个人免费版": "90：归档::90.03：模板",
    C + "::066：无需点开的模板::选择题❤️猪猪":        "90：归档::90.03：模板",
    "生活摘录":                            "90：归档::90.04：废卡",
    C:                                     "30：读过",
}

# ── 完整树（含空分类 = 预留位）──────────────────────────────────────
# 编号永不回收：空着不删，等你需要时它就在。
TREE = [
    "00：系统",
    "00：系统::00.01：使用说明",
    "00：系统::00.02：收件箱",
    "00：系统::00.03：待改写",
    "10：在练",
    "10：在练::10.01：语言",
    "10：在练::10.02：考试",
    "10：在练::10.03：专业",
    "10：在练::10.04：创作",
    "10：在练::10.05：身体",
    "10：在练::10.06：生活技能",
    "10：在练::10.07：心智",
    "10：在练::10.08：数字",
    "20：在用",
    "20：在用::20.01：工作",
    "20：在用::20.02：沟通",
    "20：在用::20.03：财务",
    "20：在用::20.04：健康",
    "20：在用::20.05：关系",
    "20：在用::20.06：事务",
    "20：在用::20.07：决策",
    "20：在用::20.08：工具",
    "30：读过",
    "30：读过::30.01：书",
    "30：读过::30.02：文章",
    "30：读过::30.03：课程",
    "30：读过::30.04：影像",
    "30：读过::30.05：网络碎片",
    "30：读过::30.06：典籍",
    "40：记过",
    "40：记过::40.01：事件",
    "40：记过::40.02：里程碑",
    "40：记过::40.03：感悟",
    "40：记过::40.04：人",
    "40：记过::40.05：地方",
    "40：记过::40.06：决定",
    "90：归档",
    "90：归档::90.01：外语",
    "90：归档::90.02：冷却",
    "90：归档::90.03：模板",
    "90：归档::90.04：废卡",
]

NCE_PARENT = "90：归档::90.01：外语::90.01.01：新概念英语"


def target_for(deck_name: str):
    """返回目标牌组名；返回 None 表示不动（也不报错）。"""
    if deck_name.startswith(NCE + "::"):
        leaf = deck_name[len(NCE) + 2:]
        # 新概念英语第三册词汇 (高级版) → 第三册词汇
        leaf = leaf.replace("新概念英语", "").replace("(高级版)", "").strip()
        return f"{NCE_PARENT}::{leaf}"
    if deck_name == NCE:
        return None  # 父牌组本身，0 张卡，会在清理阶段删掉
    return DECK_MAP.get(deck_name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写（默认只读预览）")
    ap.add_argument("--out", default="/tmp/migrate_preview.json")
    args = ap.parse_args()

    col = Collection(LIVE)
    try:
        dn = {d["id"]: d["name"] for d in col.decks.all()}

        # 每张卡 → 当前牌组
        plan = collections.defaultdict(list)   # (old, new) -> [cid]
        unmapped = collections.Counter()
        comp = collections.defaultdict(collections.Counter)

        for cid in col.db.list("select id from cards"):
            card = col.get_card(cid)
            old = dn.get(card.did, f"?{card.did}")
            comp[old][card.note().note_type()["name"]] += 1
            new = target_for(old)
            if new is None or new == old:
                continue
            plan[(old, new)].append(cid)

        print("=" * 78)
        print("迁移预览" + ("（--apply 会真写）" if args.apply else "（只读，没动任何东西）"))
        print("=" * 78)
        tot = 0
        for (old, new), cids in sorted(plan.items(), key=lambda x: -len(x[1])):
            tot += len(cids)
            nt = "  ".join(f"{k}:{v}" for k, v in comp[old].most_common(3))
            print(f"\n{len(cids):>5} 张   {old}")
            print(f"         →  {new}")
            if nt:
                print(f"         含 {nt}")
        print(f"\n合计移动 {tot} 张卡")

        # 没映射到的（应该只有空牌组）
        print("\n" + "-" * 78)
        print("未映射（应为空牌组 / 系统默认）:")
        moved_from = {o for (o, _n) in plan}
        for did, name in sorted(dn.items(), key=lambda x: x[1]):
            n = col.db.scalar("select count() from cards where did=?", did) or 0
            if name in moved_from or target_for(name):
                continue
            print(f"  {n:>5} 张   {name}")
            if n:
                unmapped[name] = n

        if unmapped:
            print(f"\n⚠️ 有 {sum(unmapped.values())} 张卡没有目标牌组，已中止。先补 DECK_MAP。")
            return 2

        if not args.apply:
            json.dump(
                [{"from": o, "to": n, "cards": len(c)} for (o, n), c in plan.items()],
                open(args.out, "w"), ensure_ascii=False, indent=2)
            print(f"\n预览已写到 {args.out}。加 --apply 执行。")
            return 0

        # ── 真写 ──
        deck_ids = {}
        for (_o, new) in plan:
            deck_ids[new] = col.decks.id(new)
        moved = 0
        for (old, new), cids in plan.items():
            col.set_deck(cids, deck_ids[new])
            moved += len(cids)
        print(f"\n已移动 {moved} 张卡")

        # 清理空牌组
        removed = []
        for did in list(dn):
            d = col.decks.get(did)
            if not d or d["name"] == "系统默认":
                continue
            n = col.db.scalar("select count() from cards where did=?", did) or 0
            if n == 0:
                removed.append(d["name"])
                col.decks.remove([did])
        print(f"已删除 {len(removed)} 个空牌组")

        # 建完整树（含空分类 = 预留位）
        for name in TREE:
            col.decks.id(name)
        print(f"已建完整树 {len(TREE)} 个牌组（含空分类预留位）")

        # 刷时间戳，让手机看得到（col.mod 是毫秒）
        now = int(time.time())
        for name in ("生活摘录", "生活挖空", "生活选择"):
            col.db.execute(
                f"update notetypes set mtime_secs={now}, usn=-1 where name=?", name)
        col.db.execute(f"update col set mod={now * 1000}")
        print(f"已刷 mtime_secs={now} usn=-1")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

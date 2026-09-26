#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《高性价比人生指南》(HowToLiveBetter) → Anki 卡片，确定性批量生成。

用法：
  python3 htlb2cards.py --book /tmp/HowToLiveBetter --out /tmp/htlb_p0.json --only-p0
  python3 htlb2cards.py --book /tmp/HowToLiveBetter --dry-run-5     # 只看前 5 条

设计要点（对应用户体系）：
  - 回忆型卡（观点/概念）：正面只显示【出处】→ 所以出处必须是"问题"
  - 通读型卡（方法等）  ：正面显示出【处】+【正文】
  - 正文 = 原书「说人话」段（中位 111 字，96% 在 150 字内）
  - 我的话 = 成本 + 关键数字 +（有争议则附反方）
"""
import argparse
import glob
import json
import os
import re
import sys

# 33 章 → 7 板块（按"什么时候用"归并，不是按主题）
CH2ZONE = {
    "01": "活久一点", "02": "活久一点", "16": "活久一点", "24": "活久一点", "28": "活久一点",
    "05": "守住钱", "06": "守住钱", "07": "守住钱", "12": "守住钱", "15": "守住钱",
    "19": "守住钱", "25": "守住钱",
    "08": "别进去", "09": "别进去", "11": "别进去", "14": "别进去", "26": "别进去",
    "03": "省出时间精力", "04": "省出时间精力", "22": "省出时间精力",
    "10": "家里的人", "17": "家里的人", "18": "家里的人", "20": "家里的人",
    "27": "家里的人", "30": "家里的人",
    "21": "走哪条路", "23": "走哪条路", "31": "走哪条路", "32": "走哪条路",
    "13": "出了事怎么办", "29": "出了事怎么办", "33": "出了事怎么办",
}
ZONE_NUM = {
    "活久一点": "20.09.01", "守住钱": "20.09.02", "别进去": "20.09.03",
    "省出时间精力": "20.09.04", "家里的人": "20.09.05",
    "走哪条路": "20.09.06", "出了事怎么办": "20.09.07",
}
ROOT = "20：在用::20.09：《高性价比人生指南》"


def parse_block(b):
    """解析一条建议的六段 + 成本标签"""
    lines = b.split("\n")
    # 去掉原书编号前缀「3. 」——它不属于标题，且会挡住避坑类的否定词识别
    title = re.sub(r"^\d+\.\s*", "", lines[0].strip())
    tag = re.search(r"<!--\s*成本标签:(.*?)-->", b)
    vals = dict(re.findall(r"(\S+?)=(\S+)", tag.group(1))) if tag else {}

    def seg(name):
        m = re.search(r"- %s：(.*?)(?=\n- |\n\n|\Z)" % name, b, re.S)
        return m.group(1).strip() if m else ""

    return {
        "title": title,
        "vals": vals,
        "cost": seg("成本"),
        "plain": seg("说人话"),
        "gain": seg("收益"),
        "note": seg("备注"),
        "evidence": (re.search(r"证据等级：([ABC])", b).group(1)
                     if re.search(r"证据等级：([ABC])", b) else ""),
    }


def clip(text, limit=150):
    """截断到 limit 字符，但**必须停在完整句**。

    曾经写成"超过一半才找句末，否则硬截+…"——结果正文被切成
    「…把人弄成重伤的判 3 到 10 年，弄死」，句子断在半截，很难看。
    改：只要 limit 内找得到句末标点就停在那儿（宁可短一点，不要断句）。
    """
    t = text.strip()
    if len(t) <= limit:
        return t
    best = -1
    for p in ("。", "；", "！", "？"):
        i = t[:limit].rfind(p)
        if i > best:
            best = i
    if best > 0:
        return t[:best + 1]
    return t[:limit] + "…"


def first_number_sentence(gain):
    """从收益段抓一句"人话证据"。

    优先抓含「下降/降低/低/减少/%/成」的句子 —— 那是读者能用的结论。
    避开「OR 0.39, 95% CI 0.18 到 0.83」这类纯统计术语（看不懂也记不住）。
    """
    # 注意：不能只认阿拉伯数字 —— 「六成」「一半」「降三成」全是中文数字，
    # 只匹配 \d 会漏掉最通俗的那一句，反而抓到后面的统计术语。
    KEY = r"下降|降低|低|减少|%|成|倍|省|多活|延长|死于|死亡|风险"
    sents = [s.strip() for s in re.split(r"(?<=[。；])", gain) if s.strip()]
    good = [s for s in sents if re.search(KEY, s) and len(s) >= 8]
    pick = good[0] if good else next((s for s in sents if re.search(r"\d", s)), "")
    return clip(pick, 80)


def make_question(title, ctype):
    """生成正面问题。只有避坑类能生成自然问句，其余用原标题做提示。"""
    if ctype == "避坑":
        # 只去掉「不要 / 别」——「不采、不买、不吃」是并列否定，
        # 去掉第一个「不」会变成「采…」，语义直接反了。
        m = re.match(r"^(不要|别)(.+)$", title)
        if m:
            return "%s，值不值得做？" % m.group(2).strip()
        # 避坑类是「回忆型」，正面只显示出【处】——所以绝不能把结论写进问题。
        # 反例（2026-09-26 抓到）：
        #   「不采、不买、不吃野生蘑菇，任何「土办法鉴别」都不成立 —— 为什么？」
        #   ↑「都不成立」就是答案，正面直接泄露，卡片失效。
        # 修法：问题只取标题的第一个分句，砍掉后面的结论性补充。
        head = re.split(r"[，,。；;]", title)[0].strip()
        return "%s —— 为什么？" % (head or title)
    return title


def classify(title):
    """内容类型 → (型标签, Anki 类型)"""
    if re.match(r"^(不要|别|不)", title):
        return "避坑", "观点"          # 观点 → 回忆（自测）
    if re.search(r"怎么办|如何|出了|之后|怎么救|第一步", title):
        return "流程", "方法"          # 方法 → 通读
    return "建议", "方法"


def build(path):
    """解析整本书 → 条目列表"""
    out = []
    for p in sorted(glob.glob(os.path.join(path, "book", "*.md"))):
        ch = os.path.basename(p)[:2]
        chap = os.path.basename(p)[3:-3]
        zone = CH2ZONE.get(ch, "")
        txt = open(p, encoding="utf-8").read()
        for b in re.split(r"^### ", txt, flags=re.M)[1:]:
            d = parse_block(b)
            d.update({"ch": ch, "chap": chap, "zone": zone})
            out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="/tmp/HowToLiveBetter")
    ap.add_argument("--out", default="/tmp/htlb_p0.json")
    ap.add_argument("--only-p0", action="store_true")
    ap.add_argument("--tier", choices=["p0", "p1", "p2", "c", "all"], default="all",
                    help="p0=A+益大+钱0/少 / p1=A级其余 / p2=B级 / c=C级 / all=全部")
    ap.add_argument("--skip-existing", metavar="JSON",
                    help="跳过该 JSON 里已有的出处（用于分批续写）")
    ap.add_argument("--dry-run-5", action="store_true")
    a = ap.parse_args()

    items = build(a.book)
    print("解析到条目: %d" % len(items))

    done_titles = set()
    if a.skip_existing:
        for c in json.load(open(a.skip_existing, encoding="utf-8")):
            done_titles.add(c["fields"]["出处"])

    cards = []
    for d in items:
        v = d["vals"]
        is_p0 = (d["evidence"] == "A" and v.get("收益") == "大"
                 and v.get("钱") in ("0", "少"))
        # 分档筛选
        ev, gain_v = d["evidence"], v.get("收益")
        if a.tier == "p0" and not is_p0:
            continue
        elif a.tier == "p1" and not (ev == "A" and not is_p0):
            continue
        elif a.tier == "p2" and ev != "B":
            continue
        elif a.tier == "c" and ev != "C":
            continue
        if a.only_p0 and not is_p0:
            continue
        if a.skip_existing:
            if d["title"] in done_titles or make_question(d["title"], classify(d["title"])[0]) in done_titles:
                continue
        ctype, atype = classify(d["title"])
        body = d["plain"] or d["gain"]
        num = first_number_sentence(d["gain"])

        note = []
        if d["cost"]:
            note.append("成本：%s" % clip(d["cost"], 60))
        if num:
            note.append("数据：%s" % num)
        if "争议" in d["note"]:
            m = re.search(r"(争议[：:].{0,160})", d["note"], re.S)
            if m:
                note.append("⚠️ %s" % clip(m.group(1), 160))
        if d["evidence"] == "C":
            body = "【弱证据】" + body

        tags = ["HowToLiveBetter", "证" + (d["evidence"] or "?"),
                "章-" + d["chap"], "型-" + ctype]
        for k, prefix in (("钱", "钱"), ("时间", "时"), ("毅力", "毅"), ("收益", "益")):
            if v.get(k):
                tags.append(prefix + v[k])
        if v.get("口径"):
            tags.append("口径-" + v["口径"])

        cards.append({
            "deck": "%s::%s：%s" % (ROOT, ZONE_NUM[d["zone"]], d["zone"]),
            "notetype": "生活摘录",
            "fields": {
                "正文": clip(body, 150),
                "出处": make_question(d["title"], ctype),
                "我的话": "\n".join(note)[:400],
                "类型": atype,
                "风格": "",          # 空 = 脚本按版式池轮换
                "日期": "",
                "自测": "",          # 空 = 脚本按类型推导
            },
            "tags": tags,
        })

    if a.dry_run_5:
        for c in cards[:5]:
            print("\n" + "─" * 60)
            print("牌组:", c["deck"])
            print("出处(正面问题):", c["fields"]["出处"])
            print("正文:", c["fields"]["正文"][:150])
            print("我的话:", c["fields"]["我的话"][:200])
            print("类型:", c["fields"]["类型"], "| 标签:", ",".join(c["tags"]))
        print("\n（仅预览，未写入）")
        return

    json.dump(cards, open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    from collections import Counter
    print("生成卡片: %d 张 → %s" % (len(cards), a.out))
    for z, n in Counter(c["deck"] for c in cards).most_common():
        print("  %4d  %s" % (n, z.split("::")[-1]))


if __name__ == "__main__":
    main()

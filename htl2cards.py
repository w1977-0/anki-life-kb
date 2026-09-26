#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HowToLiveLonger（程序员延寿指南）→ Anki 卡片，确定性批量生成。

切分（用户拍板 Q1/Q3）：
  - 6.1 输入：按「一级主题」切（白肉/蔬果/牛奶…）
  - 6.2 输出 / 6.3 上下文：这两节的"一级"其实是文章标题，没有主题层
    → 按「子节」切（挥拍运动/走路/睡眠…）
  - 第 5 节「行动」：单独一张总览卡

字段映射（Q4）：
  - 出处 = 主题/子节名
  - 正文 = 该主题下所有研究的结论 + 图片
  - 来源 = 中文文章标题 + 链接
  - 备注 = 英文原文标题 + 链接
  - 标签含「争议」若主题名带争议（Q6）

用法：
  python3 htl2cards.py --repo /tmp/HowToLiveLonger --dry-run 5
  python3 htl2cards.py --repo /tmp/HowToLiveLonger --out /tmp/htl.json
"""
import argparse
import json
import os
import re

ROOT = "20：在用::20.11：《程序员延寿指南》"
# 三大类（Q3）
SEC_DECK = {
    "6.1": ("20.11.01", "输入"),
    "6.2": ("20.11.02", "输出"),
    "6.3": ("20.11.03", "上下文"),
    "5":   ("20.11.04", "行动总览"),
}


def esc(s):
    """HTML 转义（裸 & / < / >）"""
    if not s:
        return s
    s = re.sub(r"&(?![a-zA-Z]+;|#\d+;)", "&amp;", s)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def inline(s):
    """行内 markdown：链接 → <a>、**粗体** → <strong>、`代码` → <code>

    2026-09-26 踩：只处理了粗体，漏了链接，导致正文里出现
    `[标题](链接)` 原始语法。
    """
    s = esc(s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def split_paras(text, max_chars=140, max_sents=5, threshold=120):
    """长段落分段，句子不切断。

    ⚠️ 含 **粗体** 的文本不切分 —— 否则 ** 会被拆到两段里，标签不成对
    （2026-09-26 踩：4 张卡的粗体因此丢失）。
    """
    t = (text or "").strip()
    if "**" in t:
        return [t] if t else []
    if len(t) <= threshold:
        return [t] if t else []
    sents = [s.strip() for s in re.split(r"(?<=[。！？；])", t) if s.strip()]
    out, cur, n = [], "", 0
    for s in sents:
        if cur and (len(cur) + len(s) > max_chars or n >= max_sents):
            out.append(cur); cur, n = s, 1
        else:
            cur += s; n += 1
    if cur:
        out.append(cur)
    return out


def link_of(s):
    """从 `[标题](链接)` 里取 (标题, 链接)"""
    m = re.match(r"^\[(.+?)\]\((.+?)\)\s*$", s.strip())
    return (m.group(1), m.group(2)) if m else (s.strip(), "")


def strip_link(s):
    """去掉 markdown 链接，只留标题"""
    return re.sub(r"\[(.+?)\]\(.+?\)", r"\1", s).strip()


def parse_evidence(readme):
    """解析「### 6. 证据」段 → [(节号, 子节名, [条目])]

    条目 = {"level":1|2|3, "text":..., "link":..., "imgs":[...]}
    """
    ev = readme[readme.find("### 6. 证据"):]
    out = []
    # 按 ##### 子节切
    blocks = re.split(r"^##### ", ev, flags=re.M)[1:]
    for b in blocks:
        name = b.split("\n")[0].strip()
        sec = name.split(".")[0] + "." + name.split(".")[1]  # 如 6.1
        items = []
        for ln in b.split("\n"):
            m = re.match(r"^(\s*)[*\-]\s+(.+)$", ln)
            if not m:
                continue
            # tab 缩进要按 4 空格算 —— 仓库里混用 tab，按 1 字符算会把深层项
            # 误判成「一级」，进而错误地切出新主题（2026-09-26 踩，辣椒卡正文空）
            indent = len(m.group(1).replace("\t", "    "))
            lv = indent // 2 + 1
            txt = m.group(2).strip()
            imgs = re.findall(r"!\[[^]]*\]\(([^)]+)\)", txt)
            txt = re.sub(r"!\[[^]]*\]\([^)]+\)", "", txt).strip()
            items.append({"level": lv, "text": txt, "imgs": imgs})
        out.append((sec, name, items))
    return out


def build_card(sec, subname, items):
    """一个子节 → 一张卡（6.1 按主题拆在 collect 里做）"""
    parts, srcs, notes, imgs = [], [], [], []
    for it in items:
        txt = it["text"]
        # 先收图片 —— 纯图片行的 txt 为空，不能提前 continue（踩过）
        for u in it["imgs"]:
            if "img.shields.io" in u:      # 徽章不是内容图
                continue
            if u not in imgs:
                imgs.append(u)
        if not txt:
            continue
        title, link = link_of(txt)
        if it["level"] == 1:
            # 一级：6.1 是主题名（进正文当小标题）；6.2/6.3 是文章标题（进来源）
            if link:
                srcs.append((title, link))
            else:
                parts.append("<p><strong>%s</strong></p>" % inline(strip_link(txt)))
        elif it["level"] == 2:
            # 二级：6.1 里是「文章标题」（有链接）→ 只进来源，不进正文
            #       6.2/6.3 里是结论（无链接）→ 进正文
            if link:
                srcs.append((title, link))
            else:
                for p in split_paras(txt):
                    parts.append("<p>%s</p>" % inline(p))
        else:
            # 三级：出处 / 结论 / 图片
            if txt.startswith("出处") or txt.startswith("["):
                notes.append(inline(strip_link(txt)))
            elif txt:
                for p in split_paras(txt):
                    parts.append("<p>%s</p>" % inline(p))
    return parts, srcs, notes, imgs


def collect(repo):
    readme = open(os.path.join(repo, "README.md"), encoding="utf-8").read()
    subs = parse_evidence(readme)
    cards = []

    # 6.1：按一级主题拆
    # ⚠️ 主题名可能在不同子节重复（如「亚精胺」在液体和药物都有、「综合」也是），
    #    重名会导致写入时互相覆盖 → 冲突的加子节名区分（2026-09-26 踩）
    from collections import Counter as _C
    _allnames = []
    for sec2, subname2, items2 in subs:
        if sec2 != "6.1":
            continue
        for it2 in items2:
            if it2["level"] == 1 and not link_of(it2["text"])[1]:
                _allnames.append(strip_link(it2["text"]))
    _dup = {k for k, v in _C(_allnames).items() if v > 1}

    for sec, subname, items in subs:
        if sec != "6.1":
            continue
        # 按一级切块
        chunks, cur = [], None
        for it in items:
            if it["level"] == 1:
                if cur: chunks.append(cur)
                cur = {"name": strip_link(it["text"]), "items": []}
            elif cur is not None:
                cur["items"].append(it)
        if cur: chunks.append(cur)
        for ch in chunks:
            if not ch["name"]:
                continue
            # 原文里有些主题只有标题/链接、没有结论（如 NMN）——正文会空，
            # Anki 模板 {{#正文}} 要求非空，这类直接跳过（2026-09-26）
            _p, _s, _n, _i = build_card(sec, subname, ch["items"])
            if not "".join(_p).strip():
                continue
            _title = ch["name"]
            if _title in _dup:
                _title = "%s（%s）" % (_title, subname.split(". ", 1)[-1])
            parts, srcs, notes, imgs = build_card(sec, ch["name"], ch["items"])
            cards.append(_mk(sec, subname, _title, parts, srcs, notes, imgs))

    # 6.2 / 6.3：按子节整张
    for sec, subname, items in subs:
        if sec not in ("6.2", "6.3"):
            continue
        parts, srcs, notes, imgs = build_card(sec, subname, items)
        title = subname.split(". ", 1)[-1].strip()
        cards.append(_mk(sec, subname, title, parts, srcs, notes, imgs))

    # 第 5 节「行动」→ 总览卡
    m = re.search(r"^### 5\. 行动\s*\n(.*?)(?=\n### |\Z)", readme, re.S | re.M)
    if m:
        body = m.group(1).strip()
        parts = []
        for ln in body.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            lv = (len(ln) - len(ln.lstrip("*")) ) // 2
            txt = re.sub(r"^[*\-]\s*", "", ln).strip()
            if not txt:
                continue
            if ln.startswith("* ") or ln.startswith("- "):
                parts.append("<p><strong>%s</strong></p>" % inline(txt))
            else:
                parts.append("<p>%s</p>" % inline(txt))
        cards.append({
            "deck": "%s::%s：%s" % (ROOT, SEC_DECK["5"][0], SEC_DECK["5"][1]),
            "notetype": "生活摘录",
            "fields": {
                "正文": "\n".join(parts), "出处": "行动总览（降 66.67% 全因死亡率）",
                "我的话": "", "类型": "方法", "风格": "", "日期": "", "自测": "",
                "来源": "HowToLiveLonger 程序员延寿指南 · 第 5 节 行动", "备注": "",
            },
            "tags": ["HowToLiveLonger", "分类-行动总览"],
            "_images": [],
        })
    return cards


def _mk(sec, subname, title, parts, srcs, notes, imgs=None):
    num, cn = SEC_DECK[sec]
    tags = ["HowToLiveLonger", "分类-" + cn]
    if "争议" in title or "争议" in subname:
        tags.append("争议")
    return {
        "deck": "%s::%s：%s" % (ROOT, num, cn),
        "notetype": "生活摘录",
        "fields": {
            "正文": "\n".join(parts),
            "出处": title,
            "我的话": "",
            "类型": "方法",
            "风格": "", "日期": "", "自测": "",
            "来源": "\n".join('<p><a href="%s">%s</a></p>' % (u, esc(ti)) if u else "<p>%s</p>" % esc(ti)
                              for ti, u in srcs) if srcs else "",
            "备注": "\n".join("<p>%s</p>" % n for n in notes) if notes else "",
        },
        "tags": tags,
        "_images": imgs or [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/HowToLiveLonger")
    ap.add_argument("--out", default="/tmp/htl.json")
    ap.add_argument("--dry-run", type=int, default=0)
    a = ap.parse_args()
    cards = collect(a.repo)
    print("生成卡片: %d" % len(cards))
    from collections import Counter
    for k, v in Counter(c["deck"].split("：")[-1] for c in cards).most_common():
        print("  %2d  %s" % (v, k))
    if a.dry_run:
        for c in cards[:a.dry_run]:
            print("\n" + "─" * 62)
            print("牌组:", c["deck"])
            print("出处:", c["fields"]["出处"], "| 标签:", ",".join(c["tags"]))
            print("--- 正文 ---")
            print(c["fields"]["正文"][:900])
            if c["fields"]["来源"]:
                print("--- 来源 ---"); print(c["fields"]["来源"][:300])
            if c["fields"]["备注"]:
                print("--- 备注 ---"); print(c["fields"]["备注"][:300])
        print("\n（仅预览，未写入）")
        return
    json.dump(cards, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", a.out)


if __name__ == "__main__":
    main()

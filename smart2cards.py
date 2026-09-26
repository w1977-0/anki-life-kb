#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《提问的智慧》(How-To-Ask-Questions-The-Smart-Way) → Anki 卡片，确定性批量生成。

切分（用户拍板 Q1/Q5）：
  - H3 一张卡（26 张，每条一条原则）
  - 有内容的 H2 各一张卡（10 张，含「相关资源」「鸣谢」）
  - 纯容器 H2（「当你提问时」0 字、「如何解读答案」17 字）自身不出卡，
    只作为牌组承载其 H3
  - 合计 36 张

分段参数：220 字 / 8 句（实测选定，见 docs 记录）

用法：
  python3 smart2cards.py --repo /tmp/SmartQuestions --dry-run 5
  python3 smart2cards.py --repo /tmp/SmartQuestions --out /tmp/smart.json
"""
import argparse
import json
import os
import re

ROOT = "20：在用::20.12：《提问的智慧》"
SRC = "README-zh_CN.md"          # Q2：简体
NAV = {"目录", "[原文版本历史](history.md)", "Contributors ✨"}
MIN_H2_CHARS = 50                # H2 自身内容少于此值不出卡（纯容器）


def esc(s):
    if not s:
        return s
    s = re.sub(r"&(?![a-zA-Z]+;|#\d+;)", "&amp;", s)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def inline(s):
    """行内 markdown：链接 → <a>、**粗体** → <strong>、`代码` → <code>"""
    s = esc(s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def split_paras(text, max_chars=220, max_sents=8, threshold=200):
    """长段落分段，句子绝不切断。

    ⚠️ 含 **粗体** 的文本不切分 —— 否则 ** 会被拆到两段里，标签不成对
    （HowToLiveLonger 踩过）。
    """
    t = (text or "").strip()
    if not t:
        return []
    if "**" in t:
        return [t]
    if len(t) <= threshold:
        return [t]
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


def body_to_html(text):
    """段落 + 列表 → HTML"""
    out = []
    lines = text.split("\n")
    buf, mode = [], None

    def flush():
        nonlocal buf, mode
        if not buf:
            mode = None; return
        if mode == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ol>")
        else:
            for p in split_paras(" ".join(buf)):
                out.append("<p>%s</p>" % inline(p))
        buf = []; mode = None

    for ln in lines:
        s = ln.rstrip()
        if re.match(r"^\s*[-*]\s+", s):
            if mode != "ul": flush(); mode = "ul"
            buf.append(re.sub(r"^\s*[-*]\s+", "", s).strip())
        elif re.match(r"^\s*\d+\.\s+", s):
            if mode != "ol": flush(); mode = "ol"
            buf.append(re.sub(r"^\s*\d+\.\s+", "", s).strip())
        elif not s.strip():
            flush()
        elif s.strip().startswith("!["):
            flush()   # 徽章类图片不进卡
        elif s.strip().startswith("#"):
            flush()
        else:
            if mode is None: mode = "p"
            buf.append(s.strip())
    flush()
    return out


def parse(repo):
    """返回 [(h2, [(h3_or_None, 内容)])]"""
    t = open(os.path.join(repo, SRC), encoding="utf-8").read()
    secs = re.split(r"^## ", t, flags=re.M)[1:]
    result = []
    for s in secs:
        name = s.split("\n")[0].strip()
        if name in NAV:
            continue
        body = s[len(name):]
        subs = re.split(r"^### ", body, flags=re.M)
        own = subs[0].strip()
        items = []
        if len(own) >= MIN_H2_CHARS:
            items.append((None, own))
        for sub in subs[1:]:
            sn = sub.split("\n")[0].strip()
            sc = sub[len(sn):].strip()
            if sc:
                items.append((sn, sc))
        result.append((name, items))
    return result


def collect(repo):
    data = parse(repo)
    cards = []
    for i, (h2, items) in enumerate(data, 1):
        deck = "%s::20.12.%02d：%s" % (ROOT, i, h2)
        for title, content in items:
            # 出处：H3 用 H3 标题；H2 自身用 H2 标题
            src_title = title if title else h2
            parts = body_to_html(content)
            if not parts:
                continue
            cards.append({
                "deck": deck,
                "notetype": "生活摘录",
                "fields": {
                    "正文": "\n".join(parts),
                    "出处": src_title,
                    "我的话": "",
                    "类型": "方法",
                    "风格": "", "日期": "", "自测": "",
                    "来源": "《提问的智慧》· %s%s" % (h2, (" / " + title) if title else ""),
                    "备注": "",
                },
                "tags": ["提问的智慧", "章节-" + h2],
            })
    return cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/SmartQuestions")
    ap.add_argument("--out", default="/tmp/smart.json")
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
            print(c["fields"]["正文"][:800])
            print("--- 来源 ---", c["fields"]["来源"])
        print("\n（仅预览，未写入）")
        return
    json.dump(cards, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→", a.out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HowToCook（程序员做饭指南）→ Anki 卡片，确定性批量生成。

设计要点（沿用《高性价比人生指南》那套标准）：
  - 单面卡（自测置空 → 通读），点击无变化
  - 原文全量进正文，不做删减
  - HTML 转义（裸 & / < / >），否则 < 后面的字会被吃掉
  - 长段落分段（≤140 字、≤5 句，句子不切断）
  - 步骤用 <ol>，原料用 <ul>（CSS 已支持）
  - 图片重命名防冲突后导入 collection.media

用法：
  python3 htc2cards.py --repo /tmp/HowToCook --out /tmp/htc.json [--cat breakfast]
  python3 htc2cards.py --repo /tmp/HowToCook --dry-run 3
"""
import argparse
import glob
import html
import json
import os
import re

ROOT = "20：在用::20.10：《程序员做饭指南》"
# 分类目录 → 中文名（编号按此顺序）
CATS = [
    ("meat_dish",      "荤菜"),
    ("vegetable_dish", "素菜"),
    ("staple",         "主食"),
    ("aquatic",        "水产"),
    ("breakfast",      "早餐"),
    ("soup",           "汤"),
    ("drink",          "饮品"),
    ("dessert",        "甜点"),
    ("semi-finished",  "半成品"),
    ("condiment",      "调料"),
]
CAT_NUM = {en: "20.10.%02d" % (i + 1) for i, (en, _) in enumerate(CATS)}
CAT_CN = dict(CATS)
TIPS_NUM = "20.10.11"


def esc(s):
    """HTML 转义。裸 & → &amp;，< → &lt;，> → &gt;。"""
    if not s:
        return s
    s = re.sub(r"&(?![a-zA-Z]+;|#\d+;)", "&amp;", s)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def split_paras(text, max_chars=140, max_sents=5, threshold=120):
    """长段落分段：按句末标点切句后聚合，句子绝不切断。"""
    t = (text or "").strip()
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


def sec(text, name):
    """取 ## 段落内容"""
    m = re.search(r"## %s\s*\n(.*?)(?=\n## |\Z)" % re.escape(name), text, re.S)
    return m.group(1).strip() if m else ""


def parse_recipe(path):
    raw = open(path, encoding="utf-8").read()
    # 标题
    t = re.search(r"^# (.+?)$", raw, re.M)
    title = t.group(1).replace("的做法", "").strip() if t else ""
    # 简介：标题后到「预估烹饪难度」
    m = re.search(r"^# .*?\n+(.+?)\n+预估烹饪难度", raw, re.S | re.M)
    intro = m.group(1).strip() if m else ""
    # 难度 / 卡路里
    diff = re.search(r"预估烹饪难度：(\S+)", raw)
    kcal = re.search(r"预估卡路里：(\S+)", raw)
    # 原料 / 计算 / 操作 / 附加
    return {
        "title": title,
        "intro": intro,
        "diff": diff.group(1) if diff else "",
        "kcal": kcal.group(1) if kcal else "",
        "ing": sec(raw, "必备原料和工具"),
        "calc": sec(raw, "计算"),
        "steps": sec(raw, "操作"),
        "extra": sec(raw, "附加内容"),
        "raw": raw,
    }


def md_list_to_html(body):
    """Markdown 无序/有序列表 → <ul>/<ol>；其余按段落处理。"""
    lines = body.split("\n")
    out, buf, mode = [], [], None

    def flush():
        nonlocal buf, mode
        if not buf:
            mode = None; return
        if mode == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % esc(x) for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join("<li>%s</li>" % esc(x) for x in buf) + "</ol>")
        else:
            out.append("<p>%s</p>" % esc(" ".join(buf)))
        buf = []; mode = None

    for ln in lines:
        s = ln.rstrip()
        if re.match(r"^\s*[-*]\s+", s):
            if mode != "ul": flush(); mode = "ul"
            buf.append(re.sub(r"^\s*[-*]\s+", "", s).strip())
        elif re.match(r"^\s*\d+\.\s+", s):
            if mode != "ol": flush(); mode = "ol"
            buf.append(re.sub(r"^\s*\d+\.\s+", "", s).strip())
        elif re.match(r"^#{3,}\s+", s):
            flush()
            out.append("<p><strong>%s</strong></p>" % esc(re.sub(r"^#+\s+", "", s)))
        elif re.match(r"^\s*!\[[^]]*\]\([^)]+\)\s*$", s):
            flush()
            mm = re.match(r"^\s*!\[[^]]*\]\(([^)]+)\)\s*$", s)
            out.append("__IMG__%s" % mm.group(1).strip())
        elif not s.strip():
            flush()
        elif s.strip().startswith(">"):
            flush()
            out.append("<p>%s</p>" % esc(s.strip().lstrip("> ").strip()))
        else:
            if mode is None: mode = "p"
            buf.append(s.strip())
    flush()
    return out


def build_body(d):
    parts = []
    # 简介（长则分段）
    if d["intro"]:
        ps = split_paras(d["intro"])
        parts.append("<p><strong>简介：</strong>%s</p>" % esc(ps[0]))
        parts += ["<p>%s</p>" % esc(x) for x in ps[1:]]
    # 难度 + 卡路里
    meta = []
    if d["diff"]: meta.append("难度 %s" % d["diff"])
    if d["kcal"]: meta.append("卡路里 %s 大卡" % d["kcal"])
    if meta:
        parts.append("<p><strong>%s</strong></p>" % esc("　".join(meta)))
    # 原料
    if d["ing"]:
        parts.append("<p><strong>必备原料和工具：</strong></p>")
        parts += md_list_to_html(d["ing"])
    # 计算
    if d["calc"]:
        parts.append("<p><strong>计算：</strong></p>")
        parts += md_list_to_html(d["calc"])
    # 操作（含子标题）
    if d["steps"]:
        parts.append("<p><strong>操作：</strong></p>")
        parts += md_list_to_html(d["steps"])
    return parts


def clean_extra(extra):
    """去掉模板句，保留真实提示"""
    if not extra:
        return ""
    s = re.sub(r"如果您遵循本指南.*?Pull request\s*。?", "", extra, flags=re.S).strip()
    s = re.sub(r"!\[[^]]*\]\([^)]*\)", "", s).strip()   # 去掉图片引用
    return s if len(s) > 10 else ""


def find_images(raw, path, title):
    """返回 [(绝对路径, 安全文件名)]。

    重命名规则：htc-<菜名>-<原名>。<ext>
    因为仓库里 1.jpeg / 1.jpg 这类名字被 20+ 道菜复用，直接导入会互相覆盖。
    """
    out, seen = [], {}
    base = os.path.dirname(path)
    for m in re.finditer(r"!\[[^]]*\]\(([^)]+)\)", raw):
        p = m.group(1).strip()
        p = p[2:] if p.startswith("./") else p
        fp = os.path.join(base, p)
        if not os.path.exists(fp):
            continue
        base_name = os.path.basename(fp)
        ext = os.path.splitext(base_name)[1].lower()
        safe = "htc-%s-%s%s" % (re.sub(r"[^\w\u4e00-\u9fff]", "", title)[:20],
                                os.path.splitext(base_name)[0][:20], ext)
        # 同一菜谱内重名再补序号
        if safe in seen:
            seen[safe] += 1
            safe = "%s-%d%s" % (os.path.splitext(safe)[0], seen[safe], ext)
        seen.setdefault(safe, 1)
        out.append((fp, safe))
    return out


def replace_md_images(body_parts, img_map):
    """把正文里残留的 ![alt](path) 换成 <img src="safe_name">"""
    out = []
    for seg in body_parts:
        def sub(m):
            raw = m.group(1).strip()
            raw = raw[2:] if raw.startswith("./") else raw
            safe = img_map.get(os.path.basename(raw))
            return '<img src="%s">' % safe if safe else ""
        seg = re.sub(r"!\[[^]]*\]\(([^)]+)\)", sub, seg)
        def sub2(m):
            raw = m.group(1).strip()
            raw = raw[2:] if raw.startswith("./") else raw
            safe = img_map.get(os.path.basename(raw))
            return '<p><img src="%s"></p>' % safe if safe else ""
        out.append(re.sub(r"__IMG__([^\s]+)", sub2, seg))
    return out


def collect(repo, only_cat=None):
    items = []
    for en, cn in CATS:
        if only_cat and en != only_cat:
            continue
        files = sorted(set(glob.glob(os.path.join(repo, "dishes", en, "*.md")))
                       | set(glob.glob(os.path.join(repo, "dishes", en, "*", "*.md"))))
        for f in files:
            if "template" in f:
                continue
            d = parse_recipe(f)
            d["cat_en"], d["cat_cn"] = en, cn
            d["path"] = f
            items.append(d)
    return items


def inline(s):
    """行内 markdown：**粗体** → <strong>（先转义再加标签）"""
    s = esc(s)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def md_to_html(body):
    """tips 用的轻量 markdown → HTML：标题/列表/引用/表格/段落。"""
    lines = body.split("\n")
    out, buf, mode = [], [], None

    def flush():
        nonlocal buf, mode
        if not buf:
            mode = None; return
        if mode == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ol>")
        elif mode == "p":
            out.append("<p>%s</p>" % inline(" ".join(buf)))
        buf = []; mode = None

    i = 0
    while i < len(lines):
        s = lines[i].rstrip()
        # 表格
        if s.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|", lines[i+1]):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if rows:
                th = "".join("<th>%s</th>" % esc(c) for c in rows[0])
                trs = "".join("<tr>" + "".join("<td>%s</td>" % esc(c) for c in r) + "</tr>"
                              for r in rows[1:] if not re.match(r"^[\s:|-]+$", "".join(r)))
                out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (th, trs))
            continue
        if re.match(r"^#{2,}\s+", s):
            flush(); out.append("<p><strong>%s</strong></p>" % esc(re.sub(r"^#+\s+", "", s)))
        elif re.match(r"^\s*[-*]\s+", s):
            if mode != "ul": flush(); mode = "ul"
            buf.append(re.sub(r"^\s*[-*]\s+", "", s).strip())
        elif re.match(r"^\s*\d+\.\s+", s):
            if mode != "ol": flush(); mode = "ol"
            buf.append(re.sub(r"^\s*\d+\.\s+", "", s).strip())
        elif s.strip().startswith(">"):
            flush(); out.append("<p>%s</p>" % esc(s.strip().lstrip("> ").strip()))
        elif not s.strip():
            flush()
        else:
            if mode is None: mode = "p"
            buf.append(s.strip())
        i += 1
    flush()
    return out


def collect_tips(repo):
    """18 篇 tips：标题 + 全文"""
    out = []
    # 只用 recursive glob —— 之前又加了根目录 glob，导致根目录 3 篇被算两次
    for p in sorted(set(glob.glob(os.path.join(repo, "tips", "**", "*.md"), recursive=True))):
        raw = open(p, encoding="utf-8").read()
        t = re.search(r"^# (.+?)$", raw, re.M)
        title = t.group(1).strip() if t else os.path.basename(p)[:-3]
        body = re.sub(r"^# .+?$", "", raw, count=1, flags=re.M).strip()
        # 去掉脚注定义
        body = re.sub(r"^\[\^\d+\]:.*$", "", body, flags=re.M).strip()
        out.append({"title": title, "body": body, "path": p})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/HowToCook")
    ap.add_argument("--out", default="/tmp/htc.json")
    ap.add_argument("--cat", default="", help="只做某个分类（如 breakfast）")
    ap.add_argument("--tips", action="store_true", help="只做 tips 18 篇")
    ap.add_argument("--dry-run", type=int, default=0)
    a = ap.parse_args()

    if a.tips:
        tips = collect_tips(a.repo)
        print("解析到 tips: %d" % len(tips))
        cards = []
        for d in tips:
            cards.append({
                "deck": "%s::%s：烹饪技法" % (ROOT, TIPS_NUM),
                "notetype": "生活摘录",
                "fields": {
                    "正文": "\n".join(md_to_html(d["body"])),
                    "出处": d["title"], "我的话": "", "类型": "方法",
                    "风格": "", "日期": "", "自测": "",
                    "来源": "HowToCook 程序员做饭指南 · %s" % d["path"].split("tips/")[-1],
                    "备注": "",
                },
                "tags": ["HowToCook", "分类-烹饪技法"],
                "_images": [],
            })
        json.dump(cards, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("生成 tips 卡片: %d → %s" % (len(cards), a.out))
        return

    items = collect(a.repo, a.cat or None)
    print("解析到菜谱: %d" % len(items))

    cards = []
    for d in items:
        body = build_body(d)
        imgs = find_images(d["raw"], d["path"], d["title"])
        img_map = {os.path.basename(fp): safe for fp, safe in imgs}
        body = replace_md_images(body, img_map)
        tags = ["HowToCook", "分类-" + d["cat_cn"]]
        if d["diff"]: tags.append("难度-" + d["diff"])
        if d["kcal"]: tags.append("卡路里-" + d["kcal"])
        cards.append({
            "deck": "%s::%s：%s" % (ROOT, CAT_NUM[d["cat_en"]], d["cat_cn"]),
            "notetype": "生活摘录",
            "fields": {
                "正文": "\n".join(body),
                "出处": d["title"],
                "我的话": "",
                "类型": "方法",
                "风格": "",
                "日期": "",
                "自测": "",
                "来源": "HowToCook 程序员做饭指南 · %s" % d["path"].split("dishes/")[-1],
                "备注": "\n".join("<p>%s</p>" % esc(x)
                                 for x in split_paras(clean_extra(d["extra"])))
                          if clean_extra(d["extra"]) else "",
            },
            "tags": tags,
            "_images": [{"path": fp, "name": safe} for fp, safe in imgs],
        })

    if a.dry_run:
        for c in cards[:a.dry_run]:
            print("\n" + "─" * 62)
            print("牌组:", c["deck"])
            print("出处:", c["fields"]["出处"])
            print("标签:", ",".join(c["tags"]))
            print("图片:", c["_images"])
            print("--- 正文 ---")
            print(c["fields"]["正文"][:900])
            if c["fields"]["备注"]:
                print("--- 备注 ---")
                print(c["fields"]["备注"][:300])
        print("\n（仅预览，未写入）")
        return

    json.dump(cards, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("生成卡片: %d → %s" % (len(cards), a.out))
    for k, v in Counter(c["deck"].split("：")[-1] for c in cards).most_common():
        print("  %3d  %s" % (v, k))
    n_img = sum(len(c["_images"]) for c in cards)
    print("  涉及图片: %d 张" % n_img)


if __name__ == "__main__":
    main()

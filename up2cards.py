#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《人生进阶指南》(byoungd/up) → Anki 卡片，确定性批量生成。

方案 A（用户 2026-09-26 拍板）：一节一卡 · 全文通读 · 整节全放
  - 切分：按 `## ` 二级标题切节（排除「本章速览」）
  - 正文：整节全文，md → HTML（表格/列表/引用/代码块全转）
  - 不拦 150 字（资料卡正文全量），版式强制 paper
  - 出处 = 小节标题（通读型正面显示出【处】+【正文】，标题即提示）

用法：
  python3 up2cards.py --repo /tmp/up --out /tmp/up_all.json
  python3 up2cards.py --repo /tmp/up --dry-run 5
"""
import argparse
import glob
import json
import os
import re

ROOT = "20：在用::20.13：《人生进阶指南》"

# part 目录 → (编号, 中文名)
PARTS = {
    "part-0": ("20.13.01", "开始"),
    "part-1": ("20.13.02", "打开输入"),
    "part-2": ("20.13.03", "把自己放回生活"),
    "part-3": ("20.13.04", "借工具放大能力"),
    "part-4": ("20.13.05", "实践与恢复"),
    "part-5": ("20.13.06", "行动与长期改变"),
    "part-6": ("20.13.07", "后记"),
}


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def inline(s):
    """行内 markdown：**粗体** → <strong>；`代码` → <code>"""
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    # 链接：**仓库内部链接（.md 相对路径）在 Anki 里点不动**，
    # 留着只会变成死链 —— 转成纯文字。外部链接保留可点。
    s = re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]+\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(body):
    """轻量 markdown → HTML：标题/列表/引用/表格/代码块/段落。"""
    lines = body.split("\n")
    out, buf, mode = [], [], None

    def flush():
        nonlocal buf, mode
        if not buf:
            mode = None
            return
        if mode == "ul":
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join("<li>%s</li>" % inline(x) for x in buf) + "</ol>")
        elif mode == "p":
            out.append("<p>%s</p>" % inline(" ".join(buf)))
        buf = []
        mode = None

    i = 0
    while i < len(lines):
        s = lines[i].rstrip()

        # 代码块
        if s.strip().startswith("```"):
            flush()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % esc("\n".join(code)))
            continue

        # 表格
        if s.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|", lines[i + 1]):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if rows:
                th = "".join("<th>%s</th>" % inline(c) for c in rows[0])
                trs = "".join("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>"
                              for r in rows[1:] if not re.match(r"^[\s:|-]+$", "".join(r)))
                out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (th, trs))
            continue

        if re.match(r"^#{3,}\s+", s):
            flush()
            out.append("<p><strong>%s</strong></p>" % esc(re.sub(r"^#+\s+", "", s)))
        elif re.match(r"^\s*[-*]\s+", s):
            if mode != "ul":
                flush()
                mode = "ul"
            buf.append(re.sub(r"^\s*[-*]\s+", "", s).strip())
        elif re.match(r"^\s*\d+\.\s+", s):
            if mode != "ol":
                flush()
                mode = "ol"
            buf.append(re.sub(r"^\s*\d+\.\s+", "", s).strip())
        elif s.strip().startswith(">"):
            flush()
            out.append("<blockquote>%s</blockquote>" % inline(s.strip().lstrip("> ").strip()))
        elif not s.strip():
            flush()
        else:
            if mode is None:
                mode = "p"
            buf.append(s.strip())
        i += 1
    flush()
    return out


def classify(title, part):
    """内容类型 → 型标签"""
    if part == "part-2" and re.search(r"故事|之后|如何面对", title):
        return "故事"
    if re.match(r"^(不要|别|不|先|把|让|用|接受|区分|保存|选择)", title):
        return "方法"
    return "原则"


def chapter_title(path):
    """取章节的 `# ` 标题（中文），用于「来源」字段和标签"""
    for line in open(path, encoding="utf-8"):
        if line.startswith("# "):
            return line[2:].strip()
    return os.path.splitext(os.path.basename(path))[0]


def split_sections(path):
    """按 `## ` 切节，返回 [(标题, 正文md)]"""
    txt = open(path, encoding="utf-8").read()
    blocks = re.split(r"^## ", txt, flags=re.M)[1:]
    out = []
    for b in blocks:
        lines = b.split("\n")
        title = lines[0].strip()
        if title.startswith("本章速览"):
            continue
        body = "\n".join(lines[1:]).strip()
        if not body:
            continue
        out.append((title, body))
    return out


def build(repo):
    cards = []
    for part, (num, cn) in sorted(PARTS.items()):
        for f in sorted(glob.glob(os.path.join(repo, "docs", "threads", part, "*.md"))):
            chap = chapter_title(f)
            for title, body in split_sections(f):
                html = "".join(md_to_html(body))
                if not html.strip():
                    continue
                ctype = classify(title, part)
                cards.append({
                    "deck": "%s::%s：%s" % (ROOT, num, cn),
                    "notetype": "生活摘录",
                    "fields": {
                        "正文": html,
                        "出处": title,
                        "我的话": "",
                        "类型": "长文",
                        "风格": "paper",
                        "日期": "",
                        "自测": "",
                    },
                    "tags": ["人生进阶指南", "部-" + cn, "章-" + re.sub(r"[：:].*$", "", chap).strip(),
                             "型-" + ctype, "完整保留", "CC-BY-NC"],
                    "_src": os.path.basename(f),
                })
    return cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/up")
    ap.add_argument("--out", default="/tmp/up_all.json")
    ap.add_argument("--dry-run", type=int, default=0)
    a = ap.parse_args()

    cards = build(a.repo)
    print("生成卡片: %d" % len(cards))

    if a.dry_run:
        for c in cards[:a.dry_run]:
            print("\n" + "─" * 62)
            print("牌组:", c["deck"].split("::")[-1])
            print("出处:", c["fields"]["出处"])
            print("标签:", ",".join(c["tags"]))
            print("正文字数:", len(c["fields"]["正文"]))
            print("正文前 300 字:", c["fields"]["正文"][:300])
        print("\n（仅预览，未写入）")
        return

    json.dump(cards, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("→ %s" % a.out)
    for z, n in Counter(c["deck"].split("::")[-1] for c in cards).most_common():
        print("  %4d  %s" % (n, z))
    # 自检：md 残留
    bad = [c["fields"]["出处"] for c in cards
           if re.search(r"\*\*|\|\s*---|^##", c["fields"]["正文"], re.M)]
    print("正文含 md 残留:", len(bad))


if __name__ == "__main__":
    main()

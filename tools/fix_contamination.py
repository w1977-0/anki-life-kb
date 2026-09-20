#!/usr/bin/env python3
"""清掉「复制粘贴污染」—— 字段里塞进的整页 HTML。

为什么必须清：`<style>` 在 HTML 里是**会被浏览器真的应用**的。
这 6 张卡的「我的话」里带着一整份页面 CSS
（`body { font-family ... max-width: 800px }` 之类），
它会覆盖 base.css 的版式 —— 卡片背面会变样。这不是脏数据，是渲染 bug。

做的事：
  1. 剥掉 `<style> / <script> / <head> / <meta> / <title> / <!DOCTYPE>` 等页面框架
  2. 保留正文级的标签（p / ul / strong / table / blockquote —— base.css 都给过样式）
  3. 把那张「故意没标 [x] 的降级测试卡」移到 90：归档::90.03：模板
     （它是测试件，不该躺在 10.02.01：行测 里）

默认 --dry-run，加 --apply 才写。
"""
import argparse
import re
import sys

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection  # noqa: E402

LIVE = "/var/lib/anki-autocards/collection.anki2"
MINE = ("生活摘录", "生活挖空", "生活选择")
TEST_DECK = "90：归档::90.03：模板"
# 那张故意没标 [x] 的降级测试卡
TEST_NOTE_ID = 1789741154071


def strip_page(v: str) -> str:
    """剥掉页面框架，保留内容级标签。"""
    if not v:
        return v
    t = v
    t = re.sub(r"(?is)<!DOCTYPE[^>]*>", "", t)
    for tag in ("style", "script", "head", "meta", "title", "link"):
        t = re.sub(r"(?is)<%s\b.*?</%s>" % (tag, tag), "", t)
        t = re.sub(r"(?is)<%s\b[^>]*/?>" % tag, "", t)
    # 有 <body> 就只留 body 里的内容
    m = re.search(r"(?is)<body[^>]*>(.*)</body>", t)
    if m:
        t = m.group(1)
    t = re.sub(r"(?is)</?(html|body)\b[^>]*>", "", t)
    # {{...}}：真 cloze（{{c1::答案}}）一个字都不能动；
    # 其余是 AI 摘要里标记「挖空重点」的花括号 —— 去括号、留文字。
    t = re.sub(r"\{\{(?!c\d+::)([^}]*)\}\}", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(LIVE)
    try:
        dn = {d["id"]: d["name"] for d in col.decks.all()}
        changed = []
        for nid in col.find_notes(""):
            n = col.get_note(nid)
            if n.note_type()["name"] not in MINE:
                continue
            dirty = False
            for k in ("正文", "我的话"):
                old = (n[k] if k in n else "") or ""
                new = strip_page(old)
                if new != old:
                    changed.append((nid, k, len(old), len(new)))
                    dirty = True
                    if args.apply:
                        n[k] = new
            if args.apply and dirty:
                col.update_note(n)

        print(f"{'已清洗' if args.apply else '待清洗'} {len(changed)} 个字段")
        for nid, k, a, b in changed:
            print(f"  note {nid}  {k}: {a} → {b} 字符")

        # 测试卡归位
        try:
            tn = col.get_note(TEST_NOTE_ID)
            cur = dn.get(tn.cards()[0].did, "?")
            print(f"\n降级测试卡 {TEST_NOTE_ID}")
            print(f"  现在：{cur}")
            print(f"  应去：{TEST_DECK}")
            if args.apply and cur != TEST_DECK:
                col.set_deck([c.id for c in tn.cards()], col.decks.id(TEST_DECK))
                print("  已移动")
        except Exception as e:
            print(f"  测试卡没找到（可能已处理）：{e}")

        if args.apply:
            import time
            now = int(time.time())
            for name in MINE:
                col.db.execute(
                    f"update notetypes set mtime_secs={now}, usn=-1 where name=?", name)
            col.db.execute(f"update col set mod={now * 1000}")
            print("\n已刷 mtime / usn")
        else:
            print("\n（只读，加 --apply 执行）")
    finally:
        col.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

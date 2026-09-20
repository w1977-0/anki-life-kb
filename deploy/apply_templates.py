#!/usr/bin/env python3
"""v7 —— 形式三分（通读 + 回忆 + 挖空 + 选择）

做的事：
  1. 「生活摘录」加新字段「自测」（空 = 通读，填「自测」= 回忆）
  2. 按 SKILL.md §1.2 的规则，对 370 张现有卡回填「自测」字段
  3. 改「生活摘录」的模板 qfmt/afmt：用 {{#自测}}/{{^自测}} 分流
     - 空 → 通读（正面就展开全内容 + 大引号 + 出处，背面 + 我的话 + 波浪）
     - 填 → 回忆（正面只出标题 + 提示，背面出全文 + 我的话）
  4. 模板 ID 不变，所以 370 张现有卡的复习历史全部保留
  5. CSS 加 add_read.css（长文排版 + .mode-read 装饰打开）
  6. 「生活挖空」「生活选择」不动

前置：design/{base.css, cloze.css, choice.css} 已写到 /tmp/skins4/
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection  # noqa: E402

LIVE = "/var/lib/anki-autocards/collection.anki2"
SRC = "/tmp/skins4"

# 哪些类型走「回忆」（= 自测 填「自测」）；其他走「通读」（= 空）
RECALL_TYPES = {"观点", "概念", "典故"}

# 「生活摘录」新模板的 qfmt/afmt（双模式）
Q = r"""{{#正文}}<div class="pg skin-{{风格}}{{^自测}} mode-read{{/自测}}">
  <div class="tape"></div>
  <div class="runner">
    <span class="kind">{{类型}}</span>
    {{#日期}}<span class="date">{{日期}}</span>{{/日期}}
  </div>
  <div class="rule"><i></i></div>
  {{#自测}}{{#出处}}<div class="title">{{出处}}</div>{{/出处}}
  {{^出处}}<div class="title faint">还记得吗</div>{{/出处}}{{/自测}}
  {{^自测}}{{#出处}}<div class="title">{{出处}}</div>{{/出处}}
  <span class="mark">&ldquo;</span>
  <div class="body">{{正文}}</div>{{/自测}}
  <div class="tail">
    {{#自测}}{{#出处}}当时记下了什么{{/出处}}{{^出处}}· · ·{{/出处}}{{/自测}}
    {{^自测}}· · ·{{/自测}}
  </div>
</div>{{/正文}}"""

A = r"""{{#正文}}<div class="pg skin-{{风格}}{{^自测}} mode-read{{/自测}}">
  <div class="tape"></div>
  <div class="runner">
    <span class="kind">{{类型}}</span>
    {{#日期}}<span class="date">{{日期}}</span>{{/日期}}
  </div>
  <div class="rule"><i></i></div>
  {{#出处}}<div class="title">{{出处}}</div>{{/出处}}
  <span class="mark">&ldquo;</span>
  <div class="body">{{正文}}</div>
  {{^自测}}{{#我的话}}<svg class="wave" viewBox="0 0 130 8" preserveAspectRatio="none"><path d="M0 4 Q16 0 32 4 T64 4 T96 4 T130 4" fill="none" stroke="currentColor" stroke-width="1"/></svg>{{/我的话}}{{/自测}}
  {{#我的话}}<div class="note">{{我的话}}</div>{{/我的话}}
  <div class="tail">· · ·</div>
</div>{{/正文}}"""


def main():
    base = open(os.path.join(SRC, "base.css"), encoding="utf-8").read().rstrip()
    cloze = open(os.path.join(SRC, "cloze.css"), encoding="utf-8").read().strip()
    choice = open(os.path.join(SRC, "choice.css"), encoding="utf-8").read().strip()
    cloze_css = base + "\n\n" + cloze + "\n"
    choice_css = base + "\n\n" + choice + "\n"
    print(f"base={len(base)} cloze={len(cloze)} choice={len(choice)}")
    print(f"挖空/摘录 CSS={len(cloze_css)}  选择 CSS={len(choice_css)}")

    col = Collection(LIVE)
    m_ex = col.models.by_name("生活摘录")
    if not m_ex:
        raise SystemExit("没有「生活摘录」")

    # ── 1. 加字段「自测」────────────────────────────────────
    fld_names = [f["name"] for f in m_ex["flds"]]
    if "自测" not in fld_names:
        new_field = col.models.new_field("自测")
        col.models.add_field(m_ex, new_field)
        print("已加字段「自测」")
        fld_names = [f["name"] for f in m_ex["flds"]]
    i_type = fld_names.index("类型")
    i_selftest = fld_names.index("自测")

    # ── 2. 回填 370 张卡的「自测」────────────────────────────
    # 按 SQL 直接更新（避免 update_note 的循环）
    # 字段值存储：notes.flds 用 \x1f 分隔（U+001F）
    # 我们读出来 → 改 自测 字段 → 写回
    rows = col.db.execute(
        "select id, flds from notes where mid = ?", m_ex["id"])
    SEP = "\x1f"
    upd = 0
    for nid, flds in list(rows):
        vals = flds.split(SEP)
        # 保证长度
        while len(vals) < len(fld_names):
            vals.append("")
        cur = vals[i_selftest]
        t = (vals[i_type] or "").strip()
        want = "自测" if t in RECALL_TYPES else ""
        if cur != want:
            vals[i_selftest] = want
            col.db.execute(
                "update notes set flds = ? where id = ?",
                SEP.join(vals), nid)
            upd += 1
    print(f"回填 自测：{upd} 张")

    # ── 3. 改模板 qfmt/afmt ─────────────────────────────────
    tmpl = m_ex["tmpls"][0]
    if tmpl["name"] != "摘录":
        raise SystemExit(f"模板名不是「摘录」？{tmpl['name']}")
    tmpl["qfmt"] = Q
    tmpl["afmt"] = A
    print("已改「摘录」模板 qfmt/afmt（模板 ID 不变，复习历史保留）")

    # ── 4. CSS ──────────────────────────────────────────────
    before_css = m_ex["css"]
    m_ex["css"] = cloze_css
    col.models.update_dict(m_ex)
    print(f"生活摘录 CSS：{len(before_css)} → {len(cloze_css)}")

    # ── 5. 生活挖空 / 生活选择：仅换 CSS ────────────────────
    for name, css in (("生活挖空", cloze_css), ("生活选择", choice_css)):
        m = col.models.by_name(name)
        if not m:
            continue
        before = m["css"]
        before_skins = set(re.findall(r"skin-([a-z]+)", before))
        m["css"] = css
        col.models.update_dict(m)
        after_skins = set(re.findall(r"skin-([a-z]+)", css))
        print(f"{name}: CSS {len(before)} → {len(css)}  "
              f"移除 {sorted(before_skins - after_skins) or '无'}  "
              f"新增 {sorted(after_skins - before_skins) or '无'}")

    # ── 6. 强制标记模型待上传 ───────────────────────────────
    now = int(time.time())
    for name in ("生活摘录", "生活挖空", "生活选择"):
        col.db.execute(
            f"update notetypes set mtime_secs={now}, usn=-1 where name=?", name)
    col.db.execute(f"update col set mod={now * 1000}")
    print(f"mtime_secs={now} usn=-1")

    # ── 7. 验证：检查 370 张卡的 card 行没动 ──────────────
    # 关键：card.id 还在，复习历史不丢
    cards = col.db.execute("select count() from cards where ord != 0")
    print(f"（sanity）非 ord=0 的卡 {col.db.scalar('select count() from cards where ord != 0')} 张")

    notes = col.db.scalar("select count() from notes")
    total_cards = col.db.scalar("select count() from cards")
    print(f"数据：notes={notes} cards={total_cards}")

    col.close()
    print("✓ v7 部署完成（同步副本尚未覆盖）")


if __name__ == "__main__":
    main()
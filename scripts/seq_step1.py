#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤 1：备份 → 加「编号」字段（末尾）→ 改正面模板 → 初始化计数器"""
import sys, os, json, shutil, datetime, sqlite3
sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection

TS = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
BK = "/var/lib/anki-autocards/backups"
os.makedirs(BK, exist_ok=True)
WORK = "/var/lib/anki-autocards/collection.anki2"
SYNC = "/var/lib/anki-autocards/sync/anki/collection.anki2"
SEQFILE = "/var/lib/anki-autocards/card_seq.json"

# ── 1) 备份 ──
shutil.copy(WORK, "%s/collection-before-seq-%s.anki2" % (BK, TS))
shutil.copy(SYNC, "%s/collection-sync-before-seq-%s.anki2" % (BK, TS))
print("[1] 库已备份 2 份")

c = Collection(WORK)

# 备份笔记类型（含模板/CSS）
bak = {}
for nt in c.models.all():
    bak[nt["name"]] = {
        "flds": [f["name"] for f in nt["flds"]],
        "tmpls": [{"n": t["name"], "q": t["qfmt"], "a": t["afmt"]} for t in nt["tmpls"]],
        "css": nt["css"],
    }
with open("%s/notetypes-before-seq-%s.json" % (BK, TS), "w", encoding="utf-8") as f:
    json.dump(bak, f, ensure_ascii=False, indent=1)
print("[2] 笔记类型已备份")

# ── 2) 加「编号」字段（★ 只加在末尾，绝不重排）──
added = []
for nt in c.models.all():
    names = [f["name"] for f in nt["flds"]]
    if "编号" in names:
        continue
    fld = c.models.new_field("编号")
    c.models.add_field(nt, fld)          # add_field 本身就追加到末尾
    c.models.save(nt)
    added.append(nt["name"])
print("[3] 已加「编号」字段（末尾）:", added)

# 复核：字段顺序里「编号」必须是最后一个
c2 = Collection(WORK)
for nt in c2.models.all():
    names = [f["name"] for f in nt["flds"]]
    assert names[-1] == "编号", "❌ %s 的编号不在末尾: %s" % (nt["name"], names)
print("[4] 复核通过：所有笔记类型的「编号」都在最后一位")

# ── 3) 改正面模板（★ 只改 qfmt，afmt 不动）──
TARGET = "生活摘录"
nt = c2.models.by_name(TARGET)
t = nt["tmpls"][0]
q_before = t["qfmt"]
a_before = t["afmt"]

if "编号" not in q_before:
    old_runner = """  <div class="runner">
    <span class="kind">{{类型}}</span>
    {{#日期}}<span class="date">{{日期}}</span>{{/日期}}
  </div>"""
    new_runner = """  <div class="runner">
    <span class="kind">{{类型}}</span>
    {{#编号}}<span class="seq">{{编号}}</span>{{/编号}}
    {{#日期}}<span class="date">{{日期}}</span>{{/日期}}
  </div>"""
    if old_runner in q_before:
        t["qfmt"] = q_before.replace(old_runner, new_runner, 1)
    else:
        # 退化：直接在 kind 后插入
        t["qfmt"] = q_before.replace(
            '<span class="kind">{{类型}}</span>',
            '<span class="kind">{{类型}}</span>\n    {{#编号}}<span class="seq">{{编号}}</span>{{/编号}}', 1)
    c2.models.save(nt)
    print("[5] 正面模板已加编号显示")
else:
    print("[5] 正面模板已有编号（跳过）")

# 复核：afmt 必须没有编号
nt2 = c2.models.by_name(TARGET)
assert "编号" not in nt2["tmpls"][0]["afmt"], "❌ 背面模板被误改！"
print("[6] 复核通过：背面模板未被改动（符合『只在正面』）")

# ── 4) 加 CSS（正面编号：最小字号 + 最淡色）──
nt3 = c2.models.by_name(TARGET)
css = nt3["css"]
if ".runner .seq" not in css:
    css += """
/* 卡片编号（正面，低调） */
.pg .runner .seq {
  font-size: var(--fs-1, 11px);
  color: var(--ink3, #a8a29a);
  letter-spacing: .08em;
  font-variant-numeric: tabular-nums;
  opacity: .75;
}
"""
    nt3["css"] = css
    c2.models.save(nt3)
    print("[7] CSS 已加 .seq 样式")
else:
    print("[7] CSS 已有 .seq（跳过）")

# ── 5) 初始化计数器 ──
if not os.path.exists(SEQFILE):
    with open(SEQFILE, "w") as f:
        json.dump({"seq": 0, "created": TS, "note": "卡片编号计数器（单调递增，删除不回收）"}, f)
    print("[8] 计数器已初始化:", SEQFILE)
else:
    print("[8] 计数器已存在:", SEQFILE, "→", open(SEQFILE).read()[:80])

# ── 6) 重置 usn（★ 上次事故的教训：改完笔记类型必须重置）──
col_usn = c2.db.scalar("select usn from col")
for r in c2.db.all("select id from notetypes where usn=-1"):
    c2.db.execute("update notetypes set usn=? where id=?", col_usn, r[0])
c2.db.execute("pragma wal_checkpoint(truncate)")
left = c2.db.scalar("select count() from notetypes where usn=-1")
print("[9] usn 已重置（剩余 usn=-1: %d）" % left)

c2.close()
print("\n=== 步骤 1 完成 ===")

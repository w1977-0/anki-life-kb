#!/usr/bin/env python3
"""把三个笔记类型当前的字段 / 模板 / CSS 快照到 docs/templates/。

只读，不写 collection。改完模板跑一次，让快照跟实际保持一致。

用法：
  sudo /opt/anki-autocards/venv/bin/python /opt/anki-autocards/docs/deploy/snapshot.py
"""
import json
import os
import sys
import time

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection  # noqa: E402

LIVE = "/var/lib/anki-autocards/collection.anki2"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")
TARGETS = ["生活摘录", "生活挖空", "生活选择"]


def main() -> int:
    col = Collection(LIVE)
    try:
        out = {}
        for nt in col.models.all():
            if nt["name"] not in TARGETS:
                continue
            out[nt["name"]] = {
                "id": nt["id"],
                "mod": nt.get("mod"),
                "fields": [{"name": f["name"], "ord": f["ord"]} for f in nt["flds"]],
                "templates": [
                    {
                        "name": t["name"],
                        "ord": t["ord"],
                        "qfmt": t["qfmt"],
                        "afmt": t["afmt"],
                    }
                    for t in nt["tmpls"]
                ],
                "css_len": len(nt.get("css", "")),
            }
    finally:
        col.close()

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "v7-templates.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"写出 {path}")
    for name, d in out.items():
        print(f"  {name}: {len(d['fields'])} 字段 / {len(d['templates'])} 模板 / css {d['css_len']} 字符")
        print(f"    字段: {' / '.join(x['name'] for x in d['fields'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

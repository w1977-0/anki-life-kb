#!/usr/bin/env python3
"""给 anki_cli.py 加「自动兜底」—— 让写卡从"容易失败"变成"写错也能救回来"。

动三处，都是**加宽不收紧**（原来会失败的，现在修好；原来能过的照样过）：

  1. 字段缺失 → 不再 `failed`，缺的补 `""`
  2. `自测` 空 → 按 `类型` 推导（观点/概念/典故 → 自测）
  3. `风格` 无效或空 → 兜底成 `kaiwu`（避免卡片变白板）

修补了什么会写进返回值的 `repairs` 字段，Hermes 汇报时能说清楚。

用法：sudo /opt/anki-autocards/venv/bin/python <本文件>
      （会先备份到 anki_cli.py.bak-autorepair-<时间戳>）
"""
import py_compile
import shutil
import sys
import time

TARGET = "/opt/anki-autocards/anki_cli.py"

# ── 1. 在 _resolve_fields 的静态段里插入兜底常量与修补函数 ──────────
ANCHOR = '''    @staticmethod
    def _resolve_fields(card: dict, field_names: list[str]) -> dict | None:'''

NEW_STATIC = '''    # 自测由类型推导：这三类走「回忆」，其余走「通读」
    RECALL_TYPES = frozenset({"观点", "概念", "典故"})
    VALID_SKINS = ("kaiwu", "gezhi", "paper", "memo")
    DEFAULT_SKIN = "kaiwu"

    @classmethod
    def _repair_fields(cls, fields: dict) -> list[str]:
        """补齐/纠正字段，返回做了哪些修补（写进返回值供汇报）。

        只修「不修就会坏」的三件事：自测、风格、以及空标题。
        正文、出处的内容一个字都不动 —— 那是用户的。
        """
        fixes = []

        # 1. 自测：留空时按类型推导
        if not (fields.get("自测") or "").strip():
            t = (fields.get("类型") or "").strip()
            if t in cls.RECALL_TYPES:
                fields["自测"] = "自测"
                fixes.append(f"自测：按类型「{t}」补为「自测」")

        # 2. 风格：无效或空 → 兜底（写错会变白板，最难发现）
        s = (fields.get("风格") or "").strip()
        if s not in cls.VALID_SKINS:
            fields["风格"] = cls.DEFAULT_SKIN
            fixes.append(f"风格：{s or '未填'} → {cls.DEFAULT_SKIN}")

        # 3. 出处：空 → 给个占位（它是卡片标题，空了顶部就没东西）
        if not (fields.get("出处") or "").strip():
            fields["出处"] = "（未标出处）"
            fixes.append("出处：未填 → 占位「（未标出处）」")

        return fixes

    @staticmethod
    def _resolve_fields(card: dict, field_names: list[str]) -> dict | None:'''

# ── 2. 缺字段不再直接失败，缺的补空 ────────────────────────────────
OLD_MISSING = '''            missing = [f for f in field_names if f not in fields]
            if missing:
                return None
            return {f: fields[f] for f in field_names}'''

NEW_MISSING = '''            missing = [f for f in field_names if f not in fields]
            # 缺字段不再整张失败 —— 补空后交给 _repair_fields 兜底
            for f in missing:
                fields[f] = ""
            return {f: fields[f] for f in field_names}'''

# ── 3. add_cards 里调用修补，并把修补记录带回 ─────────────────────
OLD_ADD = '''                self.col.add_note(note, deck_id)
                added.append({"index": idx, "note_id": str(note.id), "front": front[:60]})'''

NEW_ADD = '''                fixes = self._repair_fields(fields)
                for name, value in fields.items():
                    note[name] = value

                self.col.add_note(note, deck_id)
                entry = {"index": idx, "note_id": str(note.id), "front": front[:60]}
                if fixes:
                    entry["repairs"] = fixes
                added.append(entry)'''


def main() -> int:
    src = open(TARGET, encoding="utf-8").read()
    orig = src

    for name, old, new in (
        ("插入修补函数", ANCHOR, NEW_STATIC),
        ("缺字段补空", OLD_MISSING, NEW_MISSING),
        ("调用修补并记录", OLD_ADD, NEW_ADD),
    ):
        if new in src:
            print(f"  ⏭  {name}：已打过，跳过")
            continue
        if old not in src:
            print(f"  ❌ {name}：锚点没找到，已中止（文件没动）")
            return 2
        src = src.replace(old, new, 1)
        print(f"  ✅ {name}")

    if src == orig:
        print("\n没有变化。")
        return 0

    stamp = time.strftime("%Y%m%dT%H%M%SZ")
    backup = f"{TARGET}.bak-autorepair-{stamp}"
    shutil.copy2(TARGET, backup)
    print(f"\n已备份 → {backup}")

    open(TARGET, "w", encoding="utf-8").write(src)

    try:
        py_compile.compile(TARGET, doraise=True)
        print("✅ 语法检查通过")
    except Exception as e:
        print(f"❌ 语法错误，已回滚：{e}")
        shutil.copy2(backup, TARGET)
        return 3

    print(f"✅ 已写入 {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

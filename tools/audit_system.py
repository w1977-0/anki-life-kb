#!/usr/bin/env python3
"""全局审计 —— 用服务器上**活的**模板和 CSS 渲染**真实的**卡片，逐项 PASS/FAIL。

不是"我觉得没问题"，是跑出来给你看。

用法：
  sudo /opt/anki-autocards/venv/bin/python /opt/anki-autocards/docs/deploy/audit_system.py

检查项：A 数据基线 / B 牌组命名 / C 牌组树 / D 风格 / E 类型 / F 自测一致性
        G 出处 / H 选择题可解析 / I 模板与 CSS / J 真实渲染 / K 同步
"""
import collections
import html
import json
import os
import re
import sys

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection  # noqa: E402

LIVE = "/var/lib/anki-autocards/collection.anki2"

# 基线（2026-09-20 首次试车前）。三个数都只增不减：
#   notes/cards 涨 = 正常制卡；revlog 涨 = 用户在真机复习并同步上来了。
#   只有「跌」才是事故 —— 那意味着卡片被重建过、复习历史丢了。
EXPECT_MIN = {"notes": 3641, "cards": 6829, "revlog": 2232}
SKINS = {"kaiwu", "gezhi", "paper", "memo"}
TYPES = {"句子", "典故", "概念", "观点", "感悟", "方法", "场景", "事件", "里程碑"}
RECALL = {"观点", "概念", "典故"}          # 走回忆；其余走通读
MINE = {"生活摘录", "生活挖空", "生活选择"}
# 旧体系残留：顶层不该再出现这些（系统默认是 Anki 的 Default，合法）
LEGACY = ("A：", "B：", "C：文章", "好的历史性文章", "生活摘录")
# 模板 / 废卡里的东西是测试件，不按正式规则卡它
LOOSE = ("90：归档::90.03：模板", "90：归档::90.04：废卡")

results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))
    return ok


# ── 模板渲染（与 design/render_real.py 同一套逻辑）────────────────
COND = re.compile(r"\{\{([#^])([^}]+)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)


def esc(s):
    return html.escape(str(s), quote=False)


def render_cond(s, f):
    while True:
        innermost = None
        for cand in COND.finditer(s):
            if "{{#" not in cand.group(3) and "{{^" not in cand.group(3):
                innermost = cand
                break
        if innermost:
            sign, name, body = innermost.groups()
            keep = bool(f.get(name)) if sign == "#" else not f.get(name)
            s = s[:innermost.start()] + (body if keep else "") + s[innermost.end():]
            continue
        outer = None
        for cand in COND.finditer(s):
            if "{{#" in cand.group(3) or "{{^" in cand.group(3):
                outer = cand
                break
        if not outer:
            break
        sign, name, body = outer.groups()
        body_done = render_cond(body, f)
        keep = bool(f.get(name)) if sign == "#" else not f.get(name)
        s = s[:outer.start()] + (body_done if keep else "") + s[outer.end():]
    return s


def render(tpl, f, side, ordinal=1):
    out = render_cond(tpl, f)

    def field_sub(mo):
        return f.get(mo.group(1).split(":")[-1], "")

    out = re.sub(r"\{\{([^}{]+)\}\}", field_sub, out)

    def cloze_sub(mo):
        n, inner = mo.group(1), mo.group(2)
        ans = inner.split("::")[0]
        ordn = int(n) if n else 1
        if ordn == ordinal:
            if side == "front":
                return ('<span class="cloze" data-cloze="%s" data-ordinal="%d">[...]</span>'
                        % (esc(ans), ordn))
            return '<span class="cloze" data-ordinal="%d">%s</span>' % (ordn, esc(ans))
        return '<span class="cloze-inactive" data-ordinal="%d">%s</span>' % (ordn, esc(ans))

    return re.sub(r"\{\{c(\d*)::([^}]+)\}\}", cloze_sub, out)


def main():
    col = Collection(LIVE)
    try:
        # ══ A 数据基线 ══════════════════════════════════════
        print("\n【A】数据基线")
        got = {
            "notes": col.db.scalar("select count() from notes"),
            "cards": col.db.scalar("select count() from cards"),
            "revlog": col.db.scalar("select count() from revlog"),
        }
        for k, v in EXPECT_MIN.items():
            d = got[k] - v
            check(f"{k} >= {v}（只增不减）", got[k] >= v,
                  f"实测 {got[k]}" + (f"，比基线 +{d}" if d else "，与基线一致"))

        dn = {d["id"]: d["name"] for d in col.decks.all()}

        # ══ B 牌组命名 ══════════════════════════════════════
        print("\n【B】牌组命名（全角冒号 / 编号 / 无空格）")
        bad = []
        for name in dn.values():
            if name == "系统默认":
                continue
            for part in name.split("::"):
                if part != part.strip():
                    bad.append((name, "层级分隔符旁有空格"))
                if re.match(r"^\d", part) and "：" not in part:
                    bad.append((name, f"编号后缺全角冒号：{part}"))
                if re.search(r"\b\d{2}:", part) or re.match(r"^\d{2}:", part):
                    bad.append((name, f"用了半角冒号：{part}"))
        check("没有空格 / 缺冒号 / 半角冒号", not bad,
              f"{len(bad)} 处问题" + (f"，例：{bad[0]}" if bad else ""))

        legacy = [n for n in dn.values() if any(n.startswith(x) for x in LEGACY)]
        check("旧体系顶层已清空", not legacy, f"残留 {legacy[:3] if legacy else '无'}")

        # ══ C 牌组树 ════════════════════════════════════════
        print("\n【C】牌组树完整性")
        tops = {n.split("::")[0] for n in dn.values()} - {"系统默认"}
        need = {"00：系统", "10：在练", "20：在用", "30：读过", "40：记过", "90：归档"}
        check("六个顶层齐全", need <= tops, f"缺 {sorted(need - tops) or '无'}")
        for area, cats in (("10：在练", 8), ("20：在用", 8), ("30：读过", 6),
                           ("40：记过", 6), ("90：归档", 4)):
            have = {n for n in dn.values() if n.startswith(area + "::") and
                    n.count("::") == 1}
            check(f"{area} 有 {cats} 个类", len(have) >= cats, f"实测 {len(have)}")

        # ══ D–H 字段 ════════════════════════════════════════
        print("\n【D–H】字段合规（只看三个自制笔记类型）")
        bad_skin, bad_type, bad_self, bad_src, bad_opt = [], [], [], [], []
        bad_html = []
        # 注意用 `<head[ >]` 而不是 `<head` —— 否则 `<header>` 会误报
        PAGE = ("<style", "<meta", "<title", "<script", "<!doctype", "<head>", "<head ")
        n_mine = 0
        for nid in col.find_notes(""):
            n = col.get_note(nid)
            nt = n.note_type()["name"]
            if nt not in MINE:
                continue
            n_mine += 1
            g = lambda k: (n[k] if k in n else "")
            src = g("出处")
            deck = dn.get(n.cards()[0].did, "") if n.cards() else ""
            loose = deck.startswith(LOOSE)          # 测试件，放宽

            for k in ("正文", "我的话"):
                v = (g(k) or "").lower()
                hit = [p for p in PAGE if p in v]
                if hit:
                    bad_html.append((nid, k, hit))

            sk = g("风格")
            if sk not in SKINS and not loose:
                bad_skin.append((nid, sk))
            ty = g("类型")
            # 只有「生活摘录」的 9 个值决定形式和版式；
            # 「生活选择」的 类型是书眉标签，允许领域标签（如行测的「常识判断」）
            if nt.startswith("生活摘"):
                if ty not in TYPES and not loose:
                    bad_type.append((nid, ty))
            elif not ty.strip():
                bad_type.append((nid, "(空)"))
            if nt.startswith("生活摘"):
                want = "自测" if ty in RECALL else ""
                if g("自测") != want:
                    bad_self.append((nid, ty, g("自测")))
                if not src.strip():
                    bad_src.append(nid)
            if nt == "生活选择":
                raw = g("选项")
                xs = re.findall(r"^\s*-\s+\[[xX]\]\s+\S", raw, re.M)
                os_ = re.findall(r"^\s*-\s+\[\s\]\s+\S", raw, re.M)
                if (not xs or not os_) and not loose:
                    bad_opt.append((nid, len(xs), len(os_)))
                if not src.strip():
                    bad_src.append(nid)
        print(f"      （共 {n_mine} 条自制笔记）")
        check("风格 ∈ 四套版式", not bad_skin, f"{len(bad_skin)} 条无效"
              + (f"，例 {bad_skin[0]}" if bad_skin else ""))
        check("类型 ∈ 九个值", not bad_type, f"{len(bad_type)} 条无效")
        check("自测 与 类型 一致", not bad_self,
              f"{len(bad_self)} 条不一致" + (f"，例 {bad_self[0]}" if bad_self else ""))
        check("出处 非空", not bad_src, f"{len(bad_src)} 条为空")
        check("选择题 选项可解析", not bad_opt,
              f"{len(bad_opt)} 条解析不了" + (f"，例 {bad_opt[0]}" if bad_opt else ""))
        check("字段无整页 HTML（会注入 CSS 破坏版式）", not bad_html,
              f"{len(bad_html)} 条被污染" + (f"，例 {bad_html[0]}" if bad_html else ""))

        # ══ I 模板与 CSS ════════════════════════════════════
        print("\n【I】模板与 CSS")
        tpl, css = {}, {}
        for nt in col.models.all():
            if nt["name"] in MINE:
                tpl[nt["name"]] = nt["tmpls"][0]
                css[nt["name"]] = nt.get("css", "")
        check("三个笔记类型都在", len(tpl) == 3, f"实测 {sorted(tpl)}")
        for name, c in css.items():
            skins = set(re.findall(r"skin-([a-z]+)", c))
            check(f"{name} CSS 含四套版式", SKINS <= skins,
                  f"{len(c)} 字符，缺 {sorted(SKINS - skins) or '无'}")
        check("生活摘录 CSS 用 :root 挂令牌", ":root {" in css.get("生活摘录", ""), "")
        check("生活摘录模板有 mode-read 分流",
              "mode-read" in tpl.get("生活摘录", {}).get("qfmt", ""), "")

        # ══ J 真实渲染 ══════════════════════════════════════
        print("\n【J】真实渲染（活模板 + 活 CSS + 真卡片）")
        samples = []
        for nid in col.find_notes("deck:00：系统::00.01：使用说明"):
            samples.append(col.get_note(nid))
        # 再从每个有卡的牌组各抽一张
        seen = set()
        for cid in col.db.list("select id from cards"):
            d = dn.get(col.get_card(cid).did, "")
            if d and d not in seen:
                seen.add(d)
                samples.append(col.get_card(cid).note())
        print(f"      抽样 {len(samples)} 条")

        broken = []
        for n in samples:
            nt = n.note_type()["name"]
            if nt not in tpl:
                continue
            f = {k: (n[k] if k in n else "") for k in n.keys()}
            for side in ("front", "back"):
                key = "qfmt" if side == "front" else "afmt"
                out = render(tpl[nt][key], f, side)
                if "{{" in out:
                    broken.append((n.id, side, "有未替换的 {{"))
                if nt.startswith("生活摘") and 'class="pg' not in out:
                    broken.append((n.id, side, "缺少 .pg 容器"))
                m = re.search(r'skin-([a-z]+)', out)
                if m and m.group(1) not in SKINS:
                    broken.append((n.id, side, f"版式无效 {m.group(1)}"))
        check("渲染无残留 / 有容器 / 版式有效", not broken,
              f"{len(broken)} 处问题" + (f"，例 {broken[0]}" if broken else ""))

        # ══ K 同步 ══════════════════════════════════════════
        print("\n【K】同步")
        sync_path = "/var/lib/anki-autocards/sync/anki/collection.anki2"
        ok_sync = os.path.exists(sync_path)
        check("同步副本存在", ok_sync, sync_path)

        # ══ 汇总 ════════════════════════════════════════════
        print("\n" + "=" * 62)
        failed = [r for r in results if not r[0]]
        print(f"共 {len(results)} 项检查：通过 {len(results) - len(failed)}，失败 {len(failed)}")
        for _ok, name, detail in failed:
            print(f"  ❌ {name}  {detail}")
        print("=" * 62)
    finally:
        col.close()
    return 1 if any(not r[0] for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

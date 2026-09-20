#!/usr/bin/env python3
"""用真实模板 + 真实 CSS 渲染卡片，一张一页（避免 #quiz-root 撞 id）。

输入：
  restore/live_tmpls.json    服务器现行 生活挖空 / 生活选择 模板
  restore/orig_excerpt.json  pre-29skins 备份里 生活摘录 被污染前的原始模板
  design/base.css            新版式基础层（v6.1）
  design/add_cloze.css       挖空追加层
  design/add_choice.css      选择追加层

输出：design/render/card_NN_<标签>.html
"""
import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "render")
os.makedirs(OUT, exist_ok=True)

base = open(os.path.join(HERE, "base.css"), encoding="utf-8").read()
add_cloze = open(os.path.join(HERE, "add_cloze.css"), encoding="utf-8").read()
add_choice = open(os.path.join(HERE, "add_choice.css"), encoding="utf-8").read()

live = json.load(open(os.path.join(ROOT, "restore", "live_tmpls.json"), encoding="utf-8"))
orig = json.load(open(os.path.join(ROOT, "restore", "orig_excerpt.json"), encoding="utf-8"))

TPL = {
    "摘录": orig["生活摘录"]["tmpls"][0],     # 被污染前的原始模板
    "挖空": live["生活挖空"]["tmpls"][0],
    "选择": live["生活选择"]["tmpls"][0],
}
CSS = {
    "摘录": base + "\n\n" + add_cloze + "\n",
    "挖空": base + "\n\n" + add_cloze + "\n",
    "选择": base + "\n\n" + add_choice + "\n",
}

# ── Anki 各端默认注入的东西 —— 故意保留，用来验证我们的重置真的盖得住 ──
ANKI_DEFAULT = """
/* 模拟 Anki 桌面端/移动端注入的默认样式 */
html, body { background-color: #ffffff; }
body { margin: 0; }
.card { text-align: center; background-color: #ffffff; padding: 0; }
"""

COND = re.compile(r"\{\{([#^])([^}]+)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)


def esc(s):
    return html.escape(str(s), quote=False)


def render_cond(s, f):
    """递归处理 Anki 条件块（支持嵌套）。返回渲染好的字符串。"""
    while True:
        # 找最内层条件（body 内没有 {{# 或 {{^）
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
        # 没有最内层了——但可能还有外层（其 body 内含嵌套）。
        # 找到最左的外层，递归渲染它的 body。
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
    """Anki 模板渲染：条件块 + 字段 + cloze。"""
    out = render_cond(tpl, f)

    # 先做字段替换（{{field}} / {{text:field}} / {{cloze:field}} 都先变成原始值）
    def field_sub(mo):
        expr = mo.group(1)
        name = expr.split(":")[-1]
        return f.get(name, "")

    out = re.sub(r"\{\{([^}{]+)\}\}", field_sub, out)

    # 再处理 cloze 源码 {{cN::答案}} → 正面空位 / 背面答案
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

    out = re.sub(r"\{\{c(\d*)::([^}]+)\}\}", cloze_sub, out)
    return out


# ── 样例内容：每套版式对应它真正擅长的那一类 ────────────────────────
SAMPLES = {
    "kaiwu": {
        "类型": "概念",
        "出处": "《思考，快与慢》· 第 1 章",
        "正文": ("系统一与系统二：系统一是快速、自动、几乎不费力的直觉；"
                 "系统二慢，需要集中注意力，负责计算与自我控制。"
                 "多数判断由系统一完成，系统二只在它被叫醒时才介入。"),
        "挖空": "所谓{{c1::锚定效应}}，是指人在做估算时会被最先看到的那个数字牵着走。",
        "题干": "下面哪一项是「系统一」的特征？",
        "选项": "- [x] 快速、自动、几乎不费力\n- [ ] 需要集中注意力\n- [ ] 负责复杂计算",
        "我的话": "写方案时先给一个数字，就是在用这个。",
    },
    "gezhi": {
        "类型": "典故",
        "出处": "《论语》· 为政",
        "正文": "子曰：吾十有五而志于学，三十而立，四十而不惑，五十而知天命，六十而耳顺。",
        "挖空": "子曰：{{c1::学而不思则罔}}，思而不学则殆。",
        "题干": "这句话出自哪一篇？",
        "选项": "- [x] 为政\n- [ ] 里仁\n- [ ] 述而",
        "我的话": "",
    },
    "paper": {
        "类型": "场景",
        "出处": "《人类简史》· 序章",
        "正文": ("七万年前，智人还只是一种不起眼的动物，在非洲的角落里过着自己的日子。"
                 "接下来的几千年里，他们登上食物链顶端，成为地球史上最致命的生物。"
                 "不是因为单个智人变强了，而是因为他们学会了大规模、灵活地合作 —— "
                 "靠的是「讲故事」这种独有的能力：能让成千上万的陌生人相信同一个虚构的东西。"),
        "挖空": ("智人能登上食物链顶端，靠的不是个体变强，而是{{c1::大规模、灵活的合作}} —— "
                 "背后是「讲故事」这种独有能力。"),
        "题干": "作者认为智人崛起的关键是什么？",
        "选项": "- [x] 能大规模灵活地合作\n- [ ] 个体体力更强\n- [ ] 学会了使用火",
        "我的话": "",
    },
    "memo": {
        "类型": "句子",
        "出处": "《被讨厌的勇气》· 第三夜",
        "正文": "决定我们自身的不是过去的经历，而是我们自己赋予经历的意义。",
        "挖空": "勇气，就是{{c1::被讨厌}}的勇气。",
        "题干": "这句话最接近哪个说法？",
        "选项": "- [x] 经历本身不决定人\n- [ ] 过去决定现在\n- [ ] 意义是客观存在的",
        "我的话": "",
    },
}

PAGE = """<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>{anki}{css}</style>
<div class="card card1">
{body}
</div>
"""


def build(kind, skin, side):
    s = SAMPLES[skin]
    t = TPL[kind]
    f = {
        "正文": s["挖空"] if kind == "挖空" else s["正文"],
        "出处": s["出处"],
        "我的话": s["我的话"],
        "类型": s["类型"],
        "风格": skin,
        "日期": "2026.09.19" if skin in ("kaiwu", "memo") else "",
    }
    if kind == "选择":
        f["正文"] = s["题干"]
        f["选项"] = s["选项"]
        f["我的话"] = ""
    # 正面不显示「我的话」（真实 Anki 里它在 afmt，这里靠模板自己区分）
    tpl = t["qfmt"] if side == "front" else t["afmt"]
    body = render(tpl, f, side)
    title = f"{kind}-{skin}-{side}"
    return PAGE.format(title=title, anki=ANKI_DEFAULT, css=CSS[kind], body=body)


idx = 0
manifest = []
for kind in ("摘录", "挖空", "选择"):
    for skin in ("kaiwu", "gezhi", "paper", "memo"):
        for side in ("front", "back"):
            idx += 1
            name = f"card_{idx:02d}_{kind}_{skin}_{side}"
            path = os.path.join(OUT, name + ".html")
            open(path, "w", encoding="utf-8").write(build(kind, skin, side))
            manifest.append({"file": name + ".html", "kind": kind,
                             "skin": skin, "side": side})
json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"生成 {len(manifest)} 张 -> {OUT}")

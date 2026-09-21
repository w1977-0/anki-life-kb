#!/usr/bin/env python3
"""PDF（墨苍离系列）→ 每篇一张卡的 JSON

用法:
  python3 tools/split_vol.py <PDF> <输出.json> [封面页页数]

流程: A 目录解析 → B 全文行流分段 → C 按编号定位分界 → D 逐篇清理 → E 输出
"""
import os
import re
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from extract_vol import page_lines, WM, CJK, SEC     # 复用清洗逻辑

# ── A. 目录解析：逐行扫，编号重复即代表正文开始 ────────────────
def parse_toc(pdf, scan_pages=8):
    from pypdf import PdfReader
    r = PdfReader(pdf)
    rows = []
    for i in range(min(scan_pages, len(r.pages))):
        for ln in (r.pages[i].extract_text() or '').split('\n'):
            s = ln.strip()
            if not s or s.replace(WM, '').strip() == '':
                continue
            s = re.sub(r'(?:%s\s*)+' % WM, '', s).strip()
            if s:
                rows.append(s)

    start = next((i for i, s in enumerate(rows) if re.fullmatch(r'目\s*录', s)), 0)

    def tidy(t):
        t = re.sub(r'\s*[.．·\s]*\d{1,4}\s*$', '', t)      # 尾部点线 + 页码
        t = re.sub(r'\s*[.．·]{2,}\s*$', '', t)            # 残留点线
        t = re.sub(r'^(\d{1,3})[.、]\s*', r'\1. ', t)      # 编号后补空格
        t = re.sub(r'^标题\s*[：:]\s*', '', t)             # 目录里偶见「标题：xxx」
        return re.sub(r'\s+', ' ', t).strip()

    titles, cur = {}, None
    for s in rows[start + 1:]:
        m = re.match(r'^(\d{1,3})[.、]\s*(.*)$', s)
        if m:
            n, t = m.group(1), m.group(2)
            if n in titles:                                 # 编号重复 → 正文开始了
                break
            if cur:
                titles[cur[0]] = cur[1]
            cur = (n, t)
            continue
        if cur is None:
            continue
        cur = (cur[0], cur[1] + s)                           # 标题折行，拼回去
    if cur:
        titles[cur[0]] = cur[1]

    toc = {n: tidy(t) for n, t in titles.items()}
    return toc, sorted(toc, key=int)


# ── B. 全文行流 → (h3/p) 块 ────────────────────────────────
def build_html(pdf):
    from pypdf import PdfReader
    r = PdfReader(pdf)
    all_lines = []
    for i, p in enumerate(r.pages):
        all_lines.extend(page_lines(p, i))

    blocks, buf = [], ''
    for s in all_lines:
        num_head = bool(re.match(r'^\d{1,3}[.、]\s*\S', s))
        sec_head = bool(re.match(r'^(?:[一二三四五六七八九十]+、|Part\s*\d+)', s))
        short_head = (len(s) <= 20 and re.search(r'[？?:：]$', s))
        if num_head or sec_head or short_head:
            if buf:
                blocks.append(('p', buf))
                buf = ''
            blocks.append(('h', s))
            continue
        buf += s
        if s and s[-1] in '。！？':                          # 句末标点才收段
            blocks.append(('p', buf))
            buf = ''
    if buf:
        blocks.append(('p', buf))

    merged = []
    for kind, txt in blocks:
        txt = txt.strip()
        sec_mark = bool(re.match('^' + SEC, txt))
        if (kind == 'h' and merged and merged[-1][0] == 'h' and len(txt) < 40
                and not sec_mark                                # 小节标记另起，不并
                and not re.match(r'^\d{1,3}[.、]\s', txt)):      # 另一条编号标题，不并
            prev = merged[-1][1]
            if re.match(r'^\d{1,3}[.、]\s', prev):               # 前一条是文章标题 → 续接
                merged[-1] = ('h', prev + txt)
            elif len(prev) < 40 and not re.search(r'[。！？]', prev):
                merged[-1] = ('h', prev + txt)
            else:
                merged.append((kind, txt))
        else:
            merged.append((kind, txt))

    def esc(x):
        return x.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return ''.join(f'<h3>{esc(t)}</h3>' if k == 'h' else f'<p>{esc(t)}</p>'
                   for k, t in merged)


# ── D. 标黑启发式 ──────────────────────────────────────────
PAT_KEY = re.compile(
    r'[^。！？]{0,28}?(?:这就是|本质(?:上|是)?|真正的|真正|意味着|决定了|'
    r'不在于|问题不在|核心在于|核心问题|关键在于|结论是|记住|请记住|'
    r'真正的区别|真正的问题|更重要的是|最要紧的是)[^。！？]{0,32}。')
PAT_EXCL = re.compile(r'需要说明|需要标注|诚实地|声明|局限|样本量|免责|本文不|不代表|'
                      r'最重要的是|下面要说|注意|这一条|这一?点|简单说|一句话|比如|例如|'
                      r'^[一二三四五六七八九十]、|^\d+[.、]|年成立|年发表')
PAT_NOTBUT = re.compile(r'[^。]{0,25}不是[^。]{2,18}(?:而是|是)[^。]{2,25}。')


# 标题若以这些字收尾，说明被 PDF 折行截断了半句
DANGLING = (r'(?:里|中|上|下|后|前|时|的|了|是|在|把|让|给|对|从|向|而|并|或|就|'
            r'才|也|会|能|要|有|和|与|跟|用|被|为|但|却|还|都|只|再|又|像|如|使|'
            r'令|当|因为|所以|如果|那么|并且|还是|或者)$')


def target_n(clen):
    if clen < 3000:
        return 3
    if clen < 6000:
        return 4
    if clen < 10000:
        return 6
    return 8


def bold_key(html, max_n):
    n = 0

    def do(mo):
        nonlocal n
        inner = mo.group(1)
        if n >= max_n or '<strong>' in inner:
            return mo.group(0)
        out = []
        for s in re.split(r'(?<=[。！？])', inner):
            if not s or n >= max_n:
                out.append(s)
                continue
            ok = (12 <= len(s) <= 55 and '<strong>' not in s
                  and not PAT_EXCL.search(s)
                  and (PAT_KEY.search(s) or PAT_NOTBUT.search(s)))
            out.append(f'<strong>{s}</strong>' if ok else s)
            if ok:
                n += 1
        return '<p>' + ''.join(out) + '</p>'
    return re.sub(r'<p>([^<]*)</p>', do, html), n


def norm(x):
    return re.sub(r'[\s，。、？！：；“”‘’（）「」《》·—\-]', '', x)


def drop_title_echo(seg, title):
    """删掉正文开头那些「标题被 PDF 折行切下来的尾巴」
    例：标题折成三段 → 正文开头会留下 <p>…跨越</p><h3>鸿沟…？</h3>"""
    nt = norm(title)
    for _ in range(4):
        m = re.match(r'\s*<(h3|p)>([^<]*)</\1>', seg)
        if not m or len(m.group(2)) > 60:
            break
        frag = norm(m.group(2))
        if len(frag) < 5:
            break
        # 标题被折行切成好几块，残片可能在标题中段（不一定是尾巴）
        idx = nt.find(frag[:5])
        if idx < 0:                                  # 与标题无关 → 是正文，收手
            break
        L = 0
        while L < len(frag) and idx + L < len(nt) and nt[idx + L] == frag[L]:
            L += 1
        # 整块基本就是标题（剩下的只是副标题/署名）→ 整块删；否则视作正文，不动
        if L >= 5 and (len(frag) - L <= 20 or L >= len(frag) * 0.6):
            seg = seg[m.end():]
        else:
            break
    return seg


def main():
    pdf, out = sys.argv[1], sys.argv[2]
    scan = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    h = build_html(pdf)
    heads = [(m.start(), m.group(1), m.group(2))
             for m in re.finditer(r'<h3>(\d{1,3})[.、]\s*([^<]*)</h3>', h)]

    toc, order = parse_toc(pdf, scan)
    if toc:
        print(f'目录: {len(toc)} 条  编号 {order[0]}~{order[-1]}')
        miss = [n for n in range(int(order[0]), int(order[-1]) + 1) if str(n) not in toc]
        if miss:
            print('  ⚠️ 目录缺编号:', miss)
        from_toc = True
    else:
        from_toc = False
        # PDF 没印目录 → 用正文里的编号锚点补一份（只收严格递增的那条链）
        seq = [(p, n, t) for p, n, t in heads if not re.match(r'^0\d', n)]
        if seq:
            cur = seq[0][1]
            toc = {seq[0][1]: seq[0][2]}
            for p, n, t in seq[1:]:
                if int(n) > int(cur):
                    toc[n] = t
                    cur = n
        order = sorted(toc, key=int)
        print(f'无印本目录 → 从正文锚点补出 {len(toc)} 条  编号 {order[0]}~{order[-1]}')
        miss = [n for n in range(int(order[0]), int(order[-1]) + 1) if str(n) not in toc]
        if miss:
            print('  ⚠️ 缺编号:', miss)

    # 跳过目录块：编号连续 +1、间距很小的一段
    k = 0
    while (k + 1 < len(heads)
           and int(heads[k + 1][1]) == int(heads[k][1]) + 1
           and heads[k + 1][0] - heads[k][0] < 500):
        k += 1
    pos = heads[k][0] if k >= 1 else 0
    print(f'  目录块 {k+1} 条，正文从位置 {pos} 起')

    def sim(a, b):
        return len(set(a[:12]) & set(b[:12])) / 12 if a and b else 0.0

    arts = []
    for want in order:
        cands = [(p, n, t) for p, n, t in heads if n == want and p > pos]
        if not cands:
            print(f'  ⚠️ 第 {want} 篇在正文里定位不到')
            continue
        best = max(((sim(t, toc[want]), p, n, t) for p, n, t in cands[:8]))
        _, p, n, t = best
        arts.append((p, n, t))
        pos = p
    print(f'  文章分界: {len(arts)} 个\n')

    cards = []
    for i, (p, num, _) in enumerate(arts):
        end = arts[i + 1][0] if i + 1 < len(arts) else len(h)
        seg = h[p:end]
        title = toc.get(num, '')
        seg = re.sub(r'^<h3>\d{1,3}[.、]\s*[^<]*</h3>', '', seg, count=1)
        # 标题被截在半句（结尾是接不下去的虚词，后半段掉进了正文首句）→ 补回去
        if (from_toc is False and title and len(title) >= 10
                and not re.search(r'[。！？]$', title)
                and re.search(DANGLING, title)):
            m = re.match(r'\s*<p>([^<]*)</p>', seg)
            if m:
                first = re.split(r'(?<=[。！？])', m.group(1))[0]
                if 0 < len(first) <= 30 and len(title) + len(first) <= 62:
                    title = title + '，' + first.rstrip('。！？')
                    rest = m.group(1)[len(first):].strip()
                    seg = (seg[:m.start()] + (f'<p>{rest}</p>' if rest else '')
                           + seg[m.end():])
        seg = drop_title_echo(seg, title)
        seg = re.sub(r'文\s*/\s*墨苍离', '', seg)
        seg = re.sub(r'<h3>\s*</h3>', '', seg)
        pl = len(re.sub(r'<[^>]+>', '', seg))
        tgt = target_n(pl)
        seg2, nk = bold_key(seg, max(0, tgt))
        cards.append({'n': num, 'title': title, 'html': seg2,
                      'nkey': nk, 'tgt': tgt, 'chars': len(seg2), 'plain': pl})

    toc_html = '<h3>目 录</h3>' + ''.join(f'<h3>{n}. {toc[n]}</h3>' for n in order)
    cards.append({'n': '0', 'title': '目 录', 'html': toc_html, 'nkey': 0,
                  'tgt': 0, 'chars': len(toc_html),
                  'plain': len(re.sub(r'<[^>]+>', '', toc_html))})

    print('%-4s %-46s %7s %6s %4s' % ('篇', '标题', '纯文字', '字数', '标黑'))
    print('-' * 76)
    for c in cards:
        print('%-4s %-46s %7d %6d %4d' % (c['n'], c['title'][:44],
                                          c['plain'], c['chars'], c['nkey']))
    print('\n纯文字合计:', sum(c['plain'] for c in cards))
    json.dump(cards, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'共 {len(cards)} 张 → {out}')


if __name__ == '__main__':
    main()

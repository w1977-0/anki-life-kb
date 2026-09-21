#!/usr/bin/env python3
"""PDF → 清洗 HTML（通用，自动识别「全文每字重复两次」的编码问题并去重）

用法:
  python3 extract_vol.py <PDF路径> <输出.html> "<卷号>" "<日期>" "<篇数>"
"""
import re
import statistics
import sys
from pypdf import PdfReader

WM = '婉若游龙'
CJK = r'\u4e00-\u9fff'


def dedup_line(s):
    """若整行是「每字重复两次」的形态（PDF 字体重复绘制）→ 去重。正常行不动。"""
    t = re.sub(r'\s', '', s)
    if not t:
        return s, False
    ded = re.sub(r'(.)\1', r'\1', t)
    if len(ded) * 2 == len(t):
        return re.sub(r'(.)\1', r'\1', s), True
    return s, False


SEC = r'(?:[一二三四五六七八九十]+、|Part\s*\d+|PART\s*\d+|第[一二三四五六七八九十\d]+章)'


def clean_line(s):
    s = s.strip()
    if not s:
        return ''
    # 编号后可能粘着「?」「多余空格」（字体重绘留下的残渣）：81. ? 如何… → 81. 如何…
    m0 = re.match(r'^(\d{1,3})[.、]\s*[?？\s]+(.*\S)\s*$', s)
    if m0:
        return f'{m0.group(1)}. {m0.group(2)}'
    # 目录条目：标题 + 点线 + 页码
    m = re.match(r'^(\d{1,2})[.、]\s*(.+?)\s*[.．·\s]{4,}\s*\.?\s*\d{1,4}\s*$', s)
    if m and len(m.group(2)) > 3:
        return f'{m.group(1)}. {m.group(2).strip().rstrip(".． ")}'
    # 行内长点线
    m2 = re.match(r'^(.*?)\s*[.．·\s]{6,}.*$', s)
    if m2 and len(m2.group(1)) > 3:
        return m2.group(1).strip()


def strip_pageno(s, pageno):
    """剥掉混进正文的页码。只剥「正好等于本页页号(±1)」的孤立数字，不动正文数字。"""
    if pageno is None:
        return s
    cands = {str(pageno), str(pageno - 1), str(pageno + 1)} - {'0', '-1'}
    for _ in range(3):
        hit = False
        # 行首：数字 + 中文/标点（如「61偏样本…」「5764. 过度沉迷…」）
        m = re.match(r'^(\d{1,3})(?=[%s（(《“"\u3001])' % CJK, s)
        if m and m.group(1) in cands and len(s) > len(m.group(1)):
            s = s[m.end():]
            hit = True
        # 行中：中文 + 数字 + 中文（如「不76教你什么时候退出」）
        m = re.search(r'(?<=[%s])(\d{1,3})(?=[%s])' % (CJK, CJK), s)
        if m and m.group(1) in cands:
            s = s[:m.start()] + s[m.end():]
            hit = True
        if not hit:
            break
    return s


def page_lines(p, idx=None):
    t = p.extract_text() or ''
    raw = []
    for ln in t.split('\n'):
        s = ln.strip()
        if not s or s.replace(WM, '').strip() == '':
            continue
        s = re.sub(r'(?:%s\s*)+' % WM, '', s).strip()
        if s:
            raw.append(s)
    # 推断本页页号：该页「独立成行的数字」取最小的那个（页眉在最前）
    nums = [int(x) for x in raw[:3] if re.fullmatch(r'\d{1,4}', x)]
    pageno = nums[0] if nums else (idx + 1 if idx is not None else None)
    ls = []
    for s in raw:
        if re.fullmatch(r'\d{1,4}', s):          # 独立成行的页码，直接扔
            continue
        s, was_dedup = dedup_line(s)
        s = strip_pageno(s, pageno)
        s2 = clean_line(s) or s
        if s2:
            ls.append(s2)
    return ls


def main():
    src, out = sys.argv[1], sys.argv[2]
    vol, date, cnt = (sys.argv + ['', '', ''])[:5][2:] if len(sys.argv) > 2 else ('', '', '')

    r = PdfReader(src)
    blocks = []
    n_dedup = 0
    # 关键：先把所有页的行收成一条流，再统一分段 —— 这样跨页的段落不会被页面边界切断
    all_lines = []
    for i, p in enumerate(r.pages):
        all_lines.extend(page_lines(p, i))

    buf = ''
    for s in all_lines:
        # 标题判据：编号开头，或「一、 / Part 1」这类小节标记
        num_head = bool(re.match(r'^\d{1,3}[.、]\s*\S', s))
        sec_head = bool(re.match(r'^(?:[一二三四五六七八九十]+、|Part\s*\d+)', s))
        # 短行只在末尾是问号/冒号时才当标题，避免把折行残句误判成标题
        short_head = (len(s) <= 20 and re.search(r'[？?:：]$', s))
        if num_head or sec_head or short_head:
            if buf:
                blocks.append(('p', buf))
                buf = ''
            blocks.append(('h', s))
            continue
        buf += s
        # 段落结束：行尾是句末标点（不再看长度，也不再按页切断）
        if s and s[-1] in '。！？':
            blocks.append(('p', buf))
            buf = ''
    if buf:
        blocks.append(('p', buf))

    merged = []
    for kind, txt in blocks:
        txt = txt.strip()
        # 两个 h3 相邻 → 多半是同一个标题被 PDF 折成两行，拼回去
        sec_mark = bool(re.match('^' + SEC, txt))
        if (kind == 'h' and merged and merged[-1][0] == 'h' and len(txt) < 40
                and not sec_mark                                  # 小节标记另起，不并
                and not re.match(r'^\d{1,3}[.、]\s', txt)):       # 另一条编号标题，不并
            prev = merged[-1][1]
            if re.match(r'^\d{1,3}[.、]\s', prev):                # 前一条是文章标题 → 无条件续接
                merged[-1] = ('h', prev + txt)
            elif len(prev) < 40 and not re.search(r'[。！？]', prev):
                merged[-1] = ('h', prev + txt)
            else:
                merged.append((kind, txt))
        else:
            merged.append((kind, txt))

    def esc(x):
        return x.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    html = ''.join(f'<h3>{esc(t)}</h3>' if k == 'h' else f'<p>{esc(t)}</p>' for k, t in merged)
    open(out, 'w', encoding='utf-8').write(html)

    print('页数:', len(r.pages))
    print('块数:', len(merged), '| 标题:', sum(1 for k, _ in merged if k == 'h'),
          '| 段落:', sum(1 for k, _ in merged if k == 'p'))
    print('HTML 字符:', len(html))
    print('输出:', out)
    if vol:
        print(f'（卷 {vol} · {date} · {cnt}）')


if __name__ == '__main__':
    main()
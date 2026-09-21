#!/usr/bin/env python3
"""q9adg 的 markdown 文集 → Anki 卡片 JSON（本地跑，不碰库）

用法: python3 tools/md2cards.py <index.json> <输出.json> [分类名 ...]
     不给分类名 = 全部
"""
import re
import sys
import json
import html
import collections

ROOT = "30：读过::30.02：文章::30.02.03：q9adg"

# 标黑启发式（沿用墨苍离系列那套，实测误标率 0.3%）
PAT_KEY = re.compile(
    r'[^。！？]{0,28}?(?:这就是|这才是|这就是说|本质(?:上|是)?|真正的|真正|'
    r'意味着|决定了|不在于|问题不在|核心在于|核心问题|关键在于|结论是|记住|'
    r'更重要的是|最要紧的是|这是|结论|根本|必然是|唯一|从来没有|'
    r'无论.*?都|只有.*?才)[^。！？]{0,32}。')
PAT_EXCL = re.compile(r'需要说明|需要标注|诚实地|声明|局限|样本量|免责|本文不|不代表|'
                      r'最重要的是|下面要说|注意|这一条|这一?点|简单说|一句话|比如|例如|'
                      r'^[一二三四五六七八九十]、|^\d+[.、]|年成立|年发表')
PAT_NOTBUT = re.compile(r'[^。]{0,25}不是[^。]{2,18}(?:而是|是)[^。]{2,25}。')


def target_n(n):
    if n < 3000:
        return 3
    if n < 6000:
        return 4
    if n < 10000:
        return 6
    return 8


def esc(s):
    return html.escape(s, quote=False)


def inline(s):
    """行内 markdown → HTML（先转义，再还原标记）"""
    s = esc(s)
    s = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'[图片]', s)        # 图片 → 占位
    s = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1', s)  # 链接 → 留文字
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<![*\w])\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', s)
    return s


def comments_html(cmts):
    """爱发电评论区：hr 分隔 + h3 小标题 + blockquote（左边框灰字，与正文区分）"""
    if not cmts:
        return ''
    out = ['<hr>', f'<h3>评论 · {len(cmts)} 条</h3>']
    for c in cmts:
        who = inline(c['who'])
        txt = md2html(c['text'])
        txt = re.sub(r'^<p>(.*)</p>$', r'\1', txt, flags=re.S)
        out.append(f'<blockquote><b>{who}</b> · {inline(c["date"])}<br>{txt}</blockquote>')
    return ''.join(out)


def md2html(body):
    """按空行分段；# 开头的行当小标题"""
    out = []
    for block in re.split(r'\n\s*\n', body.strip()):
        b = block.strip()
        if not b:
            continue
        lines = [l.rstrip() for l in b.split('\n') if l.strip()]
        m = re.match(r'^#{1,6}[ \t]+(.+)$', lines[0])
        if m and len(lines) == 1:
            out.append(f'<h3>{inline(m.group(1))}</h3>')
            continue
        if all(re.match(r'^[-*+][ \t]', l) for l in lines):
            out.append('<p>' + '<br>'.join(
                inline(re.sub(r'^[-*+][ \t]+', '', l)) for l in lines) + '</p>')
            continue
        out.append('<p>' + '<br>'.join(inline(l) for l in lines) + '</p>')
    return ''.join(out)


def fallback_bold(h):
    """零命中兜底：标最后一段的末句（通常是结论句），只标 1 处，不冒险"""
    ps = re.findall(r'<p>([^<]+)</p>', h)
    for p in reversed(ps):
        sents = [s for s in re.split(r'(?<=[。！？])', p) if s.strip()]
        if not sents:
            continue
        s = sents[-1].strip()
        # 必须是以句号收尾的完整句 —— 否则会标到「事业」这类换行切碎的残片
        if s.endswith('。') and 15 <= len(s) <= 60 and '<strong>' not in p:
            i = p.rfind(s)
            if i >= 0:
                return h.replace('<p>' + p + '</p>',
                                 '<p>' + p[:i] + f'<strong>{s}</strong>' + '</p>', 1)
    return h


def bold_key(h, max_n):
    n = 0

    def do(m):
        nonlocal n
        inner = m.group(1)
        if n >= max_n or '<strong>' in inner or '<' in inner:
            return m.group(0)
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
    return re.sub(r'<p>([^<]*)</p>', do, h), n


def main():
    idx_path, out = sys.argv[1], sys.argv[2]
    cats = set(sys.argv[3:])
    items = json.load(open(idx_path, encoding='utf-8'))
    if cats:
        items = [i for i in items if i['cat'] in cats]

    cards, toc = [], collections.defaultdict(list)
    for i in items:
        title = i['title'] or i['fname'][:-3]
        h = md2html(i['body'])
        plain = len(re.sub(r'<[^>]+>', '', h))
        h2, nk = bold_key(h, target_n(plain))
        if nk == 0:                       # 一篇都没标到 → 兜底标末段结论句
            h2 = fallback_bold(h)
            nk = h2.count('<strong>')
        # 评论附在正文下方（不参与标黑）
        ch = comments_html(i.get('comments') or [])
        h2 = h2 + ch
        plain += len(re.sub(r'<[^>]+>', '', ch))
        src = f'{title} ｜ {i["refer"]}' if i['refer'] else title
        tags = ['q9adg', i['cat']] + list(dict.fromkeys(i['tags']))
        cards.append({'deck': ROOT + '::' + i['cat'], 'cat': i['cat'],
                      'title': title, 'src': src, 'html': h2,
                      'plain': plain, 'nkey': nk, 'tags': tags})
        toc[i['cat']].append(title)

    for c, titles in toc.items():
        h = '<h3>目 录</h3>' + ''.join(f'<h3>{esc(t)}</h3>' for t in titles)
        cards.append({'deck': ROOT + '::' + c, 'cat': c, 'title': '目录',
                      'src': '目录', 'html': h,
                      'plain': len(re.sub(r'<[^>]+>', '', h)), 'nkey': 0,
                      'tags': ['q9adg', c, '目录']})

    print(f'卡片 {len(cards)} 张（正文 {len(cards)-len(toc)} + 目录 {len(toc)}）')
    print(f'总字数 {sum(c["plain"] for c in cards):,}   标黑 {sum(c["nkey"] for c in cards)} 处')
    bad = [(c['cat'], c['title'], c['plain']) for c in cards
           if c['title'] != '目录' and (c['plain'] < 200 or c['nkey'] == 0)]
    print(f'可疑（<200字 或 零标黑）: {len(bad)} 篇')
    for b in bad[:8]:
        print('   ', b)
    json.dump(cards, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print('→', out)


if __name__ == '__main__':
    main()

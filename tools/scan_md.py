#!/usr/bin/env python3
"""扫描 q9adg 的 markdown 文集 → 清单 JSON（不写库，只摸底）

用法: python3 tools/scan_md.py <目录> <输出.json>
"""
import os
import re
import sys
import json
import collections

SKIP_DIR = {'.assets', '__pycache__', '.git'}


def parse(path):
    """返回 dict：title / refer / body / tags / chars / 异常标记"""
    try:
        raw = open(path, encoding='utf-8').read()
    except UnicodeDecodeError:
        try:
            raw = open(path, encoding='utf-8', errors='replace').read()
            enc_bad = True
        except Exception as e:
            return {'err': f'读取失败 {e}'}
    else:
        enc_bad = False

    d = {'title': '', 'refer': '', 'body': '', 'tags': [], 'chars': 0,
         'enc_bad': enc_bad, 'warn': []}

    # 注意：[ \t] 而不是 \s —— 否则「##」后面是空行时会把下一行（### Refer）当成标题
    m = re.search(r'^##[ \t]+(.+?)[ \t]*$', raw, re.M)
    if m:
        d['title'] = m.group(1).strip()
    else:
        d['warn'].append('无 ## 标题')

    m = re.search(r'^###\s*Refer\s*$\s*(.+?)\s*$', raw, re.M | re.I)
    if m:
        d['refer'] = m.group(1).strip()

    # 结束条件含 ^## —— 否则会把「## 评论」（爱发电评论）整段吃进正文
    m = re.search(r'^###\s*正文\s*$(.*?)(?=^#{2,3}\s|\Z)', raw, re.M | re.S)
    body = m.group(1).strip() if m else ''
    if not body:
        # 退一步：没有「### 正文」就取去掉头部后的全部
        body = re.sub(r'^##\s+.+?$', '', raw, count=1, flags=re.M)
        body = re.sub(r'^###\s*Refer\s*$.*?(?=^#|\Z)', '', body, flags=re.M | re.S)
        body = body.strip()
        if body:
            d['warn'].append('无 ### 正文 段（已回退取全文）')

    # 只从「标题+正文」取标签 —— 整个 raw 含爱发电评论段，评论里的 #标签# 会串进来
    d['tags'] = re.findall(r'#([^#\s\n]{1,10})#', (d['title'] or '') + '\n' + body)
    d['body'] = body

    # 爱发电的「## 评论」段：不是正文，但是有价值的补充，单独存起来附在正文下方
    cm = re.search(r'^##\s*评论\s*$\s*(.*)', raw, re.M | re.S)
    cmts = []
    if cm:
        for dt, who, txt in re.findall(
                r'^#####\s*<span>\[\d+\]\s*([\d\-: ]+?)\s*by\s*(.+?)</span>\s*\n+(.*?)'
                r'(?=^-{3,}|\Z)', cm.group(1), re.M | re.S):
            t = txt.strip()
            t = re.sub(r'\n\s*\n+', '\n\n', t)
            if t:
                cmts.append({'date': dt.strip(), 'who': who.strip(), 'text': t})
    d['comments'] = cmts
    d['chars'] = len(re.sub(r'\s', '', body))
    if d['chars'] < 300:
        d['warn'].append(f'正文过短({d["chars"]}字)')
    return d


def main():
    root, out = sys.argv[1], sys.argv[2]
    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
        for fn in sorted(filenames):
            if not fn.endswith('.md') or fn == '.DS_Store':
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            cat = rel.split(os.sep)[0] if os.sep in rel else '(根)'
            d = parse(p)
            d.update(path=p, rel=rel, cat=cat, fname=fn,
                     size=os.path.getsize(p))
            items.append(d)

    cats = collections.Counter(i['cat'] for i in items)
    warns = collections.Counter(w for i in items for w in i['warn'])

    print(f'文件总数: {len(items)}')
    print(f'总字数: {sum(i["chars"] for i in items):,}')
    print('\n分类分布:')
    for c, n in cats.most_common():
        sub = [i for i in items if i['cat'] == c]
        print(f'  {c:<14} {n:>4} 篇   平均 {sum(x["chars"] for x in sub)//max(n,1):>5} 字')
    print('\n异常标记:')
    for w, n in warns.most_common():
        print(f'  {w:<26} {n}')

    small = [i for i in items if i['size'] < 1024]
    print(f'\n⚠️ 小于 1KB 的文件: {len(small)} 个（G 项待你定夺）')
    for i in small:
        print(f'   {i["rel"][:52]:<54} {i["size"]:>5}B  正文{i["chars"]}字  {i["title"][:24]}')

    json.dump(items, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'\n清单 → {out}')


if __name__ == '__main__':
    main()

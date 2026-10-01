#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-10-01 技能补丁（第二批，2 处）。

第一批已成功 3 处（图片禁令 / 出处占位符 / 查重加固），
这批补上因锚点不匹配而跳过的 2 处。

跑法：sudo python3 /tmp/patch_skill2.py

锚点取自服务器实测行号（v6.3.1 / 23555 字节）：
  · 227 行：以「长文必须用 --body-file」开头的那一行
  · 323 行：Pitfalls 章节标题
"""
import datetime
import os
import shutil

SKILL_MD = "/home/hermes/.hermes/skills/note-taking/anki-cards/SKILL.md"
TS = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
report = []

SRC_REMARK = '''**来源 / 备注 两个字段（2026-10-01 加）**

这两个字段 2026-09-26 就加进笔记类型了，但**到 10-01 为止 255 张卡一张都没填过**
—— 因为 SKILL.md 从来没写过它们，agent 根本不知道有。

| 字段 | 参数 | 什么时候填 |
|---|---|---|
| **来源** | `--origin` | **知道原始链接/出处时**：网址、期刊、DOI、公众号名。转发来的内容尽量填 |
| **备注** | `--remark` | 争议、例外、适用人群、待核实事项 |

⚠️ `--source` 是**出处（卡片标题）**，跟 `--origin`（来源）**不是一回事**，别混。

```bash
... --source "网络观点·异性相处紧张源于馋身子" \\
    --origin "https://example.com/article/123" \\
    --remark "样本量小，仅一项队列研究"
```

'''

RETRY_RULE = '''## ⚠️ 被查重拦下 → 停手（2026-10-01 加）

**被查重拦下，绝对不要换个版式重试。**

2026-09-30 真实发生：「网络观点·异性相处紧张源于馋身子」在 08:41 和 08:44
各写了一次，**正文一字不差**，只有版式不同（gezhi / paper）—— 这就是重试造成的重复卡。

查重是按**正文内容**比的。换版式绕不过去，但**重试时顺手改一下措辞就绕过去了**。

所以：**被拦下就停** —— 不要重试、不要改写、不要换版式，
如实告诉用户「这段之前记过」。

'''

ANCHOR_BODYFILE = "**长文必须用 `--body-file`**（命令行单参数上限 128KB，超了会 `OSError`）；正文分段用 `\\n\\n`，脚本自动转 `<p>`。"
ANCHOR_PITFALLS = "\n## Pitfalls\n"

path = SKILL_MD
if not os.path.exists(path):
    print("✗ 找不到 %s" % path)
    raise SystemExit(1)

src = open(path, encoding="utf-8").read()
orig = src

for label, anchor, block, before in (
    ("① 补 来源/备注 字段用法", ANCHOR_BODYFILE, SRC_REMARK, True),
    ("② 补 被查重拦下→停手", ANCHOR_PITFALLS, RETRY_RULE, True),
):
    if block.split("\n")[0] in src or block.split("\n")[0][:14] in src:
        report.append("  · %s：看起来已经改过了，跳过" % label)
        continue
    if anchor not in src:
        report.append("  ⚠ %s：锚点没找到，跳过" % label)
        continue
    src = src.replace(anchor, block + anchor, 1)
    report.append("  ✓ %s" % label)

if src != orig:
    d = os.path.join(os.path.dirname(path), ".backup-%s" % TS)
    os.makedirs(d, exist_ok=True)
    shutil.copy2(path, os.path.join(d, "SKILL.md.batch2"))
    open(path, "w", encoding="utf-8").write(src)
    report.append("    已备份 → %s" % d)
else:
    report.append("  （无改动）")

print("=" * 58)
print("第二批补丁结果（%s）" % TS)
print("=" * 58)
for line in report:
    print(line)
print()
print("文件大小：%d 字节" % len(src.encode("utf-8")))
print()
print("接着必须重启网关：sudo systemctl restart hermes-gateway")

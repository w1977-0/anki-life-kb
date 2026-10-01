#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-10-01 技能补丁：四处改动。

跑法（在服务器上）：
    sudo python3 /tmp/patch_skill_20261001.py

会自动备份到 <技能目录>/.backup-<时间戳>/ 和 /opt/anki-autocards/backups/

四处改动：
  1. SKILL.md   新增「收到图片怎么办」——禁止 OCR 瞎试
  2. SKILL.md   补上 来源/备注 两个字段的用法（参数早就有，文档没写）
  3. SKILL.md   强化「被查重拦下不要换版式重试」
  4. anki_add.py  出处占位符拦死「网络」，改为要求「网络观点·<主题>」
  5. anki_cli.py  查重加固：去 HTML、探针加长、失败打日志（不再静默）
"""
import datetime
import os
import re
import shutil
import sys

SKILL_DIR = "/home/hermes/.hermes/skills/note-taking/anki-cards"
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
ANKI_ADD = os.path.join(SKILL_DIR, "scripts", "anki_add.py")
ANKI_CLI = "/opt/anki-autocards/anki_cli.py"

TS = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
report = []


def backup(path, tag):
    d = os.path.join(os.path.dirname(path), ".backup-%s" % TS)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.basename(path) + "." + tag)
    shutil.copy2(path, dst)
    return dst


def patch(path, tag, edits):
    """edits: [(说明, 旧串, 新串)]，找不到旧串就跳过并报告"""
    if not os.path.exists(path):
        report.append("✗ 找不到文件：%s" % path)
        return
    src = open(path, encoding="utf-8").read()
    orig = src
    for label, old, new in edits:
        if old not in src:
            report.append("  ⚠ %s：锚点没找到，跳过（可能已被改过）" % label)
            continue
        if new in src:
            report.append("  · %s：已经改过了，跳过" % label)
            continue
        src = src.replace(old, new, 1)
        report.append("  ✓ %s" % label)
    if src != orig:
        b = backup(path, tag)
        open(path, "w", encoding="utf-8").write(src)
        report.append("    已备份 → %s" % b)
    else:
        report.append("  （%s 无改动）" % os.path.basename(path))


# ─────────────────────────────────────────────────────────
# 1–3. SKILL.md
# ─────────────────────────────────────────────────────────

IMG_SECTION = '''
---

## ⛔ 收到图片怎么办（2026-10-01 加，真实踩过）

**当前模型是纯文本的，看不了图。所以：**

1. **不要尝试 OCR** —— 不要装库、不要写脚本、不要试 `rapidocr` / `tesseract` /
   任何图像处理库。一次都不要试。
2. **不要连续重试** —— 这条路根本不通，重试只是浪费用户时间。
3. **直接回复用户**，照这个意思说：

> 图片我暂时读不了（当前模型不支持看图）。麻烦你把图里的文字**直接发成文本**，
> 我立刻做成卡片。

**为什么写死这条**：2026-10-01 用户发了一张图，agent 去试 OCR ——
先 `import rapidocr_onnxruntime`（没装）→ 自己写 `ocr_slices.py` → 连崩三次
（163 秒 / 273 秒 / 308 秒）→ 又被写文件保护和 lifecycle guard 各拦一次。
**整整 20 分钟，一张卡没产出。**

'''

SRC_REMARK = '''**④ 来源 / 备注 两个字段（2026-10-01 加）**

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

RETRY_RULE = '''**被查重拦下，绝对不要换个版式重试。**

2026-09-30 真实发生：「网络观点·异性相处紧张源于馋身子」在 08:41 和 08:44
各写了一次，**正文一字不差**，只有版式不同（gezhi / paper）—— 这就是重试造成的重复卡。

查重是按**正文内容**比的。换版式绕不过去，但**重试时顺手改一下措辞就绕过去了**。
所以：**被拦下就停**，如实告诉用户「这段之前记过」，不要重试、不要改写、不要换版式。

'''

patch(SKILL_MD, "skills", [
    ("① 新增「收到图片怎么办」",
     "\n---\n\n## When to Use\n",
     IMG_SECTION + "\n---\n\n## When to Use\n"),
    ("② 补 来源/备注 字段用法",
     "**长文必须用 `--body-file`，不能用 `--body`：**",
     SRC_REMARK + "**长文必须用 `--body-file`，不能用 `--body`：**"),
    ("③ 强化「被查重拦下不要重试」",
     "**`--whole` 该进哪个牌组（别搞错类别）：**",
     RETRY_RULE + "**`--whole` 该进哪个牌组（别搞错类别）：**"),
])

# ─────────────────────────────────────────────────────────
# 4. anki_add.py —— 出处占位符拦死「网络」
# ─────────────────────────────────────────────────────────

patch(ANKI_ADD, "scripts", [
    ("④ 出处：把「网络」也列为占位符",
     'BAD_SOURCE = {"", "一句话", "未知", "无", "none", "None", "null", "-", "??"}',
     'BAD_SOURCE = {"", "一句话", "未知", "无", "none", "None", "null", "-", "??",\n'
     '              "网络", "网络观点", "网上", "互联网"}'),
    ("④b 出处报错提示：教它写描述性标题",
     '''    if (a.source or "").strip() in BAD_SOURCE:
        fail(f"出处「{a.source}」是占位符，不能当来源。\\n"
             f"      出处要写真实来源：书名《…》/ 平台（知乎、B站、微博）/ 场景。\\n"
             f"      实在不知道 → 写「网络」，牌组用 30：读过::30.05：网络碎片。")''',
     '''    if (a.source or "").strip() in BAD_SOURCE:
        fail(f"出处「{a.source}」是占位符，不能当来源。\\n"
             f"      出处是卡片顶部标题，要能一眼看出这条讲什么。\\n"
             f"      ① 知道真实来源 → 书名《…》/ 平台文章标题 / 课程名\\n"
             f"      ② 不知道来源（网上看到的观点）→ 写「网络观点·<一句话主题>」\\n"
             f"         例：网络观点·异性相处紧张源于馋身子\\n"
             f"      ③ 自己的想法 → 触发场景，如「读完《被讨厌的勇气》想到的」\\n"
             f"      ❌ 不要写「网络」「知乎」这种纯平台名 —— 同一牌组里会全是重名。")'''),
])

# ─────────────────────────────────────────────────────────
# 5. anki_cli.py —— 查重加固
# ─────────────────────────────────────────────────────────

OLD_DUP = '''    def _is_duplicate(self, front: str) -> bool:
        probe = " ".join(front.split())[:60]
        if not probe:
            return False
        try:
            return bool(self.col.find_notes(f'"{probe}"'))
        except Exception:
            return False  # 搜索语法出错不应阻断写入'''

NEW_DUP = '''    def _is_duplicate(self, front: str) -> bool:
        """正文前若干字的全库短语搜索。

        2026-10-01 加固三处：
          ① 先剥 HTML 标签 —— 正文是 <p><strong>…</strong></p>，带标签的探针
             更容易踩到搜索语法边界；
          ② 探针里不能留双引号，否则整条查询变非法语法（会走 except）；
          ③ 搜索失败不再静默 —— 静默失败等于查重悄悄失效，永远发现不了。
        """
        plain = re.sub(r"<[^>]+>", "", front or "")
        probe = " ".join(plain.split())[:80].replace('"', " ").strip()
        if not probe:
            return False
        try:
            return bool(self.col.find_notes('"%s"' % probe))
        except Exception as e:
            print(f"（警告）查重搜索失败，本次按「不重复」处理："
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            return False'''

patch(ANKI_CLI, "cli", [
    ("⑤ 查重加固（去 HTML / 加长 / 失败留痕）", OLD_DUP, NEW_DUP),
])

# 确保 anki_cli.py 顶部有 import re
if os.path.exists(ANKI_CLI):
    t = open(ANKI_CLI, encoding="utf-8").read()
    if not re.search(r"^import re$", t, re.M):
        t2 = re.sub(r"^(import fcntl\n)", r"\1import re\n", t, count=1, flags=re.M)
        if t2 == t:
            t2 = re.sub(r"^(import os\n)", r"\1import re\n", t, count=1, flags=re.M)
        if t2 != t:
            backup(ANKI_CLI, "cli")
            open(ANKI_CLI, "w", encoding="utf-8").write(t2)
            report.append("  ✓ 给 anki_cli.py 补了 import re")
        else:
            report.append("  ⚠ anki_cli.py 缺 import re，且没找到插入位置 —— 请手动加")
    if "import sys" not in t:
        report.append("  ⚠ anki_cli.py 没有 import sys（查重告警会失败），请手动加")

print("=" * 58)
print("技能补丁执行结果（%s）" % TS)
print("=" * 58)
for line in report:
    print(line)
print()
print("接下来必须做：sudo systemctl restart hermes-gateway")
print("（网关启动时把技能烘进内存，不重启不生效）")

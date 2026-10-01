#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-10-01 技能补丁（第三批）—— 纠正「图片禁止 OCR」那条错误规则。

第一批我误判了：以为 rapidocr 没装、OCR 不可用，于是写了「收到图片直接拒绝」。
用户实测推翻：OCR 是通的（装在单独的 ocrvenv 里），晚上 7 分钟顺利出卡。

这批做两件事：
  1. 把正式版 OCR 脚本落盘到 /opt/anki-autocards/ocr/ocr.py
     （自动分片 + 阅读顺序排序；取代 cache/scratch 里那些写死尺寸的一次性脚本）
  2. 把 SKILL.md 里那条错误规则换成正确做法

跑法：sudo python3 /tmp/patch_skill3.py
"""
import datetime
import os
import shutil
import stat

SKILL_MD = "/home/hermes/.hermes/skills/note-taking/anki-cards/SKILL.md"
OCR_DIR = "/opt/anki-autocards/ocr"
OCR_PY = os.path.join(OCR_DIR, "ocr.py")
TS = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
report = []

OCR_SRC = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把图片里的文字 OCR 出来 —— 给 agent 用的确定性脚本。

用法：
    <ocrvenv>/bin/python /opt/anki-autocards/ocr/ocr.py <图片路径>

为什么要它：当前模型是纯文本模型（非 VLM），看不了图。OCR 是唯一通道。
为什么要有正式版：2026-10-01 之前 agent 每次都去 cache/scratch 翻历次残留的
一次性脚本（切片边界硬编码成某张图的尺寸），换张图就不灵，甚至用错 venv
白跑 20 分钟。这里把「自动分片 + 按阅读顺序排序」固定下来。

输出：先打印图片尺寸，再按 上→下 / 左→右 打印识别到的每一行，最后给行数统计。
"""
import os
import sys

SLICE_H = 600          # 每片高度（像素）
OVERLAP = 50           # 相邻片重叠，避免把一行字切两半
SCALE = 2              # 放大倍数（小字放大后识别率更高）


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: ocr.py <图片路径>")
        return 2
    path = sys.argv[1]
    if not os.path.exists(path):
        print("【失败】找不到图片：%s" % path)
        return 2

    try:
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:
        print("【失败】OCR 依赖缺失：%s" % e)
        print("  必须用装了 rapidocr 的那个 venv 跑（见 SKILL.md 的图片那一节）")
        return 3

    engine = RapidOCR()
    img = Image.open(path).convert("RGB")
    W, H = img.size
    print("图片尺寸: %dx%d" % (W, H))

    lines = []
    y = 0
    idx = 0
    while y < H:
        y1 = min(y + SLICE_H, H)
        crop = img.crop((0, y, W, y1))
        crop = crop.resize((crop.width * SCALE, crop.height * SCALE), Image.LANCZOS)
        tmp = "/tmp/_ocr_slice_%d.png" % idx
        crop.save(tmp)

        res, _ = engine(tmp)
        if res:
            items = []
            for item in res:
                try:
                    box, text, score = item[0], item[1], float(item[2])
                except Exception:
                    continue
                if not text:
                    continue
                ys = sorted(float(p[1]) for p in box)
                xs = sorted(float(p[0]) for p in box)
                items.append((ys[0] / SCALE + y, xs[0] / SCALE, text.strip()))
            # 按 行（12 像素为一档，容忍轻微基线差）→ 列 排序
            items.sort(key=lambda t: (round(t[0] / 12.0), t[1]))
            lines.extend(t[2] for t in items)

        try:
            os.unlink(tmp)
        except OSError:
            pass
        if y1 >= H:
            break
        y = y1 - OVERLAP          # 往回退一点，防止切行
        idx += 1

    # 相邻重复行去掉（重叠区带来的）
    dedup = []
    for t in lines:
        if not dedup or dedup[-1] != t:
            dedup.append(t)

    print("=" * 52)
    for t in dedup:
        print(t)
    print("=" * 52)
    print("共识别 %d 行" % len(dedup))
    if not dedup:
        print("（一个字都没识别出来 —— 可能是纯图片、分辨率太低，或语言不是中英文）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

OLD_SECTION = '''## ⛔ 收到图片怎么办（2026-10-01 加，真实踩过）

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
**整整 20 分钟，一张卡没产出。**'''

NEW_SECTION = '''## 📷 收到图片怎么办（2026-10-01 修订 —— 上一版写错了，已纠正）

**当前模型是纯文本模型，看不了图。但 OCR 通道是通的，走对了能正常制卡。**

### ✅ 唯一正确做法

```bash
VENV=/home/hermes/.hermes/cache/scratch/ocrvenv/bin/python
$VENV /opt/anki-autocards/ocr/ocr.py <图片路径>
```

输出就是图里的全部文字，然后**照正常流程制卡**。

- 一张 800x1200 的截图约 **5–8 分钟**（OCR 慢，正常，不要以为卡死了）
- 识别结果可能**在图片底部截断**（截图本身没截全）→ **以识别到的内容为限，
  不补全、不编造**，并在汇报里说明「截图末条被截断」
- 识别完把文字落盘（`origin` / `--origin` 或写进正文），别只在对话里说

### ❌ 绝对不要做的三件事

1. **不要自己写 OCR / 切片脚本** —— 现成的 `ocr.py` 已经做好自动分片和阅读顺序排序
2. **不要用默认 venv**（`hermes-agent/venv` 里**没有** rapidocr）—— 必须用上面那个 `ocrvenv`
3. **不要装库、不要重试** —— rapidocr 已经装好了；一条路走不通就换正确的路，别硬试

**为什么写死这条**（真实踩过两次，结果天差地别）：

| 时间 | 做法 | 结果 |
|---|---|---|
| 10-01 早上 | 用错 venv → import 失败 → 自己写切片脚本 | **连崩三次（273s / 308s），白跑 20 分钟、0 产出** |
| 10-01 晚上 | 用对 `ocrvenv` + 现成脚本 | **7 分钟顺利出卡，质量好** |

⚠️ `cache/scratch/` 是**临时目录**。`ocrvenv` 目前在那里，如果哪天被清理掉，
用这条命令重建：

```bash
python3 -m venv /home/hermes/.hermes/cache/scratch/ocrvenv
/home/hermes/.hermes/cache/scratch/ocrvenv/bin/pip install rapidocr-onnxruntime pillow
```'''


# ── 1. 落盘正式版 OCR 脚本 ────────────────────────────────
os.makedirs(OCR_DIR, exist_ok=True)
if os.path.exists(OCR_PY):
    shutil.copy2(OCR_PY, OCR_PY + ".bak-" + TS)
    report.append("  · 旧 ocr.py 已备份为 ocr.py.bak-%s" % TS)
open(OCR_PY, "w", encoding="utf-8").write(OCR_SRC)
os.chmod(OCR_PY, 0o755)
try:
    shutil.chown(OCR_PY, user="hermes")
except Exception as e:
    report.append("  ⚠ chown hermes 失败（不影响运行）：%s" % e)
report.append("  ✓ 已写入 %s（%d 字节）" % (OCR_PY, len(OCR_SRC.encode("utf-8"))))

# 语法自检
import py_compile
try:
    py_compile.compile(OCR_PY, doraise=True)
    report.append("  ✓ 语法自检通过")
except Exception as e:
    report.append("  ✗ 语法有错！%s" % e)

# ── 2. 改 SKILL.md ────────────────────────────────────────
if not os.path.exists(SKILL_MD):
    report.append("  ✗ 找不到 %s" % SKILL_MD)
else:
    src = open(SKILL_MD, encoding="utf-8").read()
    if NEW_SECTION[:30] in src:
        report.append("  · SKILL.md 已经改过了，跳过")
    elif OLD_SECTION in src:
        d = os.path.join(os.path.dirname(SKILL_MD), ".backup-%s" % TS)
        os.makedirs(d, exist_ok=True)
        shutil.copy2(SKILL_MD, os.path.join(d, "SKILL.md.batch3"))
        src = src.replace(OLD_SECTION, NEW_SECTION, 1)
        open(SKILL_MD, "w", encoding="utf-8").write(src)
        report.append("  ✓ SKILL.md 已替换（备份在 %s）" % d)
    else:
        report.append("  ⚠ 找不到旧段落，跳过（可能已被手动改过）")

print("=" * 58)
print("第三批补丁结果（%s）" % TS)
print("=" * 58)
for line in report:
    print(line)
print()
print("接着必须重启网关：sudo systemctl restart hermes-gateway")
print()
print("然后自测 OCR：")
print("  /home/hermes/.hermes/cache/scratch/ocrvenv/bin/python %s <任意图片>" % OCR_PY)

#!/usr/bin/env python3
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

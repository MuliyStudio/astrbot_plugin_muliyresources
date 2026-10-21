# -*- coding: utf-8 -*-
"""把预览图整理成 README 用图（统一宽度、压缩体积）。"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "assets", "screenshots")
PREVIEW = os.path.join(ROOT, "assets", "preview")
os.makedirs(SHOTS, exist_ok=True)

JOBS = [
    (os.path.join(ROOT, "checkin_card_preview.png"), "checkin_card.jpg", 900),
    (os.path.join(PREVIEW, "novel_list.jpg"), "search_novel_card.jpg", 900),
    (os.path.join(PREVIEW, "pan_list.jpg"), "search_pan_card.jpg", 900),
    (os.path.join(PREVIEW, "points_card.jpg"), "points_card.jpg", 900),
    (os.path.join(PREVIEW, "points_rank.jpg"), "points_rank.jpg", 900),
]

for src, dst, width in JOBS:
    im = Image.open(src).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = os.path.join(SHOTS, dst)
    im.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    print(dst, im.size, os.path.getsize(out) // 1024, "KB")

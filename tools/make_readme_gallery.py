# -*- coding: utf-8 -*-
"""生成 README 效果预览用的统一比例缩略图。

README 里直接放原始截图时，长截图（软件日报 1:3.5）和方图（积分卡 1:1）
高度差太大，两列并排会非常参差。这里统一裁成 3:5 的「展示卡」：

- 长截图（日报 / 列表）：顶部对齐裁切，保留标题和主要内容；
- 单张卡片（签到 / 积分）：完整等比缩放，居中留白，不裁内容。

输出：assets/screenshots/thumbs/<name>.jpg（480×800，约 30–60KB）
用法：python tools/make_readme_gallery.py
"""
import os

from PIL import Image, ImageDraw, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "screenshots")
OUT = os.path.join(SRC, "thumbs")

W, H = 480, 800          # 3:5
RADIUS = 14
BG = (244, 244, 245)     # 与 README 页面底色接近，缩略图之间不打架
BORDER = (228, 228, 230)

# (源文件, 输出名, 模式)  mode: fit=顶部裁切 / contain=完整缩放
JOBS = [
    ("search_drama.jpg", "search_drama.jpg", "fit"),
    ("drama_daily.jpg", "drama_daily.jpg", "fit"),
    ("movie_daily.jpg", "movie_daily.jpg", "fit"),
    ("software_daily.jpg", "software_daily.jpg", "fit"),
    ("game_daily.jpg", "game_daily.jpg", "fit"),
    ("checkin_card.jpg", "checkin_card.jpg", "contain"),
    ("search_novel_card.jpg", "search_novel_card.jpg", "fit"),
    ("search_pan_card.jpg", "search_pan_card.jpg", "fit"),
    ("points_card.jpg", "points_card.jpg", "contain"),
    ("points_rank.jpg", "points_rank.jpg", "contain"),
]


def make(src: str, dst: str, mode: str) -> tuple:
    im = Image.open(src).convert("RGB")
    if mode == "fit":
        body = ImageOps.fit(im, (W, H), Image.LANCZOS, centering=(0.5, 0.0))
    else:
        body = Image.new("RGB", (W, H), BG)
        thumb = im.copy()
        thumb.thumbnail((W, H), Image.LANCZOS)
        body.paste(thumb, ((W - thumb.width) // 2, (H - thumb.height) // 2))

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, W - 1, H - 1], radius=RADIUS, fill=255)
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(body, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS,
                           outline=BORDER, width=2)

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, dst)
    canvas.save(path, "JPEG", quality=86, optimize=True, progressive=True)
    return canvas.size, os.path.getsize(path)


def main() -> None:
    total = 0
    for src_name, dst_name, mode in JOBS:
        size, size_bytes = make(os.path.join(SRC, src_name), dst_name, mode)
        total += size_bytes
        print(f"{dst_name:26} {size[0]}x{size[1]}  {size_bytes // 1024:4d} KB  [{mode}]")
    print(f"\n共 {len(JOBS)} 张，{total / 1024 / 1024:.2f} MB -> {OUT}")


if __name__ == "__main__":
    main()

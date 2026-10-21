# -*- coding: utf-8 -*-
"""从用户提供的白底 logo 抠出透明 PNG，并生成一份用于网页内联的小图。

用法：python tools/make_logo.py <源图路径>
产物：
  assets/logo_mark.png      256px 透明主图（README / 文档可用）
  assets/logo_mark_128.png  128px 内联用（卡片、日报 HTML 里 base64）
  assets/preview/logo_check.png  白底 + 暖黄底对照图（仅人工检查）
"""
import os
import sys
import base64

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cutout(src_path: str) -> Image.Image:
    im = Image.open(src_path).convert("RGBA")
    arr = np.array(im)
    rgb = arr[..., :3].astype(np.int16)
    # 「接近白色」的像素：三通道都很亮（含浅蓝抗锯齿边），留一点余量
    near_white = (rgb.min(axis=2) >= 225)
    # 注意：Image.fromarray 得到的是 numpy 只读缓冲，floodfill 写不进去（会静默失败），
    # 必须 .copy() 成可写图像。
    mask = Image.fromarray(np.where(near_white, 255, 0).astype(np.uint8), "L").copy()
    # 只抹掉「从画布边缘连通进来」的白，保留图标内部的白色（放大镜镜片/边框留白）
    h, w = mask.size
    for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if mask.getpixel(pt) == 255:
            ImageDraw.floodfill(mask, pt, 128)
    bg = np.array(mask) == 128

    alpha = np.where(bg, 0, 255).astype(np.uint8)
    arr[..., 3] = alpha
    out = Image.fromarray(arr, "RGBA")
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    return out


def resize_premultiplied(img: Image.Image, size: int) -> Image.Image:
    """预乘 alpha 再缩放，避免透明区域把边缘染白。"""
    arr = np.array(img).astype(np.float32)
    a = (arr[..., 3:4] / 255.0)
    arr[..., :3] *= a
    small = Image.fromarray(arr.astype(np.uint8), "RGBA").resize(
        (size, size), Image.LANCZOS)
    arr2 = np.array(small).astype(np.float32)
    a2 = np.maximum(arr2[..., 3:4] / 255.0, 1e-6)
    arr2[..., :3] = np.clip(arr2[..., :3] / a2, 0, 255)
    arr2[..., 3:4] = np.clip(arr2[..., 3:4], 0, 255)
    return Image.fromarray(arr2.astype(np.uint8), "RGBA")


def with_padding(img: Image.Image, ratio: float = 0.05) -> Image.Image:
    side = max(img.size)
    pad = int(round(side * ratio))
    canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
    canvas.paste(img, ((canvas.width - img.width) // 2,
                       (canvas.height - img.height) // 2), img)
    return canvas


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ["TEMP"], "opencode", "logo_src.png")
    master = with_padding(cutout(src), 0.04)
    master = resize_premultiplied(master, 256)
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    p256 = os.path.join(ROOT, "assets", "logo_mark.png")
    p128 = os.path.join(ROOT, "assets", "logo_mark_128.png")
    master.save(p256, "PNG", optimize=True)
    resize_premultiplied(master, 128).save(p128, "PNG", optimize=True)
    print("saved", p256, os.path.getsize(p256) // 1024, "KB")
    print("saved", p128, os.path.getsize(p128) // 1024, "KB")

    # 对照预览：白底 / 暖黄底 / 深色底
    sizes = [256, 128, 64, 32]
    prev = Image.new("RGB", (sum(s + 40 for s in sizes) + 20, 3 * 130), "#ffffff")
    d = ImageDraw.Draw(prev)
    for row, bgc in enumerate(("#ffffff", "#f9f0d8", "#1a1a1a")):
        d.rectangle([0, row * 130, prev.width, row * 130 + 129], fill=bgc)
        x = 20
        for s in sizes:
            small = master.resize((s, s), Image.LANCZOS)
            prev.paste(small, (x, row * 130 + (128 - s) // 2), small)
            x += s + 40
    os.makedirs(os.path.join(ROOT, "assets", "preview"), exist_ok=True)
    chk = os.path.join(ROOT, "assets", "preview", "logo_check.png")
    prev.save(chk)
    print("preview", chk)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""品牌标识：把 assets/logo_mark_128.png 以 base64 内联进各处 HTML。

为什么用 base64 而不是文件路径：
  · 列表卡片用 page.set_content 注入 HTML（页面是 about:blank），
    浏览器会拦截 file:// 本地图片，只能内联；
  · 日报虽然走临时文件渲染，但内联后单文件 HTML 也能离线直接打开，
    与现有封面图的处理方式一致。

图片只有 128px / 十几 KB，内联开销可以忽略；显示尺寸 28~40px，
2x 出图也足够清晰。
"""
from __future__ import annotations

import base64
import functools
import os

LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "logo_mark_128.png")


@functools.lru_cache(maxsize=1)
def logo_data_url() -> str:
    """返回 logo 的 data URI；文件缺失时返回空串（调用方跳过 logo）。"""
    try:
        with open(LOGO_PATH, "rb") as f:
            raw = f.read()
        if not raw:
            return ""
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return ""


@functools.lru_cache(maxsize=8)
def logo_img(px: int = 34, alt: str = "") -> str:
    """生成一个固定尺寸的 logo <img>；无图时返回空串。"""
    url = logo_data_url()
    if not url:
        return ""
    return (f'<img src="{url}" alt="{alt}" width="{px}" height="{px}" '
            f'style="width:{px}px;height:{px}px;display:block">')

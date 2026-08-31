# -*- coding: utf-8 -*-
"""纯 Python（Pillow）日报图片渲染 —— Playwright/Chromium 未安装时的兜底方案。

不需要浏览器、不需要 playwright install chromium，装好 Pillow（requirements 已含）
即可把日报条目渲染成图片。三种日报（软件/游戏/影视）共用本模块：

  render_pil_report(cards, date_label, source_label, font_path, width)

cards 为条目列表，每项：
  cover: str|None   —— 封面 base64 data URI（如 "data:image/jpeg;base64,..."）或空
  title: str        —— 标题
  chips: list[str]  —— 标签（豆瓣评分/画质/更新时间等）
  desc : str        —— 简介/剧情摘要

布局：顶部标题条 + 每条目一张卡片（封面缩略图 + 标题 + 标签 + 简介）+ 页脚。
全部用 Pillow 绘制，中文字体取插件自带的 SourceHanSansCN-Heavy.otf（思源黑体）。
"""
import base64
import io
from PIL import Image, ImageDraw, ImageFont

_HEADER_BG = (66, 133, 244)
_BG_TOP = (245, 247, 252)
_BG_BOTTOM = (229, 235, 245)
_CARD_BG = (255, 255, 255)
_CARD_BORDER = (225, 230, 240)
_TEXT = (40, 48, 64)
_TEXT_SUB = (120, 130, 150)
_CHIP_BG = (237, 242, 255)
_CHIP_TEXT = (66, 133, 244)
_FOOTER = (150, 160, 178)

_PAD = 24
_CARD_MARGIN = 14
_COVER_W = 116
_COVER_H = 150


def _font(path, size):
    try:
        if path:
            ImageFont.truetype(path, size)
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _b64_to_bytes(data_uri: str):
    """把 base64 data URI 解码为原始图片字节；失败返回 None。"""
    if not data_uri:
        return None
    try:
        if "," in data_uri:
            data_uri = data_uri.split(",", 1)[1]
        return base64.b64decode(data_uri)
    except Exception:
        return None


def _cover_image(data_uri: str, box_w: int, box_h: int):
    """解码封面并缩放（保持比例），失败返回 None。"""
    raw = _b64_to_bytes(data_uri)
    if not raw:
        return None
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((box_w, box_h), Image.LANCZOS)
        return im
    except Exception:
        return None


def _wrap(draw, text, font, max_w) -> list:
    """按像素宽度换行（逐字符累计宽度，兼容中英文混排）。"""
    lines = []
    for seg in (text or "").split("\n"):
        cur = ""
        for ch in seg:
            if draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines or [""]


def render_pil_report(cards: list, date_label: str = "", source_label: str = "",
                      font_path: str = "", width: int = 720) -> bytes | None:
    """把日报条目渲染成 JPEG 字节。失败返回 None（调用方再降级文字版）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        return None

    font_title = _font(font_path, 34)
    font_sub = _font(font_path, 20)
    font_card_title = _font(font_path, 24)
    font_chip = _font(font_path, 16)
    font_desc = _font(font_path, 20)
    font_footer = _font(font_path, 17)

    cards = list(cards or [])
    text_w = width - _PAD * 2 - _COVER_W - 34  # 标题/简介可用宽度

    # 第一遍：排版，计算每张卡片高度
    tmp = Image.new("RGB", (10, 10))
    _d = ImageDraw.Draw(tmp)
    heights = []
    for c in cards:
        title_lines = _wrap(_d, (c.get("title") or "未知")[:60], font_card_title, text_w)
        desc_lines = _wrap(_d, c.get("desc") or "暂无简介", font_desc, text_w)[:4]
        body_h = len(title_lines) * 32 + 12 + 30 + len(desc_lines) * 30 + 6
        heights.append(max(_COVER_H + 20, body_h + 24))

    total_h = 96 + sum(h + _CARD_MARGIN for h in heights) + 56
    img = Image.new("RGB", (width, total_h), _BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    # 背景渐变
    for yy in range(total_h):
        ratio = yy / max(total_h - 1, 1)
        col = tuple(int(_BG_TOP[i] + (_BG_BOTTOM[i] - _BG_TOP[i]) * ratio) for i in range(3))
        draw.line([(0, yy), (width, yy)], fill=col)

    # 顶部标题条
    draw.rectangle([0, 0, width, 88], fill=_HEADER_BG)
    draw.text((_PAD, 18), "暮黎资源日报", font=font_title, fill=(255, 255, 255))
    meta = "  ".join(x for x in (date_label, source_label) if x)
    if meta:
        draw.text((_PAD, 60), meta, font=font_sub, fill=(235, 242, 255))

    # 卡片
    y = 100
    for idx, c in enumerate(cards, 1):
        card_h = heights[idx - 1]
        title = (c.get("title") or "未知")[:60]
        chips = c.get("chips") or []
        desc = c.get("desc") or "暂无简介"
        cover_im = _cover_image(c.get("cover") or "", _COVER_W, _COVER_H)
        title_lines = _wrap(draw, title, font_card_title, text_w)
        desc_lines = _wrap(draw, desc, font_desc, text_w)[:4]

        draw.rounded_rectangle([_PAD, y, width - _PAD, y + card_h],
                               radius=16, fill=_CARD_BG, outline=_CARD_BORDER, width=1)
        draw.text((_PAD + 14, y + 12), f"{idx:02d}", font=font_sub, fill=_CARD_BORDER)

        x = _PAD + 18
        if cover_im:
            cw, chh = cover_im.size
            cy = y + 12
            draw.rounded_rectangle([x, cy, x + _COVER_W, cy + _COVER_H],
                                   radius=10, fill=(240, 243, 250))
            img.paste(cover_im, (x + (_COVER_W - cw) // 2, cy + (_COVER_H - chh) // 2))
        tx = x + _COVER_W + 16
        ty = y + 14
        for tl in title_lines:
            draw.text((tx, ty), tl, font=font_card_title, fill=_TEXT)
            ty += 32
        if chips:
            cyy = ty
            tx_run = tx
            for chip in chips[:5]:
                chip_txt = str(chip)[:16]
                cwpx = draw.textlength(chip_txt, font=font_chip) + 18
                if tx_run + cwpx > width - _PAD - 10:
                    tx_run = tx
                    cyy += 28
                draw.rounded_rectangle([tx_run, cyy, tx_run + cwpx, cyy + 24],
                                       radius=12, fill=_CHIP_BG)
                draw.text((tx_run + 9, cyy + 3), chip_txt, font=font_chip, fill=_CHIP_TEXT)
                tx_run += cwpx + 8
            ty = cyy + 30
        for dl in desc_lines:
            draw.text((x + _COVER_W + 16, ty), dl, font=font_desc, fill=_TEXT_SUB)
            ty += 30
        y += card_h + _CARD_MARGIN

    # 页脚
    draw.text((_PAD, total_h - 42), f"数据来源：{source_label or '暮黎资源'}  ｜  共 {len(cards)} 条",
              font=font_footer, fill=_FOOTER)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()

# -*- coding: utf-8 -*-
"""入群审核 —— 20-100 以内加减法算术题 + 图形验证码渲染（Pillow）。

本模块只做两件事，其余（入群 notice 识别、答案校验、撤回、踢人）在 main.py 完成：

  generate_arithmetic()        -> ("63 - 27", 36)   生成题目与答案
  render_captcha(expr, font)   -> PNG bytes        渲染成带干扰的验证码图片

题目约束：两个操作数与结果都落在 [20, 100]，避免出现负数或超大数，
既能拦住脚本机器人，又不会为难正常人类。

验证码强度：随机底色 + 多层干扰线/弧线 + 大量噪点/色斑 + **逐字符随机旋转**
+ 抖动，尽量让群验证码 bot（OCR）难以识别。

依赖 Pillow（requirements.txt 已含）。未安装时 PIL_AVAILABLE 为 False，
上层会降级为纯文本题目（提示用户直接回复答案）。
"""

import os
import random
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:  # noqa: BLE001 —— 缺 Pillow 时给出降级信号，不影响插件加载
    PIL_AVAILABLE = False

# 兜底字体候选（插件自带思源黑体子集优先，其次各系统常见等宽/黑体）
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONT_CANDIDATES = (
    os.path.join(_PLUGIN_ROOT, "assets", "fonts", "MuliHeavy.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

_MIN = 20
_MAX = 100


def generate_arithmetic(lo: int = _MIN, hi: int = _MAX):
    """生成一道 20-100 以内的加减法题。

    返回 (表达式字符串, 答案整数)。加法的和、减法的差都保证在 [lo, hi]。
    """
    if random.random() < 0.5:
        # 加法：a ∈ [lo, hi-lo]，b ∈ [lo, hi-a] → 和 ∈ [2lo, hi]
        a = random.randint(lo, hi - lo)
        b = random.randint(lo, hi - a)
        return f"{a} + {b}", a + b
    # 减法：a ∈ [2lo, hi]，b ∈ [lo, a-lo] → 差 ∈ [lo, hi-lo]，恒非负
    a = random.randint(lo * 2, hi)
    b = random.randint(lo, a - lo)
    return f"{a} - {b}", a - b


def _load_font(font_path: str, size: int):
    """按「传入路径 → 内置候选 → Pillow 默认字体」依次尝试加载。"""
    candidates = []
    if font_path:
        candidates.append(font_path)
    candidates.extend(_FONT_CANDIDATES)
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _rand_color(lo: int, hi: int):
    return tuple(random.randint(lo, hi) for _ in range(3))


def render_captcha(expression: str, font_path: str = "",
                   width: int = 300, height: int = 112) -> bytes | None:
    """把 `expression` 渲染成 PNG 验证码图片（强干扰版）。

    干扰手段：随机底色、多层干扰线/弧线（含压在文字上的）、大量噪点与色斑、
    逐字符随机旋转与抖动、字符间距随机。Pillow 不可用时返回 None。
    """
    if not PIL_AVAILABLE:
        return None

    bg = _rand_color(238, 254)
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # ── 背景干扰：细线 + 弧线 ──
    for _ in range(random.randint(7, 12)):
        draw.line(
            [(random.randint(0, width), random.randint(0, height)),
             (random.randint(0, width), random.randint(0, height))],
            fill=_rand_color(120, 215), width=random.choice([1, 1, 2]),
        )
    for _ in range(random.randint(3, 6)):
        y0 = random.randint(6, height - 6)
        draw.arc(
            [random.randint(-30, width // 3), y0 - random.randint(14, 26),
             random.randint(width // 2, width + 30), y0 + random.randint(14, 26)],
            start=random.randint(0, 180), end=random.randint(180, 360),
            fill=_rand_color(110, 200), width=random.choice([1, 2]),
        )

    # ── 噪点 + 彩色斑点 ──
    for _ in range(random.randint(220, 420)):
        draw.point((random.randint(0, width), random.randint(0, height)),
                   fill=_rand_color(90, 225))
    for _ in range(random.randint(8, 16)):
        r = random.randint(1, 3)
        cx, cy = random.randint(0, width), random.randint(0, height)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rand_color(120, 215))

    # ── 题目文本：逐字符渲染成透明图层后随机旋转、抖动，再叠加 ──
    text = f"{expression} = ?"
    pad = 10
    # 自适应字号：保证整串（含随机间距与旋转留白）不会超出画布被裁切
    fit_w = width - 2 * pad - 8
    font = None
    for size in range(int(height * 0.42), 15, -2):
        f = _load_font(font_path, size)
        try:
            tot = sum(draw.textlength(ch, font=f) for ch in text) * 1.14
        except Exception:  # noqa: BLE001 —— 极旧 Pillow 无 textlength
            tot = len(text) * size * 0.62
        if tot <= fit_w:
            font = f
            break
    if font is None:
        font = _load_font(font_path, 16)
    try:
        widths = [draw.textlength(ch, font=font) for ch in text]
    except Exception:  # noqa: BLE001
        widths = [height * 0.26 for _ in text]
    total = max(1.0, sum(widths))
    x = max(4.0, (width - total) / 2)
    for ch, adv in zip(text, widths):
        if ch == " ":
            x += adv * random.uniform(0.8, 1.6)
            continue
        cw, chh = int(adv) + pad * 2, height + pad * 2
        layer = Image.new("RGBA", (max(cw, 8), chh), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        color = (random.randint(0, 55), random.randint(0, 55), random.randint(60, 145), 255)
        ld.text((pad, pad + random.randint(-4, 4)), ch, font=font, fill=color)
        layer = layer.rotate(random.uniform(-26, 26),
                             resample=Image.BICUBIC, expand=False)
        img.paste(layer, (int(x) - pad, (height - chh) // 2 + random.randint(-5, 5)), layer)
        x += adv * random.uniform(0.95, 1.18)

    # ── 前景干扰线：压在文字上方，进一步打断字符轮廓 ──
    for _ in range(random.randint(2, 4)):
        draw.line(
            [(random.randint(0, width // 3), random.randint(0, height)),
             (random.randint(width * 2 // 3, width), random.randint(0, height))],
            fill=_rand_color(100, 190), width=random.choice([1, 1, 2]),
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

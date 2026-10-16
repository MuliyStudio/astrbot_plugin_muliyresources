# -*- coding: utf-8 -*-
"""入群审核 —— 20-100 以内加减法算术题 + 图形验证码渲染（Pillow）。

本模块只做两件事，其余（入群 notice 识别、答案校验、撤回、踢人）在 main.py 完成：

  generate_arithmetic()        -> ("63 - 27", 36)   生成题目与答案
  render_captcha(expr, font)   -> PNG bytes        渲染成带干扰的验证码图片

题目约束：两个操作数与结果都落在 [20, 100]，避免出现负数或超大数，
既能拦住脚本机器人，又不会为难正常人类。

依赖 Pillow（requirements.txt 已含）。未安装时 PIL_AVAILABLE 为 False，
上层会降级为纯文本题目（提示用户直接回复答案）。
"""

import random
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:  # noqa: BLE001 —— 缺 Pillow 时给出降级信号，不影响插件加载
    PIL_AVAILABLE = False

# 兜底字体候选（插件自带思源黑体优先，其次各系统常见等宽/黑体）
_FONT_CANDIDATES = (
    "SourceHanSansCN-Heavy.otf",
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


def render_captcha(expression: str, font_path: str = "",
                   width: int = 260, height: int = 100) -> bytes | None:
    """把 `expression` 渲染成 PNG 验证码图片（带干扰线/噪点/字符抖动）。

    Pillow 不可用时返回 None，调用方需降级为纯文本题目。
    """
    if not PIL_AVAILABLE:
        return None

    bg = tuple(random.randint(243, 255) for _ in range(3))
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # ── 背景干扰线 ──
    for _ in range(random.randint(4, 6)):
        draw.line(
            [(random.randint(0, width), random.randint(0, height)),
             (random.randint(0, width), random.randint(0, height))],
            fill=tuple(random.randint(150, 220) for _ in range(3)),
            width=1,
        )
    # ── 噪点 ──
    for _ in range(random.randint(60, 120)):
        draw.point((random.randint(0, width), random.randint(0, height)),
                   fill=tuple(random.randint(140, 220) for _ in range(3)))

    # ── 题目文本：逐字符绘制，颜色/纵向位置抖动（防简单 OCR 切图） ──
    text = f"{expression} = ?"
    font = _load_font(font_path, int(height * 0.46))
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
    except Exception:  # noqa: BLE001 —— 极旧 Pillow 无 textbbox
        text_w = int(len(text) * height * 0.28)
    x = max(6, (width - text_w) // 2)
    for ch in text:
        try:
            adv = draw.textlength(ch, font=font)
        except Exception:  # noqa: BLE001
            adv = height * 0.28
        draw.text(
            (x, random.randint(int(height * 0.22), int(height * 0.30))),
            ch, font=font,
            fill=(random.randint(0, 70), random.randint(0, 70), random.randint(70, 150)),
        )
        x += adv

    # ── 前景干扰弧线（压在文字上方） ──
    for _ in range(random.randint(1, 2)):
        y0 = random.randint(10, height - 10)
        draw.arc(
            [random.randint(-20, width // 3), y0 - 18,
             random.randint(width // 2, width + 20), y0 + 18],
            start=random.randint(0, 180), end=random.randint(180, 360),
            fill=tuple(random.randint(120, 190) for _ in range(3)), width=2,
        )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

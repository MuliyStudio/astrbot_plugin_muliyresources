# -*- coding: utf-8 -*-
"""
diydoutu 表情包通用 GIF 生成引擎
================================
舔狗（doutu/389）、柴犬按摩（doutu/401）等 diydoutu 站点的表情均为
fabric.js + gif.js **纯前端生成**、无服务端接口，因此本模块在本地用 Pillow
把「用户头像」（**头像优先，文字仅兜底**）叠加到模板 GIF 的每一个文字位上。

通用插槽约定（与站点 JS 的 left / tops / size / word 数组一一对应）：
  - slot0 = 被@成员（dog），对应逆向出的第一个文字位
  - slot1 = 发送者（kicker），对应第二个文字位

依赖：Pillow (PIL)
"""

import os
import io
import re
import logging
import tempfile

logger = logging.getLogger("astrbot_plugin_muliyresources")

# ==================== Pillow 可选导入 ====================
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = ImageDraw = ImageFont = None  # type: ignore

# ==================== 名字清洗 ====================
# 仅保留：中文字（CJK 基本区 + 扩展A）、英文字母、数字。
# 其余（emoji、数学花体 𝓜𝓾𝓵𝓲𝔂、特殊符号、空格等）字体无法渲染，会变成方块/空白，需剔除。
_NAME_SANITIZE_RE = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbfA-Za-z0-9]")

# ==================== 常量 ====================
_FONT_SIZE_DEFAULT = 26
_STROKE_WIDTH = 6
_FILL = (255, 255, 255)    # 白字
_STROKE = (0, 0, 0)        # 黑描边

# 字体搜索目录（优先共享 assets/fonts，其次各 meme 自带目录，避免重复打包字体）
_ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
_FONT_SEARCH_DIRS = [
    os.path.join(_ASSET_DIR, "fonts"),
    os.path.join(_ASSET_DIR, "lickdog"),
    os.path.join(_ASSET_DIR, "doutu"),
]
_SYSTEM_FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\NotoSansSC-Regular.otf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def _resolve_font(size: int = _FONT_SIZE_DEFAULT) -> "ImageFont.FreeTypeFont":
    """解析字体：优先用插件自带 Noto Sans SC（assets/fonts 或各 meme 目录），回退系统字体。"""
    for d in _FONT_SEARCH_DIRS:
        for fn in ("font.otf", "NotoSansSC-Regular.otf"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception as e:
                    logger.warning(f"[Doutu] 字体加载失败 {p}: {e}")
    for cand in _SYSTEM_FONT_CANDIDATES:
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                continue
    logger.warning("[Doutu] 未找到中文字体，中文可能显示为方块")
    return ImageFont.load_default()


def sanitize_name(name: str, fallback: str = "") -> str:
    """清洗昵称：仅保留中文 / 英文 / 数字，去除字体无法渲染的字符。

    Args:
        name:     原始昵称
        fallback: 清洗后为空时返回的兜底（默认空串，便于调用方判断是否需要头像兜底）
    Returns:
        清洗后的安全显示名
    """
    if not name:
        return fallback
    cleaned = _NAME_SANITIZE_RE.sub("", name).strip()
    return cleaned or fallback


def _make_circular_avatar(avatar_bytes: bytes, size: int) -> "Image.Image":
    """将头像字节裁成圆形（透明背景），用于名字无法渲染 / 头像优先时的替代。"""
    img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


def _build_slot_render(name: str, avatar_bytes, fallback_text: str, idx: int,
                       force_avatar: bool = False) -> dict:
    """为一个文字位决定渲染方式（**头像优先**）：

    - 有头像            → {"kind": "avatar", "avatar": 头像字节}（优先，避免名字过长/字体限制）
    - 无头像 + 非强制   → 名字可渲染则文字，否则兜底文字
    - 无头像 + 强制头像 → 退回兜底文字（极少数头像拉取失败场景）
    """
    if avatar_bytes:
        return {"kind": "avatar", "avatar": avatar_bytes, "idx": idx}
    if force_avatar:
        cleaned = sanitize_name(name, fallback="")
        return {"kind": "text", "text": cleaned or fallback_text, "idx": idx}
    cleaned = sanitize_name(name, fallback="")
    if cleaned:
        return {"kind": "text", "text": cleaned, "idx": idx}
    return {"kind": "text", "text": fallback_text, "idx": idx}


def generate_doutu_meme(template_path: str, slot_positions, slot_sizes,
                        kicker: str, dog: str, dest_path: str = None,
                        kicker_avatar: bytes = None, dog_avatar: bytes = None,
                        fill=_FILL, stroke=_STROKE, stroke_width=_STROKE_WIDTH) -> str:
    """通用 diydoutu 表情 GIF 生成引擎。

    Args:
        template_path: 模板 GIF 路径
        slot_positions: [(x0,y0), (x1,y1), ...] 各文字位左上角坐标（slot0=dog, slot1=kicker）
        slot_sizes:     [s0, s1, ...] 各文字位基础字号（也是头像直径基准）
        kicker: 发送者（slot1）
        dog:    被@成员（slot0）
        dest_path: 输出路径；None 时自动生成临时文件
        kicker_avatar / dog_avatar: 头像字节（头像优先；缺则退回文字兜底）
        fill / stroke / stroke_width: 文字兜底样式
    Returns:
        dest_path
    Raises:
        FileNotFoundError: 模板缺失
        RuntimeError: 模板解析失败
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow 未安装，无法生成表情 GIF")
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"模板缺失: {template_path}")

    if not dest_path:
        fd, dest_path = tempfile.mkstemp(suffix=".gif", prefix="doutu_")
        os.close(fd)

    font = _resolve_font()

    # 头像优先：有头像即贴圆形头像，无头像才退回文字兜底
    slot_dog = _build_slot_render(dog, dog_avatar, fallback_text="群友", idx=0, force_avatar=True)
    slot_kicker = _build_slot_render(kicker, kicker_avatar, fallback_text="某人", idx=1, force_avatar=True)
    slots = [ slot_dog,slot_kicker]

    gif = Image.open(template_path)
    frames_p = []
    durations = []
    try:
        while True:
            frames_p.append(gif.copy())
            durations.append(gif.info.get("duration", 80))
            gif.seek(gif.tell() + 1)
    except EOFError:
        pass

    if not frames_p:
        raise RuntimeError("模板 GIF 解析失败：无可用帧")

    out_frames = []
    for frame_p in frames_p:
        rgba = frame_p.convert("RGBA")
        draw = ImageDraw.Draw(rgba)

        for slot in slots:
            x, y = slot_positions[slot["idx"]]
            if slot["kind"] == "text":
                size = slot_sizes[slot["idx"]]
                sw = max(1, int(round(stroke_width * size / _FONT_SIZE_DEFAULT)))
                try:
                    fnt = font.font_variant(size=size) if hasattr(font, "font_variant") else font
                except Exception:
                    fnt = font
                draw.text(
                    (x, y), slot["text"], font=fnt,
                    fill=fill, stroke_width=sw, stroke_fill=stroke,
                )
            else:
                av_size = slot_sizes[slot["idx"]] + 15
                circ = _make_circular_avatar(slot["avatar"], av_size)
                rgba.alpha_composite(circ, (x, y))

        try:
            quantized = rgba.quantize(palette=frame_p, dither=False)
        except Exception:
            quantized = rgba.convert("RGB").quantize(colors=255, dither=False)
        out_frames.append(quantized)

    save_kwargs = dict(
        format="GIF",
        save_all=True,
        optimize=False,
        append_images=out_frames[1:],
        duration=durations if len(set(durations)) > 1 else durations[0],
        disposal=2,
        loop=0,
    )
    if "transparency" in frames_p[0].info:
        save_kwargs["transparency"] = frames_p[0].info["transparency"]
    out_frames[0].save(dest_path, **save_kwargs)

    logger.info(f"[Doutu] GIF 生成成功: {dest_path} ({len(out_frames)}帧)")
    return dest_path

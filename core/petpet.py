# -*- coding: utf-8 -*-
"""
PetPet 摸头杀 GIF 生成模块
===========================
基于 https://github.com/camprevail/pet-pet-gif 的 Python 实现。

算法：
  - 10 帧动画，头像在手掌下方做"挤压"弹性运动
  - 每帧叠加对应的手部模板图（pet0.gif ~ pet9.gif）
  - 输出带透明通道的 GIF

依赖：Pillow (PIL)
"""

import os
import io
import logging
import tempfile
from typing import List, Tuple, Union, Optional
from collections import defaultdict
from random import randrange
from itertools import chain

logger = logging.getLogger("astrbot_plugin_muliyresources")

# Pillow 可选导入（插件运行环境需安装 pillow）
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None  # type: ignore

try:
    import requests
except ImportError:
    requests = None  # type: ignore

# ==================== 常量 ====================

FRAMES = 10
RESOLUTION = (128, 128)
DELAY = 20  # 每帧延迟（毫秒）

# 手部模板图目录（相对于插件根目录）
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "petpet")

# QQ 头像 URL 模板
_QQ_AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640"


# ==================== 透明 GIF 保存 ====================
# 以下代码适配自 https://github.com/camprevail/pet-pet-gif/blob/main/petpetgif/saveGif.py
# 解决 Pillow 保存透明 GIF 时透明像素变黑的问题

class _TransparentAnimatedGifConverter:
    """将 RGBA 帧转换为带透明色的 P 模式帧，用于 GIF 保存。"""

    _PALETTE_SLOTSET = set(range(256))

    def __init__(self, img_rgba, alpha_threshold: int = 0):
        self._img_rgba = img_rgba
        self._alpha_threshold = alpha_threshold

    def _process_pixels(self):
        self._transparent_pixels = set(
            idx for idx, alpha in enumerate(
                self._img_rgba.getchannel(channel='A').getdata())
            if alpha <= self._alpha_threshold
        )

    def _set_parsed_palette(self):
        palette = self._img_p.getpalette()
        self._img_p_used_palette_idxs = set(
            idx for pal_idx, idx in enumerate(self._img_p_data)
            if pal_idx not in self._transparent_pixels
        )
        self._img_p_parsedpalette = dict(
            (idx, tuple(palette[idx * 3:idx * 3 + 3]))
            for idx in self._img_p_used_palette_idxs
        )

    def _get_similar_color_idx(self):
        old_color = self._img_p_parsedpalette[0]
        dict_distance = defaultdict(list)
        for idx in range(1, 256):
            color_item = self._img_p_parsedpalette[idx]
            if color_item == old_color:
                return idx
            distance = sum((
                abs(old_color[0] - color_item[0]),
                abs(old_color[1] - color_item[1]),
                abs(old_color[2] - color_item[2])))
            dict_distance[distance].append(idx)
        return dict_distance[sorted(dict_distance)[0]][0]

    def _remap_palette_idx_zero(self):
        free_slots = self._PALETTE_SLOTSET - self._img_p_used_palette_idxs
        new_idx = free_slots.pop() if free_slots else self._get_similar_color_idx()
        self._img_p_used_palette_idxs.add(new_idx)
        self._palette_replaces['idx_from'].append(0)
        self._palette_replaces['idx_to'].append(new_idx)
        self._img_p_parsedpalette[new_idx] = self._img_p_parsedpalette[0]
        del self._img_p_parsedpalette[0]

    def _get_unused_color(self) -> tuple:
        used_colors = set(self._img_p_parsedpalette.values())
        while True:
            new_color = (randrange(256), randrange(256), randrange(256))
            if new_color not in used_colors:
                return new_color

    def _process_palette(self):
        self._set_parsed_palette()
        if 0 in self._img_p_used_palette_idxs:
            self._remap_palette_idx_zero()
        self._img_p_parsedpalette[0] = self._get_unused_color()

    def _adjust_pixels(self):
        if self._palette_replaces['idx_from']:
            trans_table = bytearray.maketrans(
                bytes(self._palette_replaces['idx_from']),
                bytes(self._palette_replaces['idx_to']))
            self._img_p_data = self._img_p_data.translate(trans_table)
        for idx_pixel in self._transparent_pixels:
            self._img_p_data[idx_pixel] = 0
        self._img_p.frombytes(data=bytes(self._img_p_data))

    def _adjust_palette(self):
        unused_color = self._get_unused_color()
        final_palette = chain.from_iterable(
            self._img_p_parsedpalette.get(x, unused_color) for x in range(256))
        self._img_p.putpalette(data=final_palette)

    def process(self):
        self._img_p = self._img_rgba.convert(mode='P')
        self._img_p_data = bytearray(self._img_p.tobytes())
        self._palette_replaces = dict(idx_from=list(), idx_to=list())
        self._process_pixels()
        self._process_palette()
        self._adjust_pixels()
        self._adjust_palette()
        self._img_p.info['transparency'] = 0
        self._img_p.info['background'] = 0
        return self._img_p


def _create_animated_gif(images, durations: Union[int, List[int]]) -> Tuple:
    save_kwargs = dict()
    new_images: List = []

    for frame in images:
        thumbnail = frame.copy()
        thumbnail_rgba = thumbnail.convert(mode='RGBA')
        thumbnail_rgba.thumbnail(size=frame.size, reducing_gap=3.0)
        converter = _TransparentAnimatedGifConverter(img_rgba=thumbnail_rgba)
        thumbnail_p = converter.process()
        new_images.append(thumbnail_p)

    output_image = new_images[0]
    save_kwargs.update(
        format='GIF',
        save_all=True,
        optimize=False,
        append_images=new_images[1:],
        duration=durations,
        disposal=2,
        loop=0
    )
    return output_image, save_kwargs


def _save_transparent_gif(images, durations: Union[int, List[int]], save_file):
    """保存带透明背景的 GIF 动画。"""
    root_frame, save_args = _create_animated_gif(images, durations)
    root_frame.save(save_file, **save_args)


# ==================== 手部模板加载 ====================

_template_cache: List = []


def _load_templates() -> List:
    """加载 10 帧手部模板图（带缓存）。"""
    global _template_cache
    if _template_cache:
        return _template_cache
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow 未安装，无法生成 PetPet GIF")
    for i in range(FRAMES):
        path = os.path.join(_TEMPLATE_DIR, f"pet{i}.gif")
        if not os.path.exists(path):
            raise FileNotFoundError(f"手部模板图缺失: {path}")
        img = Image.open(path).convert('RGBA').resize(RESOLUTION)
        _template_cache.append(img)
    logger.info("[PetPet] 手部模板图加载完成 (10帧)")
    return _template_cache


# ==================== 头像下载 ====================

def download_qq_avatar(qq: Union[int, str], size: int = 640) -> bytes:
    """下载 QQ 用户头像，返回图片字节。

    Args:
        qq: QQ 号
        size: 头像尺寸（像素），可选 40/100/140/640
    Returns:
        图片二进制数据
    Raises:
        RuntimeError: 下载失败
    """
    if not requests:
        raise RuntimeError("requests 未安装，无法下载头像")
    url = _QQ_AVATAR_URL.format(qq=qq, s=size)
    resp = requests.get(url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    if resp.status_code != 200 or len(resp.content) < 100:
        raise RuntimeError(f"头像下载失败: HTTP {resp.status_code}, {len(resp.content)}B")
    return resp.content


def download_avatar_by_platform(platform: str, user_id: str) -> bytes:
    """根据平台下载用户头像。

    目前支持：
      - aiocqhttp (QQ): 使用 q1.qlogo.cn 公开头像 API
      - 其他平台: 暂不支持，抛出 RuntimeError

    Args:
        platform: 平台名称（event.get_platform_name()）
        user_id: 用户 ID
    Returns:
        图片二进制数据
    """
    platform_lower = (platform or "").lower()
    if "aiocqhttp" in platform_lower or "qq" in platform_lower:
        return download_qq_avatar(user_id)
    # Telegram / Discord 等平台可在此扩展
    raise RuntimeError(f"平台 {platform} 暂不支持获取用户头像")


# ==================== GIF 生成 ====================

def _make_circular(img: "Image.Image") -> "Image.Image":
    """将图片裁剪为圆形（透明背景）。

    使用径渐变 alpha 蒙版实现抗锯齿圆形裁剪。
    """
    size = img.size
    # 创建径向渐变蒙版：中心不透明，边缘透明，实现抗锯齿
    mask = Image.new('L', size, 0)
    # 用 ImageDraw 在蒙版上画一个白色椭圆
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
    # 应用蒙版
    result = Image.new('RGBA', size, (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


def generate_petpet(source_image: Union[str, bytes, io.BytesIO], dest_path: str) -> str:
    """生成 PetPet 摸头 GIF。

    Args:
        source_image: 源图片路径 / 字节数据 / BytesIO 对象
        dest_path: 输出 GIF 文件路径
    Returns:
        dest_path（生成的 GIF 文件路径）
    Raises:
        RuntimeError: Pillow 未安装或生成失败
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow 未安装，无法生成 PetPet GIF")

    # 加载头像
    if isinstance(source_image, bytes):
        source_image = io.BytesIO(source_image)
    base = Image.open(source_image).convert('RGBA').resize(RESOLUTION)

    # 将头像裁剪为圆形
    base = _make_circular(base)

    # 加载手部模板
    templates = _load_templates()

    # 逐帧合成
    images: List = []
    for i in range(FRAMES):
        squeeze = i if i < FRAMES / 2 else FRAMES - i
        width = 0.8 + squeeze * 0.02
        height = 0.8 - squeeze * 0.05
        offsetX = (1 - width) * 0.5 + 0.1
        offsetY = (1 - height) - 0.08

        canvas = Image.new('RGBA', size=RESOLUTION, color=(0, 0, 0, 0))
        # 粘贴缩放后的头像
        avatar_w = round(width * RESOLUTION[0])
        avatar_h = round(height * RESOLUTION[1])
        avatar_x = round(offsetX * RESOLUTION[0])
        avatar_y = round(offsetY * RESOLUTION[1])
        resized_avatar = base.resize((avatar_w, avatar_h))
        canvas.paste(resized_avatar, (avatar_x, avatar_y))
        # 叠加手部模板
        canvas.paste(templates[i], mask=templates[i])
        images.append(canvas)

    # 保存透明 GIF
    _save_transparent_gif(images, durations=DELAY, save_file=dest_path)
    logger.info(f"[PetPet] GIF 生成成功: {dest_path}")
    return dest_path


def generate_petpet_from_avatar(platform: str, user_id: str) -> str:
    """完整流程：下载头像 → 生成 GIF → 返回临时文件路径。

    Args:
        platform: 平台名称
        user_id: 被摸头用户的 ID
    Returns:
        生成的 GIF 临时文件路径
    Raises:
        RuntimeError: 任何步骤失败
    """
    # 下载头像
    avatar_bytes = download_avatar_by_platform(platform, user_id)
    # 生成 GIF 到临时文件
    fd, tmp_path = tempfile.mkstemp(suffix=".gif", prefix="petpet_")
    os.close(fd)
    try:
        generate_petpet(avatar_bytes, tmp_path)
        return tmp_path
    except Exception:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise

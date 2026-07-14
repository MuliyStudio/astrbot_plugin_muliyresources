# -*- coding: utf-8 -*-
"""
舔狗表情 GIF 生成（「给你一脚」功能）
====================================
模板与文字定位逆向自 https://www.diydoutu.com/diy/doutu/389 （马踢舔狗 GIF 加字）。

实际生成逻辑见 `core/doutu_common.py`（通用 diydoutu 引擎）。本文件仅做薄包装：
  - slot0（被@成员，119,36，size 18）
  - slot1（发送者，244,54，size 34）
两个文字位均**头像优先**（圆形头像），无头像时退回白字+黑描边文字兜底。
"""

import os
from .doutu_common import generate_doutu_meme, PIL_AVAILABLE

LICKDOG_PIL_AVAILABLE = PIL_AVAILABLE
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "lickdog")


def generate_lickdog(kicker: str, dog: str, dest_path: str = None,
                    kicker_avatar: bytes = None, dog_avatar: bytes = None) -> str:
    """生成「马踢舔狗」GIF。

    Args:
        kicker: 踢人者（发送指令的人），slot1（244,54，size 34）
        dog:    被踢的舔狗（被@的成员），slot0（119,36，size 18）
        dest_path: 输出 GIF 路径；为 None 时自动生成临时文件
        kicker_avatar / dog_avatar: 头像字节（头像优先；缺则退回文字兜底）
    Returns:
        dest_path
    """
    return generate_doutu_meme(
        os.path.join(_TEMPLATE_DIR, "template.gif"),
        [(119, 36), (244, 54)],   # slot0=dog, slot1=kicker
        [18, 34],
        kicker, dog, dest_path,
        kicker_avatar=kicker_avatar, dog_avatar=dog_avatar,
    )

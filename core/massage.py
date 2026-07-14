# -*- coding: utf-8 -*-
"""
柴犬按摩表情 GIF 生成（「按摩」功能）
====================================
模板与文字定位逆向自 https://www.diydoutu.com/diy/doutu/401 （柴犬帮另一只柴犬按摩动图）。

实际生成逻辑见 `core/doutu_common.py`（通用 diydoutu 引擎）。本文件仅做薄包装：
  - slot0（被@成员，135,28，size 42）
  - slot1（发送者，19,85，size 42）
两个文字位均**头像优先**（圆形头像），无头像时退回白字+黑描边文字兜底。
"""

import os
from .doutu_common import generate_doutu_meme, PIL_AVAILABLE

MASSAGE_PIL_AVAILABLE = PIL_AVAILABLE
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "doutu")


def generate_massage(kicker: str, dog: str, dest_path: str = None,
                    kicker_avatar: bytes = None, dog_avatar: bytes = None) -> str:
    """生成「柴犬按摩」GIF。

    Args:
        kicker: 按摩者（发送指令的人），slot1（19,85，size 42）
        dog:    被按摩的群友（被@的成员），slot0（135,28，size 42）
        dest_path: 输出 GIF 路径；为 None 时自动生成临时文件
        kicker_avatar / dog_avatar: 头像字节（头像优先；缺则退回文字兜底）
    Returns:
        dest_path
    """
    return generate_doutu_meme(
        os.path.join(_TEMPLATE_DIR, "template.gif"),
        [(135, 28), (19, 85)],   # slot0=dog, slot1=kicker
        [42, 42],
        kicker, dog, dest_path,
        kicker_avatar=kicker_avatar, dog_avatar=dog_avatar,
    )

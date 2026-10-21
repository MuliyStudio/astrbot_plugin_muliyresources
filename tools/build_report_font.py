# -*- coding: utf-8 -*-
"""把日报用的思源黑体 Heavy 子集化，供 HTML / Pillow 共用。

产物：
  assets/fonts/MuliHeavy.woff2  HTML @font-face（日报 / 签到卡）
  assets/fonts/MuliHeavy.ttf    Pillow 兜底渲染（不能读 woff2）

源字体（上游 Source Han Sans CN Heavy，OFL）不随插件分发，
需要重新生成时把源 otf 放在仓库根目录或用参数指定。

用法：python tools/build_report_font.py [源otf]
"""
import os
import sys

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "fonts")


def charset() -> str:
    chars = set()
    for b1 in range(0xA1, 0xF8):
        for b2 in range(0xA1, 0xFF):
            try:
                chars.add(bytes([b1, b2]).decode("gb2312"))
            except Exception:
                pass
    chars.update(chr(c) for c in range(0x20, 0x7F))
    chars.update("　·—–…“”‘’【】「」『』《》〈〉、。，！？：；（）％＋－×÷℃№"
                 "①②③④⑤⑥⑦⑧⑨⑩㎡・～￥")
    return "".join(sorted(chars))


def subset(src: str, dst: str, text: str, flavor=None) -> None:
    font = TTFont(src)
    opt = Options()
    opt.desubroutinize = True
    opt.layout_features = ["*"]
    opt.name_IDs = ["*"]
    opt.name_legacy = True
    opt.name_languages = ["*"]
    opt.notdef_outline = True
    opt.recalc_bounds = True
    opt.drop_tables += ["DSIG"]
    ss = Subsetter(options=opt)
    ss.populate(unicodes=[ord(c) for c in text])
    ss.subset(font)
    if flavor:
        font.flavor = flavor
    font.save(dst)
    print(f"{os.path.basename(dst)}  {os.path.getsize(dst)/1024/1024:.2f} MB")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "SourceHanSansCN-Heavy.otf")
    os.makedirs(OUT_DIR, exist_ok=True)
    text = charset()
    print(f"字符集：{len(text)} 个")
    subset(src, os.path.join(OUT_DIR, "MuliHeavy.woff2"), text, "woff2")
    subset(src, os.path.join(OUT_DIR, "MuliHeavy.ttf"), text)


if __name__ == "__main__":
    main()

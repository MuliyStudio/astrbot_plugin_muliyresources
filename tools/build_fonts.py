# -*- coding: utf-8 -*-
"""生成可内嵌的思源黑体 / 思源宋体子集（GB2312 全字集 + ASCII + 常用标点）。

用 Google Fonts 的可变字体（Noto Sans SC / Noto Serif SC，SIL OFL）：
  NotoSansSC[wght].ttf  → assets/fonts/MuliSans.woff2
  NotoSerifSC[wght].ttf → assets/fonts/MuliSerif.woff2

只保留 GB2312 的 6763 个汉字和常用符号，体积从 16~23MB 压到 2MB 左右；
生僻字仍会回退到系统字体，不影响正常阅读。

用法：
  python tools/build_fonts.py <sans.ttf> <serif.ttf>
"""
import os
import sys

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "fonts")


def charset() -> str:
    chars = set()
    # GB2312 全部合法双字节编码（6763 汉字 + 希腊/西里尔/假名/符号）
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


def build(src: str, dst: str, text: str) -> None:
    font = TTFont(src)
    opt = Options()
    opt.flavor = "woff2"
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
    font.flavor = "woff2"
    font.save(dst)
    print(f"{os.path.basename(dst)}  {os.path.getsize(dst)/1024/1024:.2f} MB")


def main():
    sans = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ["TEMP"], "opencode", "fonts", "sans.ttf")
    serif = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.environ["TEMP"], "opencode", "fonts", "serif.ttf")
    os.makedirs(OUT_DIR, exist_ok=True)
    text = charset()
    print(f"字符集：{len(text)} 个")
    build(sans, os.path.join(OUT_DIR, "MuliSans.woff2"), text)
    build(serif, os.path.join(OUT_DIR, "MuliSerif.woff2"), text)


if __name__ == "__main__":
    main()

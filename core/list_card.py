# -*- coding: utf-8 -*-
"""搜索结果列表卡片：把「超长列表」渲染成图片，替掉刷屏的纯文本。

适用场景（列表条目多、文本读起来累）：
  · 小说多源聚合搜索结果（书名 / 作者 / 书源）
  · 影视网盘资源列表（资源名 / 网盘类型 / 分享者 / 时间）

设计基底沿用 oil-html：白纸 + 极淡网格纹理 + 黑字 + 暖黄高亮。
图片在聊天窗口里会被等比缩小，所以正文字号不低于 14px，
数字用等宽tabular-nums，行距放宽，扫读时不挤。

渲染性能（这是本模块的重点）：
  1. 常驻渲染线程 + 复用同一个 Chromium 实例和 Page，
     避免每次渲染都付 1~2 秒的浏览器冷启动；
  2. 用 set_content 直接注入 HTML，不落地临时文件、不跑 goto；
  3. 等 document.fonts.ready + 两帧 rAF 就截图，不做固定 sleep；
  4. 截图直接出 JPEG（quality 84），省掉 PNG 编码与二次压缩；
  5. 同一张卡片 10 分钟内命中内存缓存，翻页来回切是 0 耗时；
  6. 空闲 10 分钟自动关掉浏览器释放内存，下次用再拉起。

渲染失败一律返回 None，由调用方回退纯文本，不影响原有流程。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import queue
import re
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from html import escape

from .constants import logger
from .brand import logo_img
from .mdi_icons import svg as _svg
from .episode_utils import (
    episode_display_name, episode_page_size, episode_pages,
    episodes_are_named, node_episodes, normalize_ep_page,
)

CARD_WIDTH = 760          # CSS 像素宽度（截图按 scale 放大）
DEFAULT_SCALE = 2         # 2x 出图，聊天里缩放到手机宽度仍清晰
_JPEG_QUALITY = 84
_CACHE_TTL = 600.0        # 缓存有效期（秒）
_CACHE_MAX = 32           # 最多缓存多少张卡片
_IDLE_SHUTDOWN = 600.0    # 渲染线程空闲多久关浏览器
_RENDER_TIMEOUT = 15.0    # 单张卡片渲染超时（秒）
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
_FONT_FILES = ("MuliSans.woff2", "MuliSerif.woff2")

# emoji / 装饰符号（卡片不依赖 emoji 字体，统一清掉）
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF"      # 表情、符号、旗帜主体
    "\U0001F1E6-\U0001F1FF"       # 区域指示符
    "\u2600-\u27BF"               # 杂项符号 / dingbats
    "\u2B00-\u2BFF"               # 箭头星形补充
    "\uFE00-\uFE0F"               # variation selectors
    "\u20E3"                      # keycap
    "\u200D"                      # ZWJ
    "\U000E0020-\U000E007F]"      # 标签字符
)
_BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
]

# ==================== 设计系统（内联 CSS）====================

_CSS = """
@font-face{font-family:'Muli Sans';src:url('MuliSans.woff2') format('woff2');
  font-weight:100 900;font-style:normal;font-display:block}
@font-face{font-family:'Muli Serif';src:url('MuliSerif.woff2') format('woff2');
  font-weight:200 900;font-style:normal;font-display:block}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased}
body{
  font-family:'Muli Sans','Noto Sans SC','PingFang SC','Microsoft YaHei UI','Microsoft YaHei',
              'Noto Sans CJK SC','Source Han Sans SC','Hiragino Sans GB',sans-serif;
  color:#1a1a1a;background:#f4f4f5;letter-spacing:.01em;
  -webkit-font-smoothing:antialiased;
}
.canvas{
  padding:20px;background-color:#f4f4f5;
  background-image:
    radial-gradient(ellipse 70% 30% at 50% 0%,rgba(255,226,138,.28),rgba(255,226,138,0) 72%),
    linear-gradient(rgba(0,0,0,.032) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,0,0,.032) 1px,transparent 1px);
  background-size:100% 100%,32px 32px,32px 32px;
}
.sheet{
  background:#fff;border:1px solid #e8e8e8;border-radius:22px;
  padding:26px 30px 24px;
  box-shadow:0 1px 2px rgba(0,0,0,.03),0 12px 30px rgba(0,0,0,.045);
}

/* ---- 头部 ---- */
.head{display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding-bottom:16px;border-bottom:1px solid #f0f0f0}
.brand{display:flex;align-items:center;gap:10px;font-size:14px;color:#9a9a9a}
.brand-logo{width:27px;height:27px;flex:0 0 auto;display:flex;align-items:center;justify-content:center}
.brand-logo img{width:27px;height:27px;display:block}
.brand-fallback{width:28px;height:28px;border-radius:9px;background:#1a1a1a;color:#fff;
  font-size:14px;font-weight:700;display:flex;align-items:center;justify-content:center}
.brand-name{font-size:14px;font-weight:600;color:#1a1a1a;letter-spacing:.05em}
.brand-sep{width:1px;height:11px;background:#e2e2e2}
.brand-kind{font-size:14px;color:#9a9a9a;letter-spacing:.02em;
  display:inline-flex;align-items:center;gap:5px}
.brand-kind svg{display:block;opacity:.85}
.page-ind{font-size:14px;color:#9a9a9a;white-space:nowrap}

/* ---- 标题区 ---- */
.title-wrap{padding:20px 0 14px}
.title{font-size:31px;font-weight:700;line-height:1.3;letter-spacing:-.01em;
  word-break:break-word;font-family:'Muli Serif','Muli Sans','Noto Sans SC',
  'PingFang SC','Microsoft YaHei',sans-serif}
.hl{background:linear-gradient(transparent 60%,#ffe28a 60%,#ffe28a 93%,transparent 93%);
  padding:0 3px}
.subtitle{margin-top:9px;font-size:14px;color:#8a8a8a;line-height:1.7}
.subtitle .dot{margin:0 7px;color:#d4d4d4}

/* ---- 列表 ---- */
.rows{list-style:none}
.row{display:flex;gap:14px;padding:14px 0;border-radius:12px}
.row+.row{border-top:1px solid #f2f2f2}
.num{flex:0 0 auto;width:30px;height:30px;margin-top:1px;border-radius:10px;
  border:1px solid #e6e6e6;background:#fafafa;color:#1a1a1a;
  font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center;
  font-variant-numeric:tabular-nums}
/* 行首封面：有图放图，无图用标题色相生成渐变块，保证每行视觉节奏一致 */
.row-cover{position:relative;flex:0 0 auto;width:58px;height:80px;margin-top:1px;
  border-radius:10px;overflow:hidden;background:#f2f2f2;
  border:1px solid rgba(0,0,0,.045);display:flex;align-items:center;justify-content:center}
.row-cover.icon{width:56px;height:56px;margin-top:5px;border-radius:14px;border:none}
.row-cover.icon svg{display:block;opacity:.95}
.row-cover.square{width:56px;height:56px;margin-top:5px;border-radius:14px}
.row-cover-wrap{position:relative;flex:0 0 auto;display:block;align-self:flex-start}
.row-cover img{display:block;width:100%;height:100%;object-fit:cover}
.row-cover.ph .ph-char{font-size:23px;font-weight:700;color:rgba(255,255,255,.96);
  line-height:1;text-shadow:0 1px 2px rgba(0,0,0,.18)}
.row-no{position:absolute;left:4px;top:4px;z-index:2;min-width:20px;height:20px;
  padding:0 5px;border-radius:6px;background:rgba(22,22,22,.74);color:#fff;
  font-size:12px;font-weight:700;line-height:20px;text-align:center;
  font-variant-numeric:tabular-nums;box-shadow:0 1px 3px rgba(0,0,0,.22)}
.row-main{flex:1;min-width:0}
.row-line{display:flex;align-items:flex-start;gap:10px}
.row-title{flex:1;min-width:0;font-size:18px;font-weight:600;line-height:1.45;
  color:#1a1a1a;word-break:break-word;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.row-meta{margin-top:6px;display:flex;align-items:center;gap:9px;flex-wrap:wrap;
  font-size:14px;color:#8a8a8a;line-height:1.5}
.row-meta .dot{color:#d4d4d4}
.chip{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:6px;
  font-size:14px;font-weight:500;white-space:nowrap}
.chip-src{background:#f9f0d8;color:#7a6520}
.chip-pan{flex:0 0 auto;margin-top:3px;background:#f5f5f5;color:#555;height:23px}

/* ---- 选集宫格 ---- */
.ep-grid{display:grid;gap:9px}
.ep-grid.named{grid-template-columns:repeat(3,1fr)}
.ep-grid.plain{grid-template-columns:repeat(6,1fr)}
.ep-cell{background:#fafafa;border:1px solid #ededed;border-radius:11px;
  padding:9px 11px;min-width:0}
.ep-grid.plain .ep-cell{display:flex;align-items:center;justify-content:center;
  padding:9px 4px}
.ep-cell.named{background:#fffdf3;border-color:#f2e9cd}
.ep-num{display:block;font-size:17px;font-weight:700;line-height:1.25;
  font-variant-numeric:tabular-nums;color:#2a2a2a}
.ep-grid.plain .ep-num{font-size:18px}
.ep-cell.named .ep-num{color:#7a6520}
.ep-name{display:-webkit-box;margin-top:4px;overflow:hidden;font-size:14px;
  color:#7a7a7a;line-height:1.45;word-break:break-word;
  -webkit-line-clamp:2;-webkit-box-orient:vertical}
.ep-cell.named .ep-name{color:#6c5a1e}

/* ---- 小游戏结算 ---- */
.chip-win{background:#eef8ef;color:#1f7a3d}
.chip-loss{background:#faf3e1;color:#8a6a1f}
.chip-gold{background:#ffe28a;color:#5c4a12}

/* ---- 小游戏大厅 / 组队 / 题目 ---- */
.mg-games{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.mg-game{background:#fafafa;border:1px solid #ededed;border-radius:16px;padding:16px}
.mg-game-top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.mg-icon{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;
  justify-content:center;flex:0 0 auto}
.mg-icon-bomb{background:#fff1e0;color:#c2410c}
.mg-icon-number{background:#eef8ef;color:#1f7a3d}
.mg-icon-cover{background:#eef4ff;color:#2563eb}
.mg-badge{font-size:12px;color:#8a8a8a;background:#f1f1f2;padding:3px 8px;border-radius:999px;
  white-space:nowrap}
.mg-game-name{margin-top:12px;font-size:21px;font-weight:700;line-height:1.3}
.mg-game-desc{margin-top:7px;font-size:14px;line-height:1.65;color:#7a7a7a;min-height:66px}
.mg-game-meta{margin-top:10px;font-size:13px;color:#9a9a9a;display:flex;gap:8px;
  align-items:center;flex-wrap:wrap}
.mg-game-key{margin-top:12px;font-size:14px;color:#5c5c5c;display:flex;align-items:center;gap:8px}
.mg-key{display:inline-flex;width:26px;height:26px;border-radius:8px;background:#1a1a1a;
  color:#fff;font-weight:700;font-size:14px;align-items:center;justify-content:center}
.mg-wait{display:flex;gap:24px;align-items:center;margin-top:4px}
.mg-timer{flex:0 0 auto;width:122px;height:122px;border-radius:50%;border:2px solid #ffe28a;
  background:#fffdf3;display:flex;flex-direction:column;align-items:center;justify-content:center}
.mg-timer b{font-size:46px;line-height:1;font-variant-numeric:tabular-nums}
.mg-timer small{font-size:12px;color:#9a8a4a;margin-top:6px}
.mg-players{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:8px;min-width:0}
.mg-player{background:#fafafa;border:1px solid #ededed;border-radius:10px;padding:8px 10px;
  font-size:14px;display:flex;gap:8px;align-items:center;min-width:0}
.mg-player .no{font-size:12px;color:#9a9a9a;width:16px;flex:0 0 auto}
.mg-player .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mg-player .host{font-size:11px;color:#8a6a1f;background:#f9f0d8;padding:1px 6px;
  border-radius:6px;flex:0 0 auto}
.mg-player.empty{color:#c4c4c4;border-style:dashed;background:#fff}
.mg-note{margin-top:14px;font-size:14px;color:#7a7a7a;line-height:1.75}
.mg-note b{color:#1a1a1a}
.mg-types{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.mg-type{background:#fafafa;border:1px solid #ededed;border-radius:14px;padding:14px}
.mg-type-top{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:700}
.mg-type-desc{margin-top:6px;font-size:13px;color:#8a8a8a;line-height:1.6}
.mg-type-key{margin-top:10px;font-size:13px;color:#5c5c5c}
.mg-cover-wrap{display:flex;gap:22px;align-items:flex-start}
.mg-cover{flex:0 0 230px;border-radius:14px;overflow:hidden;background:#f2f2f2;
  border:1px solid #e8e8e8}
.mg-cover img{display:block;width:230px;height:auto}
.mg-cover-side{flex:1;min-width:0}
.mg-hint{font-size:14px;color:#8a7a45;background:#fffdf3;border:1px solid #f2e9cd;
  border-radius:10px;padding:9px 12px;margin-bottom:10px;line-height:1.6}
.mg-opts{display:flex;flex-direction:column;gap:8px}
.mg-opt{display:flex;align-items:center;gap:10px;background:#fafafa;border:1px solid #ededed;
  border-radius:12px;padding:10px 12px}
.mg-opt .l{flex:0 0 auto;width:28px;height:28px;border-radius:8px;background:#1a1a1a;
  color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center;
  font-size:14px}
.mg-opt .t{font-size:15px;font-weight:600;line-height:1.45;word-break:break-word}

/* ---- 影视详情卡 ---- */
.md-hero{display:flex;gap:22px;align-items:flex-start}
.md-cover{flex:0 0 220px;border-radius:14px;overflow:hidden;background:#f2f2f2;
  border:1px solid #e8e8e8}
.md-cover img{display:block;width:220px;height:auto}
.md-cover .ph{width:220px;height:300px;display:flex;align-items:center;
  justify-content:center;font-size:54px;font-weight:800;color:#c4c4c4;background:#f7f7f8}
.md-main{flex:1;min-width:0}
.md-tags{display:flex;flex-wrap:wrap;gap:7px}
.md-tag{display:inline-flex;align-items:center;gap:4px;height:24px;padding:0 9px;
  border-radius:7px;background:#f5f5f6;color:#5c5c5c;font-size:13px;white-space:nowrap}
.md-tag svg{display:block;opacity:.82;flex:0 0 auto}
.md-tag.score{background:#fffdf3;color:#8a6a1f}
.md-credits{margin-top:14px;font-size:14px;line-height:2;color:#5c5c5c}
.md-credits .k{display:inline-flex;align-items:center;gap:4px;min-width:44px;
  color:#a3a3a3;vertical-align:middle}
.md-credits .k svg{display:block;opacity:.8;flex:0 0 auto}
.md-desc{margin-top:12px;font-size:14px;line-height:1.8;color:#6f6f6f;
  white-space:pre-wrap;word-break:break-word}
.md-shots{margin-top:20px}
.md-shots-title{font-size:14px;color:#9a9a9a;display:flex;align-items:center;gap:6px}
.md-shot-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:8px}
.md-shot-grid.one{grid-template-columns:1fr}
.md-shot-grid.two{grid-template-columns:repeat(2,1fr)}
.md-shot-grid.hero{grid-template-columns:repeat(2,1fr)}
.md-shot-grid.hero .md-shot:first-child{grid-column:1/-1}
.md-shot{border-radius:10px;overflow:hidden;background:#f2f2f2;border:1px solid #ededed}
.md-shot img{display:block;width:100%;height:auto}
.md-empty{margin-top:18px;padding:12px 14px;border-radius:10px;background:#fafafa;
  color:#9a9a9a;font-size:14px}

/* ---- 通用详情信息（游戏 / 软件 / 短剧 / 小说）---- */
.dt-head{display:flex;align-items:center;gap:15px;padding:16px 18px;border-radius:16px;
  background:linear-gradient(135deg,#fffdf3,#f7f7f8);border:1px solid #f2e9cd}
.dt-icon{flex:0 0 auto;width:56px;height:56px;border-radius:15px;background:#ffe28a;
  color:#5c4a12;display:flex;align-items:center;justify-content:center;overflow:hidden}
.dt-icon.cover{padding:0;background:#f2f2f2;border:1px solid rgba(0,0,0,.05)}
.dt-icon.cover img{display:block;width:100%;height:100%;object-fit:cover}
.dt-head-main{flex:1;min-width:0}
.dt-head-sub{margin-top:6px;font-size:14px;color:#8a7a45;line-height:1.55}

/* ---- 底部提示 ---- */
.foot{margin-top:18px;padding:14px 18px;border-radius:14px;background:#f7f7f8;
  font-size:14px;color:#5c5c5c;line-height:1.95}
.foot b{font-weight:600;color:#1a1a1a}
.foot .k{display:inline-block;min-width:38px;color:#a3a3a3}
.foot .dim{color:#9a9a9a}
.foot .note{color:#8a7a45}

/* ---- 积分卡 ---- */
.p-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-top:4px}
.p-label{font-size:14px;color:#9a9a9a}
.p-balance{margin-top:7px;font-size:58px;font-weight:800;line-height:.95;
  letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.p-balance small{font-size:18px;font-weight:600;color:#8a8a8a;margin-left:8px;letter-spacing:0}
.p-status{flex:0 0 auto;margin-bottom:8px;padding:6px 12px;border-radius:999px;
  font-size:14px;font-weight:600;white-space:nowrap}
.p-status.on{background:#eef8ef;color:#1f7a3d}
.p-status.off{background:#faf3e1;color:#8a6a1f}
.p-status.off-system{background:#f2f2f4;color:#6f6f74}
.p-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:20px}
.p-cell{background:#f7f7f8;border-radius:14px;padding:13px 16px}
.p-cell .k{font-size:14px;color:#9a9a9a}
.p-cell .v{margin-top:5px;font-size:22px;font-weight:700;line-height:1.25;
  font-variant-numeric:tabular-nums}
.p-cell .v small{font-size:14px;font-weight:500;color:#9a9a9a;margin-left:3px}
.p-cell .v.date{font-size:18px;font-weight:600}
.p-sec{margin-top:22px;font-size:14px;color:#9a9a9a}
.p-costs{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.p-cost{display:inline-flex;align-items:baseline;gap:6px;padding:6px 11px;border-radius:9px;
  background:#f7f7f8;font-size:14px;color:#3a3a3a;white-space:nowrap}
.p-cost b{font-weight:700;font-variant-numeric:tabular-nums;color:#1a1a1a}
.p-cost i{font-style:normal;font-size:14px;color:#9a9a9a}

/* ---- 积分排行 ---- */
.rk{list-style:none}
.rk-row{display:flex;align-items:center;gap:12px;padding:11px 0}
.rk-row+.rk-row{border-top:1px solid #f2f2f2}
.rk-no{flex:0 0 auto;width:28px;height:28px;border-radius:9px;display:flex;
  align-items:center;justify-content:center;font-size:14px;font-weight:700;
  font-variant-numeric:tabular-nums;border:1px solid #e6e6e6;color:#8a8a8a;background:#fafafa}
.rk-no.gold{background:#ffe28a;border-color:#ffe28a;color:#5c4a12}
.rk-no.top{background:#1a1a1a;border-color:#1a1a1a;color:#fff}
.rk-av{flex:0 0 auto;width:40px;height:40px;border-radius:50%;overflow:hidden;background:#f9f0d8}
.rk-av img{width:40px;height:40px;display:block;object-fit:cover}
.rk-av .ph{width:40px;height:40px;display:flex;align-items:center;justify-content:center;
  font-size:16px;font-weight:600;color:#7a6520}
.rk-main{flex:1;min-width:0}
.rk-name{display:block;font-size:17px;font-weight:600;line-height:1.4;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rk-sub{display:block;margin-top:1px;font-size:14px;color:#9a9a9a}
.rk-sub.off{color:#c4c4c4}
.rk-pts{flex:0 0 auto;font-size:19px;font-weight:800;font-variant-numeric:tabular-nums;
  letter-spacing:-.01em}
.rk-pts small{font-size:14px;font-weight:500;color:#9a9a9a;margin-left:3px}
.me-chip{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:6px;
  background:#ffe28a;color:#5c4a12;font-size:14px;font-weight:600;vertical-align:2px}
"""


# ==================== HTML 构建 ====================

def _strip_emoji(text: str) -> str:
    """去掉标题里的 emoji / 装饰符号。

    卡片不走 emoji 字体（服务器没装就会显示方块），网盘标题里又常带
    🔥🔥🚩🚩 这类前缀，直接清掉更干净。纯 emoji 的标题会保留原文，
    避免渲染成空行。
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    cleaned = _EMOJI_RE.sub("", raw)
    # 顺带清掉标题开头的方块/几何装饰符号（如 ◀▉▉、【源站】前的杂符）
    cleaned = re.sub(r"^[\s\u2500-\u25FF\u2B00-\u2BFF]+", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned or raw


def _clip(text: str, limit: int) -> str:
    text = _strip_emoji(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _page_text(page: int, pages: int) -> str:
    if pages <= 1:
        return "全部结果"
    return f"第 {page + 1} / {pages} 页"


def _page_shell(*, kind: str, page_ind: str, title: str, subtitle: str,
                body: str, foot: str, icon_html: str = "") -> str:
    """拼一张完整卡片（列表 / 积分等共用）。title 可含 <span class="hl">。"""
    logo = logo_img(27)
    brand_logo = (f'<span class="brand-logo">{logo}</span>' if logo
                  else '<span class="brand-fallback">暮</span>')
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>{_CSS}</style></head>
<body>
<div class="canvas">
  <div class="sheet">
    <div class="head">
      <div class="brand">
        {brand_logo}
        <span class="brand-name">暮黎资源</span>
        <span class="brand-sep"></span>
        <span class="brand-kind">{icon_html}{escape(kind)}</span>
      </div>
      <div class="page-ind">{escape(page_ind)}</div>
    </div>
    <div class="title-wrap">
      <div class="title">{title}</div>
      <div class="subtitle">{subtitle}</div>
    </div>
    {body}
    {foot}
  </div>
</div>
</body></html>"""


def _shell(*, kind: str, page_ind: str, title: str, subtitle: str,
           rows: str, foot: str, icon_html: str = "") -> str:
    body = f'<ol class="rows">\n{rows}\n    </ol>'
    return _page_shell(kind=kind, page_ind=page_ind, title=title,
                       subtitle=subtitle, body=body, foot=foot,
                       icon_html=icon_html)


def _hue(text: str) -> int:
    """由标题稳定生成色相，保证同一资源每次渲染的渐变色一致。"""
    try:
        digest = hashlib.md5((text or "").encode("utf-8")).hexdigest()
        return int(digest[:2], 16) * 360 // 256
    except Exception:  # noqa: BLE001
        return 214


def _row_cover(text: str, cover: str = "", icon: str = "",
               square: bool = False) -> str:
    """行首视觉：有图用图；没有图用 56×56 小图标；再兜底才用首字渐变块。"""
    if cover:
        src = cover if cover.startswith("data:") else f"data:image/jpeg;base64,{cover}"
        cls = "row-cover square" if square else "row-cover"
        return f'<span class="{cls}"><img src="{src}" alt=""></span>'
    h = _hue(text)
    if icon:
        return (f'<span class="row-cover icon" style="background:linear-gradient(145deg,'
                f'hsl({h} 62% 58%),hsl({(h + 28) % 360} 64% 42%))">'
                f'{_svg(icon, 34, "#fff")}</span>')
    char = escape(_initial(text))
    return (f'<span class="row-cover ph" style="background:linear-gradient(145deg,'
            f'hsl({h} 62% 58%),hsl({(h + 28) % 360} 64% 42%))">'
            f'<span class="ph-char">{char}</span></span>')


def _rows(items: list) -> str:
    out = []
    for it in items:
        title = escape(it['title'])
        if it.get("me"):
            title += '<span class="me-chip">你</span>'
        cover = it.get("cover") or ""
        if it.get("tile"):
            h = _hue(it['title'])
            leading = (f'<span class="row-cover-wrap">'
                       f'{_row_cover(it["title"], cover, it.get("icon") or "", bool(it.get("square")))}'
                       f'<span class="row-no">{it["n"]}</span></span>')
            style = (f' style="background:linear-gradient(90deg,'
                     f'hsla({h},72%,56%,.065),rgba(255,255,255,0) 64%)"')
        else:
            leading = f'<span class="num">{it["n"]}</span>'
            style = ""
        out.append(f"""      <li class="row"{style}>
        {leading}
        <div class="row-main">
          <div class="row-line">
            <div class="row-title">{title}</div>{it.get('right', '')}
          </div>
          <div class="row-meta">{it.get('meta', '')}</div>
        </div>
      </li>""")
    return "\n".join(out)


def _foot(lines: list) -> str:
    html = "\n".join(lines)
    return f'<div class="foot">\n{html}\n    </div>'


def _clean_note(note: str) -> str:
    """把扣费提示压成一行干净文案（去掉 emoji、广告括号与多余空行）。"""
    if not note:
        return ""
    text = " ".join(note.split())
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
    text = re.sub(r"[（(][^）)]*签到[^）)]*[）)]", "", text)
    return text.strip()


def novel_card_html(ses: dict, *, timeout: int = 120, note: str = "") -> str:
    """小说多源聚合搜索结果卡片（与 _format_novel_page 同分页口径）。"""
    results = ses.get("results") or []
    total = len(results)
    ps = max(1, int(ses.get("page_size", 8) or 8))
    pages = max(1, (total + ps - 1) // ps)
    page = max(0, min(int(ses.get("page", 0) or 0), pages - 1))
    st, ed = page * ps, min(page * ps + ps, total)
    keyword = (ses.get("keyword") or "").strip() or "小说"

    items = []
    for i, x in enumerate(results[st:ed], 1):
        author = (x.get("author") or "佚名").strip()
        src = (x.get("source_name") or "未知书源").strip()
        meta = (f'<span>{escape(_strip_emoji(author))}</span>'
                f'<span class="dot">·</span>'
                f'<span class="chip chip-src">{escape(_strip_emoji(src))}</span>')
        items.append({
            "n": i,
            "title": _clip(x.get("book_name") or "未知书名", 40),
            "meta": meta,
            "tile": True, "icon": "book",
        })

    subtitle = (f'共 <b>{total}</b> 条结果'
                f'<span class="dot">·</span>多书源聚合'
                f'<span class="dot">·</span>本页 {ed - st} 条')

    lines = [f'<div><span class="k">选择</span>回复数字 <b>1–{ed - st}</b>；回复 <b>0</b> 取消</div>']
    if pages > 1:
        lines.append('<div><span class="k">翻页</span>「下一页」/「上一页」/「跳 3」'
                     f'<span class="dim"> · {timeout} 秒无操作自动结束</span></div>')
    else:
        lines.append(f'<div class="dim"><span class="k">超时</span>{timeout} 秒无操作自动结束</div>')
    note = _clean_note(note)
    if note:
        lines.append(f'<div class="note"><span class="k">积分</span>{escape(note)}</div>')

    return _shell(
        kind="小说搜索",
        icon_html=_svg("book", 15, "currentColor"),
        page_ind=_page_text(page, pages),
        title=f'<span class="hl">{escape(_strip_emoji(keyword))}</span>',
        subtitle=subtitle,
        rows=_rows(items),
        foot=_foot(lines),
    )


def pan_card_html(panlist: list, *, page: int = 0, page_size: int = 12,
                  type_filter: str = "", title: str = "", year: str = "",
                  timeout: int = 120) -> str:
    """影视网盘资源列表卡片（与 format_pan_list 同分页口径）。"""
    if type_filter:
        panlist = [p for p in panlist if p.get("type", "") == type_filter]
    total = len(panlist)
    ps = max(1, int(page_size or 12))
    pages = max(1, (total + ps - 1) // ps)
    page = max(0, min(int(page or 0), pages - 1))
    st, ed = page * ps, min(page * ps + ps, total)

    items = []
    for i, p in enumerate(panlist[st:ed], 1):
        name = _clip(p.get("name") or "未命名资源", 58)
        pan_type = _strip_emoji(p.get("type") or "网盘").strip() or "网盘"
        meta_bits = []
        if p.get("user"):
            meta_bits.append(escape(_strip_emoji(str(p["user"]).strip())))
        if p.get("time"):
            meta_bits.append(escape(_strip_emoji(str(p["time"]).strip())))
        meta = '<span class="dot">·</span>'.join(meta_bits) or '<span class="dim">资源直链</span>'
        items.append({
            "n": i,
            "title": name,
            "right": f'<span class="chip chip-pan">{escape(pan_type)}</span>',
            "meta": meta,
            "tile": True, "icon": "cloud",
        })

    head_title = escape(_clip(title or "网盘资源", 26))
    if year and title:
        head_title += f' <span style="font-size:18px;color:#9a9a9a;font-weight:500">({escape(_strip_emoji(str(year)))})</span>'

    subtitle = (f'共 <b>{total}</b> 个资源'
                f'<span class="dot">·</span>{escape(_strip_emoji(type_filter)) if type_filter else "全部网盘"}'
                f'<span class="dot">·</span>本页 {ed - st} 个')

    lines = [f'<div><span class="k">选择</span>回复数字 <b>1–{ed - st}</b>；回复 <b>0</b> 取消</div>']
    if pages > 1:
        lines.append('<div><span class="k">翻页</span>「下一页」/「上一页」/「跳 3」'
                     f'<span class="dim"> · {timeout} 秒无操作自动结束</span></div>')
    else:
        lines.append(f'<div class="dim"><span class="k">超时</span>{timeout} 秒无操作自动结束</div>')

    return _shell(
        kind="网盘资源",
        icon_html=_svg("cloud", 15, "currentColor"),
        page_ind=_page_text(page, pages),
        title=head_title,
        subtitle=subtitle,
        rows=_rows(items),
        foot=_foot(lines),
    )


def episode_card_html(detail: dict, node: dict, *, page: int = 0,
                      timeout: int = 120) -> str:
    """在线播放选集卡片：纯序号用 6 列数字键盘，有集名时用 3 列宫格。

    分页口径与 `format_episode_list` 完全一致；回复数字仍是**全局集序号**
    （不受当前页影响），所以用户可以直接输入任意集数。
    """
    detail = detail or {}
    node = node or {}
    eps = node_episodes(node)
    total = len(eps)
    named = episodes_are_named(eps)
    size = episode_page_size(eps)
    pages = episode_pages(total, size)
    page = normalize_ep_page(page, total, size)
    st, ed = page * size, min(page * size + size, total)

    cells = []
    for i, ep in enumerate(eps[st:ed], st + 1):
        label = _strip_emoji(episode_display_name(ep.get("name"))) if named else ""
        if label:
            cells.append(
                f'<div class="ep-cell named"><span class="ep-num">{i}</span>'
                f'<span class="ep-name">{escape(label)}</span></div>')
        else:
            cells.append(
                f'<div class="ep-cell"><span class="ep-num">{i}</span></div>')
    grid_cls = "named" if named else "plain"
    body = (f'<div class="ep-grid {grid_cls}">\n'
            + "\n".join(cells) + "\n    </div>")

    head_title = escape(_clip(detail.get("name") or "在线播放", 24))
    bits = [f'共 <b>{total}</b> 集']
    node_t = _strip_emoji(str(node.get("t") or "")).strip()
    if node_t:
        bits.insert(0, escape(node_t))
    if named:
        bits.append("含集名")
    bits.append(f"本页 {st + 1}–{ed}")
    subtitle = '<span class="dot">·</span>'.join(bits)

    lines = [f'<div><span class="k">选集</span>回复数字 <b>1–{total}</b>'
             f'<span class="dim">（可直接输入任意集数）</span>；回复 <b>0</b> 取消</div>']
    if pages > 1:
        lines.append('<div><span class="k">翻页</span>「上一页」/「下一页」/「末页」/「跳 3」'
                     f'<span class="dim"> · 末页=最新 · {timeout} 秒无操作自动结束</span></div>')
    else:
        lines.append(f'<div class="dim"><span class="k">超时</span>{timeout} 秒无操作自动结束</div>')

    return _page_shell(
        kind="选集播放",
        icon_html=_svg("movie", 15, "currentColor"),
        page_ind=(f"第 {page + 1} / {pages} 页" if pages > 1 else "全部集数"),
        title=head_title,
        subtitle=subtitle,
        body=body,
        foot=_foot(lines),
    )


def minigame_lobby_html(*, reward_text: str = "", timeout: int = 90) -> str:
    """群游戏大厅：两张玩法卡片 + 编号入口。"""
    guess_icon = _svg("casino", 22, "currentColor")
    cover_icon = _svg("movie", 22, "currentColor")
    users = _svg("users", 13, "currentColor")
    clock = _svg("clock", 13, "currentColor")
    body = f"""    <div class="mg-games">
      <div class="mg-game">
        <div class="mg-game-top">
          <span class="mg-icon mg-icon-number">{guess_icon}</span>
          <span class="mg-badge">多人轮流</span>
        </div>
        <div class="mg-game-name">猜数字</div>
        <div class="mg-game-desc">1-100 起，人数越多范围越大；每次提示大了/小了，猜中直接赢积分。</div>
        <div class="mg-game-meta">{users} 1-6 人<span class="dot">·</span>{clock} 约 2 分钟</div>
        <div class="mg-game-key"><span class="mg-key">1</span> 开始组队</div>
      </div>
      <div class="mg-game">
        <div class="mg-game-top">
          <span class="mg-icon mg-icon-cover">{cover_icon}</span>
          <span class="mg-badge">四选一</span>
        </div>
        <div class="mg-game-name">封面猜猜</div>
        <div class="mg-game-desc">选电影 / 电视剧 / 动漫，看马赛克封面猜片名，四选一作答。</div>
        <div class="mg-game-meta">{users} 1-10 人<span class="dot">·</span>{clock} 约 2 分钟</div>
        <div class="mg-game-key"><span class="mg-key">2</span> 选择题库</div>
      </div>
    </div>"""
    foot = ['<div><span class="k">选择</span>回复 <b>1</b> 猜数字 / <b>2</b> 封面猜猜；回复 <b>0</b> 关闭</div>']
    if reward_text:
        foot.append(f'<div><span class="k">奖励</span>{escape(reward_text)}</div>')
    foot.append(f'<div class="dim"><span class="k">超时</span>{timeout} 秒内未选择自动关闭</div>')
    return _page_shell(
        kind="暮黎游戏厅",
        icon_html=_svg("gamepad", 15, "currentColor"),
        page_ind="群聊小游戏",
        title='<span class="hl">今晚玩点什么？</span>',
        subtitle="一局几分钟，群友一起玩",
        body=body,
        foot=_foot(foot),
    )


def minigame_bomb_wait_html(*, host_name: str, players: list | None = None,
                            seconds: int = 30, max_players: int = 6,
                            timeout: int = 90) -> str:
    """猜数字组队卡：倒计时 + 已加入玩家 + 空位。"""
    players = players or []
    cells = []
    for i, p in enumerate(players[:max_players], 1):
        name = escape(_clip(p.get("name") or "玩家", 10))
        host = '<span class="host">房主</span>' if p.get("host") else ""
        cells.append(f'<div class="mg-player"><span class="no">{i}</span>'
                     f'<span class="nm">{name}</span>{host}</div>')
    show_slots = max_players
    for i in range(len(players), show_slots):
        cells.append(f'<div class="mg-player empty"><span class="no">{i + 1}</span>'
                     f'<span class="nm">等待加入…</span></div>')
    body = f"""    <div class="mg-wait">
      <div class="mg-timer"><b>{int(seconds)}</b><small>秒后开始</small></div>
      <div class="mg-players">{"".join(cells)}</div>
    </div>
    <div class="mg-note">群友回复 <b>1</b> 加入；房主回复 <b>2</b> 立即开始。<br>
      人数越多范围越大（1 人 1-100，6 人 1-600），猜中直接获胜；<br>
      {int(timeout)} 秒内无人加入将进入<b>单人猜数字</b>（猜中即获胜）。</div>"""
    return _page_shell(
        kind="猜数字",
        icon_html=_svg("casino", 15, "currentColor"),
        page_ind="组队中",
        title='<span class="hl">猜数字 · 组队</span>',
        subtitle=f"房主 {escape(_clip(host_name or '玩家', 12))} 已加入"
                 f"<span class=\"dot\">·</span>已加入 {len(players)}/{max_players}",
        body=body,
        foot=_foot([
            '<div><span class="k">加入</span>回复 <b>1</b></div>',
            '<div><span class="k">开始</span>房主回复 <b>2</b> 立即开始</div>',
            '<div class="dim"><span class="k">取消</span>发送 /结束游戏</div>',
            f'<div class="dim"><span class="k">超时</span>{timeout} 秒后自动开始</div>',
        ]),
    )


def minigame_cover_pick_html(*, timeout: int = 90, owner_name: str = "") -> str:
    """封面猜猜领域选择卡：单人游戏，电影 / 电视剧 / 动漫。"""
    items = [
        ("movie", "电影", "最新电影海报", "1"),
        ("tv", "电视剧", "热播剧集海报", "2"),
        ("anime", "动漫", "新番 / 动画海报", "3"),
    ]
    cards = []
    for icon, name, desc, key in items:
        cards.append(
            f'<div class="mg-type">'
            f'<div class="mg-type-top">{_svg(icon, 18, "currentColor")}{escape(name)}</div>'
            f'<div class="mg-type-desc">{escape(desc)}</div>'
            f'<div class="mg-type-key"><span class="mg-key">{key}</span> 选这一类</div>'
            f'</div>')
    body = f'    <div class="mg-types">{"".join(cards)}</div>'
    sub = "单人游戏 · 仅发起者可作答 · 题目来自片库最新更新"
    if owner_name:
        sub = (f"单人游戏 · 发起者 {escape(_clip(owner_name, 12))} 可作答"
               f"<span class=\"dot\">·</span>题目来自片库最新更新")
    return _page_shell(
        kind="封面猜猜",
        icon_html=_svg("image", 15, "currentColor"),
        page_ind="选择题库",
        title='<span class="hl">你想猜哪一类？</span>',
        subtitle=sub,
        body=body,
        foot=_foot([
            '<div><span class="k">选择</span>回复 <b>1</b> 电影 / <b>2</b> 电视剧 / <b>3</b> 动漫；回复 <b>0</b> 关闭</div>',
            f'<div class="dim"><span class="k">超时</span>{timeout} 秒内未选择自动关闭</div>',
        ]),
    )


def minigame_cover_question_html(*, question: dict, cover_b64: str,
                                 round_no: int, total: int, timeout: int,
                                 kind_label: str = "", solo: bool = True) -> str:
    """封面猜猜题目卡：马赛克封面 + 四个选项，整页出图。"""
    question = question or {}
    options = question.get("options") or []
    hint = question.get("hint") or "影视"
    opts = []
    for i, o in enumerate(options):
        opts.append(
            f'<div class="mg-opt"><span class="l">{"ABCD"[i]}</span>'
            f'<span class="t">{escape(o.get("title") or "?")}</span></div>')
    body = f"""    <div class="mg-cover-wrap">
      <div class="mg-cover"><img src="data:image/jpeg;base64,{cover_b64}" alt="cover"></div>
      <div class="mg-cover-side">
        <div class="mg-hint">提示：{escape(hint)}</div>
        <div class="mg-opts">{"".join(opts)}</div>
      </div>
    </div>"""
    bits = []
    if solo:
        bits.append("单人")
    if kind_label:
        bits.append(escape(kind_label))
    bits.append(f"第 {round_no}/{total} 题")
    sub = '<span class="dot">·</span>'.join(bits)
    return _page_shell(
        kind="封面猜猜",
        icon_html=_svg("image", 15, "currentColor"),
        page_ind=f"第 {round_no} / {total} 题",
        title='<span class="hl">猜猜这是哪部作品？</span>',
        subtitle=sub,
        body=body,
        foot=_foot([
            '<div><span class="k">作答</span>回复 <b>A / B / C / D</b> 选择</div>',
            f'<div class="dim"><span class="k">限时</span>{timeout} 秒内作答，答错直接下一题</div>',
        ]),
    )


def minigame_result_card_html(*, title: str, subtitle: str = "",
                              rows: list | None = None,
                              foot_lines: list | None = None,
                              page_ind: str = "本局结算") -> str:
    """小游戏结算卡片。

    rows: [{n, title, right?, meta?}]，right/meta 由调用方保证是安全 HTML
    （用 escape() 处理玩家昵称后再拼 chip）。
    """
    rows = rows or []
    if not rows:
        rows = [{"n": "-", "title": "本局无人参与", "meta": ""}]
    body = '<ol class="rows">\n' + _rows(rows) + '\n    </ol>'
    return _page_shell(
        kind="游戏结算",
        icon_html=_svg("gamepad", 15, "currentColor"),
        page_ind=page_ind,
        title=f'<span class="hl">{escape(_clip(title or "小游戏", 20))}</span>',
        subtitle=escape(subtitle or ""),
        body=body,
        foot=_foot(foot_lines or []),
    )


def points_card_html(*, name: str = "", uid: str = "", balance: int = 0,
                     streak: int = 0, last_checkin: str = "",
                     total_earned: int = 0, total_spent: int = 0,
                     costs: dict | None = None, labels: dict | None = None,
                     enabled: bool = True, today: str = "",
                     today_checked: bool = False,
                     date_label: str = "") -> str:
    """积分卡：余额 + 签到状态 + 累计 + 搜索消耗，一屏看完。"""
    labels = labels or {}
    costs = costs or {}
    display = _clip(name or uid or "我的积分", 14)

    if not enabled:
        status_cls, status_txt = "off-system", "积分系统未开启"
    elif today_checked:
        status_cls, status_txt = "on", "今日已签到"
    else:
        status_cls, status_txt = "off", "今日未签到"

    subtitle = "跨群聊 / 私聊统一累计"
    if last_checkin:
        subtitle += f'<span class="dot">·</span>最近签到 {escape(str(last_checkin))}'

    cells = [
        ("连续签到", f'{int(streak)}<small>天</small>'),
        ("最近签到", f'<span class="date">{escape(str(last_checkin))}</span>'
                     if last_checkin else '<span class="date">从未签到</span>'),
        ("累计获得", f'{int(total_earned)}<small>积分</small>'),
        ("累计消耗", f'{int(total_spent)}<small>积分</small>'),
    ]
    grid = "\n".join(
        f'      <div class="p-cell"><div class="k">{k}</div>'
        f'<div class="v">{v}</div></div>' for k, v in cells)

    cost_html = ""
    if costs:
        chips = "".join(
            f'<span class="p-cost">{escape(labels.get(k, k))} <b>{int(v)}</b><i>积分</i></span>'
            for k, v in costs.items())
        cost_html = (f'    <div class="p-sec">获取资源消耗</div>\n'
                     f'    <div class="p-costs">{chips}</div>\n')

    body = f"""    <div class="p-hero">
      <div>
        <div class="p-label">当前积分</div>
        <div class="p-balance">{int(balance)}<small>积分</small></div>
      </div>
      <div class="p-status {status_cls}">{status_txt}</div>
    </div>
    <div class="p-grid">
{grid}
    </div>
{cost_html}"""

    lines = []
    if enabled:
        lines.append('<div><span class="k">签到</span>发送 <b>/签到</b> 领取每日积分</div>')
        lines.append('<div><span class="k">榜单</span><b>/积分排行</b> 查看前 10 名</div>')
    else:
        lines.append('<div class="note"><span class="k">状态</span>'
                     '积分系统未开启，以上为历史数据</div>')

    return _page_shell(
        kind="积分与签到",
        icon_html=_svg("star", 15, "currentColor"),
        page_ind=date_label or today,
        title=f'<span class="hl">{escape(display)}</span>',
        subtitle=subtitle,
        body=body,
        foot=_foot(lines),
    )


def _page_bounds(total: int, page: int, page_size: int):
    ps = max(1, int(page_size or 8))
    pages = max(1, (total + ps - 1) // ps)
    p = max(0, min(int(page or 0), pages - 1))
    st = p * ps
    return p, pages, st, min(st + ps, total), ps


def _search_foot(*, count: int, page: int, pages: int, timeout: int,
                 note: str = "") -> str:
    lines = [f'<div><span class="k">选择</span>回复数字 <b>1–{max(1, count)}</b>；'
             f'回复 <b>0</b> 取消</div>']
    if pages > 1:
        lines.append('<div><span class="k">翻页</span>「下一页」/「上一页」/「跳 3」'
                     f'<span class="dim"> · {timeout} 秒无操作自动结束</span></div>')
    else:
        lines.append(f'<div class="dim"><span class="k">超时</span>'
                     f'{timeout} 秒无操作自动结束</div>')
    note = _clean_note(note)
    if note:
        lines.append(f'<div class="note"><span class="k">积分</span>{escape(note)}</div>')
    return _foot(lines)


def _search_card(*, kind: str, icon: str, keyword: str, total: int,
                 page: int, page_size: int, items: str, unit: str,
                 timeout: int = 120, note: str = "") -> str:
    """游戏 / 软件 / 影视 / 短剧搜索列表的通用卡片。"""
    p, pages, st, ed, ps = _page_bounds(total, page, page_size)
    subtitle = (f'共 <b>{total}</b> 个{unit}'
                f'<span class="dot">·</span>本页 {ed - st} 个')
    if pages > 1:
        subtitle += f'<span class="dot">·</span>第 {p + 1} / {pages} 页'
    title = f'<span class="hl">{escape(_clip(keyword or "搜索结果", 16))}</span>'
    return _page_shell(
        kind=kind,
        icon_html=_svg(icon, 15, "currentColor"),
        page_ind=_page_text(p, pages),
        title=title,
        subtitle=subtitle,
        body='<ol class="rows">\n' + items + '\n    </ol>',
        foot=_search_foot(count=ed - st, page=p, pages=pages,
                          timeout=timeout, note=note),
    )


def _meta(*parts) -> str:
    vals = [escape(_strip_emoji(str(x))) for x in parts if x]
    return '<span class="dot">·</span>'.join(vals) or '<span class="dim">查看详情</span>'


def _cover_of(item: dict, covers: dict | None) -> str:
    """从预下载的封面映射里取 base64；键优先用 cover URL，其次 id/url。"""
    if not covers or not isinstance(item, dict):
        return ""
    for key in (item.get("cover"), item.get("id"), item.get("url")):
        if key and key in covers:
            return covers[key]
    return ""


def _type_icon(kind: str, category: str = "", title: str = "") -> str:
    """按资源类型/分类选 56×56 小图标（不请求站点图片）。"""
    cat = str(category or "")
    name = str(title or "")
    if kind == "software":
        # 分类优先，避免标题里的 "WPS/Office" 把所有条目的图标都盖成文档
        if any(k in cat for k in ("办公", "学习")):
            return "book"
        if any(k in cat for k in ("影音", "视频", "剪辑", "音乐", "播放")):
            return "movie"
        if any(k in cat for k in ("安卓", "手机", "Android")):
            return "apps"
        if any(k in cat for k in ("会员", "活动", "福利", "领取")):
            return "star"
        if any(k in cat for k in ("游戏", "辅助", "修改器")):
            return "gamepad"
        text = f"{cat} {name}"
        if any(k in text for k in ("办公", "学习", "Office", "WPS", "文档")):
            return "book"
        if any(k in text for k in ("影音", "视频", "剪辑", "音乐", "播放")):
            return "movie"
        if any(k in text for k in ("安卓", "Android", "手机")):
            return "apps"
        if any(k in text for k in ("会员", "活动", "福利", "领取")):
            return "star"
        return "package"
    if kind == "game":
        text = f"{cat} {name}"
        if any(k in text for k in ("模拟", "经营", "策略")):
            return "apps"
        if any(k in text for k in ("体育", "竞速", "赛车")):
            return "play"
        return "gamepad"
    return "apps"


def game_card_html(ses: dict, *, timeout: int = 120, note: str = "",
                   covers: dict | None = None) -> str:
    """游戏搜索结果卡片：封面 + 序号 + 标题 + 类型/更新日期。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知游戏", 56),
                      "meta": _meta(x.get("type"), x.get("date")),
                      "tile": True, "cover": _cover_of(x, covers), "square": True,
                      "icon": _type_icon("game", x.get("type"), x.get("title"))})
    return _search_card(kind="游戏搜索", icon="gamepad", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="游戏", timeout=timeout, note=note)


def software_card_html(ses: dict, *, timeout: int = 120, note: str = "",
                       covers: dict | None = None) -> str:
    """软件搜索结果卡片：渐变封面 + 序号 + 标题 + 更新时间。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知资源", 56),
                      "meta": _meta(x.get("category"), x.get("update_time") or x.get("date")),
                      "tile": True, "cover": "",
                      "icon": _type_icon("software", x.get("category"), x.get("title"))})
    return _search_card(kind="软件搜索", icon="package", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="资源", timeout=timeout, note=note)


def movie_card_html(ses: dict, *, timeout: int = 120, note: str = "",
                    covers: dict | None = None) -> str:
    """影视搜索（a123tv）卡片：封面 + 序号 + 片名 + 类别/年份。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知影视", 56),
                      "meta": _meta(x.get("category"), x.get("year")),
                      "tile": True, "icon": "movie", "cover": _cover_of(x, covers)})
    return _search_card(kind="影视搜索", icon="movie", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="影视", timeout=timeout, note=note)


def movie_detail_card_html(detail: dict, *, cover_b64: str = "",
                           screenshots: list | None = None,
                           source_name: str = "暮黎影视",
                           link_hint: str = "播放 / 下载链接已单独发送") -> str:
    """影视详情卡：封面 + 简介 + 导演/主演 + 年份/类型/地区 + 剧照。"""
    detail = detail or {}
    screenshots = screenshots or []
    name = detail.get("name") or "未知影视"
    year = str(detail.get("year") or "").strip()
    status = _strip_emoji(str(detail.get("status") or "")).strip()
    score = _strip_emoji(str(detail.get("score_db") or detail.get("score") or "")).strip()
    leixing = detail.get("leixing") or []
    diqu = detail.get("diqu") or []
    if isinstance(leixing, str):
        leixing = [x.strip() for x in re.split(r"[,，/]", leixing) if x.strip()]
    if isinstance(diqu, str):
        diqu = [x.strip() for x in re.split(r"[,，/]", diqu) if x.strip()]
    daoyan = detail.get("daoyan") or []
    zhuyan = detail.get("zhuyan") or []
    if isinstance(daoyan, str):
        daoyan = [x.strip() for x in re.split(r"[,，/]", daoyan) if x.strip()]
    if isinstance(zhuyan, str):
        zhuyan = [x.strip() for x in re.split(r"[,，/]", zhuyan) if x.strip()]
    desc = str(detail.get("desc") or "").strip() or "暂无简介"

    tags = []
    if year:
        tags.append(f'<span class="md-tag">{_svg("event", 12, "currentColor")}'
                    f'{escape(year)}</span>')
    for x in leixing[:3]:
        tags.append(f'<span class="md-tag">{_svg("apps", 12, "currentColor")}'
                    f'{escape(_clip(str(x), 12))}</span>')
    for x in diqu[:2]:
        tags.append(f'<span class="md-tag">{_svg("location", 12, "currentColor")}'
                    f'{escape(_clip(str(x), 10))}</span>')
    if score:
        tags.append(f'<span class="md-tag score">{_svg("star", 12, "currentColor")} '
                    f'{escape(score)}</span>')
    if status:
        tags.append(f'<span class="md-tag">{_svg("clock", 12, "currentColor")}'
                    f'{escape(_clip(status, 14))}</span>')

    if cover_b64:
        cover_html = (f'<div class="md-cover"><img src="data:image/jpeg;base64,'
                      f'{cover_b64}" alt="cover"></div>')
    else:
        ph = escape(_clip(name, 1) or "影")
        cover_html = f'<div class="md-cover"><div class="ph">{ph}</div></div>'

    credit_lines = []
    if daoyan:
        credit_lines.append('<div><span class="k">' + _svg("movie", 13, "currentColor")
                            + '导演</span>'
                            + escape("、".join(str(x) for x in daoyan[:4])) + '</div>')
    if zhuyan:
        credit_lines.append('<div><span class="k">' + _svg("users", 13, "currentColor")
                            + '主演</span>'
                            + escape("、".join(str(x) for x in zhuyan[:6])) + '</div>')
    credits = ('<div class="md-credits">' + "".join(credit_lines) + '</div>'
               if credit_lines else "")

    tags_html = (f'<div class="md-tags">{"".join(tags)}</div>' if tags else "")
    body = f"""    <div class="md-hero">
      {cover_html}
      <div class="md-main">
        {tags_html}
        {credits}
        <div class="md-desc">{escape(_clip(desc, 320))}</div>
      </div>
    </div>"""
    if screenshots:
        valid = [b64 for b64 in screenshots[:3] if b64]
        shots = "".join(
            f'<div class="md-shot"><img src="data:image/jpeg;base64,{b64}" alt="shot"></div>'
            for b64 in valid)
        if shots:
            grid_cls = " one" if len(valid) == 1 else (" two" if len(valid) == 2 else "")
            body += (f'\n    <div class="md-shots">'
                     f'<div class="md-shots-title">{_svg("image", 14, "currentColor")}'
                     f' 剧照</div><div class="md-shot-grid{grid_cls}">{shots}</div></div>')
    foot = [f'<div><span class="k">链接</span>{escape(link_hint)}</div>',
            f'<div class="dim"><span class="k">来源</span>{escape(source_name)}</div>']
    return _page_shell(
        kind="影视详情",
        icon_html=_svg("movie", 15, "currentColor"),
        page_ind="详情",
        title=f'<span class="hl">{escape(_clip(name, 26))}</span>',
        subtitle="封面 / 简介 / 演职员 / 剧照",
        body=body,
        foot=_foot(foot),
    )


def _detail_tag(icon: str, text, cls: str = "") -> str:
    if text in (None, ""):
        return ""
    c = f" {cls}" if cls else ""
    return (f'<span class="md-tag{c}">{_svg(icon, 12, "currentColor")}'
            f'{escape(str(text))}</span>')


def _detail_shots(screenshots: list | None, title: str = "截图") -> str:
    valid = [b64 for b64 in (screenshots or [])[:3] if b64]
    if not valid:
        return ""
    shots = "".join(
        f'<div class="md-shot"><img src="data:image/jpeg;base64,{b64}" alt="shot"></div>'
        for b64 in valid)
    if len(valid) >= 3:
        grid_cls = " hero"       # 一张大图在上，两张并排在下
    elif len(valid) == 1:
        grid_cls = " one"
    else:
        grid_cls = " two"
    return (f'\n    <div class="md-shots">'
            f'<div class="md-shots-title">{_svg("image", 14, "currentColor")}'
            f' {escape(title)}</div>'
            f'<div class="md-shot-grid{grid_cls}">{shots}</div></div>')


def _detail_head(icon: str, cover_b64: str, tags: list,
                 subtitle: str = "") -> str:
    """详情卡头部：小尺寸封面图标 + 标签，避免大图占掉半张卡。"""
    if cover_b64:
        icon_html = (f'<span class="dt-icon cover"><img src="data:image/jpeg;base64,'
                     f'{cover_b64}" alt="cover"></span>')
    else:
        icon_html = f'<span class="dt-icon">{_svg(icon, 26, "currentColor")}</span>'
    sub = f'<div class="dt-head-sub">{escape(subtitle)}</div>' if subtitle else ""
    return (f'    <div class="dt-head">\n      {icon_html}\n'
            f'      <div class="dt-head-main">\n'
            f'        <div class="md-tags">{"".join(tags)}</div>\n'
            f'        {sub}\n      </div>\n    </div>')


def game_detail_card_html(detail: dict, *, cover_b64: str = "",
                          screenshots: list | None = None,
                          meta: dict | None = None,
                          source_name: str = "暮黎游戏",
                          link_hint: str = "选好网盘后会单独发送下载链接") -> str:
    """游戏详情卡：小封面图标 + 简介 + 二段式截图 + 网盘数量。"""
    detail = detail or {}
    meta = meta or {}
    name = detail.get("name") or meta.get("title") or "未知游戏"
    desc = str(detail.get("desc") or "").strip() or "暂无简介"
    links = detail.get("download_links") or []

    tags = [_detail_tag("gamepad", "游戏")]
    if meta.get("type"):
        tags.append(_detail_tag("apps", _clip(str(meta["type"]), 12)))
    if meta.get("date"):
        tags.append(_detail_tag("event", meta["date"]))
    if links:
        tags.append(_detail_tag("download", f"{len(links)} 个网盘", "score"))

    body = _detail_head("gamepad", cover_b64, tags)
    body += (f'\n    <div class="md-desc" style="margin-top:14px">'
             f'{escape(_clip(desc, 420))}</div>')
    body += _detail_shots(screenshots, "游戏截图")
    foot = [f'<div><span class="k">链接</span>{escape(link_hint)}</div>',
            f'<div class="dim"><span class="k">来源</span>{escape(source_name)}</div>']
    return _page_shell(
        kind="游戏详情",
        icon_html=_svg("gamepad", 15, "currentColor"),
        page_ind="详情",
        title=f'<span class="hl">{escape(_clip(name, 26))}</span>',
        subtitle="简介 / 截图 / 网盘选择",
        body=body,
        foot=_foot(foot),
    )


def software_detail_card_html(detail: dict, *, cover_b64: str = "",
                              screenshots: list | None = None,
                              meta: dict | None = None,
                              source_name: str = "暮黎软件",
                              link_hint: str = "选好网盘后会单独发送下载链接") -> str:
    """软件详情卡：小封面图标 + 简介 + 二段式截图 + 网盘数量。"""
    detail = detail or {}
    meta = meta or {}
    name = detail.get("name") or meta.get("title") or "未知资源"
    desc = str(detail.get("desc") or "").strip() or "暂无简介"
    links = detail.get("download_links") or []

    tags = [_detail_tag("package", "软件资源")]
    if meta.get("category"):
        tags.append(_detail_tag("apps", _clip(str(meta["category"]), 12)))
    if meta.get("date"):
        tags.append(_detail_tag("event", meta["date"]))
    if links:
        tags.append(_detail_tag("download", f"{len(links)} 个网盘", "score"))

    body = _detail_head("package", cover_b64, tags)
    body += (f'\n    <div class="md-desc" style="margin-top:14px">'
             f'{escape(_clip(desc, 420))}</div>')
    body += _detail_shots(screenshots, "资源截图")
    foot = [f'<div><span class="k">链接</span>{escape(link_hint)}</div>',
            f'<div class="dim"><span class="k">来源</span>{escape(source_name)}</div>']
    return _page_shell(
        kind="软件详情",
        icon_html=_svg("package", 15, "currentColor"),
        page_ind="详情",
        title=f'<span class="hl">{escape(_clip(name, 26))}</span>',
        subtitle="简介 / 截图 / 网盘选择",
        body=body,
        foot=_foot(foot),
    )


def movie_new_card_html(results: list, keyword: str = "", page: int = 0,
                        page_size: int = 8, *, timeout: int = 120,
                        note: str = "", covers: dict | None = None) -> str:
    """影视搜索（片库 / pdy0）卡片：封面 + 序号 + 片名 + 类型/年份/评分。"""
    r = results or []
    p, pages, st, ed, ps = _page_bounds(len(r), page, page_size)
    items = []
    for i, x in enumerate(r[st:ed], 1):
        bits = [x.get("type"), x.get("year")]
        if x.get("score"):
            bits.append(f'{x.get("score")} 分')
        items.append({"n": i, "title": _clip(x.get("title") or "未知影视", 56),
                      "meta": _meta(*bits), "tile": True, "icon": "movie",
                      "cover": _cover_of(x, covers)})
    return _search_card(kind="影视搜索", icon="movie", keyword=keyword,
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="影视", timeout=timeout, note=note)


def drama_card_html(ses: dict, *, timeout: int = 120, note: str = "",
                    covers: dict | None = None) -> str:
    """短剧搜索结果卡片：渐变封面 + 序号 + 剧名 + 分类/日期。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知短剧", 56),
                      "meta": _meta(x.get("category") or "短剧", x.get("date")),
                      "tile": True, "icon": "tv", "cover": _cover_of(x, covers)})
    return _search_card(kind="短剧搜索", icon="movie", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="短剧", timeout=timeout, note=note)


def _initial(text: str) -> str:
    """头像加载失败时的占位字：取名字第一个字符。"""
    chars = [c for c in _strip_emoji(text) if not c.isspace()]
    return chars[0] if chars else "?"


def points_rank_html(*, rows: list | None = None, total: int = 0,
                     me_key: str = "", me_rank: int = 0, me_points: int = 0,
                     me_name: str = "", date_label: str = "") -> str:
    """积分排行榜卡片：名次 + 头像 + 昵称 + 积分，当前用户高亮。"""
    rows = rows or []
    items = []
    for r in rows:
        rank = int(r.get("rank") or 0)
        no_cls = "gold" if rank == 1 else ("top" if rank <= 3 else "")
        raw_name = str(r.get("name") or "匿名用户")
        name = escape(_clip(raw_name, 18))
        if r.get("me"):
            name += '<span class="me-chip">你</span>'
        avatar = r.get("avatar") or ""
        if avatar:
            av = f'<span class="rk-av"><img src="{avatar}" alt=""></span>'
        else:
            av = (f'<span class="rk-av"><span class="ph">'
                  f'{escape(_initial(raw_name))}</span></span>')
        streak = int(r.get("streak") or 0)
        sub = (f'<span class="rk-sub">连续签到 {streak} 天</span>'
               if streak > 0 else '<span class="rk-sub off">暂未连续签到</span>')
        items.append(f"""      <li class="rk-row">
        <span class="rk-no {no_cls}">{rank}</span>
        {av}
        <span class="rk-main"><span class="rk-name">{name}</span>{sub}</span>
        <span class="rk-pts">{int(r.get('points') or 0)}<small>积分</small></span>
      </li>""")

    body = '    <ol class="rk">\n' + "\n".join(items) + "\n    </ol>"

    lines = []
    if me_rank and me_rank > len(rows):
        lines.append(f'<div><span class="k">我的排名</span>第 <b>{me_rank}</b> 名 · '
                     f'<b>{int(me_points)}</b> 积分</div>')
    lines.append('<div><span class="k">提示</span>发送 <b>/签到</b> 领取积分 · '
                 '<b>/积分</b> 查余额</div>')

    subtitle = (f'共 <b>{int(total) if total else len(rows)}</b> 位用户参与'
                f'<span class="dot">·</span>按积分降序'
                f'<span class="dot">·</span>前 {len(rows)} 名')
    return _page_shell(
        kind="积分排行",
        icon_html=_svg("star", 15, "currentColor"),
        page_ind=date_label,
        title='<span class="hl">积分排行榜</span>',
        subtitle=subtitle,
        body=body,
        foot=_foot(lines),
    )


# ==================== 渲染线程（复用浏览器）====================

class _CardRenderer:
    """一个常驻线程负责所有卡片截图，线程内复用 browser / page。"""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._dead = False
        self._thread = threading.Thread(target=self._loop, name="muli-list-card",
                                        daemon=True)
        self._thread.start()

    @property
    def dead(self) -> bool:
        return self._dead

    def submit(self, html_text: str, width: int, scale: int,
               timeout: float = _RENDER_TIMEOUT):
        if self._dead:
            return None
        box: dict = {}
        done = threading.Event()
        self._jobs.put((html_text, width, scale, done, box))
        if not done.wait(timeout):
            logger.warning("[列表卡片] 渲染超时，回退文本")
            return None
        return box.get("data")

    # ---- 线程主体 ----
    @staticmethod
    def _launch(p):
        return p.chromium.launch(headless=True, args=_BROWSER_ARGS)

    def _shoot(self, page, html_text: str, width: int):
        # 页面已预加载 shell.html（含 @font-face + 全部样式），这里只换 body，
        # 避免每次重新解析 4.5MB 字体导致 200ms+ 的额外耗时。
        body = html_text
        if "<body>" in body and "</body>" in body:
            body = body.split("<body>", 1)[1].rsplit("</body>", 1)[0]
        page.evaluate("(h) => { document.body.innerHTML = h; }", body)
        # 等内嵌封面/截图解码完成（最多 3 秒，避免坏图卡死整张卡片）
        try:
            page.evaluate(
                "() => Promise.race(["
                " Promise.all(Array.from(document.images).map(i => i.complete ? true :"
                "   new Promise(r => { i.onload = i.onerror = () => r(true); }))),"
                " new Promise(r => setTimeout(() => r(true), 3000))])")
        except Exception:
            pass
        # 等字体就绪 + 两帧渲染，比固定 sleep 快且稳
        page.evaluate(
            "() => (document.fonts && document.fonts.ready)"
            " ? document.fonts.ready.then(() => true) : true")
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame("
            "() => requestAnimationFrame(() => r(true))))")
        # 内容比视口矮时（如积分卡），full_page 会按视口高度出图，底部留一大片空白。
        # 这里按 .canvas 实际高度裁切，图多高就出多高。
        try:
            height = page.evaluate(
                "() => { const el = document.querySelector('.canvas');"
                " const h = el ? el.getBoundingClientRect().height"
                " : document.documentElement.scrollHeight;"
                " return Math.max(120, Math.ceil(h)); }")
        except Exception:
            height = 0
        if height:
            return page.screenshot(
                full_page=True, type="jpeg", quality=_JPEG_QUALITY,
                animations="disabled",
                clip={"x": 0, "y": 0, "width": width, "height": height})
        return page.screenshot(full_page=True, type="jpeg",
                               quality=_JPEG_QUALITY, animations="disabled")

    def _loop(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[列表卡片] Playwright 不可用，长列表继续发文本：{e}")
            self._dead = True
            self._drain()
            return

        try:
            with sync_playwright() as p:
                browser = self._launch(p)
                page = None
                page_key = None
                shell_ok = False
                while True:
                    try:
                        job = self._jobs.get(timeout=_IDLE_SHUTDOWN)
                    except queue.Empty:
                        logger.debug("[列表卡片] 空闲超时，关闭浏览器释放内存")
                        break
                    if job is None:
                        break
                    html_text, width, scale, done, box = job
                    data = None
                    for attempt in (0, 1):
                        sc = scale if attempt == 0 else 1  # 超高页面降级 1x
                        try:
                            if browser is None:
                                browser = self._launch(p)
                            key = (width, sc)
                            if page is None or page_key != key:
                                if page is not None:
                                    try:
                                        page.close()
                                    except Exception:
                                        pass
                                page = browser.new_page(
                                    viewport={"width": width, "height": 900},
                                    device_scale_factor=sc)
                                page.set_default_timeout(15000)
                                try:
                                    page.emulate_media(color_scheme="light",
                                                       reduced_motion="reduce")
                                except Exception:
                                    pass
                                page_key = key
                                shell_ok = False
                            if page is not None and not shell_ok:
                                page.goto(_shell_uri(), wait_until="load")
                                shell_ok = True
                            data = self._shoot(page, html_text, width)
                            if data:
                                break
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"[列表卡片] 截图失败(scale={sc}, "
                                           f"attempt={attempt}): {e}")
                            try:
                                if browser is not None:
                                    browser.close()
                            except Exception:
                                pass
                            browser, page, page_key = None, None, None
                            shell_ok = False
                    box["data"] = data
                    done.set()
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.error(f"[列表卡片] 渲染线程异常退出：{e}")
        finally:
            # 线程退出（空闲回收/异常）后标记不可用，下次调用自动重新拉起
            self._dead = True
            self._drain()

    def _drain(self):
        """线程退出前把排队中的任务全部标记失败，避免调用方一直等。"""
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            if job is None:
                continue
            _, _, _, done, box = job
            box["data"] = None
            done.set()


_renderer: _CardRenderer | None = None
_renderer_lock = threading.Lock()
_render_dir: str | None = None
_render_dir_lock = threading.Lock()
_cache: "OrderedDict[str, tuple[bytes, float]]" = OrderedDict()
_cache_lock = threading.Lock()


def _render_dir_path() -> str:
    """渲染用的临时目录：放 shell.html 和字体文件（只准备一次）。"""
    global _render_dir
    if _render_dir is None:
        with _render_dir_lock:
            if _render_dir is None:
                d = tempfile.mkdtemp(prefix="muli_card_")
                for name in _FONT_FILES:
                    src = os.path.join(_FONT_DIR, name)
                    if os.path.exists(src):
                        try:
                            shutil.copyfile(src, os.path.join(d, name))
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"[列表卡片] 字体复制失败 {name}: {e}")
                _render_dir = d
    return _render_dir


def _shell_uri() -> str:
    """预加载页：样式和字体只解析一次，后续卡片只替换 body。"""
    path = os.path.join(_render_dir_path(), "shell.html")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                    f'<style>{_CSS}</style></head><body></body></html>')
    return pathlib.Path(path).as_uri()


def _get_renderer() -> _CardRenderer:
    global _renderer
    if _renderer is None or _renderer.dead:
        with _renderer_lock:
            if _renderer is None or _renderer.dead:
                _renderer = _CardRenderer()
    return _renderer


def _cache_get(key: str):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        data, ts = hit
        if now - ts > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return data


def _cache_put(key: str, data: bytes):
    with _cache_lock:
        _cache[key] = (data, time.time())
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def render_list_card(html_text: str, *, width: int = CARD_WIDTH,
                     scale: int = DEFAULT_SCALE) -> bytes | None:
    """把卡片 HTML 渲染成 JPEG 字节；失败返回 None（调用方回退文本）。"""
    if not html_text:
        return None
    key = hashlib.sha1(f"{width}|{scale}|{html_text}".encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if cached:
        return cached
    data = _get_renderer().submit(html_text, width, scale)
    if data:
        _cache_put(key, data)
    return data


def prewarm() -> None:
    """后台预热：提前拉起浏览器并跑一遍中文排版，首次搜索不用再等冷启动。"""
    def _run():
        try:
            _get_renderer().submit(
                "<html><body><div class='canvas'><div class='sheet'>"
                "<div class='title'>暮黎资源</div>"
                "<div class='subtitle'>积分排行 · 小说搜索 · 网盘资源 · 共 22 条结果</div>"
                "</div></div></body></html>",
                CARD_WIDTH, DEFAULT_SCALE, timeout=40)
            logger.info("[列表卡片] 渲染器预热完成（含字体）")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[列表卡片] 预热失败（不影响使用）：{e}")

    threading.Thread(target=_run, name="muli-list-card-warmup", daemon=True).start()

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
.row{display:flex;gap:14px;padding:15px 0}
.row+.row{border-top:1px solid #f2f2f2}
.num{flex:0 0 auto;width:30px;height:30px;margin-top:1px;border-radius:10px;
  border:1px solid #e6e6e6;background:#fafafa;color:#1a1a1a;
  font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center;
  font-variant-numeric:tabular-nums}
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


def _rows(items: list) -> str:
    out = []
    for it in items:
        out.append(f"""      <li class="row">
        <span class="num">{it['n']}</span>
        <div class="row-main">
          <div class="row-line">
            <div class="row-title">{escape(it['title'])}</div>{it.get('right', '')}
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
        cost_html = (f'    <div class="p-sec">搜索消耗</div>\n'
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


def game_card_html(ses: dict, *, timeout: int = 120, note: str = "") -> str:
    """游戏搜索结果卡片：序号 + 标题 + 类型/更新日期。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知游戏", 56),
                      "meta": _meta(x.get("type"), x.get("date"))})
    return _search_card(kind="游戏搜索", icon="gamepad", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="游戏", timeout=timeout, note=note)


def software_card_html(ses: dict, *, timeout: int = 120, note: str = "") -> str:
    """软件搜索结果卡片：序号 + 标题 + 更新时间。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知资源", 56),
                      "meta": _meta(x.get("update_time") or x.get("date"))})
    return _search_card(kind="软件搜索", icon="package", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="资源", timeout=timeout, note=note)


def movie_card_html(ses: dict, *, timeout: int = 120, note: str = "") -> str:
    """影视搜索（a123tv）卡片：序号 + 片名 + 类别/年份。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知影视", 56),
                      "meta": _meta(x.get("category"), x.get("year"))})
    return _search_card(kind="影视搜索", icon="movie", keyword=ses.get("keyword", ""),
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="影视", timeout=timeout, note=note)


def movie_new_card_html(results: list, keyword: str = "", page: int = 0,
                        page_size: int = 8, *, timeout: int = 120,
                        note: str = "") -> str:
    """影视搜索（片库新站）卡片：序号 + 片名 + 类型/年份/评分。"""
    r = results or []
    p, pages, st, ed, ps = _page_bounds(len(r), page, page_size)
    items = []
    for i, x in enumerate(r[st:ed], 1):
        bits = [x.get("type"), x.get("year")]
        if x.get("score"):
            bits.append(f'{x.get("score")} 分')
        items.append({"n": i, "title": _clip(x.get("title") or "未知影视", 56),
                      "meta": _meta(*bits)})
    return _search_card(kind="影视搜索", icon="movie", keyword=keyword,
                        total=len(r), page=p, page_size=ps, items=_rows(items),
                        unit="影视", timeout=timeout, note=note)


def drama_card_html(ses: dict, *, timeout: int = 120, note: str = "") -> str:
    """短剧搜索结果卡片：序号 + 剧名 + 分类/日期。"""
    r = ses.get("results") or []
    p, pages, st, ed, ps = _page_bounds(len(r), ses.get("page", 0),
                                        ses.get("page_size", 8))
    items = []
    for i, x in enumerate(r[st:ed], 1):
        items.append({"n": i, "title": _clip(x.get("title") or "未知短剧", 56),
                      "meta": _meta(x.get("category") or "短剧", x.get("date"))})
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

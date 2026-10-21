# -*- coding: utf-8 -*-
"""游戏日报（XDGAME）相关函数。

每天自动抓取 xdgame.com 列表页，按 <time> 元素的时间关键词过滤「今天更新」的游戏，
取标题 / 简介 / 截图（不取下载链接），排版成卡通风格 HTML 后用 Playwright 渲染为图片发送。

对外接口：
    get_today_games(max_games=8, cookie="") -> dict
    build_cartoon_html(games, date_label) -> str
    render_html_to_png(html_text, font_path="", width=700, channel="", exe="") -> bytes|None
    gen_report_zip(games, html_str, ts) -> str|None
"""
import os
import re
import io
import base64
import random
import time
import datetime
import tempfile
import zipfile

import requests
from bs4 import BeautifulSoup
from PIL import Image

from .constants import GAME_BASE_URL, logger
from .brand import logo_img

# ==================== 常量 ====================
GAME_LIST_URL = GAME_BASE_URL + "/list/1/"
GAME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": GAME_BASE_URL + "/",
}

# 卡通配色（卡片边框 / 标题 / 角标循环使用）
_CARTOON_PALETTE = [
    "#ff7eb3", "#7c4dff", "#26c6da", "#ffa726", "#66bb6a",
    "#ef5350", "#5c6bc0", "#ec407a", "#29b6f6", "#ab47bc",
]

# 卡通图标（内联 SVG，避免服务器缺 emoji 字体导致图标不显示）
_ICONS = {
    "gamepad": '<svg class="ic" viewBox="0 0 48 32" width="40" height="28" fill="#ff8fb1">'
               '<rect x="2" y="8" width="44" height="20" rx="10"/>'
               '<circle cx="13" cy="18" r="3" fill="#fff"/><circle cx="19" cy="18" r="3" fill="#fff"/>'
               '<rect x="32" y="15" width="3" height="7" fill="#fff"/><rect x="30.5" y="18.5" width="6" height="3" fill="#fff"/></svg>',
    "star": '<svg class="ic" viewBox="0 0 24 24" width="14" height="14" fill="white">'
            '<path d="M12 2l3 6.3 6.9.9-5 4.9 1.2 6.9L12 18.8 5.9 21l1.2-6.9-5-4.9 6.9-.9z"/></svg>',
    "box": '<svg class="ic" viewBox="0 0 24 24" width="13" height="13" fill="white">'
           '<path d="M12 2l9 5v10l-9 5-9-5V7l9-5zm0 2.3L5 7.4v9.2l7 3.9 7-3.9V7.4L12 4.3z'
           'M12 12l-4-2.3v3.6l4 2.3 4-2.3v-3.6L12 12z"/></svg>',
    "camera": '<svg class="ic" viewBox="0 0 24 24" width="18" height="18" fill="#b0a8bd">'
              '<path d="M9 4l-1.5 2H4a2 2 0 00-2 2v9a2 2 0 002 2h16a2 2 0 002-2v-9a2 2 0 00-2-2h-3.5L15 4H9z'
              'm3 4.5a4.5 4.5 0 110 9 4.5 4.5 0 010-9z"/></svg>',
}


# ==================== 通用工具 ====================
def _get_html(url: str, retries: int = 3, timeout: int = 20):
    for i in range(retries):
        try:
            r = requests.get(url, headers=GAME_HEADERS, timeout=timeout)
            r.encoding = "utf-8"
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")
            if len(r.text) < 500:
                raise Exception("过短")
            return r.text
        except Exception as e:
            logger.debug(f"[游戏日报] 请求失败(第{i+1}次): {e}")
            if i < retries - 1:
                time.sleep(2)
    return None


def _fix_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return GAME_BASE_URL + url
    return GAME_BASE_URL + "/" + url


# ==================== 列表解析 ====================
def parse_game_list(html: str) -> list:
    """解析 xdgame 列表页，返回每个游戏的基础信息（不含详情页简介/截图）。"""
    soup = BeautifulSoup(html, "html.parser")
    lis = soup.select("div.fl.soft.list.force-grid > ul > li")
    games = []
    for li in lis:
        time_el = li.select_one("time.news") or li.select_one("time")
        time_text = time_el.get_text(strip=True) if time_el else ""

        tit = li.select_one("a.tit")
        title = tit.get_text(strip=True) if tit else ""
        href = tit.get("href", "") if tit else ""
        detail_url = _fix_url(href) if href else ""

        cover_img = li.select_one("a.grid-cover img") or li.select_one("a.img img")
        cover = ""
        if cover_img:
            cover = (cover_img.get("data-original") or cover_img.get("data-litpic")
                     or cover_img.get("src", ""))
        cover = _fix_url(cover)

        type_el = li.select_one("span.type")
        category = type_el.get_text(strip=True) if type_el else ""

        size_el = li.select_one("div.data span.size") or li.select_one("span.size")
        size = ""
        if size_el:
            size = size_el.get_text(strip=True).replace("fa fa-download size", "").strip()

        rank_el = li.select_one("div.data span.rank") or li.select_one("span.rank")
        rank = rank_el.get_text(strip=True) if rank_el else ""

        if title and detail_url:
            games.append({
                "title": title,
                "detail_url": detail_url,
                "time_text": time_text,
                "cover": cover,
                "category": category,
                "size": size,
                "rank": rank,
                "intro": "",
                "cover_b64": "",
                "shots_b64": [],
            })
    return games


def get_random_game_xdgame() -> dict | None:
    """从 xdgame 列表页随机取一款游戏，用于签到推荐（不抓详情）。"""
    html = _get_html(GAME_LIST_URL, retries=2, timeout=12)
    if not html:
        return None
    blocked = ("绅士", "黄油", "成人", "里番", "色情", "福利")
    games = [
        g for g in parse_game_list(html)
        if g.get("title") and len(g["title"]) <= 30
        and not any(k in (g.get("category") or "") or k in g["title"] for k in blocked)
    ]
    if not games:
        return None
    game = random.choice(games)
    desc = " · ".join(x for x in (game.get("category"), game.get("size")) if x)
    query = (game["title"].split("/")[0] or game["title"]).strip()
    return {"name": game["title"], "desc": desc or "xdgame 游戏", "query": query}


def _is_today(time_text: str) -> bool:
    """根据 <time> 元素的时间关键词判断是否为今天更新。

    支持：
    - 相对词：今天 / Today / 刚刚 / X分钟前 / X小时前
    - 绝对日期：YYYY-MM-DD / YYYY年MM月DD日 / MM-DD（视为今年）
    """
    if not time_text:
        return False
    t = time_text.strip()
    low = t.lower()
    if "今天" in t or "today" in low:
        return True
    # 相对时间：昨天 / 前天 / yesterday 不算；分钟前 / 小时前 / 刚刚 一定是今天
    if "昨天" in t or "前天" in t or "yesterday" in low:
        return False
    if "分钟前" in t or "小时前" in t or "刚刚" in t:
        return True
    today = datetime.date.today()
    # YYYY-MM-DD / YYYY年MM月DD日 / YYYY/MM/DD
    m = re.search(r"(\d{4})[-/年\.](\d{1,2})[-/月\.](\d{1,2})", t)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) == today
        except Exception:
            pass
    # MM-DD / M月D日（默认今年）
    m = re.search(r"(?<!\d)(\d{1,2})[-/月\.](\d{1,2})(?!\d)", t)
    if m:
        try:
            return datetime.date(today.year, int(m.group(1)), int(m.group(2))) == today
        except Exception:
            pass
    return False


# 图床熔断：同一 host 连续下载失败达到阈值后，跳过该 host 后续所有图片，
# 避免个别图床（如被墙/极慢的 CDN）拖垮整条日报。
_IMG_FAIL_THRESHOLD = 3


def _dl_and_b64(url: str, fail_tracker: dict = None) -> str:
    """下载图片并压缩为 base64 data URI，供 HTML 内联渲染（离线、避免防盗链）。失败返回空串。

    fail_tracker: 可选 {host: 连续失败次数} 字典，用于跨图片共享熔断状态。
    """
    if not url or not url.startswith("http"):
        return ""
    host = ""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
    except Exception:
        pass
    if fail_tracker is not None and host in fail_tracker and fail_tracker[host] >= _IMG_FAIL_THRESHOLD:
        logger.info(f"[游戏日报] 跳过图片（{host} 已连续失败 {fail_tracker[host]} 次，疑似被墙/超时）: {str(url)[:50]}")
        return ""
    try:
        r = requests.get(url, headers={**GAME_HEADERS, "Referer": GAME_BASE_URL + "/"}, timeout=10)
        if r.status_code != 200 or not r.content:
            raise ValueError(f"status={r.status_code}")
        img = Image.open(io.BytesIO(r.content))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            mask = img.split()[-1] if img.mode == "RGBA" else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w = img.width
        if w > 360:
            img = img.resize((360, int(img.height * 360 / w)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        b = base64.b64encode(buf.getvalue()).decode("ascii")
        if fail_tracker is not None and host:
            fail_tracker[host] = 0
        return f"data:image/jpeg;base64,{b}"
    except Exception as e:
        if fail_tracker is not None and host:
            fail_tracker[host] = fail_tracker.get(host, 0) + 1
        logger.debug(f"[游戏日报] 图片下载失败 {str(url)[:50]}: {e}")
        return ""


# ==================== 抓取今日游戏 ====================
def _has_meaningful_title(title: str) -> bool:
    """判断清洗后的标题是否含真实游戏名，排除只有空壳或纯元数据的脏数据。"""
    if not title or not title.strip():
        return False
    m = re.search(r'《([^》]*)》', title)
    name = m.group(1).strip() if m else re.split(r'[（(]', title)[0].strip()
    return bool(re.search(r'[^\s《》（）()|｜+\-—·.、,，:：]', name))


def get_today_games(max_games: int = 8, cookie: str = "", progress_cb=None) -> dict:
    """抓取今天更新的游戏（含简介 + 截图 base64）。

    progress_cb: 可选回调，用于在抓取过程中回报进度，签名 progress_cb(msg:str)。
    返回 {"success":bool,"games":[...],"error":""}
    - success=True 且 games=[] 表示今日暂无更新（error="今日暂无更新"）
    """
    res = {"success": False, "games": [], "error": ""}
    fail_tracker = {}
    def _prog(msg):
        logger.info(f"[游戏日报] {msg}")
        if callable(progress_cb):
            try: progress_cb(msg)
            except Exception: pass
    try:
        _prog("📄 正在获取新游列表...")
        html = _get_html(GAME_LIST_URL)
        if not html:
            res["error"] = "列表页获取失败"
            _prog("列表页获取失败")
            return res
        items = parse_game_list(html)
        today = [g for g in items if _is_today(g["time_text"]) and _has_meaningful_title(g.get("title", ""))]
        if not today:
            res["success"] = True
            res["error"] = "今日暂无更新"
            _prog("未找到今日更新的游戏")
            return res
        today = today[:max_games]
        total = len(today)
        _prog(f"📋 共找到 {total} 款今日新游，开始抓取封面/截图与简介...")
        # 延迟导入，避免循环依赖
        from .game import get_game_detail
        for idx, g in enumerate(today, 1):
            try:
                _prog(f"⏳ 抓取详情 ({idx}/{total})：{g.get('title','?')[:24]}")
                d = get_game_detail(g["detail_url"], cookie)
                g["intro"] = d.get("desc", "") or "暂无简介"
                shots = d.get("screenshots", [])[:2]
                if not g.get("cover") and d.get("cover"):
                    g["cover"] = d["cover"]
            except Exception as e:
                logger.warning(f"[游戏日报] 详情失败 [{g.get('title','?')[:30]}]: {e}")
                g["intro"] = "暂无简介"
                shots = []
            # 下载并内联图片
            g["cover_b64"] = _dl_and_b64(g.get("cover", ""), fail_tracker) if g.get("cover") else ""
            g["shots_b64"] = []
            for u in shots:
                b = _dl_and_b64(u, fail_tracker)
                if b:
                    g["shots_b64"].append(b)
            time.sleep(0.5)
        res["success"] = True
        res["games"] = today
        _prog(f"✅ 抓取完成，共 {total} 款（含封面 {sum(1 for g in today if g.get('cover_b64'))} 款）")
    except Exception as e:
        logger.error(f"[游戏日报] 抓取失败: {e}")
        res["error"] = str(e)[:200]
    return res


# ==================== 卡通风格 HTML ====================
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_cartoon_html(games: list, date_label: str, source_label: str = "XDGAME") -> str:
    """把今日游戏排版成卡通风格 HTML（图片已内联 base64，离线可渲染）。

    source_label 用于页脚「数据来源」，xdgame 源传 "XDGAME"，switch618 源传 "switch618"。
    """
    cards = []
    for i, g in enumerate(games):
        color = _CARTOON_PALETTE[i % len(_CARTOON_PALETTE)]
        cover = g.get("cover_b64") or ""
        cover_html = (
            f'<img class="cover" src="{cover}" alt="封面">'
            if cover else
            f'<div class="cover noimg" style="border-color:{color}">{_ICONS["gamepad"]}</div>'
        )
        # 简介：截断，避免图片过长
        intro = _esc(g.get("intro", "") or "暂无简介")
        if len(intro) > 320:
            intro = intro[:320] + "…"
        # 换行成 <p>
        intro_html = "".join(f"<p>{ln}</p>" for ln in intro.split("\n") if ln.strip()) or "<p>暂无简介</p>"

        chips = []
        if g.get("category"):
            chips.append(f'<span class="chip" style="background:{color}">{_esc(g["category"])}</span>')
        if g.get("size"):
            chips.append(f'<span class="chip gray">{_ICONS["box"]} {_esc(g["size"])}</span>')
        if g.get("rank"):
            chips.append(f'<span class="chip gray">{_ICONS["star"]} {_esc(g["rank"])}</span>')
        chips_html = "".join(chips)

        shots = g.get("shots_b64", []) or []
        if shots:
            shots_html = '<div class="shots">'
            for s in shots:
                shots_html += f'<div class="shot"><img src="{s}" alt="截图"></div>'
            shots_html += "</div>"
        else:
            shots_html = '<div class="noshots">{camera} 暂无截图</div>'.format(camera=_ICONS["camera"])

        badge = '<div class="badge" style="background:{c}">NEW!</div>'.format(c=color)

        cards.append(f'''
<div class="card" style="border-color:{color}">
  {badge}
  <div class="card-head">
    <div class="cover-wrap">{cover_html}</div>
    <div class="head-right">
      <div class="title">{_esc(g.get('title',''))}</div>
      <div class="chips">{chips_html}</div>
    </div>
  </div>
  <div class="bubble">{intro_html}</div>
  {shots_html}
</div>''')

    cards_html = "\n".join(cards)
    n = len(games)
    _logo = logo_img(40)
    brand_logo = f'<div class="brand-logo">{_logo}</div>' if _logo else ""
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>暮黎游戏日报 - {date_label}</title>
<style>
@font-face{{font-family:'reportfont';src:url('MuliHeavy.woff2') format('woff2');font-weight:normal;font-display:swap}}
*{{margin:0;padding:0;box-sizing:border-box}}
.ic{{vertical-align:middle;margin-right:2px}}
body{{font-family:'reportfont','PingFang SC','Microsoft YaHei','Noto Sans CJK SC','Hiragino Sans GB',sans-serif;
  background:
    radial-gradient(circle at 20% 30%, rgba(255,255,255,0.35) 0 6px, transparent 7px),
    radial-gradient(circle at 70% 60%, rgba(255,255,255,0.30) 0 6px, transparent 7px),
    linear-gradient(135deg,#ffd1e8 0%,#c5e1ff 50%,#d7c4ff 100%);
  background-size:46px 46px,46px 46px,100% 100%;
  padding:22px 14px 30px;line-height:1.6;color:#3a3340}}
.wrap{{max-width:720px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#ff8fb1,#9b6bff);border-radius:28px;
  padding:26px 22px;text-align:center;color:#fff;
  box-shadow:0 12px 30px rgba(155,107,255,0.35);position:relative;overflow:hidden}}
.header h1{{font-size:30px;font-weight:800;letter-spacing:2px;
  text-shadow:0 3px 0 rgba(0,0,0,0.12)}}
.header .brand-logo{{position:relative;z-index:1;width:56px;height:56px;margin:0 auto 12px;
  background:#fff;border-radius:18px;display:flex;align-items:center;justify-content:center;
  box-shadow:0 8px 20px rgba(0,0,0,0.18)}}
.header .brand-logo img{{width:40px;height:40px;display:block}}
.header .date{{margin-top:8px;display:inline-block;background:rgba(255,255,255,0.25);
  padding:6px 18px;border-radius:20px;font-size:16px;font-weight:700}}
.header .sub{{margin-top:8px;font-size:13px;opacity:0.9}}
.header .deco{{position:absolute;font-size:34px;opacity:0.5}}
.header .d1{{left:16px;top:14px}}
.header .d2{{right:16px;bottom:10px}}
.count{{text-align:center;margin:18px 0 6px;font-size:16px;font-weight:700;color:#7c4dff}}
.card{{position:relative;background:#fff;border:4px solid #ff7eb3;border-radius:26px;
  padding:18px 18px 16px;margin-bottom:22px;
  box-shadow:0 10px 24px rgba(120,90,160,0.18)}}
.card:nth-child(even){{transform:rotate(-0.6deg)}}
.card:nth-child(odd){{transform:rotate(0.6deg)}}
.badge{{position:absolute;top:-14px;right:18px;background:#ff7eb3;color:#fff;
  font-size:13px;font-weight:800;padding:4px 14px;border-radius:20px;
  box-shadow:0 4px 10px rgba(0,0,0,0.15);transform:rotate(6deg)}}
.card-head{{display:flex;gap:16px;align-items:center}}
.cover-wrap{{flex:0 0 120px}}
.cover{{width:120px;height:160px;object-fit:cover;border-radius:16px;
  border:3px solid #ffd1e8;box-shadow:0 6px 14px rgba(0,0,0,0.12)}}
.cover.noimg{{display:flex;align-items:center;justify-content:center;font-size:46px;
  background:#fff0f7;border:3px dashed #ffb3d1}}
.head-right{{flex:1;min-width:0}}
.title{{font-size:21px;font-weight:800;color:#2b2540;line-height:1.35;
  word-break:break-word}}
.chips{{margin-top:10px;display:flex;flex-wrap:wrap;gap:8px}}
.chip{{color:#fff;font-size:13px;font-weight:700;padding:4px 12px;border-radius:20px}}
.chip.gray{{background:#9aa0b5}}
.bubble{{position:relative;margin-top:14px;background:#fff7fb;border:2px solid #ffd9ec;
  border-radius:16px;padding:12px 14px;font-size:14px;line-height:1.8;color:#5a5160}}
.bubble:before{{content:"";position:absolute;left:24px;top:-10px;width:0;height:0;
  border-left:9px solid transparent;border-right:9px solid transparent;
  border-bottom:10px solid #ffd9ec}}
.bubble p{{margin:0 0 6px}}
.shots{{margin-top:14px;display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
.shot{{border-radius:14px;overflow:hidden;aspect-ratio:16/9;background:#f0eaf6;
  border:2px solid #ece3f7}}
.shot img{{width:100%;height:100%;object-fit:cover;display:block}}
.noshots{{margin-top:14px;text-align:center;color:#b0a8bd;font-size:14px;
  padding:18px;background:#f7f3fc;border-radius:14px}}
.footer{{text-align:center;margin-top:10px;padding:14px;color:#8a7fa0;font-size:13px}}
.footer b{{color:#7c4dff}}
</style></head>
<body><div class="wrap">
<div class="header">
  <span class="deco d1"><svg viewBox="0 0 48 32" width="36" height="24" fill="rgba(255,255,255,0.85)"><rect x="2" y="8" width="44" height="20" rx="10"/><circle cx="13" cy="18" r="3" fill="#fff"/><circle cx="19" cy="18" r="3" fill="#fff"/><rect x="32" y="15" width="3" height="7" fill="#fff"/><rect x="30.5" y="18.5" width="6" height="3" fill="#fff"/></svg></span><span class="deco d2"><svg viewBox="0 0 24 24" width="34" height="34" fill="rgba(255,255,255,0.85)"><path d="M12 2l3 6.3 6.9.9-5 4.9 1.2 6.9L12 18.8 5.9 21l1.2-6.9-5-4.9 6.9-.9z"/></svg></span>
  {brand_logo}
  <h1>暮黎游戏日报</h1>
  <div class="date">{date_label}</div>
  <div class="sub">游戏日报新鲜出炉，@机器人搜索游戏名称即可</div>
</div>
<div class="count"><svg class="ic" viewBox="0 0 24 24" width="16" height="16" fill="#ff8fb1"><path d="M12 2l3 6.3 6.9.9-5 4.9 1.2 6.9L12 18.8 5.9 21l1.2-6.9-5-4.9 6.9-.9z"/></svg> 今日共 {n} 款新游戏更新</div>
{cards_html}
<div class="footer">数据来源 <b>{source_label}</b> ｜ 由「暮黎资源聚合」插件自动生成<br>By：暮黎 Muliy</div>
</div></body></html>'''


# ==================== HTML → 图片（Playwright） ====================
def render_html_to_png(html_text: str, font_path: str = "", width: int = 700,
                        channel: str = "", exe: str = "") -> bytes | None:
    """用 Playwright 把卡通 HTML 渲染为 JPEG 字节（整页）。失败返回 None。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logger.error(f"[游戏日报] Playwright 未安装: {e}")
        return None
    tmpdir = tempfile.mkdtemp(prefix="game_report_")
    html_path = os.path.join(tmpdir, "report.html")
    try:
        import shutil
        fonts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "fonts")
        for _name in ("MuliHeavy.woff2",):
            _src = os.path.join(fonts_dir, _name)
            if os.path.exists(_src):
                shutil.copyfile(_src, os.path.join(tmpdir, _name))
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_text)
        with sync_playwright() as p:
            kw = {"headless": True,
                  "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]}
            if channel:
                kw["channel"] = channel
            elif exe:
                kw["executable_path"] = exe
            browser = p.chromium.launch(**kw)
            data = None
            # 先试 2x（高清），若页面过高超出 Chromium 截图尺寸上限则降级 1x
            for scale in (2, 1):
                page = browser.new_page(viewport={"width": width, "height": 1200},
                                        device_scale_factor=scale)
                try:
                    page.goto("file://" + html_path, wait_until="load")
                    page.wait_for_timeout(900)
                    data = page.screenshot(full_page=True, type="jpeg", quality=85)
                    break
                except Exception as e:
                    logger.warning(f"[游戏日报] 渲染(scale={scale})失败，尝试降级: {e}")
                    data = None
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            browser.close()
            return data
    except Exception as e:
        logger.error(f"[游戏日报] 渲染失败: {e}")
        return None
    finally:
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ==================== 打包 ZIP（HTML 文件） ====================
def gen_report_zip(games: list, html_str: str, ts: str) -> str | None:
    """把卡通 HTML 打包成 zip（HTML 内图片已内联，用户可在自己设备打开）。"""
    try:
        fd, path = tempfile.mkstemp(suffix=f"_{ts}.zip", prefix="game_report_")
        os.close(fd)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"暮黎游戏日报_{ts}.html", html_str)
        return path
    except Exception as e:
        logger.error(f"[游戏日报] ZIP 生成失败: {e}")
        return None

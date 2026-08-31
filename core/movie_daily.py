# -*- coding: utf-8 -*-
"""影视日报（片库新站 / a123tv 旧站，双源自动切换）相关函数。

每天抓取影视站主页「最近更新」的电影 / 剧集 / 动漫，排版成【毛玻璃简约风格】
HTML 后用 Playwright 渲染为图片发送。

支持两个源（由 fetch_movie_daily_auto 自动选择）：
  1) 片库新站（需 muliy_cookie）：首页 _obj.inlist，含状态/豆瓣/IMDb/画质，
     详情页 /{ty}/{id} 内联 _obj.d.summary 简介，封面 {MULIY_IMG_HOST}/img/{ty}/{id}/256.webp
  2) a123tv 旧站（免登录）：首页 w4-main 区块（电影/连续剧/动漫），含封面/类别·年份/
     画质(1080p/4K)，详情页抓简介；无 Cookie 也能出日报。

主页数据结构（片库新站，关键，已实测）：
    _obj.inlist = [
      {"g":[状态...], "t":[标题...], "d":[豆瓣分...], "im":[IMDb分...],
       "i":[ID...], "q":[[画质]...], "ty":"mv", "ht":"最近更新的电影"}, ...
    ]
  - ty: "mv"=电影 / "tv"=剧集 / "ac"=动漫

对外接口：
    fetch_movie_daily(cookie, base_url="", max_per_section=24, sections_filter=None, fetch_synopsis=True) -> dict
    fetch_movie_daily_a123tv(max_per_section=24, sections_filter=None, fetch_synopsis=True) -> dict
    fetch_movie_daily_auto(cookie="", base_url="", max_per_section=24, sections_filter=None, fetch_synopsis=True) -> dict
    build_glass_html(items, date_label, source_label="片库") -> str
    render_glass_to_png(html, font_path="", width=720, channel="", exe="") -> bytes|None
    gen_report_zip(items, html_str, ts) -> str|None
"""
import os
import re
import io
import time
import json
import base64
import tempfile
import zipfile
import logging

import requests
from PIL import Image

from .constants import logger, MULIY_UA, MULIY_IMG_HOST
from .muliy_site import MuliySiteClient, solve_pow, cover_url
from .mdi_icons import svg as _svg

# ty -> 中文类别名（用于区块标题与过滤）
SECTION_TY = {"mv": "电影", "tv": "剧集", "ac": "动漫"}
# 区块标题（主页 ht 字段）前缀 -> ty
_HT_TO_TY = {"最近更新的电影": "mv", "最近更新的剧集": "tv", "最近更新的动漫": "ac"}


# ==================== Cookie 清洗 ====================
def _clean_cookie(cookie_str: str) -> str:
    """去掉 browser_verified / browser_pow 等 PoW 相关 cookie。

    PoW 验证态由 solve_pow 现场重新求解并写入 session，若预置的
    browser_verified 与会话新生成的产生「同名重复 cookie」，requests
    会把两条都发出去导致服务端拒绝。因此注入登录身份时只保留
    app_auth / PHPSESSID 等鉴权字段，PoW 字段交给 solve_pow 生成。
    """
    if not cookie_str:
        return ""
    keep = []
    for part in re.split(r"[;\n]", cookie_str):
        part = part.strip()
        if "=" not in part:
            continue
        k = part.split("=", 1)[0].strip().lower()
        if k in ("browser_verified", "browser_pow", "browser_pow_verify",
                 "browser_pow_challenge"):
            continue
        keep.append(part)
    return "; ".join(keep)


# ==================== 主页抓取 ====================
def _fetch_homepage_html(client: MuliySiteClient) -> str:
    """带 PoW 预处理地抓取片库主页 HTML（含 _obj.inlist）。失败返回空串。"""
    base = client._get_base()
    hdrs = {"Referer": base + "/", "User-Agent": MULIY_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    try:
        # 1) 先 GET / 触发 browser_pow 挑战，再 solve_pow 解出 browser_verified
        try:
            client._session.get(base + "/", headers=hdrs, timeout=25, verify=False)
            solve_pow(client._session, base)
        except Exception as e:
            logger.warning(f"[影视日报] PoW 预处理异常: {e}")
        # 2) 取真页；若仍回到验证页则再解一次 PoW 后重试
        for _ in range(2):
            r = client._session.get(base + "/", headers=hdrs, timeout=25, verify=False)
            if "_obj.inlist" in r.text:
                return r.text
            try:
                solve_pow(client._session, base)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[影视日报] 主页获取失败: {e}")
    return ""


def parse_inlist(html: str) -> list:
    """从主页 HTML 提取 _obj.inlist 数组（list[section]）。"""
    m = re.search(r'_obj\.inlist\s*=\s*(\[[\s\S]*?\])\s*;', html)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception as e:
        logger.warning(f"[影视日报] inlist 解析失败: {e}")
        return []


# ==================== 条目组装 ====================
def _section_items(sec: dict, max_n: int, base: str) -> list:
    ty = sec.get("ty", "mv")
    ht = sec.get("ht", "")
    titles = sec.get("t", []) or []
    g = sec.get("g", []) or []
    d = sec.get("d", []) or []
    im = sec.get("im", []) or []
    i_ids = sec.get("i", []) or []
    q = sec.get("q", []) or []
    n = min(len(titles), max_n)
    items = []
    for k in range(n):
        iid = i_ids[k] if k < len(i_ids) else ""
        items.append({
            "title": titles[k] if k < len(titles) else "",
            "dir": ty,
            "type_name": SECTION_TY.get(ty, ty),
            "id": iid,
            "status": g[k] if k < len(g) else "",
            "douban": d[k] if k < len(d) else "",
            "imdb": im[k] if k < len(im) else "",
            "quality": (q[k] if k < len(q) and isinstance(q[k], list) else []) or [],
            "section_title": ht,
            "cover": cover_url(ty, iid) if iid else "",
            "cover_b64": "",
            "synopsis": "",
            "detail_url": (base + "/" + ty + "/" + iid) if iid else "",
        })
    return items


def _dl_and_b64(url: str, referer: str) -> str:
    """下载封面并压缩为 base64 data URI（离线渲染用）。失败返回空串。"""
    if not url or not url.startswith("http") or Image is None:
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": MULIY_UA, "Referer": referer,
                                       "Accept": "image/webp,image/*,*/*;q=0.8"},
                         timeout=15, verify=False)
        if r.status_code != 200:
            return ""
        img = Image.open(io.BytesIO(r.content))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            mask = img.split()[-1] if img.mode == "RGBA" else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w = img.width
        if w > 320:
            img = img.resize((320, int(img.height * 320 / w)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=78, optimize=True)
        b = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b}"
    except Exception as e:
        logger.debug(f"[影视日报] 封面下载失败 {str(url)[:50]}: {e}")
        return ""


def fetch_movie_daily(cookie: str = "", base_url: str = "", max_per_section: int = 24,
                      sections_filter: list = None, fetch_synopsis: bool = True) -> dict:
    """抓取片库影视日报（最近更新的电影/剧集/动漫）。

    参数：
      - cookie：片库登录态 Cookie（与 muliy_cookie 同款；browser_verified 会被自动剔除并现场 PoW）
      - base_url：留空则自动用片库默认域名
      - max_per_section：每个区块（电影/剧集/动漫）最多取多少部，<=0 表示不限制
      - sections_filter：只抓哪些类型，元素为 ty（"mv"/"tv"/"ac"）；None=全部
      - fetch_synopsis：是否逐个详情页抓简介（需更多请求；False 仅用主页信息）

    返回 {"success":bool,"items":[...],"error":""}
      - success=True 且 items=[] 表示主页无数据（error="暂无更新数据"）
    """
    res = {"success": False, "items": [], "error": ""}
    try:
        client = MuliySiteClient(base_url=base_url, cookies=_clean_cookie(cookie))
        base = client._get_base()
        html = _fetch_homepage_html(client)
        if not html:
            res["error"] = "主页获取失败（PoW 未通过或网络异常）"
            return res
        sections = parse_inlist(html)
        if not sections:
            res["error"] = "主页未解析到更新列表"
            return res

        items = []
        for sec in sections:
            ty = sec.get("ty", "mv")
            if sections_filter and ty not in sections_filter:
                continue
            cap = max_per_section if max_per_section and max_per_section > 0 else len(sec.get("t", []) or [])
            sec_items = _section_items(sec, cap, base)
            items.extend(sec_items)

        if not items:
            res["success"] = True
            res["error"] = "暂无更新数据"
            return res

        # 下载封面 + 抓简介
        for it in items:
            it["cover_b64"] = _dl_and_b64(it.get("cover", ""), base) if it.get("cover") else ""
            if fetch_synopsis and it.get("id"):
                try:
                    det = client.get_detail(it["dir"], it["id"])
                    it["synopsis"] = (det.get("desc", "") or "").strip() or "暂无简介"
                except Exception as e:
                    logger.warning(f"[影视日报] 简介获取失败 [{it.get('title','?')[:20]}]: {e}")
                    it["synopsis"] = "暂无简介"
                time.sleep(0.25)

        res["success"] = True
        res["items"] = items
    except Exception as e:
        logger.error(f"[影视日报] 抓取失败: {e}")
        res["error"] = str(e)[:200]
    return res


# ==================== a123tv 旧站源（无登录，免 Cookie 回退） ====================
from bs4 import BeautifulSoup  # noqa: E402

# a123tv 首页区块(h3) -> 标准 ty
_A123_CAT_TO_TY = {"电影": "mv", "连续剧": "tv", "电视剧": "tv", "动漫": "ac"}
# a123tv 区块 -> 日报展示标题（与片库源一致，复用图标）
_A123_CAT_TO_TITLE = {
    "电影": "最近更新的电影",
    "连续剧": "最近更新的剧集",
    "动漫": "最近更新的动漫",
}


def fetch_movie_daily_a123tv(max_per_section: int = 24, sections_filter: list = None,
                             fetch_synopsis: bool = True) -> dict:
    """抓取 a123tv.com（旧站，免登录）首页「最近更新」的影视日报。

    解析首页 w4-main 区块：每个区块 w4-meta>h3（电影/连续剧/动漫）+ 后续 w4-list
    条目（封面 data-src、标题、画质 div.r、信息 div.i 类别/年份）。
    返回结构与 fetch_movie_daily 一致：{"success","items","error","source":"a123tv"}。
    """
    res = {"success": False, "items": [], "error": "", "source": "a123tv"}
    try:
        from .movie import _get_html, _fix_url, get_movie_detail, MV_BASE_URL
        html = _get_html(MV_BASE_URL + "/")
        if not html:
            res["error"] = "a123tv 首页获取失败（可能被拦截或网络异常）"
            return res
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find("main", class_="w4-main") or soup

        items = []
        for meta in main.find_all("div", class_="w4-meta"):
            h3 = meta.find("h3")
            if not h3:
                continue
            cat = h3.get_text(strip=True)
            ty = _A123_CAT_TO_TY.get(cat)
            if not ty:
                continue  # 跳过 综艺 / 福利 等非标准区块
            if sections_filter and ty not in sections_filter:
                continue
            lst = meta.find_next_sibling("div", class_="w4-list")
            if not lst:
                continue
            cap = max_per_section if (max_per_section and max_per_section > 0) else 999
            cnt = 0
            for a in lst.find_all("a", class_="w4-item", href=True):
                if cnt >= cap:
                    break
                href = a["href"]
                # 封面（lazyload：真实地址在 data-src）
                cover = ""
                img = a.find("img")
                if img:
                    src = img.get("data-src") or img.get("src") or ""
                    if src:
                        cover = _fix_url(src)
                # 标题
                tdiv = a.find("div", class_="t")
                title = ""
                if tdiv is not None:
                    title = (tdiv.get("title") or tdiv.get_text(strip=True) or "").strip()
                if not title:
                    title = (a.get("title") or "").strip()
                if not title:
                    continue
                # 画质（如 1080p / 4K，在 div.r）
                qdiv = a.find("div", class_="r")
                quality = [qdiv.get_text(strip=True)] if (qdiv and qdiv.get_text(strip=True)) else []
                # 信息行（div.i：如 "剧情片 / 2026年"）作为状态徽标
                status = ""
                idiv = a.find("div", class_="i")
                if idiv:
                    status = idiv.get_text(" ", strip=True).replace(" / ", " · ").strip()
                slug = href.rsplit("/", 1)[-1].replace(".html", "")
                items.append({
                    "title": title,
                    "dir": ty,
                    "type_name": SECTION_TY.get(ty, ty),
                    "id": slug,
                    "status": status,
                    "douban": "",
                    "imdb": "",
                    "quality": quality,
                    "section_title": _A123_CAT_TO_TITLE.get(cat, cat),
                    "cover": cover,
                    "cover_b64": "",
                    "synopsis": "",
                    "detail_url": _fix_url(href),
                })
                cnt += 1

        if not items:
            res["success"] = True
            res["error"] = "暂无更新数据"
            return res

        # 下载封面 + 抓简介（a123tv 简介在详情页 meta/正文）
        for it in items:
            it["cover_b64"] = _dl_and_b64(it.get("cover", ""), MV_BASE_URL) if it.get("cover") else ""
            if fetch_synopsis and it.get("detail_url"):
                try:
                    det = get_movie_detail(it["detail_url"])
                    it["synopsis"] = (det.get("desc", "") or "暂无简介").strip() or "暂无简介"
                except Exception as e:
                    logger.warning(f"[影视日报-a123] 简介获取失败 [{it.get('title','?')[:20]}]: {e}")
                    it["synopsis"] = "暂无简介"
                time.sleep(0.2)

        res["success"] = True
        res["items"] = items
    except Exception as e:
        logger.error(f"[影视日报-a123] 抓取失败: {e}")
        res["error"] = str(e)[:200]
    return res


def fetch_movie_daily_auto(cookie: str = "", base_url: str = "", max_per_section: int = 24,
                           sections_filter: list = None, fetch_synopsis: bool = True) -> dict:
    """自动选择影视源获取日报：

    - 配置了片库 Cookie → 优先片库新站（登录态，含网盘/在线播放信息）；
      片库抓取失败/空数据 → 自动回退 a123tv 旧站。
    - 未配置 Cookie 或片库源不可用 → 直接用 a123tv（免登录）。

    返回 dict 额外带 "source" 字段（"片库" / "a123tv"），供前端标注数据来源。
    """
    if cookie and cookie.strip():
        try:
            r = fetch_movie_daily(cookie, base_url, max_per_section, sections_filter, fetch_synopsis)
            if r.get("success") and r.get("items"):
                r["source"] = "片库"
                return r
            logger.warning(f"[影视日报] 片库源不可用，回退 a123tv：{r.get('error','')}")
        except Exception as e:
            logger.warning(f"[影视日报] 片库源异常，回退 a123tv：{e}")
    r = fetch_movie_daily_a123tv(max_per_section, sections_filter, fetch_synopsis)
    r.setdefault("source", "a123tv")
    return r


# ==================== 毛玻璃简约风格 HTML ====================
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# 区块标题 -> 图标（Material Design Icons，避免服务器缺 emoji 字体乱码）
_SECTION_ICON = {"最近更新的电影": "movie", "最近更新的剧集": "tv", "最近更新的动漫": "anime"}


def _section_icon(title: str) -> str:
    for k, v in _SECTION_ICON.items():
        if k in (title or ""):
            return _svg(v, 22, "currentColor")
    return _svg("play", 22, "currentColor")


def build_glass_html(items: list, date_label: str, source_label: str = "片库") -> str:
    """把影视日报条目排版成毛玻璃简约风格 HTML（图片已内联 base64，离线可渲染）。

    按 section_title 分组；每部作品：封面(左) + 名称/状态/评分/画质(右) + 简介。
    背景铺满整页（不使用 background-attachment:fixed，避免整页截图时下方露白），
    并叠加装饰光斑层与更强的毛玻璃质感，排版更灵动。
    """
    # 分组
    groups = {}
    order = []
    for it in items:
        key = it.get("section_title") or it.get("type_name") or "其他"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(it)

    cards_blocks = []
    for key in order:
        sec_items = groups[key]
        sec_html = []
        for idx, g in enumerate(sec_items, 1):
            cover = g.get("cover_b64") or ""
            cover_html = (
                f'<img class="cover" src="{cover}" alt="封面">'
                if cover else
                f'<div class="cover noimg">{_svg("movie", 40, "currentColor")}</div>'
            )
            title = _esc(g.get("title", "") or "未知")
            # 状态徽标
            status = (g.get("status") or "").strip()
            status_html = f'<span class="badge">{_esc(status)}</span>' if status else ""

            # 评分 / 画质 小标签
            chips = []
            db = g.get("douban", "")
            im = g.get("imdb", "")
            if db and str(db) not in ("0", "0.0", ""):
                chips.append(f'<span class="chip db">{_svg("star", 12, "currentColor")} 豆瓣 {_esc(str(db))}</span>')
            if im and str(im) not in ("0", "0.0", ""):
                chips.append(f'<span class="chip im">{_svg("star", 12, "currentColor")} IMDb {_esc(str(im))}</span>')
            for q in (g.get("quality") or []):
                chips.append(f'<span class="chip q">{_esc(str(q))}</span>')
            chips_html = f'<div class="chips">{"" .join(chips)}</div>' if chips else ""

            syn = _esc(g.get("synopsis", "") or "暂无简介")
            if len(syn) > 140:
                syn = syn[:140] + "…"
            syn_html = "".join(f"<p>{ln}</p>" for ln in syn.split("\n") if ln.strip()) or "<p>暂无简介</p>"

            sec_html.append(f'''
<div class="card">
  <div class="idx">{idx:02d}</div>
  {status_html}
  <div class="card-head">
    <div class="cover-wrap">{cover_html}</div>
    <div class="head-right">
      <div class="title">{title}</div>
      {chips_html}
    </div>
  </div>
  <div class="synopsis">{syn_html}</div>
</div>''')
        block = (
            f'<div class="section">'
            f'<div class="sec-head"><span class="sec-ico">{_section_icon(key)}</span>'
            f'<span class="sec-title">{_esc(key)}</span></div>'
            f'<div class="sec-line"></div>'
            + "\n".join(sec_html) + "</div>"
        )
        cards_blocks.append(block)

    body_html = "\n".join(cards_blocks)
    n = len(items)

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>暮黎影视日报 - {date_label}</title>
<style>
@font-face{{font-family:'reportfont';src:url('report.otf') format('opentype');font-weight:normal;font-display:swap}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{background:#160a33;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{position:relative;min-height:100vh;font-family:'reportfont','PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif;
  color:#f2f2f7;line-height:1.65;
  background:
    radial-gradient(900px 600px at 8% 4%, rgba(139,92,246,0.55), transparent 60%),
    radial-gradient(800px 560px at 96% 10%, rgba(56,189,248,0.40), transparent 60%),
    radial-gradient(900px 700px at 92% 88%, rgba(236,72,153,0.42), transparent 60%),
    radial-gradient(760px 560px at 4% 92%, rgba(16,185,129,0.34), transparent 60%),
    linear-gradient(160deg,#1a0f3a 0%,#241248 38%,#102033 100%);
  background-color:#160a33;
  padding:26px 16px 36px}}
/* 装饰光斑层：随文档流铺满整页，整页截图不会露白 */
.bg{{position:absolute;inset:0;overflow:hidden;z-index:0;pointer-events:none}}
.bg i{{position:absolute;border-radius:50%;filter:blur(60px);opacity:0.5}}
.bg i:nth-child(1){{width:320px;height:320px;left:-80px;top:120px;background:radial-gradient(circle,#a855f7,transparent 70%)}}
.bg i:nth-child(2){{width:280px;height:280px;right:-60px;top:560px;background:radial-gradient(circle,#38bdf8,transparent 70%)}}
.bg i:nth-child(3){{width:360px;height:360px;left:30%;top:1500px;background:radial-gradient(circle,#ec4899,transparent 70%)}}
.bg i:nth-child(4){{width:260px;height:260px;right:10%;top:2400px;background:radial-gradient(circle,#34d399,transparent 70%)}}
.wrap{{position:relative;z-index:2;max-width:740px;margin:0 auto}}
.header{{position:relative;border-radius:28px;padding:32px 24px 30px;text-align:center;overflow:hidden;
  background:linear-gradient(135deg,rgba(255,255,255,0.16),rgba(255,255,255,0.06));
  backdrop-filter:blur(18px) saturate(160%);-webkit-backdrop-filter:blur(18px) saturate(160%);
  border:1px solid rgba(255,255,255,0.25);
  box-shadow:0 14px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.35)}}
.header::before{{content:"";position:absolute;left:-30%;top:0;width:160%;height:3px;
  background:linear-gradient(90deg,transparent,#f0abfc,#67e8f9,#a5b4fc,transparent)}}
.header .logo{{font-size:34px;line-height:1;margin-bottom:8px;filter:drop-shadow(0 4px 10px rgba(0,0,0,.35))}}
.header h1{{font-size:32px;font-weight:800;letter-spacing:4px;
  background:linear-gradient(90deg,#c4b5fd,#f0abfc,#67e8f9,#a5f3fc);-webkit-background-clip:text;
  background-clip:text;color:transparent}}
.header .date{{margin-top:12px;display:inline-block;background:rgba(255,255,255,0.16);
  padding:7px 22px;border-radius:22px;font-size:16px;font-weight:700;
  border:1px solid rgba(255,255,255,0.3)}}
.header .sub{{margin-top:10px;font-size:13px;opacity:0.85;letter-spacing:1px}}
.count{{text-align:center;margin:20px 0 4px;font-size:15px;font-weight:700;opacity:0.95;
  text-shadow:0 2px 8px rgba(0,0,0,.4)}}
.section{{margin-top:26px}}
.sec-head{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
.sec-ico{{font-size:22px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.4))}}
.sec-title{{font-size:19px;font-weight:800;letter-spacing:1px;
  background:linear-gradient(90deg,#fff,#e9d5ff);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sec-line{{height:2px;margin:-6px 0 14px;border-radius:2px;
  background:linear-gradient(90deg,rgba(244,114,182,0.8),rgba(168,85,247,0.5),transparent)}}
.card{{position:relative;display:flex;flex-direction:column;gap:12px;align-items:stretch;
  background:linear-gradient(135deg,rgba(255,255,255,0.12),rgba(255,255,255,0.05));
  backdrop-filter:blur(16px) saturate(160%);-webkit-backdrop-filter:blur(16px) saturate(160%);
  border:1px solid rgba(255,255,255,0.2);border-radius:22px;
  padding:16px 16px 16px 18px;margin-bottom:16px;
  box-shadow:0 10px 26px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.28)}}
.idx{{position:absolute;left:-10px;top:14px;width:30px;height:30px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;color:#fff;
  background:linear-gradient(135deg,#a855f7,#6366f1);box-shadow:0 4px 12px rgba(99,102,241,0.5)}}
.badge{{position:absolute;top:-11px;right:16px;background:linear-gradient(135deg,#f472b6,#a855f7);
  color:#fff;font-size:12px;font-weight:800;padding:4px 13px;border-radius:18px;
  box-shadow:0 4px 12px rgba(168,85,247,0.5)}}
.card-head{{display:flex;gap:16px;align-items:center;width:100%}}
.cover-wrap{{flex:0 0 96px}}
.cover{{width:96px;height:132px;object-fit:cover;border-radius:14px;
  border:1px solid rgba(255,255,255,0.3);box-shadow:0 8px 20px rgba(0,0,0,0.45)}}
.cover.noimg{{display:flex;align-items:center;justify-content:center;font-size:40px;
  background:rgba(255,255,255,0.08);border:1px dashed rgba(255,255,255,0.35)}}
.head-right{{flex:1;min-width:0}}
.title{{font-size:19px;font-weight:800;line-height:1.4;word-break:break-word;
  text-shadow:0 2px 6px rgba(0,0,0,.35)}}
.chips{{margin-top:10px;display:flex;flex-wrap:wrap;gap:7px}}
.chip{{font-size:12px;font-weight:700;padding:3px 11px;border-radius:14px;
  background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.22)}}
.chip.db{{background:rgba(250,204,21,0.24);border-color:rgba(250,204,21,0.55);color:#fde68a}}
.chip.im{{background:rgba(56,189,248,0.22);border-color:rgba(56,189,248,0.55);color:#bae6fd}}
.chip.q{{background:rgba(244,63,94,0.24);border-color:rgba(244,63,94,0.55);color:#fecdd3}}
.synopsis{{margin-top:12px;font-size:13.5px;line-height:1.9;opacity:0.92;
  border-top:1px solid rgba(255,255,255,0.14);padding-top:11px}}
.synopsis p{{margin:0 0 5px}}
.footer{{position:relative;text-align:center;margin-top:16px;padding:18px;font-size:13px;opacity:0.85;
  background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.14);border-radius:20px;
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}}
.footer b{{color:#c4b5fd;font-weight:800}}
</style></head>
<body>
<div class="bg"><i></i><i></i><i></i><i></i></div>
<div class="wrap">
<div class="header">
  <div class="logo">{_svg("movie", 34, "currentColor")}</div>
  <h1>暮黎影视日报</h1>
  <div class="date">{date_label}</div>
  <div class="sub">今日影视新鲜速递 · 回复片名即可追剧</div>
</div>
<div class="count">{_svg("movie", 17, "currentColor")} 今日共更新 {n} 部影视</div>
{body_html}
<div class="footer">数据来源 <b>{source_label}</b> ｜ 由「暮黎资源聚合」插件自动生成<br>By：暮黎 Muliy</div>
</div></body></html>'''


# ==================== HTML → 图片（复用游戏日报 Playwright） ====================
def render_glass_to_png(html_text: str, font_path: str = "", width: int = 720,
                        channel: str = "", exe: str = "") -> bytes | None:
    """用 Playwright 把毛玻璃 HTML 渲染为 JPEG 字节（整页）。失败返回 None。"""
    from .game_daily import render_html_to_png
    return render_html_to_png(html_text, font_path, width, channel, exe)


# ==================== 打包 ZIP（HTML 文件） ====================
def gen_report_zip(items: list, html_str: str, ts: str) -> str | None:
    """把影视日报 HTML 打包成 zip（图片已内联，用户可在自己设备打开）。"""
    try:
        fd, path = tempfile.mkstemp(suffix=f"_{ts}.zip", prefix="movie_report_")
        os.close(fd)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"暮黎影视日报_{ts}.html", html_str)
        return path
    except Exception as e:
        logger.error(f"[影视日报] ZIP 生成失败: {e}")
        return None

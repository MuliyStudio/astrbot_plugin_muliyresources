# -*- coding: utf-8 -*-
"""短剧搜索与日报（网盘贴吧 wangpant8.com）。

站点为 Next.js（App Router）SSR：页面 HTML 里直接带数据，无需签名/登录。

实测结构（2026-10）：
  搜索页  GET /search/{关键词}?page=N
      → 结果条目：<a href="/details/{id}"> 日期 + 分类("短剧") + 剧名（N集）
  详情页  GET /details/{id}
      → <h1>剧名（N集）</h1>，页面 RSC 内嵌转义 JSON：
        \"diskType\":\"夸克\"  \"fromShareLink\":\"https://pan.quark.cn/s/xxx\"
        \"webdramaType\":\"短剧\"  \"fileName\":\"剧名（N集）\"
  首页    GET /
      → 「最新上传」列表（日期/短剧/剧名/详情链接/网盘图标），另有热榜

对外接口：
    search_dramas(keyword, limit=20, timeout=15)  -> {"success","items","total_pages","error"}
    get_drama_detail(drama_id, timeout=15)        -> {"success","title","link","disk_type",...}
    fetch_latest_dramas(limit=12, resolve_links=True, timeout=15) -> {"success","items","error"}
    build_drama_html(items, date_label)           -> str
    render_drama_to_png(html, font_path, width, channel, exe) -> bytes|None
    gen_report_zip(items, html_str, ts)           -> str|None
"""
import os
import re
import io
import time
import base64
import tempfile
import zipfile

import requests

from .constants import logger
from .mdi_icons import svg as _svg

DRAMA_BASE = "https://www.wangpant8.com"
DRAMA_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DRAMA_HEADERS = {
    "User-Agent": DRAMA_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": DRAMA_BASE + "/",
}

# 网盘类型图标（本站资源全部为夸克网盘）
DRAMA_DISK_ICONS = {"夸克": "🟣", "夸克网盘": "🟣", "百度": "☁️", "阿里": "🟠",
                    "UC": "📂", "123": "🔑", "迅雷": "⚡"}

_DETAIL_RE = re.compile(r"^/details/(\d+)$")
_DATE_RE = re.compile(r"^(\d{1,2}/\d{1,2}(?:/\d{4})?)$")


def _disk_icon(disk: str) -> str:
    disk = (disk or "").strip()
    for k, v in DRAMA_DISK_ICONS.items():
        if k and k in disk:
            return v
    return "🟣"


def _get_html(url: str, timeout: int = 15) -> str:
    """GET 页面 HTML。失败返回空串（不抛异常）。"""
    try:
        r = requests.get(url, headers=DRAMA_HEADERS, timeout=max(5, int(timeout or 15)))
        if r.status_code == 200:
            return r.text
        logger.warning(f"[短剧] HTTP {r.status_code}: {url}")
    except Exception as e:
        logger.warning(f"[短剧] 请求失败 {url}: {e}")
    return ""


def _parse_list_items(html: str) -> list:
    """解析页面里所有 /details/{id} 链接条目（搜索页与首页通用）。

    每条抽取：id / 日期 / 分类 / 剧名 / 网盘类型 / 详情页链接。
    返回按页面出现顺序去重的列表。
    """
    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
    except Exception:
        logger.error("[短剧] 缺少 beautifulsoup4，无法解析列表")
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = _DETAIL_RE.match((a.get("href") or "").strip())
        if not m:
            continue
        did = m.group(1)
        if did in seen:
            continue
        date, category = "", ""
        for sp in a.find_all("span"):
            cls = " ".join(sp.get("class") or [])
            txt = sp.get_text(" ", strip=True)
            if _DATE_RE.match(txt):
                date = txt
            elif "p-1" in cls and "bg-" in cls:
                category = txt
        pl2 = a.find("span", class_=re.compile(r"pl-2"))
        title = (pl2.get_text("", strip=True) if pl2 else "").strip()
        if not title:
            continue
        img = a.find("img")
        disk = ((img.get("alt") or "").strip() if img else "")
        seen.add(did)
        out.append({
            "id": did,
            "title": title,
            "category": category or "短剧",
            "date": date,
            "disk": disk,
            "detail_url": f"{DRAMA_BASE}/details/{did}",
        })
    return out


def _rsc_field(html: str, name: str) -> str:
    """从详情页转义 JSON 中取字符串字段，如 \\"fromShareLink\\":\\"https://...\\"。"""
    m = re.search(r'\\?"' + re.escape(name) + r'\\?":\\?"([^"\\]*)', html or "")
    return m.group(1) if m else ""


def search_dramas(keyword: str, limit: int = 20, timeout: int = 15) -> dict:
    """按关键词搜索短剧。

    返回 {"success","items":[{id,title,category,date,disk,detail_url}],"total_pages","error"}
      - success=True 且 items=[] 表示无结果（error="no_result"）。
    """
    from urllib.parse import quote
    res = {"success": False, "items": [], "total_pages": 1, "error": ""}
    kw = (keyword or "").strip()
    if not kw:
        res["error"] = "关键词为空"
        return res
    html = _get_html(f"{DRAMA_BASE}/search/{quote(kw)}", timeout)
    if not html:
        res["error"] = "站点请求失败（可能被拦截或网络异常）"
        return res
    items = _parse_list_items(html)
    m = re.search(r'"totalPages"\s*:\s*(\d+)', html)
    if m:
        try:
            res["total_pages"] = max(1, int(m.group(1)))
        except Exception:
            pass
    if not items:
        res["success"] = True
        res["error"] = "no_result"
        return res
    if limit and limit > 0:
        items = items[:limit]
    res["items"] = items
    res["success"] = True
    return res


def get_drama_detail(drama_id: str, timeout: int = 15) -> dict:
    """取短剧详情 + 真实网盘链接。

    返回 {"success","id","title","link","disk_type","type","detail_url","error"}
    """
    res = {"success": False, "error": ""}
    did = str(drama_id or "").strip()
    if not did.isdigit():
        res["error"] = "无效的详情 ID"
        return res
    url = f"{DRAMA_BASE}/details/{did}"
    html = _get_html(url, timeout)
    if not html:
        res["error"] = "详情页请求失败"
        return res
    h1 = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if m:
        h1 = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    link = _rsc_field(html, "fromShareLink")
    disk = _rsc_field(html, "diskType") or "夸克"
    typ = _rsc_field(html, "webdramaType") or "短剧"
    fname = _rsc_field(html, "fileName")
    title = fname or h1 or did
    res.update({"id": did, "title": title, "disk_type": disk, "type": typ,
                "detail_url": url})
    if not link:
        res["error"] = "未能解析到网盘链接（该条目可能暂无资源）"
        return res
    res["link"] = link
    res["success"] = True
    return res


def fetch_latest_dramas(limit: int = 12, resolve_links: bool = True,
                        timeout: int = 15) -> dict:
    """抓取首页「最新上传」短剧（带日期的条目）。

    resolve_links=True 时逐个进入详情页取真实网盘链接（用于日报直接给出可转存链接）。
    返回 {"success","items":[{id,title,category,date,disk,detail_url,link}],"error"}
    """
    res = {"success": False, "items": [], "error": ""}
    html = _get_html(DRAMA_BASE + "/", timeout)
    if not html:
        res["error"] = "首页请求失败（可能被拦截或网络异常）"
        return res
    items = _parse_list_items(html)
    # 首页同时包含「最新上传」与「热榜」；最新上传带日期（MM/DD），热榜无日期。
    latest = [it for it in items if it.get("date")] or items
    if limit and limit > 0:
        latest = latest[:limit]
    if not latest:
        res["success"] = True
        res["error"] = "no_result"
        return res
    if resolve_links:
        for it in latest:
            try:
                det = get_drama_detail(it["id"], timeout)
                if det.get("success"):
                    it["link"] = det.get("link", "")
                    if det.get("title"):
                        it["title"] = det["title"]
            except Exception as e:
                logger.debug(f"[短剧] 详情解析失败 {it.get('id')}: {e}")
            time.sleep(0.15)
    res["items"] = latest
    res["success"] = True
    return res


# ==================== 日报 HTML（毛玻璃简约风，复用影视日报视觉） ====================
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_drama_html(items: list, date_label: str) -> str:
    """把短剧日报条目排版成毛玻璃简约风格 HTML（离线可渲染，无需外链资源）。"""
    cards = []
    for idx, it in enumerate(items, 1):
        title = _esc(it.get("title") or "未知")
        chips = []
        cat = (it.get("category") or "短剧").strip()
        if cat:
            chips.append(f'<span class="chip cat">{_esc(cat)}</span>')
        date = (it.get("date") or "").strip()
        if date:
            chips.append(f'<span class="chip date">{_svg("event", 12, "currentColor")} {_esc(date)}</span>')
        disk = (it.get("disk") or "夸克").strip()
        if disk:
            chips.append(f'<span class="chip disk">{_disk_icon(disk)} {_esc(disk)}</span>')
        chips_html = f'<div class="chips">{"".join(chips)}</div>' if chips else ""

        link = (it.get("link") or "").strip()
        link_html = (f'<div class="link">{_svg("link", 14, "currentColor")}'
                     f'<span>{_esc(link)}</span></div>') if link else ""

        cards.append(f'''
<div class="card">
  <div class="idx">{idx:02d}</div>
  <div class="title">{title}</div>
  {chips_html}
  {link_html}
</div>''')

    body_html = "\n".join(cards)
    n = len(items)
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>暮黎短剧日报 - {date_label}</title>
<style>
@font-face{{font-family:'reportfont';src:url('report.otf') format('opentype');font-weight:normal;font-display:swap}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{background:#12082b;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{position:relative;min-height:100vh;font-family:'reportfont','PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif;
  color:#f2f2f7;line-height:1.65;
  background:
    radial-gradient(900px 600px at 8% 4%, rgba(244,114,182,0.50), transparent 60%),
    radial-gradient(800px 560px at 96% 10%, rgba(139,92,246,0.45), transparent 60%),
    radial-gradient(900px 700px at 92% 88%, rgba(56,189,248,0.36), transparent 60%),
    linear-gradient(160deg,#1a0f3a 0%,#2a1050 40%,#101a33 100%);
  background-color:#12082b;padding:26px 16px 36px}}
.bg{{position:absolute;inset:0;overflow:hidden;z-index:0;pointer-events:none}}
.bg i{{position:absolute;border-radius:50%;filter:blur(60px);opacity:0.5}}
.bg i:nth-child(1){{width:320px;height:320px;left:-80px;top:120px;background:radial-gradient(circle,#f472b6,transparent 70%)}}
.bg i:nth-child(2){{width:280px;height:280px;right:-60px;top:620px;background:radial-gradient(circle,#a855f7,transparent 70%)}}
.bg i:nth-child(3){{width:360px;height:360px;left:28%;top:1600px;background:radial-gradient(circle,#38bdf8,transparent 70%)}}
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
  background:linear-gradient(90deg,#fbcfe8,#c4b5fd,#67e8f9,#a5f3fc);-webkit-background-clip:text;
  background-clip:text;color:transparent}}
.header .date{{margin-top:12px;display:inline-block;background:rgba(255,255,255,0.16);
  padding:7px 22px;border-radius:22px;font-size:16px;font-weight:700;
  border:1px solid rgba(255,255,255,0.3)}}
.header .sub{{margin-top:10px;font-size:13px;opacity:0.85;letter-spacing:1px}}
.count{{text-align:center;margin:20px 0 4px;font-size:15px;font-weight:700;opacity:0.95;
  text-shadow:0 2px 8px rgba(0,0,0,.4)}}
.card{{position:relative;display:flex;flex-direction:column;gap:12px;align-items:stretch;
  background:linear-gradient(135deg,rgba(255,255,255,0.12),rgba(255,255,255,0.05));
  backdrop-filter:blur(16px) saturate(160%);-webkit-backdrop-filter:blur(16px) saturate(160%);
  border:1px solid rgba(255,255,255,0.2);border-radius:22px;
  padding:16px 16px 16px 20px;margin-top:16px;
  box-shadow:0 10px 26px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.28)}}
.idx{{position:absolute;left:-10px;top:16px;width:30px;height:30px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;color:#fff;
  background:linear-gradient(135deg,#f472b6,#a855f7);box-shadow:0 4px 12px rgba(168,85,247,0.5)}}
.title{{font-size:19px;font-weight:800;line-height:1.45;word-break:break-word;
  text-shadow:0 2px 6px rgba(0,0,0,.35)}}
.chips{{display:flex;flex-wrap:wrap;gap:7px}}
.chip{{font-size:12px;font-weight:700;padding:3px 11px;border-radius:14px;
  display:inline-flex;align-items:center;gap:4px;
  background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.22)}}
.chip.cat{{background:rgba(244,114,182,0.24);border-color:rgba(244,114,182,0.55);color:#fbcfe8}}
.chip.date{{background:rgba(56,189,248,0.20);border-color:rgba(56,189,248,0.5);color:#bae6fd}}
.chip.disk{{background:rgba(168,85,247,0.22);border-color:rgba(168,85,247,0.55);color:#e9d5ff}}
.link{{display:flex;align-items:flex-start;gap:7px;margin-top:2px;padding-top:10px;
  border-top:1px solid rgba(255,255,255,0.14);
  font-size:13px;color:#a5f3fc;word-break:break-all}}
.link span{{flex:1;min-width:0}}
.footer{{position:relative;text-align:center;margin-top:18px;padding:18px;font-size:13px;opacity:0.85;
  background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.14);border-radius:20px;
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}}
.footer b{{color:#c4b5fd;font-weight:800}}
</style></head>
<body>
<div class="bg"><i></i><i></i><i></i></div>
<div class="wrap">
<div class="header">
  <div class="logo">{_svg("movie", 34, "currentColor")}</div>
  <h1>暮黎短剧日报</h1>
  <div class="date">{date_label}</div>
  <div class="sub">每日精选短剧 · 夸克网盘转存即看</div>
</div>
<div class="count">{_svg("fire", 17, "currentColor")} 今日上新 {n} 部短剧</div>
{body_html}
<div class="footer">数据来源 <b>网盘贴吧</b> ｜ 由「暮黎资源聚合」插件自动生成<br>By：暮黎 Muliy</div>
</div></body></html>'''


def render_drama_to_png(html_text: str, font_path: str = "", width: int = 720,
                        channel: str = "", exe: str = "") -> bytes | None:
    """用 Playwright 把短剧日报 HTML 渲染为 JPEG 字节（整页）。失败返回 None。"""
    from .game_daily import render_html_to_png
    return render_html_to_png(html_text, font_path, width, channel, exe)


def gen_report_zip(items: list, html_str: str, ts: str) -> str | None:
    """把短剧日报 HTML 打包成 zip（供面板回看/离线打开）。"""
    try:
        fd, path = tempfile.mkstemp(suffix=f"_{ts}.zip", prefix="drama_report_")
        os.close(fd)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"暮黎短剧日报_{ts}.html", html_str)
        return path
    except Exception as e:
        logger.error(f"[短剧日报] ZIP 生成失败: {e}")
        return None

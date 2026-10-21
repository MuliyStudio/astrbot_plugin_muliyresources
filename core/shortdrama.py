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
import datetime
import tempfile
import zipfile

import requests

from .constants import logger
from .mdi_icons import svg as _svg
from .brand import logo_img

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

    resolve_links=True 时逐个进入详情页取真实网盘链接（用于文字兜底/zip）。
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


# ==================== 农历 / 星期（纯 Python，无需第三方依赖） ====================
_LUNAR_INFO = [
    0x04bd8,0x04ae0,0x0a570,0x054d5,0x0d260,0x0d950,0x16554,0x056a0,0x09ad0,0x055d2,
    0x04ae0,0x0a5b6,0x0a4d0,0x0d250,0x1d255,0x0b540,0x0d6a0,0x0ada2,0x095b0,0x14977,
    0x04970,0x0a4b0,0x0b4b5,0x06a50,0x06d40,0x1ab54,0x02b60,0x09570,0x052f2,0x04970,
    0x06566,0x0d4a0,0x0ea50,0x06e95,0x05ad0,0x02b60,0x186e3,0x092e0,0x1c8d7,0x0c950,
    0x0d4a0,0x1d8a6,0x0b550,0x056a0,0x1a5b4,0x025d0,0x092d0,0x0d2b2,0x0a950,0x0b557,
    0x06ca0,0x0b550,0x15355,0x04da0,0x0a5b0,0x14573,0x052b0,0x0a9a8,0x0e950,0x06aa0,
    0x0aea6,0x0ab50,0x04b60,0x0aae4,0x0a570,0x05260,0x0f263,0x0d950,0x05b57,0x056a0,
    0x096d0,0x04dd5,0x04ad0,0x0a4d0,0x0d4d4,0x0d250,0x0d558,0x0b540,0x0b6a0,0x195a6,
    0x095b0,0x049b0,0x0a974,0x0a4b0,0x0b27a,0x06a50,0x06d40,0x0af46,0x0ab60,0x09570,
    0x04af5,0x04970,0x064b0,0x074a3,0x0ea50,0x06b58,0x05ac0,0x0ab60,0x096d5,0x092e0,
    0x0c960,0x0d954,0x0d4a0,0x0da50,0x07552,0x056a0,0x0abb7,0x025d0,0x092d0,0x0cab5,
    0x0a950,0x0b4a0,0x0baa4,0x0ad50,0x055d9,0x04ba0,0x0a5b0,0x15176,0x052b0,0x0a930,
    0x07954,0x06aa0,0x0ad50,0x05b52,0x04b60,0x0a6e6,0x0a4e0,0x0d260,0x0ea65,0x0d530,
    0x05aa0,0x076a3,0x096d0,0x04afb,0x04ad0,0x0a4d0,0x1d0b6,0x0d250,0x0d520,0x0dd45,
    0x0b5a0,0x056d0,0x055b2,0x049b0,0x0a577,0x0a4b0,0x0aa50,0x1b255,0x06d20,0x0ada0,
    0x14b63,0x09370,0x049f8,0x04970,0x064b0,0x168a6,0x0ea50,0x06b20,0x1a6c4,0x0aae0,
    0x0a2e0,0x0d2e3,0x0c960,0x0d557,0x0d4a0,0x0da50,0x05d55,0x056a0,0x0a6d0,0x055d4,
    0x052d0,0x0a9b8,0x0a950,0x0b4a0,0x0b6a6,0x0ad50,0x055a0,0x0aba4,0x0a5b0,0x052b0,
    0x0b273,0x06930,0x07337,0x06aa0,0x0ad50,0x14b55,0x04b60,0x0a570,0x054e4,0x0d160,
    0x0e968,0x0d520,0x0daa0,0x16aa6,0x056d0,0x04ae0,0x0a9d4,0x0a2d0,0x0d150,0x0f252,
    0x0d520,
]
_LUNAR_BASE = datetime.date(1900, 1, 31)
_GAN = "甲乙丙丁戊己庚辛壬癸"
_ZHI = "子丑寅卯辰巳午未申酉戌亥"
_MONTH_CN = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
_DAY_CN = ["初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
           "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
           "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]
_WEEK_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _leap_month(y: int) -> int:
    return _LUNAR_INFO[y - 1900] & 0xf


def _leap_days(y: int) -> int:
    return 30 if (_LUNAR_INFO[y - 1900] & 0x10000) else 29


def _month_days(y: int, m: int) -> int:
    return 30 if (_LUNAR_INFO[y - 1900] & (0x10000 >> m)) else 29


def _year_days(y: int) -> int:
    s = 0
    for i in range(1, 13):
        s += _month_days(y, i)
    return s + _leap_days(y) if _leap_month(y) else s


def solar_to_lunar(d: datetime.date) -> dict:
    """公历 → 农历，返回 {year, month, day, leap, ganzhi}。支持 1900-2100。"""
    if isinstance(d, datetime.datetime):
        d = d.date()
    offset = (d - _LUNAR_BASE).days
    y = 1900
    while y < 2101:
        yd = _year_days(y)
        if offset < yd:
            break
        offset -= yd
        y += 1
    leap = _leap_month(y)
    is_leap = False
    m = 1
    while m <= 12:
        if leap > 0 and m == leap + 1 and not is_leap:
            cur = _leap_days(y)
            is_leap = True
            m -= 1
        else:
            cur = _month_days(y, m)
        if offset < cur:
            break
        offset -= cur
        if is_leap and m == leap + 1:
            is_leap = False
        m += 1
    day = offset + 1
    return {"year": y, "month": m, "day": day, "leap": is_leap,
            "ganzhi": _GAN[(y - 4) % 10] + _ZHI[(y - 4) % 12]}


def lunar_text(d: datetime.date) -> str:
    """返回如「丙午年九月初六」。"""
    if isinstance(d, datetime.datetime):
        d = d.date()
    l = solar_to_lunar(d)
    mon = _MONTH_CN[l["month"] - 1] if 1 <= l["month"] <= 12 else str(l["month"])
    day = _DAY_CN[l["day"] - 1] if 1 <= l["day"] <= 30 else str(l["day"])
    return f"{l['ganzhi']}年{'闰' if l['leap'] else ''}{mon}月{day}"


def weekday_text(d: datetime.date) -> str:
    return _WEEK_CN[d.weekday()]


# ==================== 日报 HTML（浅色杂志风：标题 + 大号星期 + 编号剧名列表） ====================
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# 字体栈：优先思源宋体/黑体（服务器已装 Noto CJK），回退到插件内嵌 reportfont，
# 保证在没有系统 CJK 字体的机器上也不会出现豆腐块。
_FONT_SANS = ("'Noto Sans CJK SC','Source Han Sans SC','Source Han Sans CN',"
              "'PingFang SC','Microsoft YaHei','reportfont',sans-serif")
_FONT_SERIF = ("'Noto Serif CJK SC','Source Han Serif SC','Source Han Serif CN',"
               "'Songti SC','STSong','SimSun','reportfont',serif")


def _label_to_date(date_label: str) -> datetime.date:
    """把「2026年10月15日」解析为 date；失败用今天。"""
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", date_label or "")
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return datetime.date.today()


def build_drama_html(items: list, date_label: str) -> str:
    """短剧日报 HTML：编号列表只放剧名，其余以标题/星期/引语/页脚等装饰为主。

    浅色杂志风（参考「每天 60s 读懂世界」排版）。
    """
    d = _label_to_date(date_label)
    week = weekday_text(d)
    lunar = lunar_text(d)
    n = len(items)

    rows = []
    for idx, it in enumerate(items, 1):
        title = _esc(it.get("title") or "未知")
        rows.append(
            f'<li class="item"><span class="num">{idx}</span>'
            f'<span class="txt">{title}</span></li>'
        )
    list_html = "\n".join(rows) or '<li class="item"><span class="txt">今日暂无上新</span></li>'
    _logo = logo_img(34)
    brand_logo = (f'<div class="h-brand">{_logo}</div>' if _logo else "")

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>暮黎短剧日报 - {_esc(date_label)}</title>
<style>
@font-face{{font-family:'reportfont';src:url('MuliHeavy.woff2') format('woff2');font-weight:normal;font-display:swap}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{background:#f6f4ef;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{font-family:{_FONT_SANS};color:#1f2328;background:#f6f4ef;
  background-image:radial-gradient(circle at 12% 6%, rgba(232,121,43,0.05), transparent 42%),
                   radial-gradient(circle at 92% 2%, rgba(232,121,43,0.05), transparent 36%);
  padding-bottom:30px}}
.topbar{{height:4px;background:linear-gradient(90deg,#f5a623,#e8792b 45%,rgba(232,121,43,0.15) 72%,transparent)}}
.wrap{{max-width:720px;margin:0 auto;padding:34px 30px 0}}
.header{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding-bottom:18px}}
.h-brand{{display:flex;align-items:center;margin-bottom:8px}}
.h-brand img{{width:34px;height:34px;display:block}}
.h-title{{font-family:{_FONT_SERIF};font-size:38px;font-weight:800;letter-spacing:1.5px;color:#1c1f24;line-height:1.05}}
.h-sub{{margin-top:13px;display:flex;align-items:center;gap:9px;font-size:15px;color:#8a8577}}
.h-sub .ico{{display:inline-flex;align-items:center}}
.h-sub .date{{color:#3a3f46;font-weight:700;letter-spacing:0.5px}}
.h-sub .dot{{color:#d8d2c6}}
.h-week{{font-family:{_FONT_SERIF};font-size:46px;font-weight:800;letter-spacing:4px;color:#1c1f24;line-height:0.95;white-space:nowrap}}
.rule{{height:2px;background:linear-gradient(90deg,#e8792b,rgba(232,121,43,0.22) 55%,transparent)}}
.list{{list-style:none;margin-top:14px}}
.item{{display:flex;gap:15px;align-items:flex-start;padding:13px 0;
  border-bottom:1px dashed #ece7dd}}
.item:last-child{{border-bottom:none}}
.num{{flex:0 0 25px;width:25px;height:25px;border-radius:50%;border:1.5px solid #ccc5b8;color:#8f897a;
  font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:3px}}
.txt{{flex:1;font-size:18px;font-weight:700;line-height:1.62;color:#22262b;letter-spacing:0.3px;word-break:break-word}}
.quote{{margin-top:24px;padding:20px 26px;border-radius:16px;
  background:linear-gradient(180deg,#fbfaf7,#f7f4ee);border:1px solid #ece7dd;
  font-family:{_FONT_SERIF};font-size:16px;color:#5f594b;text-align:center;line-height:1.85;letter-spacing:0.5px}}
.quote .q{{color:#e8792b;font-weight:700;padding:0 6px}}
.foot{{margin-top:22px;padding-top:15px;border-top:1px solid #e7e2d8;
  display:flex;justify-content:space-between;gap:14px;color:#a29c8e;font-size:12.5px}}
.foot .r{{text-align:right;white-space:nowrap}}
.foot b{{color:#8a8577;font-weight:700}}
</style></head>
<body>
<div class="topbar"></div>
<div class="wrap">
  <div class="header">
    <div>
      {brand_logo}
      <div class="h-title">暮黎短剧日报</div>
      <div class="h-sub"><span class="ico">{_svg("event", 15, "#e8792b")}</span><span class="date">{_esc(date_label)}</span><span class="dot">·</span><span>农历 {lunar}</span></div>
    </div>
    <div class="h-week">{week}</div>
  </div>
  <div class="rule"></div>
  <ol class="list">
{list_html}
  </ol>
  <div class="quote"><span class="q">「</span>好剧不怕晚 · 每日准时见<span class="q">」</span></div>
  <div class="foot">
    <div><b>数据来源</b> 网盘贴吧 · 共 {n} 部上新</div>
    <div class="r">@暮黎资源聚合 · 更新于 {d.strftime('%Y/%m/%d')}</div>
  </div>
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

# -*- coding: utf-8 -*-
"""签到成功卡片：Bing 每日壁纸 + 天气 + 每日一言 + 资源推荐 → HTML。

数据源（全部免 Key）：
- Bing 每日壁纸：https://www.bing.com/HPImageArchive.aspx
- 天气：UAPI（https://uapis.cn/api/v1/misc/weather）优先，wttr.in 兜底
- 每日一言：https://v1.hitokoto.cn/
- 推荐：插件后台配置的本地清单（每天轮换，不依赖网络）

渲染：主程序优先 Playwright，失败回退 AstrBot 内置 T2I。
"""

from __future__ import annotations

import base64
import html
import io
import os
import random
import re
import shutil
import tempfile
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

try:
    import requests
except ImportError:  # requests 缺失时签到卡片降级为占位内容
    requests = None

try:
    from PIL import Image
except ImportError:  # Pillow 为插件可选依赖，缺失时直接内联原图
    Image = None

from .mdi_icons import svg

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_BING_CACHE: dict = {"key": "", "value": None}
_WEATHER_CACHE: dict = {}
_CACHE: dict = {}
_MISSING = object()


def _cache_get(key: str):
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return _MISSING


def _cache_set(key: str, value, ttl: float) -> None:
    _CACHE[key] = (time.time() + ttl, value)

_FALLBACK_QUOTES = [
    ("生活明朗，万物可爱。", "汪曾祺"),
    ("慢慢来，比较快。", "佚名"),
    ("愿你有前进一寸的勇气，也有后退一步的从容。", "佚名"),
    ("把日子过成自己喜欢的样子。", "佚名"),
    ("山高路远，看世界，也找自己。", "佚名"),
    ("今天也要好好吃饭，好好睡觉。", "佚名"),
]

DEFAULT_RECOMMEND_GAMES = [
    "黑神话：悟空|国产动作大作，战斗手感扎实",
    "塞尔达传说：王国之泪|开放世界探索，随便逛都能玩很久",
    "双人成行|双人合作解谜，适合和朋友一起",
]
DEFAULT_RECOMMEND_SOFTWARE = [
    "Everything|毫秒级本地文件搜索，装机必备",
    "PotPlayer|轻量全能播放器，格式支持很全",
    "7-Zip|开源压缩工具，干净无广告",
]
DEFAULT_RECOMMEND_MOVIES = [
    "流浪地球2|国产科幻，视效和故事都在线",
    "庆余年|古装权谋剧，适合连着追",
    "疯狂动物城|轻松合家欢，随时都能看",
]


# ==================== 网络数据 ====================


def _get(url: str, *, params=None, timeout: float = 8.0, stream: bool = False):
    if requests is None:
        raise RuntimeError("requests 未安装")
    return requests.get(url, params=params, timeout=timeout, stream=stream,
                        headers={"User-Agent": _UA, "Accept": "*/*"})


def fetch_bing_wallpaper(day_key: str = "", timeout: float = 10.0) -> Optional[dict]:
    """获取 Bing 当日壁纸，返回 {data_uri, title, copyright}。

    day_key 按天缓存，避免每次签到都重新下载。
    """
    day_key = day_key or date.today().isoformat()
    cached = _BING_CACHE.get("value")
    if _BING_CACHE.get("key") == day_key and cached:
        return cached
    try:
        meta = _get("https://www.bing.com/HPImageArchive.aspx",
                    params={"format": "js", "idx": 0, "n": 1, "mkt": "zh-CN"},
                    timeout=timeout).json()
        images = meta.get("images") or []
        if not images:
            return None
        item = images[0]
        path = item.get("url") or ""
        if not path and item.get("urlbase"):
            path = item["urlbase"] + "_1920x1080.jpg"
        if not path:
            return None
        if path.startswith("/"):
            path = "https://www.bing.com" + path
        elif not path.startswith("http"):
            path = "https://www.bing.com/" + path
        resp = _get(path, timeout=max(timeout, 12.0))
        raw = resp.content
        if not raw or len(raw) > 8 * 1024 * 1024:
            return None
        mime = "image/jpeg"
        if Image is not None:
            try:
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                if im.width > 1200:
                    im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=82, optimize=True)
                raw = buf.getvalue()
            except Exception:
                pass
        value = {
            "data_uri": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
            "title": (item.get("title") or "").strip(),
            "copyright": (item.get("copyright") or "").strip(),
        }
        _BING_CACHE.update({"key": day_key, "value": value})
        return value
    except Exception:
        return None


_WTTR_CN = {
    "sunny": "晴", "clear": "晴", "partly cloudy": "多云", "cloudy": "多云",
    "overcast": "阴", "mist": "薄雾", "fog": "雾", "haze": "霾",
    "light rain": "小雨", "moderate rain": "中雨", "heavy rain": "大雨",
    "light drizzle": "毛毛雨", "patchy rain possible": "可能有雨",
    "patchy rain nearby": "附近有雨", "thunderstorm": "雷阵雨",
    "light snow": "小雪", "moderate snow": "中雪", "heavy snow": "大雪",
    "blizzard": "暴雪", "sleet": "雨夹雪", "freezing fog": "冻雾",
}


def _weather_icon(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("雪", "snow", "sleet", "冻")):
        return "snow"
    if any(k in t for k in ("雷", "thunder", "雨", "rain", "drizzle", "shower")):
        return "rain"
    if any(k in t for k in ("雾", "fog", "mist", "霾", "haze", "沙", "dust")):
        return "fog"
    if any(k in t for k in ("风", "wind")):
        return "wind"
    if any(k in t for k in ("云", "cloud", "overcast", "阴")):
        return "cloud"
    return "sun"


def fetch_weather(city: str = "", timeout: float = 6.0) -> Optional[dict]:
    """获取实时天气。city 留空时由 UAPI 按服务器出口 IP 自动定位。"""
    cache_key = (city or "").strip() or "__auto__"
    cached = _WEATHER_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 1800:
        return cached[1]

    # 主源：UAPI（中文、免 Key）
    try:
        params = {"lang": "zh"}
        if cache_key != "__auto__":
            params["city"] = cache_key
        data = _get("https://uapis.cn/api/v1/misc/weather",
                    params=params, timeout=timeout).json()
        if data.get("weather") and data.get("temperature") is not None:
            value = {
                "ok": True,
                "city": (data.get("city") or data.get("district") or cache_key or "本地").strip(),
                "weather": str(data.get("weather") or ""),
                "temp": round(float(data.get("temperature"))),
                "humidity": data.get("humidity"),
                "wind": f"{data.get('wind_direction') or ''} {data.get('wind_power') or ''}".strip(),
                "report_time": str(data.get("report_time") or ""),
                "icon": _weather_icon(str(data.get("weather") or "")),
                "source": "UAPI",
            }
            _WEATHER_CACHE[cache_key] = (time.time(), value)
            return value
    except Exception:
        pass

    # 兜底：wttr.in（免 Key，英文描述本地翻译）
    try:
        loc = quote(cache_key) if cache_key != "__auto__" else ""
        data = _get(f"https://wttr.in/{loc}?format=j1&lang=zh", timeout=timeout).json()
        cc = (data.get("current_condition") or [{}])[0]
        desc_en = ((cc.get("weatherDesc") or [{}])[0].get("value") or "").strip()
        desc = _WTTR_CN.get(desc_en.lower(), desc_en or "未知")
        area = cache_key
        try:
            area = data["nearest_area"][0]["areaName"][0]["value"] or cache_key
        except Exception:
            pass
        value = {
            "ok": True,
            "city": area or "本地",
            "weather": desc,
            "temp": round(float(cc.get("temp_C") or 0)),
            "humidity": cc.get("humidity"),
            "wind": f"{cc.get('winddir16Point') or ''} {cc.get('windspeedKmph') or ''}km/h".strip(),
            "report_time": "",
            "icon": _weather_icon(desc + " " + desc_en),
            "source": "wttr.in",
        }
        _WEATHER_CACHE[cache_key] = (time.time(), value)
        return value
    except Exception:
        _WEATHER_CACHE[cache_key] = (time.time(), None)
        return None


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value or "")).strip()


def fetch_epic_free(timeout: float = 6.0) -> Optional[dict]:
    """Epic 当前限免游戏（喜加一）。"""
    cached = _cache_get("epic")
    if cached is not _MISSING:
        return cached
    try:
        data = _get(
            "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions",
            params={"locale": "zh-CN", "country": "CN", "allowCountries": "CN"},
            timeout=timeout,
        ).json()
        catalog = ((data.get("data") or {}).get("Catalog") or {})
        elements = ((catalog.get("searchStore") or {}).get("elements") or [])
        free = []
        for item in elements:
            if item.get("offerType") not in (None, "BASE_GAME", "BUNDLE"):
                continue
            offers = ((item.get("promotions") or {}).get("promotionalOffers") or [])
            if not offers:
                continue
            try:
                offer = offers[0]["promotionalOffers"][0]
                pct = (offer.get("discountSetting") or {}).get("discountPercentage")
                end = offer.get("endDate") or ""
            except Exception:
                continue
            if pct != 0:
                continue
            price = ((item.get("price") or {}).get("totalPrice") or {})
            title = (item.get("title") or "").strip()
            if not title:
                continue
            free.append({
                "title": title,
                "original": int(price.get("originalPrice") or 0),
                "currency": price.get("currencyCode") or "CNY",
                "end": end,
            })
        if not free:
            _cache_set("epic", None, 600)
            return None
        item = free[0]
        end_text = ""
        if item["end"]:
            try:
                dt = datetime.fromisoformat(item["end"].replace("Z", "+00:00"))
                end_text = f"{dt.month}月{dt.day}日"
            except Exception:
                end_text = ""
        if item["currency"] == "CNY" and item["original"] > 0:
            price_text = f"原价 ¥{item['original'] / 100:.0f} · 现价免费"
        else:
            price_text = "限时免费"
        value = {
            "ok": True, "kind": "epic", "title": item["title"],
            "price": price_text, "end": end_text, "count": len(free),
        }
        _cache_set("epic", value, 1800)
        return value
    except Exception:
        _cache_set("epic", None, 300)
        return None


def fetch_history_today(day: date, timeout: float = 6.0) -> Optional[dict]:
    """百度百科「历史上的今天」。"""
    cache_key = f"history:{day.isoformat()}"
    cached = _cache_get(cache_key)
    if cached is not _MISSING:
        return cached
    try:
        data = _get(
            f"https://baike.baidu.com/cms/home/eventsOnHistory/{day.month:02d}.json",
            timeout=timeout,
        ).json()
        month = data.get(str(day.month)) or data.get(f"{day.month:02d}") or {}
        day_key = f"{day.month:02d}{day.day:02d}"
        items = month.get(day_key) or month.get(f"{day.month}{day.day}") or []
        events = []
        for item in items:
            text = _strip_tags(item.get("title"))
            year = str(item.get("year") or "").strip()
            if year and len(text) >= 6:
                events.append({"year": year, "text": text})
            if len(events) >= 2:
                break
        if not events:
            _cache_set(cache_key, None, 600)
            return None
        value = {"ok": True, "kind": "history", "events": events,
                 "date": f"{day.month}月{day.day}日"}
        _cache_set(cache_key, value, 21600)
        return value
    except Exception:
        _cache_set(cache_key, None, 600)
        return None


def fetch_poem(timeout: float = 5.0) -> Optional[dict]:
    """今日诗词（jinrishici）。"""
    key = f"poem:{date.today().isoformat()}"
    cached = _cache_get(key)
    if cached is not _MISSING:
        return cached
    try:
        data = _get("https://v2.jinrishici.com/one.json", timeout=timeout).json()
        body = data.get("data") or {}
        content = (body.get("content") or "").strip()
        if not content:
            return None
        origin = body.get("origin") or {}
        source = "·".join(x for x in (origin.get("dynasty"), origin.get("author")) if x)
        if origin.get("title"):
            source += f"《{origin['title']}》"
        value = {"ok": True, "kind": "poem", "text": content,
                 "from": source or "今日诗词"}
        _cache_set(key, value, 21600)
        return value
    except Exception:
        _cache_set(key, None, 600)
        return None


INFO_MODULES = ("epic", "history", "poem", "weather", "off")


def fetch_info(module: str, day: date, city: str = "",
               timeout: float = 6.0) -> Optional[dict]:
    """按配置获取左下角信息模块；失败的模块会降级到诗词/历史。"""
    module = (module or "epic").strip().lower()
    if module not in INFO_MODULES:
        module = "epic"
    if module == "off":
        return None
    if module == "weather":
        return fetch_weather(city, timeout)
    if module == "history":
        return fetch_history_today(day, timeout) or fetch_poem(timeout)
    if module == "poem":
        return fetch_poem(timeout) or fetch_history_today(day, timeout)
    # epic（默认）：接口失败时依次降级到诗词、历史
    return (fetch_epic_free(timeout) or fetch_poem(timeout)
            or fetch_history_today(day, timeout))


def fetch_hitokoto(timeout: float = 5.0) -> dict:
    """获取每日一言；失败时使用内置句子。"""
    key = f"hitokoto:{date.today().isoformat()}"
    cached = _cache_get(key)
    if cached is not _MISSING:
        return cached
    try:
        data = _get("https://v1.hitokoto.cn/",
                    params=[("encode", "json"), ("charset", "utf-8"),
                            ("c", "d"), ("c", "i")],
                    timeout=timeout).json()
        text = (data.get("hitokoto") or "").strip()
        if text:
            value = {
                "text": text,
                "from": (data.get("from_who") or data.get("from") or "").strip(),
            }
            _cache_set(key, value, 86400)
            return value
    except Exception:
        pass
    text, source = random.choice(_FALLBACK_QUOTES)
    value = {"text": text, "from": source}
    _cache_set(key, value, 300)
    return value


# ==================== 推荐 ====================


def _parse_items(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [x for x in re.split(r"[\n,，;；]+", raw) if x.strip()]
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            desc = str(item.get("desc") or "").strip()
            query = str(item.get("query") or name).strip()
            if name:
                out.append({"name": name, "desc": desc, "query": query or name})
            continue
        s = str(item or "").strip()
        if not s:
            continue
        parts = re.split(r"[|｜]", s, maxsplit=1)
        name = parts[0].strip()
        desc = parts[1].strip() if len(parts) > 1 else ""
        if name:
            out.append({"name": name, "desc": desc, "query": name})
    return out


_REC_KINDS = (
    ("movie", "影视", "movie", "找影视"),
    ("game", "游戏", "gamepad", "找游戏"),
    ("software", "软件", "apps", "找软件"),
)


def pick_recommendations(games, software, movies, day: date) -> list[dict]:
    """每天从三个清单里各挑一个（按日期轮换，同一天所有用户看到的一致）。"""
    pools = {"game": games, "software": software, "movie": movies}
    ordinal = day.toordinal()
    result = []
    for kind, label, icon, cmd in _REC_KINDS:
        pool = _parse_items(pools.get(kind))
        if not pool:
            continue
        item = pool[ordinal % len(pool)]
        result.append({
            "kind": kind,
            "label": label,
            "icon": icon,
            "cmd": cmd,
            "name": item["name"],
            "desc": item["desc"],
            "query": item.get("query") or item["name"],
        })
    return result


def recommendation_text(recs: list[dict]) -> str:
    """给纯文本兜底用的一行推荐。"""
    if not recs:
        return ""
    parts = [f"{r['label']}《{r['name']}》（/{r['cmd']} {r.get('query') or r['name']}）" for r in recs]
    return "今日推荐：" + " · ".join(parts)


# ==================== HTML ====================


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


_CSS = """
@font-face{font-family:'reportfont';src:url('report.otf') format('opentype');font-weight:normal;font-display:swap}
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:'Noto Sans SC','PingFang SC','Microsoft YaHei','reportfont','Noto Sans CJK SC',sans-serif;
  background:#f5f4f0;color:#1a1a1a;line-height:1.6;
  -webkit-font-smoothing:antialiased;letter-spacing:.02em;
}
.page{
  padding:24px 16px 28px;
  background:
    radial-gradient(ellipse 80% 50% at 50% 0%,rgba(249,240,216,.55),transparent 70%),
    linear-gradient(rgba(0,0,0,.032) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,0,0,.032) 1px,transparent 1px),
    #f5f4f0;
  background-size:auto,32px 32px,32px 32px,auto;
}
.sheet{max-width:688px;margin:0 auto;background:#fff;border:1px solid #e8e8e8;border-radius:24px;
  overflow:hidden;box-shadow:0 1px 2px rgba(0,0,0,.04),0 18px 48px rgba(0,0,0,.07)}
.hero{position:relative;height:292px;background:#2a2a2a center/cover no-repeat;color:#fff}
.hero.no-photo{background:linear-gradient(135deg,#1f1f1f 0%,#3a362c 58%,#7a6a3a 100%)}
.hero::after{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(0,0,0,.10) 0%,rgba(0,0,0,.22) 38%,rgba(0,0,0,.78) 100%)}
.hero-in{position:relative;z-index:2;height:100%;padding:22px 26px;display:flex;flex-direction:column;justify-content:space-between}
.hero-top{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:14px}
.brand{display:inline-flex;align-items:center;gap:7px;padding:6px 11px;border:1px solid rgba(255,255,255,.35);
  border-radius:999px;background:rgba(255,255,255,.13);font-weight:600;letter-spacing:.04em}
.hero-date{color:rgba(255,255,255,.82);white-space:nowrap}
.hero-main{display:flex;align-items:flex-end;justify-content:space-between;gap:18px}
.status{font-size:15px;font-weight:600;letter-spacing:.06em;color:#ffe28a;margin-bottom:7px}
.earn{font-size:56px;font-weight:800;line-height:.95;letter-spacing:-.04em;font-style:italic;color:#ffe28a;text-shadow:0 2px 22px rgba(255,226,138,.35)}
.earn small{font-size:18px;font-weight:700;letter-spacing:0;margin-left:8px;font-style:normal;color:rgba(255,255,255,.92)}
.earn.muted{font-size:34px;font-weight:700;font-style:normal;letter-spacing:.02em;color:#fff;text-shadow:none}
.sub{margin-top:10px;font-size:15px;color:rgba(255,255,255,.82)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid #f0f0f0}
.stat{padding:17px 22px;border-right:1px solid #f0f0f0}
.stat:last-child{border-right:none}
.stat .k{font-size:14px;color:#888}
.stat .v{margin-top:2px;font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1.3}
.stat .v small{font-size:14px;font-weight:500;color:#888;margin-left:3px}
.section{padding:22px 24px 0}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:11px}
.sec-head h2{font-size:19px;font-weight:700;letter-spacing:-.01em}
.sec-head span{font-size:14px;color:#999;white-space:nowrap}
.rec-list{display:flex;flex-direction:column;gap:8px}
.rec{display:grid;grid-template-columns:44px minmax(0,1fr) auto;align-items:center;gap:12px;
  padding:10px 12px;border:1px solid #efefef;border-radius:14px;background:#fcfcfb}
.rec-icon{width:44px;height:44px;display:flex;align-items:center;justify-content:center;
  border-radius:12px;background:#f9f0d8;color:#1a1a1a}
.rec-body{min-width:0}
.rec-kind{font-size:14px;color:#8a7a45;font-weight:600;letter-spacing:.05em;line-height:1.2}
.rec-name{font-size:17px;font-weight:600;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rec-desc{font-size:14px;color:#8a8a8a;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rec-cmd{font-family:'SF Mono','Cascadia Code',Consolas,monospace;font-size:14px;color:#1a1a1a;
  background:#fff;border:1px solid #e4e4e4;border-radius:999px;padding:5px 10px;white-space:nowrap;
  max-width:250px;overflow:hidden;text-overflow:ellipsis}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:20px 24px 0}
.panel{border-radius:16px;padding:15px 16px 14px;border:1px solid #ececec;background:#fafaf8;min-width:0;display:flex;flex-direction:column}
.panel.dark{background:#1a1a1a;border-color:#1a1a1a;color:#fff}
.panel-head{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:600;color:#666;min-width:0}
.panel.dark .panel-head{color:#ffe28a}
.panel-head .city{margin-left:auto;font-weight:400;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.weather-main{display:flex;align-items:center;gap:13px;margin-top:7px}
.temp{font-size:40px;font-weight:700;line-height:1;letter-spacing:-.03em}
.wx{min-width:0}
.wx .cond{font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wx .meta{font-size:14px;color:#8a8a8a;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.weather-foot{margin-top:auto;padding-top:7px;font-size:14px;color:#aaa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.info-title{margin-top:8px;font-size:18px;font-weight:700;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.info-desc{margin-top:4px;font-size:15px;font-weight:600;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.info-meta{margin-top:auto;padding-top:6px;font-size:14px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.history-list{display:flex;flex-direction:column;gap:7px;margin-top:9px}
.history-row{display:flex;gap:8px;align-items:flex-start;font-size:15px;line-height:1.5}
.history-year{flex:0 0 auto;font-size:14px;font-weight:700;color:#8a7a45;padding-top:1px}
.history-text{color:#333;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.poem-text{margin-top:9px;font-size:17px;font-weight:500;line-height:1.7;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.info-from{margin-top:auto;padding-top:8px;text-align:right;font-size:14px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.quote-text{margin-top:9px;font-size:17px;font-weight:500;line-height:1.6;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.quote-text::before{content:"\\201C";color:#ffe28a}
.quote-text::after{content:"\\201D";color:#ffe28a}
.quote-from{margin-top:auto;padding-top:8px;text-align:right;font-size:14px;color:rgba(255,255,255,.62)}
.foot{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:18px 24px 10px;font-size:14px;color:#999}
.foot .cmd{font-family:'SF Mono','Cascadia Code',Consolas,monospace;color:#555;white-space:nowrap}
.source{padding:0 24px 18px;font-size:14px;color:#b3b3b3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
"""


def build_checkin_html(
    *,
    user_name: str,
    date_label: str,
    weekday: str,
    earned: int,
    bonus: int,
    streak: int,
    balance: int,
    duplicate: bool,
    wallpaper: Optional[dict],
    info: Optional[dict],
    quote_data: dict,
    recommendations: list[dict],
    info_module: str = "epic",
) -> str:
    """拼出签到卡片 HTML（所有图片均已内联，离线可渲染）。"""
    wallpaper = wallpaper or {}
    quote_data = quote_data or {}
    recs = recommendations or []
    who = (user_name or "").strip()
    if len(who) > 12:
        who = who[:12] + "…"
    greeting = f"{_e(who)}，" if who else ""

    hero_style = ""
    hero_class = "hero no-photo"
    if wallpaper.get("data_uri"):
        hero_class = "hero"
        hero_style = f" style=\"background-image:url('{wallpaper['data_uri']}')\""

    if duplicate:
        status = "今天已签到"
        earn_html = '<div class="earn muted">明天再来</div>'
        hero_sub = f"{greeting}已连续签到 {streak} 天 · 当前 {balance} 积分"
    else:
        status = "签到成功"
        earn_html = f'<div class="earn">+{earned}<small>积分</small></div>'
        extra = f" · 连续加成 +{bonus}" if bonus else ""
        hero_sub = f"{greeting}已连续签到 {streak} 天{extra}"

    # 左下信息模块：Epic 喜加一 / 历史上的今天 / 今日诗词 / 天气 / 关闭
    info = info or {}
    info_module = (info_module or "epic").strip().lower()
    kind = info.get("kind") or ("weather" if info_module == "weather" else "")
    if info_module == "off":
        info_panel = ""
    elif kind == "weather" and info.get("ok"):
        wind = info.get("wind") or ""
        humidity = info.get("humidity")
        meta_bits = []
        if humidity not in (None, ""):
            meta_bits.append(f"湿度 {humidity}%")
        if wind:
            meta_bits.append(str(wind))
        meta = " · ".join(meta_bits) or "实时天气"
        body_html = f"""
      <div class="weather-main">
        <div class="temp">{int(info.get('temp', 0))}°</div>
        <div class="wx">
          <div class="cond">{_e(info.get('weather'))}</div>
          <div class="meta">{_e(meta)}</div>
        </div>
      </div>
      <div class="weather-foot">{_e(info.get('report_time') or '实时天气')}</div>"""
        info_panel = f"""
    <div class="panel">
      <div class="panel-head">{svg(info.get('icon', 'sun'), 17)} 天气<span class="city">{_e(info.get('city') or '本地')}</span></div>{body_html}
    </div>"""
    elif kind == "weather":
        info_panel = f"""
    <div class="panel">
      <div class="panel-head">{svg('cloud', 17)} 天气<span class="city">未获取</span></div>
      <div class="weather-main">
        <div class="temp">--</div>
        <div class="wx">
          <div class="cond">暂不可用</div>
          <div class="meta">天气服务暂时没有响应</div>
        </div>
      </div>
      <div class="weather-foot">稍后再试即可</div>
    </div>"""
    elif kind == "epic" and info.get("ok"):
        end_txt = f"截止 {info['end']} · " if info.get("end") else ""
        info_panel = f"""
    <div class="panel">
      <div class="panel-head">{svg('package', 17)} Epic 喜加一<span class="city">限时免费</span></div>
      <div class="info-title">{_e(info.get('title'))}</div>
      <div class="info-desc">{_e(info.get('price'))}</div>
      <div class="info-meta">{_e(end_txt)}Epic 商店可领取</div>
    </div>"""
    elif kind == "history" and info.get("events"):
        rows = "".join(
            f'<div class="history-row"><span class="history-year">{_e(ev.get("year"))}</span>'
            f'<span class="history-text">{_e(ev.get("text"))}</span></div>'
            for ev in info["events"][:2]
        )
        info_panel = f"""
    <div class="panel">
      <div class="panel-head">{svg('event', 17)} 历史上的今天<span class="city">{_e(info.get('date') or '')}</span></div>
      <div class="history-list">{rows}</div>
    </div>"""
    elif kind == "poem" and info.get("text"):
        info_panel = f"""
    <div class="panel">
      <div class="panel-head">{svg('book', 17)} 今日诗词<span class="city">每日一首</span></div>
      <div class="poem-text">{_e(info.get('text'))}</div>
      <div class="info-from">—— {_e(info.get('from'))}</div>
    </div>"""
    else:
        info_panel = f"""
    <div class="panel">
      <div class="panel-head">{svg('sun', 17)} 今日内容</div>
      <div class="info-title" style="color:#999;font-weight:500">今天没有额外内容</div>
      <div class="info-meta">明天再来看看</div>
    </div>"""

    quote_text = _e(quote_data.get("text") or "今天也要好好生活。")
    quote_from = _e(quote_data.get("from") or "一言")

    quote_style = "" if info_panel else ' style="grid-column:1/-1"'

    # 推荐
    rec_html = ""
    if recs:
        rows = []
        for r in recs:
            cmd = f"/{r['cmd']} {r.get('query') or r['name']}"
            rows.append(f"""
      <div class="rec">
        <div class="rec-icon">{svg(r['icon'], 23)}</div>
        <div class="rec-body">
          <div class="rec-kind">{_e(r['label'])}</div>
          <div class="rec-name">{_e(r['name'])}</div>
          <div class="rec-desc">{_e(r['desc'] or '回复下方命令即可搜索')}</div>
        </div>
        <div class="rec-cmd">{_e(cmd)}</div>
      </div>""")
        rec_html = f"""
  <div class="section">
    <div class="sec-head"><h2>今天可以看看</h2><span>回复命令即可搜索</span></div>
    <div class="rec-list">{''.join(rows)}
    </div>
  </div>"""

    credit = "Bing 每日壁纸" if wallpaper.get("data_uri") else "暮黎资源 · 每日签到"
    if wallpaper.get("data_uri") and wallpaper.get("copyright"):
        credit += " · " + str(wallpaper["copyright"])[:46]

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>暮黎资源 · 每日签到</title>
<style>{_CSS}</style></head>
<body>
<div class="page">
<div class="sheet">
  <div class="{hero_class}"{hero_style}>
    <div class="hero-in">
      <div class="hero-top">
        <span class="brand">{svg('calendar-check', 16)} 暮黎资源 · 每日签到</span>
        <span class="hero-date">{_e(date_label)} · {_e(weekday)}</span>
      </div>
      <div class="hero-main">
        <div>
          <div class="status">{status}</div>
          {earn_html}
          <div class="sub">{hero_sub}</div>
        </div>
      </div>
    </div>
  </div>

  <div class="stats">
    <div class="stat"><div class="k">今日获得</div><div class="v">+{int(earned)}<small>积分</small></div></div>
    <div class="stat"><div class="k">当前积分</div><div class="v">{int(balance)}</div></div>
    <div class="stat"><div class="k">连续签到</div><div class="v">{int(streak)}<small>天</small></div></div>
  </div>{rec_html}

  <div class="duo">{info_panel}
    <div class="panel dark"{quote_style}>
      <div class="panel-head">{svg('quote', 17)} 每日一言</div>
      <div class="quote-text">{quote_text}</div>
      <div class="quote-from">—— {quote_from}</div>
    </div>
  </div>

  <div class="foot">
    <span>{svg('check', 15)} 每天 0 点刷新签到</span>
    <span class="cmd">/签到 领积分 · /积分 查余额</span>
  </div>
  <div class="source">{_e(credit)}</div>
</div>
</div>
</body></html>"""


def render_checkin_png(html_text: str, font_path: str = "", width: int = 720,
                       channel: str = "", exe: str = "", scale: int = 2) -> Optional[bytes]:
    """用 Playwright 渲染签到卡片，只截取 .page 区域，避免固定视口留下大片空白。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    tmpdir = tempfile.mkdtemp(prefix="checkin_card_")
    html_path = os.path.join(tmpdir, "checkin.html")
    try:
        if font_path and os.path.exists(font_path):
            shutil.copyfile(font_path, os.path.join(tmpdir, "report.otf"))
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
            try:
                page = browser.new_page(viewport={"width": width, "height": 900},
                                        device_scale_factor=scale)
                page.goto("file://" + html_path, wait_until="load")
                page.wait_for_timeout(500)
                try:
                    return page.locator(".page").screenshot(type="jpeg", quality=88)
                except Exception:
                    return page.screenshot(full_page=True, type="jpeg", quality=88)
            finally:
                browser.close()
    except Exception:
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

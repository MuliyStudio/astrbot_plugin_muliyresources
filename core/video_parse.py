# -*- coding: utf-8 -*-
"""视频平台链接解析（爱奇艺 / 腾讯视频 / 优酷 / 芒果TV / 乐视视频 / 搜狐视频）

功能
----
1. 识别聊天中分享的上述平台视频链接（含 QQ 分享卡片 [CQ:json]）；
2. 真实可播放「直链」优先由影视站 VIP 解析（教父.com /zjx）产出，见
   core/muliy_site.py 的 parse_vip_url——它复用影视搜索的登录会话与域名，
   把链接提交到该站解析页还原出 .m3u8 / .mp4；
3. 本模块的 parse_video_url 作为兜底：当 VIP 解析不可用（未配置影视账号 /
   解析页未返回直链）时，抓取分享页 OpenGraph 元数据（标题/简介/封面），
   返回规范化的播放页地址。

关于「直链」的说明（重要）
-------------------------
VIP 解析成功时，返回的「直链」是真实可播放流（.m3u8 / .mp4）的规范化地址。
若 VIP 解析不可用，则退回 OG 播放页地址（点击即可在 App / 网页观看），
因为主流平台真实流签名与 IP、时效绑定，后端无法稳定自行还原。
标题 / 简介 / 封面 优先用分享卡片自带字段，缺失时由 OG 标签补充，**无需登录**。

依赖：requests（插件已依赖）。
"""
import json
import logging
import re
import html as _html
from urllib.parse import urlparse, urljoin

import requests

logger = logging.getLogger("astrbot_plugin_muliyresources.video_parse")

_VIDEO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 平台注册表：key -> {name, domains}
PLATFORMS = {
    "iqiyi": {"name": "爱奇艺", "domains": ("iqiyi.com",)},
    "qq": {"name": "腾讯视频", "domains": ("v.qq.com", "qq.com")},
    "youku": {"name": "优酷", "domains": ("youku.com",)},
    "mgtv": {"name": "芒果TV", "domains": ("mgtv.com",)},
    "le": {"name": "乐视视频", "domains": ("le.com", "letv.com")},
    "sohu": {"name": "搜狐视频", "domains": ("sohu.com", "tv.sohu.com", "my.tv.sohu.com")},
}


def _unescape(s: str) -> str:
    """HTML 实体反转义 + 去首尾空白。"""
    if not s:
        return ""
    return _html.unescape(s).strip()


def _host_of(url: str) -> str:
    """返回去除 www. 的小写主机名。"""
    h = (urlparse(url).netloc or "").lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def detect_video_url(text: str):
    """从文本中提取第一个受支持的视频平台链接。

    返回 (platform_key, url) 或 None。
    同时处理 URL 编码的链接（如 ``http%3A%2F%2F...``）。
    """
    if not text:
        return None
    import urllib.parse as _up
    # 抽取所有 http(s) 链接（遇到常见标点/空白截断）
    urls = re.findall(r"https?://[^\s，。、）)】\]\"'<>]+", text)
    # 也抽取 URL 编码的链接（如 http%3A%2F%2Fwww.iqiyi.com%2F...）
    enc_urls = re.findall(r"https?%3A%2F%2F[^\s\"'，。、）)】\]<>]+", text, re.I)
    for eu in enc_urls:
        decoded = _up.unquote(eu)
        if decoded not in urls:
            urls.append(decoded)
    for u in urls:
        h = _host_of(u)
        for key, info in PLATFORMS.items():
            for d in info["domains"]:
                if h == d or h.endswith("." + d):
                    return (key, u)
    return None


def extract_video_from_miniapp(jdata):
    """从 QQ 视频分享卡片（[CQ:json] 段）中提取第一个受支持平台的视频链接及卡片自带信息。

    分享卡片里真实的视频链接通常在 ``meta.news.jumpUrl`` 等字段，而不是出现在
    ``event.message_str`` 纯文本中（此时文本为空 / ``[ComponentType.Json]``）。
    本函数对整段 JSON 字符串做链接扫描（最稳，覆盖任意字段），并额外把卡片自带的
    ``title`` / ``desc`` / ``preview`` 一并取出，作为解析结果的高质量兜底。

    返回 ``{"platform_key", "url", "title", "desc", "cover"}`` 或 None。
    """
    if not jdata:
        return None
    # 兼容 dict / str 输入（Json 组件的 data 可能是已解析 dict，也可能是 JSON 字符串）
    if isinstance(jdata, dict):
        try:
            jstr = json.dumps(jdata, ensure_ascii=False)
        except Exception:
            jstr = str(jdata)
    else:
        jstr = str(jdata)

    # 1) 整串扫描链接（最稳，覆盖 jumpUrl 等任意字段，且能识别平台）
    hit = detect_video_url(jstr)
    url = hit[1] if isinstance(hit, tuple) else ""

    # 2) 结构化字段（兜底，仅当整串没扫到链接时再用）
    title = desc = cover = ""
    try:
        data = json.loads(jstr) if isinstance(jstr, str) else jstr
    except Exception:
        data = None
    if isinstance(data, dict):
        meta = data.get("meta") or {}
        news = meta.get("news") or {}
        # 卡片自带信息（爱奇艺 / 腾讯视频 / 优酷 等分享卡片典型字段）
        title = news.get("title") or data.get("title") or ""
        desc = news.get("desc") or data.get("desc") or data.get("description") or ""
        cover = (
            news.get("preview")
            or news.get("picture")
            or news.get("image")
            or data.get("preview")
            or ""
        )
        if not url:
            for node in (news, meta.get("detail_1") or {}, meta.get("video") or {}, data):
                if not isinstance(node, dict):
                    continue
                for f in ("jumpUrl", "url", "qqdocurl", "targetUrl", "link", "shareUrl"):
                    v = node.get(f)
                    if isinstance(v, str) and detect_video_url(v):
                        url = detect_video_url(v)[1]
                        break
                if url:
                    break

    if not url:
        return None
    # URL 解码（卡片里的链接可能是 URL 编码的，如 http%3A%2F%2F...）
    import urllib.parse as _up
    url = _up.unquote(url)
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    platform_key = hit[0] if isinstance(hit, tuple) else (detect_video_url(url) or (None,))[0]
    if not platform_key:
        return None
    return {
        "platform_key": platform_key,
        "url": url,
        "title": _unescape(title) if isinstance(title, str) else "",
        "desc": _unescape(desc) if isinstance(desc, str) else "",
        "cover": cover if isinstance(cover, str) else "",
    }


def extract_video_id(url: str, platform_key: str) -> str:
    """尽力从 URL 中抠出视频 id（用于结构化展示，非必需）。"""
    if not url or not platform_key:
        return ""
    try:
        if platform_key == "iqiyi":
            m = re.search(r"[/_](?:v|w|a|play)_[a-zA-Z0-9_]+", url)
            return m.group(0).lstrip("/_") if m else ""
        if platform_key == "qq":
            # /x/cover/xxxx/vid.html 或直接 /x/page/vid.html
            m = re.search(r"/([a-zA-Z0-9]+)\.html", url)
            return m.group(1) if m else ""
        if platform_key == "youku":
            m = re.search(r"id_([a-zA-Z0-9=]+)", url)
            return m.group(1) if m else ""
        if platform_key == "mgtv":
            m = re.search(r"/b/(\d+)/(\d+)", url) or re.search(r"/h/(\d+)/(\d+)", url)
            return "/".join(m.groups()) if m else ""
        if platform_key in ("le", "sohu"):
            m = re.search(r"/(\d+)\.html", url) or re.search(r"vplay/(\d+)", url)
            return m.group(1) if m else ""
    except Exception:
        pass
    return ""


def _abs_url(base_url: str, maybe_rel: str) -> str:
    if not maybe_rel:
        return ""
    if maybe_rel.startswith("http://") or maybe_rel.startswith("https://"):
        return maybe_rel
    try:
        return urljoin(base_url, maybe_rel)
    except Exception:
        return maybe_rel


def _meta_content(html: str, prop: str) -> str:
    """从 HTML 中取 <meta property=prop content=...> 或 <meta name=prop ...>，失败返回空。"""
    # property 在前、content 在后
    m = re.search(
        r'<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % re.escape(prop),
        html, re.I)
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']%s["\']' % re.escape(prop),
            html, re.I)
    if m:
        return _unescape(m.group(1))
    # name= 形式（用于 description）
    m = re.search(
        r'<meta[^>]+name=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % re.escape(prop),
        html, re.I)
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']%s["\']' % re.escape(prop),
            html, re.I)
    if m:
        return _unescape(m.group(1))
    return ""


def parse_video_url(url: str) -> dict:
    """解析视频链接，返回结构化信息字典。

    返回字段：platform_key, platform, url, title, desc, cover, vid
    抓取/解析失败时对应字段留空，不会抛异常。
    """
    detected = detect_video_url(url)
    platform_key = detected[0] if isinstance(detected, tuple) else ""
    info = {
        "platform_key": platform_key,
        "platform": PLATFORMS.get(platform_key, {}).get("name", "未知平台") if platform_key else "未知平台",
        "url": url,
        "title": "",
        "desc": "",
        "cover": "",
        "vid": "",
    }
    if not platform_key:
        return info

    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": _VIDEO_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            timeout=15, verify=False)
        # ⚠️ 关键：requests 在响应未声明 charset 时默认按 ISO-8859-1(latin1) 解码，
        # 而爱奇艺等页面是 UTF-8，直接 r.text 会把中文解成 ç­å¥èº 这类乱码。
        # 一律按 UTF-8 解码（失败用 replace 兜底），从根上消除乱码。
        html = r.content.decode("utf-8", "replace") or ""
    except Exception as e:
        logger.warning(f"[video_parse] 抓取失败 {url}: {e}")
        return info

    title = _meta_content(html, "og:title")
    desc = _meta_content(html, "og:description")
    if not desc:
        desc = _meta_content(html, "description")
    cover = _meta_content(html, "og:image")
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        if m:
            title = _unescape(m.group(1))

    # 平台首页 boilerplate（如爱奇艺播放页 OG 常掉到首页标题「爱奇艺-在线视频网站-海量正版高清视频在线观看」）
    # 这种标题不是具体视频名，留着反而误导，清空让上层回退到卡片标题 / 「未获取到标题」。
    if title and _is_homepage_title(title, platform_key):
        title = ""

    info["title"] = title
    info["desc"] = desc
    info["cover"] = _abs_url(url, cover)
    info["vid"] = extract_video_id(url, platform_key)
    return info


_HOME_BOILER = {
    "iqiyi": ("在线视频网站", "海量正版"),
    "qq": ("腾讯视频",),
    "youku": ("优酷",),
    "mgtv": ("芒果tv", "芒果TV"),
    "le": ("乐视",),
    "sohu": ("搜狐",),
}


def _is_homepage_title(title: str, platform_key: str) -> bool:
    """粗判 title 是否为平台首页 boilerplate（而非具体视频标题）。"""
    t = title.strip()
    if not t:
        return False
    keys = _HOME_BOILER.get(platform_key)
    if not keys:
        return False
    return all(k in t for k in keys) or t == "爱奇艺-在线视频网站-海量正版高清视频在线观看"


def format_video_info(info: dict) -> str:
    """把解析结果格式化为一条结构化聊天文本。"""
    lines = []
    lines.append(f"🎞️ {info.get('platform', '视频')} 解析结果")
    lines.append("=" * 32)
    title = info.get("title") or "（未获取到标题）"
    lines.append(f"📺 标题：{title}")
    desc = info.get("desc") or ""
    if desc:
        # 简介过长截断
        desc = desc if len(desc) <= 200 else desc[:200] + "…"
        lines.append(f"📝 简介：{desc}")
    lines.append(f"🔗 直链：{info.get('url', '')}")
    lines.append("")
    lines.append("（直链为视频播放页地址，点击即可在 App / 网页观看）")
    return "\n".join(lines)

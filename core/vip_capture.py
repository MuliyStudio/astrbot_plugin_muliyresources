"""VIP 解析 —— 基于「影视解析页」接口集合 + 浏览器播放器检测（交互式选接口）。

设计要点（按用户最新要求）：
- 直接使用用户提供的「影视解析页」接口集合（与 https://www.xn--wcv59z.com/zjx
  下拉框里的接口一致），每个接口带名字，展示给用户自己挑。
- 完整流程：
    1) 识别消息里的 VIP 视频链接（含爱奇艺分享卡片 playShare.html?shareId=）；
    2) 用浏览器加载链接，尽力把分享卡片转换为纯净播放页 v_xxx.html，
       同时抓取影视标题 / 简介 / 截图；
    3) 向用户展示命名接口菜单，让用户回复序号选择；
    4) 用户选好后，加载该接口播放直链，检测是否真渲染出可播放的
       <video>/<iframe> 播放器，返回「聊天记录格式」结果（标题+简介+截图+直链）。
- 不做 HLS 代理 / VLC 备选（按用户要求删除）。
- 直连失败时自动套用环境代理（Chromium 不会读 HTTP(S)_PROXY 环境变量，需显式传入）。

对外接口：
    is_vip_video_url(text) -> str | None
    analyze_vip_link(url, proxy="", timeout_ms=20000, channel="", exe="") -> dict
    build_interface_link(template, video_url) -> str
    verify_interface_playable(url, proxy="", timeout_ms=20000, channel="", exe="") -> dict
    VIP_INTERFACES  # [(名字, 模板), ...]
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import tempfile
import urllib.parse
from collections import Counter
from contextlib import asynccontextmanager

logger = logging.getLogger("astrbot_plugin_muliyresources.vip_capture")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ───────────────────────────────────────────────────────────────────────────
# 解析接口表（与影视解析页 /zjx 下拉框的接口一致，顺序即展示顺序）
# 模板已自带参数（?url= 或 ?jx=），拼接时直接把编码后的视频地址接在末尾。
# ───────────────────────────────────────────────────────────────────────────
VIP_INTERFACES: list[tuple[str, str]] = [
    ("虾米", "https://jx.xmflv.com/?url="),
    ("M1907", "https://im1907.top/?jx="),
    ("七哥", "https://jx.nnxv.cn/tv.php?url="),
    ("咸鱼", "https://jx.xymp4.cc/?url="),
    ("极速", "https://jx.2s0.cn/player/?url="),
    ("PlayerJY", "https://jx.playerjy.com/?url="),
    ("789", "https://jx.789jiexi.com/?url="),
    ("fongmi", "https://json.fongmi.cc/web?url="),
    ("花旗", "https://www.huaqi.live/?url="),
    ("937", "https://bfq.937auth.vip?url="),
]



# 常见 VIP / 付费视频平台域名（用于识别消息中的视频链接）
VIP_HOST_KEYWORDS = (
    "iqiyi.com", "v.qq.com", "youku.com", "tudou.com", "mgtv.com",
    "tv.sohu.com", "le.com", "letv.com", "bilibili.com", "pptv.com",
    "wasu.com", "1905.com", "cntv.cn", "cctv.com", "qy.net",
)


# ───────────────────────────────────────────────────────────────────────────
# 链接识别
# ───────────────────────────────────────────────────────────────────────────
def _extract_cq_urls(text: str) -> list[str]:
    """从 [CQ:json] / [CQ:share] / [CQ:xml] 卡片里解出跳转 URL。

    QQ 分享卡片（爱奇艺/腾讯/优酷等）通常是 ``[CQ:json,data=<URL编码的JSON>]``，
    data 里带 ``jumpUrl`` / ``url`` / ``playUrl`` 等字段；这些字段在 CQ 码里是
    URL 编码的，且 JSON 内部的值也是 URL，需要解码后才能被常规 URL 正则识别。
    兼容两种编码：data 为 URL 编码（生产环境），或含 CQ 转义（``,`` / ``&`` / ``[`` / ``]``）。
    """
    out: list[str] = []
    # 解码后的文本里取 URL：遇到空白/引号/“>”/逗号/“}”/“]”即停止，
    # 这样 JSON 里的 "jumpUrl":"https://..." 与 [CQ:share,url=...,title=...]
    # 都能精确截到链接本身，而不会贪婪吞掉后面的 JSON 字段。
    url_find = re.compile(r"https?://[^\s\"'>,}\]]+")
    for m in re.finditer(r"\[CQ:(\w+)(?:,([^\]]*))?\]", text):
        params = m.group(2) or ""
        for key in ("data", "url", "xml"):
            # data 通常是卡片里最后一个参数，直接取到卡片结尾（params 不含 ']'）
            pm = re.search(key + r"=(.+?)(?=\]|\Z)", params)
            if not pm:
                continue
            raw = urllib.parse.unquote(pm.group(1))
            # 兼容 CQ 码转义（只有未做 URL 编码时才会残留）
            raw = (raw.replace("\\,", ",").replace("\\&", "&")
                       .replace("\\[", "[").replace("\\]", "]"))
            out += url_find.findall(raw)
            # 处理 URL 编码的链接（如 http%3A%2F%2Fwww.iqiyi.com%2F...）
            enc_find = re.compile(r"https?%3A%2F%2F[^\s\"'，。、；;]+", re.I)
            for m in enc_find.finditer(raw):
                out.append(urllib.parse.unquote(m.group(0)))
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _extract_json_urls(text: str) -> list[str]:
    """从 JSON 对象字符串（如 ComponentType.Json 的 data）里提取 URL。

    先尝试读取常见字段 ``jumpUrl`` / ``url`` / ``playUrl`` / ``videoUrl`` / ``appurl`` /
    ``src``，再对整个文本做 URL 正则兜底，避免链接后紧跟的引号/逗号被吞入。
    同时处理 URL 编码的链接（如 ``http%3A%2F%2F...``）。
    """
    out: list[str] = []
    for field in ("jumpUrl", "url", "playUrl", "videoUrl", "appurl", "src"):
        # 兼容 "jumpUrl":"..." / 'jumpUrl':'...' / "jumpUrl":"..."
        pat = re.escape(field) + r"['\"]?\s*:\s*['\"]?(https?://[^\"'\s,}]+)"
        out += [m.group(1) for m in re.finditer(pat, text)]
    # 兜底：整条文本里的所有 http(s) 链接
    url_find = re.compile(r"https?://[^\s，。、；;]+")
    out += url_find.findall(text)
    # 处理 URL 编码的链接（如 http%3A%2F%2Fwww.iqiyi.com%2F...）
    enc_find = re.compile(r"https?%3A%2F%2F[^\s\"'，。、；;]+", re.I)
    for m in enc_find.finditer(text):
        decoded = urllib.parse.unquote(m.group(0))
        out.append(decoded)
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def is_vip_video_url(text: str) -> str | None:
    """若文本里含受支持的 VIP 视频链接，返回该链接；否则 None。

    支持：
    - 纯文本里的链接（整条消息就是一条链接，或句子里命中已知 VIP 域名）；
    - QQ 分享卡片 ``[CQ:json]`` / ``[CQ:share]`` / ``[CQ:xml]`` 里的 ``jumpUrl`` 等跳转地址
      （这类卡片的 ``message_str`` 是 CQ 码而非裸链接，必须解码才能识别）；
    - 消息组件 ``ComponentType.Json`` 的裸 JSON 对象字符串。

    仅当链接命中已知 VIP 域名时才接管，避免把普通搜索语句误判为视频解析。
    """
    if not text:
        return None
    s = text.strip()
    url_re = re.compile(r"https?://[^\s，。、；;]+")
    if "[CQ:" in s:
        # 分享卡片：CQ 码里的 data 是 URL 编码的 JSON，且整串没有空格，
        # 直接对整条消息跑 url_re 会贪婪吞掉半个 JSON。改为只从解码后的卡片里取链接。
        urls = _extract_cq_urls(s)
    elif s.startswith("{") and s.endswith("}"):
        # ComponentType.Json 的 data 直接是 JSON 对象字符串，先做字段精确提取，
        # 避免贪婪 URL 正则把后面的引号/逗号/字段一起吞进来。
        urls = _extract_json_urls(s)
    else:
        urls = list(url_re.findall(s))
        # 合并 CQ 卡片里解码出的链接（极少数消息同时含裸链接与卡片时也兼容）
        urls += _extract_cq_urls(s)
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    urls = uniq
    if not urls:
        return None
    # 单链接：整条消息就是一个 URL（允许带少量前后空格）
    if len(urls) == 1 and urls[0].rstrip("/") == s.rstrip("/"):
        u = urls[0]
        if any(k in u for k in VIP_HOST_KEYWORDS):
            return u
        return None
    # 多链接 / 含链接的句子 / CQ 卡片 / JSON：只接管明确命中 VIP 域名的
    for u in urls:
        if any(k in u for k in VIP_HOST_KEYWORDS):
            return u
    return None


def _is_iqiyi_share(url: str) -> bool:
    u = (url or "").lower()
    return ("playshare.html" in u) or ("shareid=" in u) or ("share.iqiyi.com" in u)


def follow_iqiyi_redirect(url: str, proxy: str = "") -> str:
    """对爱奇艺播放页做 HTTP 重定向跟随，返回最终 URL。（保留兼容旧调用）"""
    return follow_video_redirect(url, proxy=proxy)


# ───────────────────────────────────────────────────────────────────────────
# 多平台 URL 规范化（芒果TV / 优酷 / 腾讯视频 / 爱奇艺）
# ───────────────────────────────────────────────────────────────────────────
_VIDEO_HOSTS = ("iqiyi.com", "mgtv.com", "youku.com", "v.qq.com", "qq.com",
                "le.com", "letv.com", "sohu.com", "bilibili.com")


def follow_video_redirect(url: str, proxy: str = "") -> str:
    """对任意视频平台播放页做 HTTP 重定向跟随，返回最终 URL。

    分享卡片里的 URL 可能是移动版/短链/中间跳转页，解析器拿到非标准链接会失败。
    本函数用 HTTP HEAD→GET 跟随 302，拿到最终的标准播放页 URL。
    非视频平台链接或请求失败时原样返回。
    """
    if not url:
        return url
    url = urllib.parse.unquote(url)
    low = url.lower()
    if not any(h in low for h in _VIDEO_HOSTS):
        return url
    try:
        import urllib.request as _ureq
        headers = {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        handlers: list = []
        if proxy:
            handlers.append(_ureq.ProxyHandler({"http": proxy, "https": proxy}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        for method in ("HEAD", "GET"):
            try:
                req = _ureq.Request(url, headers=headers, method=method)
                with opener.open(req, timeout=10) as resp:
                    final = resp.geturl()
                    if final:
                        if final.startswith("http://"):
                            final = "https://" + final[len("http://"):]
                        if final != url:
                            logger.info(f"[vip_capture] 重定向跟随({method}) {url[:80]} -> {final[:80]}")
                        return final
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[vip_capture] 重定向跟随失败 {url[:80]}: {e}")
    return url


def _normalize_mgtv_url(url: str) -> str:
    """芒果TV：确保为 https://www.mgtv.com/b/XXX/YYY.html 格式。"""
    # m.mgtv.com → www.mgtv.com
    url = re.sub(r"https?://m\.mgtv\.com", "https://www.mgtv.com", url, flags=re.I)
    # 提取 /b/数字/数字.html
    m = re.search(r"mgtv\.com/b/(\d+)/(\d+)", url, re.I)
    if m:
        return f"https://www.mgtv.com/b/{m.group(1)}/{m.group(2)}.html"
    # /h/ 格式 → /b/（某些旧链接）
    m = re.search(r"mgtv\.com/h/(\d+)/(\d+)", url, re.I)
    if m:
        return f"https://www.mgtv.com/b/{m.group(1)}/{m.group(2)}.html"
    return url


def _normalize_youku_url(url: str) -> str:
    """优酷：确保为 https://v.youku.com/v_show/id_XXX.html 格式。

    注意：id 后面的 == 是 base64 填充，不能去掉！
    """
    # m.youku.com → v.youku.com
    url = re.sub(r"https?://m\.youku\.com", "https://v.youku.com", url, flags=re.I)
    # 提取 id_XXX（保留 = 号，只去掉末尾的 .）
    m = re.search(r"id_([A-Za-z0-9=_]+)", url)
    if m:
        vid = m.group(1).rstrip(".")
        return f"https://v.youku.com/v_show/id_{vid}.html"
    return url


def _normalize_qq_url(url: str) -> str:
    """腾讯视频：确保为 https://v.qq.com/x/cover/XXX/YYY.html 格式。"""
    # 已是标准 cover 格式
    m = re.search(r"v\.qq\.com/x/cover/(\w+)/(\w+)", url, re.I)
    if m:
        return f"https://v.qq.com/x/cover/{m.group(1)}/{m.group(2)}.html"
    # page 格式保持（单视频无 cover，解析器也能处理）
    m = re.search(r"v\.qq\.com/x/page/(\w+)", url, re.I)
    if m:
        return f"https://v.qq.com/x/page/{m.group(1)}.html"
    # 移动版播放页 m.v.qq.com/x/m/play?vid=XXX&cid=YYY → 标准格式
    m = re.search(r"[?&]vid=(\w+)", url, re.I)
    m2 = re.search(r"[?&]cid=(\w+)", url, re.I)
    if m and m2:
        return f"https://v.qq.com/x/cover/{m2.group(1)}/{m.group(1)}.html"
    # 只有 vid 没有 cid → page 格式
    if m:
        return f"https://v.qq.com/x/page/{m.group(1)}.html"
    return url


def normalize_video_url(url: str, proxy: str = "") -> str:
    """规范化视频平台 URL：URL 解码 + 重定向跟随 + 平台特定格式化。

    支持：爱奇艺/芒果TV/优酷/腾讯视频。返回标准格式的播放页 URL。
    """
    if not url:
        return url
    url = urllib.parse.unquote(url)
    low = url.lower()

    # 跟随 HTTP 重定向（所有平台通用）
    redirected = follow_video_redirect(url, proxy=proxy)
    if redirected and redirected != url:
        url = redirected
        low = url.lower()

    # 平台特定规范化
    if "mgtv.com" in low:
        url = _normalize_mgtv_url(url)
    elif "youku.com" in low:
        url = _normalize_youku_url(url)
    elif "v.qq.com" in low:
        url = _normalize_qq_url(url)
    elif "iqiyi.com" in low:
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]

    return url


def _extract_tvid(url: str) -> str:
    """从爱奇艺分享卡片链接的 shareId 里解出 tvid（base64）。"""
    m = re.search(r"shareId=([^&]+)", url, re.I)
    if not m:
        return ""
    try:
        s = urllib.parse.unquote(m.group(1))
        s += "=" * (-len(s) % 4)
        return base64.b64decode(s).decode("utf-8", "ignore")
    except Exception:
        return ""


def is_iqiyi_share_url(url: str) -> bool:
    """判断是否为爱奇艺分享中转页（playShare.html?shareId= / share.iqiyi.com）。"""
    u = (url or "").lower()
    return ("playshare.html" in u) or ("shareid=" in u) or ("share.iqiyi.com" in u)


def resolve_iqiyi_share(share_url: str, proxy: str = "") -> dict:
    """把爱奇艺分享中转页（playShare.html?shareId=）解析为真实播放页。

    通过 ``mesh.if.iqiyi.com`` 的公开接口（纯 HTTP，无需登录/浏览器），
    用 base64 解出的 tvid 拿到真实 ``v_xxx.html`` 播放页 + 标题 + 封面。
    浏览器转换（analyze_vip_link 里的 _find_clean_v）在无登录态下常常失败，
    这个 HTTP 接口是更稳的兜底。

    返回 ``{"ok", "clean_url", "title", "album", "cover", "error"}``。
    """
    out: dict = {"ok": False, "clean_url": share_url, "title": "",
                 "album": "", "cover": "", "error": ""}
    tvid = _extract_tvid(share_url)
    if not tvid:
        out["error"] = "无法从分享链接解出 tvid"
        return out
    api = ("https://mesh.if.iqiyi.com/player/pcw/video/playervideoinfo?"
           f"id={urllib.parse.quote(tvid)}&locale=zh_cn")
    try:
        import json as _json
        import urllib.request as _ureq

        headers = {
            "User-Agent": _UA,
            "Referer": "https://www.iqiyi.com/",
            "Accept": "application/json, text/plain, */*",
        }
        handlers: list = []
        if proxy:
            handlers.append(_ureq.ProxyHandler({"http": proxy, "https": proxy}))
        opener = _ureq.build_opener(*handlers) if handlers else _ureq.build_opener()
        req = _ureq.Request(api, headers=headers)
        with opener.open(req, timeout=15) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace"))
        d = data.get("data") or {}
        vu = d.get("vu") or ""
        if not vu:
            out["error"] = "接口未返回播放页(vu)"
            return out
        # API 返回的 vu 可能是 URL 编码的（如 http%3A%2F%2F...），必须解码
        vu = urllib.parse.unquote(vu)
        if vu.startswith("http://"):
            vu = "https://" + vu[len("http://"):]
        out["clean_url"] = vu
        out["title"] = d.get("vn") or d.get("an") or ""
        out["album"] = d.get("an") or ""
        out["cover"] = d.get("apic") or ""
        out["ok"] = True
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        return out


# ───────────────────────────────────────────────────────────────────────────
# 浏览器辅助
# ───────────────────────────────────────────────────────────────────────────
def _detect_proxy() -> str:
    """从环境变量探测代理（Chromium 不读 HTTP(S)_PROXY，需显式传入）。"""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return ""


@asynccontextmanager
async def _browser(proxy: str, channel: str, exe: str):
    from playwright.async_api import async_playwright
    if not proxy:
        proxy = _detect_proxy()
    kwargs: dict = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    }
    if channel:
        kwargs["channel"] = channel
    elif exe:
        kwargs["executable_path"] = exe
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    async with async_playwright() as p:
        browser = await p.chromium.launch(**kwargs)
        try:
            yield browser
        finally:
            try:
                await browser.close()
            except Exception:
                pass


async def _page_is_usable(page) -> tuple[bool, str]:
    """检测当前页面是否真的渲染出可播放的播放器。

    判定：页面正文不含明显错误字，且至少存在一个有可播放 src 的 <video>，
    或一个指向真实播放器的 <iframe>（排除 about:blank）。
    """
    try:
        info = await page.evaluate("""() => {
            const body = document.body ? document.body.innerText : '';
            const txt = (body || '').toLowerCase();
            const errWords = ['解析失败','无法解析','暂不可用','接口失效','解析接口失效',
                              '该视频','找不到','not found','invalid','expired','已失效',
                              '获取失败','播放失败','视频地址错误','地址错误'];
            const hasErr = errWords.some(w => txt.indexOf(w) !== -1);
            const videos = Array.from(document.querySelectorAll('video'));
            const vinfo = videos.slice(0, 5).map(v => ({
                src: (v.currentSrc || v.src || ''),
                rs: v.readyState,
                err: v.error ? v.error.code : null
            }));
            const iframes = Array.from(document.querySelectorAll('iframe'))
                                .map(f => f.src || '').filter(Boolean);
            return {hasErr, vinfo, iframes, title: document.title || ''};
        }""")
    except Exception:  # noqa: BLE001
        return False, ""

    if not isinstance(info, dict):
        return False, ""
    if info.get("hasErr", False):
        return False, info.get("title", "")

    for v in info.get("vinfo", []) or []:
        src = (v.get("src") or "")
        # blob: URL（MSE/MediaSource Extensions）也是有效的播放源，
        # jx.xmflv.com 等解析器用 blob: URL 播放视频，不能只认 http
        if (src.startswith("http") or src.startswith("blob:")) and v.get("err") in (None, 0):
            return True, info.get("title", "")

    for s in info.get("iframes", []) or []:
        if s.startswith("http") and "about:blank" not in s:
            return True, info.get("title", "")

    return False, info.get("title", "")


# ───────────────────────────────────────────────────────────────────────────
# 链接分析：尽力转换 + 影视信息 + 截图
# ───────────────────────────────────────────────────────────────────────────
async def _find_clean_v(page) -> str:
    """在已加载的分享页里尽力找「当前视频」的纯净 v_ 播放页。

    返回空串表示找不到（爱奇艺分享页通常只在登录态才暴露，无会话时几乎必空）。
    """
    try:
        cano = await page.evaluate(
            "() => { const l=document.querySelector('link[rel=canonical]'); return l?l.href:''; }")
        if cano and re.search(r"/v_[0-9a-zA-Z]+\.html", cano):
            return cano
    except Exception:
        pass
    u = page.url or ""
    m = re.search(r"https?://[^\s\"'\\]+iqiyi\.com/v_[0-9a-zA-Z]+\.html", u)
    if m:
        return m.group(0)
    # 扫描页面里只出现一次的 v_ 链接（推荐位会重复，当前视频通常唯一）
    try:
        links = await page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
            .map(a => a.href).filter(h => /iqiyi\\.com\\/v_[0-9a-zA-Z]+\\.html/.test(h))""")
        cnt = Counter(links)
        for link, c in cnt.items():
            if c == 1:
                return link
    except Exception:
        pass
    return ""


async def analyze_vip_link(
    url: str,
    proxy: str = "",
    timeout_ms: int = 20000,
    channel: str = "",
    exe: str = "",
) -> dict:
    """分析一条 VIP 视频链接：尽力转换为纯净播放页，并抓取影视信息 + 截图。

    返回 dict：
        {
          "clean_url": str,     # 用于喂给解析接口的链接（已尽量纯净）
          "is_share": bool,     # 是否识别为分享卡片
          "tvid": str,          # 分享卡片解出的 tvid（可能为空）
          "resolved": bool,     # 分享卡片是否成功转换为纯净链接
          "title": str,
          "desc": str,
          "poster_url": str,    # og:image 缩略图（可能为空）
          "poster_path": str,   # 浏览器截图路径（可能为空）
          "error": str,
        }
    """
    out = {
        "clean_url": url, "is_share": False, "tvid": "",
        "resolved": True, "title": "", "desc": "", "poster_url": "",
        "poster_path": "", "error": "",
    }
    if _is_iqiyi_share(url):
        out["is_share"] = True
        out["tvid"] = _extract_tvid(url)

    try:
        async with _browser(proxy, channel, exe) as browser:
            ctx = await browser.new_context(user_agent=_UA, java_script_enabled=True,
                                             ignore_https_errors=True)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:  # noqa: BLE001
                out["error"] = f"goto: {type(e).__name__}: {e}"
            # 给播放器预览 / 页面渲染一点时间
            try:
                await page.wait_for_timeout(min(8000, int(timeout_ms * 0.4)))
            except Exception:
                pass

            # 1) 元信息
            try:
                meta = await page.evaluate("""() => {
                    const g = n => { const e=document.querySelector(n);
                        return e ? (e.content || e.getAttribute('content') || '') : ''; };
                    return {
                        title: document.title,
                        og_title: g('meta[property="og:title"]'),
                        og_desc: g('meta[property="og:description"]'),
                        og_image: g('meta[property="og:image"]'),
                        desc: g('meta[name="description"]')
                    };
                }""")
                out["title"] = (meta.get("og_title") or meta.get("title") or "").strip()
                out["desc"] = (meta.get("og_desc") or meta.get("desc") or "").strip()
                out["poster_url"] = (meta.get("og_image") or "").strip()
            except Exception:
                pass

            # 2) 分享卡片：尽力转换为纯净 v_ 播放页
            if out["is_share"]:
                clean = await _find_clean_v(page)
                if clean:
                    # 浏览器返回的 URL 可能是 URL 编码的，必须解码
                    clean = urllib.parse.unquote(clean)
                    if clean.startswith("http://"):
                        clean = "https://" + clean[len("http://"):]
                    out["clean_url"] = clean
                    out["resolved"] = True
                else:
                    out["resolved"] = False

            # 3) 截图（作为影视截图；og:image 缺失时尤其有用）
            try:
                path = os.path.join(tempfile.gettempdir(),
                                    f"vip_shot_{abs(hash(url)) % 10**9}.png")
                await page.screenshot(path=path, full_page=False)
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    out["poster_path"] = path
            except Exception:
                pass

            await ctx.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"browser: {type(e).__name__}: {e}"
        out["resolved"] = out["resolved"] and not out["is_share"]

    return out


def build_interface_link(template: str, video_url: str) -> str:
    """把视频地址拼到接口模板后面，得到「解析播放直链」。"""
    enc = urllib.parse.quote(video_url, safe="")
    tpl = (template or "").strip()
    if "{url}" in tpl:
        return tpl.replace("{url}", enc)
    return tpl + enc


async def verify_interface_playable(
    url: str,
    proxy: str = "",
    timeout_ms: int = 20000,
    channel: str = "",
    exe: str = "",
) -> dict:
    """加载某个解析接口播放直链，检测是否真的渲染出可播放的播放器。

    返回 {"ok", "title", "error"}。
    """
    try:
        async with _browser(proxy, channel, exe) as browser:
            ctx = await browser.new_context(user_agent=_UA, java_script_enabled=True,
                                             ignore_https_errors=True)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:  # noqa: BLE001
                await ctx.close()
                return {"ok": False, "title": "", "error": f"goto: {type(e).__name__}: {e}"}
            try:
                await page.wait_for_timeout(min(9000, int(timeout_ms * 0.4)))
            except Exception:
                pass
            ok, title = await _page_is_usable(page)
            await ctx.close()
            if ok:
                return {"ok": True, "title": title, "error": ""}
            return {"ok": False, "title": title, "error": "no-player"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "title": "", "error": f"browser: {type(e).__name__}: {e}"}


# ───────────────────────────────────────────────────────────────────────────
# 兼容旧接口（HLS 已移除，保留签名避免导入失败）
# ───────────────────────────────────────────────────────────────────────────
async def capture_vip_m3u8(url: str, **kw) -> dict:
    """[已废弃] HLS 播放器功能已移除。保留签名以兼容旧导入。"""
    return {"ok": False, "url": "", "error": "HLS播放器已移除"}


async def shutdown():
    """清理浏览器进程（惰性单例）。"""
    global _browser, _pw
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _pw is not None:
        try:
            await _pw.stop()
        except Exception:
            pass
        _pw = None


async def capture_interface_screenshot(
    player_url: str,
    timeout_ms: int = 15000,
    channel: str = "",
    executable_path: str = "",
    proxy: str = "",
) -> "bytes | None":
    """加载解析播放页，等待播放器出现后截图（PNG 字节）。失败返回 None。"""
    if not proxy:
        proxy = _detect_proxy()
    try:
        async with _browser(proxy, channel, executable_path) as browser:
            ctx = await browser.new_context(
                ignore_https_errors=True,
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0 Safari/537.36 Edg/126.0"),
            )
            page = await ctx.new_page()
            try:
                await page.goto(player_url, wait_until="domcontentloaded",
                                timeout=min(timeout_ms, 30000))
            except Exception:
                pass
            try:
                await page.wait_for_selector("video, iframe",
                                              timeout=min(8000, timeout_ms))
            except Exception:
                pass
            await asyncio.sleep(1.5)
            png = await page.screenshot(full_page=False, type="png")
            await ctx.close()
            if png and len(png) > 2000:
                return png
            return None
    except Exception as e:
        logger.warning(f"[vip_capture] 截图失败: {e}")
        return None

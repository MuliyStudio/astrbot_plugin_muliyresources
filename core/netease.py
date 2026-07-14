# -*- coding: utf-8 -*-
"""
网易云音乐解析模块（暮黎资源聚合 v1.9.0 新增）

功能：
  - 从文本/小程序卡片中提取网易云歌曲 ID
  - 通过自建 NeteaseCloudMusicApi 实例获取 mp3 直链 + 元数据
  - 异步下载 mp3 到本地临时文件

解析后端（唯一）：
  - custom：用户自建的 NeteaseCloudMusicApi 实例（wyy_custom_url 配置其地址）。
    始终使用网易云最新密钥，最稳定，不受第三方公共解析站 WAF 拦截影响。
    公共解析站 wyapi.toubiec.cn / tools.qzxdp.cn 已被证实对服务器 IP 普遍返回 404 拦截，
    已于 v1.9.3 移除。
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from typing import Optional

logger = logging.getLogger("astrbot_plugin_muliyresources.netease")

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None


# ---------------------------------------------------------------------------
# 链接 / 小程序检测
# ---------------------------------------------------------------------------

# 网易云常见分享链接形式
_NETEASE_HOST_RE = re.compile(r"(?:music\.163\.com|y\.music\.163\.com|163cn\.tv)", re.I)
# 从 URL 中提取歌曲 ID（多种形态）
_SONG_ID_RES = [
    re.compile(r"music\.163\.com/#?/?song[?/]id=(\d+)", re.I),   # /song?id= 或 /#/song?id=
    re.compile(r"music\.163\.com/song/(\d+)", re.I),             # /song/123 路径形式
    re.compile(r"y\.music\.163\.com/m/song[?/]id=(\d+)", re.I),  # 移动端分享
    re.compile(r"music\.163\.com/song/media/outer/url[?&]id=(\d+)", re.I),  # QQ 转发的小程序卡片外链形态
    re.compile(r"(?:y\.)?music\.163\.com/[^\s\"'<>]*?id=(\d+)", re.I),  # 兜底：任意 163 链接中的 id=
    re.compile(r"163cn\.tv/([A-Za-z0-9]+)"),                      # 短链，需跟随重定向解析
    re.compile(r"orpheus://song/(\d+)"),
]


def looks_like_netease(text: str) -> bool:
    """文本是否看起来包含网易云分享（链接或小程序关键字）。"""
    if not text:
        return False
    if _NETEASE_HOST_RE.search(text):
        return True
    # 小程序关键字兜底
    return ("网易云" in text) or ("网抑云" in text) or ("音乐" in text and "分享" in text)


def extract_netease_id(text: str) -> Optional[str]:
    """从文本中提取网易云歌曲 ID。无法提取返回 None。"""
    if not text:
        return None
    for rx in _SONG_ID_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


def extract_from_miniapp(json_str) -> Optional[str]:
    """从 QQ 小程序分享卡片（json 段）的文本 / 字典中提取歌曲 ID 或链接。

    小程序卡片结构各异，这里做最大努力的提取：
      - 优先整串扫描 music.163.com 链接（卡片 Json 常内嵌外链 URL）
      - 其次找 musicId / songId / id 字段
    """
    if not json_str:
        return None
    # 兼容 dict 输入：先序列化为字符串，保证整串扫描不漏
    if isinstance(json_str, dict):
        try:
            json_str = json.dumps(json_str, ensure_ascii=False)
        except Exception:
            json_str = str(json_str)
    if isinstance(json_str, str):
        # 1) 整串扫描链接（最稳）
        link = extract_netease_id(json_str)
        if link:
            return link
    # 2) 结构化字段
    try:
        data = json.loads(json_str) if isinstance(json_str, str) else json_str
    except Exception:
        data = None
    if isinstance(data, dict):
        # 常见字段
        for key in ("musicId", "songId", "song_id", "music_id", "id"):
            v = data.get(key)
            if isinstance(v, int) and v > 0:
                return str(v)
            if isinstance(v, str) and v.isdigit():
                return v
        # 嵌套：meta.detail_1.qqdocurl / jumpUrl
        meta = data.get("meta") or {}
        detail = meta.get("detail_1") or {}
        for k, v in detail.items():
            if isinstance(v, str) and "163" in v:
                sid = extract_netease_id(v)
                if sid:
                    return sid
    return None


async def resolve_shortlink(url: str) -> str:
    """跟随短链重定向，返回最终 URL（用于 163cn.tv 等短链）。"""
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
    try:
        if aiohttp is not None:
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    return str(r.url)
        else:
            import urllib.request

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.geturl()
    except Exception as e:  # pragma: no cover
        logger.warning(f"[网易云] 短链解析失败: {e}")
        return url


# ---------------------------------------------------------------------------
# 解析后端
# ---------------------------------------------------------------------------

class NeteaseParser:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.last_error = ""  # 最近一次解析失败的具体原因，便于前端提示

    async def parse(self, song_id: str) -> Optional[dict]:
        """解析歌曲，返回 {name, artist, album, url, pic} 或 None。

        仅支持自建 NeteaseCloudMusicApi 后端（wyy_custom_url）。
        """
        return await self._parse_custom(song_id)

    # ---- 自定义后端（唯一后端：自建 NeteaseCloudMusicApi，始终用网易云最新密钥） ----
    async def _parse_custom(self, song_id: str) -> Optional[dict]:
        """自定义后端支持两种填法（wyy_custom_url）：

        1) 含 {id} 占位符的直链模板（旧写法，向后兼容）：
           http://127.0.0.1:3000/song/url?id={id}
           仅能拿到 mp3 直链，歌名/歌手可能缺失（回退“未知歌曲”）。

        2) NeteaseCloudMusicApi 实例「基础地址」（推荐）：
           http://127.0.0.1:3000
           自动调用标准接口 /song/url（拿直链）+ /song/detail（拿歌名/歌手/专辑/封面），
           名片信息完整。
        """
        tpl = (self.cfg.get("wyy_custom_url") or "").strip()
        wyy_cookie = (self.cfg.get("wyy_cookie") or "").strip()
        if not tpl:
            self.last_error = "自定义后端已启用但未配置 wyy_custom_url（请在插件配置填写 NeteaseCloudMusicApi 实例地址）"
            logger.warning("[网易云] 自定义后端已启用但未配置 wyy_custom_url")
            return None

        # —— 旧模板写法（含 {id}）——
        if "{id}" in tpl or "{song_id}" in tpl:
            url = tpl.replace("{id}", song_id).replace("{song_id}", song_id)
            try:
                resp = await _get_json(url, wyy_cookie)
            except Exception as e:
                self.last_error = f"自定义后端请求失败：{e}"
                logger.warning(f"[网易云] 自定义后端请求失败: {e}")
                return None
            if not isinstance(resp, dict):
                self.last_error = "自定义后端返回非 JSON 响应"
                return None
            url_val = (
                _dig(resp, ("data", 0, "url"))
                or _dig(resp, ("data", "url"))
                or _dig(resp, ("url",))
                or _dig(resp, ("data", 0, "src"))
            )
            if not url_val:
                self.last_error = "自定义后端未找到 mp3 直链字段（确认 wyy_custom_url 指向 /song/url 接口）"
                logger.warning("[网易云] 自定义后端未找到 mp3 直链字段")
                return None
            return {
                "name": _dig(resp, ("data", 0, "name")) or _dig(resp, ("name",)) or "未知歌曲",
                "artist": _dig(resp, ("data", 0, "artist")) or _dig(resp, ("data", 0, "ar", 0, "name")) or _dig(resp, ("artist",)) or "未知歌手",
                "album": _dig(resp, ("data", 0, "album", "name")) or _dig(resp, ("album",)) or "",
                "url": url_val,
                "pic": _dig(resp, ("data", 0, "picUrl")) or _dig(resp, ("data", 0, "cover")) or _dig(resp, ("pic",)) or "",
            }

        # —— 标准 NeteaseCloudMusicApi 实例（基础地址）——
        base = tpl.rstrip("/")
        # 1) 播放直链：/song/url?id=xxx&level=xxx -> data[0].url
        music_type = (self.cfg.get("wyy_music_type") or "standard").strip()
        try:
            url_resp = await _get_json(f"{base}/song/url?id={song_id}&level={music_type}", wyy_cookie)
        except Exception as e:
            self.last_error = f"custom /song/url 请求失败：{e}（确认 wyy_custom_url 为可达的 NeteaseCloudMusicApi 基础地址）"
            logger.warning(f"[网易云] custom /song/url 请求失败: {e}")
            url_resp = None
        mp3 = (
            _dig(url_resp, ("data", 0, "url"))
            or _dig(url_resp, ("data", "url"))
            or _dig(url_resp, ("url",))
        )
        if not mp3:
            if not self.last_error:
                self.last_error = "custom /song/url 未返回直链（实例地址不可达，或该曲需 VIP）"
            logger.warning("[网易云] custom /song/url 未返回直链（可能该曲需 VIP 或实例地址不可达）")
            return None
        # 2) 元数据：/song/detail?ids=[xxx] -> songs[0].{name,artists,album}
        name = artist = album = pic = ""
        try:
            info = await _get_json(f"{base}/song/detail?ids=[{song_id}]", wyy_cookie)
            song = _dig(info, ("songs", 0)) or _dig(info, ("data", 0)) or {}
            name = song.get("name") or "未知歌曲"
            ar = song.get("artists") or song.get("ar") or []
            if ar and isinstance(ar[0], dict):
                artist = ar[0].get("name") or "未知歌手"
            al = song.get("album") or {}
            if isinstance(al, dict):
                album = al.get("name") or ""
                pic = al.get("picUrl") or ""
            if not pic:
                pic = song.get("picUrl") or ""
        except Exception as e:
            logger.warning(f"[网易云] custom /song/detail 请求失败: {e}")
        return {
            "name": name or "未知歌曲",
            "artist": artist or "未知歌手",
            "album": album or "",
            "url": mp3,
            "pic": pic or "",
        }


def _dig(obj, keys):
    """按路径逐层取值，任意一层失败返回 None。"""
    cur = obj
    for k in keys:
        if isinstance(cur, list):
            try:
                cur = cur[int(k)]
            except Exception:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(k)
            if cur is None:
                return None
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# HTTP 辅助（异步）
# ---------------------------------------------------------------------------

async def _get_json(url: str, cookie: Optional[str] = None) -> dict:
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
    if cookie:
        # 携带会员 Cookie 才能解析 VIP/付费歌曲（NeteaseCloudMusicApi 从请求 Cookie 头取 cookie 转发）
        headers["Cookie"] = cookie
    if aiohttp is not None:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                return await r.json(content_type=None)
    else:  # pragma: no cover
        import urllib.request

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())


async def download_mp3(mp3_url: str, dest_path: Optional[str] = None) -> str:
    """下载 mp3 到本地临时文件，返回路径。"""
    if dest_path is None:
        fd, dest_path = tempfile.mkstemp(suffix=".mp3", prefix="wyy_")
        os.close(fd)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
    try:
        if aiohttp is not None:
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(mp3_url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                    r.raise_for_status()
                    with open(dest_path, "wb") as f:
                        async for chunk in r.content.iter_chunked(64 * 1024):
                            f.write(chunk)
        else:  # pragma: no cover
            import urllib.request

            req = urllib.request.Request(mp3_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r, open(dest_path, "wb") as f:
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
    except Exception:
        if os.path.exists(dest_path):
            try:
                os.unlink(dest_path)
            except Exception:
                pass
        raise
    return dest_path


# ---------------------------------------------------------------------------
# 扫码登录（v1.9.6 新增）
#
# 依赖自建 NeteaseCloudMusicApi 的官方二维码登录接口：
#   GET /login/qr/key            -> {data:{unikey}}            拿登录 key
#   GET /login/qr/create?key=&qrimg=true
#                                -> {data:{qrurl, qrimg}}      拿二维码（qrimg 为 data:image/png;base64,..）
#   GET /login/qr/check?key=     -> {code, message, cookie}    轮询扫码状态
#       code 800=二维码过期 / 801=等待扫码 / 802=已扫码待确认 / 803=授权成功(带 cookie)
#
# 注意：这些接口有缓存，必须每次带上不同的 timestamp 参数，否则 check 状态不刷新。
# ---------------------------------------------------------------------------

def normalize_api_base(custom_url: str) -> str:
    """把 wyy_custom_url（可能是基础地址或含 {id} 的直链模板）归一化为「基础地址」。

    例：
      http://127.0.0.1:3000                       -> http://127.0.0.1:3000
      http://127.0.0.1:3000/song/url?id={id}      -> http://127.0.0.1:3000
    """
    tpl = (custom_url or "").strip()
    if not tpl:
        return ""
    if "{id}" in tpl or "{song_id}" in tpl or "/song/" in tpl or "?" in tpl:
        try:
            from urllib.parse import urlparse
            p = urlparse(tpl)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    return tpl.rstrip("/")


async def qr_login_key(base: str) -> Optional[str]:
    """获取登录 unikey。失败返回 None。"""
    base = (base or "").rstrip("/")
    import time as _t
    ts = int(_t.time() * 1000)
    try:
        resp = await _get_json(f"{base}/login/qr/key?timestamp={ts}")
    except Exception as e:
        logger.warning(f"[网易云扫码] 获取 key 失败: {e}")
        return None
    return _dig(resp, ("data", "unikey")) or _dig(resp, ("unikey",))


async def qr_login_create(base: str, key: str) -> Optional[dict]:
    """用 key 生成二维码。返回 {"qrimg": data-uri, "qrurl": url} 或 None。"""
    base = (base or "").rstrip("/")
    import time as _t
    ts = int(_t.time() * 1000)
    try:
        resp = await _get_json(f"{base}/login/qr/create?key={key}&qrimg=true&timestamp={ts}")
    except Exception as e:
        logger.warning(f"[网易云扫码] 生成二维码失败: {e}")
        return None
    qrimg = _dig(resp, ("data", "qrimg")) or _dig(resp, ("qrimg",))
    qrurl = _dig(resp, ("data", "qrurl")) or _dig(resp, ("qrurl",))
    if not qrimg and not qrurl:
        return None
    return {"qrimg": qrimg, "qrurl": qrurl}


async def qr_login_check(base: str, key: str) -> dict:
    """轮询扫码状态，返回原始响应 {code, message, cookie}。异常时返回 {code:-1}。"""
    base = (base or "").rstrip("/")
    import time as _t
    ts = int(_t.time() * 1000)
    try:
        resp = await _get_json(f"{base}/login/qr/check?key={key}&timestamp={ts}&noCookie=false")
    except Exception as e:
        logger.warning(f"[网易云扫码] 轮询状态失败: {e}")
        return {"code": -1, "message": str(e)}
    return resp if isinstance(resp, dict) else {"code": -1, "message": "非 JSON 响应"}


def qrimg_to_bytes(qrimg: str) -> Optional[bytes]:
    """把 create 接口返回的 data-uri（data:image/png;base64,xxx）解码为 PNG bytes。"""
    if not qrimg or not isinstance(qrimg, str):
        return None
    try:
        import base64 as _b64
        if "," in qrimg:
            qrimg = qrimg.split(",", 1)[1]
        return _b64.b64decode(qrimg)
    except Exception as e:
        logger.warning(f"[网易云扫码] 二维码解码失败: {e}")
        return None


def extract_music_cookie(cookie_str: str) -> str:
    """从扫码返回的完整 cookie 串中提取核心字段（MUSIC_U + __csrf），拼成 wyy_cookie。"""
    if not cookie_str:
        return ""
    parts = {}
    for seg in cookie_str.split(";"):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, v = seg.split("=", 1)
        k = k.strip()
        v = v.strip()
        # 同名多次出现时保留最后一个非空值
        if v:
            parts[k] = v
    keep = []
    for k in ("MUSIC_U", "__csrf"):
        if parts.get(k):
            keep.append(f"{k}={parts[k]}")
    # 若没抓到 MUSIC_U，退而求其次返回整串，避免丢失
    if not any(x.startswith("MUSIC_U=") for x in keep):
        return cookie_str.strip()
    return "; ".join(keep)


async def get_login_nickname(base: str, cookie: str) -> str:
    """用 cookie 拉取登录账号昵称（/user/account 或 /login/status）。失败返回空串。"""
    base = (base or "").rstrip("/")
    import time as _t
    ts = int(_t.time() * 1000)
    try:
        resp = await _get_json(f"{base}/user/account?timestamp={ts}", cookie)
        nick = _dig(resp, ("profile", "nickname"))
        if nick:
            return str(nick)
    except Exception:
        pass
    try:
        resp = await _get_json(f"{base}/login/status?timestamp={ts}", cookie)
        nick = (
            _dig(resp, ("data", "profile", "nickname"))
            or _dig(resp, ("profile", "nickname"))
        )
        if nick:
            return str(nick)
    except Exception:
        pass
    return ""

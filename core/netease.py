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
import base64
import codecs
import hashlib
import json
import logging
import os
import random
import re
import tempfile
from typing import Optional

logger = logging.getLogger("astrbot_plugin_muliyresources.netease")

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None

# 网易云请求全局代理（由配置 wyy_proxy 设置，影响 weapi/api/扫码/下载）
_WYY_PROXY: str = ""


def set_wyy_proxy(proxy: str):
    """设置网易云请求代理。proxy 形如 http://user:pass@host:port 或 socks5://host:port，留空=不走代理。"""
    global _WYY_PROXY
    _WYY_PROXY = (proxy or "").strip()


def _get_wyy_proxy() -> str:
    return _WYY_PROXY



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
# 内置直连后端（weapi，无需任何外部服务）
#
# 网易云网页端用 weapi（两次 AES-CBC + 一次 RSA）对请求体加密。下面复用官方客户端
# 的同款密钥与算法，直接在插件内完成加密并请求 music.163.com，从而做到「零部署」：
# 不再需要单独跑 NeteaseCloudMusicApi 服务，也就没有 Docker / 127.0.0.1 填错的坑。
# 密钥为网易云长期固定的客户端常量（与 NeteaseCloudMusicApi 完全一致）。
# ---------------------------------------------------------------------------

_WYY_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3"
    "ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557"
    "c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82"
    "047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)
_WYY_NONCE = b"0CoJUm6Qyw8W8jud"          # 第一次 AES 密钥
_WYY_PUBKEY = b"010001"                    # RSA 指数 e = 65537
_WYY_IV = b"0102030405060708"             # AES-CBC IV

try:
    from Crypto.Cipher import AES         # pycryptodome
    _HAVE_CRYPTO = True
except Exception:                          # pragma: no cover
    AES = None
    _HAVE_CRYPTO = False


def _aes_encrypt(text_bytes: bytes, sec_key: bytes) -> bytes:
    """AES-128-CBC 加密 + PKCS7 填充 + base64。text_bytes 已是 bytes。"""
    p = 16 - len(text_bytes) % 16
    text_bytes = text_bytes + (chr(p) * p).encode()
    cipher = AES.new(sec_key, AES.MODE_CBC, _WYY_IV)
    return base64.b64encode(cipher.encrypt(text_bytes))


def _rsa_encrypt(text_bytes: bytes) -> str:
    """网易云 weapi 的 RSA：把 secKey 反转后做 modpow，结果补零到 256 位 hex。"""
    rev = text_bytes[::-1]
    n = int(codecs.encode(rev, "hex_codec"), 16)
    e = int(_WYY_PUBKEY, 16)
    m = int(_WYY_MODULUS, 16)
    return format(pow(n, e, m), "x").zfill(256)


def _weapi(raw_dict: dict) -> dict:
    """生成 weapi 请求体 {params, encSecKey}。"""
    text = json.dumps(raw_dict).encode()
    sec_key = "".join(
        random.choice("abcdefghijklmnopqrstuvwxyz1234567890") for _ in range(16)
    ).encode()
    enc_text = _aes_encrypt(_aes_encrypt(text, _WYY_NONCE), sec_key)
    enc_sec = _rsa_encrypt(sec_key)
    return {"params": enc_text.decode(), "encSecKey": enc_sec}


async def _weapi_post(api_path: str, raw_dict: dict, cookie: Optional[str] = None) -> dict:
    """POST 到网易云 weapi 接口并返回解析后的 JSON。"""
    payload = _weapi(raw_dict)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://music.163.com/",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if cookie:
        headers["Cookie"] = cookie
    url = "https://music.163.com" + api_path
    if aiohttp is not None:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.post(url, data=payload, timeout=aiohttp.ClientTimeout(total=30)) as r:
                return _loads_robust(await r.read())
    else:  # pragma: no cover
        import urllib.parse
        import urllib.request

        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return _loads_robust(r.read())


# ---------------------------------------------------------------------------
# 解析后端
# ---------------------------------------------------------------------------

class NeteaseParser:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.last_error = ""  # 最近一次解析失败的具体原因，便于前端提示
        set_wyy_proxy(self.cfg.get("wyy_proxy") or "")

    async def parse(self, song_id: str) -> Optional[dict]:
        """解析歌曲，返回 {name, artist, album, url, pic} 或 None。

        后端由配置 wyy_backend 决定：
          - direct（默认）：内置 weapi 直连网易云，零部署、无需任何外部服务。
          - custom：自建 NeteaseCloudMusicApi 实例（wyy_custom_url）。
        direct 在缺少 pycryptodome 且配置了 wyy_custom_url 时会自动回退到 custom。
        """
        backend = (self.cfg.get("wyy_backend") or "direct").strip().lower()
        if backend == "custom":
            return await self._parse_custom(song_id)
        info = await self._parse_direct(song_id)
        # 内置解析不可用（如未装 pycryptodome）且用户已配置自建后端时，优雅回退
        if info is None and self.cfg.get("wyy_custom_url") and not _HAVE_CRYPTO:
            logger.warning("[网易云] 内置直连不可用，回退到自建 NeteaseCloudMusicApi 后端")
            info = await self._parse_custom(song_id)
        return info

    # ---- 内置直连后端（默认，weapi 直连网易云，零部署） ----
    async def _parse_direct(self, song_id: str) -> Optional[dict]:
        """不依赖任何外部服务，直接以 weapi 调用 music.163.com 拿到直链 + 元数据。

        免费歌曲开箱即用；VIP/付费歌曲需在 wyy_cookie 填入黑胶会员 Cookie 才能拿到直链。
        """
        if not _HAVE_CRYPTO:
            self.last_error = (
                "内置直连解析需要 pycryptodome（在插件依赖里已包含；若环境缺失请 pip install pycryptodome），"
                "或把 wyy_backend 设为 custom 并部署 NeteaseCloudMusicApi"
            )
            logger.warning("[网易云] 未安装 pycryptodome，无法使用内置直连后端")
            return None

        cookie = (self.cfg.get("wyy_cookie") or "").strip()
        music_type = (self.cfg.get("wyy_music_type") or "standard").strip()
        try:
            sid = int(song_id)
        except Exception:
            self.last_error = f"歌曲 ID 非法：{song_id}"
            return None

        # 1) 播放直链：/weapi/song/enhance/player/url/v1 -> data[0].url
        try:
            url_resp = await _weapi_post(
                "/weapi/song/enhance/player/url/v1?csrf_token=",
                {"ids": [sid], "level": music_type, "encodeType": "mp3", "csrf_token": ""},
                cookie,
            )
        except Exception as e:
            self.last_error = f"内置直连请求失败：{e}"
            logger.warning(f"[网易云] 内置直连 /song/url 请求失败: {e}")
            return None
        mp3 = _dig(url_resp, ("data", 0, "url"))
        if not mp3:
            fee = _dig(url_resp, ("data", 0, "fee"))
            code = _dig(url_resp, ("data", 0, "code"))
            if fee and int(fee) != 0 and not cookie:
                self.last_error = (
                    "该曲为 VIP/付费歌曲：发送 /wyy_login 用网易云 App 扫码登录（direct 模式即可），"
                    "登录成功后会员 Cookie 会自动写入 wyy_cookie，再发本歌曲即可解析"
                )
            elif code == 404:
                self.last_error = "该曲可能已下架或区域限制，无法获取直链"
            else:
                self.last_error = "内置直连未返回直链（歌曲可能下架/区域限制）"
            logger.warning(f"[网易云] 内置直连未返回直链: fee={fee} code={code}")
            return None

        # 2) 元数据：/weapi/v3/song/detail -> songs[0].{name,artists,album}
        name = artist = album = pic = ""
        try:
            info = await _weapi_post(
                "/weapi/v3/song/detail?csrf_token=",
                {"c": json.dumps([{"id": sid, "v": 0}]), "ids": [sid], "csrf_token": ""},
                cookie,
            )
            song = _dig(info, ("songs", 0)) or {}
            name = song.get("name") or ""
            ar = song.get("artists") or song.get("ar") or []
            if ar and isinstance(ar[0], dict):
                artist = ar[0].get("name") or ""
            al = song.get("album") or song.get("al") or {}
            if isinstance(al, dict):
                album = al.get("name") or ""
                pic = al.get("picUrl") or ""
            if not pic:
                pic = song.get("picUrl") or ""
        except Exception as e:
            logger.warning(f"[网易云] 内置直连 /song/detail 请求失败: {e}")

        return {
            "name": name or "未知歌曲",
            "artist": artist or "未知歌手",
            "album": album or "",
            "url": mp3,
            "pic": pic or "",
        }

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

def _loads_robust(raw) -> dict:
    """容错解析 JSON。

    背景：NeteaseCloudMusicApi 某些版本会把多个 JSON 值拼接在响应体里返回，
    直接 json.loads 会报 'Extra data: line 1 column N'。这里只读【第一个】
    完整 JSON 值，并容忍 BOM / 前后空白 / JSONP 包裹（someFunc({...});）。
    """
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        text = raw
    else:
        text = str(raw)
    text = text.lstrip("\ufeff").strip()
    # 剥离 JSONP 包裹：func({...}) 或 func([...]);
    m = re.match(r"^[A-Za-z_$][\w$]*\s*\((.*)\)\s*;?\s*$", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 先尝试取第一个完整 JSON 值（忽略尾部多余数据）
        try:
            return json.JSONDecoder().raw_decode(text)[0]
        except Exception:
            pass
        # 再尝试从第一个 { 或 [ 开始截取
        cand = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        if cand:
            idx = min(cand)
            if idx > 0:
                try:
                    return json.JSONDecoder().raw_decode(text[idx:])[0]
                except Exception:
                    pass
        raise


async def _get_json(url: str, cookie: Optional[str] = None) -> dict:
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
    if cookie:
        # 携带会员 Cookie 才能解析 VIP/付费歌曲（NeteaseCloudMusicApi 从请求 Cookie 头取 cookie 转发）
        headers["Cookie"] = cookie
    proxy = _get_wyy_proxy()
    if aiohttp is not None:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(url, proxy=proxy or None, timeout=aiohttp.ClientTimeout(total=30)) as r:
                raw = await r.read()
        return _loads_robust(raw)
    else:  # pragma: no cover
        import urllib.request

        req = urllib.request.Request(url, headers=headers)
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            with opener.open(req, timeout=30) as r:
                return _loads_robust(r.read())
        with urllib.request.urlopen(req, timeout=30) as r:
            return _loads_robust(r.read())


async def download_mp3(mp3_url: str, dest_path: Optional[str] = None, cookie: str = "") -> str:
    """下载 mp3 到本地临时文件，返回路径。

    cookie：可选，携带会员 Cookie 时某些 CDN 节点放行更稳（免费歌通常不需要）。
    ⚠️ 注意：网易云音频 CDN（m*.music.126.net）会对「数据中心 IP」（云服务器）做
    403 拦截（与早年公共解析站被封同源）。此时本函数会抛异常，由调用方降级为
    「发送歌曲名片 + 播放链接」，避免用户完全收不到东西。
    """
    if dest_path is None:
        fd, dest_path = tempfile.mkstemp(suffix=".mp3", prefix="wyy_")
        os.close(fd)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    if cookie:
        headers["Cookie"] = cookie
    proxy = _get_wyy_proxy()
    try:
        if aiohttp is not None:
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(mp3_url, proxy=proxy or None, timeout=aiohttp.ClientTimeout(total=60)) as r:
                    r.raise_for_status()
                    with open(dest_path, "wb") as f:
                        async for chunk in r.content.iter_chunked(64 * 1024):
                            f.write(chunk)
        else:  # pragma: no cover
            import urllib.request

            req = urllib.request.Request(mp3_url, headers=headers)
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy})
                )
                ctx = opener.open(req, timeout=60)
            else:
                ctx = urllib.request.urlopen(req, timeout=60)
            with ctx as r, open(dest_path, "wb") as f:
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
# 内置直连扫码登录（direct 模式，零部署，无需任何外部服务）
#
# 网易云 v4.x 的扫码登录走 /api/ 明文接口（不需要 weapi/eapi 加密）：
#   POST /api/login/qrcode/unikey          body {type:3}        -> {code, unikey}
#   POST /api/login/qrcode/client/login    body {key, type:3}   -> {code, message}
#        code 800=过期 / 801=等待扫码 / 802=已扫码待确认 / 803=授权成功
#        成功时会员 Cookie(MUSIC_U) 在响应头 Set-Cookie 里返回。
# 二维码内容 = https://music.163.com/login?codekey=<unikey>，由插件本地用 qrcode 生成。
# 这样 direct 模式也能「扫码自动写入 wyy_cookie」，彻底不需要 NeteaseCloudMusicApi。
# ---------------------------------------------------------------------------

def _generate_device_id() -> str:
    """生成 52 位十六进制设备 ID（与 NCM 一致）。"""
    return "".join(random.choice("0123456789ABCDEF") for _ in range(52))


def _cloudmusic_dll_encode_id(device_id: str) -> str:
    """网易云客户端 deviceId 校验签名（XOR + MD5 + Base64）。"""
    key = "3go8&$8*3*3h0k(2)2".encode()
    data = device_id.encode()
    xored = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
    digest = hashlib.md5(xored).digest()
    return base64.b64encode(digest).decode()


async def _weapi_post_anon(api_path: str, raw: dict):
    """调用网易云 weapi 端点（匿名注册专用），api_path 以 /api/ 开头。返回 (body_dict, set_cookie_list)。"""
    import urllib.parse

    enc = _weapi(raw)
    data = urllib.parse.urlencode(enc).encode()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; SM-G960U) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    url = "https://music.163.com" + (
        "/weapi/" + api_path[5:] if api_path.startswith("/api/") else api_path
    )
    proxy = _get_wyy_proxy()
    if aiohttp is not None:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.post(url, data=data, proxy=proxy or None, timeout=aiohttp.ClientTimeout(total=30)) as r:
                raw = await r.read()
                sc = r.headers.getall("Set-Cookie") if hasattr(r.headers, "getall") else []
                return _loads_robust(raw), sc
    else:  # pragma: no cover
        import urllib.request

        req = urllib.request.Request(url, data=data, headers=headers)
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            with opener.open(req, timeout=30) as r:
                return _loads_robust(r.read()), (r.headers.get_all("Set-Cookie") or [])
        with urllib.request.urlopen(req, timeout=30) as r:
            return _loads_robust(r.read()), (r.headers.get_all("Set-Cookie") or [])


async def _register_anonymous(device_id: str):
    """调用 /api/register/anonimous 注册匿名设备，返回 (body, set_cookie_list)。失败抛出异常。"""
    if not _HAVE_CRYPTO:
        raise RuntimeError("缺少 pycryptodome，无法注册匿名设备")
    encoded = _cloudmusic_dll_encode_id(device_id)
    username = base64.b64encode(f"{device_id} {encoded}".encode()).decode()
    return await _weapi_post_anon("/api/register/anonimous", {"username": username})


def _build_qr_cookie(device_id: str, music_a: str, csrf: str = "", request_id: str = None) -> str:
    """构造与 NCM 一致的 /api/login/qrcode/* 请求 Cookie 头。"""
    import time as _time

    ts = str(int(_time.time()))[:10]
    rid = request_id or f"{int(_time.time() * 1000)}_{random.randint(0, 9999):04d}"
    fields = [
        ("osver", "16.2"),
        ("deviceId", device_id),
        ("os", "iPhone OS"),
        ("appver", "9.0.90"),
        ("versioncode", "140"),
        ("mobilename", ""),
        ("buildver", ts),
        ("__csrf", csrf or ""),
        ("channel", "distribution"),
        ("requestId", rid),
    ]
    if music_a:
        fields.append(("MUSIC_A", music_a))
    return "; ".join(f"{k}={v}" for k, v in fields)


_API_UA = "NeteaseMusic 9.0.90/5038 (iPhone; iOS 16.2; zh_CN)"


def _api_headers(cookie: str = "") -> dict:
    c = cookie or (
        "os=iPhone OS; osver=16.2; appver=9.0.90; channel=distribution; "
        "__csrf=; MUSIC_A="
    )
    return {
        "User-Agent": _API_UA,
        "Referer": "https://music.163.com/",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": c,
    }


def _extract_netease_cookie(set_cookie_list) -> str:
    """从响应头 Set-Cookie 列表里提取 MUSIC_U + __csrf。"""
    parts = {}
    for item in (set_cookie_list or []):
        first = item.split(";", 1)[0].strip()
        if "=" in first:
            k, v = first.split("=", 1)
            parts[k.strip()] = v.strip()
    keep = []
    for k in ("MUSIC_U", "__csrf"):
        if parts.get(k):
            keep.append(f"{k}={parts[k]}")
    return "; ".join(keep)


def _merge_cookies(existing: str, set_cookie_list) -> str:
    """把响应 Set-Cookie 合并进已有 cookie 串，保持会话一致。

    网易云扫码会把 unikey 与生成时的会话 cookie 绑定，check 轮询必须回传同一个
    会话，否则在「真实扫码确认」阶段会被判定设备环境异常。这里把响应下发的
    cookie（如 NMTID 等）合并进请求 cookie，与官方 / NCM 行为保持一致。
    """
    jar = {}
    for pair in (existing or "").split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            jar[k.strip()] = v.strip()
    for item in (set_cookie_list or []):
        first = item.split(";", 1)[0].strip()
        if "=" in first:
            k, v = first.split("=", 1)
            if k.strip():
                jar[k.strip()] = v.strip()
    return "; ".join(f"{k}={v}" for k, v in jar.items())


async def _api_post(api_path: str, form: dict, cookie: str = ""):
    """调用网易云 /api/ 明文接口，返回 (body_dict, set_cookie_list)。"""
    import urllib.parse

    data = urllib.parse.urlencode(form).encode()
    headers = _api_headers(cookie)
    url = "https://music.163.com" + api_path
    proxy = _get_wyy_proxy()
    if aiohttp is not None:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.post(url, data=data, proxy=proxy or None, timeout=aiohttp.ClientTimeout(total=30)) as r:
                raw = await r.read()
                sc = r.headers.getall("Set-Cookie") if hasattr(r.headers, "getall") else []
                return _loads_robust(raw), sc
    else:  # pragma: no cover
        import urllib.request

        req = urllib.request.Request(url, data=data, headers=headers)
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            with opener.open(req, timeout=30) as r:
                return _loads_robust(r.read()), (r.headers.get_all("Set-Cookie") or [])
        with urllib.request.urlopen(req, timeout=30) as r:
            return _loads_robust(r.read()), (r.headers.get_all("Set-Cookie") or [])


def build_qr_url(unikey: str) -> str:
    """扫码二维码内容（网易云 App 识别此链接完成登录）。"""
    return f"https://music.163.com/login?codekey={unikey}"


def qr_url_to_png(qr_url: str) -> Optional[bytes]:
    """把二维码链接生成为 PNG 图片 bytes（依赖 qrcode + pillow）。失败返回 None。"""
    try:
        import io

        import qrcode

        img = qrcode.make(qr_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"[网易云扫码] 生成二维码失败: {e}")
        return None


async def qr_login_key_direct():
    """direct 模式：获取扫码登录 unikey。

    返回 (unikey, device_id, music_a, csrf)：
      - unikey：二维码对应的 key
      - device_id / music_a / csrf：匿名设备会话信息（仅匿名注册成功时非空），
        透传给 check 接口保持会话一致。若匿名注册被风控（如服务器 IP 被封返回 400），
        自动退化为「最小 cookie」模式（实测 unikey 明文接口不需要 MUSIC_A 也能返回 200），
        此时 music_a / csrf 为空，check 同样用最小 cookie 轮询，扫码仍可正常进行。
    仅当 unikey 接口本身失败时才返回 (None, "", "", "").
    """
    import traceback

    device_id = _generate_device_id()
    reg_body, reg_sc = {}, []
    try:
        reg_body, reg_sc = await _register_anonymous(device_id)
    except Exception as e:
        logger.warning(f"[网易云扫码] 匿名设备注册失败（{e}），退化最小 cookie 模式继续")

    music_a = ""
    csrf = ""
    for item in (reg_sc or []):
        first = item.split(";", 1)[0].strip()
        if first.startswith("MUSIC_A="):
            music_a = first[8:]
        elif first.startswith("__csrf="):
            csrf = first[7:]
    if not music_a:
        logger.warning(f"[网易云扫码] 匿名注册未返回 MUSIC_A（body={reg_body}），退化最小 cookie 模式继续")

    # 即便没有 MUSIC_A 也尝试拿 unikey：实测 unikey 明文接口不需要 MUSIC_A 也能返回 200
    cookie = _build_qr_cookie(device_id, music_a, csrf) if music_a else ""
    try:
        body, sc = await _api_post("/api/login/qrcode/unikey", {"type": 3}, cookie=cookie)
    except Exception as e:
        logger.error(f"[网易云扫码] 获取 unikey 失败: {e}\n{traceback.format_exc()}")
        return None, "", "", ""
    unikey = _dig(body, ("data", "unikey")) or body.get("unikey")
    if not unikey:
        logger.error(f"[网易云扫码] unikey 响应异常，body={body}")
        return None, "", "", ""
    return unikey, device_id, music_a, csrf


async def qr_login_check_direct(unikey: str, device_id: str = "", music_a: str = "", csrf: str = "") -> dict:
    """direct 模式：轮询扫码状态。返回 {code, message, cookie}。异常返回 {code:-1}。

    device_id / music_a / csrf：由 qr_login_key_direct 返回的匿名设备会话信息。
    """
    import traceback

    if not device_id:
        logger.warning("[网易云扫码] 轮询缺少 device_id，扫码会话不完整")
        return {"code": -1, "message": "扫码会话不完整"}
    # 退化模式（无 MUSIC_A）下用最小 cookie，与 qr_login_key_direct 保持一致
    cookie = _build_qr_cookie(device_id, music_a, csrf) if music_a else ""
    try:
        body, sc = await _api_post(
            "/api/login/qrcode/client/login", {"key": unikey, "type": 3}, cookie=cookie
        )
    except Exception as e:
        logger.error(f"[网易云扫码] 轮询失败: {e}\n{traceback.format_exc()}")
        return {"code": -1, "message": str(e)}
    login_cookie = _extract_netease_cookie(sc)
    return {
        "code": body.get("code"),
        "message": body.get("message") or body.get("msg"),
        "cookie": login_cookie,
    }


# ---------------------------------------------------------------------------
# 扫码登录（v1.9.6 新增，custom 后端兼容：自建 NeteaseCloudMusicApi）
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

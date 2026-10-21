# -*- coding: utf-8 -*-
"""积分排行用的用户头像：QQ 头像直链 + 并发下载 + 内存缓存。

只对「平台 ID 看起来是 QQ/OneBot 且 uid 是纯数字」的用户取头像。
其它平台（Telegram / 微信 / 飞书等）没有稳定的公开头像接口，
卡片里会自动回退成「名字首字」圆标，不影响排版。

为什么下载后内联成 data URI，而不是让 Chromium 直接加载 URL：
  1. 头像接口偶尔很慢，截图时可能还没加载完，出现空白/破图；
  2. 内联后卡片渲染完全离线、可重复（同一张卡片缓存也更有意义）；
  3. 失败的用户直接走首字占位，不会在图上留下破图图标。
"""
from __future__ import annotations

import base64
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import requests

from .constants import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TTL = 6 * 3600          # 成功头像缓存 6 小时
_FAIL_TTL = 600          # 失败 10 分钟后重试
_TIMEOUT = 2.5           # 单个头像请求超时
_BATCH_TIMEOUT = 5.0     # 整批头像最多等多久，避免拖慢指令响应

_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()

# 平台 ID 里出现这些关键字就按 QQ 处理
_QQ_HINTS = ("aiocqhttp", "onebot", "cqhttp", "qq", "napcat", "lagrange")
# QQ 官方机器人没有 QQ 号头像，别去猜
_NOT_QQ_HINTS = ("official", "guild")
# 明确是其它平台的实例，即使被误传进 qq_platforms 也不取 QQ 头像
_OTHER_PLATFORM_HINTS = ("telegram", "discord", "slack", "lark", "feishu",
                         "wecom", "weixin", "webchat", "dingtalk", "kook")


def split_key(key: str) -> tuple[str, str]:
    """把 'platform:uid' 拆成 (platform, uid)。"""
    platform, _, uid = (key or "").partition(":")
    return platform, uid


def is_qq_platform(platform: str) -> bool:
    p = (platform or "").lower()
    if any(k in p for k in _NOT_QQ_HINTS):
        return False
    if any(k in p for k in _OTHER_PLATFORM_HINTS):
        return False
    return any(k in p for k in _QQ_HINTS)


def is_qq_key(key: str, qq_platforms=None) -> bool:
    """判断某个积分键是否属于 QQ 账号。

    qq_platforms 用于兜底：AstrBot 里平台实例 ID 允许自定义
    （如 "muli"、"qq-main"），不一定含 aiocqhttp 关键字，
    所以调用方可以传入「平台管理器里识别出的 QQ 实例 ID 集合」。
    """
    platform, uid = split_key(key)
    if not uid.isdigit():
        return False
    low = (platform or "").lower()
    if any(k in low for k in _NOT_QQ_HINTS + _OTHER_PLATFORM_HINTS):
        return False
    if qq_platforms and platform in qq_platforms:
        return True
    return is_qq_platform(platform)


def avatar_url(key: str, size: int = 140, qq_platforms=None) -> str:
    """QQ 用户返回头像直链；其它平台返回空串。"""
    if not is_qq_key(key, qq_platforms):
        return ""
    _platform, uid = split_key(key)
    return f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s={int(size)}"


def _candidate_urls(uid: str, size: int) -> list[str]:
    """腾讯头像 CDN 的三个常用入口，任意一个通就能出图。"""
    n = int(size)
    return [
        f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s={n}",
        f"https://q2.qlogo.cn/headimg_dl?dst_uin={uid}&spec={n}",
        f"https://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec={n}",
    ]


def _looks_like_image(raw: bytes) -> bool:
    if not raw or len(raw) < 200:
        return False
    return (raw[:3] == b"\xff\xd8\xff"          # jpeg
            or raw[:8] == b"\x89PNG\r\n\x1a\n"   # png
            or raw[:6] in (b"GIF87a", b"GIF89a")
            or raw[:4] == b"RIFF")               # webp


def _download(url: str) -> str:
    """下载并转 data URI；失败返回空串。"""
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT,
                         allow_redirects=True)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[头像] 请求异常 {url}: {type(e).__name__}: {e}")
        return ""
    if r.status_code != 200:
        logger.debug(f"[头像] HTTP {r.status_code} {url}")
        return ""
    if not _looks_like_image(r.content):
        logger.debug(f"[头像] 响应不是图片 len={len(r.content)} "
                     f"ctype={r.headers.get('Content-Type')} {url}")
        return ""
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "png" in ctype:
        mime = "image/png"
    elif "webp" in ctype:
        mime = "image/webp"
    elif "gif" in ctype:
        mime = "image/gif"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(r.content).decode("ascii")


def avatar_data_url(key: str, qq_platforms=None) -> str:
    """带缓存地取单个头像。"""
    if not is_qq_key(key, qq_platforms):
        return ""
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[1] < _TTL:
            return hit[0]
    _platform, uid = split_key(key)
    data = ""
    for url in _candidate_urls(uid, 140):
        data = _download(url)
        if data:
            break
    with _lock:
        _cache[key] = (data, now if data else now - _TTL + _FAIL_TTL)
    return data


def fetch_avatars(keys: list[str], workers: int = 6,
                  qq_platforms=None) -> dict[str, str]:
    """并发取头像，返回 {key: data_url}（取不到的不在结果里）。"""
    wanted = [k for k in dict.fromkeys(keys or []) if is_qq_key(k, qq_platforms)]
    if not wanted:
        if keys:
            logger.info(f"[头像] 未识别出 QQ 账号，跳过。"
                        f"平台实例={sorted(qq_platforms) if qq_platforms else '无'}"
                        f" 示例键={list(keys)[:3]}")
        return {}
    out: dict[str, str] = {}
    pool = ThreadPoolExecutor(max_workers=min(workers, len(wanted)))
    try:
        futures = {pool.submit(avatar_data_url, k, qq_platforms): k for k in wanted}
        done, pending = wait(futures, timeout=_BATCH_TIMEOUT)
        for fut in done:
            if fut.cancelled() or fut.exception():
                continue
            data = fut.result()
            if data:
                out[futures[fut]] = data
        if pending:
            logger.warning(f"[头像] {len(pending)} 个请求超时（>{_BATCH_TIMEOUT}s），"
                           f"本次先用首字占位")
    finally:
        # 不等待超时的请求，避免拖住整条指令
        pool.shutdown(wait=False, cancel_futures=True)
    logger.info(f"[头像] 命中 {len(out)}/{len(wanted)} 个"
                f"（QQ 实例 {sorted(qq_platforms) if qq_platforms else '按名称猜测'}）")
    if not out:
        logger.warning("[头像] 全部获取失败：①若上面显示「未识别出 QQ 账号」，"
                       "说明该平台不是 aiocqhttp/OneBot（QQ 官方机器人没有头像接口）；"
                       "②若能识别但取不到，请检查服务器能否访问 q1.qlogo.cn / q.qlogo.cn")
    return out

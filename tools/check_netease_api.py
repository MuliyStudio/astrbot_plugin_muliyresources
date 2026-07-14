#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自建 NeteaseCloudMusicApi 后端可用性自测脚本
============================================

用途：
    检测「当前运行环境」能否正常调用自建的 NeteaseCloudMusicApi 实例，
    该实例是插件网易云语音名片功能的唯一解析后端（wyapi / qzxdp 公共站已移除）。

    会依次检测：
      - GET /song/url?id=<song>&level=<type>   -> 取播放直链
      - GET /song/detail?ids=[<song>]          -> 取歌名 / 歌手 / 专辑（可选）

用法：
    python tools/check_netease_api.py --url http://127.0.0.1:3000
    python tools/check_netease_api.py --url http://127.0.0.1:3000 --song 28921655
    python tools/check_netease_api.py --url http://127.0.0.1:3000 --music-type lossless

说明：
    - 仅使用 Python 标准库（urllib），无需安装任何依赖。
    - 会先尝试显示当前出口公网 IP（用于判断是否处于特殊网络环境）。
    - 结果会明确给出：✅ 可用 / ❌ 不可用（含具体原因）。
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_SONG = "28921655"  # 示例歌曲 ID（仅用于探测接口是否存活）

# 用于探测公网出口 IP 的公共服务（任意一个可达即可）
IP_ECHO_URLS = [
    "https://ifconfig.me/ip",
    "https://api.ipify.org",
    "https://myip.ipip.net",
]


def _http(method, url, headers=None, timeout=20):
    """极简同步 HTTP 请求，返回 (status_code, text, error)。"""
    req = urllib.request.Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, body, None
    except Exception as e:  # 网络不可达、超时、SSL 等
        return None, "", str(e)


def show_public_ip():
    print("🌐 当前出口公网 IP：", end="", flush=True)
    for url in IP_ECHO_URLS:
        code, text, err = _http("GET", url, timeout=8)
        if code == 200 and text.strip():
            print(text.strip())
            return
    print("(无法获取，可能服务器无外网 / 被墙，但这不影响本次检测结论)")


def _extract(obj, *path):
    cur = obj
    for k in path:
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


def test_instance(base, song_id, music_type):
    """检测自建 NeteaseCloudMusicApi（/song/url?id= + /song/detail?ids=）。"""
    base = base.rstrip("/")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
    print(f"\n🔍 检测 [自建 NeteaseCloudMusicApi @ {base}]")

    # 1) 播放直链
    url = f"{base}/song/url?id={song_id}&level={music_type}"
    print(f"   GET {url}")
    code, text, err = _http("GET", url, headers=headers, timeout=20)
    if err:
        print(f"   ❌ 网络层失败：{err}")
        return False
    print(f"   HTTP 状态码：{code}")
    if code != 200:
        print(f"   ❌ 接口返回 {code}，实例可能未启动 / 地址错误 / 端口未暴露。")
        if text:
            print(f"   响应片段：{text[:160].replace(chr(10), ' ')}")
        return False
    try:
        payload = json.loads(text)
    except Exception:
        print("   ⚠️ 返回非 JSON，实例可能不是 NeteaseCloudMusicApi。")
        return False
    mp3 = _extract(payload, "data", 0, "url") or _extract(payload, "data", "url")
    if not mp3:
        print("   ⚠️ 返回 200 但无直链字段（可能该曲需 VIP 或字段变化）。")
        return False
    print(f"   ✅ 直链可用！音频直链已返回（长度 {len(mp3)} 字符）。")

    # 2) 元数据（可选，失败不影响直链可用性）
    detail_url = f"{base}/song/detail?ids=[{song_id}]"
    print(f"   GET {detail_url}")
    c2, t2, e2 = _http("GET", detail_url, headers=headers, timeout=20)
    if e2 or c2 != 200:
        print("   ⚠️ 元数据接口未通过（不影响发语音，但名片可能缺歌名/歌手）。")
        return True
    try:
        info = json.loads(t2)
        name = _extract(info, "songs", 0, "name")
        if name:
            print(f"   ✅ 元数据可用，示例：《{name}》")
    except Exception:
        print("   ⚠️ 元数据返回非 JSON。")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="自建 NeteaseCloudMusicApi 后端可用性自测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", required=True, help="自建 NeteaseCloudMusicApi 实例地址，如 http://127.0.0.1:3000")
    parser.add_argument("--song", default=DEFAULT_SONG, help=f"探测用歌曲 ID（默认 {DEFAULT_SONG}）")
    parser.add_argument("--music-type", default="standard", help="音质（standard/exhigh/lossless…）")
    args = parser.parse_args()

    print("=" * 60)
    print("  自建 NeteaseCloudMusicApi 后端可用性自测")
    print("=" * 60)
    show_public_ip()

    ok = test_instance(args.url, args.song, args.music_type)

    print("\n" + "=" * 60)
    print("  结论与部署建议")
    print("=" * 60)
    if ok:
        print("✅ 自建后端可用，保持插件配置 wyy_custom_url =", args.url, "即可稳定使用。")
    else:
        print("❌ 自建后端不可用。请检查：")
        print("   1) 实例是否已启动：docker compose -f tools/netease-api/docker-compose.yml ps")
        print("   2) 地址/端口是否正确，跨机请用 http://<局域网IP>:3000")
        print("   3) 插件配置 wyy_custom_url 是否与该地址一致")
        print("   参考：https://github.com/Binaryify/NeteaseCloudMusicApi")

    print("\n提示：本机还需安装 ffmpeg 才能截取『60 秒高潮片段』，"
          "否则插件会退化为发送完整音频。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

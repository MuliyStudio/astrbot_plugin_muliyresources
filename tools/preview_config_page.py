# -*- coding: utf-8 -*-
"""本地预览可视化配置页（不启动 AstrBot）。

用法：
    python tools/preview_config_page.py [端口]

打开 http://127.0.0.1:8765/ 即可交互预览。脚本会注入一个假的
window.AstrBotPluginView，让页面在没有 AstrBot 的情况下也能读写示例配置。
仅用于开发预览，不会打包进插件。
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE_DIR = os.path.join(ROOT, "pages", "config")

GROUP_ORDER = [
    "game", "software", "movie", "shortdrama", "novel", "music",
    "vip_video", "points", "verify", "minigame", "list_card", "browser",
]
GROUP_ICONS = {
    "game": "gamepad", "software": "package", "movie": "movie",
    "shortdrama": "tv", "novel": "book", "music": "music",
    "vip_video": "play", "points": "star", "verify": "verified",
    "minigame": "casino", "list_card": "image", "browser": "globe",
}
FIELD_OPTIONS = {
    "game_source": [
        {"value": "auto", "label": "自动（推荐）"},
        {"value": "xdgame", "label": "xdgame"},
        {"value": "switch618", "label": "switch618"},
    ],
    "movie_source": [
        {"value": "", "label": "new · pdy0（默认）"},
        {"value": "new", "label": "new · pdy0"},
        {"value": "old", "label": "old · 片库主站"},
    ],
    "wyy_backend": [
        {"value": "direct", "label": "direct · 内置直连（推荐）"},
        {"value": "custom", "label": "custom · 自建接口"},
    ],
    "wyy_music_type": [
        {"value": "standard", "label": "standard · 标准"},
        {"value": "exhigh", "label": "exhigh · 较高"},
        {"value": "lossless", "label": "lossless · 无损"},
        {"value": "hires", "label": "hires · Hi-Res"},
        {"value": "sky", "label": "sky · 沉浸环绕"},
        {"value": "jymaster", "label": "jymaster · 超清母带"},
    ],
    "wyy_audio_format": [
        {"value": "mp3", "label": "mp3 · 兼容好（推荐）"},
        {"value": "wav", "label": "wav"},
    ],
    "checkin_info_module": [
        {"value": "epic", "label": "Epic 喜加一（推荐）"},
        {"value": "history", "label": "历史上的今天"},
        {"value": "poem", "label": "今日诗词"},
        {"value": "weather", "label": "实时天气"},
        {"value": "off", "label": "关闭"},
    ],
    "browser_channel": [
        {"value": "", "label": "自动（插件自带 Chromium）"},
        {"value": "chrome", "label": "本机 Chrome"},
    ],
    "movie_sections": [
        {"value": "mv", "label": "电影"},
        {"value": "tv", "label": "剧集"},
        {"value": "ac", "label": "动漫"},
    ],
    "sonovel_format": [
        {"value": "txt", "label": "TXT"},
        {"value": "epub", "label": "EPUB"},
        {"value": "html", "label": "HTML"},
        {"value": "pdf", "label": "PDF"},
    ],
}
SECRET_HINTS = ("password", "cookie", "token", "secret", "api_key", "apikey")

SAMPLE = {
    "game_group_ids": ["123456789"],
    "movie_group_ids": ["987654321", "123123123"],
    "group_ids": ["123456789"],
    "drama_group_ids": ["456789123"],
    "movie_sections": ["mv", "tv", "ac"],
    "sonovel_format": ["txt", "epub"],
    "wyy_music_type": "exhigh",
    "wyy_audio_format": "mp3",
    "points_enabled": True,
    "checkin_points": 20,
    "checkin_streak_bonus": 2,
    "checkin_recommend_games": [
        "黑神话：悟空|国产动作大作，战斗手感扎实",
        "塞尔达传说：王国之泪|开放世界探索，随便逛都能玩很久",
        "双人成行|双人合作解谜，适合和朋友一起",
    ],
    "minigame_enabled": True,
    "join_verify_enabled": False,
    "browser_channel": "",
    "game_source": "auto",
    "movie_source": "new",
    "wyy_backend": "direct",
}


def long_list(value) -> bool:
    return isinstance(value, list) and bool(value) and max(len(str(x)) for x in value) > 16


def load_groups():
    with open(os.path.join(ROOT, "_conf_schema.json"), encoding="utf-8") as f:
        schema = json.load(f)
    order = [g for g in GROUP_ORDER if g in schema]
    order += [g for g in schema if g not in order]
    groups = []
    for gkey in order:
        group = schema[gkey]
        fields = []
        for fkey, field in (group.get("items") or {}).items():
            ftype = field.get("type", "string")
            default = field.get("default")
            value = SAMPLE.get(fkey, default)
            if ftype == "list" and isinstance(value, str):
                value = [x.strip() for x in re.split(r"[,，]", value) if x.strip()]
            fields.append({
                "key": fkey,
                "type": ftype,
                "label": field.get("description", fkey),
                "hint": field.get("hint", ""),
                "default": default,
                "value": value,
                "min": field.get("min"),
                "max": field.get("max"),
                "condition": field.get("condition") or {},
                "options": FIELD_OPTIONS.get(fkey),
                "secret": any(h in fkey.lower() for h in SECRET_HINTS),
                "long_items": ftype == "list" and long_list(default),
            })
        groups.append({
            "key": gkey,
            "title": group.get("description", gkey),
            "hint": group.get("hint", ""),
            "icon": GROUP_ICONS.get(gkey, "apps"),
            "fields": fields,
        })
    return groups


def build_payload():
    groups = load_groups()
    meta = {
        "plugin_name": "astrbot_plugin_muliyresources",
        "display_name": "暮黎资源聚合",
        "version": "1.17.0",
        "description": "影视 / 游戏 / 软件 / 短剧 / 小说 多源搜索与定时日报",
        "timezone": "Asia/Shanghai",
        "data_dir": r"D:\AstrBot\data\plugin_data\astrbot_plugin_muliyresources",
        "config_backup": r"D:\AstrBot\data\plugin_data\astrbot_plugin_muliyresources\config_override.json",
        "scheduler_mode": "framework",
        "scheduler_running": True,
        "schedules": [
            {"key": "software", "name": "软件日报", "enabled": True, "hour": 22,
             "minute": 0, "groups": 0, "all_groups": True, "next": "2026-10-26 22:00"},
            {"key": "game", "name": "游戏日报", "enabled": True, "hour": 23,
             "minute": 0, "groups": 1, "all_groups": False, "next": "2026-10-26 23:00"},
            {"key": "movie", "name": "影视日报", "enabled": True, "hour": 20,
             "minute": 0, "groups": 2, "all_groups": False, "next": "2026-10-26 20:00"},
            {"key": "drama", "name": "短剧日报", "enabled": True, "hour": 21,
             "minute": 0, "groups": 1, "all_groups": False, "next": "2026-10-26 21:00"},
        ],
        "features": [
            {"key": "list_card", "label": "长列表图片", "enabled": True},
            {"key": "points", "label": "签到积分", "enabled": True},
            {"key": "music", "label": "网易云名片", "enabled": True},
            {"key": "vip_video", "label": "VIP 视频解析", "enabled": True},
            {"key": "verify", "label": "入群审核", "enabled": False},
            {"key": "minigame", "label": "群聊小游戏", "enabled": True},
        ],
        "group_count": len(groups),
        "field_count": sum(len(g["fields"]) for g in groups),
    }
    return {"status": "ok", "data": {"groups": groups, "meta": meta}}


MOCK_JS = r"""
<script>
(function () {
  const payload = __PAYLOAD__;
  const ctx = {
    pluginName: "astrbot_plugin_muliyresources",
    displayName: "暮黎资源聚合",
    pageName: "config",
    pageTitle: "暮黎资源聚合控制台",
    locale: "zh-CN",
    isDark: false,
  };
  const listeners = [];
  window.AstrBotPluginView = window.AstrBotPluginPage = {
    ready: function () { return Promise.resolve(ctx); },
    getContext: function () { return ctx; },
    getLocale: function () { return "zh-CN"; },
    getI18n: function () { return {}; },
    t: function (key, fallback) { return fallback; },
    onContext: function (fn) { listeners.push(fn); return function () {}; },
    apiGet: function (endpoint, params) {
      if (endpoint === "config-view") {
        return Promise.resolve(JSON.parse(JSON.stringify(payload)));
      }
      return Promise.reject(new Error("unknown endpoint: " + endpoint));
    },
    apiPost: function (endpoint, body) {
      if (endpoint === "config-view/save") {
        const values = (body && body.values) || {};
        for (const group of payload.data.groups) {
          for (const field of group.fields) {
            if (Object.prototype.hasOwnProperty.call(values, field.key)) {
              field.value = values[field.key];
            }
          }
        }
        return Promise.resolve({ status: "ok", data: {
          saved: Object.keys(values).length,
          schedule_reloaded: ["schedule_hour", "game_schedule_hour"].some(function (k) {
            return Object.prototype.hasOwnProperty.call(values, k);
          }),
          values: values,
        }});
      }
      return Promise.reject(new Error("unknown endpoint: " + endpoint));
    },
  };
})();
</script>
"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/pages/config/")
            self.end_headers()
            return
        if path in ("/pages/config/", "/pages/config/index.html"):
            with open(os.path.join(PAGE_DIR, "index.html"), encoding="utf-8") as f:
                html = f.read()
            mock = MOCK_JS.replace("__PAYLOAD__", json.dumps(build_payload(), ensure_ascii=False))
            html = html.replace("</head>", mock + "</head>")
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"预览地址：http://127.0.0.1:{port}/")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

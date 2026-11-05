# -*- coding: utf-8 -*-
"""
暮黎资源聚合 AstrBot 插件 v1.7.0
=================================
整合影视搜索 + 游戏搜索 + 软件日报&搜索

core/constants.py  — 常量定义
core/session.py    — 会话管理器
core/game.py       — 游戏搜索相关函数
core/software.py   — 软件日报&搜索相关函数
core/movie.py      — 旧 a123tv 影视搜索函数（已停用，仅保留兼容）
"""

import asyncio, base64, concurrent.futures, copy, datetime, io, json, os, random, re, sys, tempfile, time, traceback, zipfile, zoneinfo
from html import escape
from typing import Optional

try:
    import requests
except ImportError: requests = None
try:
    from bs4 import BeautifulSoup
except ImportError: BeautifulSoup = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image as ImageComponent, File as FileComponent
from astrbot.api import logger  # 使用 AstrBot 提供的 logger 接口，日志才会在控制台与 Web 日志页显示
try:
    from astrbot.api.message_components import Record, Json, At
except ImportError:  # 旧版 AstrBot 可能未导出这些组件
    Record = Json = At = None
try:
    from astrbot.core.message.components import Node, Nodes
except ImportError: Node = Nodes = None
try:
    from astrbot.core.utils.session_waiter import SessionController, session_waiter
except ImportError:
    SessionController = None
    session_waiter = None

from .core.constants import *
from .core.constants import parse_cookie_string
from .core.session import SessionManager, SearchSessionManager
from .core.game import search_games, get_game_detail, resolve_download_link, generate_game_html, check_cookie
from .core.switch618 import (
    search_games_618, get_game_detail_618, resolve_download_link_618,
    check_618_cookie, get_qr_image_bytes, submit_618_login, get_today_games_618,
    get_random_game_618,
)
from .core.qr_login import (
    format_cookie_string, extract_xdgame_cookies,
    login_with_password_async, submit_captcha_async,
)
from .core.software import (
    search_software, get_search_detail, generate_search_html,
    get_software_list, get_detail, sync_scrape, gen_list_image, gen_report_zip,
    build_summer_html, download_summer_assets, get_random_software_recent,
)
from .core.game_daily import (
    get_today_games, build_cartoon_html, render_html_to_png, get_random_game_xdgame,
)
from .core.movie_daily import (
    fetch_movie_daily, fetch_movie_daily_auto, fetch_movie_daily_pdy,
    build_glass_html, render_glass_to_png, gen_report_zip as gen_movie_report_zip,
    get_random_movie_muliy,
)
from .core.pdy_site import (
    PdySiteClient, PdyCaptchaRequired, PDY_BASE_URL, PDY_RELEASE_URL, discover_domains,
)
from .core.shortdrama import (
    search_dramas, get_drama_detail, fetch_latest_dramas,
    build_drama_html, render_drama_to_png, gen_report_zip as gen_drama_report_zip,
    DRAMA_BASE,
)
try:
    from .core.report_pil import render_pil_report, trim_uniform_bottom
except ImportError:
    render_pil_report = None
    trim_uniform_bottom = None
try:
    from .core.list_card import (
        novel_card_html, pan_card_html, points_card_html, points_rank_html,
        game_card_html, software_card_html, movie_card_html,
        movie_new_card_html, drama_card_html, episode_card_html,
        minigame_result_card_html, minigame_lobby_html,
        minigame_bomb_wait_html, minigame_cover_pick_html,
        minigame_cover_question_html, movie_detail_card_html,
        minigame_uc_join_html, minigame_uc_round_html,
        minigame_uc_vote_html, minigame_uc_tally_html,
        minigame_uc_result_html,
        game_detail_card_html, software_detail_card_html,
        render_list_card, prewarm as prewarm_list_card,
    )
except ImportError:  # 缺 playwright 时也要能正常加载插件（列表自动回退文本）
    novel_card_html = pan_card_html = points_card_html = points_rank_html = None
    game_card_html = software_card_html = movie_card_html = None
    movie_new_card_html = drama_card_html = episode_card_html = None
    minigame_result_card_html = minigame_lobby_html = None
    minigame_bomb_wait_html = minigame_cover_pick_html = None
    minigame_cover_question_html = movie_detail_card_html = None
    minigame_uc_join_html = minigame_uc_round_html = None
    minigame_uc_vote_html = minigame_uc_tally_html = None
    minigame_uc_result_html = None
    game_detail_card_html = software_detail_card_html = None
    render_list_card = prewarm_list_card = None
from .core.episode_utils import (
    episode_display_name, episode_page_size, episode_pages,
    format_episode_list, node_episodes, normalize_ep_page,
)
from .core.minigame import (
    BombGame, COVER_KINDS, MiniGameStore, cleanup_cover_cache,
    fetch_cover_bytes, fetch_pool, normalize_choice, pick_question,
    pillow_available, read_pool_cache, save_pool_cache,
)
from .core.undercover import (
    ROLE_CIVIL, ROLE_SPY, UndercoverGame, load_pairs, pair_key, pick_pair,
)
from .core.movie import (
    search_movies, get_movie_detail, get_random_movie,
    format_movie_list, format_episodes, format_sources,
    select_episode, select_source,
    parse_play_page, build_play_url,
    MV_BASE_URL,
)
from .core.novel import (
    search_novels, fetch_novel, download_novel, download_novel_file,
    check_sources, NovelApiError, NOVEL_FORMATS,
)
from .core.muliy_site import (
    MuliySiteClient, discover_best_domain, set_release_url, cover_url as muliy_cover_url,
    play_url as muliy_play_url, format_movie_list_new, format_resource_type,
    format_play_nodes, format_pan_list, format_pan_types, group_panlist_by_type,
    extract_pwd, build_merged_text,
)
from .core.pan_health import (
    PanReportStore, annotate_panlist, check_pan_link, check_many,
)

from .core.netease import (
    NeteaseParser, extract_netease_id, extract_from_miniapp,
    looks_like_netease, resolve_shortlink, download_mp3,
    normalize_api_base, qr_login_key, qr_login_create, qr_login_check,
    qrimg_to_bytes, extract_music_cookie, get_login_nickname,
    qr_login_key_direct, qr_login_check_direct, build_qr_url, qr_url_to_png,
)
from .core.audio_clip import ffmpeg_available, get_duration_seconds, compute_clip_range, cut_clip
from .core.vip_capture import (
    is_vip_video_url, analyze_vip_link, build_interface_link,
    verify_interface_playable, fetch_muliy_interfaces, VIP_INTERFACES,
    resolve_iqiyi_share, is_iqiyi_share_url, follow_iqiyi_redirect,
    normalize_video_url,
)
from .core.petpet import (
    PIL_AVAILABLE as PETPET_PIL_AVAILABLE,
    generate_petpet_from_avatar, generate_petpet,
    download_avatar_by_platform,
)
from .core.lickdog import (
    PIL_AVAILABLE as LICKDOG_PIL_AVAILABLE,
    generate_lickdog,
)
from .core.massage import (
    PIL_AVAILABLE as MASSAGE_PIL_AVAILABLE,
    generate_massage,
)
from .core.verify import (
    PIL_AVAILABLE as VERIFY_PIL_AVAILABLE,
    generate_arithmetic, render_captcha,
)
from .core.points import PointsStore
from .core.avatars import fetch_avatars as fetch_point_avatars, split_key as split_point_key
from .core.checkin_card import (
    build_checkin_html, fetch_bing_wallpaper, fetch_hitokoto, fetch_weather,
    fetch_info, pick_recommendations, recommendation_text, render_checkin_png,
    DEFAULT_RECOMMEND_GAMES, DEFAULT_RECOMMEND_SOFTWARE, DEFAULT_RECOMMEND_MOVIES,
)

def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    if size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    return f"{size_bytes/(1024*1024):.1f} MB"


def _img_ext(img_bytes: bytes) -> str:
    """根据图片字节魔数判断扩展名（PNG/JPEG），用于以文件形式发送日报图时命名。

    渲染器输出 PNG，游戏日报压缩后输出 JPEG，故以内容而非后缀为准。
    """
    if img_bytes and img_bytes[:4] == b"\x89PNG":
        return ".png"
    return ".jpg"


def _parse_movie_meta_json(text: str):
    """从 LLM 返回的文本里抠出 {"cast":"...", "desc":"..."}。
    失败 → ("", "")。"""
    import json as _json, re as _re
    if not text:
        return ("", "")
    m = _re.search(r"\{[\s\S]*?\}", text)
    if not m:
        # 截短兜底：把整段当 desc
        return ("", text.strip()[:200])
    try:
        data = _json.loads(m.group(0))
        return (str(data.get("cast", "") or ""), str(data.get("desc", "") or ""))
    except Exception:
        return ("", "")


def _parse_audit_json(text: str):
    """从大模型返回的文本里抠出 {"allowed":bool,"reason":str,"intent":str}。
    解析失败/字段异常 → 默认放行 (True, "", "")，避免审核异常阻断正常搜索。"""
    import json as _json, re as _re
    if not text:
        return True, "", ""
    m = _re.search(r"\{[\s\S]*?\}", text)
    if not m:
        return True, "", ""
    try:
        data = _json.loads(m.group(0))
        raw = data.get("allowed", True)
        # 兼容大模型把 allowed 返回为字符串 "true"/"false" 的情况
        if isinstance(raw, str):
            allowed = raw.strip().lower() in ("true", "1", "yes", "y", "是")
        else:
            allowed = bool(raw)
        reason = str(data.get("reason", "") or "")
        intent = str(data.get("intent", "") or "")
        return allowed, reason, intent
    except Exception:
        return True, "", ""


# 配置分组映射：分组键 -> 其下叶子配置键（与 _conf_schema.json 的 object 分组保持一致）
# 顶层三大功能分类：game(游戏) / software(软件) / movie(影视)；
# 跨功能辅助分类：music(网易云音乐) / vip_video(VIP视频解析) / browser(浏览器) / novel(小说, so-novel)
# 用途：① _get_config 把嵌套分组展开为扁平视图（旧读取代码 config.get("leaf") 无需改动）
#       ② _update_config 把回写的值放回到正确的嵌套分组中
#       ③ _migrate_config 把任意旧结构配置按叶子键重归类，兼容升级
_CONF_GROUPS = {
    "game": [
        "game_source", "max_search_results",
        "game_report_enabled", "game_report_max",
        "game_schedule_hour", "game_schedule_minute", "game_group_ids",
        "xdgame_username", "xdgame_password", "cookie", "switch618_cookie",
    ],
    "software": ["schedule_hour", "schedule_minute", "group_ids"],
    "movie": [
        "movie_source", "pdy_auto_captcha", "muliy_cache_ttl", "muliy_release_url",
        "pan_expiry_hint", "pan_link_check", "pan_link_scan",
        "movie_report_enabled", "movie_report_max",
        "movie_schedule_hour", "movie_schedule_minute", "movie_group_ids", "movie_sections",
        "muliy_username", "muliy_password", "muliy_cookie",
    ],
    "music": [
        "wyy_auto_parse", "wyy_backend", "wyy_music_type", "wyy_custom_url",
        "wyy_clip_seconds", "wyy_audio_format", "wyy_cookie", "wyy_proxy",
    ],
    "shortdrama": [
        "drama_enabled", "drama_search_limit",
        "drama_report_enabled", "drama_report_max",
        "drama_schedule_hour", "drama_schedule_minute", "drama_group_ids",
        "drama_timeout",
    ],
    "vip_video": ["video_vip_parse", "video_vip_timeout"],
    "browser": ["browser_channel", "browser_exe"],
    "verify": [
        "join_verify_enabled", "join_verify_group_ids", "join_verify_timeout",
        "join_verify_max_attempts", "join_verify_recall", "join_verify_kick",
        "join_verify_welcome_text",
    ],
    "novel": [
        "sonovel_base_url", "sonovel_token", "sonovel_search_limit",
        "sonovel_format", "sonovel_timeout", "sonovel_download_timeout",
    ],
    "list_card": ["list_card_enabled", "list_card_threshold"],
    "minigame": [
        "minigame_enabled", "minigame_group_ids", "minigame_points_reward",
        "minigame_daily_cap", "minigame_bomb_timeout",
        "minigame_bomb_turn_timeout",
        "minigame_cover_rounds", "minigame_cover_timeout",
        "minigame_cover_pool_ttl", "minigame_cover_pixel",
        "minigame_uc_enabled", "minigame_uc_join_timeout",
        "minigame_uc_min_players", "minigame_uc_max_players",
        "minigame_uc_turn_timeout", "minigame_uc_vote_timeout",
        "minigame_uc_desc_max", "minigame_uc_spies",
        "minigame_uc_private_vote", "minigame_uc_reveal_role",
        "minigame_uc_word_level",
    ],
    "points": [
        "points_enabled", "points_initial", "checkin_points",
        "checkin_streak_bonus", "checkin_streak_max",
        "points_cost_game", "points_cost_software", "points_cost_movie",
        "points_cost_drama", "points_cost_novel",
        "checkin_card_enabled", "checkin_info_module", "checkin_weather_city",
        "checkin_recommend_dynamic",
        "checkin_recommend_games", "checkin_recommend_software", "checkin_recommend_movies",    ],
}
_KEY_TO_GROUP = {k: g for g, ks in _CONF_GROUPS.items() for k in ks}

# ========================================================================
#  可视化配置视图（AstrBot 插件页面）
# ========================================================================
# 页面按 _conf_schema.json 自动生成表单；下面只补充「更好看/更好填」的展示信息，
# 不改变配置结构，也不影响原配置页。
_VIEW_GROUP_ORDER = [
    "game", "software", "movie", "shortdrama", "novel", "music",
    "vip_video", "points", "verify", "minigame", "list_card", "browser",
]
_VIEW_GROUP_ICONS = {
    "game": "gamepad", "software": "package", "movie": "movie",
    "shortdrama": "tv", "novel": "book", "music": "music",
    "vip_video": "play", "points": "star", "verify": "verified",
    "minigame": "casino", "list_card": "image", "browser": "globe",
}
# 组内二级分类：同一组字段太多时按功能分块展示（未列出的字段作为「全局设置」放在框外）。
# 只影响可视化页面，不改变 _conf_schema.json 的结构。
_VIEW_SECTIONS = {
    "game": [
        {"key": "accounts", "title": "账号与 Cookie", "icon": "server",
         "hint": "xdgame 自动登录与两个搜索源的登录态",
         "keys": ["xdgame_username", "xdgame_password", "cookie",
                  "switch618_cookie"]},
        {"key": "daily", "title": "游戏日报", "icon": "spark",
         "hint": "定时推送、每期数量与推送群",
         "keys": ["game_report_enabled", "game_report_max",
                  "game_schedule_hour", "game_schedule_minute",
                  "game_group_ids"]},
    ],
    "software": [
        {"key": "daily", "title": "软件日报", "icon": "spark",
         "hint": "定时推送时间与推送群",
         "keys": ["schedule_hour", "schedule_minute", "group_ids"]},
    ],
    "movie": [
        {"key": "search", "title": "搜索与网盘", "icon": "search",
         "hint": "搜索源、验证码与网盘链接检测",
         "keys": ["movie_source", "pdy_auto_captcha", "pan_expiry_hint",
                  "pan_link_check", "pan_link_scan"]},
        {"key": "backup", "title": "片库主站（备用源）", "icon": "server",
         "hint": "备用源地址、登录态缓存与账号",
         "keys": ["muliy_release_url", "muliy_cache_ttl", "muliy_username",
                  "muliy_password", "muliy_cookie"]},
        {"key": "daily", "title": "影视日报", "icon": "spark",
         "hint": "板块、数量、推送时间与推送群",
         "keys": ["movie_report_enabled", "movie_report_max", "movie_sections",
                  "movie_schedule_hour", "movie_schedule_minute",
                  "movie_group_ids"]},
    ],
    "shortdrama": [
        {"key": "search", "title": "短剧搜索", "icon": "search",
         "hint": "搜索开关、结果上限与请求超时",
         "keys": ["drama_enabled", "drama_search_limit", "drama_timeout"]},
        {"key": "daily", "title": "短剧日报", "icon": "spark",
         "hint": "定时推送、每期数量与推送群",
         "keys": ["drama_report_enabled", "drama_report_max",
                  "drama_schedule_hour", "drama_schedule_minute",
                  "drama_group_ids"]},
    ],
    "novel": [
        {"key": "conn", "title": "连接设置", "icon": "server",
         "hint": "so-novel 服务地址与访问令牌",
         "keys": ["sonovel_base_url", "sonovel_token"]},
        {"key": "search", "title": "搜索与下载", "icon": "search",
         "hint": "默认格式、搜索上限与超时",
         "keys": ["sonovel_format", "sonovel_search_limit", "sonovel_timeout",
                  "sonovel_download_timeout"]},
    ],
    "music": [
        {"key": "parse", "title": "解析方式", "icon": "music",
         "hint": "语音名片开关、后端模式与自建接口",
         "keys": ["wyy_auto_parse", "wyy_backend", "wyy_custom_url"]},
        {"key": "audio", "title": "音质与时长", "icon": "bolt",
         "hint": "解析音质、语音格式与最大发送时长",
         "keys": ["wyy_music_type", "wyy_audio_format", "wyy_clip_seconds"]},
        {"key": "account", "title": "账号与网络", "icon": "server",
         "hint": "黑胶会员 Cookie 与请求代理",
         "keys": ["wyy_cookie", "wyy_proxy"]},
    ],
    "points": [
        {"key": "checkin", "title": "签到", "icon": "verified",
         "hint": "初始积分、每日签到与连续加成",
         "keys": ["points_initial", "checkin_points", "checkin_streak_bonus",
                  "checkin_streak_max"]},
        {"key": "card", "title": "签到卡片", "icon": "image",
         "hint": "卡片开关、左下模块与推荐清单",
         "keys": ["checkin_card_enabled", "checkin_info_module",
                  "checkin_weather_city", "checkin_recommend_dynamic",
                  "checkin_recommend_games", "checkin_recommend_software",
                  "checkin_recommend_movies"]},
        {"key": "cost", "title": "资源扣费", "icon": "bolt",
         "hint": "按资源类型设置获取时消耗的积分",
         "keys": ["points_cost_game", "points_cost_software",
                  "points_cost_movie", "points_cost_drama",
                  "points_cost_novel"]},
    ],
    "verify": [
        {"key": "rules", "title": "验证规则", "icon": "verified",
         "hint": "限时、答题次数与失败处理",
         "keys": ["join_verify_timeout", "join_verify_max_attempts",
                  "join_verify_recall", "join_verify_kick"]},
        {"key": "welcome", "title": "通过后的欢迎语", "icon": "spark",
         "hint": "验证通过时发送的文案",
         "keys": ["join_verify_welcome_text"]},
    ],
    "minigame": [
        {"key": "guess", "title": "猜数字", "icon": "casino",
         "hint": "组队等待与每回合限时",
         "keys": ["minigame_bomb_timeout", "minigame_bomb_turn_timeout"]},
        {"key": "cover", "title": "封面猜猜", "icon": "image",
         "hint": "题数、限时、题库缓存与马赛克强度",
         "keys": ["minigame_cover_rounds", "minigame_cover_timeout",
                  "minigame_cover_pool_ttl", "minigame_cover_pixel"]},
        {"key": "undercover", "title": "谁是卧底", "icon": "eye",
         "hint": "报名、人数、描述、投票与词库难度",
         "keys": ["minigame_uc_enabled", "minigame_uc_join_timeout",
                  "minigame_uc_min_players", "minigame_uc_max_players",
                  "minigame_uc_turn_timeout", "minigame_uc_vote_timeout",
                  "minigame_uc_desc_max", "minigame_uc_spies",
                  "minigame_uc_private_vote", "minigame_uc_reveal_role",
                  "minigame_uc_word_level"]},
    ],
}
# string 字段的推荐值（页面渲染为下拉框）；list 字段为多选。
_VIEW_FIELD_OPTIONS = {
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
# 多选字段允许的值（后端仍会校验，避免手改 API 写入脏数据）
_VIEW_LIST_CHOICES = {
    "movie_sections": {"mv", "tv", "ac"},
    "sonovel_format": {"txt", "epub", "html", "pdf"},
}
# 改动这些键后需要重新注册定时任务
_VIEW_SCHEDULE_KEYS = {
    "schedule_hour", "schedule_minute",
    "game_report_enabled", "game_schedule_hour", "game_schedule_minute",
    "movie_report_enabled", "movie_schedule_hour", "movie_schedule_minute",
    "drama_report_enabled", "drama_schedule_hour", "drama_schedule_minute",
}
# 敏感字段：页面默认隐藏明文（仍可点击眼睛显示）
_VIEW_SECRET_HINTS = ("password", "cookie", "token", "secret", "api_key", "apikey")

# 积分消耗类型 → 展示名（搜索类命令 / LLM 工具共用）
_POINTS_LABELS = {
    "game": "游戏",
    "software": "软件",
    "movie": "影视",
    "drama": "短剧",
    "novel": "小说",
}


# ========================================================================
#  AstrBot 插件类
# ========================================================================

@register("astrbot_plugin_muliyresources", "暮黎 Muliy",
          "暮黎资源聚合 - 影视搜索(pdy0/片库) / 游戏搜索 / 软件日报&搜索 / 短剧搜索&日报 / 小说搜索&下载 / 长列表出图 / 积分签到&管理 / 网易云语音名片 / 摸头杀GIF / 舔狗表情 / 入群审核", "1.17.5")
class MuliyResourcesPlugin(Star):

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        # 保留 AstrBot 的 AstrBotConfig 对象，可视化页面保存时直接写回
        # data/config/<插件名>_config.json（不能只写本地兜底文件）。
        self._raw_config = config
        self._plugin_config = self._migrate_config(config)
        self._sessions = SessionManager()
        self._search_sessions = SearchSessionManager()
        self._movie_sessions = SearchSessionManager()   # 影视会话（旧 a123tv 流程，仅保留兼容）
        self._movie_sessions_new = SearchSessionManager()  # 影视会话（pdy0 / 片库主站共用）
        self._novel_sessions = SearchSessionManager()  # 小说会话 (so-novel)
        self._drama_sessions = SearchSessionManager()  # 短剧会话 (wangpant8)
        self._muliy_client: MuliySiteClient | None = None  # 片库主站客户端（懒加载）
        self._pdy_client: PdySiteClient | None = None      # pdy0 客户端（懒加载）
        # 网盘资源过期反馈（实际点到失效链接后记录，列表评分/置底用）
        self._pan_reports: Optional[PanReportStore] = None
        # 断点续选：{用户key: {引用消息文本签名: {ts, manager, state}}}
        self._breakpoints: dict = {}
        # pdy0 搜索验证码：等待用户手动输入 {key: {...}}；全局同时只保留一个
        self._pdy_pending: dict = {}
        self._pdy_ocr = None
        self._pdy_ocr_checked = False
        # 后台任务引用（防止被GC）
        self._bg_tasks: list[asyncio.Task] = []
        # 软件日报调度
        self._apscheduler: Optional[AsyncIOScheduler] = None
        self._scheduler_job_id = "daily_software_report"
        # 游戏日报调度（独立 schedule，与软件日报分开）
        self._game_scheduler_job_id = "daily_game_report"
        self._game_last_run_date: str = ""
        self._timezone: Optional[zoneinfo.ZoneInfo] = None
        self._schedule_hour: int = 10
        self._schedule_minute: int = 0
        self._game_schedule_hour: int = 18
        self._game_schedule_minute: int = 0
        # 影视日报调度（独立 schedule，与软件/游戏日报分开）
        self._movie_scheduler_job_id = "daily_movie_report"
        self._movie_last_run_date: str = ""
        self._movie_schedule_hour: int = 20
        self._movie_schedule_minute: int = 0
        # 短剧日报调度（独立 schedule，与软件/游戏/影视日报分开）
        self._drama_scheduler_job_id = "daily_drama_report"
        self._drama_last_run_date: str = ""
        self._drama_schedule_hour: int = 21
        self._drama_schedule_minute: int = 0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._fallback_task: Optional[asyncio.Task] = None
        self._sw_job_lock = None  # 懒初始化（需在事件循环内创建 asyncio.Lock）
        # 定时调度模式：优先用 AstrBot 官方 context.cron_manager.scheduler（可靠），
        # 不可用时回退到自建 AsyncIOScheduler（旧逻辑）
        self._using_framework_scheduler: bool = False
        self._scheduled_job_ids: list[str] = []
        # VIP 解析：等待用户「选接口」的待处理会话 {unified_msg_origin: {...}}
        self._vip_pending: dict = {}
        # VIP 解析接口：片库 /zjx 实时获取 + 磁盘缓存
        self._vip_interfaces: list = []
        self._vip_if_ts: float = 0.0
        self._vip_if_lock = None
        # 入群审核：待验证成员 {f"{group_id}:{user_id}": {...}} 与超时任务
        self._join_verify: dict = {}
        self._join_verify_tasks: dict = {}
        self._last_run_date: str = ""
        self._debug_log_path: str = ""
        self._reports_dir: str = ""
        self._reports_retention_days: int = 5
        # 日报「留空=全部群」：记录机器人见过的群，作为无 get_group_list 平台的后备
        self._seen_groups: dict = {}
        self._all_groups_cache: dict = {}
        # 全局积分 / 每日签到（懒加载，数据文件位于 AstrBot data 目录）
        self._points_store: Optional[PointsStore] = None
        # 群聊小游戏：会话按「平台:群号」保存，题库/战绩懒加载
        self._minigame_sessions: dict = {}
        self._minigame_store: Optional[MiniGameStore] = None
        self._minigame_pools: dict = {}      # {kind: (pool, ts)}
        self._minigame_pool_lock = None
        # 谁是卧底：词库懒加载、最近用过的词对、私聊投票会话绑定
        self._uc_pairs: Optional[list] = None
        self._uc_recent: list = []
        self._uc_vote_pending: dict = {}     # {(platform_id, uid): {...}}
        # 游戏 Cookie 自动登录：避免每次重装都手动 /game_cookie_refresh
        self._g_auto_login_next: float = 0.0
        self._g_auto_login_busy: bool = False
        # 签到推荐动态抓取缓存 {(类型:来源:日期): (过期时间, 推荐或 None)}
        self._rec_cache: dict = {}
        # 可视化配置页（AstrBot 插件页面）后端 API
        self._register_config_view()

    # ==================== 生命周期 ====================

    async def initialize(self):
        logger.info("暮黎资源聚合插件初始化")
        # 长列表图片卡片：后台预热 Chromium（不阻塞初始化），首次搜索省掉冷启动
        try:
            if prewarm_list_card and self._get_config().get("list_card_enabled", True):
                prewarm_list_card()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[暮黎资源] 列表卡片预热跳过: {e}")
        # issue4 兜底：本地配置文件恢复（防止 AstrBot 配置未落盘 / 卸载重装导致 Cookie 等数据丢失）
        # 关键：本地兜底文件位于插件目录【之外】的 AStrBot data 目录，卸载/覆盖重装插件目录不会删它；
        # 只要卸载时不勾选「同时删除插件配置文件」，这里就能把数据永久找回。
        try:
            saved = self._load_config_file()
            if saved and isinstance(saved, dict):
                cfg = self._get_config()
                if isinstance(cfg, dict):
                    # 兼容旧版嵌套/扁平兜底文件：递归展开为叶子键后再回填
                    leaves = self._flatten_leaves(saved)
                    restored = []
                    # 通用兜底：兜底文件里「非空、但当前配置为空」的项全部回填，
                    # 覆盖 cookie / switch618_cookie / wyy_cookie / wyy_custom_url /
                    # muliy_cookie 等所有会因重装/卸载而丢失的项。
                    # 仅当当前值为空（或该 key 不存在）才回填，避免覆盖用户在网页后台已修改过的值。
                    for k, v in leaves.items():
                        if k in cfg and cfg.get(k):
                            continue
                        if v not in (None, "", [], {}):
                            cfg[k] = v
                            restored.append(k)
                    if restored:
                        # 重新归组为一致性嵌套结构（game/software/movie/...），再回写
                        self._plugin_config = self._migrate_config(cfg)
                        logger.info(f"[暮黎资源] 已从本地兜底文件恢复配置: {', '.join(restored)}")
                        # 恢复后回写 AstrBot 中央配置，避免下次再丢
                        try:
                            if hasattr(self.context, 'update_plugin_config'):
                                await self.context.update_plugin_config(self._plugin_id(), self._plugin_config)
                        except Exception as e:
                            logger.warning(f"[暮黎资源] 恢复配置回写失败: {e}")
        except Exception as e:
            logger.warning(f"[暮黎资源] 本地配置恢复失败: {e}")
        # 恢复各日报「今日已发送」状态：重装/热重载后不再重复补发当天日报
        self._load_report_state()
        # 恢复「见过的群」缓存（日报留空时用于推送全部群）
        self._load_seen_groups()
        # VIP 解析接口缓存（片库 /zjx 上次抓取结果，避免每次开浏览器）
        try:
            self._load_vip_interface_cache()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[暮黎资源] VIP 接口缓存载入跳过: {e}")
        await self._start_sw_scheduler()
        # 影视源 / 游戏源：按 cookie 是否配置自动决定（替代手动 movie_source 切换）
        try:
            cfg = self._get_config()
            # 发布页地址可配置（默认挂了.com xn--ykq321c.com），用于多站点探测选点
            release_url = (cfg.get("muliy_release_url") or "").strip()
            if release_url:
                set_release_url(release_url)
            # 影视源：默认 pdy0（免登录）；movie_source=old 时用片库主站（需 Cookie/账号密码）
            cookies = (cfg.get("muliy_cookie") or "").strip()
            username = (cfg.get("muliy_username") or "").strip()
            password = (cfg.get("muliy_password") or "").strip()
            ttl = int(cfg.get("muliy_cache_ttl") or 3600)
            if cookies or (username and password):
                self._muliy_client = MuliySiteClient(
                    base_url="", cache_ttl=ttl, cookies=cookies,
                    username=username, password=password)
                logger.info(f"[暮黎资源] 片库主站备用源已就绪 ({'cookie' if cookies else '账号密码'}登录模式)")
            else:
                logger.info("[暮黎资源] 影视源=pdy0（默认）；未配置片库主站凭据，movie_source=old 将不可用")
                self._muliy_client = None
        except Exception as e:
            logger.warning(f"[暮黎资源] 客户端初始化失败: {e}")
            self._muliy_client = None
        # 游戏 Cookie：启动时检测一次；xdgame 源若配置了账密且 Cookie 失效，自动登录
        if self._game_source() == "xdgame":
            try:
                self._bg_tasks.append(asyncio.create_task(self._startup_game_cookie_check()))
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[暮黎资源] 游戏 Cookie 启动检测跳过: {e}")

    async def _startup_game_cookie_check(self):
        try:
            bad = await self._g_check_cookie()
            if bad is None:
                logger.info("[暮黎资源] xdgame Cookie 有效，无需重新登录")
            else:
                logger.warning(f"[暮黎资源] xdgame Cookie 状态={bad}；"
                               f"如已配置账号密码会尝试自动登录，否则请发送 /game_cookie_refresh")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] xdgame Cookie 启动检测异常: {e}")

    def _get_muliy_client(self) -> MuliySiteClient | None:
        """获取新站客户端；Cookie / 账号密码配置变更则重建。"""
        try:
            cfg = self._get_config()
            cookies = (cfg.get("muliy_cookie") or "").strip()
            username = (cfg.get("muliy_username") or "").strip()
            password = (cfg.get("muliy_password") or "").strip()
            if not cookies and not (username and password):
                return None
            if (self._muliy_client is None
                    or self._muliy_client._cookie_str != cookies
                    or self._muliy_client._username != username
                    or self._muliy_client._password != password):
                ttl = int(cfg.get("muliy_cache_ttl") or 3600)
                self._muliy_client = MuliySiteClient(
                    base_url="", cache_ttl=ttl, cookies=cookies,
                    username=username, password=password)
        except Exception:
            return None
        return self._muliy_client

    # ==================== 影视源选择（pdy0 / 片库主站） ====================

    def _movie_source(self) -> str:
        """当前影视搜索源：pdy（默认，pdy0.com） / muliy（movie_source=old）。"""
        try:
            cfg = self._get_config() or {}
        except Exception:
            cfg = {}
        ms = str(cfg.get("movie_source") or "").strip().lower()
        if ms in MV_SOURCE_ALIASES_OLD:
            return "muliy"
        return "pdy"

    def _get_pdy_client(self) -> PdySiteClient:
        """pdy0 客户端（懒加载，cookie/验证状态存插件 data 目录）。"""
        if self._pdy_client is None:
            self._pdy_client = PdySiteClient(
                base_url=PDY_BASE_URL,
                cookie_path=os.path.join(self._plugin_data_dir(), "pdy_cookies.json"),
            )
        return self._pdy_client

    def _get_movie_client(self, source: str = ""):
        source = source or self._movie_source()
        if source == "muliy":
            return self._get_muliy_client()
        return self._get_pdy_client()

    @staticmethod
    def _pdy_pending_key(event: AstrMessageEvent) -> str:
        try:
            chat = str(event.unified_msg_origin or "")
        except Exception:
            chat = ""
        try:
            uid = str(event.get_sender_id() or "")
        except Exception:
            uid = ""
        return f"{chat}|{uid}"

    async def _send_pdy_captcha(self, event: AstrMessageEvent, keyword: str,
                                image: bytes) -> None:
        """把 pdy0 搜索验证码发给用户，并记录待输入状态。"""
        key = self._pdy_pending_key(event)
        self._pdy_pending[key] = {
            "keyword": keyword,
            "ts": time.time(),
            "attempts": 1,
        }
        # 只保留最新一个（验证码是全局会话级的）
        for k in list(self._pdy_pending):
            if k != key:
                self._pdy_pending.pop(k, None)
        if not image:
            self._pdy_pending.pop(key, None)
            await event.send(MessageChain([Plain(
                "❌ pdy0 验证码获取失败，请稍后重新发送搜索指令。")]))
            return
        prompt = (
            "🔐 pdy0 搜索需要图片验证码。\n"
            "请把图片里的验证码（3-6 位字母数字）直接发给我，120 秒内有效，回复 0 取消。\n"
            "💡 安装 ddddocr 后可自动识别：pip install ddddocr")
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=_img_ext(image), prefix="pdy_cap_")
            os.close(fd)
            with open(tmp, "wb") as f:
                f.write(image)
            # 图片 + 提示文字放在同一条消息里发送
            await event.send(MessageChain([ImageComponent(file=tmp), Plain(prompt)]))
        except Exception as e:
            logger.warning(f"[pdy_site] 验证码图片发送失败，回退纯文本: {e}")
            await event.send(MessageChain([Plain(prompt)]))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    async def _pdy_ocr_ready(self) -> bool:
        """懒加载 ddddocr；未安装/加载失败返回 False（走手动输入）。"""
        if self._pdy_ocr_checked:
            return self._pdy_ocr is not None
        self._pdy_ocr_checked = True
        try:
            import importlib.util
            if importlib.util.find_spec("ddddocr") is None:
                logger.info("[pdy_site] 未安装 ddddocr，验证码将交给用户手动输入")
                return False

            def _load():
                import ddddocr
                return ddddocr.DdddOcr(show_ad=False)

            self._pdy_ocr = await asyncio.to_thread(_load)
            logger.info("[pdy_site] ddddocr 已加载，尝试验证码自动识别")
        except Exception as e:
            logger.warning(f"[pdy_site] ddddocr 加载失败，改用手动输入: {e}")
            self._pdy_ocr = None
        return self._pdy_ocr is not None

    async def _pdy_try_auto_captcha(self, image: bytes) -> bool:
        """用 ddddocr 自动识别验证码；最多换 3 张图重试。"""
        try:
            cfg = self._get_config() or {}
        except Exception:
            cfg = {}
        if not bool(cfg.get("pdy_auto_captcha", True)):
            return False
        if not await self._pdy_ocr_ready():
            return False
        client = self._get_pdy_client()
        img = image
        for i in range(3):
            try:
                code = await asyncio.to_thread(self._pdy_ocr.classification, img)
                if code and await asyncio.to_thread(client.verify, code):
                    logger.info(f"[pdy_site] 验证码自动识别成功（第 {i+1} 次）: {code!r}")
                    return True
            except Exception as e:
                logger.warning(f"[pdy_site] 自动识别异常: {e}")
            try:
                img = await asyncio.to_thread(client.fetch_captcha, False)
            except Exception:
                break
        return False

    async def _search_movie_source(self, event: AstrMessageEvent, keyword: str,
                                   source: str = "") -> dict:
        """按源搜索影视。返回 {"status": ok/empty/captcha_sent/no_client/error, ...}。"""
        source = source or self._movie_source()
        if source == "muliy":
            client = self._get_muliy_client()
            if not client:
                return {"status": "no_client", "source": source,
                        "msg": "片库主站未配置 Cookie/账号密码，无法使用 movie_source=old。"}
            try:
                results = await asyncio.to_thread(client.search, keyword, 24)
            except Exception as e:
                logger.error(f"[暮黎资源] 影视搜索(片库,'{keyword}') 失败: {e}")
                return {"status": "error", "source": source, "msg": str(e)[:120]}
            return {"status": "ok" if results else "empty",
                    "source": source, "results": results}

        # pdy0：可能遇到图片验证码
        client = self._get_pdy_client()
        for _ in range(2):
            try:
                results = await asyncio.to_thread(client.search, keyword, 24)
                return {"status": "ok" if results else "empty",
                        "source": source, "results": results}
            except PdyCaptchaRequired as cap:
                if await self._pdy_try_auto_captcha(cap.image):
                    continue
                # 自动识别失败时，会话里的验证码已被刷新过，重新取一张给用户
                img = cap.image
                try:
                    img = await asyncio.to_thread(client.fetch_captcha, False) or img
                except Exception:
                    pass
                await self._send_pdy_captcha(event, keyword, img)
                return {"status": "captcha_sent", "source": source}
            except Exception as e:
                logger.error(f"[暮黎资源] 影视搜索(pdy0,'{keyword}') 失败: {e}")
                return {"status": "error", "source": source, "msg": str(e)[:120]}
        return {"status": "error", "source": source, "msg": "验证码重试次数过多，请稍后再试。"}

    async def _send_movie_results(self, event: AstrMessageEvent, keyword: str,
                                  results: list, source: str) -> None:
        """统一发送影视搜索结果（pdy0 / 片库共用同一套会话状态机）。"""
        tag = "【暮黎资源】"
        ps = 8
        _charge_txt = self._points_charge(event, "movie", keyword)
        self._movie_sessions_new.set(event, {
            "stage": "select_movie_new", "keyword": keyword,
            "results": results, "page": 0, "page_size": ps,
            "source": source,
            "_updated": time.time(), "_llm_handled": True,
        })
        t = len(results); pt = (t + ps - 1) // ps
        page_txt = format_movie_list_new(results, keyword, 0, ps)
        await self._send_search_page(
            event, "movie_new",
            tag + f" 🎬 影视搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt + _charge_txt,
            results=results, keyword=keyword, page=0, page_size=ps,
            note=_charge_txt)

    async def _handle_pdy_captcha_reply(self, event: AstrMessageEvent, text: str) -> bool:
        """处理用户发来的 pdy0 验证码。返回 True 表示已消费该消息。"""
        key = self._pdy_pending_key(event)
        pending = self._pdy_pending.get(key)
        if not pending:
            return False
        if time.time() - pending.get("ts", 0) > 120:
            self._pdy_pending.pop(key, None)
            return False
        # 支持「@机器人 5064」这种带 @ 的回复
        code_text = re.sub(r"\[CQ:at,[^\]]+\]", "", text or "")
        code_text = re.sub(r"^@\S+\s*", "", code_text).strip()
        if code_text in ("0", "取消", "算了", "不要", "取消搜索"):
            self._pdy_pending.pop(key, None)
            event.stop_event()
            await event.send(MessageChain([Plain("已取消 pdy0 验证码输入。")]))
            return True
        if not re.fullmatch(r"[0-9A-Za-z]{3,6}", code_text):
            # 不像验证码：如果是新命令就放行，否则提示重新输入
            if code_text.startswith(("/", "／")):
                self._pdy_pending.pop(key, None)
                return False
            event.stop_event()
            await event.send(MessageChain([Plain(
                "请输入图片里的验证码（3-6 位字母数字），回复 0 取消。")]))
            return True

        self._pdy_pending.pop(key, None)
        event.stop_event()
        client = self._get_pdy_client()
        ok = await asyncio.to_thread(client.verify, code_text)
        if not ok:
            attempts = int(pending.get("attempts", 1))
            if attempts >= 3:
                await event.send(MessageChain([Plain(
                    "❌ 验证码连续错误，已取消本次搜索。请稍后重新发送搜索指令。")]))
                return True
            try:
                img = await asyncio.to_thread(client.fetch_captcha, False)
            except Exception:
                img = b""
            if img:
                await self._send_pdy_captcha(event, pending.get("keyword", ""), img)
                self._pdy_pending[key]["attempts"] = attempts + 1
            else:
                await event.send(MessageChain([Plain("❌ 获取验证码失败，请稍后重试。")]))
            return True

        await event.send(MessageChain([Plain("✅ pdy0 验证通过，正在继续搜索...")]))
        keyword = pending.get("keyword", "")
        if not keyword:
            return True
        r = await self._search_movie_source(event, keyword, "pdy")
        if r.get("status") == "ok":
            await self._send_movie_results(event, keyword, r.get("results", []), "pdy")
        elif r.get("status") == "empty":
            await event.send(MessageChain([Plain(
                f"【暮黎资源】未找到与「{keyword}」相关的影视，请换个关键词。")]))
        elif r.get("status") != "captcha_sent":
            await event.send(MessageChain([Plain(
                f"【暮黎资源】影视搜索失败：{r.get('msg') or '未知错误'}")]))
        return True

    async def terminate(self):
        logger.info("暮黎资源聚合插件终止")
        await self._stop_sw_scheduler()
        # 取消所有入群审核超时任务，避免插件卸载/热重载后残留后台协程
        for key in list(self._join_verify_tasks):
            self._cancel_join_verify_task(key)
        for t in self._bg_tasks:
            if not t.done():
                t.cancel()

    @filter.on_platform_loaded()
    async def _on_platform_loaded(self):
        """平台加载完成后（官方 cron_manager 已就绪）再注册一次定时任务，
        确保优先使用官方调度器，提高定时触发的可靠性。"""
        try:
            logger.info("[暮黎资源] 平台已加载，重新注册定时日报任务")
            await self._start_sw_scheduler()
        except BaseException as e:
            # 兜底：包括 CancelledError 在内的任何异常都不得冒泡到 platform_manager，
            # 否则会导致整个 AstrBot 启动崩溃（插件问题绝不能拖垮机器人）。
            logger.warning(f"[暮黎资源] 平台加载后注册定时任务失败(已忽略，不影响机器人启动): {e!r}")

    # ==================== LLM 请求拦截（强制工具调用） ====================

    # 会话内的快捷回复（选择/翻页/取消）：由系统规则直接处理，不该再触发 search_*
    _FOLLOWUP_CMD_RE = re.compile(
        r"^(?:0|取消(?:搜索)?|不要了?|算了|结束|退出|下一页|上一页|末页|首页|最新|"
        r"跳\s*\d+|\d{1,3}|第[一二三四五六七八九十两0-9]+[个部集条页])$")

    # 明显的「非搜索」语义：提问、教程、配置、评价、维护、闲聊等。
    # 命中后不注入搜索引导——这些句子常含"电影/游戏/小说/资源/下载"等词，
    # 一旦注入，模型很容易把聊天误判成搜索并调用工具。
    _NON_SEARCH_WORDS = (
        "封面", "生成", "画一张", "画个", "画图", "做一张", "做图",
        "介绍", "宣传", "公告", "海报", "banner", "logo", "文案", "宣传语",
        "配图", "插图", "表格", "代码",
        "教程", "怎么", "如何", "为什么", "为啥", "什么原因", "是不是", "能不能",
        "可不可以", "有没有办法", "怎么办", "好用吗", "值得", "推荐吗",
        "报错", "错误", "失败", "无法", "用不了", "不能用", "没反应", "不生效",
        "太慢", "很慢", "卡住", "超时", "重启", "更新日志", "版本", "作者",
        "插件", "api", "API", "token", "模型", "提示词", "部署", "安装", "卸载",
        "配置", "设置", "文档", "修复", "权限", "收费", "价格",
        "影评", "剧情", "结局", "演员", "导演", "好看", "不好看", "讲什么",
        "什么意思", "解析", "评分", "玩会儿", "一会儿", "无聊", "陪我玩",
        "看起来", "看完", "看过", "看着",
    )

    # 明确的搜索语义：动词+内容 / 类型+下载链接 / 有没有XX / 网盘资源 / 推荐个XX
    _SEARCH_INTENT_RES = (
        re.compile(r"(?:帮我|给我|我要|我想|想|要|求|麻烦|请)?\s*"
                   r"(?:找|搜|搜索|查一?下|下载|观看|想看|要看|来一?[部个本款]|追剧|追番)"
                   r"\s*[^\s，。,.!?！？]{1,}"),
        re.compile(r"(?:电影|电视剧|影视|综艺|动漫|动画|番剧|短剧|小说|游戏|软件|"
                   r"app|应用|资源|网盘)[^\s，。,.!?！？]{0,6}"
                   r"(?:下载|链接|资源|推荐|在哪|有没有|分享|合集)"),
        re.compile(r"(?:推荐|安利)[^\s，。,.!?！？]{0,3}"
                   r"(?:电影|电视剧|影视|综艺|动漫|动画|番剧|短剧|小说|游戏|软件|资源)"),
        re.compile(r"(?:有没有|有木有|求一?[个部下本款]?|来个|来点|给我来)"
                   r"\s*[^\s，。,.!?！？]{1,}"),
        re.compile(r"(?:百度|夸克|阿里|uc|115|迅雷|天翼|123)[^\s]{0,4}(?:网盘|资源|链接)"),
        re.compile(r"(?:看剧|看片|看番|追剧|追番)"),
    )

    def _active_search_session(self, event: AstrMessageEvent) -> str:
        """返回当前未过期的搜索会话类型（没有则空串）。"""
        for name, mgr in (
            ("movie_new", self._movie_sessions_new),
            ("movie", self._movie_sessions),
            ("game", self._sessions),
            ("software", self._search_sessions),
            ("novel", self._novel_sessions),
            ("drama", self._drama_sessions),
        ):
            try:
                if mgr.get(event):
                    return name
            except Exception:  # noqa: BLE001
                continue
        return ""

    def _is_non_search_request(self, text: str) -> bool:
        return any(k in (text or "") for k in self._NON_SEARCH_WORDS)

    def _looks_like_search_intent(self, text: str) -> bool:
        """判断消息是否是「明确要求搜索资源」，而不是聊天/提问/评价。"""
        t = (text or "").strip()
        if not t or len(t) > 40:
            return False
        if self._FOLLOWUP_CMD_RE.match(t):
            return False
        if self._is_non_search_request(t):
            return False
        return any(rx.search(t) for rx in self._SEARCH_INTENT_RES)

    # 清洗后剩下的无意义词：命中说明原句没有真正的资源名（如"我想玩会儿游戏"）
    _BAD_SEARCH_KEYWORDS = {
        "", "会儿", "一会", "一下", "什么", "啥", "点", "个", "款", "部", "本",
        "游戏", "软件", "app", "资源", "推荐", "安利", "下载", "搜索", "找", "搜",
        "这个", "那个", "这些", "那些", "东西", "玩意儿",
    }

    def _valid_search_keyword(self, kw: str) -> bool:
        k = (kw or "").strip()
        if len(k) < 2:
            return False
        if k.lower() in self._BAD_SEARCH_KEYWORDS:
            return False
        return bool(re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", k))

    def _inject_temp_instruction(self, req, instruction: str) -> None:
        """把指令作为「临时用户内容块」追加，不改写 system_prompt。

        这样不会破坏上游模型的上下文缓存命中率，也不写入会话历史。
        """
        # 上架规范：严禁直接改写 system_prompt（会破坏上游模型上下文缓存命中率）。
        try:
            from astrbot.core.agent.message import TextPart
            _part = TextPart(text=instruction)
            for _mark in ("mark_as_temp", "make_as_temp"):
                _fn = getattr(_part, _mark, None)
                if callable(_fn):
                    _part = _fn()
                    break
        except Exception:  # noqa: BLE001
            _part = {"type": "text", "text": instruction, "_no_save": True}
        _parts = getattr(req, "extra_user_content_parts", None)
        if isinstance(_parts, list):
            _parts.append(_part)
        else:
            # 极旧版本无该字段：退化为在用户 prompt 末尾追加（同样不改写 system_prompt）
            req.prompt = f"{req.prompt or ''}\n\n{instruction}"

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        """当用户消息包含资源搜索意图时，向 system prompt 注入工具调用规则。

        设计原则（参考 Spotify 插件的「被动视野」思路）：
        - LLM 只负责「判断意图 + 调用工具 + 排版润色」
        - 插件只负责「执行实际搜索/翻页/下载」
        - 工具的返回文本就是 LLM 看到的事实，LLM 可以自由排版
        """
        # ★非搜索意图短路：生成封面/图片、介绍、宣传、公告等类消息即使含"小说/游戏/影视"
        #   等词也绝不应触发任何资源搜索逻辑（否则"新增小说搜索下载"会被误判为小说搜索）。
        #   这类请求直接放行给普通对话/画图流程，不注入搜索引导、不拦截。
        raw_text = event.message_str.strip()

        # ★签到 / 积分查询快捷拦截：规则能处理的短指令直接回复，不经过 LLM（省 token、响应更快）
        _short = re.sub(r"^[/／]\s*", "", raw_text).strip()
        _short = re.sub(r"^(帮我|我要|我想|今天|麻烦|请)\s*", "", _short)
        _short = re.sub(r"[!！。.～~\s]+$", "", _short)
        if re.fullmatch(r"(每日签到|签到|打卡)(一下|下|吧|啦|呢|了)?", _short):
            try:
                await self._send_checkin(event)
                event.stop_event()
                return
            except Exception as e:
                logger.warning(f"[暮黎资源·积分] 签到快捷处理失败: {e}")
        if re.fullmatch(r"积分(排行榜|排行|榜单|榜)", _short):
            try:
                await self._send_points_rank_card(event)
                event.stop_event()
                return
            except Exception as e:
                logger.warning(f"[暮黎资源·积分] 积分排行快捷处理失败: {e}")
        if re.fullmatch(r"(我的)?积分(查询|余额|有多少|多少)?|查(一下)?积分", _short):
            try:
                await self._send_points_card(event)
                event.stop_event()
                return
            except Exception as e:
                logger.warning(f"[暮黎资源·积分] 积分查询快捷处理失败: {e}")

        # ★会话指令前置处理（关键）：部分 AstrBot 版本里 LLM 请求早于
        #   on_any_message，用户回复序号/翻页时模型会先回一句，插件再回一遍。
        #   这里在 LLM 请求前先跑一次会话处理器；处理完成会 stop_event，
        #   本次 LLM 请求直接取消，因此不会再出现 LLM 的“多嘴”回复。
        try:
            if self._active_search_session(event):
                await self._dispatch_any_message(event)
                if event.is_stopped():
                    # 双保险：显式关闭默认 LLM 请求（部分版本 stop_event 不会取消已排队的请求）
                    try:
                        event.should_call_llm(False)
                    except Exception:  # noqa: BLE001
                        pass
                    logger.debug("[暮黎资源] 会话指令已在 LLM 前处理，跳过本次 LLM")
                    return
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] LLM 前会话预处理失败: {e}")

        # ★非搜索意图短路：提问、教程、配置、评价、维护类消息即使含"小说/游戏/影视"
        #   等词也绝不应触发任何资源搜索逻辑（否则"插件怎么配置"会被误判为搜索）。
        if self._is_non_search_request(raw_text):
            return

        # ★新站影视会话兜底拦截：LLM 可能偷懒不调工具，在 LLM 前直接处理
        ses_mn = self._movie_sessions_new.get(event)
        if ses_mn and ses_mn.get("stage") in ("select_movie_new", "select_res_type",
                                               "select_pan_type", "select_play_node", "select_episode_new", "select_pan"):
            is_cmd = (raw_text in ("0", "取消")
                      or re.match(r'^[1-9]\d*$', raw_text)
                      or raw_text in ("下一页", "上一页", "末页", "首页", "最新")
                      or raw_text.startswith("跳")
                      or re.search(r"(网盘|在线|播放|线路|节点|夸克|百度|迅雷|阿里|天翼|115|uc)",
                                   raw_text, re.I))
            if is_cmd:
                try:
                    logger.info(f"[暮黎资源] 新站会话兜底拦截 stage={ses_mn.get('stage')} text={raw_text}")
                    await self._handle_movie_new_selection(event, raw_text)
                except Exception as e:
                    logger.error(f"[暮黎资源] 新站会话兜底处理失败: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 处理失败：{str(e)[:120]}")]))
                event.stop_event()
                return

        # ★影视搜索意图拦截：用户说"我想看XX/观看XX"时，
        #   这里直接强制调 search_movie，不依赖 LLM 选工具
        #   有旧会话时自动清除（用户要搜新的了，不必手动取消）
        _movie_intent_kws = ('想看', '要看', '观看', '看剧', '看片', '看一', '看个', '看部', '看电影')
        if any(k in raw_text for k in _movie_intent_kws):
            if ses_mn:
                self._movie_sessions_new.delete(event)
                logger.info(f"[暮黎资源] 新搜索自动清除旧会话 (stage={ses_mn.get('stage')})")
            _mn = re.sub(r'^(我想看|我要看|想看|要看|帮我看|观看|看剧|看片|看一|看个|看部|看电影|我想|我要|要|想|帮我|能不能|可以|麻烦|请)\s*', '', raw_text)
            _mn = re.sub(r'^(一下|一部|个|部|下)\s*', '', _mn)  # 去量词
            _mn = re.sub(r'[的啊呢吧呀哦！。.,，]+$', '', _mn).strip()
            # 排除"玩游戏/找软件"等非影视意图 + 太短的无意义词
            if self._valid_search_keyword(_mn) and not re.search(r'(游戏|软件|app|APP|工具)', _mn):
                try:
                    logger.info(f"[暮黎资源] 影视意图拦截: '{raw_text}' → search_movie('{_mn}')")
                    _ret = await self.llm_search_movie(event, _mn)
                    # llm_search_movie 成功时已 event.send 并返回"[已发送...]"；
                    # 未找到/失败时只返回文本（设计给 LLM 转告），但此处 stop_event 了 LLM，
                    # 需自己把未 send 的文本发给用户，否则用户收不到任何回复
                    if _ret and not _ret.startswith("[已发送"):
                        await event.send(MessageChain([Plain(_ret)]))
                    event.stop_event()
                    return
                except Exception as e:
                    logger.error(f"[暮黎资源] 影视意图拦截失败: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 影视搜索出错：{str(e)[:120]}")]))
                    event.stop_event()
                    return

        # ★短剧搜索意图拦截：用户说"搜短剧XX/看短剧XX"时，
        #   这里直接强制调 search_drama，不依赖 LLM 选工具。
        #   有旧会话时自动清除（用户要搜新的了，不必手动取消）。
        _drama_intent_kws = ('搜短剧', '看短剧', '找短剧', '追短剧', '短剧搜索')
        if any(k in raw_text for k in _drama_intent_kws):
            dses0 = self._drama_sessions.get(event)
            if dses0:
                self._drama_sessions.delete(event)
                logger.info(f"[暮黎资源] 新短剧搜索自动清除旧会话 (stage={dses0.get('stage')})")
            _dn = re.sub(r'^(我想看|我要看|想看|要看|帮我找|帮我搜|帮我看|搜|找|看|追|要|想|帮我|能不能|可以|麻烦|请)\s*', '', raw_text)
            _dn = re.sub(r'^(一下|一部|个|部|下)\s*', '', _dn)  # 去量词
            _dn = re.sub(r'短剧\s*', '', _dn)  # 去"短剧"统称
            _dn = re.sub(r'^(推荐|安利)\s*', '', _dn)
            _dn = re.sub(r'[的啊呢吧呀哦！。.,，]+$', '', _dn).strip()
            if self._valid_search_keyword(_dn):
                try:
                    logger.info(f"[暮黎资源] 短剧意图拦截: '{raw_text}' → search_drama('{_dn}')")
                    _ret = await self.llm_search_drama(event, _dn)
                    if _ret and not _ret.startswith("[已发送"):
                        await event.send(MessageChain([Plain(_ret)]))
                    event.stop_event()
                    return
                except Exception as e:
                    logger.error(f"[暮黎资源] 短剧搜索出错: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 短剧搜索出错：{str(e)[:120]}")]))
                    event.stop_event()
                    return

        # ★小说搜索意图拦截：用户说"找小说XX/搜小说XX/我想看小说XX"时，
        #   这里直接强制调 search_novel，不依赖 LLM 选工具。
        #   有旧会话时自动清除（用户要搜新的了，不必手动取消）。
        _novel_intent_kws = ('找小说', '搜小说', '看小说', '读小说', '听小说',
                             '本小说', '想看小说', '我想看小说')
        if any(k in raw_text for k in _novel_intent_kws):
            nses0 = self._novel_sessions.get(event)
            if nses0:
                self._novel_sessions.delete(event)
                logger.info(f"[暮黎资源] 新小说搜索自动清除旧会话 (stage={nses0.get('stage')})")
            _nn = re.sub(r'^(我想看|我要看|想看|要看|帮我找|帮我搜|帮我看|找|搜|看|读|听|我|要|想|帮我|能不能|可以|麻烦|请)\s*', '', raw_text)
            _nn = re.sub(r'^(一下|一本|本|部|下|个)\s*', '', _nn)  # 去量词
            _nn = re.sub(r'小说\s*', '', _nn)  # 去"小说"统称
            _nn = re.sub(r'^(推荐|安利)\s*', '', _nn)
            _nn = re.sub(r'[的啊呢吧呀哦！。.,，]+$', '', _nn).strip()
            if self._valid_search_keyword(_nn):
                try:
                    logger.info(f"[暮黎资源] 小说意图拦截: '{raw_text}' → search_novel('{_nn}')")
                    _ret = await self.llm_search_novel(event, _nn)
                    # llm_search_novel 成功时已 event.send 并返回"[已发送...]"；
                    # 未找到/失败时只返回文本（设计给 LLM 转告），但此处 stop_event 了 LLM，
                    # 需自己把未 send 的文本发给用户，否则用户收不到任何回复。
                    if _ret and not _ret.startswith("[已发送"):
                        await event.send(MessageChain([Plain(_ret)]))
                    event.stop_event()
                    return
                except Exception as e:
                    logger.error(f"[暮黎资源] 小说意图拦截失败: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 小说搜索出错：{str(e)[:120]}")]))
                    event.stop_event()
                    return

        # ★游戏搜索意图拦截：用户说"找游戏XX/搜游戏XX/下载XX游戏/我想玩XX"时，
        #   直接强制调 search_game，不依赖 LLM 选工具（省 token、防误判）。
        #   有旧会话时自动清除（用户要搜新的了，不必手动取消）。
        _game_intent_kws = (
            '找游戏', '搜游戏', '下游戏', '下载游戏', '玩游戏',
            '想玩', '要玩', '帮我找游戏', '帮我搜游戏', '帮我下游戏',
            '游戏下载', '游戏推荐', '推荐游戏', '来个游戏', '找个游戏', '搜个游戏',
        )
        if any(k in raw_text for k in _game_intent_kws):
            gses0 = self._sessions.get(event)
            if gses0:
                self._sessions.delete(event)
                logger.info(f"[暮黎资源] 新游戏搜索自动清除旧会话 (stage={gses0.get('stage')})")
            _gn = re.sub(r'^(我想玩|我要玩|想玩|要玩|帮我找|帮我搜|帮我下|帮我|找|搜|下|下载|要|想|请|玩)\s*', '', raw_text)
            _gn = re.sub(r'^(一下|一个|个|款|部|下|种)\s*', '', _gn)  # 去量词
            _gn = re.sub(r'游戏\s*', '', _gn)  # 去"游戏"统称
            _gn = re.sub(r'^(推荐|安利)\s*', '', _gn)  # 去"推荐/安利"
            _gn = re.sub(r'[的啊呢吧呀哦！。.,，]+$', '', _gn).strip()
            if self._valid_search_keyword(_gn):
                try:
                    logger.info(f"[暮黎资源] 游戏意图拦截: '{raw_text}' → search_game('{_gn}')")
                    _ret = await self.llm_search_game(event, _gn)
                    # llm_search_game 成功时已 event.send 并返回"[已发送...]"；
                    # 未找到/失败时只返回文本，需自己发给用户，否则收不到回复。
                    if _ret and not _ret.startswith("[已发送"):
                        await event.send(MessageChain([Plain(_ret)]))
                    event.stop_event()
                    return
                except Exception as e:
                    logger.error(f"[暮黎资源] 游戏意图拦截失败: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 游戏搜索出错：{str(e)[:120]}")]))
                    event.stop_event()
                    return

        # ★软件搜索意图拦截：用户说"找软件XX/搜软件XX/下载XX软件/APP下载"时，
        #   直接强制调 search_software，不依赖 LLM 选工具。
        _sw_intent_kws = (
            '找软件', '搜软件', '下软件', '下载软件', '装软件', '用软件',
            '帮我找软件', '帮我搜软件', '帮我下软件',
            '软件下载', '软件推荐', '推荐软件', '找个软件', '搜个软件',
            'app下载', 'APP下载',
        )
        if any(k in raw_text for k in _sw_intent_kws):
            swses0 = self._search_sessions.get(event)
            if swses0:
                self._search_sessions.delete(event)
                logger.info(f"[暮黎资源] 新软件搜索自动清除旧会话 (stage={swses0.get('stage')})")
            _sn = re.sub(r'^(帮我找|帮我搜|帮我下|帮我|找|搜|下|下载|装|用|要|想|请)\s*', '', raw_text)
            _sn = re.sub(r'^(一下|一个|个|款|部|下|种)\s*', '', _sn)  # 去量词
            _sn = re.sub(r'(软件|app|APP)\s*', '', _sn)  # 去"软件/app"统称
            _sn = re.sub(r'^(推荐|安利)\s*', '', _sn)  # 去"推荐/安利"
            _sn = re.sub(r'[的啊呢吧呀哦！。.,，]+$', '', _sn).strip()
            if self._valid_search_keyword(_sn):
                try:
                    logger.info(f"[暮黎资源] 软件意图拦截: '{raw_text}' → search_software('{_sn}')")
                    _ret = await self.llm_search_software(event, _sn)
                    if _ret and not _ret.startswith("[已发送"):
                        await event.send(MessageChain([Plain(_ret)]))
                    event.stop_event()
                    return
                except Exception as e:
                    logger.error(f"[暮黎资源] 软件意图拦截失败: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 软件搜索出错：{str(e)[:120]}")]))
                    event.stop_event()
                    return

        text = raw_text.lower()

        # ① 会话内的快捷回复（数字/翻页/取消）：由 on_any_message / 会话兜底直接处理，
        #    这里只给一句「不要重复搜索」的轻量提示，避免模型看到"2"就再调 search_*。
        if self._active_search_session(event) and self._FOLLOWUP_CMD_RE.match(raw_text):
            self._inject_temp_instruction(req, (
                "【暮黎资源·会话进行中】用户正在操作已有的搜索结果列表。"
                "数字、上一页/下一页、取消等回复由系统直接处理，"
                "不要再调用 search_* 重新搜索，也不要编造列表或链接。"
                "只有用户明确说出新的资源名称并要求搜索时才调用工具。"))
            logger.debug(f"[暮黎资源] LLM请求拦截，注入会话续接指令 text={raw_text}")
            return

        # ② 非搜索语义（提问/教程/配置/评价/维护/闲聊）已在前置短路处理；
        #    长句也按聊天处理，不注入搜索引导。
        if len(raw_text) > 40:
            return

        # ③ 只有「明确要求搜索资源」才注入工具调用规则。
        #    旧实现用宽泛关键词（"找/资源/有没有/1/2/3"）命中，导致正常聊天
        #    也会被注入引导、模型频繁误调工具；这里改为结构化意图判断。
        if not self._looks_like_search_intent(raw_text):
            return

        instruction = """【暮黎资源】你是资源搜索助手。
- 仅当用户在当前消息中明确要求「搜索/下载/观看某个资源」时，才调用对应工具：游戏 search_game / 软件 search_software / 影视 search_movie / 短剧 search_drama / 小说 search_novel。
- 调用前先把关键词清洗干净（去掉“帮我找/搜/下载”等前缀和量词）；类型不确定时选最可能的一个，不要做综合搜索。
- 用户只是在聊天、提问、评价、讨论剧情，或询问插件怎么用/怎么配置/为什么失败时，不要调用任何搜索工具。
- 已有搜索结果会话时，数字、翻页、取消由系统直接处理，不要重复调用 search_*，也不要编造列表或链接。
- 搜索资源会消耗积分（后台可配置），积分不足时系统会提示先发送 /签到；签到、积分查询、排行榜由系统直接回复，不要编造余额。
- 严禁使用 markdown 表格（QQ 会乱码）。"""
        self._inject_temp_instruction(req, instruction)
        logger.debug(f"[暮黎资源] LLM请求拦截，注入工具调用指令 text_len={len(text)}")

    # ==================== LLM 响应拦截：禁用 LLM 中间总结 ====================

    @staticmethod
    def _mark_llm_suppress(event: AstrMessageEvent) -> None:
        """标记「本条消息已由插件直接回复」，用于清空同一消息的 LLM 输出。

        用 event 级标记而不是 session 标记：像发送最终链接这种步骤会清掉
        session，若只依赖 session 上的 _llm_handled，LLM 的二次回复就漏出来了。
        """
        try:
            setter = getattr(event, "set_extra", None)
            if callable(setter):
                setter("_muliy_llm_suppress", True)
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(event, "_muliy_llm_suppress", True)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _consume_llm_suppress(event: AstrMessageEvent) -> bool:
        """读取并清除本消息的「插件已回复」标记。"""
        try:
            getter = getattr(event, "get_extra", None)
            if callable(getter) and getter("_muliy_llm_suppress"):
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            if getattr(event, "_muliy_llm_suppress", False):
                setattr(event, "_muliy_llm_suppress", False)
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    # ==================== 断点续选（引用消息恢复） ====================

    _BP_TTL = 1800  # 断点缓存 30 分钟

    @staticmethod
    def _bp_user_key(event: AstrMessageEvent) -> str:
        return (f"{event.get_platform_id()}:{event.get_group_id()}:"
                f"{event.get_sender_id()}")

    @staticmethod
    def _bp_sig(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).lower()

    @staticmethod
    def _quoted_reply_info(event: AstrMessageEvent):
        """取出「引用回复」的原文/发送者/消息ID。

        返回 (文本, 发送者ID, 消息ID)；不是引用返回三个空串。
        """
        def _from_comp(comp):
            txt = (getattr(comp, "message_str", None)
                   or getattr(comp, "text", None) or "")
            if not txt:
                parts = []
                for c in (getattr(comp, "chain", None) or []):
                    t = getattr(c, "text", None)
                    if t:
                        parts.append(str(t))
                txt = "".join(parts)
            sender = getattr(comp, "sender_id", "")
            mid = getattr(comp, "id", "")
            return (str(txt or "").strip(), str(sender or ""),
                    str(mid if mid is not None else ""))

        try:
            for comp in (event.get_messages() or []):
                if type(comp).__name__.lower() == "reply":
                    return _from_comp(comp)
        except Exception:  # noqa: BLE001
            pass
        try:
            obj = getattr(getattr(event, "message_obj", None), "reply", None)
            if obj is not None:
                return _from_comp(obj)
        except Exception:  # noqa: BLE001
            pass
        return "", "", ""

    def _register_breakpoint(self, event: AstrMessageEvent, manager: str,
                             state: dict | None, texts: list,
                             mid: str = "") -> None:
        """把「这条列表消息」和当时的会话状态绑定，供引用回复时恢复。"""
        if not state:
            return
        sigs = [self._bp_sig(t) for t in (texts or [])]
        sigs = [s for s in sigs if s]
        if mid:
            sigs.append(f"id:{mid}")
        if not sigs:
            return
        now = time.time()
        key = self._bp_user_key(event)
        bucket = self._breakpoints.setdefault(key, {})
        for k in [k for k, v in bucket.items()
                  if now - float(v.get("ts", 0)) > self._BP_TTL]:
            bucket.pop(k, None)
        try:
            snap = copy.deepcopy(state)
        except Exception:  # noqa: BLE001
            snap = dict(state)
        snap.pop("_llm_handled", None)
        rec = {"ts": now, "manager": manager, "state": snap}
        for s in sigs:
            bucket[s] = rec
        # 每个用户最多保留 30 条，避免长期占用内存
        if len(bucket) > 30:
            for k, _ in sorted(bucket.items(),
                               key=lambda kv: float(kv[1].get("ts", 0)))[:len(bucket) - 30]:
                bucket.pop(k, None)

    def _resume_from_quote(self, event: AstrMessageEvent) -> Optional[dict]:
        """仅当用户「引用回复机器人的列表消息」时恢复断点；直接发序号不恢复。"""
        text, sender, mid = self._quoted_reply_info(event)
        if not text and not mid:
            return None
        self_id = str(event.get_self_id() or "")
        if sender and self_id and sender != self_id:
            return None
        key = self._bp_user_key(event)
        bucket = self._breakpoints.get(key) or {}
        now = time.time()
        for k in [k for k, v in bucket.items()
                  if now - float(v.get("ts", 0)) > self._BP_TTL]:
            bucket.pop(k, None)
        rec = bucket.get(f"id:{mid}") if mid else None
        if not rec and text:
            rec = bucket.get(self._bp_sig(text))
        if not rec and text:
            # 文本列表被引用时带上了提示行：用「包含」匹配兜底
            target = self._bp_sig(text)
            for sig, cand in bucket.items():
                if len(sig) >= 8 and not sig.startswith("id:") and sig in target:
                    rec = cand
                    break
        if not rec:
            return None
        mgr = {
            "movie": self._movie_sessions_new,
            "movie_old": self._movie_sessions,
            "game": self._sessions,
            "software": self._search_sessions,
            "novel": self._novel_sessions,
            "drama": self._drama_sessions,
        }.get(rec.get("manager"))
        if mgr is None:
            return None
        try:
            state = copy.deepcopy(rec["state"])
        except Exception:  # noqa: BLE001
            state = dict(rec["state"])
        state["_updated"] = now
        mgr.set(event, state)
        logger.info(f"[断点] 引用「{text[:24]}」恢复会话 "
                    f"(manager={rec.get('manager')} stage={state.get('stage')})")
        return state

    def _mark_breakpoints_charged(self, event: AstrMessageEvent) -> None:
        """资源已扣费后，把该用户现有断点都标记为已扣费，避免引用恢复后重复扣。"""
        bucket = self._breakpoints.get(self._bp_user_key(event)) or {}
        for rec in bucket.values():
            st = rec.get("state")
            if isinstance(st, dict):
                st["_charged"] = True

    @filter.on_decorating_result()
    async def _strip_llm_chitchat_after_tool(self, event: AstrMessageEvent):
        """当插件已经直接回复过本条消息时，清空 LLM 的重复输出（多嘴总结）。

        触发条件（满足任一）：
        - 本条消息被 on_any_message / 工具流程标记了「插件已回复」
        - 当前 session 上有 _llm_handled 标记（工具直接 send 了格式化页面）

        用 event 级标记兜住「发送完链接就删除 session」的场景（小说/影视），
        否则 LLM 会对同一句「1」再回复一遍。
        """
        try:
            suppress = self._consume_llm_suppress(event)
            ses_sw = self._search_sessions.get(event)
            ses_g = self._sessions.get(event)
            ses_mv = self._movie_sessions.get(event)
            ses_mv_new = self._movie_sessions_new.get(event)
            ses_nv = self._novel_sessions.get(event)
            ses_dr = self._drama_sessions.get(event)
            target_ses = ses_sw or ses_g or ses_mv or ses_mv_new or ses_nv or ses_dr
            if not suppress and (not target_ses or not target_ses.get("_llm_handled")):
                return
            if target_ses:
                target_ses["_llm_handled"] = False
            result = event.get_result()
            if result is not None and result.chain:
                logger.info(f"[LLM-STRIP] 清空 LLM 重复输出 "
                            f"(suppress={suppress} stage={(target_ses or {}).get('stage')})")
                result.chain = []
            event.stop_event()
        except Exception as e:
            logger.warning(f"[LLM-STRIP] 拦截失败: {e}")

    # ==================== 配置 ====================

    def _flatten_leaves(self, cfg, out=None):
        """递归展开任意嵌套配置，收集所有已登记的叶子键（值为非 dict 的已知键）。

        可用于兼容旧版分组结构（account / game_search / game_report / ...）以及
        扁平旧配置、本地兜底文件等任意形态，最终都收敛为 {叶子键: 值}。
        """
        if out is None:
            out = {}
        if not isinstance(cfg, dict):
            return out
        for k, v in cfg.items():
            if k in _KEY_TO_GROUP:
                if isinstance(v, dict):
                    self._flatten_leaves(v, out)
                else:
                    out[k] = v
            elif isinstance(v, dict):
                self._flatten_leaves(v, out)
        return out

    def _migrate_config(self, cfg):
        """把任意旧版/新版嵌套配置统一归到当前分组（按叶子键重归类）。

        旧版配置可能按 account / game_search / game_report / software_report /
        movie_report / movie_search / netease_music 等分组存放；本方法递归收集
        所有叶子键并重新归到 game / software / movie / music / vip_video / browser /
        novel 新分组，避免升级后读取 KeyError 或读到 None。
        """
        nested = {g: {} for g in _CONF_GROUPS}
        if isinstance(cfg, dict):
            for k, v in self._flatten_leaves(cfg).items():
                nested[_KEY_TO_GROUP[k]][k] = v
        return nested

    def _get_config(self) -> dict:
        raw = self._plugin_config
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            try:
                raw = dict(raw)
            except Exception:
                try:
                    if hasattr(raw, '__dict__'):
                        raw = {k: v for k, v in raw.__dict__.items() if not k.startswith('_')}
                    else:
                        raw = {}
                except Exception:
                    raw = {}
        # 把 object 分组的叶子键提升到顶层，使旧读取代码（config.get("leaf")）继续有效
        flat = {}
        for k, v in raw.items():
            if k in _CONF_GROUPS and isinstance(v, dict):
                flat.update(v)
            else:
                flat[k] = v
        return flat

    @staticmethod
    def _parse_multi(val) -> list:
        """把「多选配置」统一解析为字符串列表。

        兼容三种来源：
        - AstrBot array 多选框（list / tuple / set）；
        - 旧版逗号分隔字符串（升级前用户填的 "123,456"）；
        - 空值（None / "" / []）返回 []。
        用于 game_group_ids / group_ids / movie_group_ids / movie_sections / sonovel_format。
        """
        if val is None:
            return []
        if isinstance(val, (list, tuple, set)):
            out = []
            for x in val:
                s = str(x).strip()
                if s:
                    out.append(s)
            return out
        if isinstance(val, str):
            return [x.strip() for x in val.split(",") if x.strip()]
        s = str(val).strip()
        return [s] if s else []

    def _resolve_group_ids(self, specific_key: str):
        """解析某日报的目标群（各自独立配置，不共享软件群）。

        - 仅读取各自专属键（game_group_ids / movie_group_ids 等）；
        - 不回退软件群 group_ids（用户要求三日报群号分开）；
        - 返回 (群列表, 是否走了回退) —— 当前不共享，fb 恒为 False。
        - 留空时由 `_resolve_report_groups` 决定是否推送到平台全部群。
        """
        config = self._get_config()
        raw = config.get(specific_key, []) if isinstance(config, dict) else []
        return self._parse_multi(raw), False

    # ---------- 日报目标群：留空 = 平台全部群 ----------

    def _seen_groups_path(self) -> str:
        return os.path.join(self._plugin_data_dir(), "report_groups.json")

    def _load_seen_groups(self):
        """加载「机器人见过的群」缓存，作为无 get_group_list 平台的后备。"""
        try:
            p = self._seen_groups_path()
            if not os.path.exists(p):
                return
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            cleaned = {}
            for pid, groups in data.items():
                if not isinstance(groups, list):
                    continue
                vals = []
                for gid in groups:
                    s = str(gid).strip()
                    if s and s not in vals:
                        vals.append(s)
                if vals:
                    cleaned[str(pid)] = vals
            # 合并而不是覆盖：initialize 之前可能已经通过消息记录过群
            for pid, vals in cleaned.items():
                cur = self._seen_groups.setdefault(pid, [])
                for gid in vals:
                    if gid not in cur:
                        cur.append(gid)
            logger.info(f"[暮黎资源] 已加载日报群缓存: {sum(len(v) for v in self._seen_groups.values())} 个群")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] 读取日报群缓存失败(忽略): {e!r}")

    def _save_seen_groups(self):
        try:
            p = self._seen_groups_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._seen_groups, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] 保存日报群缓存失败(忽略): {e!r}")

    def _remember_seen_group(self, platform_id, group_id):
        """记录机器人实际见过的群；新群才落盘，避免每条消息都写文件。"""
        pid = str(platform_id or "").strip()
        gid = str(group_id or "").strip()
        if not pid or not gid:
            return
        groups = self._seen_groups.setdefault(pid, [])
        if gid in groups:
            return
        groups.append(gid)
        self._all_groups_cache.pop(pid, None)
        self._save_seen_groups()

    @staticmethod
    def _extract_group_ids(payload) -> list:
        """从 OneBot/适配器返回的群列表里提取群号，兼容 dict/list 多种结构。"""
        if isinstance(payload, dict):
            for key in ("data", "groups", "group_list", "result"):
                if key in payload:
                    payload = payload[key]
                    break
        if not isinstance(payload, list):
            return []
        out, seen = [], set()
        for item in payload:
            if isinstance(item, dict):
                gid = (item.get("group_id") or item.get("group")
                       or item.get("id") or item.get("chat_id"))
            elif isinstance(item, (str, int)):
                gid = item
            else:
                gid = getattr(item, "id", None) or getattr(item, "chat_id", None)
            if gid is None or gid == "":
                continue
            s = str(gid).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    async def _fetch_platform_group_list(self, platform_id: str) -> list:
        """尝试调用平台适配器/协议端 API 获取全部群。失败返回 []。"""
        platform = None
        try:
            platform = self.context.get_platform_inst(platform_id)
        except Exception:
            platform = None
        if platform is None:
            try:
                for p in self.context.platform_manager.get_insts():
                    if str(p.meta().id) == str(platform_id):
                        platform = p
                        break
            except Exception:
                pass
        if platform is None:
            return []
        # ① 适配器自身可能提供群列表方法
        for name in ("get_group_list", "get_groups"):
            fn = getattr(platform, name, None)
            if not callable(fn):
                continue
            try:
                res = fn()
                if asyncio.iscoroutine(res):
                    res = await res
                gids = self._extract_group_ids(res)
                if gids:
                    return gids
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[暮黎资源] 平台 {platform_id}.{name} 获取群列表失败: {e!r}")
        # ② OneBot 协议端 get_group_list
        try:
            client = platform.get_client()
        except Exception:
            client = None
        if client is None:
            return []
        try:
            if hasattr(client, "call_action"):
                res = await client.call_action(action="get_group_list")
            elif hasattr(client, "api") and hasattr(client.api, "call_action"):
                try:
                    res = await client.api.call_action(action="get_group_list")
                except TypeError:
                    res = await client.api.call_action("get_group_list")
            else:
                return []
            return self._extract_group_ids(res)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[暮黎资源] 平台 {platform_id} get_group_list 失败: {e!r}")
            return []

    async def _get_all_report_groups(self) -> list:
        """获取日报平台的全部群；协议端不支持时回退到「见过的群」缓存。"""
        apid = self._resolve_report_platform()
        now = time.time()
        cached_result = self._all_groups_cache.get(apid)
        if cached_result and now - cached_result[0] < 300:
            return list(cached_result[1])
        try:
            gids = await asyncio.wait_for(self._fetch_platform_group_list(apid), timeout=10)
        except asyncio.TimeoutError:
            logger.warning(f"[暮黎资源] 获取平台 {apid} 群列表超时（10s），本次使用缓存")
            gids = []
        if gids:
            groups = self._seen_groups.setdefault(apid, [])
            changed = False
            for gid in gids:
                if gid not in groups:
                    groups.append(gid)
                    changed = True
            if changed:
                self._save_seen_groups()
            self._all_groups_cache[apid] = (now, list(gids))
            return gids
        cached = list(self._seen_groups.get(apid, []))
        self._all_groups_cache[apid] = (now, list(cached))
        if cached:
            logger.info(f"[暮黎资源] 平台 {apid} 不支持群列表 API，使用已见过的 {len(cached)} 个群")
        return cached

    async def _resolve_report_groups(self, key: str) -> list:
        """日报目标群：配置了白名单就用白名单，留空则推送到平台全部群。"""
        config = self._get_config()
        gids = self._parse_multi(config.get(key, []) if isinstance(config, dict) else [])
        if gids:
            return gids
        gids = await self._get_all_report_groups()
        if gids:
            logger.info(f"[暮黎资源] {key} 未配置，日报将推送到平台全部群（{len(gids)} 个）")
        else:
            logger.warning(f"[暮黎资源] {key} 未配置，且无法获取平台群列表（请填群号或先让机器人在目标群收到消息）")
        return gids

    def _get_cookie(self) -> str:
        return self._get_config().get("cookie", "").strip()

    async def _update_config(self, key: str, value: object):
        """持久化更新插件配置中的某个字段（issue4 修复：用插件 id 持久化 + 本地文件兜底）"""
        await self._update_configs({key: value})

    async def _update_configs(self, values: dict):
        """批量持久化插件配置（可视化配置页一次保存多个字段时只写一次磁盘）。"""
        if not isinstance(values, dict) or not values:
            return
        cfg = self._plugin_config
        if not isinstance(cfg, dict):
            cfg = {}
        for key, value in values.items():
            g = _KEY_TO_GROUP.get(key)
            if g is not None:
                if not isinstance(cfg.get(g), dict):
                    cfg[g] = {}
                cfg[g][key] = value
            else:
                cfg[key] = value
        self._plugin_config = cfg
        # ① 写回 AstrBot 的 AstrBotConfig（data/config/<插件名>_config.json）。
        #    这是当前 AstrBot 配置页真正读取的配置对象，必须同步更新，
        #    否则可视化页面保存后重载插件会回到旧值。
        raw_cfg = getattr(self, "_raw_config", None)
        save_cfg = getattr(raw_cfg, "save_config", None)
        if callable(save_cfg):
            try:
                save_cfg(cfg)
                names = ", ".join(values.keys())
                logger.info(f"[暮黎资源] 配置已写入 AstrBot: {names}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[暮黎资源] 写回 AstrBot 配置失败: {e}")
        # ② 兼容旧版/其他实现的 update_plugin_config
        try:
            if hasattr(self.context, 'update_plugin_config'):
                pid = self._plugin_id()
                # AstrBot 签名：update_plugin_config(plugin_id: str, config: dict)
                await self.context.update_plugin_config(pid, cfg)
                names = ", ".join(values.keys())
                logger.info(f"[暮黎资源] 配置已持久化: {names} (pid={pid})")
        except Exception as e:
            logger.warning(f"[暮黎资源] 配置持久化(update_plugin_config)失败: {e}")
        # 兜底：写入本地文件，防止 AstrBot 配置未落盘导致重装/重启后 Cookie 丢失
        try:
            self._persist_config_file(cfg)
        except Exception as e:
            logger.warning(f"[暮黎资源] 配置本地文件写入失败: {e}")

    def _plugin_id(self) -> str:
        """返回插件名（与 AstrBot WebUI / 插件页面 bridge 使用的 pluginName 一致）。

        AstrBot 的插件模块路径实际是 ``data.plugins.<插件目录名>.main``，
        直接取 ``module.split('.')[0]`` 会得到 ``data``，导致：
        ① 配置回写用错插件名；② register_web_api 注册到 /data/... 路由，
        插件页面请求 /<插件名>/... 时提示「未找到该路由」。
        """
        name = getattr(self, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        mod = self.__class__.__module__
        parts = [p for p in mod.split(".") if p]
        if len(parts) >= 2:
            return parts[-2] if parts[-1] == "main" else parts[-1]
        return os.path.basename(os.path.dirname(os.path.abspath(__file__)))

    def _plugin_data_dir(self) -> str:
        """插件持久化数据目录：<AstrBot data>/plugin_data/astrbot_plugin_muliyresources。

        上架规范：持久化数据（Cookie 兜底、日报缓存 zip、调度调试日志等）必须放在
        插件目录【之外】的 AstrBot data 目录下；插件目录在卸载/覆盖重装时会被删除，
        否则会造成用户数据丢失、也无法参与数据迁移与审计。
        定位不到 AstrBot data 目录时，最终兜底到用户主目录（也绝不写入插件安装目录）。
        """
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        # 优先：AstrBot 全局配置里的 data_dir（重装/覆盖插件目录也不会被删）
        try:
            gcfg = self.context.get_config()
            dd = getattr(gcfg, "data_dir", None)
            if not dd and isinstance(gcfg, dict):
                dd = gcfg.get("data_dir")
            if dd and os.path.isdir(dd):
                return os.path.join(dd, "plugin_data", "astrbot_plugin_muliyresources")
        except Exception:
            pass
        # 兜底：从插件目录向上找包含 plugins/ 的目录（即 AstrBot data 目录）
        cur = base
        for _ in range(6):
            if os.path.isdir(os.path.join(cur, "plugins")):
                return os.path.join(cur, "plugin_data", "astrbot_plugin_muliyresources")
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        # 最终兜底：用户主目录下的稳定位置（不写插件安装目录，避免卸载/重装丢数据）
        return os.path.join(os.path.expanduser("~"), ".astrbot_plugin_muliyresources")

    def _config_file_path(self) -> str:
        """Cookie 等敏感配置的兜底文件路径。

        关键：必须放在【插件目录之外】（AstrBot data 目录或用户主目录），
        否则「卸载/覆盖重装插件」会把插件目录一起删掉，兜底文件也跟着没了
        （这正是之前 switch618_cookie 重装必丢的根因）。
        """
        import os
        return os.path.join(self._plugin_data_dir(), "config_override.json")

    def _persist_config_file(self, cfg: dict):
        import os, json
        p = self._config_file_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    def _load_config_file(self) -> dict:
        import os, json
        p = self._config_file_path()
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    # ==================== 可视化配置页面（AstrBot 插件页面） ====================

    def _register_config_view(self):
        """注册可视化配置页所需的后端 Web API。

        页面本体位于 pages/config/（兼容 views/config/）。旧版 AstrBot 没有
        register_web_api 时静默跳过，不影响插件本身和原配置页。
        """
        register = getattr(self.context, "register_web_api", None)
        if not callable(register):
            logger.info("[暮黎资源] 当前 AstrBot 不支持插件页面 API，继续使用原配置页")
            return
        pid = self._plugin_id()
        try:
            register(f"/{pid}/config-view", self.view_config_get, ["GET"],
                     "读取暮黎资源可视化配置")
            register(f"/{pid}/config-view/save", self.view_config_save, ["POST"],
                     "保存暮黎资源可视化配置")
            logger.info(f"[暮黎资源] 可视化配置页 API 已注册: /{pid}/config-view")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] 可视化配置页 API 注册失败: {e}")

    def _load_conf_schema(self) -> dict:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_conf_schema.json")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _view_bool(value, default=False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("true", "1", "yes", "y", "on", "开", "是"):
                return True
            if s in ("false", "0", "no", "n", "off", "关", "否"):
                return False
        if value is None:
            return bool(default)
        return bool(value)

    @staticmethod
    def _view_int(value, default=0) -> int:
        try:
            if isinstance(value, bool):
                return int(default)
            if isinstance(value, str) and not value.strip():
                return int(default)
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return int(default)

    @staticmethod
    def _view_secret_key(key: str) -> bool:
        k = key.lower()
        return any(h in k for h in _VIEW_SECRET_HINTS)

    @staticmethod
    def _view_long_list(value) -> bool:
        """推荐清单这类长文本列表用多行文本框，群号这类短列表用标签编辑器。"""
        if not isinstance(value, (list, tuple)) or not value:
            return False
        # 推荐项通常带「名称|一句话」，长度明显大于群号；阈值放宽到 16，
        # 让 Discord 等较长 ID 也能用多行文本，避免标签过长。
        return max(len(str(x)) for x in value) > 16

    def _view_value_for(self, field: dict, cfg: dict):
        """把当前配置值按 schema 类型归一化，供前端直接渲染。"""
        key = field.get("_key", "")
        default = field.get("default")
        raw = cfg.get(key, default)
        if raw is None and default is not None:
            raw = default
        ftype = str(field.get("type") or "string").lower()
        if ftype == "bool":
            return self._view_bool(raw, self._view_bool(default, False))
        if ftype in ("int", "integer"):
            val = self._view_int(raw, self._view_int(default, 0))
            mn, mx = field.get("min"), field.get("max")
            if mn is not None:
                val = max(self._view_int(mn, val), val)
            if mx is not None:
                val = min(self._view_int(mx, val), val)
            return val
        if ftype in ("float", "number"):
            try:
                return float(raw)
            except (TypeError, ValueError):
                try:
                    return float(default or 0)
                except (TypeError, ValueError):
                    return 0.0
        if ftype == "list":
            return self._parse_multi(raw)
        if ftype == "dict":
            return raw if isinstance(raw, dict) else (default if isinstance(default, dict) else {})
        if raw is None:
            return "" if default is None else str(default)
        return str(raw)

    def _view_coerce(self, key: str, field: dict, value):
        """校验并归一化前端提交的单个字段。返回 (ok, value, error)。"""
        ftype = str(field.get("type") or "string").lower()
        label = str(field.get("description") or key)
        if ftype == "bool":
            if isinstance(value, bool):
                return True, value, ""
            if isinstance(value, (int, float)) and value in (0, 1):
                return True, bool(value), ""
            if isinstance(value, str):
                s = value.strip().lower()
                if s in ("true", "1", "yes", "y", "on", "开", "是"):
                    return True, True, ""
                if s in ("false", "0", "no", "n", "off", "关", "否"):
                    return True, False, ""
            return False, None, f"{label} 需要是开关值"
        if ftype in ("int", "integer", "float", "number"):
            try:
                if isinstance(value, bool):
                    raise ValueError
                if isinstance(value, str) and not value.strip():
                    raise ValueError
                num = float(value)
            except (TypeError, ValueError, OverflowError):
                return False, None, f"{label} 需要是数字"
            if not (num == num and num not in (float("inf"), float("-inf"))):
                return False, None, f"{label} 需要是有效数字"
            if ftype in ("int", "integer"):
                num = int(num)
                mn, mx = field.get("min"), field.get("max")
                if mn is not None:
                    num = max(int(mn), num)
                if mx is not None:
                    num = min(int(mx), num)
                return True, num, ""
            return True, float(num), ""
        if ftype == "list":
            if value is None:
                raw = []
            elif isinstance(value, str):
                raw = re.split(r"[\n,，;；]", value)
            elif isinstance(value, (list, tuple, set)):
                raw = list(value)
            else:
                raw = [value]
            out, seen = [], set()
            for item in raw:
                if isinstance(item, (dict, list, tuple, set)):
                    return False, None, f"{label} 的每一项都需要是文本"
                s = str(item).strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                out.append(s)
            allowed = _VIEW_LIST_CHOICES.get(key)
            if allowed is None:
                raw_options = field.get("options")
                if isinstance(raw_options, list) and raw_options:
                    allowed = {str(x) for x in raw_options}
            if allowed is not None:
                bad = [x for x in out if x not in allowed]
                if bad:
                    return False, None, f"{label} 不支持：{', '.join(bad)}"
            return True, out, ""
        if ftype == "dict":
            return False, None, f"{label} 是嵌套配置，请使用原配置页编辑"
        if isinstance(value, (dict, list, tuple, set)):
            return False, None, f"{label} 需要是文本"
        return True, ("" if value is None else str(value)).strip(), ""

    def _view_next_run(self, job_id: str) -> str:
        try:
            if self._using_framework_scheduler:
                sch = self._framework_scheduler()
                job = sch.get_job(job_id) if sch else None
            else:
                job = self._apscheduler.get_job(job_id) if self._apscheduler else None
            dt = self._job_next_run(job, self._timezone)
            if dt:
                return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        return ""

    def _view_meta(self, groups: list, cfg: dict) -> dict:
        meta = {"display_name": "暮黎资源聚合", "version": ""}
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.yaml")
            with open(p, encoding="utf-8") as f:
                text = f.read()
            m = re.search(r'^display_name:\s*["\']?([^"\'\n]+)', text, re.M)
            if m:
                meta["display_name"] = m.group(1).strip()
            m = re.search(r'^version:\s*["\']?([^"\'\s]+)', text, re.M)
            if m:
                meta["version"] = m.group(1).strip()
        except Exception:
            pass

        def _clock(key: str, default: int, upper: int) -> int:
            return max(0, min(upper, self._view_int(cfg.get(key), default)))

        schedules = [
            {
                "key": "software", "name": "软件日报", "enabled": True,
                "hour": _clock("schedule_hour", 22, 23),
                "minute": _clock("schedule_minute", 0, 59),
                "groups": len(self._parse_multi(cfg.get("group_ids", []))),
                "all_groups": not bool(self._parse_multi(cfg.get("group_ids", []))),
                "next": self._view_next_run(self._scheduler_job_id),
            },
            {
                "key": "game", "name": "游戏日报",
                "enabled": self._view_bool(cfg.get("game_report_enabled"), True),
                "hour": _clock("game_schedule_hour", 18, 23),
                "minute": _clock("game_schedule_minute", 0, 59),
                "groups": len(self._parse_multi(cfg.get("game_group_ids", []))),
                "all_groups": not bool(self._parse_multi(cfg.get("game_group_ids", []))),
                "next": self._view_next_run(self._game_scheduler_job_id),
            },
            {
                "key": "movie", "name": "影视日报",
                "enabled": self._view_bool(cfg.get("movie_report_enabled"), True),
                "hour": _clock("movie_schedule_hour", 20, 23),
                "minute": _clock("movie_schedule_minute", 0, 59),
                "groups": len(self._parse_multi(cfg.get("movie_group_ids", []))),
                "all_groups": not bool(self._parse_multi(cfg.get("movie_group_ids", []))),
                "next": self._view_next_run(self._movie_scheduler_job_id),
            },
            {
                "key": "drama", "name": "短剧日报",
                "enabled": self._view_bool(cfg.get("drama_report_enabled"), True),
                "hour": _clock("drama_schedule_hour", 21, 23),
                "minute": _clock("drama_schedule_minute", 0, 59),
                "groups": len(self._parse_multi(cfg.get("drama_group_ids", []))),
                "all_groups": not bool(self._parse_multi(cfg.get("drama_group_ids", []))),
                "next": self._view_next_run(self._drama_scheduler_job_id),
            },
        ]
        mode = "idle"
        running = False
        if self._using_framework_scheduler:
            mode = "framework"
            running = self._framework_scheduler() is not None
        elif self._apscheduler is not None:
            mode = "local"
            running = bool(getattr(self._apscheduler, "running", False))
        features = [
            {"key": "list_card", "label": "长列表图片",
             "enabled": self._view_bool(cfg.get("list_card_enabled"), True)},
            {"key": "points", "label": "签到积分",
             "enabled": self._view_bool(cfg.get("points_enabled"), False)},
            {"key": "music", "label": "网易云名片",
             "enabled": self._view_bool(cfg.get("wyy_auto_parse"), True)},
            {"key": "vip_video", "label": "VIP 视频解析",
             "enabled": self._view_bool(cfg.get("video_vip_parse"), True)},
            {"key": "verify", "label": "入群审核",
             "enabled": self._view_bool(cfg.get("join_verify_enabled"), False)},
            {"key": "minigame", "label": "群聊小游戏",
             "enabled": self._view_bool(cfg.get("minigame_enabled"), True)},
        ]
        meta.update({
            "plugin_name": self._plugin_id(),
            "description": "影视 / 游戏 / 软件 / 短剧 / 小说 多源搜索与定时日报",
            "timezone": (
                (getattr(self._timezone, "key", None) or str(self._timezone))
                if self._timezone is not None else "系统本地"
            ),
            "data_dir": self._view_safe_path(self._plugin_data_dir),
            "config_backup": self._view_safe_path(self._config_file_path),
            "scheduler_mode": mode,
            "scheduler_running": running,
            "schedules": schedules,
            "features": features,
            "group_count": len(groups),
            "field_count": sum(len(g.get("fields", [])) for g in groups),
        })
        return meta

    @staticmethod
    def _view_safe_path(getter):
        """路径解析失败时不影响整个配置页面。"""
        try:
            return getter()
        except Exception:
            return ""

    async def view_config_get(self):
        """GET：返回 schema + 当前值 + 运行状态，供可视化配置页渲染。"""
        try:
            schema = self._load_conf_schema()
            current = self._get_config()
            cfg = current if isinstance(current, dict) else {}
            groups = []
            order = [g for g in _VIEW_GROUP_ORDER if g in schema]
            order += [g for g in schema if g not in order]
            for gkey in order:
                group = schema.get(gkey)
                if not isinstance(group, dict):
                    continue
                items = group.get("items")
                if not isinstance(items, dict):
                    continue
                fields = []
                for fkey, field in items.items():
                    if not isinstance(field, dict):
                        continue
                    f = dict(field)
                    f["_key"] = fkey
                    ftype = str(f.get("type") or "string").lower()
                    value = self._view_value_for(f, cfg)
                    default = f.get("default")
                    if ftype == "list":
                        default = self._parse_multi(default)
                        value = self._parse_multi(value)
                    options = _VIEW_FIELD_OPTIONS.get(fkey)
                    if options is None:
                        raw_options = f.get("options")
                        if isinstance(raw_options, list) and raw_options:
                            labels = f.get("labels")
                            labels = labels if isinstance(labels, list) else []
                            options = [
                                {
                                    "value": str(opt),
                                    "label": str(labels[i]) if i < len(labels) else str(opt),
                                }
                                for i, opt in enumerate(raw_options)
                            ]
                    fields.append({
                        "key": fkey,
                        "type": ftype,
                        "label": str(f.get("description") or fkey),
                        "hint": str(f.get("hint") or ""),
                        "default": default,
                        "value": value,
                        "min": f.get("min"),
                        "max": f.get("max"),
                        "condition": f.get("condition") if isinstance(f.get("condition"), dict) else {},
                        "options": options,
                        "secret": self._view_secret_key(fkey),
                        "long_items": ftype == "list" and self._view_long_list(default),
                    })
                present = {f["key"] for f in fields}
                sections = []
                for i, spec in enumerate(_VIEW_SECTIONS.get(gkey) or []):
                    if not isinstance(spec, dict):
                        continue
                    keys = [k for k in (spec.get("keys") or []) if k in present]
                    if not keys:
                        continue
                    sections.append({
                        "key": str(spec.get("key") or f"sec{i}"),
                        "title": str(spec.get("title") or ""),
                        "hint": str(spec.get("hint") or ""),
                        "icon": str(spec.get("icon") or _VIEW_GROUP_ICONS.get(gkey, "apps")),
                        "keys": keys,
                    })
                groups.append({
                    "key": gkey,
                    "title": str(group.get("description") or gkey),
                    "hint": str(group.get("hint") or ""),
                    "icon": _VIEW_GROUP_ICONS.get(gkey, "apps"),
                    "fields": fields,
                    "sections": sections,
                })
            return {"status": "ok", "data": {"groups": groups, "meta": self._view_meta(groups, cfg)}}
        except Exception as e:  # noqa: BLE001
            logger.error(f"[暮黎资源] 读取可视化配置失败: {e}\n{traceback.format_exc()}")
            return {"status": "error", "message": f"读取配置失败：{e}"}

    async def _view_read_json(self) -> dict:
        try:
            from astrbot.api.web import request as web_request
        except Exception:
            web_request = None
        if web_request is not None:
            try:
                data = await web_request.json(default={})
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        try:
            from quart import request as quart_request
            data = await quart_request.get_json(silent=True)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def view_config_save(self):
        """POST：批量保存可视化配置页提交的字段，并按需重载定时任务。"""
        try:
            payload = await self._view_read_json()
            values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
            if not isinstance(values, dict) or not values:
                return {"status": "error", "message": "没有收到需要保存的配置项"}
            if len(values) > 300:
                return {"status": "error", "message": "一次提交的配置项过多"}
            schema = self._load_conf_schema()
            fields = {}
            for group in schema.values():
                items = group.get("items") if isinstance(group, dict) else None
                if isinstance(items, dict):
                    fields.update({k: v for k, v in items.items() if isinstance(v, dict)})
            cleaned, errors = {}, {}
            for key, value in values.items():
                if key not in fields:
                    errors[key] = "未知配置项"
                    continue
                ok, val, err = self._view_coerce(key, fields[key], value)
                if not ok:
                    errors[key] = err
                    continue
                cleaned[key] = val
            if errors:
                first = next(iter(errors.values()))
                return {"status": "error", "message": first, "errors": errors}
            if not cleaned:
                return {"status": "ok", "data": {"saved": 0, "schedule_reloaded": False, "values": {}}}
            await self._update_configs(cleaned)
            reloaded = False
            if _VIEW_SCHEDULE_KEYS & set(cleaned):
                try:
                    await self._start_sw_scheduler()
                    reloaded = True
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[暮黎资源] 保存配置后重载定时任务失败: {e}")
            logger.info(f"[暮黎资源] 可视化配置已保存 {len(cleaned)} 项: {', '.join(cleaned)}")
            return {"status": "ok", "data": {
                "saved": len(cleaned),
                "schedule_reloaded": reloaded,
                "values": cleaned,
            }}
        except Exception as e:  # noqa: BLE001
            logger.error(f"[暮黎资源] 保存可视化配置失败: {e}\n{traceback.format_exc()}")
            return {"status": "error", "message": f"保存失败：{e}"}

    # ==================== 全局积分 / 每日签到 ====================

    def _points_settings(self) -> dict:
        """把积分相关配置归一化为统一结构（缺失 / 非法值自动回退默认）。"""
        cfg = self._get_config()
        if not isinstance(cfg, dict):
            cfg = {}

        def _int(key: str, default: int) -> int:
            try:
                return max(0, int(cfg.get(key, default)))
            except (TypeError, ValueError):
                return max(0, int(default))

        def _list(key: str, default: list) -> list:
            raw = cfg.get(key)
            return self._parse_multi(default if raw is None else raw)

        return {
            "enabled": bool(cfg.get("points_enabled", False)),
            "initial": _int("points_initial", 0),
            "checkin": _int("checkin_points", 10),
            "streak_bonus": _int("checkin_streak_bonus", 0),
            "streak_max": max(1, _int("checkin_streak_max", 7)),
            "card_enabled": bool(cfg.get("checkin_card_enabled", True)),
            "info_module": str(cfg.get("checkin_info_module") or "epic").strip().lower(),
            "weather_city": str(cfg.get("checkin_weather_city") or "").strip(),
            "recommend_dynamic": bool(cfg.get("checkin_recommend_dynamic", True)),
            "recommend_games": _list("checkin_recommend_games", DEFAULT_RECOMMEND_GAMES),
            "recommend_software": _list("checkin_recommend_software", DEFAULT_RECOMMEND_SOFTWARE),
            "recommend_movies": _list("checkin_recommend_movies", DEFAULT_RECOMMEND_MOVIES),
            "costs": {
                "game": _int("points_cost_game", 5),
                "software": _int("points_cost_software", 5),
                "movie": _int("points_cost_movie", 5),
                "drama": _int("points_cost_drama", 5),
                "novel": _int("points_cost_novel", 5),
            },
        }

    def _points_db(self) -> PointsStore:
        """懒加载积分存储（路径依赖 AstrBot data 目录，不能在 __init__ 里固定）。"""
        if self._points_store is None:
            self._points_store = PointsStore(
                os.path.join(self._plugin_data_dir(), "points.json"),
                tz_getter=lambda: self._timezone,
            )
        return self._points_store

    def _points_user(self, event: AstrMessageEvent) -> tuple[str, str, str]:
        """返回 (存储键, 用户ID, 昵称)。键包含平台标识，跨群聊/私聊共享。"""
        try:
            uid = str(event.get_sender_id() or "")
        except Exception:
            uid = ""
        try:
            platform = str(event.get_platform_id() or "")
        except Exception:
            platform = ""
        try:
            name = str(event.get_sender_name() or "")
        except Exception:
            name = ""
        if not uid:
            # 极少数平台取不到用户 ID 时退回会话标识，避免所有用户共用一个 anonymous 账户
            try:
                uid = str(getattr(event, "unified_msg_origin", "") or "anonymous")
            except Exception:
                uid = "anonymous"
        return PointsStore.make_key(platform, uid), uid, name

    def _points_guard(self, event: AstrMessageEvent, kind: str) -> Optional[str]:
        """搜索前不再拦截/扣费；余额只在最终获取资源时检查。"""
        return None

    def _points_charge(self, event: AstrMessageEvent, kind: str,
                       keyword: str = "") -> str:
        """兼容旧调用：搜索阶段不再扣费，统一在最终链接/文件发送时扣。

        保留此方法是为了不改动大量历史调用点；实际扣费见 `_points_final_charge`。
        """
        return ""

    def _points_final_charge(self, event: AstrMessageEvent, kind: str,
                             title: str = "") -> tuple[bool, str]:
        """获取到最终资源（网盘链接 / 播放直链 / 文件）时扣费。

        返回 (是否成功, 追加到消息末尾的提示)。搜索阶段不扣费。
        """
        s = self._points_settings()
        if not s["enabled"]:
            return True, ""
        cost = int(s["costs"].get(kind, 0) or 0)
        if cost <= 0:
            return True, ""
        key, _uid, name = self._points_user(event)
        try:
            ok, balance = self._points_db().spend(key, cost, name, s["initial"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源·积分] 最终扣费失败（已放行）: {e}")
            return True, ""
        logger.info(f"[暮黎资源·积分] 最终扣费 {kind} cost={cost} title={title[:20]!r} "
                    f"ok={ok} balance={balance}")
        if not ok:
            label = _POINTS_LABELS.get(kind, kind)
            return False, (f"【暮黎资源·积分】\n"
                           f"💰 获取{label}资源需要 {cost} 积分，你当前只有 {balance} 积分。\n"
                           f"📅 发送 /签到 领取每日积分后再试。")
        # 已扣费：同步标记断点，引用旧列表换资源时不再重复扣
        self._mark_breakpoints_charged(event)
        return True, (f"\n\n💰 本次获取资源消耗 {cost} 积分，剩余 {balance} 积分"
                      f"（发送 /签到 领取每日积分）")

    def _points_can_afford(self, event: AstrMessageEvent, kind: str) -> tuple[bool, int, int]:
        """只检查余额，不扣费。返回 (是否足够, 余额, 价格)。"""
        s = self._points_settings()
        if not s["enabled"]:
            return True, 0, 0
        cost = int(s["costs"].get(kind, 0) or 0)
        if cost <= 0:
            return True, 0, 0
        key, _uid, name = self._points_user(event)
        try:
            user = self._points_db().get(key, name, s["initial"])
            balance = int(user.get("points", 0) or 0)
        except Exception:
            return True, 0, cost
        return balance >= cost, balance, cost

    def _points_spend_now(self, event: AstrMessageEvent, kind: str) -> tuple[bool, int, int]:
        """立即扣费（用于文件已成功发送后的补扣）。返回 (成功, 余额, 价格)。"""
        s = self._points_settings()
        if not s["enabled"]:
            return True, 0, 0
        cost = int(s["costs"].get(kind, 0) or 0)
        if cost <= 0:
            return True, 0, 0
        key, _uid, name = self._points_user(event)
        try:
            ok, balance = self._points_db().spend(key, cost, name, s["initial"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源·积分] 补扣失败（已放行）: {e}")
            return True, 0, cost
        return ok, balance, cost

    def _points_card_data(self, event: AstrMessageEvent) -> Optional[dict]:
        """读取积分卡所需的全部数据（文本与图片共用，避免读两次库）。"""
        s = self._points_settings()
        key, uid, name = self._points_user(event)
        try:
            user = self._points_db().get(key, name, s["initial"])
        except Exception as e:
            logger.warning(f"[暮黎资源·积分] 读取积分卡失败: {e}")
            return None
        today = self._points_day().strftime("%Y-%m-%d")
        last = str(user.get("last_checkin") or "")
        return {
            "name": name or uid or "用户",
            "uid": uid,
            "balance": int(user.get("points", 0) or 0),
            "streak": int(user.get("streak", 0) or 0),
            "last_checkin": last,
            "total_earned": int(user.get("total_earned", 0) or 0),
            "total_spent": int(user.get("total_spent", 0) or 0),
            "costs": {k: int(s["costs"].get(k, 0) or 0) for k in _POINTS_LABELS},
            "labels": dict(_POINTS_LABELS),
            "enabled": bool(s["enabled"]),
            "today": today,
            "today_checked": last == today,
            "date_label": today,
        }

    def _points_card_text(self, d: dict) -> str:
        costs = " ｜ ".join(f"{d['labels'][k]} {d['costs'][k]}" for k in d["labels"])
        lines = [
            "【暮黎资源·积分】",
            f"👤 {d['name']}",
            f"💰 当前积分：{d['balance']}",
            f"🔥 连续签到：{d['streak']} 天 ｜ 📅 最近签到：{d['last_checkin'] or '从未签到'}",
            f"🧾 累计获得 {d['total_earned']} ｜ 累计消耗 {d['total_spent']}",
            f"📌 搜索消耗：{costs}",
        ]
        if d["enabled"]:
            lines.append("📅 发送 /签到 领取每日积分。")
        else:
            lines.append("⚠️ 积分系统当前未开启（仅展示历史数据）。")
        return "\n".join(lines)

    def _points_card(self, event: AstrMessageEvent) -> str:
        d = self._points_card_data(event)
        if not d:
            return "【暮黎资源·积分】\n⚠️ 积分数据读取失败，请稍后再试。"
        return self._points_card_text(d)

    async def _send_points_card(self, event: AstrMessageEvent) -> None:
        """积分卡：优先发图片卡片，失败/未启用时回退文本。"""
        d = self._points_card_data(event)
        if not d:
            await event.send(MessageChain([Plain(
                "【暮黎资源·积分】\n⚠️ 积分数据读取失败，请稍后再试。")]))
            return
        cards_on, _ = self._list_card_cfg()
        html = ""
        if cards_on and points_card_html:
            try:
                html = points_card_html(**d)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 积分卡构建失败，回退文本: {e}")
        img = None
        if html and render_list_card:
            try:
                img = await asyncio.to_thread(render_list_card, html)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 积分卡渲染异常，回退文本: {e}")
        if img and await self._send_card_image(event, img, "暮黎_积分.jpg"):
            return
        await event.send(MessageChain([Plain(self._points_card_text(d))]))

    def _points_day(self) -> datetime.date:
        """签到日期按插件时区计算（默认 Asia/Shanghai）。"""
        try:
            if self._timezone:
                return datetime.datetime.now(self._timezone).date()
        except Exception:
            pass
        return datetime.date.today()

    def _recommend_source(self, kind: str) -> str:
        """返回动态推荐应使用的源；空串表示该类型暂不做动态（回退静态清单）。"""
        if kind == "movie":
            return "pdy" if self._movie_source() == "pdy" else "muliy"
        if kind == "game":
            return self._game_source()
        if kind == "software":
            return "x6d"
        return ""

    def _dynamic_recommendation(self, kind: str, day: datetime.date):
        """按当前搜索源取一个动态推荐；结果按「类型:源:日期」缓存一天。"""
        source = self._recommend_source(kind)
        if not source:
            return None
        cache_key = f"{kind}:{source}:{day.isoformat()}"
        hit = self._rec_cache.get(cache_key)
        if hit and hit[0] > time.time():
            return hit[1]

        item = None
        try:
            if kind == "movie":
                if source == "pdy":
                    item = self._get_pdy_client().random_movie()
                elif source == "muliy":
                    client = self._get_muliy_client()
                    item = get_random_movie_muliy(client) if client else None
                else:
                    item = get_random_movie()
            elif kind == "game":
                if source == "switch618":
                    item = get_random_game_618(self._g_cookie())
                else:
                    item = get_random_game_xdgame()
            elif kind == "software":
                item = get_random_software_recent()
            if isinstance(item, dict) and item.get("name"):
                logger.info(f"[暮黎资源·签到] 动态推荐 {kind}/{source}: {item['name']}")
            else:
                item = None
        except Exception as e:
            logger.warning(f"[暮黎资源·签到] 动态推荐失败 {kind}/{source}: {e}")
            item = None

        # 成功缓存一天；失败只缓存 10 分钟，避免把临时故障锁死一整天
        self._rec_cache[cache_key] = (time.time() + (86400 if item else 600), item)
        return item

    async def _pick_checkin_recs_async(self, s: dict, day: datetime.date) -> list:
        pools = {
            "game": list(s.get("recommend_games") or []),
            "software": list(s.get("recommend_software") or []),
            "movie": list(s.get("recommend_movies") or []),
        }
        if s.get("recommend_dynamic", True):
            kinds = ("movie", "game", "software")
            tasks = [
                asyncio.wait_for(
                    asyncio.to_thread(self._dynamic_recommendation, kind, day), timeout=9)
                for kind in kinds
            ]
            got = await asyncio.gather(*tasks, return_exceptions=True)
            for kind, item in zip(kinds, got):
                if isinstance(item, BaseException) or not isinstance(item, dict):
                    continue
                if item.get("name"):
                    pools[kind] = [item]
        try:
            return pick_recommendations(
                pools["game"], pools["software"], pools["movie"], day)
        except Exception:
            return []

    def _perform_checkin(self, event: AstrMessageEvent) -> dict:
        """执行签到并返回原始结果；error 字段表示未开启 / 存储失败。"""
        s = self._points_settings()
        if not s["enabled"]:
            return {"error": "disabled"}
        key, uid, name = self._points_user(event)
        try:
            r = self._points_db().checkin(
                key, s["checkin"], s["streak_bonus"], s["streak_max"], name, s["initial"])
        except Exception as e:
            logger.warning(f"[暮黎资源·积分] 签到失败: {e}")
            return {"error": "io"}
        r.update({"name": name or uid, "uid": uid, "key": key})
        if not r.get("duplicate"):
            logger.info(f"[暮黎资源·积分] 签到 {key} earned={r['earned']} "
                        f"streak={r['streak']} balance={r['balance']}")
        return r

    def _format_checkin_text(self, r: dict) -> str:
        if r.get("error") == "disabled":
            return "【暮黎资源·签到】\n⚠️ 签到积分功能尚未开启，请联系管理员。"
        if r.get("error"):
            return "【暮黎资源·签到】\n⚠️ 签到数据保存失败，请稍后再试。"
        if r.get("duplicate"):
            return (f"【暮黎资源·签到】\n"
                    f"📅 今天已经签到过啦，明天再来～\n"
                    f"💰 当前积分：{r['balance']} ｜ 🔥 连续签到：{r['streak']} 天")
        bonus_txt = f"（连续 {r['streak']} 天，额外 +{r['bonus']}）" if r.get("bonus") else ""
        return (f"【暮黎资源·签到】\n"
                f"✅ 签到成功，获得 {r['earned']} 积分{bonus_txt}\n"
                f"💰 当前积分：{r['balance']} ｜ 🔥 连续签到：{r['streak']} 天\n"
                f"📅 明天再来可继续累计连续签到。")

    def _do_checkin(self, event: AstrMessageEvent) -> str:
        """纯文本签到结果（保留给旧调用方 / 兜底）。"""
        return self._format_checkin_text(self._perform_checkin(event))

    async def _send_checkin(self, event: AstrMessageEvent) -> None:
        """签到入口：优先发送 HTML 卡片图，失败时退回文本。"""
        if getattr(event, "_muliy_checkin_sent", False):
            return
        try:
            setattr(event, "_muliy_checkin_sent", True)
        except Exception:
            pass

        r = self._perform_checkin(event)
        text = self._format_checkin_text(r)
        s = self._points_settings()
        day = self._points_day()
        recs = await self._pick_checkin_recs_async(s, day)

        if not r.get("error") and s.get("card_enabled", True):
            try:
                img = await self._build_checkin_card(r, s, recs, day)
            except Exception as e:
                logger.warning(f"[暮黎资源·签到] 卡片生成失败，回退文本: {e}")
                img = None
            if img and await self._send_checkin_image(event, img):
                return

        if not r.get("error"):
            rec_text = recommendation_text(recs)
            if rec_text:
                text = f"{text}\n\n{rec_text}"
        try:
            await event.send(MessageChain([Plain(text)]))
        except Exception as e:
            logger.error(f"[暮黎资源·签到] 文本发送失败: {e}")

    async def _build_checkin_card(self, r: dict, s: dict, recs: list,
                                  day: datetime.date) -> bytes | None:
        """并行抓壁纸 / 左下信息模块 / 一言，拼 HTML 并渲染为图片。"""
        cfg = self._get_config()
        channel = (cfg.get("browser_channel", "") or "").strip() if isinstance(cfg, dict) else ""
        exe = (cfg.get("browser_exe", "") or "").strip() if isinstance(cfg, dict) else ""
        info_module = (s.get("info_module") or "epic").strip().lower()

        tasks = [asyncio.wait_for(
            asyncio.to_thread(fetch_bing_wallpaper, day.isoformat(), 5), timeout=7)]
        if info_module == "off":
            tasks.append(asyncio.sleep(0, result=None))
        else:
            tasks.append(asyncio.wait_for(
                asyncio.to_thread(fetch_info, info_module, day,
                                  s.get("weather_city", ""), 4), timeout=6))
        tasks.append(asyncio.wait_for(
            asyncio.to_thread(fetch_hitokoto, 4), timeout=5))
        got = await asyncio.gather(*tasks, return_exceptions=True)

        wallpaper = None if isinstance(got[0], BaseException) else got[0]
        info = None if isinstance(got[1], BaseException) else got[1]
        quote = None if isinstance(got[2], BaseException) else got[2]
        if not isinstance(quote, dict) or not quote.get("text"):
            quote = {"text": "生活明朗，万物可爱。", "from": "暮黎资源"}

        html = build_checkin_html(
            user_name=r.get("name") or "",
            date_label=day.strftime("%Y年%m月%d日"),
            weekday="星期" + "一二三四五六日"[day.weekday()],
            earned=int(r.get("earned", 0) or 0),
            bonus=int(r.get("bonus", 0) or 0),
            streak=int(r.get("streak", 0) or 0),
            balance=int(r.get("balance", 0) or 0),
            duplicate=bool(r.get("duplicate")),
            wallpaper=wallpaper,
            info=info,
            quote_data=quote,
            recommendations=recs,
            info_module=info_module,
        )
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        img = await asyncio.to_thread(
            render_checkin_png, html, font_path, 720, channel, exe)
        if img:
            logger.info(f"[暮黎资源·签到] 卡片渲染完成（Playwright，{len(img)//1024}KB）")
            return img
        img = await self._html_render_astrbot(html, 720)
        if img:
            img = await self._finalize_report_image(img, "签到卡片")
            logger.info(f"[暮黎资源·签到] 卡片渲染完成（AstrBot T2I，{len(img)//1024}KB）")
        return img

    async def _send_checkin_image(self, event: AstrMessageEvent, img_bytes: bytes) -> bool:
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=_img_ext(img_bytes), prefix="checkin_")
            os.close(fd)
            with open(tmp, "wb") as f:
                f.write(img_bytes)
            await event.send(MessageChain([ImageComponent(file=tmp)]))
            logger.info(f"[暮黎资源·签到] 卡片已发送（{len(img_bytes)//1024}KB）")
            return True
        except Exception as e:
            logger.warning(f"[暮黎资源·签到] 图片发送失败，回退文本: {e}")
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    def _points_rank_text(self, limit: int = 10) -> str:
        s = self._points_settings()
        if not s["enabled"]:
            return "【暮黎资源·积分排行】\n⚠️ 积分系统当前未开启。"
        try:
            rows = self._points_db().top(max(1, int(limit)))
        except Exception as e:
            logger.warning(f"[暮黎资源·积分] 读取排行失败: {e}")
            return "【暮黎资源·积分排行】\n⚠️ 积分数据读取失败，请稍后再试。"
        if not rows:
            return "【暮黎资源·积分排行】\n📭 还没有人获得积分，发送 /签到 抢个第一吧～"
        lines = [f"【暮黎资源·积分排行】（前 {len(rows)} 名）"]
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, (key, user) in enumerate(rows, 1):
            nm = user.get("name") or key.split(":", 1)[-1]
            lines.append(f"{medals.get(i, f'{i}.')} {nm} — {int(user.get('points', 0) or 0)} 积分")
        return "\n".join(lines)


    def _qq_platform_ids(self) -> set:
        """从平台管理器里找出「确实是 QQ / OneBot」的实例 ID。

        积分键里的平台段来自 event.get_platform_id()，而 AstrBot 允许给平台实例
        起任意 ID（如 muli、qq-main），只靠关键字匹配会漏掉 → 头像一直取不到。
        这里直接问平台管理器，用适配器名（aiocqhttp/onebot/napcat…）判定。
        """
        ids: set = set()
        try:
            insts = list(self.context.platform_manager.get_insts())
        except Exception:
            return ids
        for p in insts:
            try:
                meta = p.meta()
                pid = str(getattr(meta, "id", "") or "")
                name = str(getattr(meta, "name", "") or "")
            except Exception:
                continue
            blob = f"{pid} {name}".lower()
            if any(k in blob for k in ("official", "guild")):
                continue
            if any(k in blob for k in ("aiocqhttp", "onebot", "cqhttp",
                                       "qq", "napcat", "lagrange")):
                if pid:
                    ids.add(pid)
        return ids

    def _points_rank_data(self, event: AstrMessageEvent | None = None,
                          limit: int = 10):
        """读取排行榜数据，返回 (data, 错误文本)。"""
        s = self._points_settings()
        if not s["enabled"]:
            return None, "【暮黎资源·积分排行】\n⚠️ 积分系统当前未开启。"
        try:
            all_rows = self._points_db().top(1000)
        except Exception as e:
            logger.warning(f"[暮黎资源·积分] 读取排行失败: {e}")
            return None, "【暮黎资源·积分排行】\n⚠️ 积分数据读取失败，请稍后再试。"
        if not all_rows:
            return None, "【暮黎资源·积分排行】\n📭 还没有人获得积分，发送 /签到 抢个第一吧～"

        me_key = self._points_user(event)[0] if event is not None else ""
        me_rank = me_points = 0
        for i, (k, u) in enumerate(all_rows, 1):
            if k == me_key:
                me_rank = i
                me_points = int(u.get("points", 0) or 0)
                break

        top_rows = all_rows[:max(1, int(limit))]
        keys = [k for k, _ in top_rows]
        if me_key and me_rank > len(top_rows):
            keys.append(me_key)
        try:
            avatars = fetch_point_avatars(keys, qq_platforms=self._qq_platform_ids())
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[暮黎资源·积分] 头像获取失败（改用首字占位）: {e}")
            avatars = {}

        rows = []
        for i, (k, u) in enumerate(top_rows, 1):
            _platform, uid = split_point_key(k)
            rows.append({
                "rank": i,
                "name": u.get("name") or uid or "匿名用户",
                "points": int(u.get("points", 0) or 0),
                "streak": int(u.get("streak", 0) or 0),
                "avatar": avatars.get(k, ""),
                "me": k == me_key,
            })
        return {
            "rows": rows,
            "total": len(all_rows),
            "me_key": me_key,
            "me_rank": me_rank,
            "me_points": me_points,
            "date_label": self._points_day().strftime("%Y-%m-%d"),
        }, ""

    async def _send_points_rank_card(self, event: AstrMessageEvent,
                                     limit: int = 10) -> None:
        """积分排行榜：图片优先，失败回退文本。"""
        data, err = None, ""
        try:
            data, err = await asyncio.to_thread(
                self._points_rank_data, event, limit)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[列表卡片] 排行榜数据准备失败: {e}")
            err = "【暮黎资源·积分排行】\n⚠️ 积分数据读取失败，请稍后再试。"
        if not data:
            await event.send(MessageChain([Plain(err or "积分排行读取失败，请稍后再试。")]))
            return
        cards_on, _ = self._list_card_cfg()
        html = ""
        if cards_on and points_rank_html:
            try:
                html = points_rank_html(**data)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 排行榜卡片构建失败，回退文本: {e}")
        img = None
        if html and render_list_card:
            try:
                img = await asyncio.to_thread(render_list_card, html)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 排行榜渲染异常，回退文本: {e}")
        if img and await self._send_card_image(event, img, "暮黎_积分排行.jpg"):
            return
        await event.send(MessageChain([Plain(self._points_rank_text(limit))]))

    # ==================== 群聊小游戏（猜数字 / 封面猜猜 / 谁是卧底）====================
    # 设计：
    # - 会话按「平台:群号」保存，一个群同时只能开一局；
    # - 只有明确的输入（1/2/3、数字、A-D、0/结束）才拦截，普通聊天继续走 LLM；
    # - 超时/结算用 asyncio.Task，结算后立即清理，避免后台任务堆积；
    # - 积分奖励走 MiniGameStore 的每日额度，再写入 PointsStore；
    # - 谁是卧底额外约束：词和身份只走私聊，群消息与卡片永不含词。

    def _minigame_cfg(self) -> dict:
        c = self._get_config() or {}
        if not isinstance(c, dict):
            c = {}

        def _b(key: str, default: bool) -> bool:
            v = c.get(key, default)
            if isinstance(v, str):
                return v.strip().lower() not in ("", "0", "false", "no", "off")
            return bool(v)

        def _i(key: str, default: int, lo: int, hi: int) -> int:
            try:
                v = int(c.get(key, default))
            except (TypeError, ValueError):
                v = int(default)
            return max(lo, min(hi, v))

        return {
            "enabled": _b("minigame_enabled", True),
            "groups": self._parse_multi(c.get("minigame_group_ids") or []),
            "reward": _i("minigame_points_reward", 5, 0, 1000),
            "daily_cap": _i("minigame_daily_cap", 30, 0, 10000),
            "bomb_wait": _i("minigame_bomb_timeout", 30, 10, 300),
            "bomb_turn": _i("minigame_bomb_turn_timeout", 30, 10, 300),
            "cover_rounds": _i("minigame_cover_rounds", 3, 1, 10),
            "cover_timeout": _i("minigame_cover_timeout", 25, 10, 120),
            "cover_pool_ttl": _i("minigame_cover_pool_ttl", 12, 1, 168),
            "cover_pixel": _i("minigame_cover_pixel", 12, 4, 40),
            "uc_enabled": _b("minigame_uc_enabled", True),
            "uc_join": _i("minigame_uc_join_timeout", 90, 30, 180),
            "uc_min": _i("minigame_uc_min_players", 4, 3, 6),
            "uc_max": _i("minigame_uc_max_players", 6, 4, 12),
            "uc_turn": _i("minigame_uc_turn_timeout", 40, 15, 90),
            "uc_vote": _i("minigame_uc_vote_timeout", 30, 15, 90),
            "uc_desc_max": _i("minigame_uc_desc_max", 20, 6, 50),
            "uc_spies": _i("minigame_uc_spies", 1, 1, 2),
            "uc_private_vote": _b("minigame_uc_private_vote", True),
            "uc_reveal_role": _b("minigame_uc_reveal_role", False),
            "uc_level": (str(c.get("minigame_uc_word_level") or "mixed")
                         .strip().lower()),
        }

    @staticmethod
    def _minigame_group_key(event: AstrMessageEvent) -> str:
        try:
            gid = str(event.get_group_id() or "").strip()
            pid = str(event.get_platform_id() or "").strip()
        except Exception:
            return ""
        return f"{pid}:{gid}" if gid else ""

    def _minigame_has_user_session(self, event: AstrMessageEvent) -> bool:
        """用户正在搜索/选集时，不抢他的数字输入。"""
        for mgr in (self._sessions, self._search_sessions, self._movie_sessions,
                    self._movie_sessions_new, self._novel_sessions,
                    self._drama_sessions):
            try:
                if mgr.get(event):
                    return True
            except Exception:
                continue
        return False

    def _minigame_db(self) -> MiniGameStore:
        if self._minigame_store is None:
            self._minigame_store = MiniGameStore(
                os.path.join(self._plugin_data_dir(), "minigame_stats.json"),
                tz_getter=lambda: self._timezone,
            )
        return self._minigame_store

    def _minigame_cache_dir(self) -> str:
        d = os.path.join(self._plugin_data_dir(), "minigame")
        os.makedirs(d, exist_ok=True)
        return d

    def _minigame_cover_dir(self) -> str:
        d = os.path.join(self._minigame_cache_dir(), "covers")
        os.makedirs(d, exist_ok=True)
        return d

    async def _minigame_cover_pool(self, kind: str = "movie") -> list:
        """按领域取题库：优先用未过期缓存，过期后抓对应 pdy 分类并落盘。"""
        kind = kind if kind in COVER_KINDS else "movie"
        info = COVER_KINDS[kind]
        cfg = self._minigame_cfg()
        try:
            cache = os.path.join(self._minigame_cache_dir(),
                                 f"cover_pool_{kind}.json")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[小游戏] 题库目录不可用: {e}")
            return []
        ttl = cfg["cover_pool_ttl"] * 3600
        pool, ts = read_pool_cache(cache)
        if pool and time.time() - ts < ttl:
            self._minigame_pools[kind] = (pool, ts)
            return pool
        cached = self._minigame_pools.get(kind)
        if cached and time.time() - cached[1] < ttl:
            return cached[0]
        if self._minigame_pool_lock is None:
            self._minigame_pool_lock = asyncio.Lock()
        async with self._minigame_pool_lock:
            pool, ts = read_pool_cache(cache)
            if pool and time.time() - ts < ttl:
                self._minigame_pools[kind] = (pool, ts)
                return pool
            new_pool = []
            try:
                client = self._get_pdy_client()
                new_pool = await asyncio.to_thread(
                    fetch_pool,
                    lambda tid, page: client.latest(tid, 10, page),
                    (info["tid"],), 3, kind)
                if len(new_pool) < 10:
                    more = await asyncio.to_thread(
                        fetch_pool,
                        lambda tid, page: client.latest(tid, 10, page),
                        (info["tid"],), 4, kind)
                    if len(more) > len(new_pool):
                        new_pool = more
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] {info['label']}题库抓取失败: {e}")
            if new_pool:
                save_pool_cache(cache, new_pool)
                self._minigame_pools[kind] = (new_pool, time.time())
                try:
                    cleanup_cover_cache(self._minigame_cover_dir())
                except Exception:
                    pass
                logger.info(f"[小游戏] {info['label']}题库已更新：{len(new_pool)} 条")
                return new_pool
            return pool or (cached[0] if cached else [])

    def _minigame_award(self, key: str, name: str, points: int) -> tuple[int, str]:
        """发游戏积分；返回 (实际发放, 额外提示)。"""
        s = self._points_settings()
        if not s.get("enabled") or int(points or 0) <= 0:
            return 0, ""
        cfg = self._minigame_cfg()
        try:
            awarded, _today = self._minigame_db().award(
                key, name, int(points), cfg["daily_cap"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[小游戏] 奖励额度写入失败: {e}")
            return 0, ""
        if awarded > 0:
            try:
                self._points_db().add(key, awarded, name, s["initial"])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 积分发放失败: {e}")
                return 0, ""
        note = ""
        if cfg["daily_cap"] > 0 and awarded < int(points):
            note = f"（今日游戏奖励已达上限 {cfg['daily_cap']}）"
        return awarded, note

    async def _minigame_send_image_text(self, event: AstrMessageEvent,
                                        img_bytes: bytes, text: str) -> None:
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="mg_")
            os.close(fd)
            with open(tmp, "wb") as f:
                f.write(img_bytes)
            await event.send(MessageChain([ImageComponent(file=tmp), Plain(text)]))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[小游戏] 封面发送失败，回退文本: {e}")
            await event.send(MessageChain([Plain(text)]))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    async def _minigame_send_result(self, event: AstrMessageEvent, *, title: str,
                                    subtitle: str, rows: list, foot_lines: list,
                                    text: str, page_ind: str = "本局结算") -> None:
        html = ""
        if minigame_result_card_html:
            try:
                html = minigame_result_card_html(
                    title=title, subtitle=subtitle, rows=rows,
                    foot_lines=foot_lines, page_ind=page_ind)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 结算卡片构建失败，回退文本: {e}")
        await self._send_list_card(event, html=html, text=text,
                                   total=len(rows), label="游戏结算",
                                   force=True)

    def _minigame_cancel_task(self, game: dict) -> None:
        if not isinstance(game, dict):
            return
        task = game.get("task")
        if task is not None:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if task is not current and not task.done():
                task.cancel()
        game["task"] = None

    def _minigame_schedule(self, gkey: str, game: dict,
                           seconds: int, kind: str, token=None) -> None:
        self._minigame_cancel_task(game)
        task = asyncio.create_task(self._minigame_timeout_job(
            gkey, game.get("id"), kind, max(1, int(seconds)), token))
        game["task"] = task
        try:
            self._bg_tasks.append(task)
            self._bg_tasks = [t for t in self._bg_tasks if not t.done()][-30:]
        except Exception:
            pass

    async def _minigame_timeout_job(self, gkey: str, gid, kind: str,
                                    seconds: int, token=None) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        game = self._minigame_sessions.get(gkey)
        if not game or game.get("id") != gid:
            return
        try:
            if kind == "lobby":
                self._minigame_sessions.pop(gkey, None)
                ev = game.get("event")
                if ev:
                    await ev.send(MessageChain([Plain(
                        "⌛ 游戏大厅超时，已关闭。发送 /小游戏 重新打开。")]))
            elif kind == "bomb_wait":
                ev = game.get("event")
                if not ev:
                    self._minigame_sessions.pop(gkey, None)
                else:
                    await self._minigame_bomb_begin(ev, gkey, game, auto=True)
            elif kind == "bomb_turn":
                await self._minigame_bomb_turn_timeout(gkey, game, token)
            elif kind == "cover_pick":
                self._minigame_sessions.pop(gkey, None)
                ev = game.get("event")
                if ev:
                    await ev.send(MessageChain([Plain(
                        "⌛ 选择题库超时，已关闭。发送 /小游戏 重新打开。")]))
            elif kind == "cover":
                await self._minigame_cover_timeout(gkey, game)
            elif kind == "uc_join":
                await self._uc_join_timeout(gkey, game)
            elif kind == "uc_turn":
                await self._uc_turn_timeout(gkey, game, token)
            elif kind == "uc_vote":
                await self._uc_vote_timeout(gkey, game, token)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[小游戏] 超时结算失败 kind={kind}: {e}")

    async def _minigame_open_lobby(self, event: AstrMessageEvent,
                                   start: str = "") -> None:
        cfg = self._minigame_cfg()
        if not cfg["enabled"]:
            await event.send(MessageChain([Plain("【暮黎资源】小游戏未启用，请联系管理员开启。")]))
            return
        gkey = self._minigame_group_key(event)
        if not gkey:
            await event.send(MessageChain([Plain("【暮黎资源】小游戏只能在群聊里玩。")]))
            return
        gid = str(event.get_group_id() or "")
        if cfg["groups"] and gid not in cfg["groups"]:
            await event.send(MessageChain([Plain("【暮黎资源】本群暂未开放小游戏。")]))
            return
        if self._minigame_has_user_session(event):
            await event.send(MessageChain([Plain(
                "【暮黎资源】你还有未完成的搜索/选集，先回复 0 取消后再开游戏。")]))
            return
        old = self._minigame_sessions.get(gkey)
        if old:
            if start == "guess" and old.get("stage") == "bomb_wait":
                await self._minigame_bomb_join(event, gkey, old)
                return
            if start == "guess" and old.get("stage") == "bomb":
                await event.send(MessageChain([Plain(
                    "【暮黎资源】本局猜数字已经开始了，等下一局吧。")]))
                return
            await event.send(MessageChain([Plain(
                "【暮黎资源】本群已有进行中的小游戏。\n"
                "发送 /结束游戏 可以提前结束。")]))
            return
        key, uid, name = self._points_user(event)
        game = {
            "id": time.time_ns(),
            "stage": "lobby",
            "host_key": key,
            "host_name": name or uid,
            "event": event,
            "players": {},
            "task": None,
            "updated": time.time(),
        }
        self._minigame_sessions[gkey] = game
        if start == "guess":
            await self._minigame_start_bomb(event, gkey, game)
            return
        if start == "cover":
            game.update({
                "stage": "cover_pick",
                "cover_owner_key": key,
                "cover_owner_name": name or uid or "玩家",
            })
            await self._minigame_send_cover_pick(event, game)
            self._minigame_schedule(gkey, game, 90, "cover_pick")
            return
        if start == "undercover":
            if not cfg["uc_enabled"]:
                self._minigame_sessions.pop(gkey, None)
                await event.send(MessageChain([Plain(
                    "【暮黎资源】谁是卧底未启用，请联系管理员在配置里开启。")]))
                return
            await self._uc_start(event, gkey, game)
            return
        s = self._points_settings()
        if s.get("enabled") and cfg["reward"] > 0:
            cap = (f"每人每日上限 {cfg['daily_cap']} 积分"
                   if cfg["daily_cap"] > 0 else "不限每日额度")
            reward_txt = f"答对 / 获胜 +{cfg['reward']} 积分（{cap}）"
        elif s.get("enabled"):
            reward_txt = "本局不计积分"
        else:
            reward_txt = "积分未开启，本局只计胜负"
        uc_on = bool(cfg["uc_enabled"])
        text = (
            "🎮 暮黎游戏厅\n"
            "============================\n\n"
            "1. 猜数字\n"
            "   1-100 猜一个数字，每次提示大了/小了，猜中直接获胜\n"
            "2. 封面猜猜\n"
            "   选电影 / 电视剧 / 动漫，看马赛克封面四选一\n"
            + ("3. 谁是卧底\n"
               "   私聊发词，轮流描述，投票找出拿到不同词的人\n" if uc_on else "")
            + f"\n💰 {reward_txt}\n"
            + ("⚠️ 谁是卧底需要机器人能私聊群成员，请管理员确认已开启私聊权限。\n"
               if uc_on else "")
            + f"💬 回复 1 / 2{' / 3' if uc_on else ''} 开始，回复 0 关闭。\n"
            "⏱️ 90 秒内未选择自动关闭。"
        )
        html = ""
        if minigame_lobby_html:
            try:
                html = minigame_lobby_html(reward_text=reward_txt, timeout=90,
                                           undercover=uc_on)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 大厅卡片构建失败，回退文本: {e}")
        await self._send_list_card(event, html=html, text=text, total=1,
                                   label="游戏大厅", force=True)
        self._minigame_schedule(gkey, game, 90, "lobby")

    async def _minigame_end(self, event: AstrMessageEvent, gkey: str, game: dict,
                            reason: str = "") -> None:
        stage = game.get("stage")
        if stage == "lobby":
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain("🎮 游戏大厅已关闭。")]))
            return
        if stage == "bomb_wait":
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain("💣 组队已取消。")]))
            return
        if stage == "cover_pick":
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain("🎬 已关闭封面猜猜。")]))
            return
        if stage == "bomb":
            await self._minigame_bomb_finish(event, gkey, game, reason=reason or "手动结束")
            return
        if stage == "cover":
            q = game.get("question") or {}
            if q and not game.get("answered"):
                game["answered"] = True
                title = (q.get("correct") or {}).get("title") or "?"
                await event.send(MessageChain([Plain(
                    f"🛑 封面猜猜已结束，本题答案：《{title}》。")]))
            await self._minigame_cover_finish(event, gkey, game, early=True)
            return
        if str(stage or "").startswith("uc_"):
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            self._uc_cleanup_pending(game)
            await event.send(MessageChain([Plain(
                "🕵️ 谁是卧底已结束，本局不计分。\n发送 /小游戏 3 重开一局。")]))
            return
        self._minigame_cancel_task(game)
        self._minigame_sessions.pop(gkey, None)

    BOMB_MAX_TURNS = 30
    BOMB_MAX_PLAYERS = 6

    def _minigame_at(self, uid: str, name: str = ""):
        """构造 @ 组件；旧版 AstrBot / 构造参数不兼容时退回纯文本 @。"""
        if At is not None:
            try:
                return At(qq=str(uid))
            except Exception:
                pass
        return Plain(f"@{name or uid}")

    async def _minigame_send_at(self, event: AstrMessageEvent, chain: list,
                                fallback: str) -> None:
        """发带 @ 的消息；平台不支持 At 组件时回退纯文本。"""
        try:
            await event.send(MessageChain(chain))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[小游戏] @消息发送失败，回退纯文本: {e}")
            await event.send(MessageChain([Plain(fallback)]))

    def _minigame_next_bomb_turn(self, game: dict) -> str:
        order = game.get("order") or []
        if not order:
            return ""
        idx = (int(game.get("turn_index", 0)) + 1) % len(order)
        game["turn_index"] = idx
        game["turn_key"] = order[idx]
        return order[idx]

    async def _minigame_send_bomb_wait(self, event: AstrMessageEvent, game: dict,
                                       seconds: int = 30) -> None:
        players = game.get("players") or {}
        order = game.get("order") or []
        rows = [{"name": (players.get(k) or {}).get("name") or "玩家",
                 "host": bool((players.get(k) or {}).get("host"))} for k in order]
        html = ""
        if minigame_bomb_wait_html:
            try:
                html = minigame_bomb_wait_html(
                    host_name=game.get("host_name") or "房主",
                    players=rows, seconds=seconds, max_players=6,
                    timeout=seconds)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 组队卡片构建失败，回退文本: {e}")
        names = "、".join(p.get("name") or "玩家" for p in rows)
        text = (f"🔢 猜数字 · 组队中\n"
                f"============================\n\n"
                f"房主：{game.get('host_name') or '房主'}\n"
                f"已加入：{names or '暂无'}\n\n"
                f"群友回复 1 加入；房主回复 2 立即开始。\n"
                f"无人加入将进入单人猜数字（猜中即获胜）。\n"
                f"回复 0 取消。\n"
                f"⏱️ {seconds} 秒后自动开始（最多 6 人）。")
        await self._send_list_card(event, html=html, text=text, total=1,
                                   label="猜数字组队", force=True)

    async def _minigame_start_bomb(self, event: AstrMessageEvent, gkey: str,
                                   game: dict) -> None:
        """进入组队等待：30 秒内回复 1 加入，房主回复 2 立即开始。"""
        if self._minigame_sessions.get(gkey) is not game:
            return
        cfg = self._minigame_cfg()
        self._minigame_cancel_task(game)
        key, uid, name = self._points_user(event)
        name = name or uid or "房主"
        host = {"name": name, "uid": str(uid or ""), "host": True}
        wait = max(10, int(cfg["bomb_wait"]))
        game.update({
            "stage": "bomb_wait",
            "host_key": key,
            "host_name": name,
            "players": {key: host},
            "order": [key],
            "wait_deadline": time.time() + wait,
            "event": event,
            "updated": time.time(),
        })
        await self._minigame_send_bomb_wait(event, game, wait)
        self._minigame_schedule(gkey, game, wait, "bomb_wait")

    async def _minigame_bomb_join(self, event: AstrMessageEvent, gkey: str,
                                  game: dict) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        key, uid, name = self._points_user(event)
        name = name or uid or "玩家"
        players = game.setdefault("players", {})
        if key in players:
            await event.send(MessageChain([Plain("🙋 你已经在队伍里了，等房主开始吧。")]))
            return
        if len(players) >= self.BOMB_MAX_PLAYERS:
            await event.send(MessageChain([Plain(
                f"😅 人数已满（{self.BOMB_MAX_PLAYERS} 人），本局不能再加入了。")]))
            return
        players[key] = {"name": name, "uid": str(uid or ""), "host": False}
        game.setdefault("order", []).append(key)
        game["updated"] = time.time()
        remaining = max(1, int(float(game.get("wait_deadline") or 0) - time.time()))
        await self._minigame_send_bomb_wait(event, game, remaining)

    async def _minigame_bomb_begin(self, event: AstrMessageEvent, gkey: str,
                                   game: dict, auto: bool = False) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") != "bomb_wait":
            return
        cfg = self._minigame_cfg()
        self._minigame_cancel_task(game)
        players = game.get("players") or {}
        order = [k for k in (game.get("order") or []) if k in players]
        if not order:
            key, uid, name = self._points_user(event)
            players[key] = {"name": name or uid or "玩家", "uid": str(uid or ""),
                            "host": True}
            game["players"] = players
            order = [key]
            game["order"] = order
        turn_timeout = max(10, int(cfg["bomb_turn"]))
        solo = len(order) == 1
        range_high = 100 * max(1, len(order))
        token = time.time_ns()
        game.update({
            "stage": "bomb",
            "bomb": BombGame(1, range_high),
            "range_high": range_high,
            "solo": solo,
            "turn_index": 0,
            "turn_key": order[0],
            "turn_token": token,
            "turn_count": 0,
            "event": event,
            "updated": time.time(),
        })
        cur = players.get(order[0]) or {}
        cur_name = cur.get("name") or "玩家"
        if solo:
            head = ("⏰ 组队时间到，无人加入，进入单人猜数字！\n" if auto
                    else "🧍 单人猜数字\n")
            chain = [Plain(
                head
                + f"目标：猜中 1-{range_high} 的隐藏数字，猜中即获胜。\n"
                + f"范围：1-{range_high}\n👉 轮到 ")]
            chain.append(self._minigame_at(cur.get("uid") or "", cur_name))
            chain.append(Plain(f" 了，请猜一个数字（{turn_timeout} 秒内）。"))
            fallback = (f"{head}"
                        f"目标：猜中 1-{range_high} 的隐藏数字，猜中即获胜。\n"
                        f"范围：1-{range_high}\n👉 轮到 {cur_name} 了，请猜一个数字（{turn_timeout} 秒内）。")
        else:
            prefix = "⏰ 组队时间到，自动开始！" if auto else "🔢 猜数字开始！"
            chain = [Plain(prefix + "\n顺序：")]
            for i, k in enumerate(order, 1):
                p = players.get(k) or {}
                chain.append(Plain(f"\u200b\n{i}. "))
                chain.append(self._minigame_at(p.get("uid") or "",
                                               p.get("name") or ""))
            chain.append(Plain(
                f"\u200b\n\n本局范围 1-{range_high}（{len(order)} 人自适应），"
                "每次提示大了/小了，猜中直接获胜。\n"
                f"范围：1-{range_high}\n👉 轮到 "))
            chain.append(self._minigame_at(cur.get("uid") or "", cur_name))
            chain.append(Plain(f" 了，请猜一个数字（{turn_timeout} 秒内）。"))
            order_txt = "\n".join(
                f"{i}. {((players.get(k) or {}).get('name') or '玩家')}"
                for i, k in enumerate(order, 1))
            fallback = (f"{prefix}\n顺序：\n{order_txt}\n"
                        f"本局范围 1-{range_high}（{len(order)} 人自适应），"
                        "每次提示大了/小了，猜中直接获胜。\n"
                        f"范围：1-{range_high}\n👉 轮到 {cur_name} 了，"
                        f"请猜一个数字（{turn_timeout} 秒内）。")
        await self._minigame_send_at(event, chain, fallback)
        self._minigame_schedule(gkey, game, turn_timeout, "bomb_turn", token)

    async def _minigame_bomb_guess(self, event: AstrMessageEvent, gkey: str,
                                   game: dict, text: str) -> None:
        key, uid, name = self._points_user(event)
        name = name or uid or "玩家"
        game["event"] = event
        game["updated"] = time.time()
        try:
            number = int(text)
        except (TypeError, ValueError):
            return
        players = game.setdefault("players", {})
        if key != game.get("turn_key"):
            cur = players.get(game.get("turn_key") or "") or {}
            chain = [Plain("🙋 还没轮到你，当前轮到 "),
                     self._minigame_at(cur.get("uid") or "", cur.get("name") or ""),
                     Plain("。")]
            await self._minigame_send_at(
                event, chain,
                f"🙋 还没轮到你，当前轮到 {cur.get('name') or '玩家'}。")
            return
        num_game: BombGame = game["bomb"]
        result = num_game.guess(number)
        if result["type"] == "out":
            await event.send(MessageChain([Plain(
                f"范围是 {num_game.low}-{num_game.high}，请猜这个区间里的数字。")]))
            return
        player = players.setdefault(key, {"name": name, "uid": str(uid or ""),
                                          "guesses": 0})
        player["name"] = name
        player["uid"] = str(uid or player.get("uid") or "")
        player["guesses"] = int(player.get("guesses", 0) or 0) + 1
        if result["type"] == "hit":
            await self._minigame_bomb_finish(
                event, gkey, game, winner_key=key, winner_name=name)
            return
        # low / high：提示太大/太小，换下一位
        game["turn_count"] = int(game.get("turn_count", 0) or 0) + 1
        if game["turn_count"] >= self.BOMB_MAX_TURNS:
            await self._minigame_bomb_finish(event, gkey, game,
                                             reason="回合数用尽")
            return
        next_key = self._minigame_next_bomb_turn(game)
        next_p = players.get(next_key) or {}
        token = time.time_ns()
        game["turn_token"] = token
        cfg = self._minigame_cfg()
        turn_timeout = max(10, int(cfg["bomb_turn"]))
        hint = "📉 太小了！" if result["type"] == "low" else "📈 太大了！"
        chain = [Plain(f"{hint} {name} 猜 {number}。\n"
                       f"范围收窄到 {num_game.low}-{num_game.high}。\n👉 轮到 "),
                 self._minigame_at(next_p.get("uid") or "", next_p.get("name") or ""),
                 Plain(f" 了（{turn_timeout} 秒内）。")]
        await self._minigame_send_at(
            event, chain,
            f"{hint} {name} 猜 {number}。\n"
            f"范围收窄到 {num_game.low}-{num_game.high}。\n"
            f"👉 轮到 {next_p.get('name') or '玩家'} 了（{turn_timeout} 秒内）。")
        self._minigame_schedule(gkey, game, turn_timeout, "bomb_turn", token)

    async def _minigame_bomb_turn_timeout(self, gkey: str, game: dict,
                                          token=None) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") != "bomb":
            return
        if token is not None and token != game.get("turn_token"):
            return
        ev = game.get("event")
        if not ev:
            self._minigame_sessions.pop(gkey, None)
            return
        if game.get("solo"):
            await self._minigame_bomb_finish(ev, gkey, game, reason="超时")
            return
        players = game.get("players") or {}
        cur_key = game.get("turn_key") or ""
        cur = players.get(cur_key) or {}
        game["turn_count"] = int(game.get("turn_count", 0) or 0) + 1
        if game["turn_count"] >= self.BOMB_MAX_TURNS:
            await self._minigame_bomb_finish(ev, gkey, game, reason="回合数用尽")
            return
        next_key = self._minigame_next_bomb_turn(game)
        next_p = players.get(next_key) or {}
        token = time.time_ns()
        game["turn_token"] = token
        cfg = self._minigame_cfg()
        turn_timeout = max(10, int(cfg["bomb_turn"]))
        chain = [Plain("⏭️ "), self._minigame_at(cur.get("uid") or "", cur.get("name") or ""),
                 Plain(" 超时，跳过。\n👉 轮到 "),
                 self._minigame_at(next_p.get("uid") or "", next_p.get("name") or ""),
                 Plain(f" 了（{turn_timeout} 秒内）。")]
        await self._minigame_send_at(
            ev, chain,
            f"⏭️ {cur.get('name') or '玩家'} 超时，跳过。\n"
            f"👉 轮到 {next_p.get('name') or '玩家'} 了（{turn_timeout} 秒内）。")
        self._minigame_schedule(gkey, game, turn_timeout, "bomb_turn", token)

    async def _minigame_bomb_finish(self, event: AstrMessageEvent, gkey: str,
                                    game: dict, winner_key: str = "",
                                    winner_name: str = "", reason: str = "") -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        self._minigame_cancel_task(game)
        self._minigame_sessions.pop(gkey, None)
        num_game: BombGame = game["bomb"]
        players = game.get("players") or {}
        solo = bool(game.get("solo"))
        cfg = self._minigame_cfg()
        awarded, note = (0, "")
        if winner_key:
            awarded, note = self._minigame_award(
                winner_key, winner_name or "玩家", cfg["reward"])
        for k, p in players.items():
            try:
                self._minigame_db().record(
                    k, p.get("name") or "", win=(k == winner_key))
            except Exception:
                pass

        rows = []
        if winner_key:
            if awarded > 0:
                chip = f'<span class="chip chip-win">+{awarded} 积分</span>'
            elif note:
                chip = '<span class="chip chip-gold">奖励上限</span>'
            else:
                chip = '<span class="chip chip-win">+0 积分</span>'
            rows.append({
                "n": 1, "title": winner_name or "玩家",
                "right": chip, "meta": "猜中数字 · 获胜",
            })
        for k, p in players.items():
            if k == winner_key:
                continue
            guesses = int(p.get("guesses", 0) or 0)
            rows.append({
                "n": len(rows) + 1, "title": p.get("name") or k,
                "right": ('<span class="chip">未猜中</span>' if guesses else ""),
                "meta": (f"猜了 {guesses} 次" if guesses else "未出手"),
            })
        if not rows:
            rows = [{"n": "-", "title": "本局无人参与", "meta": ""}]

        range_high = int(game.get("range_high", 100) or 100)
        subtitle = (f"单人猜数字 · 目标 1-{range_high}" if solo
                    else f"{len(players)} 人 · 目标 1-{range_high}")
        if reason:
            subtitle += f" · {reason}"
        foot = ['<div><span class="k">再来</span>发送 <b>/小游戏</b> 开新局</div>']
        if cfg["daily_cap"] > 0:
            foot.append(f'<div class="dim"><span class="k">奖励</span>'
                        f'每日游戏奖励上限 {cfg["daily_cap"]} 积分</div>')
        lines = [("🧍 猜数字 · 单人结算" if solo else "🔢 猜数字 · 结算")]
        if reason:
            lines.append(f"状态：{reason}")
        if winner_key:
            if awarded > 0:
                lines.append(f"🏆 猜中：{winner_name} +{awarded} 积分"
                             f"（数字 {num_game.value}）{note}")
            else:
                lines.append(f"🏆 猜中：{winner_name}{note or '（无积分奖励）'}"
                             f"（数字 {num_game.value}）")
        else:
            lines.append(f"本局无人猜中，数字是 {num_game.value}。")
        lines.append("发送 /小游戏 再来一局。")
        await self._minigame_send_result(
            event, title=("猜数字 · 单人" if solo else "猜数字"),
            subtitle=subtitle, rows=rows,
            foot_lines=foot, text="\n".join(lines))

    async def _minigame_start_cover(self, event: AstrMessageEvent, gkey: str,
                                    game: dict, kind: str = "movie") -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        kind = kind if kind in COVER_KINDS else "movie"
        info = COVER_KINDS[kind]
        cfg = self._minigame_cfg()
        self._minigame_cancel_task(game)
        if not pillow_available():
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain(
                "😕 封面猜猜需要 Pillow，当前环境未安装。\n"
                "请管理员执行：pip install pillow")]))
            return
        await event.send(MessageChain([Plain(
            f"🎬 正在准备{info['label']}题库，首次约 5-10 秒...")]))
        pool = await self._minigame_cover_pool(kind)
        cur = self._minigame_sessions.get(gkey)
        if not cur or cur.get("id") != game.get("id"):
            return
        if len(pool) < 4:
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain(
                f"😕 {info['label']}题库暂时不可用，换一类或先玩猜数字吧。")]))
            return
        owner_key = game.get("cover_owner_key") or ""
        owner_name = game.get("cover_owner_name") or "玩家"
        players = ({owner_key: {"name": owner_name, "correct": 0, "awarded": 0}}
                   if owner_key else {})
        game.update({
            "stage": "cover",
            "kind": kind,
            "kind_label": info["label"],
            "round": 0,
            "total_rounds": cfg["cover_rounds"],
            "pool": pool,
            "used": set(),
            "players": players,
            "question": None,
            "answered": True,
            "wrong": set(),
            "cover_started_at": time.time(),
            "event": event,
            "updated": time.time(),
        })
        await self._minigame_cover_next_round(event, gkey, game)

    async def _minigame_send_cover_question(self, event: AstrMessageEvent,
                                            game: dict, question: dict,
                                            img: bytes, timeout: int) -> None:
        """整页题目卡（马赛克封面 + 四选一）；渲染失败回退封面图 + 文本。"""
        b64 = base64.b64encode(img).decode("ascii")
        html = ""
        if minigame_cover_question_html:
            try:
                html = minigame_cover_question_html(
                    question=question, cover_b64=b64,
                    round_no=int(game.get("round", 1) or 1),
                    total=int(game.get("total_rounds", 1) or 1),
                    timeout=int(timeout),
                    kind_label=game.get("kind_label") or "")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 题目卡片构建失败，回退图片+文本: {e}")
        card = None
        cards_on, _ = self._list_card_cfg()
        if cards_on and html and render_list_card:
            try:
                card = await asyncio.to_thread(render_list_card, html)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 题目卡片渲染失败，回退图片+文本: {e}")
        if card and await self._send_card_image(event, card, "暮黎_封面猜猜.jpg"):
            return
        opts = "\n".join(f"{'ABCD'[i]}. {o.get('title')}"
                         for i, o in enumerate(question.get("options") or []))
        text = (
            f"🎬 封面猜猜 · 单人 第 {game.get('round')}/{game.get('total_rounds')} 题\n"
            f"{game.get('kind_label') or ''}\n"
            "============================\n\n"
            f"{opts}\n\n"
            f"💡 提示：{question.get('hint') or '影视'}\n"
            f"⏱️ {timeout} 秒内回复 A/B/C/D（仅发起者可作答）"
        )
        await self._minigame_send_image_text(event, img, text)

    async def _minigame_cover_next_round(self, event: AstrMessageEvent, gkey: str,
                                         game: dict) -> None:
        cur = self._minigame_sessions.get(gkey)
        if not cur or cur.get("id") != game.get("id") or cur.get("stage") != "cover":
            return
        game = cur
        if int(game.get("round", 0)) >= int(game.get("total_rounds", 1)):
            await self._minigame_cover_finish(event, gkey, game)
            return
        cfg = self._minigame_cfg()
        game["round"] = int(game.get("round", 0)) + 1
        question, img = None, None
        for _ in range(4):
            question = pick_question(game["pool"], game["used"])
            if not question:
                break
            correct = question["correct"]
            cid = correct.get("id") or re.sub(
                r"[^\w\u4e00-\u9fff]", "", correct.get("title") or "")[:60]
            cache_path = os.path.join(self._minigame_cover_dir(), f"{cid}.jpg")
            img = await asyncio.to_thread(
                fetch_cover_bytes, correct.get("cover") or "",
                cache_path, cfg["cover_pixel"])
            if img:
                break
        cur = self._minigame_sessions.get(gkey)
        if not cur or cur.get("id") != game.get("id") or cur.get("stage") != "cover":
            return
        if not question or not img:
            await event.send(MessageChain([Plain("😕 封面加载失败，本局提前结束。")]))
            await self._minigame_cover_finish(event, gkey, game, early=True)
            return
        game.update({
            "question": question,
            "answered": False,
            "wrong": set(),
            "round_start": time.time(),
            "event": event,
            "updated": time.time(),
        })
        await self._minigame_send_cover_question(
            event, game, question, img, cfg["cover_timeout"])
        self._minigame_schedule(gkey, game, cfg["cover_timeout"], "cover")

    async def _minigame_cover_answer(self, event: AstrMessageEvent, gkey: str,
                                     game: dict, text: str) -> None:
        choice = normalize_choice(text)
        if not choice:
            return
        cfg = self._minigame_cfg()
        key, uid, name = self._points_user(event)
        name = name or uid or "玩家"
        owner_key = game.get("cover_owner_key") or ""
        if owner_key and key != owner_key:
            owner_name = game.get("cover_owner_name") or "发起者"
            await event.send(MessageChain([Plain(
                f"🙋 封面猜猜是单人游戏，只有发起者 {owner_name} 可以作答。")]))
            return
        game["event"] = event
        game["updated"] = time.time()
        players = game.setdefault("players", {})
        player = players.setdefault(key, {"name": name, "correct": 0, "awarded": 0})
        player["name"] = name
        if game.get("answered"):
            return
        question = game.get("question") or {}
        correct_title = (question.get("correct") or {}).get("title") or "?"
        if choice != question.get("answer"):
            game["answered"] = True
            self._minigame_cancel_task(game)
            await event.send(MessageChain([Plain(
                f"❌ {name} 选 {choice}，不对。正确答案是《{correct_title}》，下一题~")]))
            await asyncio.sleep(1.0)
            await self._minigame_cover_next_round(event, gkey, game)
            return
        game["answered"] = True
        self._minigame_cancel_task(game)
        player["correct"] = int(player.get("correct", 0) or 0) + 1
        awarded, note = self._minigame_award(key, name, cfg["reward"])
        player["awarded"] = int(player.get("awarded", 0) or 0) + awarded
        msg = f"✅ {name} 答对了！答案是《{correct_title}》"
        if awarded > 0:
            msg += f"，+{awarded} 积分"
        if note:
            msg += note
        await event.send(MessageChain([Plain(msg)]))
        await asyncio.sleep(1.0)
        await self._minigame_cover_next_round(event, gkey, game)

    async def _minigame_cover_timeout(self, gkey: str, game: dict) -> None:
        if game.get("answered"):
            return
        game["answered"] = True
        question = game.get("question") or {}
        title = (question.get("correct") or {}).get("title") or "?"
        ev = game.get("event")
        if not ev:
            self._minigame_sessions.pop(gkey, None)
            return
        last = int(game.get("round", 0)) >= int(game.get("total_rounds", 1))
        await ev.send(MessageChain([Plain(
            f"⏰ 时间到！正确答案是《{title}》"
            + ("，本局结束。" if last else "，下一题~"))]))
        await asyncio.sleep(1.0)
        await self._minigame_cover_next_round(ev, gkey, game)

    async def _minigame_cover_finish(self, event: AstrMessageEvent, gkey: str,
                                     game: dict, early: bool = False) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        self._minigame_cancel_task(game)
        self._minigame_sessions.pop(gkey, None)
        players = game.get("players") or {}
        total_rounds = int(game.get("total_rounds", 0) or 0)
        owner_key = game.get("cover_owner_key") or ""
        owner_name = game.get("cover_owner_name") or "玩家"
        owner = players.get(owner_key) or {}
        correct = int(owner.get("correct", 0) or 0)
        awarded = int(owner.get("awarded", 0) or 0)
        started = float(game.get("cover_started_at") or time.time())
        elapsed = max(1, int(time.time() - started))
        if owner_key and correct > 0:
            try:
                self._minigame_db().record(owner_key, owner_name, win=True)
            except Exception:
                pass
        entry = None
        if owner_key and not early:
            try:
                entry = self._minigame_db().cover_record(
                    owner_key, owner_name, correct, total_rounds,
                    elapsed, awarded)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 封面成绩写入失败: {e}")
        board = []
        try:
            board = self._minigame_db().cover_top(10)
            count = self._minigame_db().cover_count()
        except Exception:
            count = 0
        rows = []
        seen = set()
        for rank, k, v in board:
            seen.add(k)
            c = int(v.get("correct", 0) or 0)
            total = int(v.get("total", total_rounds) or total_rounds)
            sec = int(v.get("seconds", 0) or 0)
            pts = int(v.get("awarded", 0) or 0)
            title = v.get("name") or k
            meta = f"用时 {sec} 秒" + (f" · +{pts} 积分" if pts > 0 else "")
            rows.append({"n": rank, "title": title, "me": k == owner_key,
                         "right": f'<span class="chip chip-win">答对 {c}/{total}</span>',
                         "meta": meta})
        if entry and owner_key not in seen:
            rank = 0
            try:
                rank = self._minigame_db().cover_rank(owner_key)
            except Exception:
                pass
            if rank:
                c = int(entry.get("correct", 0) or 0)
                total = int(entry.get("total", total_rounds) or total_rounds)
                sec = int(entry.get("seconds", 0) or 0)
                pts = int(entry.get("awarded", 0) or 0)
                meta = f"用时 {sec} 秒" + (f" · +{pts} 积分" if pts > 0 else "")
                rows.append({"n": rank, "title": owner_name, "me": True,
                             "right": f'<span class="chip chip-win">答对 {c}/{total}</span>',
                             "meta": meta})
        if not rows:
            rows = [{"n": "-", "title": "今日还没有封面成绩", "meta": ""}]
        kind_label = game.get("kind_label") or ""
        subtitle = (f"{kind_label} · 今日榜 · {count} 人"
                    if kind_label else f"今日榜 · {count} 人")
        subtitle += " · 先比答对题数，再比用时"
        if early:
            subtitle += " · 本局提前结束未计入"
        cfg = self._minigame_cfg()
        foot = ['<div><span class="k">再来</span>发送 <b>/小游戏 2</b> 开新局</div>']
        if cfg["daily_cap"] > 0:
            foot.append(f'<div class="dim"><span class="k">奖励</span>'
                        f'每日游戏奖励上限 {cfg["daily_cap"]} 积分</div>')
        lines = ["🎬 封面猜猜 · 今日排行榜"]
        if early:
            lines.append("本局提前结束，未计入今日榜。")
        lines.append(
            f"本局成绩：答对 {correct}/{total_rounds} 题，用时 {elapsed} 秒"
            + (f"，+{awarded} 积分" if awarded > 0 else ""))
        for rank, k, v in board:
            c = int(v.get("correct", 0) or 0)
            total = int(v.get("total", total_rounds) or total_rounds)
            sec = int(v.get("seconds", 0) or 0)
            lines.append(f"#{rank} {v.get('name') or k} · 答对 {c}/{total} · {sec} 秒")
        lines.append("发送 /小游戏 2 再来一局。")
        await self._minigame_send_result(
            event, title="封面猜猜 · 今日排行榜", subtitle=subtitle,
            rows=rows, foot_lines=foot, text="\n".join(lines),
            page_ind="今日榜")

    async def _minigame_send_cover_pick(self, event: AstrMessageEvent,
                                        game: dict) -> None:
        html = ""
        if minigame_cover_pick_html:
            try:
                html = minigame_cover_pick_html(
                    timeout=90,
                    owner_name=game.get("cover_owner_name") or "")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[小游戏] 选题卡片构建失败，回退文本: {e}")
        owner = game.get("cover_owner_name") or ""
        text = ("🎬 封面猜猜 · 单选题库\n"
                "============================\n\n"
                + (f"发起者：{owner}\n仅发起者可作答。\n\n" if owner else "单人游戏。\n\n")
                + "1. 电影\n2. 电视剧\n3. 动漫\n\n"
                "💬 回复 1 / 2 / 3 选择；回复 0 关闭。\n"
                "⏱️ 90 秒内未选择自动关闭。")
        await self._send_list_card(event, html=html, text=text, total=1,
                                   label="封面猜猜选题", force=True)

    # ==================== 谁是卧底 ====================
    # 信息可见性红线：任何群消息/卡片都不能出现「词」和「身份」，结算时才揭晓。
    # 发词、投票走私聊；私聊失败时把失败提示和降级方式讲清楚。

    UC_MAX_ROUNDS = 10

    def _uc_word_pairs(self) -> list:
        if self._uc_pairs is None:
            extra = os.path.join(self._plugin_data_dir(), "undercover_words.json")
            self._uc_pairs = load_pairs(extra)
        return self._uc_pairs

    def _uc_remember_pair(self, uc) -> None:
        try:
            self._uc_recent.append(pair_key(uc.pair))
            self._uc_recent = self._uc_recent[-20:]
        except Exception:
            pass

    async def _uc_dm(self, event: AstrMessageEvent, uid: str, text: str) -> bool:
        """私聊发送单条文本；失败返回 False（由调用方决定降级）。"""
        uid = str(uid or "").strip()
        if not uid:
            return False
        pid = str(event.get_platform_id() or "")
        try:
            await self.context.send_message(
                f"{pid}:FriendMessage:{uid}",
                MessageChain([Plain(text)]))
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[卧底] 私聊发送失败 uid={uid}: {e}")
            return False

    def _uc_cleanup_pending(self, game: dict) -> None:
        gid = (game or {}).get("id")
        for k, v in list(self._uc_vote_pending.items()):
            if (v or {}).get("gid") == gid:
                self._uc_vote_pending.pop(k, None)

    def _uc_join_rows(self, game: dict) -> list:
        players = game.get("players") or {}
        order = [k for k in (game.get("order") or []) if k in players]
        return [{"n": i, "name": (players.get(k) or {}).get("name") or "玩家",
                 "host": bool((players.get(k) or {}).get("host"))}
                for i, k in enumerate(order, 1)]

    async def _uc_start(self, event: AstrMessageEvent, gkey: str, game: dict) -> None:
        """进入报名阶段（房主自动加入）。"""
        cfg = self._minigame_cfg()
        if not cfg["uc_enabled"]:
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain(
                "【暮黎资源】谁是卧底未启用，请联系管理员在配置里开启。")]))
            return
        if self._minigame_sessions.get(gkey) is not game:
            return
        self._minigame_cancel_task(game)
        key, uid, name = self._points_user(event)
        name = name or uid or "房主"
        wait = max(30, int(cfg["uc_join"]))
        game.update({
            "stage": "uc_join",
            "host_key": key,
            "host_name": name,
            "players": {key: {"name": name, "uid": str(uid or ""), "host": True}},
            "order": [key],
            "uc_deadline": time.time() + wait,
            "event": event,
            "updated": time.time(),
        })
        await self._uc_send_join(event, game, wait)
        self._minigame_schedule(gkey, game, wait, "uc_join")

    async def _uc_send_join(self, event: AstrMessageEvent, game: dict,
                            seconds: int) -> None:
        cfg = self._minigame_cfg()
        rows = self._uc_join_rows(game)
        names = "、".join(r["name"] for r in rows) or "暂无"
        timeout = max(30, int(cfg["uc_join"]))
        html = ""
        if minigame_uc_join_html:
            try:
                html = minigame_uc_join_html(
                    host_name=game.get("host_name") or "房主",
                    players=rows, seconds=seconds,
                    min_players=int(cfg["uc_min"]),
                    max_players=int(cfg["uc_max"]),
                    timeout=timeout)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[卧底] 报名卡构建失败，回退文本: {e}")
        text = (f"🕵️ 谁是卧底 · 报名中\n"
                f"============================\n\n"
                f"房主：{game.get('host_name') or '房主'}\n"
                f"已加入 {len(rows)}/{int(cfg['uc_max'])}：{names}\n\n"
                f"群友回复 1 加入；房主回复 2 立即开始。\n"
                f"至少 {int(cfg['uc_min'])} 人才能开局，回复 0 退出（房主=结束）。\n"
                f"⚠️ 本游戏会私聊发词，请管理员确认机器人已开启群聊私聊权限。\n"
                f"⏱️ {int(seconds)} 秒后自动开始/取消。")
        await self._send_list_card(event, html=html, text=text,
                                   total=max(1, len(rows)), label="卧底报名",
                                   force=True)

    async def _uc_join(self, event: AstrMessageEvent, gkey: str, game: dict) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") != "uc_join":
            return
        cfg = self._minigame_cfg()
        key, uid, name = self._points_user(event)
        name = name or uid or "玩家"
        players = game.setdefault("players", {})
        if key in players:
            await event.send(MessageChain([Plain("🙋 你已经在名单里了，等房主开始吧。")]))
            return
        if len(players) >= int(cfg["uc_max"]):
            await event.send(MessageChain([Plain(
                f"😅 人数已满（{int(cfg['uc_max'])} 人），本局不能再加入了。")]))
            return
        players[key] = {"name": name, "uid": str(uid or ""), "host": False}
        game.setdefault("order", []).append(key)
        game["updated"] = time.time()
        deadline = game.get("uc_deadline")
        if not deadline:
            deadline = time.time() + int(cfg["uc_join"])
            game["uc_deadline"] = deadline
        remaining = max(1, int(deadline - time.time()))
        await self._uc_send_join(event, game, remaining)

    async def _uc_leave(self, event: AstrMessageEvent, gkey: str, game: dict) -> None:
        """报名阶段玩家主动退出；房主退出则顺延给最早加入的人。"""
        if game.get("stage") != "uc_join":
            return
        key, uid, name = self._points_user(event)
        players = game.get("players") or {}
        if key not in players:
            await event.send(MessageChain([Plain("🙋 你还没加入本局。")]))
            return
        players.pop(key, None)
        order = [k for k in (game.get("order") or []) if k in players]
        game["order"] = order
        if key == game.get("host_key"):
            if order:
                nk = order[0]
                players[nk]["host"] = True
                game["host_key"] = nk
                game["host_name"] = players[nk].get("name") or "房主"
            else:
                self._minigame_cancel_task(game)
                self._minigame_sessions.pop(gkey, None)
                await event.send(MessageChain([Plain("🕵️ 报名已清空，本局取消。")]))
                return
        await event.send(MessageChain([Plain(f"👋 {name or '玩家'} 退出了报名。")]))
        cfg = self._minigame_cfg()
        deadline = float(game.get("uc_deadline") or (time.time() + cfg["uc_join"]))
        await self._uc_send_join(event, game,
                                 max(1, int(deadline - time.time())))

    async def _uc_resend_word(self, event: AstrMessageEvent, gkey: str,
                              game: dict) -> None:
        """发词阶段玩家回复「重发」：只补发自己的词。"""
        if game.get("stage") != "uc_deal":
            return
        uc = game.get("uc")
        key, _uid, name = self._points_user(event)
        p = (uc.players.get(key) if uc else None)
        if not p:
            await event.send(MessageChain([Plain("🙋 你不在本局名单里。")]))
            return
        text = (f"🔍 谁是卧底\n"
                f"你的词：{p.get('word') or '?'}\n\n"
                f"轮流用一句话描述它，不能直接说出词本身。\n"
                f"这条消息请勿转发到群里。")
        ok = await self._uc_dm(event, p.get("uid"), text)
        p["dm_ok"] = bool(ok) or bool(p.get("dm_ok"))
        await event.send(MessageChain([Plain(
            "✅ 已重新私聊发词，请查收。" if ok else
            "❌ 还是发不出去，请先加机器人好友，或联系管理员开启私聊权限。")]))

    async def _uc_join_timeout(self, gkey: str, game: dict) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") != "uc_join":
            return
        cfg = self._minigame_cfg()
        players = game.get("players") or {}
        ev = game.get("event")
        if len(players) < int(cfg["uc_min"]):
            self._minigame_sessions.pop(gkey, None)
            if ev:
                await ev.send(MessageChain([Plain(
                    f"😅 人数不足（{len(players)}/{int(cfg['uc_min'])}），"
                    f"本局已取消。发送 /小游戏 3 重新开。")]))
            return
        if ev:
            await self._uc_begin(ev, gkey, game, auto=True)

    async def _uc_begin(self, event: AstrMessageEvent, gkey: str, game: dict,
                        auto: bool = False) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") != "uc_join":
            return
        cfg = self._minigame_cfg()
        players = game.get("players") or {}
        if len(players) < int(cfg["uc_min"]):
            await event.send(MessageChain([Plain(
                f"🙋 还差 {int(cfg['uc_min']) - len(players)} 人才能开局"
                f"（当前 {len(players)} 人），继续回复 1 加入。")]))
            return
        self._minigame_cancel_task(game)
        pair = pick_pair(self._uc_word_pairs(), recent=self._uc_recent,
                         level=cfg["uc_level"])
        if not pair:
            self._minigame_sessions.pop(gkey, None)
            await event.send(MessageChain([Plain(
                "😕 词库为空，请管理员检查 core/undercover_words.py。")]))
            return
        uc = UndercoverGame(players, spy_count=int(cfg["uc_spies"]))
        uc.deal(pair)
        self._uc_remember_pair(uc)
        game.update({
            "stage": "uc_deal",
            "uc": uc,
            "host_key": game.get("host_key"),
            "event": event,
            "updated": time.time(),
        })
        if auto:
            await event.send(MessageChain([Plain(
                f"⏰ 报名时间到，{len(uc.alive_keys())} 人开局。")]))
        await event.send(MessageChain([Plain(
            "🕵️ 谁是卧底 · 发词中\n"
            "============================\n\n"
            "正在私聊给每位玩家发词，请留意私聊消息。\n"
            "没收到请回复「重发」，仍失败请联系管理员开启私聊权限。")]))

        failed = []
        for i, k in enumerate(uc.order):
            p = uc.player(k)
            text = (f"🔍 谁是卧底\n"
                    f"你的词：{p.get('word') or '?'}\n\n"
                    f"轮流用一句话描述它，不能直接说出词本身。\n"
                    f"这条消息请勿转发到群里。")
            ok = await self._uc_dm(event, p.get("uid"), text)
            if not ok:
                await asyncio.sleep(0.35)
                ok = await self._uc_dm(event, p.get("uid"), text)
            p["dm_ok"] = bool(ok)
            if not ok:
                failed.append(k)
            if i < len(uc.order) - 1:
                await asyncio.sleep(0.18)

        if self._minigame_sessions.get(gkey) is not game:
            return

        if failed:
            names = "、".join(f"@{uc.player(k).get('name') or '玩家'}"
                              for k in failed)
            await event.send(MessageChain([Plain(
                f"⚠️ {names} 没有收到私聊词。\n"
                "请在 12 秒内回复「重发」；仍失败会被移出本局。\n"
                "（管理员请检查机器人是否开启群聊私聊权限）")]))
            for _ in range(12):
                await asyncio.sleep(1)
                if self._minigame_sessions.get(gkey) is not game:
                    return
                if not [k for k in failed if not uc.player(k).get("dm_ok")]:
                    break
            failed = [k for k in failed if not uc.player(k).get("dm_ok")]

        if failed:
            names = "、".join(f"@{uc.player(k).get('name') or '玩家'}"
                              for k in failed)
            for k in failed:
                uc.remove(k)
            left = len(uc.alive_keys())
            if left < int(cfg["uc_min"]):
                self._minigame_sessions.pop(gkey, None)
                await event.send(MessageChain([Plain(
                    f"😕 私聊发词失败：{names} 没收到。\n"
                    f"剩余 {left} 人不足 {int(cfg['uc_min'])} 人，本局取消。\n"
                    "请管理员检查机器人是否开启了群聊私聊权限，玩家也可先加机器人好友。")]))
                return
            await event.send(MessageChain([Plain(
                f"⚠️ {names} 仍未收到私聊，已移出本局（剩余 {left} 人）。\n"
                "如果是权限问题，请管理员开启机器人私聊权限。")]))

        await self._uc_launch_round(event, gkey, game)

    async def _uc_launch_round(self, event: AstrMessageEvent, gkey: str,
                               game: dict) -> None:
        """开始新一轮（先发顺序卡，再 @ 当前发言人）。"""
        uc = game.get("uc")
        if not uc:
            return
        uc.start_round()
        game.update({"stage": "uc_desc", "event": event,
                     "updated": time.time(), "uc_tie": False})
        if not uc.turn_key:
            # 极端情况：全部出局/无人可发言
            await self._uc_start_vote(event, gkey, game)
            return
        await self._uc_send_round_card(event, game)
        await self._uc_ask_turn(event, gkey, game)

    async def _uc_send_round_card(self, event: AstrMessageEvent, game: dict) -> None:
        uc = game.get("uc")
        if not uc:
            return
        cfg = self._minigame_cfg()
        rows = uc.round_rows()
        tie = bool(game.get("uc_tie"))
        cur = uc.player(uc.turn_key)
        html = ""
        if minigame_uc_round_html:
            try:
                html = minigame_uc_round_html(
                    round_no=uc.round_no, rows=rows,
                    turn_name=cur.get("name") or "—",
                    seconds=int(cfg["uc_turn"]),
                    alive=len(uc.alive_keys()), tie=tie)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[卧底] 发言卡构建失败，回退文本: {e}")
        head = ("⚖️ 平票加时 · 补一句描述" if tie
                else f"🗣️ 第 {uc.round_no} 轮描述")
        lines = [head, "============================", ""]
        order_txt = " → ".join(
            f"{r['n']}.{r['name']}" for r in rows) or "—"
        lines.append(f"顺序：{order_txt}")
        lines.append(f"👉 轮到 {cur.get('name') or '—'}（{int(cfg['uc_turn'])} 秒，"
                     f"{int(cfg['uc_desc_max'])} 字以内）")
        await self._send_list_card(
            event, html=html, text="\n".join(lines),
            total=max(1, len(rows)), label="卧底发言", force=True)

    async def _uc_ask_turn(self, event: AstrMessageEvent, gkey: str,
                           game: dict, prefix: str = "") -> None:
        uc = game.get("uc")
        if not uc or self._minigame_sessions.get(gkey) is not game:
            return
        key = uc.turn_key
        if not key:
            return
        cfg = self._minigame_cfg()
        cur = uc.player(key)
        timeout = max(15, int(cfg["uc_turn"]))
        token = time.time_ns()
        game["turn_token"] = token
        game["updated"] = time.time()
        chain = [Plain((prefix + "\n👉 ") if prefix else "👉 ")]
        chain.append(self._minigame_at(cur.get("uid") or "",
                                       cur.get("name") or "玩家"))
        chain.append(Plain(f" 轮到你了（{timeout} 秒，"
                           f"{int(cfg['uc_desc_max'])} 字以内）。"))
        fallback = (((prefix + "\n") if prefix else "")
                    + f"👉 {cur.get('name') or '玩家'} 轮到你了"
                    f"（{timeout} 秒，{int(cfg['uc_desc_max'])} 字以内）。")
        await self._minigame_send_at(event, chain, fallback)
        self._minigame_schedule(gkey, game, timeout, "uc_turn", token)

    def _uc_turn_header(self, game: dict) -> str:
        uc = game.get("uc")
        if not uc:
            return ""
        return ("⚖️ 平票加时" if game.get("uc_tie")
                else f"🗣️ 第 {int(uc.round_no)} 轮")

    async def _uc_after_turn(self, event: AstrMessageEvent, gkey: str,
                             game: dict, prefix: str = "") -> None:
        uc = game.get("uc")
        if not uc:
            return
        nxt = uc.next_turn()
        if nxt:
            await self._uc_ask_turn(event, gkey, game, prefix=prefix)
            return
        # 本轮描述结束
        if prefix:
            await event.send(MessageChain([Plain(prefix)]))
        rows = uc.round_rows()
        cfg = self._minigame_cfg()
        html = ""
        if minigame_uc_round_html:
            try:
                html = minigame_uc_round_html(
                    round_no=uc.round_no, rows=rows,
                    seconds=int(cfg["uc_turn"]),
                    alive=len(uc.alive_keys()),
                    tie=bool(game.get("uc_tie")), summary=True)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[卧底] 汇总卡构建失败，回退文本: {e}")
        lines = [f"{self._uc_turn_header(game)} · 发言汇总", ""]
        for r in rows:
            lines.append(f"{r['n']}. {r['name']}："
                         + (r.get("desc") or ("弃权" if r.get("miss") else "未发言")))
        lines += ["", "开始投票，留意下一条投票卡。"]
        await self._send_list_card(event, html=html, text="\n".join(lines),
                                   total=max(1, len(rows)), label="卧底汇总",
                                   force=True)
        await self._uc_start_vote(event, gkey, game)

    async def _uc_start_vote(self, event: AstrMessageEvent, gkey: str,
                             game: dict) -> None:
        uc = game.get("uc")
        if not uc or self._minigame_sessions.get(gkey) is not game:
            return
        cfg = self._minigame_cfg()
        uc.votes = {}
        self._uc_cleanup_pending(game)
        cands = uc.vote_candidates()
        if not cands:
            return
        tie = bool(uc.tie_keys)
        token = time.time_ns()
        game.update({
            "stage": "uc_vote",
            "vote_token": token,
            "uc_vote_cands": cands,
            "uc_vote_numbers": {k: i for i, k in enumerate(cands, 1)},
            "uc_tie": tie,
            "event": event,
            "updated": time.time(),
        })
        rows = [{"n": i, "name": uc.player(k).get("name") or "玩家"}
                for i, k in enumerate(cands, 1)]
        html = ""
        if minigame_uc_vote_html:
            try:
                html = minigame_uc_vote_html(
                    round_no=uc.round_no, candidates=rows,
                    seconds=int(cfg["uc_vote"]),
                    alive=len(uc.alive_keys()), tie=tie)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[卧底] 投票卡构建失败，回退文本: {e}")
        lines = [("⚖️ 平票重投" if tie else f"🗳️ 第 {uc.round_no} 轮投票"),
                 "============================", ""]
        for r in rows:
            lines.append(f"{r['n']}. {r['name']}")
        lines.append("")
        lines.append("私聊机器人回复编号投票；回复「弃权」跳过。")
        lines.append(f"⏱️ {int(cfg['uc_vote'])} 秒后统一公布票型。")
        await self._send_list_card(event, html=html, text="\n".join(lines),
                                   total=max(1, len(rows)), label="卧底投票",
                                   force=True)

        vote_text = (f"🗳️ 第 {int(uc.round_no)} 轮投票（{int(cfg['uc_vote'])} 秒）\n"
                     + "\n".join(f"{r['n']}. {r['name']}" for r in rows)
                     + "\n\n直接回复编号投票；回复「弃权」跳过。")
        pid = str(event.get_platform_id() or "")
        failed = []
        for k in uc.alive_keys():
            p = uc.player(k)
            if not p.get("can_vote", True):
                continue
            if cfg["uc_private_vote"]:
                ok = await self._uc_dm(event, p.get("uid"), vote_text)
                p["dm_ok"] = bool(ok)
                if not ok:
                    failed.append(p.get("name") or "玩家")
                else:
                    self._uc_vote_pending[(pid, str(p.get("uid") or ""))] = {
                        "gkey": gkey, "gid": game.get("id"),
                        "token": token,
                    }
                await asyncio.sleep(0.15)
            else:
                p["dm_ok"] = False
        if failed:
            await event.send(MessageChain([Plain(
                "⚠️ " + "、".join(f"@{n}" for n in failed)
                + " 私聊发送失败，可直接在群里回复编号投票。")]))
        self._minigame_schedule(gkey, game, max(15, int(cfg["uc_vote"])),
                                "uc_vote", token)

    def _uc_parse_vote(self, game: dict, text: str) -> str:
        """把编号/弃权解析成目标 key；非法返回空串。"""
        cmd = (text or "").strip()
        if not cmd:
            return ""
        if cmd in ("弃权", "不投", "跳过", "abstain"):
            return "__abstain__"
        numbers = game.get("uc_vote_numbers") or {}
        m = re.fullmatch(r"\d{1,2}", cmd)
        if not m:
            return ""
        n = int(cmd)
        for k, i in numbers.items():
            if int(i) == n:
                return str(k)
        return ""

    async def _uc_handle_vote(self, event: AstrMessageEvent, gkey: str,
                              game: dict, text: str, via_dm: bool = False) -> bool:
        if game.get("stage") != "uc_vote":
            return False
        uc = game.get("uc")
        if not uc:
            return False
        key, uid, name = self._points_user(event)
        p = uc.players.get(key)
        if not p:
            return False
        if not p.get("alive"):
            if via_dm:
                await event.send(MessageChain([Plain("😵 你已出局，本局不能再投票。")]))
                return True
            return False
        if not p.get("can_vote", True):
            if via_dm:
                await event.send(MessageChain([Plain(
                    "🙈 你连续弃权，本轮没有投票权。")]))
                return True
            return False
        target = self._uc_parse_vote(game, text)
        if not target:
            if via_dm:
                await event.send(MessageChain([Plain(
                    "请回复编号；也可以回复「弃权」。")]))
                return True
            return False
        if target == "__abstain__":
            uc.votes[key] = ""
            if via_dm:
                await event.send(MessageChain([Plain("✅ 已弃权。")]))
        else:
            ok, err = uc.record_vote(key, target)
            if not ok:
                if via_dm:
                    await event.send(MessageChain([Plain(f"⚠️ {err}")]))
                return bool(via_dm)
            if via_dm:
                await event.send(MessageChain([Plain("✅ 已记录。")]))
        if uc.all_voted():
            self._minigame_cancel_task(game)
            # 私聊投票时 event 是私聊，票型必须回到群里发
            await self._uc_tally(game.get("event") or event, gkey, game)
        return True

    async def _uc_vote_timeout(self, gkey: str, game: dict, token=None) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") != "uc_vote":
            return
        if token is not None and game.get("vote_token") != token:
            return
        ev = game.get("event")
        if ev:
            await self._uc_tally(ev, gkey, game)

    async def _uc_tally(self, event: AstrMessageEvent, gkey: str, game: dict) -> None:
        uc = game.get("uc")
        if not uc or self._minigame_sessions.get(gkey) is not game:
            return
        res = uc.tally()
        counts, top, maxn = res["counts"], res["top"], res["max"]
        abstain = res["abstain"]
        cfg = self._minigame_cfg()

        def _nm(k: str) -> str:
            return uc.player(k).get("name") or "玩家"

        tie = len(top) > 1
        will_tie_desc = tie and int(uc.tie_times or 0) < 1
        eliminated = "" if (tie or maxn <= 0) else top[0]
        role_txt = ""
        if eliminated and cfg["uc_reveal_role"]:
            role_txt = "，身份：" + (
                "卧底" if uc.player(eliminated).get("role") == ROLE_SPY else "平民")

        if maxn <= 0:
            note = ("连续两轮全员弃权，将随机淘汰一人。"
                    if int(uc.abstain_rounds or 0) >= 1 else "本轮全员弃权，无人出局。")
        elif tie:
            note = (("平票：" + "、".join(_nm(k) for k in top) + "，各补一句后重投。")
                    if will_tie_desc else "再次平票，本轮无人出局。")
        else:
            note = (f"{_nm(eliminated)} 出局"
                    f"（{int(counts.get(eliminated, 0) or 0)} 票{role_txt}）。")

        parts = [f"{_nm(k)} {v} 票" for k, v in sorted(
            counts.items(), key=lambda kv: -kv[1]) if v > 0]
        if abstain:
            parts.append(f"弃权 {len(abstain)} 票")
        rows = []
        for k in sorted(counts, key=lambda x: -counts.get(x, 0)):
            state = ""
            if maxn > 0:
                if tie and k in top:
                    state = "tie"
                elif not tie and k == eliminated:
                    state = "out"
            rows.append({"name": _nm(k), "votes": int(counts.get(k, 0) or 0),
                         "state": state})
        html = ""
        if minigame_uc_tally_html:
            try:
                html = minigame_uc_tally_html(
                    round_no=uc.round_no, rows=rows, eliminated=_nm(eliminated),
                    tie=tie, abstain=len(abstain),
                    alive=len(uc.alive_keys()), note=note)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[卧底] 票型卡构建失败，回退文本: {e}")
        head = ("⚖️ 平票重投 · 票型" if game.get("uc_tie")
                else f"📊 第 {uc.round_no} 轮票型")
        text = (head + "\n" + (" · ".join(parts) if parts else "本轮没有有效票")
                + "\n" + note)
        await self._send_list_card(event, html=html, text=text,
                                   total=max(1, len(rows)), label="卧底票型",
                                   force=True)

        if maxn > 0:
            uc.abstain_rounds = 0

        # 全员弃权
        if maxn <= 0:
            uc.abstain_rounds = int(getattr(uc, "abstain_rounds", 0)) + 1
            if uc.abstain_rounds >= 2:
                alive = uc.alive_keys()
                if not alive:
                    await self._uc_finish(event, gkey, game, ROLE_SPY, "全员弃权")
                    return
                out = random.choice(alive)
                uc.eliminate(out)
                uc.abstain_rounds = 0
                await event.send(MessageChain([Plain(
                    f"🎲 连续两轮全员弃权，随机淘汰 {_nm(out)}。")]))
                await self._uc_after_elimination(event, gkey, game)
                return
            await self._uc_next_round(event, gkey, game)
            return

        # 平票
        if tie:
            if will_tie_desc:
                uc.tie_times = int(uc.tie_times or 0) + 1
                game.update({"stage": "uc_tie_desc", "uc_tie": True,
                             "event": event, "updated": time.time()})
                uc.start_tie(top)
                await self._uc_send_round_card(event, game)
                await self._uc_ask_turn(event, gkey, game)
            else:
                await self._uc_next_round(event, gkey, game)
            return

        votes = int(counts.get(eliminated, 0) or 0)
        uc.eliminate(eliminated, votes)
        await self._uc_after_elimination(event, gkey, game)

    async def _uc_after_elimination(self, event: AstrMessageEvent, gkey: str,
                                    game: dict) -> None:
        uc = game.get("uc")
        if not uc:
            return
        winner = uc.winner()
        if winner:
            await self._uc_finish(event, gkey, game, winner,
                                  reason="卧底全部出局" if winner == ROLE_CIVIL
                                  else "卧底存活到最后")
            return
        if int(uc.round_no) >= self.UC_MAX_ROUNDS:
            await self._uc_finish(event, gkey, game, ROLE_SPY, "回合数用尽")
            return
        await self._uc_next_round(event, gkey, game)

    async def _uc_next_round(self, event: AstrMessageEvent, gkey: str,
                             game: dict) -> None:
        uc = game.get("uc")
        if not uc or self._minigame_sessions.get(gkey) is not game:
            return
        uc.start_round()
        game.update({"stage": "uc_desc", "uc_tie": False,
                     "event": event, "updated": time.time()})
        if not uc.turn_key:
            await self._uc_start_vote(event, gkey, game)
            return
        await self._uc_send_round_card(event, game)
        await self._uc_ask_turn(event, gkey, game)

    async def _uc_turn_timeout(self, gkey: str, game: dict, token=None) -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        if game.get("stage") not in ("uc_desc", "uc_tie_desc"):
            return
        if token is not None and game.get("turn_token") != token:
            return
        uc = game.get("uc")
        if not uc:
            return
        key = uc.turn_key
        if not key:
            return
        uc.mark_miss(key)
        ev = game.get("event")
        if not ev:
            self._minigame_sessions.pop(gkey, None)
            return
        p = uc.player(key)
        await ev.send(MessageChain([Plain(
            f"⏭️ {p.get('name') or '玩家'} 超时未描述，记弃权。")]))
        await self._uc_after_turn(ev, gkey, game)

    async def _uc_submit_desc(self, event: AstrMessageEvent, gkey: str,
                              game: dict, text: str) -> bool:
        uc = game.get("uc")
        if not uc:
            return False
        key, uid, name = self._points_user(event)
        if key != uc.turn_key:
            return False
        cfg = self._minigame_cfg()
        p = uc.player(key)
        desc = re.sub(r"\s+", " ", str(text or "")).strip()
        if not desc:
            return True
        if len(desc) > int(cfg["uc_desc_max"]):
            await event.send(MessageChain([Plain(
                f"✂️ 太长了，控制在 {int(cfg['uc_desc_max'])} 字以内再发一次。")]))
            return True
        word = str(p.get("word") or "")
        if word and word in desc:
            p["violations"] = int(p.get("violations", 0) or 0) + 1
            if p["violations"] >= 2:
                uc.mark_miss(key)
                await event.send(MessageChain([Plain(
                    "🚫 又直接说出了自己的词，本轮记弃权。")]))
                await self._uc_after_turn(event, gkey, game)
                return True
            await event.send(MessageChain([Plain(
                "🚫 不能直接说出自己的词，换一句（再犯本轮弃权）。")]))
            return True
        uc.note_desc(key, desc)
        self._minigame_cancel_task(game)
        await self._uc_after_turn(
            event, gkey, game,
            prefix=f"✅ {p.get('name') or '玩家'}：{desc}")
        return True

    async def _uc_finish(self, event: AstrMessageEvent, gkey: str, game: dict,
                         winner: str, reason: str = "") -> None:
        if self._minigame_sessions.get(gkey) is not game:
            return
        uc = game.get("uc")
        if not uc:
            return
        self._minigame_cancel_task(game)
        self._minigame_sessions.pop(gkey, None)
        self._uc_cleanup_pending(game)
        cfg = self._minigame_cfg()
        win_side = ROLE_CIVIL if winner == ROLE_CIVIL else ROLE_SPY
        title = "平民胜利" if win_side == ROLE_CIVIL else "卧底胜利"
        rows, text_lines, awarded_total = [], [], 0
        for i, k in enumerate(uc.order, 1):
            p = uc.player(k)
            if not p:
                continue
            removed = bool(p.get("removed"))
            is_win = (not removed) and p.get("role") == win_side
            points = 0
            note = ""
            if is_win:
                points = int(cfg["reward"]) * (2 if p.get("alive") else 1)
                if p.get("role") == ROLE_SPY:
                    points += int(cfg["reward"])
                got, note = self._minigame_award(k, p.get("name") or "", points)
                awarded_total += got
                points = got
            if not removed:
                try:
                    self._minigame_db().uc_record(
                        k, p.get("name") or "", p.get("role") or "",
                        is_win, rounds=int(uc.round_no),
                        desc_count=len(p.get("descs") or {}),
                        votes_received=int(p.get("votes_received", 0) or 0))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[卧底] 战绩写入失败: {e}")
            role_txt = "卧底" if p.get("role") == ROLE_SPY else "平民"
            state_txt = "未参与" if removed else ("存活" if p.get("alive") else "出局")
            chip = (f'<span class="chip chip-win">+{points} 积分</span>'
                    if is_win and points > 0 else
                    ('<span class="chip chip-gold">奖励已达上限</span>'
                     if is_win and note else
                     f'<span class="chip chip-loss">{role_txt}</span>'))
            rows.append({
                "n": i, "title": p.get("name") or "玩家",
                "right": chip,
                "meta": (f"{role_txt} · {state_txt}"
                         f" · 被投 {int(p.get('votes_received', 0) or 0)} 次"
                         + (f" · +{points} 积分" if points else "")),
            })
            text_lines.append(
                f"{i}. {p.get('name') or '玩家'} {role_txt} {state_txt}"
                + (f" +{points} 积分" if points else "")
                + (note or ""))

        played = len([k for k in uc.order if not uc.player(k).get("removed")])
        sub = f"{int(uc.round_no)} 轮 · {played} 人"
        if reason:
            sub += f" · {reason}"
        foot = ['<div><span class="k">再来</span>发送 <b>/小游戏 3</b> 开新局</div>']
        if cfg["daily_cap"] > 0:
            foot.append(f'<div class="dim"><span class="k">奖励</span>'
                        f'每日游戏奖励上限 {int(cfg["daily_cap"])} 积分</div>')
        head = [
            f"🕵️ 谁是卧底 · {title}",
            "============================",
            f"平民词：{uc.words.get('civil') or '?'}    "
            f"卧底词：{uc.words.get('spy') or '?'}",
        ]
        if reason:
            head.append(f"结算原因：{reason}")
        text = "\n".join(head + [""] + text_lines
                         + (["", f"💰 本局共发出 {awarded_total} 积分"] if awarded_total else [])
                         + ["", "发送 /小游戏 3 再来一局。"])
        html = ""
        if minigame_uc_result_html:
            try:
                html = minigame_uc_result_html(
                    title=f"谁是卧底 · {title}",
                    subtitle=sub,
                    civil_word=uc.words.get("civil") or "?",
                    spy_word=uc.words.get("spy") or "?",
                    rows=rows, foot_lines=foot, page_ind="本局结算")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[卧底] 结算卡构建失败，回退文本: {e}")
        await self._send_list_card(event, html=html, text=text,
                                   total=max(1, len(rows)), label="卧底结算",
                                   force=True)

    async def _handle_uc_private(self, event: AstrMessageEvent, text: str) -> bool:
        """私聊投票入口；返回 True 表示已消费。"""
        if event.get_group_id():
            return False
        pid = str(event.get_platform_id() or "")
        uid = str(event.get_sender_id() or "")
        info = self._uc_vote_pending.get((pid, uid))
        if not info:
            return False
        gkey = info.get("gkey") or ""
        game = self._minigame_sessions.get(gkey)
        if (not game or game.get("id") != info.get("gid")
                or game.get("stage") != "uc_vote"):
            self._uc_vote_pending.pop((pid, uid), None)
            return False
        if game.get("vote_token") != info.get("token"):
            self._uc_vote_pending.pop((pid, uid), None)
            return False
        try:
            await self._uc_handle_vote(event, gkey, game, text, via_dm=True)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[卧底] 私聊投票处理失败: {e}")
        return True

    async def _handle_minigame_message(self, event: AstrMessageEvent,
                                       text: str) -> bool:
        """处理游戏内输入；返回 True 表示已消费，False 交回普通聊天。"""
        gkey = self._minigame_group_key(event)
        if not gkey:
            return False
        game = self._minigame_sessions.get(gkey)
        if not game:
            return False
        stage = game.get("stage")
        # 用户正在搜索/选集时优先走原来的会话；
        # 卧底游戏除外，否则轮流描述会被其它会话卡住
        if not str(stage or "").startswith("uc_") and \
                self._minigame_has_user_session(event):
            return False
        if time.time() - float(game.get("updated") or 0) > 900:
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            return False
        cmd = (text or "").strip()
        game["event"] = event
        game["updated"] = time.time()
        if cmd in ("0", "结束", "不玩了", "退出", "关闭"):
            if str(stage or "").startswith("uc_"):
                key, _uid, _name = self._points_user(event)
                if stage == "uc_join" and key != game.get("host_key"):
                    await self._uc_leave(event, gkey, game)
                    return True
                if key != game.get("host_key"):
                    await event.send(MessageChain([Plain(
                        "🙋 只有房主能结束本局，想退出请等本局结束。")]))
                    return True
            await self._minigame_end(event, gkey, game, reason="手动结束")
            return True
        try:
            if stage == "lobby":
                if cmd in ("1", "猜数字", "数字炸弹", "炸弹"):
                    await self._minigame_start_bomb(event, gkey, game)
                    return True
                if cmd in ("2", "封面猜猜", "封面", "猜封面"):
                    key, uid, name = self._points_user(event)
                    self._minigame_cancel_task(game)
                    game.update({"stage": "cover_pick", "event": event,
                                 "cover_owner_key": key,
                                 "cover_owner_name": name or uid or "玩家",
                                 "updated": time.time()})
                    await self._minigame_send_cover_pick(event, game)
                    self._minigame_schedule(gkey, game, 90, "cover_pick")
                    return True
                if cmd in ("3", "谁是卧底", "卧底"):
                    if not self._minigame_cfg()["uc_enabled"]:
                        await event.send(MessageChain([Plain(
                            "🕵️ 谁是卧底未启用，请联系管理员开启。")]))
                        return True
                    await self._uc_start(event, gkey, game)
                    return True
                return False
            if stage == "bomb_wait":
                if cmd == "1":
                    await self._minigame_bomb_join(event, gkey, game)
                    return True
                if cmd == "2":
                    key, _uid, _name = self._points_user(event)
                    if key != game.get("host_key"):
                        await event.send(MessageChain([Plain(
                            "🙋 只有房主可以立即开始，等房主回复 2 吧。")]))
                    else:
                        await self._minigame_bomb_begin(event, gkey, game)
                    return True
                return False
            if stage == "bomb":
                if re.fullmatch(r"\d{1,3}", cmd):
                    await self._minigame_bomb_guess(event, gkey, game, cmd)
                    return True
                return False
            if stage == "cover_pick":
                key, _uid, _name = self._points_user(event)
                if game.get("cover_owner_key") and key != game["cover_owner_key"]:
                    owner_name = game.get("cover_owner_name") or "发起者"
                    await event.send(MessageChain([Plain(
                        f"🙋 封面猜猜是单人游戏，只有发起者 {owner_name} 可以选题。")]))
                    return True
                kinds = {"1": "movie", "2": "tv", "3": "anime"}
                kind = kinds.get(cmd)
                if kind:
                    await self._minigame_start_cover(event, gkey, game, kind)
                    return True
                return False
            if stage == "cover":
                if normalize_choice(cmd):
                    await self._minigame_cover_answer(event, gkey, game, cmd)
                    return True
                return False
            if stage == "uc_join":
                if cmd == "1":
                    await self._uc_join(event, gkey, game)
                    return True
                if cmd == "2":
                    key, _uid, _name = self._points_user(event)
                    if key != game.get("host_key"):
                        await event.send(MessageChain([Plain(
                            "🙋 只有房主可以立即开始。")]))
                    else:
                        await self._uc_begin(event, gkey, game)
                    return True
                return False
            if stage == "uc_deal":
                if cmd in ("重发", "重发词", "重新发", "没收到"):
                    await self._uc_resend_word(event, gkey, game)
                    return True
                return False
            if stage in ("uc_desc", "uc_tie_desc"):
                return await self._uc_submit_desc(event, gkey, game, cmd)
            if stage == "uc_vote":
                cfg = self._minigame_cfg()
                uc = game.get("uc")
                key, _uid, _name = self._points_user(event)
                p = (uc.players.get(key) if uc else None) or {}
                if not p.get("alive"):
                    return False
                if not cfg["uc_private_vote"] or not p.get("dm_ok", True):
                    return await self._uc_handle_vote(event, gkey, game, cmd)
                if re.fullmatch(r"\d{1,2}", cmd or ""):
                    await event.send(MessageChain([Plain(
                        "🗳️ 本局是私聊投票，请到私聊里回复编号"
                        "（私聊发不出去可直接在群里回复）。")]))
                    return True
                return False
        except Exception as e:  # noqa: BLE001
            logger.error(f"[小游戏] 处理失败 stage={stage}: {e}")
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            try:
                await event.send(MessageChain([Plain(
                    f"😕 小游戏处理失败，已结束：{str(e)[:100]}")]))
            except Exception:
                pass
            return True
        return False

    async def _check_cookie_silent(self) -> str | None:
        """
        静默检查 Cookie 有效性，不对外发消息。
        返回：None=有效，字符串=失效原因（"expired"|"limit"|"invalid"|"error:xxx"）
        """
        cs = self._get_cookie()
        if not cs:
            return "invalid"
        try:
            ck, cm = await asyncio.to_thread(check_cookie, cs)
        except Exception as e:
            return f"error:{str(e)[:50]}"
        if ck is True:
            return None
        if ck == "limit":
            return "limit"
        if ck is False:
            return "expired"
        return "invalid"

    # ==================== 游戏源路由（xdgame / switch618 自动切换） ====================

    def _game_source(self) -> str:
        """返回当前游戏搜索源：'xdgame' 或 'switch618'。"""
        config = self._get_config()
        if not isinstance(config, dict):
            return "xdgame"
        src = (config.get("game_source") or "auto").strip().lower()
        if src == "xdgame":
            return "xdgame"
        if src == "switch618":
            return "switch618"
        # auto：配置了 xdgame 账密 → xdgame，否则 switch618
        u = (config.get("xdgame_username") or "").strip()
        p = (config.get("xdgame_password") or "").strip()
        return "xdgame" if (u and p) else "switch618"

    def _g_cookie(self) -> str:
        """返回当前源对应的登录 Cookie 字符串。"""
        config = self._get_config()
        if not isinstance(config, dict):
            return ""
        if self._game_source() == "switch618":
            return (config.get("switch618_cookie") or "").strip()
        return (config.get("cookie") or "").strip()

    def _g_search(self, keyword, n):
        if self._game_source() == "switch618":
            return search_games_618(keyword, n)
        return search_games(keyword, n)

    def _g_detail(self, url, cookie):
        if self._game_source() == "switch618":
            return get_game_detail_618(url, cookie)
        return get_game_detail(url, cookie)

    def _g_resolve(self, link, cookie):
        if self._game_source() == "switch618":
            return resolve_download_link_618(link, cookie)
        return resolve_download_link(link, cookie)

    async def _g_auto_login(self, reason: str = "") -> bool:
        """xdgame Cookie 失效时，用配置的账号密码自动登录并持久化 Cookie。

        只有登录流程不需要验证码时才能全自动完成；需要验证码时会放弃并提示
        手动发送 /game_cookie_refresh（验证码必须由用户看图输入）。
        """
        if self._game_source() != "xdgame":
            return False
        cfg = self._get_config() or {}
        username = (cfg.get("xdgame_username") or "").strip()
        password = (cfg.get("xdgame_password") or "").strip()
        if not username or not password:
            return False
        now = time.time()
        if self._g_auto_login_busy or now < self._g_auto_login_next:
            return False
        self._g_auto_login_busy = True
        try:
            logger.info(f"[暮黎资源] xdgame Cookie 失效({reason})，尝试账号自动登录: {username[:4]}***")
            result = await login_with_password_async(username, password)
            if result.get("ok") and not result.get("needs_captcha"):
                cookie_str = format_cookie_string(
                    extract_xdgame_cookies(result.get("cookies") or {}))
                if cookie_str:
                    await self._update_config("cookie", cookie_str)
                    logger.info(f"[暮黎资源] xdgame 自动登录成功，Cookie 已保存 "
                                f"({len(cookie_str)} 字符)")
                    self._g_auto_login_next = time.time() + 60
                    return True
            if result.get("needs_captcha"):
                logger.warning("[暮黎资源] xdgame 自动登录需要验证码，已跳过；"
                               "请管理员发送 /game_cookie_refresh 手动完成")
                self._g_auto_login_next = now + 600
            else:
                logger.warning(f"[暮黎资源] xdgame 自动登录失败: "
                               f"{result.get('error', '未知错误')}")
                self._g_auto_login_next = now + 300
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] xdgame 自动登录异常: {e}")
            self._g_auto_login_next = now + 300
        finally:
            self._g_auto_login_busy = False
        return False

    async def _g_check_cookie(self):
        """路由 Cookie 有效性检查。返回 None=有效，字符串=失效原因('expired'|'invalid'|'error:..')。

        xdgame 源：Cookie 失效时若配置了账号密码，先尝试一次自动登录，再复查。
        """
        if self._game_source() == "switch618":
            cfg = self._get_config()
            cs = (cfg.get("switch618_cookie", "") if isinstance(cfg, dict) else "").strip()
            if not cs:
                return "invalid"
            try:
                ok, msg = await asyncio.to_thread(check_618_cookie, cs)
            except Exception as e:
                return f"error:{e}"
            if ok is True:
                return None
            if ok is False:
                return "expired"
            return "invalid"
        bad = await self._check_cookie_silent()
        if bad in ("expired", "invalid"):
            if await self._g_auto_login(bad):
                bad = await self._check_cookie_silent()
        return bad

    async def _fetch_game_detail(self, event, url: str) -> dict:
        """取游戏详情；switch618 源会先校验 Cookie 有效性。

        返回 detail dict；若 Cookie 失效/未配置，返回 {"need_login": True}。
        """
        if self._game_source() == "switch618":
            c = self._g_cookie()
            if not c:
                return {"need_login": True, "reason": "nocookie"}
            try:
                ok, _ = await asyncio.to_thread(check_618_cookie, c)
            except Exception:
                ok = None
            if ok is not True:
                return {"need_login": True, "reason": "expired"}
        return await asyncio.to_thread(lambda u=url: self._g_detail(u, self._g_cookie()))

    def _game_login_hint(self) -> str:
        """根据当前源返回 Cookie 失效时的提示文案。"""
        if self._game_source() == "switch618":
            return ("⚠️ 游戏资源 Cookie 已失效或未配置，无法获取下载链接。\n"
                    "💡 请联系管理员发送 /game_cookie_refresh 获取 Cookie。")
        return ("⚠️ 游戏资源 Cookie 已失效，无法获取下载链接。\n"
                "💡 请发送 /game_cookie_refresh 更新 Cookie。")

    # ==================== LLM 工具（返回文本给LLM，不单独send） ====================

    async def _handle_session_reply(self, event: AstrMessageEvent, is_sw_session: bool):
        """用 session_waiter 拦截数字/翻页回复，防止 AngelHeart 介入。"""
        text = event.message_str.strip()

        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _waiter(controller: SessionController, ev: AstrMessageEvent):
            nonlocal text
            text = ev.message_str.strip()
            logger.info(f"[SESSION-WAITER] 收到回复 text=[{text}]")
            controller.stop()  # 一次回复后停止（我们只需要最新一条）

        try:
            await _waiter(event)
        except TimeoutError:
            return

        # session_waiter 拦截了这一条消息（不会触发 AngelHeart）
        # 现在调用正常的处理流程
        if is_sw_session:
            await self._process_sw_session_reply(event, text)
        else:
            await self._process_game_session_reply(event, text)

    async def _process_sw_session_reply(self, event: AstrMessageEvent, text: str):
        """处理软件搜索会话中的回复（数字/翻页/网盘名）。"""
        ses = self._search_sessions.get(event)
        if not ses:
            logger.warning(f"[SESSION-WAITER] ses 已失效 text=[{text}]")
            return
        if text in ("下一页", "上一页"):
            ps = ses.get("page_size", 8); t = len(ses["results"])
            if text == "下一页": ses["page"] = 0 if (ses.get("page", 0) + 1) * ps >= t else ses.get("page", 0) + 1
            else: pp = ses.get("page", 0) - 1; ses["page"] = (t + ps - 1) // ps - 1 if pp < 0 else pp
            ses["_updated"] = time.time()
            await self._send_search_page(event, "software", self._format_sw_page(ses), ses=ses); return
        if text.startswith("跳"):
            m = re.search(r"\d+", text)
            if m:
                ps = ses.get("page_size", 8); t = len(ses["results"]); pt = (t + ps - 1) // ps; n = int(m.group())
                if 1 <= n <= pt: ses["page"] = n - 1; ses["_updated"] = time.time(); await self._send_search_page(event, "software", self._format_sw_page(ses), ses=ses); return
        num = self._parse_natural_number(text)
        if num == -2: num = len(ses["results"]) - (ses.get("page", 0) * ses.get("page_size", 8))
        if num == 0: self._search_sessions.delete(event); await event.send(MessageChain([Plain("已取消。")])); return
        r = ses["results"]; pg = ses.get("page", 0); ps = ses.get("page_size", 8); t = len(r)
        st = pg * ps; ed = min(st + ps, t); pc = ed - st
        if num < 1 or num > pc:
            await event.send(MessageChain([Plain(f"请输入1-{pc}之间的数字，或说「第一个」「第二个」。回复0取消。")])); return
        ai = st + num - 1; sel = r[ai]
        self._search_sessions.update(event, selected_index=ai, stage="fetching")
        await event.send(MessageChain([Plain(f"已选择：{sel['title']}")]))
        try:
            detail = await asyncio.to_thread(get_search_detail, sel["url"])
        except Exception as e:
            self._search_sessions.delete(event); await event.send(MessageChain([Plain(f"失败：{str(e)[:200]}")])); return
        if not detail.get("download_links"):
            self._search_sessions.delete(event); await event.send(MessageChain([Plain("无下载链接。")])); return
        self._search_sessions.update(event, detail=detail, stage="select_link")
        await self._send_software_link_menu(event, detail, sel, detail["download_links"])
        return

    async def _process_game_session_reply(self, event: AstrMessageEvent, text: str):
        """处理游戏搜索会话中的回复。"""
        ses = self._sessions.get(event)
        if not ses:
            logger.warning(f"[SESSION-WAITER] game ses 已失效 text=[{text}]")
            return
        if text in ("下一页", "上一页"):
            ps = ses.get("page_size", 8); t = len(ses["results"])
            if text == "下一页": ses["page"] = 0 if (ses.get("page", 0) + 1) * ps >= t else ses.get("page", 0) + 1
            else: pp = ses.get("page", 0) - 1; ses["page"] = (t + ps - 1) // ps - 1 if pp < 0 else pp
            ses["_updated"] = time.time()
            await self._send_search_page(event, "game", self._format_game_page(ses), ses=ses); return
        if text.startswith("跳"):
            m = re.search(r"\d+", text)
            if m:
                ps = ses.get("page_size", 8); t = len(ses["results"]); pt = (t + ps - 1) // ps; n = int(m.group())
                if 1 <= n <= pt: ses["page"] = n - 1; ses["_updated"] = time.time(); await self._send_search_page(event, "game", self._format_game_page(ses), ses=ses); return
        num = self._parse_natural_number(text)
        if num == -2: num = len(ses["results"]) - (ses.get("page", 0) * ses.get("page_size", 8))
        if num == 0: self._sessions.delete(event); await event.send(MessageChain([Plain("已取消。")])); return
        r = ses["results"]; pg = ses.get("page", 0); ps = ses.get("page_size", 8); t = len(r)
        st = pg * ps; ed = min(st + ps, t); pc = ed - st
        if num < 1 or num > pc:
            await event.send(MessageChain([Plain(f"请输入1-{pc}之间的数字，或说「第一个」「第二个」。回复0取消。")])); return
        ai = st + num - 1; sel = r[ai]
        self._sessions.update(event, selected_index=ai, stage="fetching")
        await event.send(MessageChain([Plain(f"已选择：{sel['title']}")]))
        try:
            detail = await self._fetch_game_detail(event, sel["url"])
        except Exception as e:
            self._sessions.delete(event); await event.send(MessageChain([Plain(f"失败：{str(e)[:200]}")])); return
        if detail.get("need_login"):
            self._sessions.delete(event); await event.send(MessageChain([Plain(self._game_login_hint())])); return
        if not detail.get("download_links"):
            self._sessions.delete(event); await event.send(MessageChain([Plain("无下载链接。")])); return
        self._sessions.update(event, game_detail=detail, stage="select_link")
        await self._send_game_link_menu(event, detail, sel, detail["download_links"])
        return

    @filter.llm_tool(name="search_game")
    async def llm_search_game(self, event: AstrMessageEvent, game_name: str):
        """专门搜索游戏资源。当用户明确说"找游戏"或游戏关键词时调用。

        翻页与选择由系统自动处理，用户回复「下一页/序号」即可，无需调用其它工具。

        Args:
            game_name(string): 游戏名称（已自动去掉"游戏"后缀）
        """
        game_name = clean_search_keyword(game_name)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, game_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        _blocked = self._points_guard(event, "game")
        if _blocked:
            return _blocked
        config = self._get_config(); ps = 8
        fm = min(int(config.get("max_search_results",32) if isinstance(config,dict) else 32), 48)
        tag = "【暮黎资源】"

        # 检查 xdgame Cookie 有效性
        cookie_bad = await self._g_check_cookie()
        if cookie_bad in ("expired", "invalid"):
            logger.info(f"[暮黎资源] search_game('{game_name}') → Cookie {cookie_bad}")
            if self._game_source() == "switch618":
                return (f"{tag} ⚠️ 游戏资源 Cookie 未生效，无法搜索游戏。\n"
                        f"请联系管理员发送 /game_cookie_refresh 获取 Cookie。")
            return (f"{tag} ⚠️ 游戏资源 Cookie 已失效，无法搜索游戏。\n"
                    f"请发送 /game_cookie_refresh 更新 Cookie 后再试。")

        try: results = await asyncio.to_thread(self._g_search, game_name, fm)
        except Exception as e:
            logger.error(f"[暮黎资源] search_game('{game_name}') 失败: {e}")
            return f"{tag} 搜索失败：{str(e)[:100]}"
        if not results:
            logger.info(f"[暮黎资源] search_game('{game_name}') → 0条")
            return f"{tag} 未找到与「{game_name}」相关的游戏。请换个更精确的关键词再试。"
        _charge_txt = self._points_charge(event, "game", game_name)
        # 防覆盖：已有同关键词会话则复用
        existing = self._sessions.get(event)
        if existing and existing.get("keyword") == game_name:
            logger.info(f"[暮黎资源] search_game('{game_name}') → 复用已有会话(stage={existing.get('stage')})")
        else:
            self._sessions.set(event, {"stage":"select_game","keyword":game_name,"results":results,
                                        "page":0,"page_size":ps,"selected_index":-1,"game_detail":None,"selected_link":None})
        t = len(results); pt = (t + ps - 1) // ps
        # ★v4 关键修复：工具自己直接发格式化页面（和翻页走同一条路径，风格 100% 一致）
        page_txt = self._format_game_page(self._sessions.get(event))
        final_txt = tag + f" 🎮 游戏搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt + _charge_txt
        await self._send_search_page(event, "game", final_txt, ses=self._sessions.get(event), note=_charge_txt)
        # 标记 _llm_handled 让 _strip_llm_chitchat_after_tool 清空 LLM 后续多嘴输出
        self._sessions.update(event, _llm_handled=True)
        logger.info(f"[暮黎资源] search_game('{game_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个游戏结果，当前第 1/{pt} 页。用户的下一步操作（翻页、选数字、选网盘）由 on_any_message 直接处理，无需 LLM 再调用工具。"

    @filter.llm_tool(name="search_software")
    async def llm_search_software(self, event: AstrMessageEvent, software_name: str):
        """专门搜索软件资源。当用户明确说"找软件"或软件关键词时调用。

        翻页与选择由系统自动处理，用户回复「下一页/序号」即可，无需调用其它工具。

        Args:
            software_name(string): 软件名称（已自动去掉"软件""应用"后缀）
        """
        software_name = clean_search_keyword(software_name)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, software_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        _blocked = self._points_guard(event, "software")
        if _blocked:
            return _blocked
        ps = 8; tag = "【暮黎资源】"
        try: results = await asyncio.to_thread(search_software, software_name, 32)
        except Exception as e:
            logger.error(f"[暮黎资源] search_software('{software_name}') 失败: {e}")
            return f"{tag} 搜索失败：{str(e)[:100]}"
        if not results:
            logger.info(f"[暮黎资源] search_software('{software_name}') → 0条")
            return f"{tag} 未找到与「{software_name}」相关的资源。请换个更精确的关键词再试。"
        _charge_txt = self._points_charge(event, "software", software_name)
        existing = self._search_sessions.get(event)
        if existing and existing.get("keyword") == software_name:
            logger.info(f"[暮黎资源] search_software('{software_name}') → 复用已有会话")
        else:
            self._search_sessions.set(event, {"stage":"select_software","keyword":software_name,"results":results,
                                               "page":0,"page_size":ps,"selected_index":-1,"detail":None,"selected_link":None})
        t = len(results); pt = (t + ps - 1) // ps
        # ★v4 关键修复：工具自己直接发格式化页面（和翻页走同一条路径，风格 100% 一致）
        page_txt = self._format_sw_page(self._search_sessions.get(event))
        final_txt = tag + f" 💿 软件搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt + _charge_txt
        await self._send_search_page(event, "software", final_txt, ses=self._search_sessions.get(event), note=_charge_txt)
        # 标记 _llm_handled 让 _strip_llm_chitchat_after_tool 清空 LLM 后续多嘴输出
        self._search_sessions.update(event, _llm_handled=True)
        logger.info(f"[暮黎资源] search_software('{software_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个软件结果，当前第 1/{pt} 页。用户的下一步操作（翻页、选数字、选网盘）由 on_any_message 直接处理，无需 LLM 再调用工具。"

    @filter.llm_tool(name="search_movie")
    async def llm_search_movie(self, event: AstrMessageEvent, movie_name: str):
        """搜索影视资源。用户说"找影视/看电影/我想看/影视名"时调用。
        流程：搜索→选序号→获取详情→选[1]在线播放/[2]网盘资源，后续交互由系统自动处理。
        默认源 pdy0（片库注册站，免登录，可能弹图片验证码）；movie_source=old 时用片库主站。
        Args:
            movie_name(string): 影视名称（如"怪物"、"庆余年"）
        """
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, movie_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        _blocked = self._points_guard(event, "movie")
        if _blocked:
            return _blocked
        tag = "【暮黎资源】"
        source = self._movie_source()
        r = await self._search_movie_source(event, movie_name, source)
        st = r.get("status")
        if st == "captcha_sent":
            return (f"{tag} pdy0 搜索需要图片验证码，已把验证码图片发给用户。"
                    f"用户回复验证码后系统会自动继续搜索，不要自行编造结果。")
        if st == "empty":
            return f"{tag} 未找到与「{movie_name}」相关的影视。请换个关键词。"
        if st == "no_client":
            return f"{tag} {r.get('msg')}"
        if st != "ok":
            return f"{tag} 影视搜索失败：{r.get('msg') or '未知错误'}"
        results = r.get("results", [])
        await self._send_movie_results(event, movie_name, results, source)
        t = len(results); pt = (t + 7) // 8
        logger.info(f"[暮黎资源] search_movie({source},'{movie_name}') → {t}条 → 直接 send")
        return f"[已发送给用户] {t} 个影视结果，当前第 1/{pt} 页。用户的下一步操作（选序号/翻页）由 on_any_message 直接处理。"

    @filter.llm_tool(name="search_drama")
    async def llm_search_drama(self, event: AstrMessageEvent, drama_name: str):
        """搜索短剧资源（夸克网盘）。用户说"搜短剧/看短剧/追短剧XX"时调用。
        流程：搜索→选序号→返回夸克网盘资源链接与详情页，后续交互由系统自动处理。
        Args:
            drama_name(string): 短剧名称（如"穿越"、"开局只想苟系统"、"偏偏似你"）
        """
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, drama_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        cfg = self._get_config()
        if isinstance(cfg, dict) and not cfg.get("drama_enabled", True):
            return "【暮黎资源·短剧】短剧搜索已在后台关闭。"
        _blocked = self._points_guard(event, "drama")
        if _blocked:
            return _blocked
        try:
            limit = int(cfg.get("drama_search_limit", 20) or 20) if isinstance(cfg, dict) else 20
        except (TypeError, ValueError):
            limit = 20
        try:
            timeout = int(cfg.get("drama_timeout", 15) or 15) if isinstance(cfg, dict) else 15
        except (TypeError, ValueError):
            timeout = 15
        ps = 8; tag = "【暮黎资源·短剧】"
        try:
            r = await asyncio.to_thread(search_dramas, drama_name, limit, timeout)
        except Exception as e:
            logger.error(f"[暮黎资源] search_drama('{drama_name}') 失败: {e}")
            return f"{tag} 搜索失败：{str(e)[:120]}"
        if not r.get("success"):
            return f"{tag} 搜索失败：{r.get('error', '未知错误')}"
        results = r.get("items", [])
        if not results:
            return f"{tag} 未找到与「{drama_name}」相关的短剧，换个关键词试试？"
        _charge_txt = self._points_charge(event, "drama", drama_name)
        self._drama_sessions.set(event, {
            "stage": "select_drama", "keyword": drama_name, "results": results,
            "page": 0, "page_size": ps, "timeout": timeout,
            "_updated": time.time(), "_llm_handled": True,
        })
        t = len(results); pt = (t + ps - 1) // ps
        page_txt = self._format_drama_page(self._drama_sessions.get(event))
        final_txt = tag + f" 🎬 短剧搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt + _charge_txt
        await self._send_search_page(event, "drama", final_txt, ses=self._drama_sessions.get(event), note=_charge_txt)
        logger.info(f"[暮黎资源] search_drama('{drama_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个短剧结果，当前第 1/{pt} 页。用户的下一步操作（选序号/翻页）由 on_any_message 直接处理。"

    @filter.llm_tool(name="search_novel")
    async def llm_search_novel(self, event: AstrMessageEvent, novel_name: str):
        """搜索小说（so-novel 多源聚合）。仅当用户明确要搜索/阅读/下载小说时调用
        （如"找小说XX""看小说XX""读小说XX"）。介绍/公告类提到"小说"不算搜索，不要调用。
        流程：搜索→选序号→选格式(TXT/EPUB/HTML/PDF)→以文件形式发送，后续交互由系统处理。
        Args:
            novel_name(string): 书名或作者名（如"斗破苍穹"、"天蚕土豆"）
        """
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, novel_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        _blocked = self._points_guard(event, "novel")
        if _blocked:
            return _blocked
        ps = 8; tag = "【暮黎资源·小说】"
        base, token, limit, fmts, timeout, dl_timeout = self._novel_cfg()
        if not requests:
            return f"{tag} 缺少 requests 依赖，无法搜索小说。"
        try:
            results = await asyncio.to_thread(
                search_novels, novel_name, base, token, limit, timeout)
        except NovelApiError as e:
            logger.error(f"[暮黎资源] search_novel('{novel_name}') 失败: {e}")
            return (f"{tag} 小说搜索失败：{e.message}\n"
                    f"💡 请确认 so-novel 已以 Web 模式启动（默认 http://127.0.0.1:7765）。")
        except Exception as e:
            logger.error(f"[暮黎资源] search_novel('{novel_name}') 异常: {e}")
            return f"{tag} 小说搜索异常：{str(e)[:120]}"
        if not results:
            return f"{tag} 未找到与「{novel_name}」相关的小说，换个书名或作者名试试？"
        _charge_txt = self._points_charge(event, "novel", novel_name)
        self._novel_sessions.set(event, {
            "keyword": novel_name, "results": results, "page": 0,
            "page_size": ps, "stage": "select_novel", "_updated": time.time(),
            "_llm_handled": True,
        })
        t = len(results); pt = (t + ps - 1) // ps
        ses_now = self._novel_sessions.get(event)
        page_txt = self._format_novel_page(ses_now)
        final_txt = tag + f" 📚 小说搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt + _charge_txt
        card = ""
        if novel_card_html:
            try:
                card = novel_card_html(ses_now, timeout=SESSION_TIMEOUT, note=_charge_txt)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 小说卡片构建失败，回退文本: {e}")
        await self._send_novel_list(event, ses_now, card, final_txt, t)
        logger.info(f"[暮黎资源] search_novel('{novel_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个小说结果，当前第 1/{pt} 页。用户的下一步操作（选序号/翻页）由 on_any_message 直接处理。"

    # ==================== 新站影视会话状态机 ====================

    async def _handle_movie_new_selection(self, event: AstrMessageEvent, selection: str):
        """新站影视会话状态机：select_movie_new → select_res_type →
        select_play_node / select_pan → 合并转发。"""
        tag = "【暮黎资源】"
        ses = self._movie_sessions_new.get(event)
        if not ses:
            await event.send(MessageChain([Plain(
                f"{tag} 会话已失效，请重新搜索影视。")]))
            return f"{tag} 会话已失效，已提示用户重新搜索。"
        stage = ses.get("stage")
        text = selection.strip()
        source = ses.get("source") or self._movie_source()
        client = self._get_movie_client(source)
        if not client:
            self._movie_sessions_new.delete(event)
            await event.send(MessageChain([Plain(
                f"{tag} 片库主站未配置，请在插件配置填写账号密码或 Cookie。")]))
            return f"{tag} 片库主站未配置，已提示用户。"

        num0 = self._parse_natural_number(text)
        if num0 == 0 or text in ("取消", "不要", "不要了", "算了", "取消搜索"):
            self._movie_sessions_new.delete(event)
            await event.send(MessageChain([Plain(f"{tag} 已取消。")]))
            return f"{tag} 用户取消。"

        # 本条消息由插件直接回复：标记忽略 LLM 的重复输出（工具流程同样适用）
        self._mark_llm_suppress(event)

        # ===== 断点导航：回复「网盘 / 在线播放」可回到对应列表，无需重新搜索 =====
        _nav = text.strip()
        if (not re.fullmatch(r"\d{1,3}", _nav)
                and _nav not in ("下一页", "上一页")
                and not _nav.startswith("跳")):
            if re.search(r"(网盘|夸克|百度|迅雷|阿里|天翼|115|uc)", _nav, re.I):
                _pl = ses.get("resources", {}).get("panlist", [])
                if _pl:
                    _tc = group_panlist_by_type(_pl)
                    self._movie_sessions_new.update(
                        event, stage="select_pan_type", pan_type_counts=_tc,
                        page=0, _llm_handled=True)
                    await self._send_movie_pan_types(event, ses, tag)
                    return f"{tag} 已重新发送网盘分类列表。"
            if re.search(r"(在线|播放|线路|节点)", _nav):
                _nodes = ses.get("resources", {}).get("playlist", [])
                if _nodes:
                    self._movie_sessions_new.update(
                        event, stage="select_play_node", page=0, _llm_handled=True)
                    await self._send_movie_nodes(event, ses, tag)
                    return f"{tag} 已重新发送播放节点列表。"

        # 链接已发送后会话已结束；只有引用列表消息才会恢复断点

        # ===== 阶段1：选择影视 =====
        if stage == "select_movie_new":
            r = ses.get("results", []); p = ses.get("page", 0); ps = ses.get("page_size", 8)
            t = len(r); pt = (t + ps - 1) // ps; st = p * ps; ed = min(st + ps, t); pc = ed - st
            # 翻页
            if text in ("下一页", "上一页") or text.startswith("跳"):
                new_page = p
                if text == "下一页": new_page = min(p + 1, pt - 1)
                elif text == "上一页": new_page = max(0, p - 1)
                elif text.startswith("跳"):
                    m = re.search(r"\d+", text)
                    if m: new_page = max(0, min(pt - 1, int(m.group()) - 1))
                if new_page != p:
                    self._movie_sessions_new.update(event, page=new_page, _llm_handled=True)
                    new_txt = format_movie_list_new(r, ses.get("keyword", ""), new_page, ps)
                    await self._send_search_page(
                        event, "movie_new",
                        tag + f" 🎬 影视搜索结果（第 {new_page+1}/{pt} 页）：\n\n" + new_txt,
                        results=r, keyword=ses.get("keyword", ""),
                        page=new_page, page_size=ps)
                    return f"{tag} 翻页到第{new_page+1}页。等待用户选择。"
            num = num0 if num0 != -2 else pc
            if num < 1 or num > pc:
                await event.send(MessageChain([Plain(f"{tag} 序号超出范围（1-{pc}），请重新输入。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 序号超出范围，已让用户重新输入。等待用户回复。"
            ai = st + num - 1; sel = r[ai]
            await event.send(MessageChain([Plain(f"🎬 已选择：{sel['title']}\n⏳ 正在获取详情与资源，请稍候...")]))
            try:
                detail = await asyncio.to_thread(client.get_detail, sel["dir"], sel["id"])
                resources = await asyncio.to_thread(client.get_resources, sel["dir"], sel["id"])
            except Exception as e:
                self._movie_sessions_new.delete(event)
                await event.send(MessageChain([Plain(f"❌ 获取详情失败：{str(e)[:200]}")]))
                return f"{tag} 获取详情失败。"
            n_play = len(resources.get("playlist", [])); n_pan = len(resources.get("panlist", []))
            # 网盘资源打过期概率标签并按风险排序（高风险置底），写入会话后
            # 展示与后续选择共用同一顺序，避免序号错位
            if n_pan:
                resources["panlist"] = self._annotate_pan_resources(resources["panlist"])
            if n_play == 0 and n_pan == 0:
                self._movie_sessions_new.delete(event)
                await event.send(MessageChain([Plain(f"{tag} 「{sel['title']}」暂无任何资源。")]))
                return f"{tag} 该影视暂无资源。"
            self._movie_sessions_new.set(event, {
                "stage": "select_res_type", "detail": detail, "resources": resources,
                "selected": sel, "page": 0, "source": source,
                "_updated": time.time(), "_llm_handled": True,
            })
            # 详情卡（封面/简介/演职员/剧照）→ 再发资源类型选择
            if movie_detail_card_html:
                try:
                    cover_b64, shot_b64 = await self._detail_media(
                        detail.get("cover", ""), detail.get("screenshots") or [], "")
                    html = movie_detail_card_html(
                        detail, cover_b64=cover_b64, screenshots=shot_b64,
                        source_name="暮黎影视",
                        link_hint="在线播放 / 网盘资源，请选择下方编号")
                    await self._send_detail_card(event, html, "影视详情")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[详情卡] 新站影视详情卡失败，回退文本: {e}")
            await event.send(MessageChain([Plain(tag + "\n" + format_resource_type(detail, resources))]))
            return f"{tag} 已发送资源类型选择（在线播放/网盘）。等待用户回复 1 或 2。"

        # ===== 阶段2：选择资源类型 =====
        if stage == "select_res_type":
            detail = ses.get("detail", {}); resources = ses.get("resources", {})
            num = num0 if num0 != -2 else 1
            if num == 1:
                playlist = resources.get("playlist", [])
                if not playlist:
                    await event.send(MessageChain([Plain(f"{tag} 该影视暂无在线播放节点。")]))
                    return f"{tag} 无在线播放节点。"
                self._movie_sessions_new.update(event, stage="select_play_node", page=0, _llm_handled=True)
                await self._send_movie_nodes(event, ses, tag)
                return f"{tag} 已发送播放节点列表。等待用户选节点。"
            elif num == 2:
                panlist = resources.get("panlist", [])
                if not panlist:
                    await event.send(MessageChain([Plain(f"{tag} 该影视暂无网盘资源。")]))
                    return f"{tag} 无网盘资源。"
                # 按网盘类型分组，先让用户选分类
                type_counts = group_panlist_by_type(panlist)
                self._movie_sessions_new.update(event, stage="select_pan_type",
                                                pan_type_counts=type_counts,
                                                page=0, _llm_handled=True)
                await self._send_movie_pan_types(event, ses, tag)
                return f"{tag} 已发送网盘分类列表（{len(type_counts)}种）。等待用户选分类。"
            else:
                await event.send(MessageChain([Plain(f"{tag} 请回复 1（在线播放）或 2（网盘资源）。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 让用户重新选择资源类型。"

        # ===== 阶段2b：选择网盘分类 =====
        if stage == "select_pan_type":
            type_counts = ses.get("pan_type_counts", [])
            n = len(type_counts)
            if n == 0:
                self._movie_sessions_new.delete(event)
                await event.send(MessageChain([Plain(f"{tag} 网盘分类数据异常，请重新搜索。")]))
                return f"{tag} 网盘分类数据异常。"
            num = num0 if num0 != -2 else 1
            if num < 1 or num > n:
                await event.send(MessageChain([Plain(f"{tag} 序号超出范围（1-{n}），请重新输入。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 分类序号超出范围。"
            sel_type = type_counts[num - 1][0]
            self._movie_sessions_new.update(event, stage="select_pan",
                                            selected_pan_type=sel_type,
                                            page=0, _llm_handled=True)
            panlist = ses.get("resources", {}).get("panlist", [])
            # 遍历检测：并发校验该分类下全部链接，过滤已失效资源
            if self._pan_scan_enabled():
                sel_type, panlist = await self._scan_pan_type(event, ses, sel_type, tag)
                if not sel_type:
                    return f"{tag} 网盘链接遍历检测完成，该分类暂无可直接使用的资源。"
            await self._send_pan_list_card(
                event, ses.get("detail", {}), panlist, 0, sel_type, prefix=tag + "\n")
            return f"{tag} 已发送「{sel_type}」网盘资源列表。等待用户选网盘。"

        # ===== 阶段3a：选择播放节点 =====
        if stage == "select_play_node":
            playlist = ses.get("resources", {}).get("playlist", [])
            n = len(playlist)
            num = num0 if num0 != -2 else n
            if num < 1 or num > n:
                await event.send(MessageChain([Plain(f"{tag} 序号超出范围（1-{n}），请重新输入。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 节点序号超出范围。"
            node = playlist[num - 1]
            detail = ses.get("detail", {})
            eps = node_episodes(node)
            total = len(eps)
            if total > 1:
                # 剧集 / 综艺：发选集卡片（综艺带日期、上中下篇等集名）
                self._movie_sessions_new.update(event, stage="select_episode_new",
                                                selected_node=node, ep_page=0,
                                                _llm_handled=True)
                await self._send_episode_card(event, detail, node, 0,
                                              prefix=tag + "\n")
                return f"{tag} 已发送选集卡片（共{total}集）。等待用户选集。"
            else:
                # 电影：直接获取 m3u8 直链
                play_n = int(eps[0]["n"]) if eps else 1
                await event.send(MessageChain([Plain(f"▶ 已选择：{node['t']}\n⏳ 正在获取播放直链...")]))
                link = await self._get_play_link(client, node["i"], play_n)
                if not link:
                    await event.send(MessageChain([Plain(f"{tag} ❌ 获取播放直链失败，请稍后重试或换一个播放节点。")]))
                    self._movie_sessions_new.delete(event)
                    return f"{tag} 播放直链获取失败。"
                sent, _charged = await self._send_movie_merged(
                    event, detail, link, "在线播放(直链)", send_card=False,
                    charge=not ses.get("_charged"))
                # 会话结束；要换节点请引用「播放节点」那条消息
                self._movie_sessions_new.delete(event)
                if sent:
                    return (f"{tag} 已发送「{detail.get('name', '')}」在线播放。"
                            f"如需换节点，引用播放节点列表再回复序号。")
                return f"{tag} 发送播放链接失败（积分不足或链接异常）。"

        # ===== 阶段3a-2：选集（剧集 / 综艺，支持翻页）=====
        if stage == "select_episode_new":
            node = ses.get("selected_node", {})
            detail = ses.get("detail", {})
            eps = node_episodes(node)
            total = len(eps)
            if total <= 1:
                self._movie_sessions_new.delete(event)
                await event.send(MessageChain([Plain(f"{tag} 该播放节点暂无可用集数，请重新搜索。")]))
                return f"{tag} 选集数据异常。"
            size = episode_page_size(eps)
            pages = episode_pages(total, size)
            page = normalize_ep_page(ses.get("ep_page", 0), total, size)

            # 翻页：只影响展示，不影响回复数字（数字仍是全局集序号）
            if text in ("下一页", "上一页", "末页", "首页", "最新") or text.startswith("跳"):
                new_page = page
                if text == "下一页":
                    new_page = min(page + 1, pages - 1)
                elif text == "上一页":
                    new_page = max(0, page - 1)
                elif text in ("末页", "最新"):
                    new_page = pages - 1
                elif text == "首页":
                    new_page = 0
                elif text.startswith("跳"):
                    m = re.search(r"\d+", text)
                    if m:
                        new_page = max(0, min(pages - 1, int(m.group()) - 1))
                if new_page == page:
                    tip = "已经是最后一页了" if page >= pages - 1 else "已经是第一页了"
                    await event.send(MessageChain([Plain(
                        f"{tag} {tip}（第 {page + 1}/{pages} 页）。")]))
                    self._movie_sessions_new.update(event, _llm_handled=True)
                    return f"{tag} 选集翻页到边界，保持第{page + 1}页。"
                self._movie_sessions_new.update(event, ep_page=new_page,
                                                _llm_handled=True)
                await self._send_episode_card(event, detail, node, new_page,
                                              prefix=tag + "\n")
                return f"{tag} 选集翻到第{new_page + 1}/{pages}页。等待用户选集。"

            num = total if num0 == -2 else num0
            if num < 1 or num > total:
                await event.send(MessageChain([Plain(
                    f"{tag} 集数超出范围（1-{total}），请重新输入。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 集数超出范围。"
            ep = eps[num - 1]
            try:
                play_n = int(ep.get("n") or num)
            except (TypeError, ValueError):
                play_n = num
            ep_label = episode_display_name(ep.get("name"))
            shown = f"第 {num} 集" + (f" · {ep_label}" if ep_label else "")
            await event.send(MessageChain([Plain(f"▶ {shown}\n⏳ 正在获取播放直链...")]))
            link = await self._get_play_link(client, node["i"], play_n)
            if not link:
                await event.send(MessageChain([Plain(f"{tag} ❌ 获取播放直链失败，请稍后重试或换一个播放节点。")]))
                self._movie_sessions_new.delete(event)
                return f"{tag} 播放直链获取失败。"
            sent, _charged = await self._send_movie_merged(
                event, detail, link, f"在线播放({shown} · 直链)", send_card=False,
                charge=not ses.get("_charged"))
            # 会话结束；要换集请引用「选集」那条消息
            self._movie_sessions_new.delete(event)
            if sent:
                return (f"{tag} 已发送「{detail.get('name', '')}」{shown}在线播放。"
                        f"如需换集，引用选集列表再回复集数。")
            return f"{tag} 发送播放链接失败（积分不足或链接异常）。"

        # ===== 阶段3b：选择网盘 =====
        if stage == "select_pan":
            all_panlist = ses.get("resources", {}).get("panlist", [])
            sel_type = ses.get("selected_pan_type", "")
            # 按已选分类过滤
            panlist = [p for p in all_panlist if p.get("type", "") == sel_type] if sel_type else all_panlist
            p = ses.get("page", 0); ps = 12
            t = len(panlist); pt = (t + ps - 1) // ps; st = p * ps; ed = min(st + ps, t); pc = ed - st
            # 翻页
            if text in ("下一页", "上一页") or text.startswith("跳"):
                new_page = p
                if text == "下一页": new_page = min(p + 1, pt - 1)
                elif text == "上一页": new_page = max(0, p - 1)
                elif text.startswith("跳"):
                    m = re.search(r"\d+", text)
                    if m: new_page = max(0, min(pt - 1, int(m.group()) - 1))
                if new_page != p:
                    self._movie_sessions_new.update(event, page=new_page, _llm_handled=True)
                    await self._send_pan_list_card(
                        event, ses.get("detail", {}), panlist, new_page,
                        sel_type, prefix=tag + "\n")
                    return f"{tag} 网盘翻页到第{new_page+1}页。等待用户选择。"
            num = num0 if num0 != -2 else pc
            if num < 1 or num > pc:
                await event.send(MessageChain([Plain(f"{tag} 序号超出范围（1-{pc}），请重新输入。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 网盘序号超出范围。"
            ai = st + num - 1; pan = panlist[ai]
            link = pan.get("url", "")
            detail = ses.get("detail", {})
            pwd = extract_pwd(link)
            pwd_hint = f"（提取码：{pwd}）" if pwd else ""
            risk = self._pan_risk_text(pan)
            await event.send(MessageChain([Plain(
                f"📁 已选择：{pan.get('type', '')} - {pan.get('name', '')[:30]}{pwd_hint}\n"
                f"⏳ 正在校验链接有效性..." + (f"\n{risk}" if risk else ""))]))
            status = await self._check_selected_pan(pan)
            if status == "dead":
                await self._handle_dead_pan(event, ses, pan, link)
                return f"{tag} 该网盘资源已确认失效，已记录并重新推荐其他资源。"
            sent, _charged = await self._send_movie_merged(
                event, detail, link, "网盘下载", send_card=False,
                charge=not ses.get("_charged"))
            # 会话结束；要换网盘请引用「网盘资源」那条消息（直接发序号不续接）
            self._movie_sessions_new.delete(event)
            if sent:
                return (f"{tag} 已发送「{detail.get('name', '')}」网盘链接。"
                        f"若链接失效，引用网盘列表回复其他序号即可换资源。")
            return f"{tag} 发送网盘链接失败（积分不足）。"

        await event.send(MessageChain([Plain(f"{tag} 当前会话状态异常，请重新搜索影视。")]))
        return f"{tag} 未知会话状态，已提示用户重新搜索。"

    # ——— 消息发送：合并转发 / Markdown 排版 / 文本+图片 三级降级 ———
    # AstrBot 文档：Node/Nodes 合并转发「大多数平台都不支持，当前适配情况：OneBot v11」。
    # 因此发送顺序（优先级从高到低）：
    #   1) 合并聊天记录(合并转发) —— 仅 aiocqhttp(OneBot v11) 群聊
    #   2) Markdown 排版渲染 —— QQ官方/钉钉/Telegram/飞书/KOOK/Slack/企微 等原生渲染 markdown
    #   3) 普通文本 + 截图/封面 —— 个人微信等其余平台最后兜底
    # 实现：全部「群聊资源结果」出口统一走 _send_resource_result，避免每处重复实现。
    _MERGED_FORWARD_PLATFORMS = {"aiocqhttp", "onebot", "onebot11"}
    # 原生渲染 Markdown 的平台（MessageChain.use_markdown_ 或 Plain→markdown 自动转换）
    _MD_RENDER_PLATFORMS = {
        "qq_official", "dingtalk", "telegram", "lark", "kook", "slack",
        "wecom", "wecom_ai_bot",
    }

    def _platform_name(self, event: AstrMessageEvent) -> str:
        try:
            return (event.get_platform_name() or "").strip().lower()
        except Exception:
            return ""

    def _supports_merged_forward(self, event: AstrMessageEvent) -> bool:
        """当前平台是否支持「合并聊天记录/合并转发」(Node/Nodes)。"""
        name = self._platform_name(event)
        if name in self._MERGED_FORWARD_PLATFORMS:
            return True
        try:
            pid = (event.get_platform_id() or "").strip().lower()
        except Exception:
            pid = ""
        return pid in self._MERGED_FORWARD_PLATFORMS

    def _supports_markdown(self, event: AstrMessageEvent) -> bool:
        """当前平台是否支持 Markdown 渲染。"""
        name = self._platform_name(event)
        if name in self._MD_RENDER_PLATFORMS:
            return True
        try:
            pid = (event.get_platform_id() or "").strip().lower()
        except Exception:
            pid = ""
        return pid in self._MD_RENDER_PLATFORMS

    @staticmethod
    def _mdify(text: str) -> str:
        """把普通文本转成兼容多平台 Markdown 的排版：
        - 首行标题加粗（首行较短时）
        - URL 用反引号包成代码样式（QQ官方/Telegram/KOOK/Slack/飞书/钉钉均支持行内代码）
        """
        lines = (text or "").split("\n")
        if lines and 0 < len(lines[0].strip()) <= 60:
            lines[0] = f"**{lines[0].strip()}**"
        md = "\n".join(lines)
        md = re.sub(r"(https?://\S+)", r"`\1`", md)
        return md

    def _download_image(self, url: str, referer: str = "") -> str | None:
        """下载一张图片到临时文件，返回本地路径；失败返回 None。"""
        if not url or not requests:
            return None
        try:
            if not referer and url.startswith("http"):
                referer = "/".join(url.split("/")[:3]) + "/"
            ir = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer},
                              timeout=15)
            if ir.status_code == 200:
                fd, ip = tempfile.mkstemp(suffix=".jpg", prefix="mly_")
                os.close(fd)
                with open(ip, "wb") as f:
                    f.write(ir.content)
                return ip
        except Exception:
            pass
        return None

    def _image_b64(self, url: str, referer: str = "",
                   max_width: int = 300, timeout: float = 15) -> str:
        """下载图片并压成 JPEG base64，供 HTML 详情卡内嵌；失败返回空串。"""
        if not url or not requests:
            return ""
        try:
            if not referer and url.startswith("http"):
                referer = "/".join(url.split("/")[:3]) + "/"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0",
                                           "Referer": referer}, timeout=timeout)
            if r.status_code != 200 or len(r.content) < 512:
                return ""
            try:
                from PIL import Image, ImageOps
            except ImportError:
                return ""
            img = Image.open(io.BytesIO(r.content))
            img = ImageOps.exif_transpose(img).convert("RGB")
            w, h = img.size
            if w > max_width:
                img = img.resize((max_width, max(1, int(h * max_width / w))),
                                 Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[详情卡] 图片处理失败: {e}")
            return ""

    async def _prefetch_covers(self, items: list, referer: str = "",
                               max_width: int = 140, limit: int = 8) -> dict:
        """并发下载列表页当前页的封面，返回 {原图 URL: base64}。

        卡片渲染是同步线程，不能在里面下载网络图，所以统一在发送前预取。
        单张失败只影响自己，卡片会自动退回渐变色块。
        """
        urls = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            u = str(it.get("cover") or "").strip()
            if u and u not in urls:
                urls.append(u)
        urls = urls[:max(0, int(limit or 8))]
        if not urls or not requests:
            return {}

        async def _one(u: str):
            try:
                b64 = await asyncio.to_thread(
                    self._image_b64, u, referer, max_width, 8)
                return u, b64
            except Exception:  # noqa: BLE001
                return u, ""

        pairs = await asyncio.gather(*(_one(u) for u in urls))
        return {u: b for u, b in pairs if b}

    async def _detail_media(self, cover: str, screenshots: list | None,
                            referer: str = "", *, max_shots: int = 3):
        """下载详情卡需要的封面与截图，返回 (封面 base64, [截图 base64])。"""
        shots = [u for u in (screenshots or []) if u and u != cover][:max_shots]

        async def _one(u, w):
            try:
                return await asyncio.to_thread(self._image_b64, u, referer, w, 10)
            except Exception:  # noqa: BLE001
                return ""

        tasks = ([_one(cover, 240)] if cover else [""])
        tasks += [_one(u, 300) for u in shots]
        vals = await asyncio.gather(*tasks)
        cover_b64 = vals[0] if cover else ""
        shot_b64 = [x for x in vals[1:] if x]
        return cover_b64, shot_b64

    @staticmethod
    def _link_text(title: str, pan: str, url: str, *, code: str = "",
                   extra: str = "", icon: str = "📥") -> str:
        """链接单独发送时的纯文本（详情信息已在卡片里，不重复长简介）。"""
        lines = [f"📦 {title}", f"{icon} {pan}"]
        if extra:
            lines.append(extra)
        lines.append(url or "（链接获取失败）")
        if code:
            lines.append(f"🔑 提取码：{code}")
        return "\n".join(lines)

    async def _send_detail_card(self, event: AstrMessageEvent, html: str,
                                label: str = "详情") -> bool:
        """尝试把详情页渲染成图片；任何失败都返回 False，由调用方走原文本兜底。"""
        if not html or render_list_card is None:
            return False
        try:
            img = await asyncio.to_thread(render_list_card, html)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[详情卡] {label} 渲染异常，回退文本: {e}")
            return False
        if not img:
            return False
        try:
            if await self._send_card_image(event, img, f"暮黎_{label}.jpg"):
                logger.info(f"[详情卡] {label} 已发图片（{len(img) // 1024}KB）")
                return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[详情卡] {label} 发送异常，回退文本: {e}")
        return False

    async def _send_game_detail_card(self, event: AstrMessageEvent, detail: dict,
                                     meta: dict | None = None, *,
                                     link_hint: str = "选好网盘后会单独发送下载链接") -> bool:
        if not game_detail_card_html:
            return False
        try:
            # 头部用搜索列表里的游戏小图标（不是详情页第一张截图）
            icon_url = str((meta or {}).get("cover") or "").strip()
            _cover_b64, shot_b64 = await self._detail_media(
                icon_url, detail.get("screenshots") or [],
                GAME_BASE_URL + "/")
            html = game_detail_card_html(
                detail, cover_b64=_cover_b64, screenshots=shot_b64,
                meta=meta or {}, source_name="暮黎游戏", link_hint=link_hint)
            return await self._send_detail_card(event, html, "游戏详情")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[详情卡] 游戏详情卡失败，回退旧样式: {e}")
            return False

    async def _send_software_detail_card(self, event: AstrMessageEvent, detail: dict,
                                         meta: dict | None = None, *,
                                         link_hint: str = "选好网盘后会单独发送下载链接") -> bool:
        if not software_detail_card_html:
            return False
        try:
            cover_b64, shot_b64 = await self._detail_media(
                detail.get("cover", ""), detail.get("screenshots") or [],
                SW_BASE_URL + "/")
            html = software_detail_card_html(
                detail, cover_b64=cover_b64, screenshots=shot_b64,
                meta=meta or {}, source_name="暮黎软件", link_hint=link_hint)
            return await self._send_detail_card(event, html, "软件详情")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[详情卡] 软件详情卡失败，回退旧样式: {e}")
            return False

    async def _send_game_link_menu(self, event: AstrMessageEvent, detail: dict,
                                   selected: dict, links: list) -> None:
        """选择游戏后：先发详情卡，再发网盘列表（此时还没选网盘）。"""
        await self._send_game_detail_card(event, detail, selected)
        name = detail.get("name") or (selected or {}).get("title") or "游戏"
        txt = f"📦 {name}\n" + "=" * 30 + f"\n共 {len(links)} 个网盘：\n\n"
        for i, lk in enumerate(links, 1):
            extra = ""
            if lk.get("code"):
                extra += f"  提取码:{lk['code']}"
            if lk.get("password"):
                extra += f"  游戏密码:{lk['password']}"
            txt += (f"{emoji_index(i, len(links))} "
                    f"{GAME_PAN_ICONS.get(lk['pan'], '📥')} {lk['pan']}{extra}\n")
        txt += (f"\n请回复数字或网盘名选择网盘（1-{len(links)}），"
                f"选好后发送下载链接；回复 0 取消。")
        hint = f"💡 引用本条消息可换网盘 · {name}"
        await event.send(MessageChain([Plain(txt + "\n" + hint)]))
        ses = self._sessions.get(event)
        if ses:
            try:
                snap = copy.deepcopy(ses)
            except Exception:  # noqa: BLE001
                snap = dict(ses)
            snap["stage"] = "select_link"
            self._register_breakpoint(event, "game", snap, [hint, txt])

    async def _send_software_link_menu(self, event: AstrMessageEvent, detail: dict,
                                       selected: dict, links: list) -> None:
        """选择软件后：先发详情卡，再发网盘列表（此时还没选网盘）。"""
        await self._send_software_detail_card(event, detail, selected)
        name = detail.get("name") or (selected or {}).get("title") or "资源"
        txt = f"📦 {name}\n" + "=" * 30 + f"\n共 {len(links)} 个网盘：\n\n"
        for i, lk in enumerate(links, 1):
            txt += (f"{emoji_index(i, len(links))} "
                    f"{SW_DISK_ICONS.get(lk['pan'], '📥')} {lk['pan']}\n")
        txt += (f"\n请回复数字或网盘名选择网盘（1-{len(links)}），"
                f"选好后发送下载链接；回复 0 取消。")
        hint = f"💡 引用本条消息可换网盘 · {name}"
        await event.send(MessageChain([Plain(txt + "\n" + hint)]))
        ses2 = self._search_sessions.get(event)
        if ses2:
            try:
                snap = copy.deepcopy(ses2)
            except Exception:  # noqa: BLE001
                snap = dict(ses2)
            snap["stage"] = "select_link"
            self._register_breakpoint(event, "software", snap, [hint, txt])

    async def _send_download_link(self, event: AstrMessageEvent, title: str,
                                  pan: str, url: str, *, code: str = "",
                                  password: str = "", source_name: str = "暮黎资源",
                                  kind: str = "", charge: bool = True) -> bool:
        """网盘选好后只发链接（群聊优先合并转发，私聊普通文本）。

        charge=False 用于「断点续选」：同一会话已经扣过费，换网盘不再重复扣。
        """
        note = ""
        if kind and charge:
            ok, note = self._points_final_charge(event, kind, title)
            if not ok:
                await event.send(MessageChain([Plain(note)]))
                return False
        extra = f"🔒 游戏密码：{password}" if password else ""
        text = self._link_text(title, pan, url, code=code, extra=extra) + note
        if (event.get_group_id() and self._supports_merged_forward(event)
                and Nodes and Node):
            try:
                sid = event.get_self_id()
                nd = Nodes([])
                nd.nodes.append(Node(uin=sid, name=source_name, content=[Plain(text)]))
                await event.send(MessageChain([nd]))
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[下载链接] 合并转发失败，改发文本: {e}")
        await event.send(MessageChain([Plain(text)]))
        return True

    async def _send_text_with_images(self, event: AstrMessageEvent, text: str,
                                     images: list, referer: str = ""):
        """兜底发送：普通文本 + 若干截图/封面。发送失败再降级为纯文本。发完清理临时文件。"""
        chain = [Plain(text)]
        temp_files = []
        for u in (images or [])[:6]:
            ip = await asyncio.to_thread(self._download_image, u, referer)
            if ip:
                temp_files.append(ip)
                chain.append(ImageComponent(file=ip))
        try:
            await event.send(MessageChain(chain))
        except Exception as e:
            logger.warning(f"[暮黎资源] 图片消息发送失败，降级纯文本: {e}")
            try:
                await event.send(MessageChain([Plain(text)]))
            except Exception:
                pass
        for p in temp_files:
            try:
                os.unlink(p)
            except Exception:
                pass

    async def _send_resource_result(self, event: AstrMessageEvent, *, text: str,
                                    images: list = None, referer: str = "",
                                    source_name: str = "暮黎资源"):
        """统一资源结果发送（优先级从高到低）：
        1. 合并聊天记录/合并转发 —— 仅 OneBot v11 (aiocqhttp) 群聊
        2. Markdown 排版渲染 —— QQ官方/钉钉/Telegram/飞书/KOOK/Slack/企微
        3. 普通文本 + 截图/封面 —— 最后兜底（个人微信等）

        text 为纯文本版（无 markdown 标记，用于兜底）；markdown 版由 _mdify 生成。
        """
        images = images or []
        # 1) 合并转发（仅 OneBot v11 群聊）
        if event.get_group_id() and self._supports_merged_forward(event) and Nodes and Node:
            try:
                sid = event.get_self_id()
                nd = Nodes([])
                nd.nodes.append(Node(uin=sid, name=source_name, content=[Plain(text)]))
                temp_files = []
                for u in images[:6]:
                    ip = await asyncio.to_thread(self._download_image, u, referer)
                    if ip:
                        temp_files.append(ip)
                        nd.nodes.append(Node(uin=sid, name=source_name,
                                             content=[ImageComponent(file=ip)]))
                await event.send(MessageChain([nd]))
                logger.info(f"[暮黎资源] 合并转发已发送 ({source_name}) +{len(temp_files)}图")
                for p in temp_files:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
                return
            except Exception as e:
                logger.warning(f"[暮黎资源] 合并转发失败，降级重发: {e}")
        # 2) Markdown 渲染平台
        if self._supports_markdown(event):
            md = self._mdify(text)
            chain = [Plain(md)]
            temp_files = []
            for u in images[:6]:
                ip = await asyncio.to_thread(self._download_image, u, referer)
                if ip:
                    temp_files.append(ip)
                    chain.append(ImageComponent(file=ip))
            try:
                await event.send(MessageChain(chain=chain, use_markdown_=True))
                logger.info(f"[暮黎资源] Markdown 消息已发送 ({source_name}) +{len(temp_files)}图")
                for p in temp_files:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
                return
            except Exception as e:
                logger.warning(f"[暮黎资源] Markdown 发送失败，降级普通文本: {e}")
        # 3) 普通文本 + 图片（兜底）
        await self._send_text_with_images(event, text, images, referer)

    async def _send_movie_links(self, event: AstrMessageEvent, detail: dict,
                                link: str, link_label: str, note: str = "") -> None:
        """链接单独发送：QQ 群走合并转发，其他平台走普通文本。"""
        if not link:
            return
        name = (detail or {}).get("name") or "影视"
        pwd = extract_pwd(link)
        lines = [f"🎬 《{name}》", f"▶ {link_label}"]
        if pwd:
            lines.append(f"🔑 提取码：{pwd}")
        lines.append(link)
        text = "\n".join(lines) + note
        if (event.get_group_id() and self._supports_merged_forward(event)
                and Nodes and Node):
            try:
                sid = event.get_self_id()
                nd = Nodes([])
                nd.nodes.append(Node(uin=sid, name="暮黎影视", content=[Plain(text)]))
                await event.send(MessageChain([nd]))
                return
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[详情卡] 链接合并转发失败，改发文本: {e}")
        await event.send(MessageChain([Plain(text)]))

    async def _send_movie_merged(self, event: AstrMessageEvent, detail: dict,
                                 link: str, link_label: str,
                                 referer: str = "", *, charge: bool = True,
                                 send_card: bool = True) -> tuple:
        """影视结果：默认先发 HTML 详情卡，再单独发播放/下载链接。

        send_card=False 时只发链接——选择影视时已经发过详情卡，
        选播放节点 / 网盘后再发一次会造成同一张详情卡重复出现。

        返回 (是否已发送, 本次是否执行了扣费)，供「断点续选」判断要不要重复扣费。
        """
        if not link:
            return False, False
        text = build_merged_text(detail, link, link_label)
        name = (detail or {}).get("name") or "影视"
        note = ""
        if charge:
            ok, note = self._points_final_charge(event, "movie", name)
            if not ok:
                await event.send(MessageChain([Plain(note)]))
                return False, False
        if not send_card:
            await self._send_movie_links(event, detail, link, link_label, note=note)
            return True, bool(charge)
        cover = detail.get("cover", "")
        shots = [u for u in (detail.get("screenshots") or [])
                 if u and u != cover]
        card_sent = False
        if movie_detail_card_html and render_list_card:
            try:
                cover_b64 = await asyncio.to_thread(
                    self._image_b64, cover, referer, 240) if cover else ""
                shot_b64 = []
                for u in shots[:3]:
                    b = await asyncio.to_thread(self._image_b64, u, referer, 300)
                    if b:
                        shot_b64.append(b)
                html = movie_detail_card_html(
                    detail, cover_b64=cover_b64, screenshots=shot_b64,
                    source_name="暮黎影视",
                    link_hint="播放 / 下载链接已单独发送")
                img = await asyncio.to_thread(render_list_card, html)
                if img and await self._send_card_image(event, img, "暮黎_影视详情.jpg"):
                    card_sent = True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[详情卡] 影视详情卡构建/发送失败，回退旧样式: {e}")
        if card_sent:
            await self._send_movie_links(event, detail, link, link_label, note=note)
            return True, bool(charge)
        imgs = ([cover] if cover else []) + [u for u in shots[:3] if u]
        await self._send_resource_result(event, text=text + note,
                                         images=imgs,
                                         referer=referer, source_name="暮黎影视")
        return True, bool(charge)

    async def _get_play_link(self, client, node_i: str, ep: int) -> str:
        """健壮获取播放直链：先取，失败则强制刷新登录再取一次。
        返回空串表示确实拿不到（调用方应提示用户，而非发登录墙网站链接）。"""
        m3u8 = await asyncio.to_thread(client.get_play_m3u8, node_i, ep)
        if m3u8:
            return m3u8
        logger.warning("[暮黎资源] 首次取 m3u8 失败，强制刷新登录重试")
        client._relogin_on_fail()
        return await asyncio.to_thread(client.get_play_m3u8, node_i, ep)

    async def llm_paginate_results(self, event: AstrMessageEvent, action: str):
        """翻页工具。用户说"下一页"/"上一页"/"跳转N"时**必须**调用此工具。

        重要设计：
        - 此工具**只返回**下一页/上一页的原始数据（带序号），**不主动 send**
        - LLM 拿到返回数据后**自己排版**（加 emoji、改格式都行）
        - 这样可以保证翻页风格与第一页一致（同样由 LLM 美化）

        Args:
            action(string): "下一页" / "上一页" / "跳转3"（N为数字）
        """
        tag = "【暮黎资源】"

        def _do_paginate(ses: dict) -> tuple | None:
            ps = ses.get("page_size", 8); t = len(ses["results"])
            cur = ses.get("page", 0); pt = (t + ps - 1) // ps
            new_page = cur
            if "上一页" in action or action == "prev":
                new_page = max(0, cur - 1)
            elif "下一页" in action or action == "next":
                new_page = cur + 1 if (cur + 1) * ps < t else cur
            elif "跳" in action:
                m = re.search(r'(\d+)', action)
                if m: new_page = max(0, min(pt - 1, int(m.group(1)) - 1))
            else:
                m = re.search(r'(\d+)', action)
                if m: new_page = max(0, min(pt - 1, int(m.group(1)) - 1))
            return cur, new_page, pt, ps

        # ——— 游戏会话 ———
        ses = self._sessions.get(event)
        if ses and ses.get("stage") in ("select_game", "select_link"):
            ret = _do_paginate(ses)
            if ret is None: return f"{tag} 无法解析翻页指令「{action}」。"
            cur, new_page, pt, ps = ret
            if new_page == cur:
                return f"{tag} 已到第{cur+1}页，没有{action}了。"
            ses["page"] = new_page; ses["_updated"] = time.time()
            page_txt = self._format_game_page(ses)
            t = len(ses["results"])
            final_txt = tag + f" 🎮 游戏搜索结果（共 {t} 个，第 {new_page+1}/{pt} 页）：\n\n" + page_txt
            await self._send_search_page(event, "game", final_txt, ses=ses)
            self._sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 翻页 游戏 第{cur+1}→{new_page+1}页 (共{t}条) → 直接 send")
            return f"[已发送给用户] 第 {new_page+1}/{pt} 页，共 {t} 个结果。用户后续操作由 on_any_message 处理。"

        # ——— 软件会话 ———
        ses2 = self._search_sessions.get(event)
        if ses2 and ses2.get("stage") in ("select_software", "select_link"):
            ret = _do_paginate(ses2)
            if ret is None: return f"{tag} 无法解析翻页指令。"
            cur, new_page, pt, ps = ret
            if new_page == cur:
                return f"{tag} 已到第{cur+1}页，没有{action}了。"
            ses2["page"] = new_page; ses2["_updated"] = time.time()
            page_txt = self._format_sw_page(ses2)
            t = len(ses2["results"])
            final_txt = tag + f" 💿 软件搜索结果（共 {t} 个，第 {new_page+1}/{pt} 页）：\n\n" + page_txt
            await self._send_search_page(event, "software", final_txt, ses=ses2)
            self._search_sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 翻页 软件 第{cur+1}→{new_page+1}页 (共{t}条) → 直接 send")
            return f"[已发送给用户] 第 {new_page+1}/{pt} 页，共 {t} 个结果。用户后续操作由 on_any_message 处理。"

        # ——— 影视会话 ———
        ses3 = self._movie_sessions.get(event)
        if ses3 and ses3.get("stage") == "select_movie":
            ret = _do_paginate(ses3)
            if ret is None: return f"{tag} 无法解析翻页指令。"
            cur, new_page, pt, ps = ret
            if new_page == cur:
                return f"{tag} 已到第{cur+1}页，没有{action}了。"
            ses3["page"] = new_page; ses3["_updated"] = time.time()
            page_txt = self._format_mv_page(ses3)
            t = len(ses3["results"])
            final_txt = tag + f" 🎬 影视搜索结果（共 {t} 个，第 {new_page+1}/{pt} 页）：\n\n" + page_txt
            await self._send_search_page(event, "movie", final_txt, ses=ses3)
            self._movie_sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 翻页 影视 第{cur+1}→{new_page+1}页 (共{t}条) → 直接 send")
            return f"[已发送给用户] 第 {new_page+1}/{pt} 页，共 {t} 个结果。用户后续操作由 on_any_message 处理。"

        # ——— 新站影视·选集翻页 ———
        ses5 = self._movie_sessions_new.get(event)
        if ses5 and ses5.get("stage") == "select_episode_new":
            node = ses5.get("selected_node", {})
            eps = node_episodes(node)
            total = len(eps)
            size = episode_page_size(eps)
            pages = episode_pages(total, size)
            cur = normalize_ep_page(ses5.get("ep_page", 0), total, size)
            new_page = cur
            if "上一页" in action or action == "prev":
                new_page = max(0, cur - 1)
            elif "下一页" in action or action == "next":
                new_page = min(cur + 1, pages - 1)
            elif "末页" in action:
                new_page = pages - 1
            elif "最新" in action:
                new_page = pages - 1
            elif "首页" in action:
                new_page = 0
            elif "跳" in action:
                m = re.search(r'(\d+)', action)
                if m:
                    new_page = max(0, min(pages - 1, int(m.group(1)) - 1))
            if new_page == cur:
                return f"{tag} 选集已经是第{cur+1}/{pages}页，没有{action}了。"
            self._movie_sessions_new.update(event, ep_page=new_page, _llm_handled=True)
            await self._send_episode_card(event, ses5.get("detail", {}), node,
                                          new_page, prefix=tag + "\n")
            logger.info(f"[暮黎资源] 翻页 新站选集 第{cur+1}→{new_page+1}页")
            return (f"[已发送给用户] 选集第 {new_page+1}/{pages} 页（共{total}集）。"
                    "用户后续操作由 on_any_message 处理。")

        # ——— 新站影视会话 ———
        ses4 = self._movie_sessions_new.get(event)
        if ses4 and ses4.get("stage") in ("select_movie_new", "select_pan"):
            ps = 12 if ses4.get("stage") == "select_pan" else ses4.get("page_size", 8)
            sel_type = ses4.get("selected_pan_type", "")
            if ses4.get("stage") == "select_movie_new":
                ps = ses4.get("page_size", 8)
                r = ses4.get("results", []); kw = ses4.get("keyword", "")
            else:
                all_pan = ses4.get("resources", {}).get("panlist", [])
                r = [p for p in all_pan if p.get("type", "") == sel_type] if sel_type else all_pan
                kw = ""
            t = len(r); cur = ses4.get("page", 0); pt = (t + ps - 1) // ps
            new_page = cur
            if "上一页" in action or action == "prev":
                new_page = max(0, cur - 1)
            elif "下一页" in action or action == "next":
                new_page = min(cur + 1, pt - 1) if (cur + 1) * ps < t else cur
            elif "跳" in action:
                m = re.search(r'(\d+)', action)
                if m: new_page = max(0, min(pt - 1, int(m.group(1)) - 1))
            if new_page == cur:
                return f"{tag} 已到第{cur+1}页，没有{action}了。"
            self._movie_sessions_new.update(event, page=new_page, _llm_handled=True)
            if ses4.get("stage") == "select_movie_new":
                page_txt = format_movie_list_new(r, kw, new_page, ps)
                await self._send_search_page(
                    event, "movie_new", tag + "\n" + page_txt,
                    results=r, keyword=kw, page=new_page, page_size=ps)
            else:
                await self._send_pan_list_card(
                    event, ses4.get("detail", {}), r, new_page,
                    sel_type, prefix=tag + "\n")
            logger.info(f"[暮黎资源] 翻页 新站影视 第{cur+1}→{new_page+1}页")
            return f"[已发送给用户] 第 {new_page+1}/{pt} 页。用户后续操作由 on_any_message 处理。"

        return f"{tag} 当前没有活跃的搜索结果会话，无法翻页。请先调 search_game / search_software / search_movie 搜索。"

    async def llm_select_search_result(self, event: AstrMessageEvent, selection: str):
        """用户选择搜索结果后调用，获取资源详情和下载链接。

        Args:
            selection(string): 用户的选择（数字如"1"、"2"，或"第一个"、"第二个"等中文序数）
        """
        tag = "【暮黎资源】"
        # ★新站影视会话（片库）：独立状态机，优先处理
        ses_mn = self._movie_sessions_new.get(event)
        if ses_mn and ses_mn.get("stage") in ("select_movie_new", "select_res_type",
                                               "select_pan_type", "select_play_node", "select_episode_new", "select_pan"):
            return await self._handle_movie_new_selection(event, selection)
        # ★影视会话：走 on_any_message 的 session_waiter，但 LLM 也可能先调用到此工具
        #  → 直接在这里处理影视选择，插件直接发集数/线路列表给用户
        ses_mv = self._movie_sessions.get(event)
        if ses_mv and ses_mv.get("stage") == "select_movie":
            movie_ses = ses_mv
        elif ses_mv and ses_mv.get("stage") in ("select_episode", "select_source"):
            movie_ses = ses_mv
        else:
            movie_ses = None
        if movie_ses:
            # ★直接处理影视选择（避免 LLM 编造搜索结果）
            r = movie_ses.get("results", [])
            p = movie_ses.get("page", 0)
            ps = movie_ses.get("page_size", 8)
            t = len(r)
            st = p * ps
            ed = min(st + ps, t)
            number = self._parse_natural_number(selection)
            if number == -2:
                number = ed - st
            if number < 1 or number > (ed - st):
                await event.send(MessageChain([Plain(f"{tag} 序号超出范围（1-{ed-st}），请重新输入。回复0取消。")]))
                self._movie_sessions.update(event, _llm_handled=True)
                return f"{tag} 序号超出范围，已让用户重新输入。**不要再调用任何工具，等待用户回复数字。**"
            ai = st + number - 1
            sel = r[ai]
            await event.send(MessageChain([Plain(f"🎬 已选择：{sel['title']}\n⏳ 正在获取详情，请稍候...")]))
            try:
                detail = await asyncio.to_thread(get_movie_detail, sel["url"])
            except Exception as e:
                await event.send(MessageChain([Plain(f"❌ 获取详情失败：{str(e)[:200]}")]))
                self._movie_sessions.delete(event)
                return f"{tag} 获取详情失败。"
            if not detail.get("sources"):
                await event.send(MessageChain([Plain("😕 该影视暂无播放线路。")]))
                self._movie_sessions.delete(event)
                return f"{tag} 该影视暂无播放线路。"
            self._movie_sessions.set(event, {
                "stage": "select_movie_done",
                "keyword": movie_ses.get("keyword", ""),
                "selected": sel,
                "detail": detail,
                "_updated": time.time(),
                "_llm_handled": True,
            })
            if detail.get("is_series") and detail.get("episodes"):
                eps_text = format_episodes(detail, max_show=30)
                await event.send(MessageChain([Plain(eps_text)]))
                self._movie_sessions.update(event, stage="select_episode")
                return f"{tag} 已发送集数列表给用户。用户正在选集，**不要再调用任何工具，等待用户回复数字。**"
            else:
                src_text = format_sources(detail, page=0, page_size=15)
                await event.send(MessageChain([Plain(src_text)]))
                self._movie_sessions.update(event, stage="select_source")
                return f"{tag} 已发送播放线路列表给用户。**不要再调用任何工具，等待用户回复数字。**"

        number = self._parse_natural_number(selection)
        # 游戏会话
        ses = self._sessions.get(event)
        if ses and ses.get("stage") == "select_game":
            r = ses["results"]; p = ses.get("page",0); ps = ses.get("page_size",8); t = len(r)
            st = p*ps; ed = min(st+ps,t); pc = ed-st
            if number == -2: number = len(r) - (p*ps)
            if number < 1 or number > pc:
                return f"{tag} 序号超出范围（1-{pc}），请重新输入。回复0取消。"
            ai = st+number-1; sel = r[ai]
            logger.info(f"[暮黎资源] 用户选择游戏#{number}: {sel['title']}")
            self._sessions.update(event, selected_index=ai, stage="fetching")
            try: detail = await self._fetch_game_detail(event, sel["url"])
            except Exception as e:
                self._sessions.delete(event)
                logger.error(f"[暮黎资源] 获取游戏详情失败: {e}")
                return f"{tag} 获取详情失败：{str(e)[:100]}"
            if detail.get("need_login"):
                self._sessions.delete(event)
                msg = self._game_login_hint()
                await event.send(MessageChain([Plain(msg)]))
                return f"{tag} 已提示用户 Cookie 失效，请刷新。不要再调用任何工具。"
            if not detail.get("download_links"):
                self._sessions.delete(event)
                return f"{tag} 「{sel['title']}」暂无下载链接。"
            self._sessions.update(event, game_detail=detail, stage="select_link")
            await self._send_game_link_menu(event, detail, sel, detail["download_links"])
            self._sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 游戏 '{sel['title']}' → {len(detail['download_links'])}个网盘")
            return f"{tag} 已发送游戏详情卡和网盘列表给用户。请等待用户回复数字或网盘名，**不要**自行调用 select_download_link。"

        # 软件会话
        ses2 = self._search_sessions.get(event)
        if ses2 and ses2.get("stage") == "select_software":
            r = ses2["results"]; p = ses2.get("page",0); ps = ses2.get("page_size",8); t = len(r)
            st = p*ps; ed = min(st+ps,t); pc = ed-st
            if number == -2: number = len(r) - (p*ps)
            if number < 1 or number > pc:
                return f"{tag} 序号超出范围（1-{pc}），请重新输入。回复0取消。"
            ai = st+number-1; sel = r[ai]
            logger.info(f"[暮黎资源] 用户选择软件#{number}: {sel['title']}")
            self._search_sessions.update(event, selected_index=ai, stage="fetching")
            try: detail = await asyncio.to_thread(get_search_detail, sel["url"])
            except Exception as e:
                self._search_sessions.delete(event)
                logger.error(f"[暮黎资源] 获取软件详情失败: {e}")
                return f"{tag} 获取详情失败：{str(e)[:100]}"
            if not detail.get("download_links"):
                self._search_sessions.delete(event)
                return f"{tag} 「{sel['title']}」暂无下载链接。"
            self._search_sessions.update(event, detail=detail, stage="select_link")
            await self._send_software_link_menu(event, detail, sel, detail["download_links"])
            self._search_sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 软件 '{sel['title']}' → {len(detail['download_links'])}个网盘")
            return f"{tag} 已发送软件详情卡和网盘列表给用户。请等待用户回复数字或网盘名，**不要**自行调用 select_download_link。"

        logger.warning(f"[暮黎资源] select_search_result({number}) → 无活跃会话")
        return f"{tag} 当前没有活跃的搜索结果。请先使用 search_game / search_software / search_movie 搜索，或回复0取消。"

    @filter.llm_tool(name="select_download_link")
    async def llm_select_download_link(self, event: AstrMessageEvent, selection: str):
        """用户选择下载网盘后调用，获取真实下载地址并合并转发。

        Args:
            selection(string): 用户的选择（数字如"1"，或网盘名称如"百度网盘"、"夸克网盘"）
        """
        tag = "【暮黎资源】"
        # ★影视会话拦截：a123tv 只有在线播放（无网盘），由 on_any_message 处理
        ses_mv = self._movie_sessions.get(event)
        if ses_mv and ses_mv.get("stage") in ("select_movie", "select_episode", "select_source"):
            return f"{tag} 影视资源无需网盘选择，由系统直接处理。"
        # ★新站影视会话：LLM 可能误调此工具（用户选网盘/节点时），
        #   直接转交状态机处理，确保用户选择不被丢弃
        ses_mn = self._movie_sessions_new.get(event)
        if ses_mn and ses_mn.get("stage") in ("select_movie_new", "select_res_type",
                                               "select_pan_type", "select_play_node", "select_episode_new", "select_pan"):
            return await self._handle_movie_new_selection(event, selection)
        ses = self._sessions.get(event)
        if ses and ses.get("stage") == "select_link":
            detail = ses.get("game_detail")
            if not detail:
                logger.warning(f"[暮黎资源] select_download_link 会话无detail")
                return f"{tag} 会话状态异常，请重新搜索。"
            links = detail["download_links"]
            num = self._parse_selection(selection, links)
            if num == 0: self._sessions.delete(event); return f"{tag} 已取消。"
            if num < 1 or num > len(links):
                return f"{tag} 请输入1-{len(links)}或网盘名称。回复0取消。"
            sl = links[num-1]
            logger.info(f"[暮黎资源] 用户选择链接#{num}: {sl['pan']}")
            try: rlink = await asyncio.to_thread(lambda sl=sl, ck=self._get_cookie(): self._g_resolve(sl, self._g_cookie()))
            except Exception: rlink = sl
            sg = ses["results"][ses["selected_index"]]
            gn = detail.get("name") or sg["title"]
            logger.info(f"[暮黎资源] 发送资源 '{gn}' → {rlink.get('pan','?')}")
            sent = await self._send_download_link(
                event, gn, rlink.get("pan", "下载链接"), rlink.get("real_url", ""),
                code=rlink.get("code", ""), password=rlink.get("password", ""),
                source_name="暮黎游戏", kind="game",
                charge=not ses.get("_charged"))
            self._mark_llm_suppress(event)
            self._sessions.delete(event)
            return f"{tag} 已发送「{gn}」的下载链接。换网盘需引用网盘列表消息。"

        ses2 = self._search_sessions.get(event)
        if ses2 and ses2.get("stage") == "select_link":
            detail = ses2.get("detail")
            if not detail: return f"{tag} 会话状态异常，请重新搜索。"
            links = detail["download_links"]
            num = self._parse_selection(selection, links)
            if num == 0: self._search_sessions.delete(event); return f"{tag} 已取消。"
            if num < 1 or num > len(links):
                return f"{tag} 请输入1-{len(links)}或网盘名称。回复0取消。"
            sl = links[num-1]
            logger.info(f"[暮黎资源] 用户选择软件链接#{num}: {sl['pan']}")
            sr = ses2["results"][ses2["selected_index"]]
            sn = detail.get("name") or sr["title"]
            logger.info(f"[暮黎资源] 发送软件 '{sn}' → {sl['pan']}")
            sent = await self._send_download_link(
                event, sn, sl.get("pan", "下载链接"), sl.get("url", ""),
                source_name="暮黎软件", kind="software",
                charge=not ses2.get("_charged"))
            self._mark_llm_suppress(event)
            self._search_sessions.delete(event)
            return f"{tag} 已发送「{sn}」的下载链接。换网盘需引用网盘列表消息。"

        logger.warning(f"[暮黎资源] select_download_link('{selection}') → 无活跃会话")
        return f"{tag} 当前没有活跃的下载选择会话。请先搜索并选择资源，或回复0取消。"

    def _parse_selection(self, selection: str, links: list) -> int:
        """解析用户选择：数字/中文序数/网盘名 → 1-based index。0=取消, -1=无效"""
        s = selection.strip()
        # 取消词
        if s in ("0", "取消", "算了", "不用了", "不要了", "不了"): return 0
        # 自然语言序数解析
        num = self._parse_natural_number(s)
        if num == -2: return len(links)  # "最后一个"
        if num > 0: return num
        # 网盘名匹配
        for i, lk in enumerate(links):
            if s in lk["pan"] or lk["pan"] in s: return i + 1
        return -1

    def _parse_natural_number(self, text: str) -> int:
        """解析中文自然语言数字 → int。无法解析返回-1。
        '第一个'→1, '二'→2, '最后一个'→-2(调用者转len), '1'→1"""
        s = text.strip(); CN = {'零':0,'一':1,'二':2,'两':2,'俩':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
        if not s: return -1
        try: return int(s)
        except ValueError: pass
        # "第X个/位/项/名/条"
        m = re.search(r'第\s*(\S+?)\s*(?:个|位|项|名|条|款|种|行)', s)
        if m: return self._parse_natural_number(m.group(1))
        # "最后一个" / "倒数第一个"
        if re.search(r'(最后|末尾|倒数)', s): return -2
        # 纯中文数字
        if s in CN: return CN[s]
        # "十一"~"九十九"
        m = re.match(r'^(十|[一二三四五六七八九]十)([一二三四五六七八九])?$', s)
        if m:
            tens = 10 if m.group(1)=='十' else CN.get(m.group(1)[0],0)*10
            ones = CN.get(m.group(2),0) if m.group(2) else 0
            return tens+ones
        # 提取阿拉伯数字
        m = re.search(r'(\d+)', s)
        if m: return int(m.group(1))
        return -1

# ==================== 命令 ====================

    # ---------- 全局积分 / 每日签到 ----------

    @filter.command("签到")
    async def cmd_checkin(self, event: AstrMessageEvent):
        """每日签到领取积分（跨群聊/私聊全局累计，带签到卡片）。"""
        await self._send_checkin(event)

    @filter.command("每日签到")
    async def cmd_checkin_alias(self, event: AstrMessageEvent):
        """每日签到（别名）。"""
        await self._send_checkin(event)

    @filter.command("积分")
    async def cmd_points(self, event: AstrMessageEvent):
        """查看自己的积分、连续签到与搜索消耗（图片卡片）。"""
        await self._send_points_card(event)

    @filter.command("我的积分")
    async def cmd_points_alias(self, event: AstrMessageEvent):
        """查看我的积分（别名）。"""
        await self._send_points_card(event)

    @filter.command("积分排行")
    async def cmd_points_rank(self, event: AstrMessageEvent):
        """查看积分排行榜（前 10 名，带头像卡片）。"""
        await self._send_points_rank_card(event, 10)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("积分管理")
    async def cmd_points_admin(self, event: AstrMessageEvent):
        """管理员调整用户积分。

        用法：
        - /积分管理 <用户ID> <数量>        数量为正增加、为负扣除
        - /积分管理 设置 <用户ID> <数量>   直接设置余额
        - /积分管理 查询 [用户ID]          查看该用户积分（省略 ID 查自己）
        目标支持：纯用户ID / 平台:用户ID / @某人 / 引用回复某人。
        """
        usage = ("【暮黎资源·积分管理】\n"
                 "用法：\n"
                 "/积分管理 <用户ID> <数量>（正数增加，负数扣除）\n"
                 "/积分管理 设置 <用户ID> <数量>\n"
                 "/积分管理 查询 [用户ID]\n"
                 "目标也可用 @某人 / 回复 <数量>（引用对象） / 平台:用户ID")
        text = re.sub(r"^/?\s*积分管理\s*", "", event.message_str.strip())
        text = text.replace("\u3000", " ").strip()
        parts = [p for p in text.split() if p]
        if not parts or parts[0] in ("帮助", "help", "说明", "?", "？"):
            yield event.plain_result(usage); return
        logger.info(f"[暮黎资源·积分] 积分管理命令: sender={event.get_sender_id()} "
                    f"platform={event.get_platform_id()} text={text[:80]!r}")

        # —— 动作解析：省略动作时默认「调整」（兼容 /积分管理 123 50） ——
        action_alias = {
            "设置": "设置", "set": "设置", "重置": "设置", "reset": "设置",
            "查询": "查询", "查": "查询", "query": "查询", "info": "查询", "余额": "查询",
            "增加": "增加", "加": "增加", "add": "增加", "奖励": "增加",
            "扣除": "扣除", "扣": "扣除", "减": "扣除", "remove": "扣除",
        }
        action = "调整"
        if parts[0].lower() in action_alias:
            action = action_alias[parts[0].lower()]
            parts = parts[1:]

        platform = str(event.get_platform_id() or "unknown")
        store = self._points_db()

        # —— 目标解析：文本 ID / @ / 引用回复 / 省略（查询自己） ——
        def _at_target() -> str:
            """从消息组件里取 @ 的用户 ID。

            AstrBot 的 At 组件 type 是 ComponentType 枚举，直接比较字符串会失败；
            这里优先看 qq 字段（最稳），再兼容 OneBot raw_message / CQ 码。
            """
            chain = []
            try:
                if hasattr(event, "get_messages"):
                    chain = event.get_messages() or []
                if not chain:
                    chain = getattr(getattr(event, "message_obj", None), "message", None) or []
            except Exception:
                chain = []
            for comp in chain:
                qq = getattr(comp, "qq", None)
                if qq is None:
                    # 兼容 dict 形式 {"type":"at","data":{"qq":"123"}}
                    if isinstance(comp, dict) and str(comp.get("type", "")).lower() == "at":
                        qq = (comp.get("data") or {}).get("qq")
                    else:
                        continue
                qq_s = str(qq).strip()
                if not qq_s or qq_s in ("all", "everyone", "0"):
                    continue
                try:
                    if qq_s == str(event.get_self_id()):
                        continue  # 跳过 @机器人自己
                except Exception:
                    pass
                return qq_s

            # 兜底：从 raw_message / 原文本里解析 [CQ:at,qq=...] / [At:...]
            sources = []
            try:
                sources.append(getattr(getattr(event, "message_obj", None), "raw_message", None))
            except Exception:
                pass
            sources.append(text)
            for src in sources:
                if isinstance(src, dict):
                    for item in (src.get("message") or []):
                        if isinstance(item, dict) and str(item.get("type", "")).lower() == "at":
                            qq = (item.get("data") or {}).get("qq")
                            if qq and str(qq) not in ("all", "everyone", "0"):
                                return str(qq)
                    src = json.dumps(src, ensure_ascii=False)
                if not isinstance(src, str):
                    continue
                m = re.search(r"\[CQ:at,qq=([^,\]]+)", src)
                if m:
                    return m.group(1)
                m = re.search(r"\[At[:：]([^\]]+)\]", src, re.I)
                if m:
                    return m.group(1).strip()
            return ""

        def _reply_target() -> str:
            try:
                obj = getattr(getattr(event, "message_obj", None), "reply", None)
                if obj is None:
                    return ""
                for attr in ("sender_id", "user_id"):
                    v = getattr(obj, attr, None)
                    if isinstance(v, (str, int)) and str(v):
                        return str(v)
                sender = getattr(obj, "sender", None)
                for attr in ("user_id", "id"):
                    v = getattr(sender, attr, None)
                    if isinstance(v, (str, int)) and str(v):
                        return str(v)
            except Exception:
                pass
            return ""

        def _target_from_text(raw: str) -> str:
            raw = str(raw or "").strip()
            m = re.fullmatch(r"\[at[:：]([^\]]+)\]", raw, re.I)
            if m:
                return m.group(1).strip()
            m = re.fullmatch(r"\[CQ:at,qq=([^,\]]+).*\]", raw, re.I)
            if m:
                return m.group(1).strip()
            return raw.lstrip("@")

        raw_uid = parts[0] if parts else ""
        raw_uid = raw_uid.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        rest = parts[1:] if parts else []
        self_words = {"我", "自己", "me", "self"}
        reply_words = {"回复", "对方", "他", "她", "楼上", "reply"}
        if raw_uid.lower() in self_words:
            raw_uid, _, _ = self._points_user(event)
        elif re.fullmatch(r"\[at[:：][^\]]+\]", raw_uid, re.I):
            raw_uid = _target_from_text(raw_uid)
        elif raw_uid.startswith("@") or raw_uid.lower() in reply_words:
            auto = _at_target() or _reply_target()
            if not auto:
                yield event.plain_result("❌ 没识别到目标用户，请直接填写用户ID（如 123456）。"); return
            raw_uid = auto
        if not raw_uid:
            if action == "查询":
                raw_uid, _, _ = self._points_user(event)
                # 引用回复时优先查被回复的人（省略 ID + 回复 = 查对方）
                raw_uid = _reply_target() or raw_uid
            else:
                yield event.plain_result(usage); return

        # —— 存储键解析：纯 ID 时按当前平台优先，跨平台单命中自动兜底 ——
        def _resolve_key(raw: str) -> tuple[str, str, str]:
            raw = raw.strip()
            if not raw:
                return "", "", "❌ 未找到目标用户，请提供用户ID或 @某人。"
            if ":" in raw:
                plat, uid = raw.split(":", 1)
                return PointsStore.make_key(plat, uid), uid, ""
            key = PointsStore.make_key(platform, raw)
            keys = store.find_keys(raw)
            if key in keys or not keys:
                return key, raw, ""
            if len(keys) == 1:
                return keys[0], raw, ""
            options = "\n".join(f"· /积分管理 查询 {k}" for k in keys[:5])
            return "", raw, (f"⚠️ 用户 {raw} 在多个平台有记录，请带上平台前缀：\n{options}")

        def _to_int(raw: str) -> Optional[int]:
            s = str(raw).strip().translate(str.maketrans("０１２３４５６７８９＋－", "0123456789+-"))
            s = s.replace(",", "").replace("，", "").replace(" ", "")
            if s.startswith("+"):
                s = s[1:]
            if not re.fullmatch(r"[+-]?\d+", s or ""):
                return None
            try:
                return int(s)
            except ValueError:
                return None

        key, uid, err = _resolve_key(raw_uid)
        if err:
            yield event.plain_result(err); return

        s = self._points_settings()
        try:
            user = store.peek(key)
            before = int((user or {}).get("points", 0) or 0)
            if user is None and action != "设置":
                # 首次调整会按「初始积分」建档，展示时把初始值算进起始余额
                before = int(s["initial"] or 0)
            name = str((user or {}).get("name") or uid)

            if action == "查询":
                if user is None:
                    yield event.plain_result(
                        f"【暮黎资源·积分管理】\n👤 {uid}\n"
                        f"💰 当前积分：0（暂无记录，发送 /签到 后自动建档）"); return
                yield event.plain_result(
                    f"【暮黎资源·积分管理】\n👤 {name}\n"
                    f"🆔 {key}\n"
                    f"💰 当前积分：{before}\n"
                    f"🔥 连续签到：{int(user.get('streak', 0) or 0)} 天 ｜ "
                    f"📅 最近签到：{user.get('last_checkin') or '从未签到'}\n"
                    f"🧾 累计获得 {int(user.get('total_earned', 0) or 0)} ｜ "
                    f"累计消耗 {int(user.get('total_spent', 0) or 0)}"); return

            if action == "设置":
                if not rest:
                    yield event.plain_result("❌ 请提供要设置的积分数量。\n例如：/积分管理 设置 123456 100"); return
                amount = _to_int(rest[0])
                if amount is None:
                    yield event.plain_result("❌ 数量必须是整数（例如 100）。"); return
                balance = store.set_balance(key, max(0, amount), "")
                logger.info(f"[暮黎资源·积分] 管理员 {event.get_sender_id()} 设置 {key} "
                            f"{before} -> {balance}")
                yield event.plain_result(
                    f"【暮黎资源·积分管理】\n✅ 已将 {name}（{key}）的积分从 {before} 设置为 {balance}。"); return

            if not rest:
                yield event.plain_result("❌ 请提供增减数量（正数增加，负数扣除）。\n例如：/积分管理 123456 50"); return
            amount = _to_int(rest[0])
            if amount is None:
                yield event.plain_result("❌ 数量必须是整数（例如 50 或 -20）。"); return
            if action == "增加":
                amount = abs(amount)
            elif action == "扣除":
                amount = -abs(amount)

            balance = store.add(key, amount, "", s["initial"])
            delta = balance - before
            logger.info(f"[暮黎资源·积分] 管理员 {event.get_sender_id()} 调整 {key} "
                        f"amount={amount} {before} -> {balance}")
            if amount > 0:
                verb, tip = "增加", f"+{delta}"
            else:
                verb = "扣除"
                tip = f"-{abs(delta)}" if delta else "0（余额已为 0）"
            yield event.plain_result(
                f"【暮黎资源·积分管理】\n✅ 已为 {name}（{key}）{verb} {abs(amount)} 积分，"
                f"{tip}，当前 {balance} 积分。")
        except Exception as e:
            logger.warning(f"[暮黎资源·积分] 管理员调整失败: {e}")
            yield event.plain_result(f"❌ 积分操作失败：{str(e)[:100]}")

    # ==================== 群聊小游戏命令 ====================

    @filter.command("小游戏")
    async def cmd_minigame(self, event: AstrMessageEvent):
        """打开群游戏大厅：猜数字 / 封面猜猜 / 谁是卧底。支持 /小游戏 1、/小游戏 2、/小游戏 3 直接开始。"""
        raw = (event.message_str or "").strip()
        arg = re.sub(r"^/?\s*小游戏\s*", "", raw).strip()
        start = ""
        if arg in ("1", "猜数字", "数字炸弹", "炸弹"):
            start = "guess"
        elif arg in ("2", "封面猜猜", "封面", "猜封面"):
            start = "cover"
        elif arg in ("3", "谁是卧底", "卧底"):
            start = "undercover"
        try:
            await self._minigame_open_lobby(event, start=start)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[小游戏] 打开大厅失败: {e}")
            yield event.plain_result(f"😕 小游戏启动失败：{str(e)[:100]}")

    @filter.command("结束游戏")
    async def cmd_minigame_stop(self, event: AstrMessageEvent):
        """提前结束当前群的游戏。"""
        gkey = self._minigame_group_key(event)
        if not gkey:
            yield event.plain_result("【暮黎资源】小游戏只能在群聊里玩。")
            return
        game = self._minigame_sessions.get(gkey)
        if not game:
            yield event.plain_result("【暮黎资源】当前没有进行中的小游戏。")
            return
        if (game.get("stage") in ("cover_pick", "cover")
                and game.get("cover_owner_key")):
            key, _uid, _name = self._points_user(event)
            if key != game["cover_owner_key"]:
                yield event.plain_result(
                    "【暮黎资源】封面猜猜是单人游戏，只有发起者可以结束。")
                return
        if str(game.get("stage") or "").startswith("uc_"):
            key, _uid, _name = self._points_user(event)
            if key != game.get("host_key"):
                yield event.plain_result(
                    "【暮黎资源】谁是卧底只有房主可以结束。")
                return
        try:
            await self._minigame_end(event, gkey, game, reason="手动结束")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[小游戏] 结束失败: {e}")
            self._minigame_cancel_task(game)
            self._minigame_sessions.pop(gkey, None)
            yield event.plain_result(f"😕 结束游戏失败，已强制关闭：{str(e)[:100]}")

    @filter.command("找游戏")
    async def cmd_game_search(self, event: AstrMessageEvent):
        keyword = clean_search_keyword(event.message_str.strip())
        keyword = re.sub(r"^/?找游戏\s*", "", keyword)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, keyword)
        if not allowed:
            yield event.plain_result(f"⚠️ {reason}"); return
        logger.info(f"游戏搜索: 关键词=[{keyword}]")
        if not keyword: yield event.plain_result("请发送：/找游戏 <游戏名>"); return
        if not requests: yield event.plain_result("❌ 缺少 requests"); return
        if not BeautifulSoup: yield event.plain_result("❌ 缺少 beautifulsoup4"); return
        # 源路由 Cookie 检查（xdgame / switch618）
        cb = await self._g_check_cookie()
        if cb in ("expired", "invalid"):
            if self._game_source() == "switch618":
                yield event.plain_result("⚠️ 游戏资源 Cookie 未生效。\n请先联系管理员发送 /game_cookie_refresh 获取 Cookie。")
            else:
                yield event.plain_result("⚠️ 游戏资源 Cookie 已失效。\n请先发送 /game_cookie_refresh 更新 Cookie。")
            return
        # 委托给 session_waiter 交互流程
        async for result in self._run_game_search_flow(event, keyword):
            yield result

    @filter.command("找软件")
    async def cmd_sw_search(self, event: AstrMessageEvent):
        keyword = clean_search_keyword(event.message_str.strip())
        keyword = re.sub(r"^/?找软件\s*", "", keyword)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, keyword)
        if not allowed:
            yield event.plain_result(f"⚠️ {reason}"); return
        logger.info(f"软件搜索: 关键词=[{keyword}]")
        if not keyword: yield event.plain_result("请发送：/找软件 <资源名>"); return
        if not requests: yield event.plain_result("❌ 缺少 requests"); return
        if not BeautifulSoup: yield event.plain_result("❌ 缺少 beautifulsoup4"); return
        # 委托给 session_waiter 交互流程
        async for result in self._run_software_search_flow(event, keyword):
            yield result

    @filter.command("找影视")
    async def cmd_movie_search(self, event: AstrMessageEvent):
        """影视搜索 — 默认 pdy0（片库注册站，免登录）；movie_source=old 时用片库主站。"""
        keyword = event.message_str.strip()
        keyword = re.sub(r"^/?找影视\s*", "", keyword)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, keyword)
        if not allowed:
            yield event.plain_result(f"⚠️ {reason}"); return
        logger.info(f"影视搜索: 关键词=[{keyword}]")
        if not keyword:
            yield event.plain_result("请发送：/找影视 <影视名>"); return
        _blocked = self._points_guard(event, "movie")
        if _blocked:
            yield event.plain_result(_blocked); return

        tag = "【暮黎资源】"
        source = self._movie_source()
        r = await self._search_movie_source(event, keyword, source)
        st = r.get("status")
        if st == "captcha_sent":
            return
        if st == "empty":
            yield event.plain_result(f"{tag} 未找到与「{keyword}」相关的影视。请换个关键词。"); return
        if st == "no_client":
            yield event.plain_result(f"{tag} {r.get('msg')}"); return
        if st != "ok":
            yield event.plain_result(f"{tag} 影视搜索失败：{r.get('msg') or '未知错误'}"); return
        await self._send_movie_results(event, keyword, r.get("results", []), source)
        logger.info(f"[暮黎资源] /找影视({source},'{keyword}') → {len(r.get('results', []))}条")

    @filter.command("movie_status")
    async def cmd_movie_status(self, event: AstrMessageEvent):
        """检查当前影视源（pdy0 / 片库主站）状态。"""
        source = self._movie_source()
        if source == "pdy":
            try:
                client = self._get_pdy_client()
                domains = await asyncio.to_thread(discover_domains)
                base = domains[0][0] if domains else client.base_url
                r = await asyncio.to_thread(
                    requests.get, base,
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                ok = r.status_code == 200 and "片库" in r.text
                if ok:
                    online = " / ".join(u.replace("https://", "") for u, _ in domains[:4]) or "未知"
                    yield event.plain_result(
                        f"✅ pdy0 系站点状态：可访问\n"
                        f"🌐 当前使用：{client.base_url}\n"
                        f"📡 发布页可用：{online}\n"
                        f"📋 HTTP {r.status_code}  响应 {len(r.text)//1024}KB\n"
                        f"🔐 搜索验证：{'已通过（本机会话）' if client.verified else '未通过（首次搜索会弹图片验证码）'}\n"
                        f"🟢 默认影视源（发布页 {PDY_RELEASE_URL} 自动选站）；备用站切换请把 movie_source 设为 old。"
                    )
                else:
                    yield event.plain_result(
                        f"❌ pdy0 系站点状态：异常\n"
                        f"🌐 尝试站点：{base}\n"
                        f"📋 HTTP {r.status_code}  响应 {len(r.text)}B\n"
                        f"💡 会自动刷新发布页并切换可用站点。"
                    )
            except Exception as e:
                yield event.plain_result(f"❌ pdy0 系站点不可达：{str(e)[:120]}")
            return

        client = self._get_muliy_client()
        if not client:
            yield event.plain_result(
                "⚠️ 当前影视源=片库主站（old），但未配置 muliy_cookie / muliy_username+muliy_password。\n"
                "请在插件配置的「影视资源」组填写登录凭据。")
            return
        try:
            base = await asyncio.to_thread(client._get_base)
            ok = await asyncio.to_thread(client.ensure_session)
            yield event.plain_result(
                f"✅ 片库主站状态：{'登录正常' if ok else '登录失败'}\n"
                f"🌐 {base}\n"
                f"🔑 凭据：{'Cookie' if client._cookie_str else '账号密码'}\n"
                f"💡 默认源是 pdy0；只有 movie_source=old 时才走这里。"
            )
        except Exception as e:
            yield event.plain_result(f"❌ 片库主站检查失败：{str(e)[:120]}")

    # ==================== 短剧搜索与日报 (网盘贴吧 wangpant8.com) ====================

    @filter.command("找短剧")
    async def cmd_drama_search(self, event: AstrMessageEvent):
        """短剧搜索 — 网盘贴吧（wangpant8.com）→ 返回夸克网盘资源链接与详情页。"""
        keyword = re.sub(r"^/?找短剧\s*", "", event.message_str.strip()).strip()
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, keyword)
        if not allowed:
            yield event.plain_result(f"⚠️ {reason}"); return
        if not keyword:
            yield event.plain_result("请发送：/找短剧 <剧名>"); return
        logger.info(f"短剧搜索: 关键词=[{keyword}]")
        ret = await self.llm_search_drama(event, keyword)
        # llm_search_drama 成功时已 event.send；未找到/失败只返回文本，需自己发出
        if ret and not ret.startswith("[已发送"):
            yield event.plain_result(ret)

    @filter.command("drama_report")
    async def cmd_drama_report(self, event: AstrMessageEvent):
        """手动触发短剧日报（最新上传，含夸克网盘链接）。"""
        config = self._get_config()
        try:
            mx = int(config.get("drama_report_max", 12) or 12) if isinstance(config, dict) else 12
        except (TypeError, ValueError):
            mx = 12
        try:
            timeout = int(config.get("drama_timeout", 15) or 15) if isinstance(config, dict) else 15
        except (TypeError, ValueError):
            timeout = 15
        yield event.plain_result("⏳ 正在抓取最新短剧（含网盘链接）...")
        result = await asyncio.to_thread(fetch_latest_dramas, mx, True, timeout)
        if not result.get("success"):
            yield event.plain_result(f"⚠️ {result.get('error','未知错误')}"); return
        items = result.get("items", [])
        if not items:
            yield event.plain_result("📭 今日暂无短剧更新。"); return
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        html = build_drama_html(items, date_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        try:
            img_bytes = await asyncio.to_thread(render_drama_to_png, html, font_path, 720, channel, exe)
        except Exception as e:
            logger.error(f"[短剧日报] 渲染异常: {e}")
        if not img_bytes:
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            cards = [{"cover": "", "title": it.get("title") or "未知",
                      "chips": [c for c in (it.get("category") or "短剧",
                                            it.get("date") or "",
                                            it.get("disk") or "夸克") if c],
                      "desc": it.get("link") or ""} for it in items]
            img_bytes = await self._report_pil_fallback(
                cards, date_label, "网盘贴吧", font_path, 720, "短剧日报")
        ts = datetime.date.today().strftime("%Y%m%d")
        if img_bytes:
            fn = f"暮黎短剧日报_{ts}{_img_ext(img_bytes)}"
            ok = await self._send_event_file(event, img_bytes, fn, "", "短剧日报")
            if not ok:
                yield event.plain_result("⚠️ 日报图片发送失败，已尝试降级发图/文字版。")
        else:
            await event.send(MessageChain([Plain(
                "⚠️ 图片渲染失败，改为文字版：\n"
                + "\n".join(f"{i}. {it.get('title','')}  {it.get('link','')}"
                            for i, it in enumerate(items, 1)))]))
        return

    # ==================== 小说搜索与下载 (so-novel) ====================

    def _novel_cfg(self):
        """读取小说（so-novel）相关配置，带默认值兜底。"""
        c = self._get_config()
        base = (c.get("sonovel_base_url") or "http://127.0.0.1:7765").strip().rstrip("/")
        if not base:
            base = "http://127.0.0.1:7765"
        token = (c.get("sonovel_token") or "").strip()
        try:
            limit = int(c.get("sonovel_search_limit", 20) or 20)
        except (TypeError, ValueError):
            limit = 20
        fmts = self._parse_multi(c.get("sonovel_format") or ["txt"])
        fmts = [f.lower() for f in fmts if f.lower() in NOVEL_FORMATS] or ["txt"]
        try:
            timeout = int(c.get("sonovel_timeout", 30) or 30)
        except (TypeError, ValueError):
            timeout = 30
        try:
            dl_timeout = int(c.get("sonovel_download_timeout", 600) or 600)
        except (TypeError, ValueError):
            dl_timeout = 600
        return base, token, limit, fmts, timeout, dl_timeout

    def _format_novel_page(self, ses: dict) -> str:
        """格式化小说搜索结果分页展示（极简：每条仅书名+作者，书源独立一行）。

        层级设计：
          ① 书名      —— 一级（带序号，最显眼）
          ② 作者      —— 二级
          ③ 书源      —— 独立一行（🏷️ 书源：xxx），不与作者挤在一行
          ──────      —— 条目分隔线
        简介/最新章节不在列表展开（避免刷屏，选中后再看）。
        """
        r = ses["results"]
        p = ses.get("page", 0)
        ps = ses.get("page_size", 8)
        t = len(r)
        st = p * ps
        ed = min(st + ps, t)
        pc = ed - st
        tag = "【暮黎资源·小说】"
        kw = ses.get("keyword", "")
        pt = (t + ps - 1) // ps
        # 头部：关键词 + 总数 + 当前页/总页
        head = f"{tag} 🔍 「{kw}」"
        if pt > 1:
            head += f"  第 {p + 1}/{pt} 页"
        head += f"\n共 {t} 条结果（多书源聚合）"
        lines = [head, ""]
        sep = "=" * 12
        for i, x in enumerate(r[st:ed], 1):
            idx = emoji_index(i, pc)
            name = x["book_name"] or "(未知书名)"
            author = x["author"] or "佚名"
            src = x["source_name"] or "未知源"
            # 一级：序号 + 书名
            lines.append(f"{idx} {name}")
            # 二级：作者（单独一行，弱化）
            lines.append(f"   👤 {author}")
            # 三级：书源（独立一行，不与作者合并）
            lines.append(f"   🏷️ 书源：{src}")
            lines.append(sep)
        # 页脚：翻页 + 选择提示
        foot = []
        if pt > 1:
            foot.append(f"📄 翻页：回复「下一页 / 上一页」，或「跳N」（如 跳3）")
        foot.append(f"👇 回复数字 1-{pc} 选择下载；回复 0 取消（{SESSION_TIMEOUT}秒超时）")
        lines.append("")
        lines.extend(foot)
        return "\n".join(lines)

    @filter.command("找小说")
    async def cmd_novel_search(self, event: AstrMessageEvent):
        """小说搜索与下载（so-novel 多源聚合）。/找小说 <书名或作者>"""
        keyword = event.message_str.strip()
        keyword = re.sub(r"^/?找小说\s*", "", keyword).strip()
        # 去掉「小说」统称后缀，保留书名/作者
        if keyword.endswith("小说"):
            keyword = keyword[:-2].strip()
        logger.info(f"小说搜索: 关键词=[{keyword}]")
        if not keyword:
            yield event.plain_result(
                "请发送：/找小说 <书名或作者>\n例如：/找小说 斗破苍穹"); return
        if not requests:
            yield event.plain_result("❌ 缺少 requests 依赖"); return
        _blocked = self._points_guard(event, "novel")
        if _blocked:
            yield event.plain_result(_blocked); return

        base, token, limit, fmts, timeout, dl_timeout = self._novel_cfg()
        try:
            results = await asyncio.to_thread(
                search_novels, keyword, base, token, limit, timeout)
        except NovelApiError as e:
            yield event.plain_result(
                f"❌ 小说搜索失败：{e.message}\n"
                f"💡 请确认 so-novel 已以 Web 模式启动（默认 http://127.0.0.1:7765）。"); return
        except Exception as e:
            yield event.plain_result(f"❌ 小说搜索异常：{str(e)[:200]}"); return

        if not results:
            yield event.plain_result(
                f"😕 未找到与「{keyword}」相关的小说，换个关键词试试？"); return

        page_size = 8
        self._novel_sessions.set(event, {
            "keyword": keyword, "results": results, "page": 0,
            "page_size": page_size, "stage": "select_novel", "_updated": time.time(),
        })
        _charge_txt = self._points_charge(event, "novel", keyword)
        ses_now = self._novel_sessions.get(event)
        text = self._format_novel_page(ses_now) + _charge_txt
        card = ""
        if novel_card_html:
            try:
                card = novel_card_html(ses_now, timeout=SESSION_TIMEOUT, note=_charge_txt)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 小说卡片构建失败，回退文本: {e}")
        await self._send_novel_list(event, self._novel_sessions.get(event), card,
                                    text, len(results))

    @filter.command("novel_status")
    async def cmd_novel_status(self, event: AstrMessageEvent):
        """检查 so-novel 服务是否可达 + 书源可用性。"""
        base, token, limit, fmts, timeout, dl_timeout = self._novel_cfg()
        fmt_default_label = "、".join(f.upper() for f in fmts)
        try:
            sources = await asyncio.to_thread(check_sources, base, token, timeout)
            reachable = True
        except NovelApiError as e:
            yield event.plain_result(
                f"❌ so-novel 不可达：{e.message}\n🌐 当前地址：{base}"); return
        except Exception as e:
            yield event.plain_result(f"❌ 检查异常：{str(e)[:200]}"); return

        lines = [f"✅ so-novel 服务可访问\n🌐 {base}",
                 f"📋 默认格式：{fmt_default_label} ｜ 搜索上限：{limit} ｜ 下载超时：{dl_timeout}s\n"]
        if sources:
            lines.append(f"📚 已激活书源：{len(sources)} 个")
            for s in sources[:15]:
                if isinstance(s, dict):
                    nm = s.get("sourceName") or s.get("name") or s.get("sourceName") or "?"
                    av = s.get("available")
                    mark = "✅" if av is True else ("❌" if av is False else "➖")
                    lines.append(f"  {mark} {nm}")
                else:
                    lines.append(f"  • {s}")
        else:
            lines.append("📚 未能获取书源列表（接口可能未返回，不影响搜索）。")
        yield event.plain_result("\n".join(lines))

    @filter.command("game_cookie")
    async def cmd_game_cookie(self, event: AstrMessageEvent):
        """检测游戏 Cookie 状态：有效/失效/次数用尽"""
        if self._game_source() == "switch618":
            cs = self._g_cookie()
            if not cs:
                yield event.plain_result("⚠️ switch618.com Cookie 未配置。\n请让管理员发送 /game_cookie_refresh 扫码登录获取。")
                return
            yield event.plain_result("🔄 正在检测 switch618.com Cookie 状态...")
            try:
                ok, msg = await asyncio.to_thread(check_618_cookie, cs)
            except Exception as e:
                yield event.plain_result(f"❌ 检测异常：{str(e)[:100]}")
                return
            if ok is True:
                yield event.plain_result(f"✅ switch618.com Cookie 状态：有效 ✓\n📋 {msg}\n🟢 可正常搜索和下载游戏资源。")
            elif ok is False:
                yield event.plain_result(f"❌ switch618.com Cookie 状态：已失效\n📋 {msg}\n💡 请让管理员发送 /game_cookie_refresh 重新扫码登录。")
            else:
                yield event.plain_result(f"❓ switch618.com Cookie 状态：无法确认\n📋 {msg}")
            return
        config = self._get_config()
        cs = config.get("cookie", "").strip()
        if not cs:
            yield event.plain_result("⚠️ Cookie 未配置。请在 WebUI 插件设置中填写 cookie。")
            return
        yield event.plain_result("🔄 正在检测游戏资源站 Cookie 状态...")
        try:
            ck, cm = await asyncio.to_thread(check_cookie, cs)
        except Exception as e:
            yield event.plain_result(f"❌ 检测异常：{str(e)[:100]}")
            return
        if ck is True:
            yield event.plain_result(f"✅ Cookie 状态：有效 ✓\n📋 {cm}\n🟢 可正常搜索和下载游戏资源。")
        elif ck == "limit":
            yield event.plain_result(f"⚠️ Cookie 状态：次数已用尽！\n📋 {cm}\n💡 请前往 xdgame.com 重新登录获取新 Cookie。")
        elif ck is False:
            yield event.plain_result(f"❌ Cookie 状态：已失效\n📋 {cm}\n💡 请前往 xdgame.com 重新登录获取新 Cookie。")
        elif ck is None:
            yield event.plain_result(f"❓ Cookie 状态：无法确认\n📋 {cm}\n💡 建议重新获取 Cookie 或在 WebUI 更新。")

    # ====================================================================
    #  /game_cookie_refresh — 账号密码登录（自动读取配置）
    # ====================================================================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("game_cookie_refresh")
    async def cmd_game_cookie_refresh(self, event: AstrMessageEvent):
        """
        刷新游戏源 Cookie（仅 AstrBot 管理员可用），按当前游戏源动态路由：
        - 游戏源为 switch618 → 走 switch618 扫码关注登录流程，更新 switch618_cookie
        - 游戏源为 xdgame → 走 xdgame 账密登录流程（需先配置 xdgame_username/xdgame_password）

        ⚠️ 首次使用需先在 WebUI 插件设置中填写对应源的账密/配置
        """
        gid = event.get_group_id()
        uid_full = event.get_sender_id()
        pid = event.get_platform_id()
        target = f"{pid}:GroupMessage:{gid}" if gid else f"{pid}:FriendMessage:{uid_full}"

        # ——— 按当前游戏源动态路由：switch618 源一律走 switch618 流程 ———
        if self._game_source() == "switch618":
            await self._run_switch618_login_flow(event, target)
            return

        # ——— 读取配置中的账密（xdgame 源） ———
        config = self._get_config()
        username = (config.get("xdgame_username") or "").strip()
        password = (config.get("xdgame_password") or "").strip()

        if not username or not password:
            await event.send(MessageChain([Plain(
                "❌ 当前游戏源为 xdgame，但未配置 xdgame_username / xdgame_password。\n"
                "💡 请先在 WebUI 插件设置中填写 xdgame 账密；或把 game_source 设为 switch618 后重试。"
            )]))
            return

        # 脱敏日志
        display_pw = password[:2] + "***" + password[-1] if len(password) > 4 else "****"
        logger.info(f"[暮黎资源] /game_cookie_refresh 账号={username[:4]}***")
        await event.send(MessageChain([Plain("🔄 正在登录 xdgame.com，请稍候...")]))

        # ——— 步骤1：填账密，检测验证码 ———
        try:
            step1 = await login_with_password_async(username, password)
        except Exception as e:
            logger.error(f"[暮黎资源] 登录异常: {e}")
            await event.send(MessageChain([Plain(f"❌ 登录异常：{str(e)[:100]}")]))
            return

        if not step1.get("ok"):
            await event.send(MessageChain([Plain(f"❌ 登录失败：{step1.get('error', '未知错误')}")] ))
            return

        # ——— 步骤2：处理验证码 ———
        if not step1.get("needs_captcha"):
            # 无验证码，直接成功
            await self._handle_login_result(step1, target)
            return

        captcha_image = step1.get("captcha_image")
        if not captcha_image:
            await event.send(MessageChain([Plain("❌ 未获取到验证码图片，请重试。")]))
            return

        # 发验证码图片到群里
        tmp = tempfile.mktemp(suffix=".png", prefix="xdgame_captcha_")
        with open(tmp, "wb") as f:
            f.write(captcha_image)
        await event.send(MessageChain([
            Plain("🔐 请看上图验证码，在群里发送验证码完成登录（60秒内有效）"),
            ImageComponent(file=tmp)
        ]))
        try:
            os.unlink(tmp)
        except Exception:
            pass

        # ——— 使用 session_waiter 等待用户输入 ———
        if not session_waiter:
            await event.send(MessageChain([Plain("❌ session_waiter 不可用，无法接收验证码。")]))
            return

        captcha_text = None

        # === H10: 修复 session_waiter 成功路径不调 controller.stop() ===
        # 根因：成功分支只 return 没调 controller.stop()，session 没结束
        # → future 永远不完成 → wrapper 一直等 → 60秒后 TimeoutError
        # 修复：成功分支 handler 内部调 controller.stop() + return

        @session_waiter(timeout=60)
        async def _captcha_waiter(controller, ev: AstrMessageEvent):
            nonlocal captcha_text
            text = ev.message_str.strip()
            logger.info(f"[暮黎资源/H10] _captcha_waiter 被触发，text={text!r}")
            if re.match(r"^[a-zA-Z0-9]{3,8}$", text):
                captcha_text = text.upper()
                logger.info(f"[暮黎资源] 收到验证码: {captcha_text}")
                # 关键：成功时必须 controller.stop() 才能让 wrapper 退出
                controller.stop()
                return
            else:
                # 格式错误：不要 stop，让用户重新输入
                await event.send(MessageChain([Plain("⚠️ 验证码格式不对，请输入图中看到的字母/数字。")]))
                return

        try:
            await _captcha_waiter(event)
            logger.info(f"[暮黎资源/H10] session_waiter 返回，captcha_text={captcha_text}")
        except TimeoutError:
            logger.warning("[暮黎资源/H10] session_waiter 超时（60秒）")
            await event.send(MessageChain([Plain("⏰ 验证码输入超时（60秒），登录已取消。")]))
            return
        except Exception as e:
            logger.error(f"[暮黎资源/H10] session_waiter 异常: {type(e).__name__}: {e}", exc_info=True)
            await event.send(MessageChain([Plain(f"❌ 异常：{type(e).__name__}: {str(e)[:100]}")]))
            return

        if not captcha_text:
            return

        # ——— 步骤3：提交验证码 ———
        try:
            login_result = await submit_captcha_async(captcha_text)
        except Exception as e:
            logger.error(f"[暮黎资源] 提交验证码异常: {e}")
            await event.send(MessageChain([Plain(f"❌ 提交验证码异常：{str(e)[:100]}")]))
            return

        await self._handle_login_result(login_result, target)

    async def _run_switch618_login_flow(self, event: AstrMessageEvent, target: str):
        """switch618 扫码关注登录流程（与 xdgame 共用 /game_cookie_refresh）：
        1. 下发公众号二维码 + 操作指引给管理员
        2. 等待管理员回复公众号下发的验证码
        3. 用验证码提交 ews_login 自动登录
        4. 把 wordpress_logged_in Cookie 存到 switch618_cookie 配置
        """
        logger.info("[暮黎资源] /game_cookie_refresh → switch618 扫码登录流程")
        await event.send(MessageChain([Plain("🔄 正在准备 switch618.com 扫码登录...")]))

        qr_bytes = await asyncio.to_thread(get_qr_image_bytes)
        if not qr_bytes:
            await event.send(MessageChain([Plain("❌ 无法获取 switch618 公众号二维码，请稍后重试。")]))
            return

        tmp = tempfile.mktemp(suffix=".jpg", prefix="s618_qr_")
        with open(tmp, "wb") as f:
            f.write(qr_bytes)
        try:
            await event.send(MessageChain([
                Plain(
                    "📱 【switch618.com 扫码登录】\n\n"
                    "1️⃣ 用微信扫上方二维码，关注「switch618」公众号\n"
                    "2️⃣ 关注后，在公众号里回复「登录」二字\n"
                    "3️⃣ 公众号会自动回复一个【验证码】\n"
                    "4️⃣ 把验证码发到本群/会话，机器人自动完成登录\n\n"
                    "⏰ 验证码发送后请在 120 秒内回复"
                ),
                ImageComponent(file=tmp),
            ]))
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

        if not session_waiter:
            await event.send(MessageChain([Plain("❌ session_waiter 不可用，无法接收验证码。")]))
            return

        code_text = None

        @session_waiter(timeout=120)
        async def _code_waiter(controller, ev: AstrMessageEvent):
            nonlocal code_text
            text = ev.message_str.strip()
            if re.match(r"^[A-Za-z0-9]{3,12}$", text):
                code_text = text
                controller.stop()
                return
            await event.send(MessageChain([Plain("⚠️ 验证码格式不对，请直接发送公众号下发的验证码（字母/数字）。")]))

        try:
            await _code_waiter(event)
        except TimeoutError:
            await event.send(MessageChain([Plain("⏰ 验证码输入超时（120秒），登录已取消。请重新发送 /game_cookie_refresh。")]))
            return
        except Exception as e:
            await event.send(MessageChain([Plain(f"❌ 异常：{type(e).__name__}: {str(e)[:100]}")]))
            return

        if not code_text:
            return

        await event.send(MessageChain([Plain("🔐 正在用验证码登录 switch618.com...")]))
        try:
            ok, result = await asyncio.to_thread(submit_618_login, code_text)
        except Exception as e:
            await event.send(MessageChain([Plain(f"❌ 登录异常：{str(e)[:100]}")]))
            return

        if not ok:
            await self.context.send_message(target, MessageChain([Plain(f"❌ 登录失败：{result}")]))
            return

        await self._update_config("switch618_cookie", result)
        await self.context.send_message(target, MessageChain([Plain(
            "✅ switch618.com 登录成功！\n"
            "📋 新 Cookie 已保存到配置（switch618_cookie）\n"
            "🟢 现在可以正常搜索和下载游戏资源了。"
        )]))

    async def _handle_login_result(self, result: dict, target: str):
        """处理登录结果，更新配置并通知"""
        if result.get("ok"):
            cookies = result.get("cookies", {})
            xd_nick = result.get("xd_nick", "未知")
            cookie_str = format_cookie_string(extract_xdgame_cookies(cookies))
            logger.info(f"[暮黎资源] 登录成功 昵称={xd_nick} cookie长度={len(cookie_str)}")
            if cookie_str:
                await self._update_config("cookie", cookie_str)
                msg = (f"✅ xdgame.com 登录成功！\n"
                       f"👤 昵称：{xd_nick}\n"
                       f"📋 新 Cookie 已保存到配置\n"
                       f"🟢 现在可以正常搜索和下载游戏资源了。")
            else:
                msg = "⚠️ 登录成功但未提取到有效 Cookie，请手动在 WebUI 更新。"
        else:
            msg = f"❌ 登录失败：{result.get('error', '未知错误')}"
        await self.context.send_message(target, MessageChain([Plain(msg)]))

    # game_login 旧代码已移除

    # ====================================================================
    #  /movie_cookie — 片库（新站）影视登录 Cookie 查看 / 设置 / 检测
    # ====================================================================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("movie_cookie")
    async def cmd_movie_cookie(self, event: AstrMessageEvent):
        """查看/设置/检测片库影视登录（Cookie 或账号密码）。
        用法：
          /movie_cookie            → 查看当前配置状态
          /movie_cookie test       → 检测当前 Cookie/账号密码是否可用
          /movie_cookie set <cookie> → 保存 Cookie 并立即重建客户端（重启后仍生效）
        """
        config = self._get_config()
        cur = (config.get("muliy_cookie") or "").strip()
        uname = (config.get("muliy_username") or "").strip()
        upwd = (config.get("muliy_password") or "").strip()
        has_account = bool(uname and upwd)
        raw = (event.message_str or "").strip()
        parts = [p.strip() for p in raw.split(" ", 2) if p.strip()]

        # —— 设置新 Cookie ——
        if len(parts) >= 2 and parts[0].lower() == "set":
            new_cookie = parts[1]
            if not new_cookie or "=" not in new_cookie:
                yield event.plain_result("⚠️ Cookie 格式不正确。请粘贴整串 k=v;k2=v2 形式的 Cookie。")
                return
            await self._update_config("muliy_cookie", new_cookie)
            self._muliy_client = None  # 强制下次 _get_muliy_client 重建
            cur = new_cookie
            yield event.plain_result(f"✅ 片库 Cookie 已保存（{len(new_cookie)} 字符），正在检测...")
        elif len(parts) == 2 and parts[0].lower() == "set":
            yield event.plain_result("⚠️ 请提供 Cookie 内容。用法：/movie_cookie set <cookie>")
            return

        # —— 状态 / 检测 ——
        if not cur and not has_account:
            yield event.plain_result(
                "⚠️ 片库主站（备用源）登录未配置。\n"
                "📋 默认影视源是 pdy0（免登录）；只有 movie_source=old 时才需要片库主站凭据。\n"
                "💡 配置方法（二选一）：\n"
                "  • WebUI 插件设置 → movie 分组 → 填 muliy_username / muliy_password（推荐，免手动搬 Cookie）；\n"
                "  • 填 muliy_cookie 粘贴浏览器登录 Cookie（需含 app_auth、PHPSESSID，忽略 browser_verified/browser_pow）；\n"
                "  或发送 /movie_cookie set <cookie>。")
            return

        mode = "Cookie" if cur else "账号密码"
        yield event.plain_result(f"🔄 正在检测片库影视登录（{mode}，需 PoW 验证，约几秒）...")
        try:
            client = MuliySiteClient(base_url="", cookies=cur,
                                     username=uname, password=upwd)
            base = await asyncio.to_thread(client._get_base)
            ok = await asyncio.to_thread(client.search, "流浪地球", 3)
        except Exception as e:
            yield event.plain_result(f"❌ 检测异常：{str(e)[:120]}")
            return
        if ok:
            yield event.plain_result(
                f"✅ 片库影视登录有效（{mode}）✓\n"
                f"🌐 当前使用站点：{base}\n"
                f"🎬 试搜「流浪地球」返回 {len(ok)} 条结果\n"
                f"🟢 movie_source=old 时将使用片库主站（在线播放+网盘资源）。")
        else:
            yield event.plain_result(
                f"❌ 片库影视登录不可用（{mode}，当前站点 {base} 搜索无结果）。\n"
                f"💡 可能原因：Cookie 过期 / 账号密码错误 / 被站点风控。请检查配置或等待 IP 风控解除。")

    async def _format_status_msg(self, state: str, detail: str = "") -> str:
        """根据轮询状态返回提示文字"""
        msg_map = {
            "polling":    "🔍 正在轮询登录状态…",
            "scanned":    "📱 已扫码！请在手机上确认登录…",
            "confirming": "✅ 已确认登录！正在获取 Cookie…",
            "fetching":   "⏳ 正在提取 Cookie 数据…",
            "done":       "",
        }
        return msg_map.get(state, detail)

    async def _html_render_astrbot(self, html: str, width: int = 720) -> bytes | None:
        """用 AstrBot 内置 html_renderer（云端 T2I 服务）渲染 HTML→图片字节。

        这是 AstrBot 自带的文转图能力（Star.html_render / html_renderer），
        无需本机安装 Playwright/Chromium，适合「没装浏览器」的用户直接出日报图。
        失败返回 None（调用方继续走 Pillow 兜底）。
        """
        try:
            path = await self.html_render(
                html, {}, return_url=False,
                options={"full_page": True, "type": "jpeg", "quality": 85})
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                try:
                    os.unlink(path)
                except Exception:
                    pass
                if data:
                    logger.info(f"[日报] AstrBot 内置渲染完成，体积 {len(data)//1024}KB")
                    return data
        except Exception as e:
            logger.warning(f"[日报] AstrBot 内置渲染失败: {e}")
        return None

    async def _report_pil_fallback(self, cards: list, date_label: str, source_label: str,
                                   font_path: str, width: int, tag: str) -> bytes | None:
        """Playwright/Chromium 渲染失败时的兜底：用 Pillow 纯 Python 直接把日报数据画成图片。

        无需 playwright install chromium。cards 每项：{cover, title, chips, desc}。
        """
        if not render_pil_report:
            logger.warning(f"[{tag}] Pillow 渲染模块不可用，跳过图片兜底")
            return None
        try:
            img_bytes = await asyncio.to_thread(
                render_pil_report, cards, date_label, source_label, font_path, width)
            if img_bytes:
                logger.info(f"[{tag}] Pillow 兜底渲染完成，体积 {len(img_bytes)//1024}KB")
            return img_bytes
        except Exception as e:
            logger.error(f"[{tag}] Pillow 兜底渲染异常: {e}")
            return None

    async def _sw_render_image(self, sws: list) -> bytes | None:
        """软件日报：下载封面 → 橙色夏日风 HTML → Playwright 渲染为图片（压缩到 ≤2MB）。

        失败返回 None（调用方据此降级）。图标使用 Material Design Icons 内联 SVG，无 emoji 乱码。
        """
        config = self._get_config()
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        try:
            await asyncio.to_thread(download_summer_assets, sws)
        except Exception as e:
            logger.warning(f"[软件日报] 封面下载异常: {e}")
        html = build_summer_html(sws, date_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[软件日报] 开始渲染，共 {len(sws)} 款，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_html_to_png, html, font_path, 720, channel, exe)
            logger.info(f"[软件日报] 渲染完成" + (f"，原始图片体积 {len(img_bytes)//1024}KB" if img_bytes else "，但未返回图片(将用兜底渲染)"))
        except Exception as e:
            logger.error(f"[软件日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
        if not img_bytes:
            # ① AstrBot 内置 html_renderer（云端 T2I，无需本机浏览器）
            logger.info("[软件日报] Playwright 不可用，尝试 AstrBot 内置渲染")
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            # ② Pillow 纯 Python 兜底（永远可用）
            logger.info("[软件日报] 尝试 Pillow 兜底渲染")
            cards = []
            for sw in sws:
                chips = []
                ut = (sw.get("update_time") or "").replace("时间：", "").strip()
                if ut:
                    chips.append("🕒 " + ut)
                if sw.get("downloads"):
                    chips.append("⬇️ " + str(sw["downloads"]))
                if sw.get("images"):
                    chips.append(f"📷 {len(sw['images'])}图")
                cards.append({
                    "cover": sw.get("cover_b64") or "",
                    "title": sw.get("title") or sw.get("name") or "未知",
                    "chips": chips,
                    "desc": (sw.get("description") or "暂无简介")[:200],
                })
            img_bytes = await self._report_pil_fallback(
                cards, date_label, "小刀娱乐网", font_path, 720, "软件日报")
        if img_bytes and len(img_bytes) > 2 * 1024 * 1024:
            logger.info(f"[软件日报] 原始图 {len(img_bytes)//1024}KB 超过 2MB，开始压缩...")
            img_bytes = self._compress_game_image(img_bytes)
            logger.info(f"[软件日报] 压缩后体积 {len(img_bytes)//1024}KB")
        if img_bytes:
            logger.info(f"[软件日报] 准备发送，最终图片体积 {len(img_bytes)//1024}KB")
        else:
            logger.warning("[软件日报] 图片渲染失败（img_bytes=None），将降级为文字版")
        return img_bytes

    @filter.command("software_report")
    async def cmd_sw_report(self, event: AstrMessageEvent):
        config = self._get_config()
        ts = datetime.date.today().strftime("%Y%m%d")
        ys = (datetime.date.today()-datetime.timedelta(days=1)).strftime("%Y%m%d")
        tc = self._sw_cached_path(ts); yc = self._sw_cached_path(ys)
        sel_cache = ""; cds = ""
        if os.path.exists(tc): sel_cache = tc; cds = ts
        elif os.path.exists(yc): sel_cache = yc; cds = ys
        # 日报只发送图片，不再发送自包含 zip 文件
        await event.send(MessageChain([Plain("⏳ 抓取数据...")]))
        mx = 24  # max_softwares 配置已移除，固定默认 24
        result = await asyncio.to_thread(sync_scrape, mx)
        if not result["success"]: yield event.plain_result(f"⚠️ {result.get('error','未知')}"); return
        sws = result.get("softwares",[])
        if not sws: yield event.plain_result("📭 今日暂无更新。"); return
        # 橙色夏日风格：HTML → 图片（替代旧的 Pillow 手绘）
        img_bytes = await self._sw_render_image(sws)
        if img_bytes:
            ts = datetime.date.today().strftime("%Y%m%d")
            fn = f"暮黎软件日报_{ts}{_img_ext(img_bytes)}"
            ok = await self._send_event_file(event, img_bytes, fn, "", "软件日报")
            if not ok:
                yield event.plain_result("⚠️ 日报图片发送失败（已尝试降级发图/文字版）。")
        else:
            yield event.plain_result("⚠️ 日报图片渲染失败（已内置 Pillow 兜底，请查看 AstrBot 日志）。")

    @filter.command("software_report_status")
    async def cmd_sw_status(self, event: AstrMessageEvent):
        config = self._get_config()
        h = config.get("schedule_hour",10); m = config.get("schedule_minute",0)
        gh = config.get("game_schedule_hour",18); gm = config.get("game_schedule_minute",0)
        groups = self._parse_multi(config.get("group_ids", []) if isinstance(config, dict) else [])
        ggroups, gfb = self._resolve_group_ids("game_group_ids")
        ei = True; mx = 24
        def _nxt(jid):
            try:
                if self._using_framework_scheduler:
                    sch = self._framework_scheduler()
                    if sch:
                        dt = self._job_next_run(sch.get_job(jid), self._timezone)
                        if dt: return dt.strftime("%Y-%m-%d %H:%M")
                elif self._apscheduler:
                    dt = self._job_next_run(self._apscheduler.get_job(jid), self._timezone)
                    if dt: return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            return "未知"
        mode = "官方(cron_manager)" if self._using_framework_scheduler else "自建(apscheduler)"
        sk = self._using_framework_scheduler or (self._apscheduler and self._apscheduler.running)
        nxt = _nxt(self._scheduler_job_id)
        tz = self._timezone.key if self._timezone else "系统本地"
        lr = self._last_run_date or "从未执行"
        gen = config.get("game_report_enabled", True) if isinstance(config, dict) else True
        gnxt = _nxt(self._game_scheduler_job_id); glr = self._game_last_run_date or "从未执行"
        gmx = int(config.get("game_report_max", 24) or 24) if isinstance(config, dict) else 8
        # 影视日报状态
        men = config.get("movie_report_enabled", True) if isinstance(config, dict) else True
        mh = config.get("movie_schedule_hour", 20); mm = config.get("movie_schedule_minute", 0)
        mgroups, mfb = self._resolve_group_ids("movie_group_ids")
        msec = config.get("movie_sections", "mv,tv,ac") or "mv,tv,ac"
        mmx = int(config.get("movie_report_max", 24) or 24) if isinstance(config, dict) else 24
        mnxt = _nxt(self._movie_scheduler_job_id); mlr = self._movie_last_run_date or "从未执行"
        # 短剧日报状态
        den = config.get("drama_report_enabled", True) if isinstance(config, dict) else True
        dh = config.get("drama_schedule_hour", 21); dmn = config.get("drama_schedule_minute", 0)
        dgroups, dfb = self._resolve_group_ids("drama_group_ids")
        dmx = int(config.get("drama_report_max", 12) or 12) if isinstance(config, dict) else 12
        dnxt = _nxt(self._drama_scheduler_job_id); dlr = self._drama_last_run_date or "从未执行"
        def _gl(v):
            return f"{len(v)}个" if v else "全部"
        yield event.plain_result(
            f"📊 暮黎资源聚合\n{'='*30}\n"
            f"🌍 时区: {tz} | 调度: {'✅' if sk else '❌'} | 模式: {mode}\n"
            f"📦 软件日报: 每日 {h:02d}:{m:02d} | 群{_gl(groups)} | 上次:{lr} | 下次:{nxt}\n"
            f"🎮 游戏日报: {'✅开' if gen else '❌关'} 每日 {gh:02d}:{gm:02d} | 群{_gl(ggroups)}{'（共享）' if gfb else ''} | 上限{gmx}\n"
            f"   上次:{glr} | 下次:{gnxt}\n"
            f"🎬 影视日报: {'✅开' if men else '❌关'} 每日 {int(mh):02d}:{int(mm):02d} | 群{_gl(mgroups)}{'（共享）' if mfb else ''} | 上限{mmx}\n"
            f"   区块:{msec} | 上次:{mlr} | 下次:{mnxt}\n"
            f"📺 短剧日报: {'✅开' if den else '❌关'} 每日 {int(dh):02d}:{int(dmn):02d} | 群{_gl(dgroups)}{'（共享）' if dfb else ''} | 上限{dmx}\n"
            f"   上次:{dlr} | 下次:{dnxt}\n"
            f"🖼️ 软件图片: {'是' if ei else '否'} | 软件上限: {mx}\n"
            f"⚡ 命令: /找软件 | /找游戏 | /找短剧 | /game_report | /movie_report | /drama_report")

    # ==================== 翻页格式化 ====================

    def _format_game_page(self, s: dict) -> str:
        r=s["results"]; t=len(r); p=s.get("page",0); ps=s.get("page_size",8)
        pt=(t+ps-1)//ps; st=p*ps; ed=min(st+ps,t)
        # ★关键：头部显式写总/页数 + 翻页引导，让 LLM 看到后必须传达给用户
        lines=[f"🎮 共找到 {t} 个「{s.get('keyword','')}」相关游戏，当前第 {p+1}/{pt} 页"]
        lines.append("=" * 36)
        lines.append("")
        for i in range(st,ed):
            x=r[i]["title"]; x=(x[:45]+"...") if len(x)>48 else x; lines.append(f"{emoji_index(i-st+1, ed-st)} {x}")
        lines.append("")
        lines.append("=" * 36)
        nav = []
        if st>0: nav.append("「上一页」")
        if ed<t: nav.append("「下一页」")
        if pt>1: nav.append(f"「跳转 1~{pt}」")
        if nav:
            lines.append("💡 翻页指令： " + " ｜ ".join(nav))
        lines.append(f"⏱️ {SESSION_TIMEOUT}秒无操作自动取消。")
        lines.append("回复数字选择游戏，回复0取消。")
        return "\n".join(lines)

    def _format_sw_page(self, s: dict) -> str:
        r=s["results"]; t=len(r); p=s.get("page",0); ps=s.get("page_size",8)
        pt=(t+ps-1)//ps; st=p*ps; ed=min(st+ps,t)
        # ★关键：头部显式写总/页数 + 翻页引导，让 LLM 看到后必须传达给用户
        lines=[f"💿 共找到 {t} 个「{s.get('keyword','')}」相关资源，当前第 {p+1}/{pt} 页"]
        lines.append("=" * 36)
        lines.append("")
        for i in range(st,ed):
            x=r[i]["title"]; x=(x[:45]+"...") if len(x)>48 else x; lines.append(f"{emoji_index(i-st+1, ed-st)} {x}")
        lines.append("")
        lines.append("=" * 36)
        nav = []
        if st>0: nav.append("「上一页」")
        if ed<t: nav.append("「下一页」")
        if pt>1: nav.append(f"「跳转 1~{pt}」")
        if nav:
            lines.append("💡 翻页指令： " + " ｜ ".join(nav))
        lines.append(f"⏱️ {SESSION_TIMEOUT}秒无操作自动取消。")
        lines.append("回复数字选择资源，回复0取消。")
        return "\n".join(lines)

    def _format_mv_page(self, s: dict) -> str:
        """影视搜索列表的格式化（与软件列表风格一致）。

        每行格式：`[序号] 影视名  【类别·年份】`
        例：`[1] 怪物  【日本剧·2025】`
        """
        r = s["results"]; t = len(r); p = s.get("page", 0); ps = s.get("page_size", 8)
        pt = (t + ps - 1) // ps; st = p * ps; ed = min(st + ps, t)
        lines = [f"🎬 共找到 {t} 个「{s.get('keyword','')}」相关影视，当前第 {p+1}/{pt} 页"]
        lines.append("=" * 36)
        lines.append("")
        for i in range(st, ed):
            x = r[i]
            title = x["title"]
            title = (title[:32] + "...") if len(title) > 35 else title
            category = x.get("category", "")
            year = x.get("year", "")
            if category and year:
                tag = f" 【{category}·{year}】"
            elif category:
                tag = f" 【{category}】"
            elif year:
                tag = f" 【{year}】"
            else:
                tag = ""
            lines.append(f"{emoji_index(i - st + 1, ed - st)} {title}{tag}")
        lines.append("")
        lines.append("=" * 36)
        nav = []
        if st > 0: nav.append("「上一页」")
        if ed < t: nav.append("「下一页」")
        if pt > 1: nav.append(f"「跳转 1~{pt}」")
        if nav:
            lines.append("💡 翻页指令： " + " ｜ ".join(nav))
        lines.append(f"⏱️ {SESSION_TIMEOUT}秒无操作自动取消。")
        lines.append("回复数字选择影视，回复0取消。")
        return "\n".join(lines)

    def _format_drama_page(self, s: dict) -> str:
        """短剧搜索列表的格式化。每行：[序号] 剧名  【分类·日期】"""
        r = s["results"]; t = len(r); p = s.get("page", 0); ps = s.get("page_size", 8)
        pt = (t + ps - 1) // ps; st = p * ps; ed = min(st + ps, t)
        lines = [f"🎬 共找到 {t} 个「{s.get('keyword','')}」相关短剧，当前第 {p+1}/{pt} 页"]
        lines.append("=" * 36)
        lines.append("")
        for i in range(st, ed):
            x = r[i]
            title = x["title"]
            title = (title[:34] + "...") if len(title) > 37 else title
            tags = [x.get("category") or "短剧"]
            if x.get("date"):
                tags.append(x["date"])
            lines.append(f"{emoji_index(i - st + 1, ed - st)} {title}  【{'·'.join(tags)}】")
        lines.append("")
        lines.append("=" * 36)
        nav = []
        if st > 0: nav.append("「上一页」")
        if ed < t: nav.append("「下一页」")
        if pt > 1: nav.append(f"「跳转 1~{pt}」")
        if nav:
            lines.append("💡 翻页指令： " + " ｜ ".join(nav))
        lines.append(f"⏱️ {SESSION_TIMEOUT}秒无操作自动取消。")
        lines.append("回复数字选择短剧，回复0取消。")
        return "\n".join(lines)

    # ==================== 游戏搜索交互流程 (session_waiter) ====================

    async def _run_game_search_flow(self, event: AstrMessageEvent, keyword: str):
        """完整的游戏搜索交互流程（async generator）。
        使用 session_waiter 拦截后续用户输入，阻止 AngelHeart 介入。"""
        _blocked = self._points_guard(event, "game")
        if _blocked:
            yield event.plain_result(_blocked); return
        if not session_waiter:
            # 降级：直接发送搜索结果
            try:
                results = await asyncio.to_thread(self._g_search, keyword, 32)
            except Exception as e:
                yield event.plain_result(f"❌ 搜索失败：{str(e)[:200]}")
                return
            if not results:
                # 游戏无结果，尝试软件搜索
                try:
                    sw_results = await asyncio.to_thread(search_software, keyword, 32)
                except Exception:
                    sw_results = []
                if sw_results:
                    s = {"keyword": keyword, "results": sw_results, "page": 0, "page_size": 8}
                    _charge_txt = self._points_charge(event, "software", keyword)
                    await self._send_search_page(
                        event, "software",
                        f"🎮 游戏库未找到「{keyword}」，但在软件库找到：\n\n"
                        + self._format_sw_page(s) + _charge_txt,
                        ses=s, note=_charge_txt)
                    self._search_sessions.set(event, {"stage": "select_software", **s})
                    return
                yield event.plain_result(f"😕 未找到「{keyword}」的游戏或软件资源。")
                return
            _charge_txt = self._points_charge(event, "game", keyword)
            s = {"keyword": keyword, "results": results, "page": 0, "page_size": 8}
            await self._send_search_page(event, "game", self._format_game_page(s) + _charge_txt, ses=s, note=_charge_txt)
            self._sessions.set(event, {"stage": "select_game", **s})
            return

        config = self._get_config()
        max_results = min(int(config.get("max_search_results", 32) if isinstance(config, dict) else 32), 48)

        # 检查 xdgame Cookie
        cookie_bad = await self._g_check_cookie()
        if cookie_bad in ("expired", "invalid"):
            logger.info(f"[暮黎资源] /找游戏 '{keyword}' → Cookie {cookie_bad}，跳过游戏搜索")
            # Cookie 无效时直接尝试软件搜索
            try:
                sw_results = await asyncio.to_thread(search_software, keyword, max_results)
            except Exception:
                sw_results = []
            if sw_results:
                async for result in self._run_software_search_flow(event, keyword):
                    yield result
                return
            if self._game_source() == "switch618":
                yield event.plain_result("⚠️ 游戏资源 Cookie 未生效。\n请先联系管理员发送 /game_cookie_refresh 获取 Cookie。")
            elif cookie_bad == "expired":
                yield event.plain_result("⚠️ 游戏资源 Cookie 已失效。\n请先发送 /game_cookie_refresh 更新 Cookie。")
            else:
                yield event.plain_result("⚠️ Cookie 未配置。请先发送 /game_cookie_refresh 获取 Cookie。")
            return

        try:
            results = await asyncio.to_thread(self._g_search, keyword, max_results)
        except Exception as e:
            yield event.plain_result(f"❌ 搜索失败：{str(e)[:200]}")
            return
        if not results:
            # 游戏无结果，尝试软件搜索
            try:
                sw_results = await asyncio.to_thread(search_software, keyword, max_results)
            except Exception:
                sw_results = []
            if sw_results:
                async for result in self._run_software_search_flow(event, keyword):
                    yield result
                return
            yield event.plain_result(f"😕 未找到「{keyword}」的游戏或软件资源。")
            return

        page_size = 8
        session = {"keyword": keyword, "results": results, "page": 0,
                    "page_size": page_size, "_updated": time.time()}
        _charge_txt = self._points_charge(event, "game", keyword)
        await self._send_search_page(event, "game", self._format_game_page(session) + _charge_txt, ses=session, note=_charge_txt)

        # === 阶段 1：游戏选择 ===
        selected_game = None
        game_detail = None

        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _game_waiter(controller: SessionController, ev: AstrMessageEvent):
            nonlocal selected_game, game_detail
            text = ev.message_str.strip()
            session["_updated"] = time.time()

            # 翻页处理
            if text in ("下一页", "上一页"):
                ps = session.get("page_size", 8)
                t = len(session["results"])
                if text == "下一页":
                    session["page"] = 0 if (session.get("page", 0) + 1) * ps >= t else session.get("page", 0) + 1
                else:
                    pp = session.get("page", 0) - 1
                    session["page"] = (t + ps - 1) // ps - 1 if pp < 0 else pp
                await self._send_search_page(ev, "game", self._format_game_page(session), ses=session)
                return  # 继续等待
            if text.startswith("跳"):
                m2 = re.search(r"\d+", text)
                if m2:
                    ps = session.get("page_size", 8)
                    t = len(session["results"])
                    pt = (t + ps - 1) // ps
                    n = int(m2.group())
                    if 1 <= n <= pt:
                        session["page"] = n - 1
                        await self._send_search_page(ev, "game", self._format_game_page(session), ses=session)
                return

            # 数字选择
            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            if num == 0:
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            r = session["results"]
            p = session.get("page", 0)
            ps = session.get("page_size", 8)
            t = len(r)
            st = p * ps
            ed = min(st + ps, t)
            pc = ed - st
            if num < 1 or num > pc:
                await ev.send(MessageChain([Plain(f"请输入1-{pc}。")]))
                return

            ai = st + num - 1
            selected_game = r[ai]
            await ev.send(MessageChain([Plain(f"已选择：{selected_game['title']}\n⏳ 获取详情中...")]))

            try:
                game_detail = await asyncio.to_thread(lambda url=selected_game["url"], ck=self._get_cookie(): self._g_detail(url, self._g_cookie()))
            except Exception as e:
                await ev.send(MessageChain([Plain(f"❌ 获取失败：{str(e)[:200]}")]))
                controller.stop()
                return

            if not game_detail.get("download_links"):
                await ev.send(MessageChain([Plain("😕 该游戏暂无下载链接。")]))
                controller.stop()
                return

            # 先发详情卡，再发网盘列表
            await self._send_game_link_menu(
                ev, game_detail, selected_game, game_detail["download_links"])
            controller.stop()

        try:
            await _game_waiter(event)
        except TimeoutError:
            yield event.plain_result("⏰ 选择超时，已自动取消。")
            return

        if not selected_game or not game_detail:
            return

        # === 阶段 2：网盘选择 ===
        selected_link = None

        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _link_waiter(controller: SessionController, ev: AstrMessageEvent):
            nonlocal selected_link
            text = ev.message_str.strip()
            links = game_detail["download_links"]

            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            if num == 0:
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            # 尝试数字匹配
            if num < 1 or num > len(links):
                matched = -1
                for i, lk in enumerate(links):
                    if text in lk["pan"] or lk["pan"] in text:
                        matched = i
                        break
                if matched >= 0:
                    num = matched + 1

            if num < 1 or num > len(links):
                await ev.send(MessageChain([Plain(f"请输入 1-{len(links)} 或网盘名称。")]))
                return

            sl = links[num - 1]
            await ev.send(MessageChain([Plain(f"已选择 {sl['pan']}，解析地址中...")]))

            try:
                rlink = await asyncio.to_thread(lambda sl=sl, ck=self._get_cookie(): self._g_resolve(sl, self._g_cookie()))
            except Exception:
                rlink = sl

            gn = game_detail.get("name") or selected_game["title"]
            logger.info(f"[执行] 游戏 {gn} url={rlink.get('real_url', '')[:40]}")
            await self._send_download_link(
                ev, gn, rlink.get("pan", "下载链接"), rlink.get("real_url", ""),
                code=rlink.get("code", ""), password=rlink.get("password", ""),
                source_name="暮黎游戏", kind="game")

            selected_link = rlink
            controller.stop()

        try:
            await _link_waiter(event)
        except TimeoutError:
            yield event.plain_result("⏰ 选择超时，已自动取消。")

    # ==================== 软件搜索交互流程 (session_waiter) ====================

    async def _run_software_search_flow(self, event: AstrMessageEvent, keyword: str):
        """完整的软件搜索交互流程（async generator）。"""
        _blocked = self._points_guard(event, "software")
        if _blocked:
            yield event.plain_result(_blocked); return
        if not session_waiter:
            try:
                results = await asyncio.to_thread(search_software, keyword, 32)
            except Exception as e:
                yield event.plain_result(f"❌ 搜索失败：{str(e)[:200]}")
                return
            if not results:
                # 软件无结果，尝试游戏搜索
                try:
                    gm_results = await asyncio.to_thread(self._g_search, keyword, 32)
                except Exception:
                    gm_results = []
                if gm_results:
                    s = {"keyword": keyword, "results": gm_results, "page": 0, "page_size": 8}
                    _charge_txt = self._points_charge(event, "game", keyword)
                    await self._send_search_page(
                        event, "game",
                        f"💿 软件库未找到「{keyword}」，但在游戏库找到：\n\n"
                        + self._format_game_page(s) + _charge_txt,
                        ses=s, note=_charge_txt)
                    self._sessions.set(event, {"stage": "select_game", **s})
                    return
                yield event.plain_result(f"😕 未找到「{keyword}」的软件或游戏资源。")
                return
            _charge_txt = self._points_charge(event, "software", keyword)
            s = {"keyword": keyword, "results": results, "page": 0, "page_size": 8}
            await self._send_search_page(event, "software", self._format_sw_page(s) + _charge_txt, ses=s, note=_charge_txt)
            self._search_sessions.set(event, {"stage": "select_software", **s})
            return

        config = self._get_config()
        max_results = min(int(config.get("max_search_results", 32) if isinstance(config, dict) else 32), 48)

        try:
            results = await asyncio.to_thread(search_software, keyword, max_results)
        except Exception as e:
            yield event.plain_result(f"❌ 搜索失败：{str(e)[:200]}")
            return
        if not results:
            # 软件无结果，尝试游戏搜索
            try:
                gm_results = await asyncio.to_thread(self._g_search, keyword, max_results)
            except Exception:
                gm_results = []
            if gm_results:
                async for result in self._run_game_search_flow(event, keyword):
                    yield result
                return
            yield event.plain_result(f"😕 未找到「{keyword}」的软件或游戏资源。")
            return

        page_size = 8
        session = {"keyword": keyword, "results": results, "page": 0,
                    "page_size": page_size, "_updated": time.time()}
        _charge_txt = self._points_charge(event, "software", keyword)
        await self._send_search_page(event, "software", self._format_sw_page(session) + _charge_txt, ses=session, note=_charge_txt)

        # === 阶段 1：软件选择 ===
        selected_sw = None
        sw_detail = None

        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _sw_waiter(controller: SessionController, ev: AstrMessageEvent):
            nonlocal selected_sw, sw_detail
            text = ev.message_str.strip()
            session["_updated"] = time.time()

            if text in ("下一页", "上一页"):
                ps = session.get("page_size", 8)
                t = len(session["results"])
                if text == "下一页":
                    session["page"] = 0 if (session.get("page", 0) + 1) * ps >= t else session.get("page", 0) + 1
                else:
                    pp = session.get("page", 0) - 1
                    session["page"] = (t + ps - 1) // ps - 1 if pp < 0 else pp
                await self._send_search_page(ev, "software", self._format_sw_page(session), ses=session)
                return
            if text.startswith("跳"):
                m2 = re.search(r"\d+", text)
                if m2:
                    ps = session.get("page_size", 8)
                    t = len(session["results"])
                    pt = (t + ps - 1) // ps
                    n = int(m2.group())
                    if 1 <= n <= pt:
                        session["page"] = n - 1
                        await self._send_search_page(ev, "software", self._format_sw_page(session), ses=session)
                return

            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            if num == 0:
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            r = session["results"]
            p = session.get("page", 0)
            ps = session.get("page_size", 8)
            t = len(r)
            st = p * ps
            ed = min(st + ps, t)
            pc = ed - st
            if num < 1 or num > pc:
                await ev.send(MessageChain([Plain(f"请输入1-{pc}。")]))
                return

            ai = st + num - 1
            selected_sw = r[ai]
            await ev.send(MessageChain([Plain(f"已选择：{selected_sw['title']}\n⏳ 获取详情中...")]))

            try:
                sw_detail = await asyncio.to_thread(get_search_detail, selected_sw["url"])
            except Exception as e:
                await ev.send(MessageChain([Plain(f"❌ 获取失败：{str(e)[:200]}")]))
                controller.stop()
                return

            if not sw_detail.get("download_links"):
                await ev.send(MessageChain([Plain("😕 该资源暂无下载链接。")]))
                controller.stop()
                return

            await self._send_software_link_menu(
                ev, sw_detail, selected_sw, sw_detail["download_links"])
            controller.stop()

        try:
            await _sw_waiter(event)
        except TimeoutError:
            yield event.plain_result("⏰ 选择超时，已自动取消。")
            return

        if not selected_sw or not sw_detail:
            return

        # === 阶段 2：网盘选择 ===
        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _sw_link_waiter(controller: SessionController, ev: AstrMessageEvent):
            text = ev.message_str.strip()
            links = sw_detail["download_links"]

            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            if num == 0:
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            if num < 1 or num > len(links):
                matched = -1
                for i, lk in enumerate(links):
                    if text in lk["pan"] or lk["pan"] in text:
                        matched = i
                        break
                if matched >= 0:
                    num = matched + 1

            if num < 1 or num > len(links):
                await ev.send(MessageChain([Plain(f"请输入 1-{len(links)} 或网盘名称。")]))
                return

            sl = links[num - 1]
            await ev.send(MessageChain([Plain(f"已选择 {sl['pan']}，处理中...")]))

            sn = sw_detail.get("name") or selected_sw["title"]
            logger.info(f"[执行] 软件 {sn} url={(sl.get('url') or '')[:50]}")
            await self._send_download_link(
                ev, sn, sl.get("pan", "下载链接"), sl.get("url", ""),
                source_name="暮黎软件", kind="software")

            controller.stop()

        try:
            await _sw_link_waiter(event)
        except TimeoutError:
            yield event.plain_result("⏰ 选择超时，已自动取消。")

    # ==================== 影视搜索交互流程 ====================

    async def _run_movie_search_flow(self, event: AstrMessageEvent, keyword: str):
        """完整的影视搜索交互流程：
        搜索 → 选影视 → 选集数（剧时）→ 选线路 → 合并转发
        """
        _blocked = self._points_guard(event, "movie")
        if _blocked:
            yield event.plain_result(_blocked); return
        tag = "【暮黎资源】"

        # 第一步：搜索
        try:
            results = await asyncio.to_thread(search_movies, keyword, 24)
        except Exception as e:
            yield event.plain_result(f"{tag} 搜索失败：{str(e)[:200]}")
            return
        if not results:
            yield event.plain_result(f"😕 未找到与「{keyword}」相关的影视。")
            return

        page_size = 8
        session = {"keyword": keyword, "results": results, "page": 0,
                   "page_size": page_size, "_updated": time.time()}
        _charge_txt = self._points_charge(event, "movie", keyword)
        await self._send_search_page(event, "movie", self._format_mv_page(session) + _charge_txt, ses=session, note=_charge_txt)

        # 第二步：用户选影视
        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _mv_select_waiter(controller: SessionController, ev: AstrMessageEvent):
            nonlocal session
            text = ev.message_str.strip()
            session["_updated"] = time.time()

            # 翻页
            if text in ("下一页", "上一页"):
                ps = session.get("page_size", 8)
                t = len(session["results"])
                cur = session.get("page", 0)
                if text == "下一页":
                    session["page"] = 0 if (cur + 1) * ps >= t else cur + 1
                else:
                    pp = cur - 1
                    session["page"] = (t + ps - 1) // ps - 1 if pp < 0 else pp
                await self._send_search_page(ev, "movie", self._format_mv_page(session), ses=session)
                return
            if text.startswith("跳"):
                m2 = re.search(r"\d+", text)
                if m2:
                    ps = session.get("page_size", 8)
                    t = len(session["results"])
                    pt = (t + ps - 1) // ps
                    n = int(m2.group())
                    if 1 <= n <= pt:
                        session["page"] = n - 1
                        await self._send_search_page(ev, "movie", self._format_mv_page(session), ses=session)
                return

            # 取消
            if text in ("0", "取消", "算", "不要"):
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            # 数字选择
            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            r = session["results"]
            p = session.get("page", 0)
            ps = session.get("page_size", 8)
            t = len(r); st = p * ps; ed = min(st + ps, t); pc = ed - st
            if num < 1 or num > pc:
                await ev.send(MessageChain([Plain(f"请输入1-{pc}之间的数字。回复0取消。")]))
                return

            ai = st + num - 1
            sel = r[ai]
            await ev.send(MessageChain([Plain(f"已选择：{sel['title']}\n⏳ 获取详情中...")]))

            try:
                detail = await asyncio.to_thread(get_movie_detail, sel["url"])
            except Exception as e:
                await ev.send(MessageChain([Plain(f"❌ 获取详情失败：{str(e)[:200]}")]))
                controller.stop()
                return

            if not detail.get("sources"):
                await ev.send(MessageChain([Plain("😕 该影视暂无播放线路。")]))
                controller.stop()
                return

            # 把结果存到 session_waiter 闭包外的 dict（用 _movie_sessions）
            self._movie_sessions.set(ev, {
                "stage": "select_movie_done",
                "keyword": keyword,
                "selected": sel,
                "detail": detail,
                "_updated": time.time(),
            })

            # 第三步：判断是否需要选集数
            if detail.get("is_series") and detail.get("episodes"):
                # 展示集数
                eps_text = format_episodes(detail, max_show=30)
                await ev.send(MessageChain([Plain(eps_text)]))
                self._movie_sessions.update(ev, stage="select_episode")
                return  # 不停 controller，继续等用户选集
            else:
                # 电影：直接展示线路
                src_text = format_sources(detail, page=0, page_size=15)
                await ev.send(MessageChain([Plain(src_text)]))
                self._movie_sessions.update(ev, stage="select_source")
                return

        try:
            await _mv_select_waiter(event)
        except TimeoutError:
            yield event.plain_result("⏰ 选择超时，已自动取消。")
            return

        # 第三步：用户选集数（仅剧）
        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _mv_episode_waiter(controller: SessionController, ev: AstrMessageEvent):
            text = ev.message_str.strip()
            ses = self._movie_sessions.get(ev)
            if not ses:
                controller.stop()
                return
            detail = ses.get("detail", {})
            eps = detail.get("episodes", [])

            if text in ("0", "取消", "算", "不要"):
                self._movie_sessions.delete(ev)
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            if num < 1 or num > len(eps):
                await ev.send(MessageChain([Plain(f"请输入1-{len(eps)}之间的数字。回复0取消。")]))
                return
            ep = eps[num - 1]
            self._movie_sessions.update(ev, episode=ep)

            # 进入选线路阶段
            self._movie_sessions.update(ev, source_page=0, stage="select_source")
            src_text = format_sources(detail, page=0, page_size=15)
            await ev.send(MessageChain([Plain(src_text)]))
            controller.stop()

        ses = self._movie_sessions.get(event)
        if not ses:
            return
        if ses.get("stage") == "select_episode":
            try:
                await _mv_episode_waiter(event)
            except TimeoutError:
                yield event.plain_result("⏰ 选集超时，已自动取消。")
                return

        # 第四步：用户选线路 → 合并转发（v1.7.5: 支持翻页 + 用 ep.url 拿 m3u8）
        @session_waiter(timeout=SESSION_TIMEOUT)
        async def _mv_source_waiter(controller: SessionController, ev: AstrMessageEvent):
            text = ev.message_str.strip()
            ses = self._movie_sessions.get(ev)
            if not ses:
                controller.stop()
                return
            detail = ses.get("detail", {})
            srcs = detail.get("sources", [])
            sel = ses.get("selected", {})
            ep = ses.get("episode")
            page = ses.get("source_page", 0)
            ps = 15
            total = len(srcs)
            pt = (total + ps - 1) // ps
            page = max(0, min(page, pt - 1))
            st = page * ps
            ed = min(st + ps, total)
            show_count = ed - st

            if text in ("0", "取消", "算", "不要"):
                self._movie_sessions.delete(ev)
                await ev.send(MessageChain([Plain("已取消。")]))
                controller.stop()
                return

            # 翻页
            if text in ("下一页", "下一页线路"):
                if page + 1 >= pt:
                    await ev.send(MessageChain([Plain(f"已经是最后一页（第 {pt}/{pt} 页）啦~")]))
                    return
                self._movie_sessions.update(ev, source_page=page + 1)
                await ev.send(MessageChain([Plain(format_sources(detail, page=page + 1, page_size=ps))]))
                return
            if text in ("上一页", "上一页线路"):
                if page <= 0:
                    await ev.send(MessageChain([Plain("已经是第一页啦~")]))
                    return
                self._movie_sessions.update(ev, source_page=page - 1)
                await ev.send(MessageChain([Plain(format_sources(detail, page=page - 1, page_size=ps))]))
                return

            m2 = re.search(r"\d+", text)
            num = int(m2.group()) if m2 else 0
            if num < 1 or num > show_count:
                await ev.send(MessageChain([Plain(f"请输入1-{show_count}之间的数字（当前第{page+1}/{pt}页共{show_count}条线路）。回复0取消。")]))
                return
            # ★Bug D fix: 用全局索引 srcs[st+num-1]
            global_idx = st + num - 1
            src = srcs[global_idx]
            ep_tag = f" 第{ep['n']}集" if ep else ""
            # ★Bug D fix: 用 ep.url (用户选的那集) 拿 m3u8
            real_url = src["url"]
            line_name = ""
            try:
                play_url = ep["url"] if ep else src["url"]
                play = await asyncio.to_thread(parse_play_page, play_url)
                if play and play.get("lines"):
                    target_ld = ""
                    for ln in play["lines"]:
                        if ln["name"] == f"线路{src['n']}" or str(src['n']) in ln["name"]:
                            target_ld = ln["ld"]
                            break
                    if not target_ld and src['n'] and 1 <= src['n'] <= len(play["lines"]):
                        target_ld = play["lines"][src['n'] - 1]["ld"]
                    if target_ld:
                        for ln in play["lines"]:
                            if ln["ld"] == target_ld:
                                real_url = ln["m3u8"]
                                line_name = ln["name"]
                                break
            except Exception as e:
                logger.warning(f"[暮黎资源] parse_play_page 失败: {e}")
            chosen_url = real_url
            if not chosen_url or "/v/" in chosen_url:
                chosen_url = src["url"]
            name = detail.get("name") or sel.get("title", "未知影视")
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)[:30]
            gid = ev.get_group_id()
            uid = ev.get_sender_id()
            logger.info(f"[执行] 影视(session_waiter) {name}{ep_tag} → 线路{num}/{total} (m3u8={chosen_url[:60]})")

            # ★Feature 4: LLM 查百度百科
            cast = ""
            desc_brief = ""
            try:
                cast, desc_brief = await self._fetch_movie_meta_via_llm(ev, name)
            except Exception as e:
                logger.warning(f"[暮黎资源] LLM 查百科失败: {e}")

            await self._send_movie_record(ev, name, ep, src,
                                          line_name or src.get('label', f'线路{num}'),
                                          cast, desc_brief, chosen_url, gid, uid)
            self._movie_sessions.delete(ev)
            controller.stop()

        ses = self._movie_sessions.get(event)
        if not ses:
            return
        if ses.get("stage") == "select_source":
            try:
                await _mv_source_waiter(event)
            except TimeoutError:
                yield event.plain_result("⏰ 选线路超时，已自动取消。")

    # ==================== 影视辅助：LLM 查百度百科 + 合转发 ====================

    async def _fetch_movie_meta_via_llm(self, event: AstrMessageEvent, movie_name: str):
        """调用 LLM 让它查百度百科 → 返回 (主演, 简介)。失败时返回 ("", "")。

        使用 AstrBot 的统一 LLM 入口：
        - v4.5.7+ : context.get_current_chat_provider_id() + context.llm_generate()
        - 旧版 : context.get_using_provider().text_chat()
        """
        if not movie_name:
            return ("", "")
        umo = getattr(event, "unified_msg_origin", None)
        sys_prompt = (
            "你是一名影视资料助手。请联网查「百度百科」或「维基百科」,"
            "根据用户给你的影视名, 给出 (1) 主演 (2) 一句话简介(80字内)。"
            "严格按照 JSON 格式输出, 不要输出其它任何文字。"
            '输出: {"cast": "主演A、主演B、主演C", "desc": "一句话简介"}'
        )
        user_prompt = f"影视名: {movie_name}"

        # 优先 v4.5.7+ 新 API
        try:
            if hasattr(self.context, "get_current_chat_provider_id") and hasattr(self.context, "llm_generate"):
                pid = await self.context.get_current_chat_provider_id(umo=umo)
                if pid:
                    resp = await self.context.llm_generate(
                        chat_provider_id=pid, prompt=user_prompt, system_prompt=sys_prompt)
                    text = getattr(resp, "completion_text", None) or str(resp)
                    return _parse_movie_meta_json(text)
        except Exception as e:
            logger.debug(f"[暮黎资源] LLM v4.5.7+ API 失败: {e}")

        # 兜底：旧版 API
        try:
            if hasattr(self.context, "get_using_provider"):
                provider = self.context.get_using_provider(umo)
                if provider and hasattr(provider, "text_chat"):
                    resp = await provider.text_chat(prompt=user_prompt, system_prompt=sys_prompt, persist=False)
                    text = getattr(resp, "completion_text", None) or str(resp)
                    return _parse_movie_meta_json(text)
        except Exception as e:
            logger.warning(f"[暮黎资源] LLM 查百科失败 ({movie_name}): {e}")
        return ("", "")

    # ==================== 搜索关键词审核（大模型涉黄/违禁判定） ====================

    # 本地硬屏蔽词：明显涉黄/违禁，无需调用大模型直接拦截（省开销、更稳、零延迟）。
    # 仅作“保底”快速过滤；其余判定交给下方大模型审核。
    _AUDIT_BLOCK_WORDS = (
        "色情", "裸聊", "约炮", "黄片", "做爱", "性交", "性爱", "援交",
        "裸体", "春药", "淫秽", "嫖娼", "一夜情", "福利姬", "里番", "工口",
        "巨乳", "萝莉", "调教", "成人", "av", "av女优", "性交",
    )

    async def _audit_search_keyword(self, event: AstrMessageEvent, keyword: str):
        """调用大模型审核搜索关键词是否涉黄/违禁，并判断用户搜索意图。

        返回 (allowed: bool, reason: str, intent: str)。
        - 命中本地硬屏蔽词 → 直接判定为违禁（allowed=False），不消耗大模型额度。
        - 大模型显式判定 allowed=False → 拦截。
        - 大模型调用失败/不可用 → fail-open（放行），仅记录日志，
          避免大模型异常把正常的资源搜索功能拖垮。
        """
        kw = (keyword or "").strip()
        if not kw:
            return True, "", ""
        # 1) 本地硬屏蔽（快速、零延迟）
        low = kw.lower()
        for w in self._AUDIT_BLOCK_WORDS:
            if w.lower() in low:
                logger.info(f"[暮黎资源] 关键词「{kw}」命中本地违禁词，已拦截")
                return False, f"搜索关键词「{kw}」疑似涉及违规内容，已被拦截。", "违规内容"
        # 2) 大模型审核（判断是否涉黄/违禁 + 用户搜索意图）
        umo = getattr(event, "unified_msg_origin", None)
        sys_prompt = (
            "你是一名内容安全审核员。用户将在网络资源站搜索某个关键词，"
            "请判断该关键词是否涉及色情、淫秽、成人内容（涉黄）或其它明显违禁内容；"
            "同时简要判断用户的搜索意图（想找什么类型的资源）。\n"
            "只输出一行 JSON，不要任何其它文字：\n"
            '{"allowed": true 或 false, "reason": "简短理由", "intent": "搜索意图"}'
        )
        user_prompt = f"搜索关键词：{kw}"
        try:
            if hasattr(self.context, "get_current_chat_provider_id") and hasattr(self.context, "llm_generate"):
                pid = await self.context.get_current_chat_provider_id(umo=umo)
                if pid:
                    resp = await self.context.llm_generate(
                        chat_provider_id=pid, prompt=user_prompt, system_prompt=sys_prompt)
                    text = getattr(resp, "completion_text", None) or str(resp)
                    return _parse_audit_json(text)
        except Exception as e:
            logger.debug(f"[暮黎资源] 关键词审核(新API)失败: {e}")
        try:
            if hasattr(self.context, "get_using_provider"):
                provider = self.context.get_using_provider(umo)
                if provider and hasattr(provider, "text_chat"):
                    resp = await provider.text_chat(prompt=user_prompt, system_prompt=sys_prompt, persist=False)
                    text = getattr(resp, "completion_text", None) or str(resp)
                    return _parse_audit_json(text)
        except Exception as e:
            logger.warning(f"[暮黎资源] 关键词审核(旧API)失败: {e}")
        # fail-open：大模型不可用时不阻断正常搜索
        return True, "", ""

    async def _send_movie_record(self, event: AstrMessageEvent,
                                  name: str, ep, src: dict,
                                  line_name: str, cast: str,
                                  desc: str, chosen_url: str,
                                  gid: str = "", uid: str = ""):
        """群聊：合转发 (标题+集数+线路+演员+简介+直链+封面)。
        私聊：发送 HTML 文件。

        v1.7.5 调整: 移除 region, 简介由 LLM 查百度百科补全。
        """
        ep_tag = f" 第{ep['n']}集" if ep else ""
        if gid:
            detail_obj = self._movie_sessions.get(event)
            detail = dict(detail_obj.get("detail", {}) if detail_obj else {})
            detail["name"] = name or detail.get("name") or "未知影视"
            if desc:
                detail["desc"] = desc
            if cast and not detail.get("zhuyan"):
                detail["zhuyan"] = [cast]
            await self._send_movie_merged(
                event, detail, chosen_url,
                f"{line_name}{ep_tag}".strip(),
                referer=MV_BASE_URL + "/")
        elif uid:
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)[:30]
            link = {"pan": "在线播放", "url": chosen_url, "real_url": chosen_url}
            detail_obj = self._movie_sessions.get(event)
            detail = detail_obj.get("detail", {}) if detail_obj else {}
            screenshots = detail.get("screenshots") or ([detail["cover"]] if detail.get("cover") else [])
            hc = await asyncio.to_thread(generate_search_html, name + ep_tag,
                                          desc or detail.get("desc") or "",
                                          detail.get("cover") or "",
                                          screenshots, link,
                                          (detail_obj.get("keyword", "") if detail_obj else ""))
            fd, tp = tempfile.mkstemp(suffix=f"_{safe_name}.html", prefix="mv_")
            os.close(fd)
            with open(tp, "w", encoding="utf-8") as f:
                f.write(hc)
            fn = f"{safe_name}.html"
            cl = self._get_best_client(event)
            if cl:
                with open(tp, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                if str(uid).isdigit():
                    await cl.call_action(action="upload_private_file",
                                         user_id=int(uid),
                                         file=f"base64://{b64}", name=fn)
                else:
                    await self.context.send_message(
                        f"{event.get_platform_id()}:FriendMessage:{uid}",
                        MessageChain([FileComponent(file=tp, name=fn)]))
            else:
                await self.context.send_message(
                    f"{event.get_platform_id()}:FriendMessage:{uid}",
                    MessageChain([Plain(f"📄 {name}{ep_tag}\n\n🔗 {chosen_url}"),
                                  FileComponent(file=tp, name=fn)]))
            if os.path.exists(tp):
                try: os.unlink(tp)
                except Exception: pass

    # ==================== 网易云 → QQ 语音名片（v1.9.0 新增） ====================

    def _wyy_components(self, event):
        """安全获取消息组件列表（用于识别小程序分享卡片）。"""
        try:
            obj = getattr(event, "message_obj", None)
            if obj is not None:
                msgs = getattr(obj, "message", None)
                if isinstance(msgs, list):
                    return msgs
        except Exception:
            pass
        if hasattr(event, "get_messages"):
            try:
                return event.get_messages() or []
            except Exception:
                pass
        return []

    # ==================== VIP 视频解析（交互式选接口） ====================

    @filter.event_message_type(filter.EventMessageType.ALL, priority=3)
    async def on_vip_video(self, event: AstrMessageEvent):
        """识别消息中的 VIP 视频链接（爱奇艺/腾讯/优酷/芒果等，含分享卡片），
        先获取影视信息并展示命名解析接口菜单，等用户回复序号后返回解析直链。
        不做 HLS 代理 / VLC 备选。"""
        cfg = self._get_config()
        if not cfg.get("video_vip_parse", True):
            return
        text = (event.message_str or "").strip()
        if text.startswith("/"):
            return
        umo = event.unified_msg_origin

        # 清理过期待选会话（5 分钟）
        now = time.time()
        for k in [k for k, v in self._vip_pending.items() if now - v.get("ts", 0) > 300]:
            self._vip_pending.pop(k, None)

        # 1) 有待选会话：把本条消息当作「接口选择」
        if umo in self._vip_pending:
            event.stop_event()
            p = self._vip_pending.get(umo)
            sel = text.strip()
            if re.fullmatch(r"\d{1,2}", sel):
                await self._handle_vip_selection(event, umo, int(sel))
            elif sel in ("/cancel", "取消", "cancel"):
                self._vip_pending.pop(umo, None)
                await event.send(MessageChain([Plain("已取消 VIP 解析。")]))
            else:
                # 超时自动取消；超时前忽略非序号消息，不再强硬反复催促用户
                if time.time() - (p or {}).get("ts", 0) > 300:
                    self._vip_pending.pop(umo, None)
                    await event.send(MessageChain([Plain(
                        "⏰ VIP 解析等待超时，已自动取消。如需解析请重新发送视频链接。")]))
            return

        # 2) 新链接：先尝试 message_str，再遍历消息组件（QQ 分享卡片 ComponentType.Json 的 message_str 为空）
        link = None
        card_meta = {}  # 卡片自带的标题/简介/封面
        if text:
            link = is_vip_video_url(text)
        if not link and Json is not None:
            for comp in self._wyy_components(event):
                if isinstance(comp, Json):
                    jdata = getattr(comp, "data", None)
                    if jdata is None:
                        continue
                    # 解析卡片 JSON，提取 URL 和元数据
                    if isinstance(jdata, dict):
                        jdict = jdata
                    else:
                        try:
                            jdict = json.loads(str(jdata))
                        except Exception:
                            jdict = {}
                    jstr = json.dumps(jdict, ensure_ascii=False) if jdict else str(jdata)
                    link = is_vip_video_url(jstr)
                    if link:
                        # 从卡片 JSON 提取自带元数据（title/desc/cover）
                        card_meta = self._extract_card_meta(jdict)
                        break
        if not link:
            return
        event.stop_event()
        await self._handle_vip_link(event, link, cfg, prefill=card_meta)

    # 平台名称列表（用于判断卡片 title 是否只是平台名而非视频标题）
    _PLATFORM_NAMES = {"腾讯视频", "芒果tv", "芒果TV", "优酷", "爱奇艺"}

    def _extract_card_meta(self, jdict: dict) -> dict:
        """从分享卡片 JSON 提取自带的标题/简介/封面。

        卡片结构因平台而异：
        - 优酷/爱奇艺：meta.news.{title, desc, preview}
        - 腾讯/芒果：meta.detail_1.{title, desc, preview}（title 常为平台名，desc 才是视频名）

        返回 {"title", "desc", "cover"}；未提取到则对应字段为空。
        """
        out = {"title": "", "desc": "", "cover": ""}
        if not isinstance(jdict, dict):
            return out
        meta = jdict.get("meta") or {}
        # 优先 meta.news，其次 meta.detail_1
        node = meta.get("news") or meta.get("detail_1") or {}
        if not isinstance(node, dict):
            node = {}
        title = (node.get("title") or jdict.get("title") or "").strip()
        desc = (node.get("desc") or jdict.get("desc") or "").strip()
        cover = (node.get("preview") or node.get("picture") or
                 node.get("image") or jdict.get("preview") or "").strip()
        # 如果 title 只是平台名（如"腾讯视频"），用 desc 作为标题
        if title and title.strip() in self._PLATFORM_NAMES:
            if desc:
                title, desc = desc, ""
        # HTML 实体反转义
        import html as _html
        if title:
            title = _html.unescape(title)
        if desc:
            desc = _html.unescape(desc)
        out["title"] = title
        out["desc"] = desc
        out["cover"] = cover
        return out

    def _vip_interface_cache_path(self) -> str:
        return os.path.join(self._plugin_data_dir(), "vip_interfaces.json")

    def _load_vip_interface_cache(self):
        """载入上次从片库 /zjx 抓到的接口列表（15 分钟内直接复用）。"""
        try:
            path = self._vip_interface_cache_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items") or []
            clean = []
            for x in items:
                if (isinstance(x, (list, tuple)) and len(x) == 2
                        and str(x[1]).startswith("http")):
                    clean.append((str(x[0]), str(x[1])))
            if clean:
                self._vip_interfaces = clean
                self._vip_if_ts = float(data.get("ts") or 0)
                logger.info(f"[VIP] 已载入接口缓存 {len(clean)} 个")
        except Exception as e:
            logger.debug(f"[VIP] 读取接口缓存失败: {e}")

    def _save_vip_interface_cache(self):
        try:
            path = self._vip_interface_cache_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ts": self._vip_if_ts,
                           "items": [list(x) for x in self._vip_interfaces]},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[VIP] 保存接口缓存失败: {e}")

    async def _refresh_vip_interfaces(self, cfg: dict = None, force: bool = False) -> list:
        """从片库主站 /zjx 实时获取接口列表（15 分钟缓存，失败回退内置）。"""
        ttl = 900
        if not self._vip_interfaces:
            self._load_vip_interface_cache()
        if not force and self._vip_interfaces and time.time() - self._vip_if_ts < ttl:
            return list(self._vip_interfaces)
        if self._vip_if_lock is None:
            self._vip_if_lock = asyncio.Lock()
        async with self._vip_if_lock:
            if not force and self._vip_interfaces and time.time() - self._vip_if_ts < ttl:
                return list(self._vip_interfaces)
            cfg = cfg or self._get_config() or {}
            channel = str(cfg.get("browser_channel") or "").strip()
            exe = str(cfg.get("browser_exe") or "").strip()
            timeout = int(cfg.get("video_vip_timeout", 20000) or 20000)
            if timeout < 1000:
                timeout *= 1000
            live = await fetch_muliy_interfaces(
                timeout_ms=max(20000, min(timeout, 45000)),
                channel=channel, exe=exe)
            if live:
                # TXNQ / 冰豆 优先，七哥放后面；M1907/789 永远置顶
                def _rank(item):
                    n = item[0]
                    if "TXNQ" in n.upper():
                        return 0
                    if "冰豆" in n:
                        return 1
                    if "七哥" in n:
                        return 9
                    return 5
                live_sorted = sorted(live, key=_rank)
                preferred = [x for x in VIP_INTERFACES if x[0] in ("M1907", "789")]
                merged, seen, seen_names = [], set(), set()
                for name, tpl in preferred + live_sorted + list(VIP_INTERFACES):
                    key = str(tpl).rstrip("/")
                    base = str(name).replace("解析", "").strip()
                    if not key or key in seen or base in seen_names:
                        continue
                    seen.add(key)
                    seen_names.add(base)
                    merged.append((name, tpl))
                self._vip_interfaces = merged
                self._vip_if_ts = time.time()
                self._save_vip_interface_cache()
                logger.info(f"[VIP] 接口已更新（片库 /zjx）：{[n for n, _ in merged]}")
            elif not self._vip_interfaces:
                self._vip_interfaces = list(VIP_INTERFACES)
                self._vip_if_ts = time.time()
            return list(self._vip_interfaces)

    def _get_interfaces(self, cfg: dict) -> list:
        """返回当前解析接口列表（片库 /zjx 实时列表优先，失败回退内置）。"""
        return list(self._vip_interfaces or VIP_INTERFACES)

    async def _handle_vip_link(self, event, link: str, cfg: dict, prefill: dict = None):
        """分析链接 → 规范化 URL → 取标题 → 展示接口菜单。"""
        import urllib.parse as _up
        link = _up.unquote(link)
        try:
            await event.send(MessageChain([Plain("🎞️ 识别到 VIP 视频链接，正在获取影视信息…")]))
        except Exception:
            pass
        timeout = int(cfg.get("video_vip_timeout", 20000) or 20000)
        if timeout < 1000:
            timeout = timeout * 1000
        channel = (cfg.get("browser_channel") or "").strip()
        exe = ""  # video_vip_browser_path 配置已移除，统一自动探测浏览器
        proxy = ""  # video_vip_proxy 配置已移除，统一走环境代理自动探测

        # 卡片自带的元数据（优先使用，不走网络请求）
        pf = prefill or {}
        title = pf.get("title", "")
        cover = pf.get("cover", "")
        desc = pf.get("desc", "")

        # ── 1) 爱奇艺分享卡片：优先 API 转换（最快最可靠）──
        if is_iqiyi_share_url and is_iqiyi_share_url(link) and resolve_iqiyi_share:
            try:
                # resolve_iqiyi_share 内部走 urllib.request 同步网络，必须放到线程避免阻塞事件循环
                r = await asyncio.to_thread(resolve_iqiyi_share, link, proxy=proxy)
                if r.get("ok") and r.get("clean_url"):
                    link = r["clean_url"]
                    if not title:
                        title = r.get("title", "")
                    if not cover:
                        cover = r.get("cover", "")
                    logger.info(f"[VIP] 爱奇艺分享(API)已转纯净播放页: {link}")
                else:
                    logger.warning(f"[VIP] 爱奇艺分享(API)转换失败: {r.get('error')}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[VIP] resolve_iqiyi_share 异常: {e}")

        # ── 2) 多平台 URL 规范化（重定向跟随 + 格式标准化）──
        try:
            # normalize_video_url 内部走 urllib.request 同步网络（follow_video_redirect），放入线程执行
            normalized = await asyncio.to_thread(normalize_video_url, link, proxy=proxy)
            if normalized and normalized != link:
                logger.info(f"[VIP] URL 规范化: {link[:60]} -> {normalized[:60]}")
                link = normalized
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[VIP] URL 规范化失败(非致命): {e}")

        # ── 3) 获取标题（卡片已有→用卡片；没有→HTTP OG；再没有→浏览器兜底）──
        if not title:
            try:
                og_title, og_desc, og_cover = await asyncio.to_thread(
                    self._fetch_og_meta, link, proxy)
                if og_title:
                    title = og_title
                if og_desc and not desc:
                    desc = og_desc
                if og_cover and not cover:
                    cover = og_cover
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[VIP] OG 抓取失败: {e}")

        # OG 没取到标题 / 只取到平台名 → 浏览器兜底（腾讯、优酷等常见）
        _generic_title = (
            not title
            or title.strip() in self._PLATFORM_NAMES
            or any(k in title for k in ("在线视频网站", "海量正版", "高清完整版视频在线观看"))
        )
        if _generic_title:
            try:
                info = await analyze_vip_link(link, proxy=proxy, timeout_ms=timeout,
                                              channel=channel, exe=exe)
                if info.get("title"):
                    title = info["title"]
                if info.get("poster_url") and not cover:
                    cover = info["poster_url"]
            except Exception as e:  # noqa: BLE001
                logger.error(f"[VIP] 浏览器分析异常: {e}")

        # 标题清理：去掉「_电视剧_高清完整版视频在线观看_腾讯视频」这类后缀
        if title:
            title = re.sub(
                r"[_\-|](高清完整版视频在线观看|在线观看|电视剧|电影|综艺|动漫)[_\-|].*$",
                "", title).strip() or title

        interfaces = await self._refresh_vip_interfaces(cfg)
        umo = event.unified_msg_origin
        self._vip_pending[umo] = {
            "clean_url": link,
            "raw": link,
            "title": title,
            "desc": desc,
            "poster_url": cover,
            "poster_path": "",
            "resolved": True,
            "interfaces": interfaces,
            "ts": time.time(),
        }
        # 启动后台超时自动取消（用户不回复时将主动取消并提示，无需反复催促）
        try:
            asyncio.create_task(self._vip_timeout_cancel(umo, self._vip_pending[umo]["ts"]))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[VIP] 启动超时取消任务失败: {e}")

        # 组装菜单 — 仅标题 + 操作提示 + 接口列表
        title_disp = title or "（未获取到标题）"
        lines = [
            "🎬 影视解析",
            f"━━━━━━━━━━━━━━",
            f"📺 {title_disp}",
            f"━━━━━━━━━━━━━━",
            "请回复序号选择解析接口：",
        ]
        for i, (name, _t) in enumerate(interfaces, 1):
            rec = " ⭐" if name in ("M1907", "789") else ""
            lines.append(f"  {emoji_index(i, len(interfaces))} {name}{rec}")
        lines.append("")
        lines.append("⭐ M1907 / 789 为实测可用；接口列表实时取自片库 /zjx，失效自动换下一个")
        lines.append("💡 回复数字选择接口，发送「取消」可退出")
        await event.send(MessageChain([Plain("\n".join(lines))]))

    def _fetch_og_meta(self, url: str, proxy: str = "") -> tuple:
        """快速 HTTP GET 抓取播放页的 OG 标题/简介/封面（不走浏览器，1-2 秒）。

        返回 (title, desc, cover)；失败返回 ("", "", "")。
        """
        if not url or requests is None:
            return "", "", ""
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else None
            r = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }, timeout=10, proxies=proxies)
            html = r.content.decode("utf-8", "replace") or ""
            import re as _re
            import html as _html
            # OG title
            title = ""
            m = _re.search(r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, _re.I)
            if not m:
                m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:title["\']', html, _re.I)
            if m:
                title = _html.unescape(m.group(1)).strip()
            if not title:
                m = _re.search(r'<title[^>]*>([^<]+)</title>', html, _re.I)
                if m:
                    title = _html.unescape(m.group(1)).strip()
            # OG description
            desc = ""
            m = _re.search(r'<meta[^>]+(?:property|name)=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, _re.I)
            if not m:
                m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:description["\']', html, _re.I)
            if m:
                desc = _html.unescape(m.group(1)).strip()
            if not desc:
                m = _re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, _re.I)
                if m:
                    desc = _html.unescape(m.group(1)).strip()
            # OG image
            cover = ""
            m = _re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, _re.I)
            if not m:
                m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']', html, _re.I)
            if m:
                cover = m.group(1)
            return title, desc, cover
        except Exception:
            return "", "", ""

    async def _vip_timeout_cancel(self, umo: str, ts: float):
        """VIP 选源超时自动取消（后台任务）。

        菜单展示后由 _handle_vip_link 启动；到时若用户仍未选择（且非新一轮解析），
        自动清除会话并通过 context 主动告知用户，避免反复催促。
        """
        try:
            await asyncio.sleep(300)
        except Exception:
            return
        p = self._vip_pending.get(umo)
        if p and p.get("ts") == ts:
            self._vip_pending.pop(umo, None)
            try:
                await self.context.send_message(umo, MessageChain([Plain(
                    "⏰ VIP 解析等待超时，已自动取消。如需解析请重新发送视频链接。")]))
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[VIP] 超时取消通知发送失败: {e}")

    async def _handle_vip_selection(self, event, umo: str, idx: int):
        """用户选了第 idx 个接口 → 校验 → 发送聊天记录格式结果。"""
        pending = self._vip_pending.pop(umo, None)
        if not pending:
            return
        cfg = self._get_config()
        interfaces = pending.get("interfaces") or self._get_interfaces(cfg)
        if idx < 1 or idx > len(interfaces):
            # 序号无效：保留会话让用户重选
            self._vip_pending[umo] = pending
            await event.send(MessageChain([Plain(f"序号无效，请回复 1-{len(interfaces)} 之间的数字。")]))
            return

        name, tpl = interfaces[idx - 1]
        clean = pending.get("clean_url") or pending.get("raw")
        play_url = build_interface_link(tpl, clean)
        timeout = int(cfg.get("video_vip_timeout", 20000) or 20000)
        # 安全兜底：如果用户把超时设成了秒（如 25），自动转成毫秒
        if timeout < 1000:
            timeout = timeout * 1000
        channel = (cfg.get("browser_channel") or "").strip()
        exe = ""  # video_vip_browser_path 配置已移除，统一自动探测浏览器
        proxy = ""  # video_vip_proxy 配置已移除，统一走环境代理自动探测

        # ── 校验接口：选中的失效时自动尝试其它接口（M1907 / 789 优先）──
        candidates = [(name, play_url)]
        for n, t in interfaces:
            if n != name:
                candidates.append((n, build_interface_link(t, clean)))
        seen_urls = set()
        chosen = None
        last_err = ""
        try:
            await event.send(MessageChain([Plain("⏳ 正在验证解析接口，请稍候…")]))
        except Exception:
            pass
        verify_timeout = max(6000, min(timeout, 15000))
        for n, u in candidates[:3]:
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            try:
                r = await verify_interface_playable(
                    u, timeout_ms=verify_timeout, channel=channel, exe=exe)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            if r.get("ok"):
                chosen = (n, u)
                break
            last_err = r.get("error") or "no-player"
            logger.info(f"[VIP] 接口 {n} 不可用: {last_err[:80]}")
        if not chosen:
            # 保留本次解析，让用户换一个接口重试
            self._vip_pending[umo] = pending
            await event.send(MessageChain([Plain(
                f"❌ 解析接口暂时不可用（{last_err[:60]}）。\n"
                "已保留本次解析，请换一个序号重试，或发送「取消」。")]))
            return
        name, play_url = chosen

        # 菜单阶段没抓简介/封面，这里补抓（仅 HTTP OG，不走浏览器，1-2 秒）
        if not pending.get("desc") or not pending.get("poster_url"):
            try:
                _og_title, og_desc, og_cover = await asyncio.to_thread(
                    self._fetch_og_meta, clean, proxy)
                if og_desc and not pending.get("desc"):
                    pending["desc"] = og_desc
                if og_cover and not pending.get("poster_url"):
                    pending["poster_url"] = og_cover
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[VIP] OG 补抓失败(非致命): {e}")

        # 统一发送（合并转发→Markdown→文本+图片 三级降级）
        title = pending.get("title", "")
        desc = pending.get("desc", "")
        poster = pending.get("poster_url") or pending.get("poster_path")
        tlines = [
            "✅ VIP 解析完成",
            f"🎬 标题：{title}" if title else "🎬 标题：（未知）",
        ]
        if desc:
            tlines.append(f"📝 简介：{desc[:300]}")
        tlines.append(f"🛰️ 接口：{name}")
        tlines.append("🎞️ 解析直链（浏览器/播放器打开即看）：")
        tlines.append(play_url)
        await self._send_resource_result(event, text="\n".join(tlines),
                                         images=[poster] if poster else [],
                                         referer="", source_name="暮黎影视解析")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def on_netease_voice(self, event: AstrMessageEvent):
        """自动识别网易云歌曲链接 / 小程序分享卡片，解析为高潮片段语音发送。"""
        cfg = self._get_config()
        if not (cfg.get("wyy_auto_parse", True)):
            return
        text = (event.message_str or "").strip()
        # 跳过纯指令（/wyy 由命令处理器处理，避免重复）
        if text.startswith("/"):
            return
        song_id = extract_netease_id(text) if text else None
        # 小程序卡片：遍历消息组件找 Json 段
        if not song_id and Json is not None:
            for comp in self._wyy_components(event):
                if isinstance(comp, Json):
                    jdata = getattr(comp, "data", None)
                    if jdata is None:
                        continue
                    song_id = extract_from_miniapp(jdata)
                    if song_id:
                        break
        if not song_id:
            return
        # 命中：接管事件，避免 LLM / 其它处理器重复响应
        event.stop_event()
        await self._handle_netease(event, song_id, cfg)

    @filter.command("wyy")
    async def wyy_cmd(self, event: AstrMessageEvent):
        """/wyy <网易云链接或歌曲ID> — 解析为 QQ 语音名片"""
        cfg = self._get_config()
        text = (event.message_str or "").strip()
        arg = text
        if arg.startswith("/wyy"):
            arg = arg[4:].strip()
        song_id = extract_netease_id(arg)
        if not song_id and "163cn.tv" in arg:
            try:
                resolved = await resolve_shortlink(arg)
                song_id = extract_netease_id(resolved)
            except Exception:
                pass
        if not song_id:
            await event.send(MessageChain([Plain(
                "🎵 网易云语音名片\n用法：/wyy <网易云歌曲链接或歌曲ID>\n"
                "例如：/wyy https://music.163.com/song?id=1861173563")]))
            return
        await self._handle_netease(event, song_id, cfg)

    @filter.command("wyy_login")
    async def wyy_login_cmd(self, event: AstrMessageEvent):
        """管理员扫码登录网易云：发送 /wyy_login 获取二维码，App 扫码确认后自动写入会员 Cookie(wyy_cookie)。"""
        # 尽力而为的管理员校验（无法判定时放行，与现有 refresh 命令一致）
        try:
            role = None
            if hasattr(event, "get_role") and callable(event.get_role):
                role = event.get_role()
            if role == "member":
                await event.send(MessageChain([Plain("⛔ 该命令仅管理员可用。")]))
                return
        except Exception:
            pass

        cfg = self._get_config()
        backend = (cfg.get("wyy_backend") or "direct").strip().lower()
        # 直接走「内置直连」扫码（零部署，无需 NeteaseCloudMusicApi）。
        # 仅当用户显式配置 custom 后端且填了 wyy_custom_url 时，才回退到自建实例。
        if backend == "custom" and (cfg.get("wyy_custom_url") or "").strip():
            await self._wyy_login_custom(event, cfg)
            return

        await event.send(MessageChain([Plain("🔳 正在生成网易云登录二维码（内置直连，无需任何外部服务）…")]))
        unikey, device_id, music_a, csrf = await qr_login_key_direct()
        if not unikey:
            await event.send(MessageChain([Plain(
                "❌ 获取登录二维码失败。请查看 AstrBot 日志页 / docker logs 中的「[网易云扫码]」错误详情，"
                "常见原因：服务器无法访问 music.163.com、缺少 pycryptodome、或被网易云风控拦截。")]))
            return
        qr_url = build_qr_url(unikey)
        img_bytes = qr_url_to_png(qr_url)
        if img_bytes:
            import os as _os
            import tempfile as _tempfile
            _qr_path = _os.path.join(_tempfile.gettempdir(), f"muliy_wyy_qr_{abs(hash(unikey))}.png")
            with open(_qr_path, "wb") as _f:
                _f.write(img_bytes)
            await event.send(MessageChain([
                Plain("📷 请用「网易云 App」扫描上方二维码登录：\n"),
                ImageComponent(file=_qr_path),
                Plain("⏳ 等待扫码确认（2 分钟内有效，登录成功后自动写入会员 Cookie）。"),
            ]))
        else:
            await event.send(MessageChain([Plain(
                f"📷 请使用网易云 App 扫码登录（二维码链接）：\n{qr_url}\n"
                f"⏳ 等待扫码确认（2 分钟内有效）。")]))
        # 后台轮询，不阻塞命令返回（透传匿名设备会话保持 unikey↔check 一致）
        asyncio.create_task(self._wyy_login_poll(event, "direct", unikey, device_id=device_id, music_a=music_a, csrf=csrf))

    async def _wyy_login_custom(self, event: AstrMessageEvent, cfg: dict):
        """custom 后端：沿用自建 NeteaseCloudMusicApi 的扫码接口（兼容旧部署）。"""
        base = normalize_api_base(cfg.get("wyy_custom_url") or "")
        if not base:
            await event.send(MessageChain([Plain(
                "❌ 未配置 wyy_custom_url（自建 NeteaseCloudMusicApi 实例地址）。\n"
                "请先在插件配置填写 wyy_custom_url，并确保该实例已运行。")]))
            return
        await event.send(MessageChain([Plain("🔳 正在获取网易云登录二维码（自建实例）…")]))
        key = await qr_login_key(base)
        if not key:
            await event.send(MessageChain([Plain(
                "❌ 获取登录 key 失败，请确认 NeteaseCloudMusicApi 实例运行正常且 /login/qr/key 可用。")]))
            return
        created = await qr_login_create(base, key)
        if not created:
            await event.send(MessageChain([Plain(
                "❌ 生成登录二维码失败，请确认实例 /login/qr/create 接口可用。")]))
            return
        img_bytes = qrimg_to_bytes(created.get("qrimg"))
        if img_bytes:
            import os as _os
            import tempfile as _tempfile
            _qr_path = _os.path.join(_tempfile.gettempdir(), f"muliy_wyy_qr_{abs(hash(key))}.png")
            with open(_qr_path, "wb") as _f:
                _f.write(img_bytes)
            await event.send(MessageChain([Plain("📷 请使用网易云 App 扫码登录：\n"), ImageComponent(file=_qr_path)]))
        else:
            qrurl = created.get("qrurl") or ""
            await event.send(MessageChain([Plain(f"📷 请使用网易云 App 扫码登录（二维码链接）：\n{qrurl}")]))
        await event.send(MessageChain([Plain("⏳ 已发送二维码，等待扫码…（2 分钟内有效，扫码后自动写入 Cookie）")]))
        asyncio.create_task(self._wyy_login_poll(event, "custom", key, base))

    async def _wyy_login_poll(self, event: AstrMessageEvent, mode: str, key: str, base: str = "", cookie: str = "", device_id: str = "", music_a: str = "", csrf: str = ""):
        """后台轮询扫码状态，code=803 时提取会员 Cookie 写入 wyy_cookie。"""
        last_tip = ""
        for _ in range(60):  # 60 * 2s = 120s
            await asyncio.sleep(2)
            try:
                if mode == "direct":
                    r = await qr_login_check_direct(key, device_id=device_id, music_a=music_a, csrf=csrf)
                else:
                    r = await qr_login_check(base, key)
            except Exception as e:
                logger.warning(f"[网易云扫码] 轮询异常: {e}")
                continue
            code = r.get("code") if isinstance(r, dict) else -1
            if code == 800:
                await event.send(MessageChain([Plain("⌛ 二维码已过期，请重新发送 /wyy_login 获取新二维码。")]))
                return
            if code == 802 and last_tip != "scanned":
                last_tip = "scanned"
                await event.send(MessageChain([Plain("📱 已扫码！请在手机上点击「确认登录」。")]))
                continue
            if code == 803:
                cookie = r.get("cookie") or ""
                music_cookie = extract_music_cookie(cookie)
                if not music_cookie:
                    await event.send(MessageChain([Plain("⚠️ 扫码成功但未提取到会员 Cookie，请检查账号状态。")]))
                    return
                await self._update_config("wyy_cookie", music_cookie)
                nick = ""
                try:
                    if mode == "custom":
                        nick = await get_login_nickname(base, music_cookie)
                except Exception:
                    pass
                msg = "✅ 网易云登录成功！会员 Cookie 已自动写入 wyy_cookie"
                if nick:
                    msg += f"\n👤 当前账号：{nick}"
                msg += "\n🎵 现在 /wyy 解析 VIP/付费歌曲即可生效。"
                await event.send(MessageChain([Plain(msg)]))
                return
            # code 801 等待 / code -1 异常：静默重试
        await event.send(MessageChain([Plain("⌛ 登录超时（2 分钟未确认）。请重新发送 /wyy_login。")]))

    async def _handle_netease(self, event, song_id, cfg):
        """解析 → 下载 → 剪辑 → 以语音 + 名片形式发送。"""
        try:
            await event.send(MessageChain([Plain("🎵 识别到网易云歌曲，正在解析…")]))
        except Exception:
            pass
        parser = NeteaseParser(cfg)
        try:
            info = await parser.parse(song_id)
        except Exception as e:
            logger.warning(f"[网易云] 解析异常: {e}")
            info = None
        if not info or not info.get("url"):
            reason = (parser.last_error or "未知原因").strip()
            await event.send(MessageChain([Plain(
                f"❌ 网易云解析失败（歌曲ID {song_id}）。\n"
                f"原因：{reason}\n\n"
                f"内置直连模式（默认）无需任何外部服务；若仍失败，可在插件配置填黑胶会员 Cookie（wyy_cookie），\n"
                f"或发送 /wyy_login 用网易云 App 扫码登录后重试。")]))
            return

        tmp_mp3 = None
        clip_path = None
        wyy_cookie = (cfg.get("wyy_cookie") or "").strip()
        try:
            # 下载（携带会员 Cookie 时部分 CDN 节点更稳；免费歌一般无需）
            try:
                tmp_mp3 = await download_mp3(info["url"], cookie=wyy_cookie)
            except Exception as e:
                logger.warning(f"[网易云] 下载失败: {e}")
                # 服务器 IP 被网易云音频 CDN 按数据中心封禁时会 403（与公共解析站被封同源）。
                # 此时无法在服务器端下载音频，降级为「歌曲名片 + 播放链接」，用户点开即可听。
                play_url = f"https://music.163.com/song?id={song_id}"
                fallback = (
                    f"🎵 《{info['name']}》\n👤 {info['artist']}"
                    + (f"\n💽 {info['album']}" if info.get('album') else "")
                    + f"\n\n🔗 播放链接（点开即可在网易云收听）：\n{play_url}\n\n"
                    f"⚠️ 服务器下载音频失败：{str(e)[:80]}\n"
                    f"💡 这是网易云对云服务器 IP 的 CDN 限制，非插件问题。\n"
                    f"   想直接发语音，可把插件部署在本地/家宽网络，或更换未被封锁的出口 IP。"
                )
                await event.send(MessageChain([Plain(fallback)]))
                return

            # 剪辑为「不超过最大时长的语音」（从开头取 min(歌曲时长, 上限)）
            duration = await get_duration_seconds(tmp_mp3)
            max_seconds = int(cfg.get("wyy_clip_seconds", 600))
            audio_fmt = (cfg.get("wyy_audio_format", "mp3") or "mp3").lower()
            seg_txt = ""
            if ffmpeg_available() and duration > 0:
                start, length = compute_clip_range(duration, max_seconds)
                if length <= 0:
                    # 探测不到时长，回退整首
                    clip_path = tmp_mp3
                    seg_txt = "（未探测到时长，已发送完整音频）"
                else:
                    fd, clip_path = tempfile.mkstemp(suffix=f".{audio_fmt}", prefix="wyy_clip_")
                    os.close(fd)
                    await cut_clip(tmp_mp3, clip_path, start, length, audio_fmt)
                    if abs(length - duration) < 1.0:
                        seg_txt = "（整曲发送）"
                    else:
                        seg_txt = f"（前 {int(length)} 秒 · 上限 {max_seconds} 秒）"
            else:
                clip_path = tmp_mp3
                if not ffmpeg_available():
                    seg_txt = "（未安装 ffmpeg，已发送完整音频）"

            # 名片文本
            card = f"🎵 《{info['name']}》\n👤 {info['artist']}"
            if info.get("album"):
                card += f"\n💽 {info['album']}"
            card += f"\n🎤 已发送语音{seg_txt}"

            if Record is not None and clip_path:
                # 本地临时文件只传 file=，不要传 url=（url 应为 http(s) 直链，
                # 传本地路径会被 OneBot 当成网址去拉取，导致语音发送为空/失败）
                try:
                    await event.send(MessageChain([Plain(card), Record(file=clip_path)]))
                except Exception as se:
                    # 常见于长音频：OneBot(napcat) 转码 silk + 上传耗时超过 WS 动作超时，
                    # 抛「WebSocket API call timeout」。此时回退为发送音频文件，保证整曲仍送达。
                    logger.warning(f"[网易云] 语音发送失败（可能超时），回退发送文件: {se}")
                    await event.send(MessageChain([
                        Plain(card + "\n⚠️ 语音发送超时（曲目较长），已改为发送音频文件。\n"
                                     "💡 想稳定发语音可把「最大发送歌曲时长」调小（如 120 秒）。"),
                        FileComponent(file=clip_path, name=f"{info['name']}.{audio_fmt}"),
                    ]))
            else:
                await event.send(MessageChain([Plain(card + "\n⚠️ 当前 AstrBot 版本不支持语音组件，已改为发送文件。")]))
                await event.send(MessageChain([FileComponent(file=clip_path, name=f"{info['name']}.{audio_fmt}")]))
        except Exception as e:
            logger.error(f"[网易云] 处理失败: {e}", exc_info=True)
            try:
                await event.send(MessageChain([Plain(f"❌ 网易云语音生成失败：{str(e)[:150]}")]))
            except Exception:
                pass
        finally:
            # 清理临时文件（tmp_mp3 与 clip_path 可能指向同一文件，去重只删一次）
            cleaned = set()
            for p in (tmp_mp3, clip_path):
                if p and p not in cleaned and os.path.exists(p):
                    cleaned.add(p)
                    try:
                        os.unlink(p)
                    except Exception:
                        pass

    # ==================== 摸头杀 PetPet（v1.9.16 新增） ====================

    # 触发关键词
    _PETPET_TRIGGERS = ("摸摸", "摸头", "摸摸头", "pat", "rua")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=2)
    async def on_petpet(self, event: AstrMessageEvent):
        """摸摸 @某人 — 生成摸头GIF动图

        使用 event_message_type 而非 filter.command，
        这样无需 @机器人 唤醒即可直接触发。
        """
        text = (event.message_str or "").strip()
        if not text:
            return
        # 检查是否以触发词开头（去掉可能的 / 前缀）
        triggered = False
        for kw in self._PETPET_TRIGGERS:
            if text.startswith(kw) or text.startswith("/" + kw):
                triggered = True
                break
        if not triggered:
            return
        # 命中：接管事件，阻止后续处理器重复响应
        event.stop_event()
        await self._handle_petpet(event)

    async def _handle_petpet(self, event: AstrMessageEvent):
        """摸头杀核心处理逻辑。"""
        # ── 前置检查 ──
        if not PETPET_PIL_AVAILABLE:
            await event.send(MessageChain([Plain(
                "❌ 生成摸头GIF需要 Pillow 库，请让管理员执行：pip install pillow"
            )]))
            return

        # ── 提取 @ 成员 ──
        at_targets = []
        try:
            messages = event.get_messages()
        except Exception:
            messages = []
        for comp in messages:
            # AstrBot 的 At 组件：qq 属性为目标用户 ID
            if At is not None and isinstance(comp, At):
                qq_val = str(getattr(comp, "qq", "")).strip()
                if qq_val and qq_val != "all":
                    at_targets.append({
                        "id": qq_val,
                        "name": getattr(comp, "name", "") or qq_val,
                    })

        # ── 无 @ → 摸自己 ──
        if not at_targets:
            sender_id = event.get_sender_id()
            sender_name = event.get_sender_name() or "自己"
            if not sender_id:
                await event.send(MessageChain([Plain(
                    "🤚 摸头杀\n用法：摸摸 @某人\n（在群里@一位群友，我来摸TA的头～）"
                )]))
                return
            at_targets.append({"id": sender_id, "name": sender_name})

        # ── 多个 @ → 最多处理 5 个 ──
        if len(at_targets) > 5:
            await event.send(MessageChain([Plain(
                f"👐 一次最多摸5个人的头哦～（你@了{len(at_targets)}个人，只摸前5个）"
            )]))
            at_targets = at_targets[:5]

        platform_name = event.get_platform_name()

        # ── 逐个生成 GIF ──
        gif_paths = []
        errors = []
        for target in at_targets:
            uid = target["id"]
            uname = target["name"]
            try:
                gif_path = await asyncio.to_thread(
                    generate_petpet_from_avatar, platform_name, uid
                )
                gif_paths.append((gif_path, uname))
            except Exception as e:
                err_msg = str(e)[:100]
                logger.warning(f"[PetPet] 生成失败 uid={uid}: {err_msg}")
                errors.append(f"{uname}: {err_msg}")

        # ── 发送 GIF ──
        if not gif_paths:
            error_detail = "\n".join(errors[:3]) if errors else "未知原因"
            await event.send(MessageChain([Plain(
                f"❌ 摸头GIF生成失败\n原因：{error_detail}\n\n"
                f"可能的原因：\n"
                f"• 头像获取失败（该用户可能隐私设置不允许获取头像）\n"
                f"• 当前平台不支持获取用户头像（目前支持 QQ）\n"
                f"• 网络问题，请稍后重试"
            )]))
            return

        # 直接发送 GIF，不加多余文字
        for gif_path, uname in gif_paths:
            try:
                await event.send(MessageChain([
                    ImageComponent(file=gif_path),
                ]))
            except Exception as e:
                logger.error(f"[PetPet] 发送GIF失败: {e}")
                # 发送失败时尝试仅发文本
                try:
                    await event.send(MessageChain([Plain(f"❌ GIF发送失败: {str(e)[:100]}")]))
                except Exception:
                    pass
            finally:
                # 清理临时文件
                try:
                    os.unlink(gif_path)
                except Exception:
                    pass

        # ── 汇报部分失败 ──
        if errors:
            err_detail = "\n".join(errors[:3])
            try:
                await event.send(MessageChain([Plain(f"⚠️ 部分失败：\n{err_detail}")]))
            except Exception:
                pass

    # ==================== 舔狗表情「给你一脚」（v1.9.17 新增） ====================

    # 触发关键词
    _LICKDOG_TRIGGERS = ("给你一脚", "一脚", "踹", "踢", "kick")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=2)
    async def on_lickdog(self, event: AstrMessageEvent):
        """给你一脚 @某成员 — 生成「马踢舔狗」GIF 表情

        无需 @机器人 唤醒即可直接触发。
        发送者 = 踢人者（右下角文字），被@成员 = 舔狗（左上角文字）。
        """
        text = (event.message_str or "").strip()
        if not text:
            return
        triggered = False
        for kw in self._LICKDOG_TRIGGERS:
            if text.startswith(kw) or text.startswith("/" + kw):
                triggered = True
                break
        if not triggered:
            return
        event.stop_event()
        await self._handle_lickdog(event)

    async def _handle_lickdog(self, event: AstrMessageEvent):
        """舔狗表情核心处理逻辑。"""
        if not LICKDOG_PIL_AVAILABLE:
            await event.send(MessageChain([Plain(
                "❌ 生成舔狗表情需要 Pillow 库，请让管理员执行：pip install pillow"
            )]))
            return

        # ── 提取 @ 成员 ──
        at_targets = []
        try:
            messages = event.get_messages()
        except Exception:
            messages = []
        for comp in messages:
            if At is not None and isinstance(comp, At):
                qq_val = str(getattr(comp, "qq", "")).strip()
                if qq_val and qq_val != "all":
                    at_targets.append({
                        "id": qq_val,
                        "name": getattr(comp, "name", "") or qq_val,
                    })

        # 发送者（踢人者）
        kicker_id = event.get_sender_id() or "未知"
        kicker_name = event.get_sender_name() or "某人"

        # 被踢的舔狗：优先取第一个 @ 成员；无 @ 则踢自己
        if at_targets:
            dog = at_targets[0]
            dog_name = dog["name"]
            dog_id = dog["id"]
            # 多个 @ 时只踢第一个（模板仅一个舔狗位）
            if len(at_targets) > 1:
                await event.send(MessageChain([Plain(
                    f"🐴 一次只能踢一只舔狗哦～（你@了{len(at_targets)}个，只踢 {dog_name}）"
                )]))
        else:
            dog_name = kicker_name
            dog_id = kicker_id

        # ── 两个文字位都用用户头像（避免名字过长/字体无法渲染） ──
        platform_name = event.get_platform_name()
        kicker_avatar = await self._fetch_avatar_or_none(platform_name, kicker_id)
        dog_avatar = await self._fetch_avatar_or_none(platform_name, dog_id)

        # ── 生成 GIF ──
        try:
            gif_path = await asyncio.to_thread(
                generate_lickdog, kicker_name, dog_name,
                kicker_avatar=kicker_avatar, dog_avatar=dog_avatar,
            )
        except Exception as e:
            err_msg = str(e)[:120]
            logger.error(f"[LickDog] 生成失败: {err_msg}")
            await event.send(MessageChain([Plain(
                f"❌ 舔狗表情生成失败\n原因：{err_msg}\n\n"
                f"可能原因：\n• Pillow/字体缺失\n• 模板文件 assets/lickdog/template.gif 不存在"
            )]))
            return

        # 直接发送 GIF，不加多余文字
        try:
            await event.send(MessageChain([ImageComponent(file=gif_path)]))
        except Exception as e:
            logger.error(f"[LickDog] 发送GIF失败: {e}")
            try:
                await event.send(MessageChain([Plain(f"❌ GIF发送失败: {str(e)[:100]}")]))
            except Exception:
                pass
        finally:
            try:
                os.unlink(gif_path)
            except Exception:
                pass

    # ==================== 柴犬按摩「按摩」（v1.9.18 新增） ====================

    # 触发关键词
    _MASSAGE_TRIGGERS = ("给我按摩", "给我揉揉")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=2)
    async def on_massage(self, event: AstrMessageEvent):
        """按摩 @某成员 — 生成「柴犬按摩」GIF 表情

        无需 @机器人 唤醒即可直接触发。
        发送者 = 按摩者（右上角），被@成员 = 被按摩的群友（左下角）。
        """
        text = (event.message_str or "").strip()
        if not text:
            return
        triggered = False
        for kw in self._MASSAGE_TRIGGERS:
            if text.startswith(kw) or text.startswith("/" + kw):
                triggered = True
                break
        if not triggered:
            return
        event.stop_event()
        await self._handle_massage(event)

    async def _handle_massage(self, event: AstrMessageEvent):
        """柴犬按摩核心处理逻辑。"""
        if not MASSAGE_PIL_AVAILABLE:
            await event.send(MessageChain([Plain(
                "❌ 生成按摩表情需要 Pillow 库，请让管理员执行：pip install pillow"
            )]))
            return

        # ── 提取 @ 成员 ──
        at_targets = []
        try:
            messages = event.get_messages()
        except Exception:
            messages = []
        for comp in messages:
            if At is not None and isinstance(comp, At):
                qq_val = str(getattr(comp, "qq", "")).strip()
                if qq_val and qq_val != "all":
                    at_targets.append({
                        "id": qq_val,
                        "name": getattr(comp, "name", "") or qq_val,
                    })

        # 发送者（按摩者）
        kicker_id = event.get_sender_id() or "未知"
        kicker_name = event.get_sender_name() or "某人"

        # 被按摩的群友：优先取第一个 @ 成员；无 @ 则按摩自己
        if at_targets:
            dog = at_targets[0]
            dog_name = dog["name"]
            dog_id = dog["id"]
            if len(at_targets) > 1:
                await event.send(MessageChain([Plain(
                    f"💆 一次只能按摩一只柴犬哦～（你@了{len(at_targets)}个，只按摩 {dog_name}）"
                )]))
        else:
            dog_name = kicker_name
            dog_id = kicker_id

        # ── 两个文字位都用用户头像（避免名字过长/字体无法渲染） ──
        platform_name = event.get_platform_name()
        kicker_avatar = await self._fetch_avatar_or_none(platform_name, kicker_id)
        dog_avatar = await self._fetch_avatar_or_none(platform_name, dog_id)

        # ── 生成 GIF ──
        try:
            gif_path = await asyncio.to_thread(
                generate_massage, kicker_name, dog_name,
                kicker_avatar=kicker_avatar, dog_avatar=dog_avatar,
            )
        except Exception as e:
            err_msg = str(e)[:120]
            logger.error(f"[Massage] 生成失败: {err_msg}")
            await event.send(MessageChain([Plain(
                f"❌ 按摩表情生成失败\n原因：{err_msg}\n\n"
                f"可能原因：\n• Pillow/字体缺失\n• 模板文件 assets/doutu/template.gif 不存在"
            )]))
            return

        # 直接发送 GIF，不加多余文字
        try:
            await event.send(MessageChain([ImageComponent(file=gif_path)]))
        except Exception as e:
            logger.error(f"[Massage] 发送GIF失败: {e}")
            try:
                await event.send(MessageChain([Plain(f"❌ GIF发送失败: {str(e)[:100]}")]))
            except Exception:
                pass
        finally:
            try:
                os.unlink(gif_path)
            except Exception:
                pass

    async def _fetch_avatar_or_none(self, platform: str, user_id) -> bytes:
        """最佳努力拉取头像字节，失败返回 None（用于名字无法渲染时的兜底）。"""
        if not PETPET_PIL_AVAILABLE or not user_id:
            return None
        try:
            return await asyncio.to_thread(
                download_avatar_by_platform, platform, str(user_id)
            )
        except Exception as e:
            logger.warning(f"[LickDog] 头像兜底获取失败 uid={user_id}: {e}")
            return None

    # ==================== 消息处理（ALL，仅在有活跃会话时触发） ====================

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1)
    async def _track_report_group(self, event: AstrMessageEvent):
        """记录机器人见过的群，供「日报留空=全部群」在非 OneBot 平台兜底。"""
        try:
            gid = event.get_group_id()
            if gid:
                self._remember_seen_group(event.get_platform_id(), gid)
        except Exception:
            pass

    @filter.event_message_type(filter.EventMessageType.ALL, priority=999999)
    async def on_any_message(self, event: AstrMessageEvent):
        """会话内硬指令处理（事件监听入口）。

        实际逻辑放在 `_dispatch_any_message`：on_llm_request 可能会在 LLM
        请求前提前调用同一次处理（不同 AstrBot 版本里 LLM 与事件处理顺序不同），
        用同一个方法可以保证「用户回复序号」不会既被插件处理、又被 LLM 回一遍。
        """
        await self._dispatch_any_message(event)

    async def _dispatch_any_message(self, event: AstrMessageEvent):
        """会话内硬指令处理：有 session → 用 event.set_result() 注入已格式化文本 →
        走完整 ResultDecorateStage + RespondStage 发送。
        无 session → 正常退出，让 LLM 处理搜索意图。

        关键修复（v3）：把 on_any_message 内的 event.send() 改成 event.set_result()，
        消息会经过 on_decorating_result（AngelHeart strip + 我方 LLM-STRIP）再发出，
        而不再是被 stop_event 截胡或绕开整个 pipeline。
        """
        try:
            text = event.message_str.strip()
        except Exception:
            return
        if not text:
            return

        # 同一条消息只处理一次：on_llm_request 可能提前调用本方法做拦截
        try:
            if event.get_extra("_muliy_any_ran"):
                return
            event.set_extra("_muliy_any_ran", True)
        except Exception:  # noqa: BLE001
            pass

        # ── 谁是卧底私聊投票（优先于其它会话处理） ──
        try:
            if await self._handle_uc_private(event, text):
                event.stop_event()
                self._mark_llm_suppress(event)
                return
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[卧底] 私聊入口处理失败: {e}")

        # ── pdy0 搜索验证码回复（必须在会话清理之前消费） ──
        try:
            if await self._handle_pdy_captcha_reply(event, text):
                return
        except Exception as e:
            logger.warning(f"[pdy_site] 处理验证码回复失败: {e}")

        # ── 通用关键词 ──
        page_kw = ("下一页", "上一页")
        jump_kw = ("跳转", "跳到")
        cancel_kw = ("0", "取消", "算", "不要", "no")
        num_kw = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")

        # 去掉 @机器人 / CQ at 前缀，支持「@bot 1」这种回复
        session_text = re.sub(r"\[CQ:at,[^\]]+\]", "", text)
        session_text = re.sub(r"^@\S+\s*", "", session_text).strip()

        # ── 断点续选：仅当本条消息「引用」了机器人的列表消息时才恢复会话 ──
        #    直接发序号不会恢复（会话结束后就是新对话，方便用户去做别的事）
        try:
            if session_text and self._resume_from_quote(event):
                logger.debug("[断点] 已从引用消息恢复会话")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[断点] 引用恢复失败: {e}")

        # ── 群聊小游戏：只消费明确的游戏输入，普通聊天继续走原流程 ──
        if session_text and not text.startswith("/"):
            try:
                if await self._handle_minigame_message(event, session_text):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    return
            except Exception as e:  # noqa: BLE001
                logger.error(f"[小游戏] 兜底处理失败: {e}")

        # ══════════════════════════════════════════════
        # 影视会话（pdy0 / 片库主站）
        # 在线程内（已出搜索结果 / 资源菜单 / 选集）直接处理，
        # 不依赖 @机器人；@ 了也能正常识别。
        # ══════════════════════════════════════════════
        ses_mn = self._movie_sessions_new.get(event)
        if ses_mn:
            valid = (
                session_text in cancel_kw
                or session_text in page_kw
                or session_text.startswith(("跳", "第", "选", "最后"))
                or re.fullmatch(r"\d{1,3}", session_text or "")
                or any(k in session_text for k in (
                    "在线", "网盘", "线路", "节点", "磁力",
                    "夸克", "百度", "迅雷", "阿里", "天翼", "uc", "115", "正片"))
            )
            if valid:
                event.stop_event()
                self._mark_llm_suppress(event)
                try:
                    await self._handle_movie_new_selection(event, session_text)
                except Exception as e:
                    logger.error(f"[暮黎资源] 影视会话处理失败: {e}")
                    await event.send(MessageChain([Plain(
                        f"【暮黎资源】影视操作失败：{str(e)[:120]}")]))
                return

        # ══════════════════════════════════════════════
        # 残留会话自动清理（issue2 修复）
        # 若当前消息不是任何活跃会话的有效操作（翻页/选号/取消/网盘名），
        # 视为新意图，清理所有残留会话后放行给 LLM，避免“还要发0手动取消”的死循环。
        # ══════════════════════════════════════════════
        sel_like = (
            text in cancel_kw or text in page_kw
            or text.startswith("下一页") or text.startswith("上一页")
            or text.startswith("跳") or text in num_kw
            or re.fullmatch(r"\d{1,3}", text or "")
            or text.startswith("第") or text.startswith("选") or text.startswith("最后")
            or any(k in text for k in ("夸克", "百度", "天翼", "迅雷", "阿里", "123", "uc", "磁力", "网盘", "线路"))
            or any(k in text for k in ("下载", "确认", "txt", "epub", "html", "pdf", "格式"))
        )
        _all_session_mgrs = (self._sessions, self._search_sessions,
                              self._movie_sessions, self._movie_sessions_new,
                              self._novel_sessions, self._drama_sessions)
        _active = [m for m in _all_session_mgrs if m.get(event)]
        if _active and not sel_like:
            for m in _active:
                m.delete(event)
            logger.info(f"[暮黎资源] 残留会话因非选择类消息已自动清理，放行新意图: {text[:24]}")
            return

        # ══════════════════════════════════════════════
        # 游戏会话
        # ══════════════════════════════════════════════
        ses = self._sessions.get(event)
        if ses:
            stage = ses.get("stage", "")

            # ── 1. 取消（所有阶段通用） ──
            if text in cancel_kw:
                event.stop_event()
                self._mark_llm_suppress(event)
                self._sessions.delete(event)
                event.set_result(event.plain_result("已取消搜索。"))
                return

            # ── 2. select_game 阶段 ──
            if stage == "select_game":
                # 翻页/跳转 → ★插件自己发格式化页面（保证响应）
                if text in page_kw or text.startswith("跳"):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    ps = ses.get("page_size", 8); t = len(ses["results"])
                    cur = ses.get("page", 0)
                    if text in page_kw:
                        ses["page"] = 0 if (cur + 1) * ps >= t else cur + 1 if "下一页" in text else max(0, cur - 1)
                    else:
                        m = re.search(r'\d+', text)
                        if m:
                            pt = (t + ps - 1) // ps
                            ses["page"] = max(0, min(pt - 1, int(m.group()) - 1))
                    ses["_updated"] = time.time()
                    # ★关键：用 event.send 立即发格式化页面
                    await self._send_search_page(event, "game", self._format_game_page(ses), ses=ses)
                    return

                # 数字/自然语言选择 → 插件处理（调详情 + 列网盘）
                if text in num_kw or text.startswith("第") or text.startswith("选") or text.startswith("最后"):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    num = self._parse_natural_number(text)
                    if num == -2: num = len(ses["results"]) - (ses.get("page", 0) * ses.get("page_size", 8))
                    r = ses["results"]; pg = ses.get("page", 0); ps = ses.get("page_size", 8)
                    t = len(r); st = pg * ps; ed = min(st + ps, t); pc = ed - st
                    if num < 1 or num > pc:
                        await event.send(MessageChain([Plain(f"请输入1-{pc}之间的数字。回复0取消。")]))
                        return
                    ai = st + num - 1; sel = r[ai]
                    self._sessions.update(event, selected_index=ai, stage="fetching")
                    await event.send(MessageChain([Plain(f"已选择：{sel['title']}")]))
                    try:
                        detail = await self._fetch_game_detail(event, sel["url"])
                    except Exception as e:
                        self._sessions.delete(event)
                        await event.send(MessageChain([Plain(f"失败：{str(e)[:100]}")]))
                        return
                    if detail.get("need_login"):
                        self._sessions.delete(event)
                        await event.send(MessageChain([Plain(self._game_login_hint())]))
                        return
                    if not detail.get("download_links"):
                        self._sessions.delete(event)
                        await event.send(MessageChain([Plain("无下载链接。")]))
                        return
                    self._sessions.update(event, game_detail=detail, stage="select_link")
                    await self._send_game_link_menu(event, detail, sel, detail["download_links"])
                    return

            # ── 3. select_link 阶段 ──
            if stage == "select_link":
                event.stop_event()
                self._mark_llm_suppress(event)
                detail = ses.get("game_detail", {})
                links = detail.get("download_links", [])
                num = self._parse_selection(text, links)
                if num < 1 or num > len(links):
                    await event.send(MessageChain([Plain(f"请输入1-{len(links)}或网盘名（如「第一个」「百度网盘」）。回复0取消。")]))
                    return
                sl = links[num - 1]
                self._sessions.update(event, stage="resolving")
                await event.send(MessageChain([Plain(f"已选择{sl['pan']}，解析地址...")]))
                try:
                    rlink = await asyncio.to_thread(
                        lambda sl=sl, ck=self._get_cookie(): self._g_resolve(sl, self._g_cookie()))
                except Exception:
                    rlink = sl
                sg = ses["results"][ses["selected_index"]]
                gn = detail.get("name") or sg["title"]
                logger.info(f"[执行] 游戏 {gn} url={rlink.get('real_url', '')[:40]}")
                sent = await self._send_download_link(
                    event, gn, rlink.get("pan", "下载链接"), rlink.get("real_url", ""),
                    code=rlink.get("code", ""), password=rlink.get("password", ""),
                    source_name="暮黎游戏", kind="game",
                    charge=not ses.get("_charged"))
                # 会话结束；换网盘需引用网盘列表消息
                self._sessions.delete(event)
                return

        # ══════════════════════════════════════════════
        # 软件会话
        # ══════════════════════════════════════════════
        ses2 = self._search_sessions.get(event)
        if ses2:
            stage = ses2.get("stage", "")

            # ── 1. 取消（所有阶段通用） ──
            if text in cancel_kw:
                event.stop_event()
                self._mark_llm_suppress(event)
                self._search_sessions.delete(event)
                event.set_result(event.plain_result("已取消搜索。"))
                return

            # ── 2. select_software 阶段 ──
            if stage == "select_software":
                # 翻页/跳转 → ★插件自己发格式化页面（保证响应），然后标记 _llm_handled
                # 让 on_decorating_result 清掉 LLM 后续的多嘴总结
                # 这样既保证响应速度，又不会出现 LLM 二次输出的混乱
                if text in page_kw or text.startswith("跳"):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    ps = ses2.get("page_size", 8); t = len(ses2["results"])
                    cur = ses2.get("page", 0)
                    if text in page_kw:
                        ses2["page"] = 0 if (cur + 1) * ps >= t else cur + 1 if "下一页" in text else max(0, cur - 1)
                    else:
                        m = re.search(r'\d+', text)
                        if m:
                            pt = (t + ps - 1) // ps
                            ses2["page"] = max(0, min(pt - 1, int(m.group()) - 1))
                    ses2["_updated"] = time.time()
                    # ★关键：用 event.send 立即发格式化页面（保证响应），不走 LLM 排版
                    await self._send_search_page(event, "software", self._format_sw_page(ses2), ses=ses2)
                    return

                # 数字/自然语言选择 → 让插件处理（调详情 + 列网盘），保持原来逻辑
                if text in num_kw or text.startswith("第") or text.startswith("选") or text.startswith("最后"):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    num = self._parse_natural_number(text)
                    if num == -2: num = len(ses2["results"]) - (ses2.get("page", 0) * ses2.get("page_size", 8))
                    r = ses2["results"]; pg = ses2.get("page", 0); ps = ses2.get("page_size", 8)
                    t = len(r); st = pg * ps; ed = min(st + ps, t); pc = ed - st
                    if num < 1 or num > pc:
                        await event.send(MessageChain([Plain(f"请输入1-{pc}之间的数字。回复0取消。")]))
                        return
                    ai = st + num - 1; sel = r[ai]
                    self._search_sessions.update(event, selected_index=ai, stage="fetching")
                    await event.send(MessageChain([Plain(f"已选择：{sel['title']}")]))
                    try:
                        detail = await asyncio.to_thread(get_search_detail, sel["url"])
                    except Exception as e:
                        self._search_sessions.delete(event)
                        await event.send(MessageChain([Plain(f"失败：{str(e)[:100]}")]))
                        return
                    if not detail.get("download_links"):
                        self._search_sessions.delete(event)
                        await event.send(MessageChain([Plain("无下载链接。")]))
                        return
                    self._search_sessions.update(event, detail=detail, stage="select_link")
                    await self._send_software_link_menu(event, detail, sel, detail["download_links"])
                    return

            # ── 3. select_link 阶段 ──
            if stage == "select_link":
                event.stop_event()
                self._mark_llm_suppress(event)
                detail = ses2.get("detail", {})
                links = detail.get("download_links", [])
                num = self._parse_selection(text, links)
                if num < 1 or num > len(links):
                    event.set_result(event.plain_result(f"请输入1-{len(links)}或网盘名（如「第一个」「百度网盘」）。回复0取消。"))
                    return
                sl = links[num - 1]
                self._search_sessions.update(event, stage="resolving")
                # 先提示「处理中」，再发送合并转发，避免信息先于提示发出
                await event.send(MessageChain([Plain(f"已选择{sl['pan']}，处理中...")]))
                sr = ses2["results"][ses2["selected_index"]]
                sn = detail.get("name") or sr["title"]
                logger.info(f"[执行] 软件 {sn} url={(sl.get('url') or '')[:50]}")
                sent = await self._send_download_link(
                    event, sn, sl.get("pan", "下载链接"), sl.get("url", ""),
                    source_name="暮黎软件", kind="software",
                    charge=not ses2.get("_charged"))
                # 会话结束；换网盘需引用网盘列表消息
                self._search_sessions.delete(event)
                return

        # ══════════════════════════════════════════════
        # 影视会话（兜底：当 session_waiter 不存在/失败时由 on_any_message 处理）
        # ══════════════════════════════════════════════
        ses3 = self._movie_sessions.get(event)
        if ses3:
            stage = ses3.get("stage", "")

            # 取消
            if text in cancel_kw:
                event.stop_event()
                self._mark_llm_suppress(event)
                self._movie_sessions.delete(event)
                event.set_result(event.plain_result("已取消搜索。"))
                return

            # ★选影视：回复数字选影片 / 翻页（原依赖 LLM 调 select_search_result 工具，
            #   但该 AstrBot 版本工具循环不会实际执行该工具，导致选序号无响应。
            #   这里直接拦截处理，与 select_episode / select_source / 新站影视一致）
            if stage == "select_movie":
                event.stop_event()
                self._mark_llm_suppress(event)
                r = ses3.get("results", [])
                p = ses3.get("page", 0)
                ps = ses3.get("page_size", 8)
                t = len(r)
                st = p * ps
                ed = min(st + ps, t)
                # 翻页
                if text in ("下一页", "上一页") or text.startswith("跳"):
                    pt = (t + ps - 1) // ps
                    new_page = p
                    if "下一页" in text:
                        new_page = 0 if (p + 1) * ps >= t else p + 1
                    elif "上一页" in text:
                        new_page = max(0, p - 1)
                    elif text.startswith("跳"):
                        m = re.search(r"\d+", text)
                        if m:
                            new_page = max(0, min(pt - 1, int(m.group()) - 1))
                    self._movie_sessions.update(event, page=new_page, _updated=time.time())
                    await self._send_search_page(event, "movie", self._format_mv_page(self._movie_sessions.get(event)), ses=self._movie_sessions.get(event))
                    return
                # 数字选择
                number = self._parse_natural_number(text)
                if number == -2:
                    number = ed - st
                if number < 1 or number > (ed - st):
                    await event.send(MessageChain([Plain(f"序号超出范围（1-{ed-st}），请重新输入。回复0取消。")]))
                    return
                ai = st + number - 1
                sel = r[ai]
                await event.send(MessageChain([Plain(f"🎬 已选择：{sel['title']}\n⏳ 正在获取详情，请稍候...")]))
                try:
                    detail = await asyncio.to_thread(get_movie_detail, sel["url"])
                except Exception as e:
                    await event.send(MessageChain([Plain(f"❌ 获取详情失败：{str(e)[:200]}")]))
                    self._movie_sessions.delete(event)
                    return
                if not detail.get("sources"):
                    await event.send(MessageChain([Plain("😕 该影视暂无播放线路。")]))
                    self._movie_sessions.delete(event)
                    return
                self._movie_sessions.set(event, {
                    "stage": "select_movie_done",
                    "keyword": ses3.get("keyword", ""),
                    "selected": sel,
                    "detail": detail,
                    "_updated": time.time(),
                })
                if detail.get("is_series") and detail.get("episodes"):
                    eps_text = format_episodes(detail, max_show=30)
                    await event.send(MessageChain([Plain(eps_text)]))
                    self._movie_sessions.update(event, stage="select_episode")
                else:
                    src_text = format_sources(detail, page=0, page_size=15)
                    await event.send(MessageChain([Plain(src_text)]))
                    self._movie_sessions.update(event, stage="select_source")
                return

            # 选集数
            if stage == "select_episode":
                event.stop_event()
                self._mark_llm_suppress(event)
                detail = ses3.get("detail", {})
                eps = detail.get("episodes", [])
                m2 = re.search(r"\d+", text)
                num = int(m2.group()) if m2 else 0
                if num < 1 or num > len(eps):
                    await event.send(MessageChain([Plain(f"请输入1-{len(eps)}之间的数字（想看第几集）。回复0取消。")]))
                    return
                ep = eps[num - 1]
                self._movie_sessions.update(event, episode=ep, stage="select_source",
                                            source_page=0)
                src_text = format_sources(detail, page=0, page_size=15)
                await event.send(MessageChain([Plain(src_text)]))
                return

            # 选线路（支持翻页）
            if stage == "select_source":
                event.stop_event()
                self._mark_llm_suppress(event)
                detail = ses3.get("detail", {})
                srcs = detail.get("sources", [])
                sel = ses3.get("selected", {})
                ep = ses3.get("episode")
                page = ses3.get("source_page", 0)
                ps = 15
                total = len(srcs)
                pt = (total + ps - 1) // ps
                page = max(0, min(page, pt - 1))
                st = page * ps
                ed = min(st + ps, total)
                show_count = ed - st

                # 翻页
                if text in ("下一页", "下一页线路"):
                    if page + 1 >= pt:
                        await event.send(MessageChain([Plain(f"已经是最后一页（第 {pt}/{pt} 页）啦~")]))
                        return
                    self._movie_sessions.update(event, source_page=page + 1)
                    await event.send(MessageChain([Plain(format_sources(detail, page=page + 1, page_size=ps))]))
                    return
                if text in ("上一页", "上一页线路"):
                    if page <= 0:
                        await event.send(MessageChain([Plain("已经是第一页啦~")]))
                        return
                    self._movie_sessions.update(event, source_page=page - 1)
                    await event.send(MessageChain([Plain(format_sources(detail, page=page - 1, page_size=ps))]))
                    return

                m2 = re.search(r"\d+", text)
                num = int(m2.group()) if m2 else 0
                if num < 1 or num > show_count:
                    await event.send(MessageChain([Plain(f"请输入1-{show_count}之间的数字（当前第{page+1}/{pt}页共{show_count}条线路）。回复0取消。")]))
                    return
                # ★关键修复 (Bug D): 用全局索引选 srcs，再拿 ep.url (用户选的那集的播放页) 取 m3u8
                global_idx = st + num - 1
                src = srcs[global_idx]
                ep_tag = f" 第{ep['n']}集" if ep else ""
                # ★懒加载 m3u8：从 ep.url 抓 pp.la，找 src['n'] 匹配的线路
                real_url = src["url"]
                line_name = ""
                try:
                    play_url = ep["url"] if ep else src["url"]
                    play = await asyncio.to_thread(parse_play_page, play_url)
                    if play and play.get("lines"):
                        target_ld = ""
                        for ln in play["lines"]:
                            if ln["name"] == f"线路{src['n']}" or str(src['n']) in ln["name"]:
                                target_ld = ln["ld"]
                                break
                        if not target_ld and src['n'] and 1 <= src['n'] <= len(play["lines"]):
                            target_ld = play["lines"][src['n'] - 1]["ld"]
                        if target_ld:
                            for ln in play["lines"]:
                                if ln["ld"] == target_ld:
                                    real_url = ln["m3u8"]
                                    line_name = ln["name"]
                                    break
                except Exception as e:
                    logger.warning(f"[暮黎资源] parse_play_page 失败: {e}")
                chosen_url = real_url
                if not chosen_url or "/v/" in chosen_url:
                    chosen_url = src["url"]
                name = detail.get("name") or sel.get("title", "未知影视")
                gid = event.get_group_id()
                uid = event.get_sender_id()
                logger.info(f"[执行] 影视(on_any_message) {name}{ep_tag} → 线路{num}/{total} (m3u8={chosen_url[:60]})")

                # ★Feature 4: 调用 LLM 查百度百科（简介+演员）
                cast = ""
                desc_brief = ""
                try:
                    cast, desc_brief = await self._fetch_movie_meta_via_llm(event, name)
                except Exception as e:
                    logger.warning(f"[暮黎资源] LLM 查百科失败: {e}")

                await self._send_movie_record(event, name, ep, src,
                                              line_name or src.get('label', f'线路{num}'),
                                              cast, desc_brief, chosen_url, gid, uid)
                self._movie_sessions.delete(event)
                return

        # ══════════════════════════════════════════════
        # 短剧会话 (wangpant8)
        # ══════════════════════════════════════════════
        dses = self._drama_sessions.get(event)
        if dses:
            stage = dses.get("stage", "")

            # ── 取消（所有阶段通用） ──
            if text in cancel_kw:
                event.stop_event()
                self._mark_llm_suppress(event)
                self._drama_sessions.delete(event)
                event.set_result(event.plain_result("已取消搜索。"))
                return

            if stage == "select_drama":
                # 翻页 / 跳转
                if text in page_kw or text.startswith("跳"):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    ps = dses.get("page_size", 8); t = len(dses["results"])
                    cur = dses.get("page", 0)
                    if text in page_kw:
                        dses["page"] = 0 if (cur + 1) * ps >= t else cur + 1 if "下一页" in text else max(0, cur - 1)
                    else:
                        m = re.search(r"\d+", text)
                        if m:
                            pt = (t + ps - 1) // ps
                            dses["page"] = max(0, min(pt - 1, int(m.group()) - 1))
                    dses["_updated"] = time.time()
                    await self._send_search_page(event, "drama", self._format_drama_page(self._drama_sessions.get(event)), ses=self._drama_sessions.get(event))
                    return

                # 数字/自然语言选择 → 取详情 + 返回网盘链接
                if text in num_kw or text.startswith("第") or text.startswith("选") or text.startswith("最后"):
                    event.stop_event()
                    self._mark_llm_suppress(event)
                    num = self._parse_natural_number(text)
                    if num == -2:
                        num = len(dses["results"]) - (dses.get("page", 0) * dses.get("page_size", 8))
                    r = dses["results"]; pg = dses.get("page", 0); ps = dses.get("page_size", 8)
                    t = len(r); st = pg * ps; ed = min(st + ps, t); pc = ed - st
                    if num < 1 or num > pc:
                        await event.send(MessageChain([Plain(f"请输入1-{pc}之间的数字。回复0取消。")]))
                        return
                    ai = st + num - 1; sel = r[ai]
                    self._drama_sessions.update(event, selected_index=ai, stage="fetching")
                    await event.send(MessageChain([Plain(f"🎬 已选择：{sel['title']}\n⏳ 正在获取网盘资源，请稍候...")]))
                    try:
                        det = await asyncio.to_thread(
                            get_drama_detail, sel["id"], int(dses.get("timeout", 15) or 15))
                    except Exception as e:
                        self._drama_sessions.delete(event)
                        await event.send(MessageChain([Plain(f"❌ 获取资源失败：{str(e)[:100]}")]))
                        return
                    if not det.get("success"):
                        self._drama_sessions.delete(event)
                        await event.send(MessageChain([Plain(
                            f"😕 {det.get('error', '未获取到资源链接')}，换一部试试？")]))
                        return
                    title = det.get("title") or sel["title"]
                    ok, note = self._points_final_charge(event, "drama", title)
                    if not ok:
                        await event.send(MessageChain([Plain(note)]))
                        return
                    lines = [
                        f"🎬 {title}",
                        "=" * 30,
                        f"☁️ 网盘：{det.get('disk_type', '夸克')}",
                        f"🔗 资源：{det.get('link', '')}",
                        "",
                        "💡 复制资源链接到夸克网盘转存即可观看。",
                    ]
                    await event.send(MessageChain([Plain("\n".join(lines) + note)]))
                    logger.info(f"[执行] 短剧 {title} → {det.get('link','')}")
                    # 会话结束；换一部请引用短剧列表消息
                    self._drama_sessions.delete(event)
                    return

        # ══════════════════════════════════════════════
        # 小说会话 (so-novel)
        # ══════════════════════════════════════════════
        nses = self._novel_sessions.get(event)
        if nses:
            stage = nses.get("stage", "")
            # 取消（任意阶段通用）
            if text in cancel_kw:
                event.stop_event()
                self._mark_llm_suppress(event)
                self._novel_sessions.delete(event)
                event.set_result(event.plain_result("已取消小说下载。"))
                return
            # 翻页（仅 select_novel 阶段）
            if stage == "select_novel" and (text in page_kw or text.startswith("跳")):
                event.stop_event()
                self._mark_llm_suppress(event)
                r = nses["results"]; ps = nses.get("page_size", 8)
                t = len(r); cur = nses.get("page", 0)
                if text in page_kw:
                    nses["page"] = 0 if (cur + 1) * ps >= t else cur + 1 if "下一页" in text else max(0, cur - 1)
                else:
                    m = re.search(r"\d+", text)
                    if m:
                        pt = (t + ps - 1) // ps
                        nses["page"] = max(0, min(pt - 1, int(m.group()) - 1))
                nses["_updated"] = time.time()
                nses["_llm_handled"] = True
                ses_now = self._novel_sessions.get(event)
                card = ""
                if novel_card_html:
                    try:
                        card = novel_card_html(ses_now, timeout=SESSION_TIMEOUT)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[列表卡片] 小说卡片构建失败，回退文本: {e}")
                await self._send_novel_list(
                    event, self._novel_sessions.get(event), card,
                    self._format_novel_page(ses_now), len(r))
                return
            # 选书
            if stage == "select_novel":
                event.stop_event()
                self._mark_llm_suppress(event)
                r = nses["results"]; p = nses.get("page", 0); ps = nses.get("page_size", 8)
                t = len(r); st = p * ps; ed = min(st + ps, t); pc = ed - st
                number = self._parse_natural_number(text)
                if number == -2:
                    number = pc
                if number < 1 or number > pc:
                    await event.send(MessageChain([Plain(
                        f"请输入 1-{pc} 之间的数字（当前第 {p + 1} 页共 {pc} 条）。回复 0 取消。")]))
                    return
                ai = st + number - 1
                sel = r[ai]
                self._novel_sessions.set(event, {
                    **nses, "stage": "select_format", "selected": sel,
                    "_updated": time.time(), "_llm_handled": True,
                })
                fmt_menu = (
                    f"📚 已选择：《{sel.get('book_name') or '未知'}》／{sel.get('author') or '佚名'}\n"
                    f"请选择下载格式（回复数字或格式名）：\n"
                    + "\n".join(
                        f"  {emoji_index(i, len(NOVEL_FORMATS))} {f.upper()}"
                        + ("（打包为 zip）" if f == "html" else "")
                        for i, f in enumerate(NOVEL_FORMATS, 1))
                    + f"\n\n回复 1-{len(NOVEL_FORMATS)} 选择；回复「下载 / 确认」使用默认 TXT；回复 0 取消。"
                )
                await event.send(MessageChain([Plain(fmt_menu)]))
                return
            # 选格式 → 触发下载（默认格式支持多选：回复「下载/确认」生成全部默认格式）
            if stage == "select_format":
                event.stop_event()
                self._mark_llm_suppress(event)
                sel = nses.get("selected", {})
                base, token, limit, def_fmts, timeout, dl_timeout = self._novel_cfg()
                low = text.strip().lower()
                # 确认词 → 使用配置的全部默认格式；否则解析单个临时格式
                if low in ("下载", "确认", "ok", "go", "默认", "直接", "是", "y", "yes", "全部", "all"):
                    fmt_list = list(def_fmts) or ["txt"]
                else:
                    fm = re.search(r"(txt|epub|html|pdf)", low)
                    if fm:
                        fmt_list = [fm.group(1)]
                    else:
                        num = self._parse_natural_number(text)
                        if 1 <= num <= len(NOVEL_FORMATS):
                            fmt_list = [NOVEL_FORMATS[num - 1]]
                        else:
                            await event.send(MessageChain([Plain(
                                f"未识别格式，请回复 1-{len(NOVEL_FORMATS)} 选择，"
                                f"或回复「下载/确认」使用默认格式。回复 0 取消。")]))
                            return
                multi = len(fmt_list) > 1
                fmt_label = "、".join(f.upper() for f in fmt_list)
                suffix = "（多格式将依次抓取，请稍候…）" if multi else ""
                can, balance, cost = self._points_can_afford(event, "novel")
                if not can:
                    await event.send(MessageChain([Plain(
                        f"【暮黎资源·积分】\n💰 获取小说需要 {cost} 积分，"
                        f"你当前只有 {balance} 积分。\n📅 发送 /签到 领取每日积分后再试。")]))
                    return
                await event.send(MessageChain([Plain(
                    f"⏳ 已提交《{sel.get('book_name', '')}》下载任务，"
                    f"生成格式：{fmt_label}{suffix}")]))
                book_name = sel.get("book_name", "") or "小说"
                author = sel.get("author", "") or ""
                results = []
                for fmt in fmt_list:
                    try:
                        # 1) 服务端抓取整本 + 插件侧拉取字节 + 按文件头校验真实格式。
                        #    download_novel 会在「同名旧文件 / 错格式」时自动换候选，
                        #    避免把上次的 TXT 改名成 .epub / .pdf 发出去。
                        dl = await asyncio.to_thread(
                            download_novel, sel, base, token, fmt, dl_timeout)
                        content = dl["content"]
                        fname = dl["file_name"]
                        ext = dl.get("ext") or (
                            fname.rsplit(".", 1)[-1].lower() if "." in fname else fmt)
                        if not content:
                            raise NovelApiError("下载到的文件内容为空，书源可能已失效",
                                                stage="download")
                        # 2) 落盘后发送：优先 base64 经 OneBot 文件接口（规避
                        #    「客户端读不到 AstrBot 容器内 /tmp」的 ENOENT），
                        #    失败再退 AstrBot 文件组件，并把真实原因带回来。
                        fd, tp = tempfile.mkstemp(suffix=f".{ext}", prefix="novel_")
                        os.close(fd)
                        with open(tp, "wb") as f:
                            f.write(content)
                        try:
                            ok, reason = await self._send_file_to_chat(
                                tp, fname, event=event, label=fmt.upper())
                        finally:
                            if os.path.exists(tp):
                                try:
                                    os.unlink(tp)
                                except Exception:
                                    pass
                        if ok:
                            results.append((fmt, fname, None, len(content)))
                        else:
                            results.append((fmt, None, reason or "文件发送失败", 0))
                    except Exception as e:
                        msg = e.message if isinstance(e, NovelApiError) else str(e)[:200]
                        results.append((fmt, None, msg, 0))
                ok_count = sum(1 for r in results if r[1])
                point_note = ""
                if ok_count > 0:
                    okc, bal, pcost = self._points_spend_now(event, "novel")
                    if okc and pcost > 0:
                        point_note = (f"\n\n💰 本次获取资源消耗 {pcost} 积分，"
                                      f"剩余 {bal} 积分（发送 /签到 领取每日积分）")
                lines = [
                    f"✅ 下载完成：《{book_name}》／{author}",
                    f"📦 已发送 {ok_count}/{len(fmt_list)} 个格式",
                ]
                for fmt, fname, err, size in results:
                    if err:
                        lines.append(f"❌ {fmt.upper()}：{err}")
                    else:
                        lines.append(f"✅ {fmt.upper()}：{fname}（{_format_size(size)}）")
                if any(r[0] == "html" and r[1] for r in results):
                    lines.append("💡 HTML 版是 zip 压缩包，解压后打开 0_目录.txt 或章节页即可。")
                if ok_count == 0:
                    lines.append("💡 全部格式失败：PDF 多为 so-novel 缺中文字体（见上方提示），"
                                 "其余可换一个书源或改用 TXT 重试。")
                await event.send(MessageChain([Plain("\n".join(lines) + point_note)]))
                # 会话结束；换一本请引用小说列表消息
                self._novel_sessions.delete(event)
                return

        # ── 无活跃 session → 正常退出，不 stop_event，让 LLM 接 ──

    def _framework_scheduler(self):
        """获取 AstrBot 官方调度器（context.cron_manager.scheduler）。不可用返回 None。"""
        try:
            cm = getattr(self.context, "cron_manager", None)
            if cm is not None:
                sch = getattr(cm, "scheduler", None)
                if sch is not None:
                    return sch
        except Exception:
            pass
        return None

    @staticmethod
    def _job_next_run(job, tz=None):
        """读取调度任务的「下次运行时间」，取不到就返回 None。

        APScheduler 3.x 的 Job 在 **scheduler 尚未 start** 时不会写入
        next_run_time（任务先挂在 _pending_jobs 里），直接访问会抛
        `'Job' object has no attribute 'next_run_time'`。
        插件 initialize 早于 AstrBot 启动 cron_manager，必然踩到这条路径，
        所以这里统一用 getattr 并回退到 trigger 现场推算。
        """
        if job is None:
            return None
        try:
            nxt = getattr(job, "next_run_time", None)
        except Exception:
            nxt = None
        if nxt is not None:
            return nxt
        trig = getattr(job, "trigger", None)
        if trig is None:
            return None
        try:
            now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
            return trig.get_next_fire_time(None, now)
        except Exception:
            return None

    # ==================== 日报运行状态持久化（防止重装/重启后重复补发） ====================
    # 四个日报的「今日已发送日期」原本只存在内存：插件一重装/热重载就归零，
    # 兜底守护（_sw_fallback）会立刻把当天已过时间点的日报全部补发一遍。
    # 这里把状态落到 data 目录下的 json，重装后也能读到，从而不再重复触发。

    _REPORT_STATE_KINDS = {
        "sw": "_last_run_date",
        "game": "_game_last_run_date",
        "movie": "_movie_last_run_date",
        "drama": "_drama_last_run_date",
    }

    def _report_state_path(self) -> str:
        return os.path.join(self._plugin_data_dir(), "daily_reports_state.json")

    def _load_report_state(self):
        """从 data 目录恢复各日报「上次发送日期」。"""
        try:
            p = self._report_state_path()
            if not os.path.exists(p):
                return
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            restored = []
            for kind, attr in self._REPORT_STATE_KINDS.items():
                v = str(data.get(kind) or "").strip()
                if v:
                    setattr(self, attr, v)
                    restored.append(f"{kind}={v}")
            if restored:
                logger.info(f"[暮黎资源] 已恢复日报运行状态（本次不会重复补发）: {', '.join(restored)}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] 读取日报运行状态失败(忽略): {e!r}")

    def _persist_report_state(self):
        try:
            p = self._report_state_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            data = {k: str(getattr(self, a, "") or "") for k, a in self._REPORT_STATE_KINDS.items()}
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)  # 原子替换，避免半截文件
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源] 写入日报运行状态失败(忽略): {e!r}")

    def _mark_report_ran(self, kind: str, ts: str):
        """标记某日报今日已处理（含占位），并即时持久化，重装后不会再触发。"""
        attr = self._REPORT_STATE_KINDS.get(kind)
        if not attr:
            return
        if getattr(self, attr, "") == ts:
            return
        setattr(self, attr, ts)
        self._persist_report_state()

    async def _start_sw_scheduler(self):
        """注册三个独立日报的每日定时任务。

        优先使用 AstrBot 官方 context.cron_manager.scheduler + CronTrigger(hour,minute)
        （与 AstrBot 主事件循环绑定，可靠触发）；不可用时回退自建 AsyncIOScheduler。
        """
        await self._stop_sw_scheduler()
        try: self._timezone = zoneinfo.ZoneInfo("Asia/Shanghai")
        except Exception:
            try: self._timezone = zoneinfo.ZoneInfo("local")
            except Exception: self._timezone = None
        config = self._get_config()
        try:
            h = int(config.get("schedule_hour",10) if isinstance(config,dict) else 10)
            m = int(config.get("schedule_minute",0) if isinstance(config,dict) else 0)
        except Exception: h,m = 10,0
        self._schedule_hour = max(0,min(23,h)); self._schedule_minute = max(0,min(59,m))
        # 游戏日报独立调度（与软件日报分开）
        try:
            gh = int(config.get("game_schedule_hour",18) if isinstance(config,dict) else 18)
            gm = int(config.get("game_schedule_minute",0) if isinstance(config,dict) else 0)
        except Exception: gh,gm = 18,0
        self._game_schedule_hour = max(0,min(23,gh)); self._game_schedule_minute = max(0,min(59,gm))
        # 影视日报独立调度（与软件/游戏日报分开）
        try:
            mh = int(config.get("movie_schedule_hour",20) if isinstance(config,dict) else 20)
            mm = int(config.get("movie_schedule_minute",0) if isinstance(config,dict) else 0)
        except Exception: mh,mm = 20,0
        self._movie_schedule_hour = max(0,min(23,mh)); self._movie_schedule_minute = max(0,min(59,mm))
        # 短剧日报独立调度（与软件/游戏/影视日报分开）
        try:
            dh = int(config.get("drama_schedule_hour",21) if isinstance(config,dict) else 21)
            dm = int(config.get("drama_schedule_minute",0) if isinstance(config,dict) else 0)
        except Exception: dh,dm = 21,0
        self._drama_schedule_hour = max(0,min(23,dh)); self._drama_schedule_minute = max(0,min(59,dm))
        self._scheduled_job_ids = []
        sch = self._framework_scheduler()
        if sch is not None:
            # ===== 官方调度器：CronTrigger 每日重复，无需手动重排 =====
            self._using_framework_scheduler = True
            tz_kw = {"timezone": self._timezone} if self._timezone else {}
            jobs = [
                (self._scheduler_job_id, self._schedule_hour, self._schedule_minute, self._sw_daily_job, "软件日报"),
                (self._game_scheduler_job_id, self._game_schedule_hour, self._game_schedule_minute, self._game_daily_job, "游戏日报"),
                (self._movie_scheduler_job_id, self._movie_schedule_hour, self._movie_schedule_minute, self._movie_daily_job, "影视日报"),
                (self._drama_scheduler_job_id, self._drama_schedule_hour, self._drama_schedule_minute, self._drama_daily_job, "短剧日报"),
            ]
            for job_id, jh, jm, func, name in jobs:
                try:
                    sch.add_job(func, CronTrigger(hour=int(jh), minute=int(jm), **tz_kw),
                                id=job_id, replace_existing=True, misfire_grace_time=600)
                except Exception as e:
                    logger.error(f"[暮黎资源] 注册官方定时任务失败 ({name}): {e}")
                    continue
                self._scheduled_job_ids.append(job_id)
                # 插件初始化早于 AstrBot 启动 cron_manager：此时任务挂在
                # _pending_jobs，Job 上还没有 next_run_time，不能直接点访问。
                nxt_dt = self._job_next_run(sch.get_job(job_id), self._timezone)
                nxt = nxt_dt.strftime("%Y-%m-%d %H:%M") if nxt_dt else "待调度器启动"
                logger.info(f"[暮黎资源] 已注册官方定时任务: {name} @ {int(jh):02d}:{int(jm):02d} (Asia/Shanghai) 下次运行: {nxt}")
            # 配置热更新守护：每 600s 检测时间配置变更并重新注册
            if self._heartbeat_task: self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._sw_heartbeat(), name="sw_heartbeat")
            logger.info(f"[暮黎资源] 官方定时调度已就绪（{len(self._scheduled_job_ids)} 个任务）")
        else:
            # ===== 回退：自建 AsyncIOScheduler + CronTrigger 每日重复（不依赖手动重排）=====
            self._using_framework_scheduler = False
            logger.warning("[暮黎资源] 未找到官方 context.cron_manager.scheduler，回退自建 AsyncIOScheduler(CronTrigger)")
            tz_kw = {"timezone": self._timezone} if self._timezone else {}
            jobs = [
                (self._scheduler_job_id, self._schedule_hour, self._schedule_minute, self._sw_daily_job, "软件日报"),
                (self._game_scheduler_job_id, self._game_schedule_hour, self._game_schedule_minute, self._game_daily_job, "游戏日报"),
                (self._movie_scheduler_job_id, self._movie_schedule_hour, self._movie_schedule_minute, self._movie_daily_job, "影视日报"),
                (self._drama_scheduler_job_id, self._drama_schedule_hour, self._drama_schedule_minute, self._drama_daily_job, "短剧日报"),
            ]
            self._apscheduler = AsyncIOScheduler(**tz_kw); self._apscheduler.start()
            for job_id, jh, jm, func, name in jobs:
                try:
                    self._apscheduler.add_job(func, CronTrigger(hour=int(jh), minute=int(jm), **tz_kw),
                                id=job_id, replace_existing=True, misfire_grace_time=600)
                    self._scheduled_job_ids.append(job_id)
                    logger.info(f"[暮黎资源] 已注册自建定时任务: {name} @ {int(jh):02d}:{int(jm):02d}")
                except Exception as e:
                    logger.error(f"[暮黎资源] 注册自建定时任务失败 ({name}): {e}")
            if self._heartbeat_task: self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._sw_heartbeat(), name="sw_heartbeat")
            logger.info(f"[暮黎资源] 自建定时调度已就绪（{len(self._scheduled_job_ids)} 个任务）")
        # 启动兜底守护：机器人恰好在定时点之后/重启晚于定时点上线时，
        # 补发『今天已过目标时间且今日尚未发送』的日报（见 _sw_fallback）。
        if self._fallback_task:
            self._fallback_task.cancel()
        self._fallback_task = asyncio.create_task(self._sw_fallback(), name="sw_fallback")
        logger.info("[暮黎资源] 兜底守护任务已启动（机器人恢复上线后补发今日日报）")
        # 持久化数据统一放到 AstrBot data 目录下（不得写入插件安装目录，
        # 否则卸载/覆盖重装时插件目录被删会导致日报缓存与调试日志丢失）。
        _pd = self._plugin_data_dir()
        # 一次性迁移：把旧版遗留在插件目录内的 debug_logs / reports 挪到新位置
        try:
            _legacy = os.path.dirname(__file__)
            if os.path.abspath(_legacy) != os.path.abspath(_pd):
                import shutil
                for _name in ("debug_logs", "reports"):
                    _old = os.path.join(_legacy, _name)
                    _new = os.path.join(_pd, _name)
                    if os.path.isdir(_old) and not os.path.exists(_new):
                        try:
                            os.makedirs(os.path.dirname(_new), exist_ok=True)
                            shutil.move(_old, _new)
                        except Exception:
                            pass
        except Exception:
            pass
        try:
            d = os.path.join(_pd,"debug_logs"); os.makedirs(d,exist_ok=True)
            self._debug_log_path = os.path.join(d,"scheduler_debug.log")
        except Exception: pass
        try:
            self._reports_dir = os.path.join(_pd,"reports"); os.makedirs(self._reports_dir,exist_ok=True)
            self._sw_cleanup_reports()
        except Exception: pass

    async def _stop_sw_scheduler(self):
        # 1. 取消后台守护任务
        #    注意：await 一个被 cancel() 的任务会抛 asyncio.CancelledError，
        #    而它在 Python 3.8+ 继承自 BaseException，普通 except Exception 抓不到，
        #    若不显式捕获会一路冒泡到 platform_manager 导致整个机器人启动崩溃。
        if self._fallback_task:
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except (asyncio.CancelledError, Exception):
                pass
            self._fallback_task = None
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        # 2. 移除官方调度器上的定时任务
        if self._using_framework_scheduler:
            sch = self._framework_scheduler()
            if sch is not None:
                for jid in self._scheduled_job_ids:
                    try:
                        if sch.get_job(jid): sch.remove_job(jid)
                    except Exception: pass
            self._scheduled_job_ids = []
            self._using_framework_scheduler = False
        # 3. 关闭自建调度器
        if self._apscheduler and self._apscheduler.running:
            try: self._apscheduler.shutdown(wait=True)
            except Exception: pass
            self._apscheduler = None

    def _sw_next_run(self):
        n = datetime.datetime.now(self._timezone) if self._timezone else datetime.datetime.now()
        nr = n.replace(hour=self._schedule_hour,minute=self._schedule_minute,second=0,microsecond=0)
        if nr <= n: nr += datetime.timedelta(days=1)
        return nr

    def _game_next_run(self):
        n = datetime.datetime.now(self._timezone) if self._timezone else datetime.datetime.now()
        nr = n.replace(hour=self._game_schedule_hour,minute=self._game_schedule_minute,second=0,microsecond=0)
        if nr <= n: nr += datetime.timedelta(days=1)
        return nr

    def _schedule_sw_next(self):
        # 已统一改用 CronTrigger 每日重复，无需手动重排下一次
        return

    def _schedule_game_next(self):
        # 已统一改用 CronTrigger 每日重复，无需手动重排下一次
        return

    def _movie_next_run(self):
        n = datetime.datetime.now(self._timezone) if self._timezone else datetime.datetime.now()
        nr = n.replace(hour=self._movie_schedule_hour,minute=self._movie_schedule_minute,second=0,microsecond=0)
        if nr <= n: nr += datetime.timedelta(days=1)
        return nr

    def _schedule_movie_next(self):
        # 已统一改用 CronTrigger 每日重复，无需手动重排下一次
        return

    def _drama_next_run(self):
        n = datetime.datetime.now(self._timezone) if self._timezone else datetime.datetime.now()
        nr = n.replace(hour=self._drama_schedule_hour,minute=self._drama_schedule_minute,second=0,microsecond=0)
        if nr <= n: nr += datetime.timedelta(days=1)
        return nr

    def _schedule_drama_next(self):
        # 已统一改用 CronTrigger 每日重复，无需手动重排下一次
        return

    async def _sw_heartbeat(self):
        """每 600s 守护一次：
        - 官方模式下检测日报时间配置是否变更，变更则重新注册（配置热更新）；
        - 兜底：若任务丢失则重注册。自建模式下保留原重排逻辑。
        """
        while True:
            try:
                await asyncio.sleep(600)
                config = self._get_config()
                try:
                    nh = int(config.get("schedule_hour",10) if isinstance(config,dict) else 10)
                    nm = int(config.get("schedule_minute",0) if isinstance(config,dict) else 0)
                    ngh = int(config.get("game_schedule_hour",18) if isinstance(config,dict) else 18)
                    ngm = int(config.get("game_schedule_minute",0) if isinstance(config,dict) else 0)
                    nmh = int(config.get("movie_schedule_hour",20) if isinstance(config,dict) else 20)
                    nmm = int(config.get("movie_schedule_minute",0) if isinstance(config,dict) else 0)
                    ndh = int(config.get("drama_schedule_hour",21) if isinstance(config,dict) else 21)
                    ndm = int(config.get("drama_schedule_minute",0) if isinstance(config,dict) else 0)
                except Exception:
                    nh,nm,ngh,ngm,nmh,nmm,ndh,ndm = 10,0,18,0,20,0,21,0
                changed = (nh != self._schedule_hour or nm != self._schedule_minute or
                           ngh != self._game_schedule_hour or ngm != self._game_schedule_minute or
                           nmh != self._movie_schedule_hour or nmm != self._movie_schedule_minute or
                           ndh != self._drama_schedule_hour or ndm != self._drama_schedule_minute)
                if changed:
                    logger.info("[暮黎资源] 检测到日报时间配置变更，重新注册定时任务")
                    await self._start_sw_scheduler(); continue
                if self._using_framework_scheduler:
                    sch = self._framework_scheduler()
                    if sch is None:
                        logger.warning("[暮黎资源] 官方调度器不可用，尝试回退自建"); await self._start_sw_scheduler(); continue
                    for jid in self._scheduled_job_ids:
                        try:
                            if not sch.get_job(jid): raise RuntimeError("missing")
                        except Exception:
                            logger.warning("[暮黎资源] 官方定时任务丢失，重新注册"); await self._start_sw_scheduler(); break
                else:
                    if not self._apscheduler or not self._apscheduler.running: await self._start_sw_scheduler(); continue
                    if not self._job_next_run(self._apscheduler.get_job(self._scheduler_job_id), self._timezone):
                        self._schedule_sw_next()
                    if not self._job_next_run(self._apscheduler.get_job(self._game_scheduler_job_id), self._timezone):
                        self._schedule_game_next()
                    if not self._job_next_run(self._apscheduler.get_job(self._movie_scheduler_job_id), self._timezone):
                        self._schedule_movie_next()
                    if not self._job_next_run(self._apscheduler.get_job(self._drama_scheduler_job_id), self._timezone):
                        self._schedule_drama_next()
            except asyncio.CancelledError: return
            except Exception: pass

    async def _sw_fallback(self):
        """兜底守护：机器人恰好在定时点之后（含重启晚于定时点）上线时，
        补发『今天已过目标时间且今日尚未发送』的日报，避免全天漏发。

        进入循环前先立即检查一次（不等 30s），随后每 30s 轮询。
        是否真正发送由各 *_daily_job 内的『今日已运行』guard 决定，天然防重复。
        """
        try:
            await self._sw_fallback_check()
        except Exception:
            pass
        while True:
            try:
                await asyncio.sleep(30)
                await self._sw_fallback_check()
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    async def _sw_fallback_check(self):
        n = datetime.datetime.now(self._timezone) if self._timezone else datetime.datetime.now()
        ts = n.strftime("%Y%m%d")
        # 软件日报：今天目标时间已过 且 今日尚未发送 → 补发
        tgt = n.replace(hour=self._schedule_hour, minute=self._schedule_minute, second=0, microsecond=0)
        if n >= tgt and self._last_run_date != ts:
            logger.warning(f"[暮黎资源] 🛡️ 软件日报兜底补发（今日目标 {self._schedule_hour:02d}:{self._schedule_minute:02d} 已过且未发送）")
            try: await self._sw_daily_job()
            except Exception as e: logger.error(f"[暮黎资源] 软件日报兜底执行失败: {e!r}")
        # 游戏日报
        gtgt = n.replace(hour=self._game_schedule_hour, minute=self._game_schedule_minute, second=0, microsecond=0)
        if n >= gtgt and self._game_last_run_date != ts:
            logger.warning(f"[暮黎资源] 🛡️ 游戏日报兜底补发（今日目标 {self._game_schedule_hour:02d}:{self._game_schedule_minute:02d} 已过且未发送）")
            try: await self._game_daily_job()
            except Exception as e: logger.error(f"[暮黎资源] 游戏日报兜底执行失败: {e!r}")
        # 影视日报
        mtgt = n.replace(hour=self._movie_schedule_hour, minute=self._movie_schedule_minute, second=0, microsecond=0)
        if n >= mtgt and self._movie_last_run_date != ts:
            logger.warning(f"[暮黎资源] 🛡️ 影视日报兜底补发（今日目标 {self._movie_schedule_hour:02d}:{self._movie_schedule_minute:02d} 已过且未发送）")
            try: await self._movie_daily_job()
            except Exception as e: logger.error(f"[暮黎资源] 影视日报兜底执行失败: {e!r}")
        # 短剧日报
        dtgt = n.replace(hour=self._drama_schedule_hour, minute=self._drama_schedule_minute, second=0, microsecond=0)
        if n >= dtgt and self._drama_last_run_date != ts:
            logger.warning(f"[暮黎资源] 🛡️ 短剧日报兜底补发（今日目标 {self._drama_schedule_hour:02d}:{self._drama_schedule_minute:02d} 已过且未发送）")
            try: await self._drama_daily_job()
            except Exception as e: logger.error(f"[暮黎资源] 短剧日报兜底执行失败: {e!r}")

    def _sw_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir,f"sw_report_{ds}.zip") if self._reports_dir else ""

    def _sw_cleanup_reports(self):
        if not self._reports_dir: return
        try:
            now = datetime.date.today(); cut = now - datetime.timedelta(days=self._reports_retention_days)
            for fn in os.listdir(self._reports_dir):
                if not fn.endswith(".zip"): continue
                if not (fn.startswith("sw_report_") or fn.startswith("game_report_")
                        or fn.startswith("movie_report_") or fn.startswith("drama_report_")): continue
                p = (fn.replace("sw_report_","").replace("game_report_","").replace("movie_report_","").replace("drama_report_","").replace(".zip",""))
                if len(p)!=8 or not p.isdigit(): continue
                fd = datetime.date(int(p[:4]),int(p[4:6]),int(p[6:8]))
                if fd < cut: os.remove(os.path.join(self._reports_dir,fn))
        except: pass

    def _movie_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir, f"movie_report_{ds}.zip") if self._reports_dir else ""

    async def _movie_send_report(self, img_bytes, ts, text: str = "", gids=None):
        if gids is None:
            gids = await self._resolve_report_groups("movie_group_ids")
        if not gids: return 0
        apid = self._resolve_report_platform()
        logger.info(f"[暮黎资源] 影视日报推送目标平台: {apid} | 目标群: {gids}")
        fn = f"暮黎影视日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        sent = 0
        for gid in gids:
            umo = f"{apid}:GroupMessage:{gid}"
            if await self._try_send_group_file(umo, img_bytes, fn, text, "影视日报"):
                sent += 1
        logger.info(f"[暮黎资源] 影视日报本次成功推送 {sent}/{len(gids)} 个群")
        return sent

    async def _movie_build_and_send(self, items: list, ts: str, source_label: str = "pdy0", gids=None):
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        html = build_glass_html(items, date_label, source_label=source_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        config = self._get_config()
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[影视日报] 开始渲染，共 {len(items)} 部，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_glass_to_png, html, font_path, 720, channel, exe)
            logger.info(f"[影视日报] 渲染完成" + (f"，原始图片体积 {len(img_bytes)//1024}KB" if img_bytes else "，但未返回图片(将用兜底渲染)"))
        except Exception as e:
            logger.error(f"[影视日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
        if not img_bytes:
            # ① AstrBot 内置 html_renderer（云端 T2I，无需本机浏览器）
            logger.info("[影视日报] Playwright 不可用，尝试 AstrBot 内置渲染")
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            # ② Pillow 纯 Python 兜底（永远可用）
            logger.info("[影视日报] 尝试 Pillow 兜底渲染")
            cards = []
            for it in items:
                chips = []
                if it.get("status"):
                    chips.append(str(it["status"]))
                db = it.get("douban", "")
                if db and str(db) not in ("0", "0.0", ""):
                    chips.append("豆瓣 " + str(db))
                im = it.get("imdb", "")
                if im and str(im) not in ("0", "0.0", ""):
                    chips.append("IMDb " + str(im))
                for q in (it.get("quality") or []):
                    chips.append(str(q))
                cards.append({
                    "cover": it.get("cover_b64") or "",
                    "title": it.get("title") or "未知",
                    "chips": chips,
                    "desc": (it.get("synopsis") or "暂无简介")[:160],
                })
            img_bytes = await self._report_pil_fallback(
                cards, date_label, source_label, font_path, 720, "影视日报")
        if img_bytes and len(img_bytes) > 2 * 1024 * 1024:
            logger.info(f"[影视日报] 原始图 {len(img_bytes)//1024}KB 超过 2MB，开始压缩...")
            img_bytes = self._compress_game_image(img_bytes)
            logger.info(f"[影视日报] 压缩后体积 {len(img_bytes)//1024}KB")
        # 始终构建文字版，作为图片上传失败时的兜底（定时任务无 event 可用）
        text = (f"🎬 暮黎影视日报 {date_label}\n今日更新 {len(items)} 部：\n"
                + "\n".join(f"{i}. {it.get('title','')}（{it.get('type_name','')}）{(' '+it.get('status','')) if it.get('status') else ''}"
                             for i, it in enumerate(items, 1)))
        if not img_bytes:
            logger.warning("[影视日报] 图片渲染失败，将改用文字版推送")
        return await self._movie_send_report(img_bytes, ts, text, gids=gids)

    async def _movie_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._movie_last_run_date == ts:
                logger.info(f"[暮黎资源] 影视日报今日({ts})已运行过，跳过")
                return
            config = self._get_config()
            if not (config.get("movie_report_enabled", True) if isinstance(config, dict) else True):
                logger.warning("[暮黎资源] 影视日报已触发，但 movie_report_enabled 关闭，跳过")
                self._mark_report_ran("movie", ts)
                return
            gs_list = await self._resolve_report_groups("movie_group_ids")
            if not gs_list:
                logger.warning("[暮黎资源] 影视日报未能获取目标群（留空=全部群），等待兜底重试")
                return
            self._mark_report_ran("movie", ts)  # 先占位，防止并发重入（并持久化）
        logger.info(f"[暮黎资源] ⏰ 影视日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        cookie = (config.get("muliy_cookie", "") or "") if isinstance(config, dict) else ""
        username = (config.get("muliy_username", "") or "") if isinstance(config, dict) else ""
        password = (config.get("muliy_password", "") or "") if isinstance(config, dict) else ""
        mx = int(config.get("movie_report_max", 24) or 24)
        sections = self._parse_multi(config.get("movie_sections", ["mv", "tv", "ac"]) or ["mv", "tv", "ac"])
        sections_filter = [s for s in sections if s in ("mv", "tv", "ac")] or None
        # 日报源：pdy0 优先（免登录），失败且有片库凭据时自动回退片库主站
        logger.info("[影视日报] 开始抓取（源=pdy0 优先，片库主站备用）")
        result = await asyncio.to_thread(fetch_movie_daily_auto, cookie, "", mx, sections_filter, True,
                                         username, password)
        if not result["success"]:
            logger.warning(f"[影视日报] 抓取失败: {result.get('error','')}（不标记今日完成，兜底守护将重试）")
            return
        items = result.get("items", [])
        if not items:
            logger.info("[影视日报] 今日暂无更新，标记今日已完成")
            self._mark_report_ran("movie", ts); return
        src_label = result.get("source", "pdy0")
        # 缓存 zip 供面板回看
        try:
            date_label = datetime.date.today().strftime("%Y年%m月%d日")
            html = build_glass_html(items, date_label, source_label=src_label)
            zp = await asyncio.to_thread(gen_movie_report_zip, items, html, ts)
            if zp:
                import shutil
                shutil.copy2(zp, self._movie_cached_path(ts))
                self._sw_cleanup_reports()
        except Exception as e: logger.warning(f"[影视日报] 缓存 zip 失败: {e}")
        sent = await self._movie_build_and_send(items, ts, src_label, gids=gs_list)
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._mark_report_ran("movie", ts)
            logger.info(f"[影视日报] 今日推送完成（{sent} 群）")
        else:
            logger.error("[影视日报] 抓取成功但发送 0 群，兜底守护将重试")
        self._schedule_movie_next()

    @filter.command("movie_report")
    async def cmd_movie_report(self, event: AstrMessageEvent):
        config = self._get_config()
        cookie = (config.get("muliy_cookie", "") or "") if isinstance(config, dict) else ""
        username = (config.get("muliy_username", "") or "") if isinstance(config, dict) else ""
        password = (config.get("muliy_password", "") or "") if isinstance(config, dict) else ""
        mx = int(config.get("movie_report_max", 24) or 24)
        sections = self._parse_multi(config.get("movie_sections", ["mv", "tv", "ac"]) or ["mv", "tv", "ac"])
        sections_filter = [s for s in sections if s in ("mv", "tv", "ac")] or None
        yield event.plain_result("⏳ 正在抓取 pdy0（片库主站备用）最近更新影视...")
        result = await asyncio.to_thread(fetch_movie_daily_auto, cookie, "", mx, sections_filter, True,
                                         username, password)
        if not result["success"]:
            yield event.plain_result(f"⚠️ {result.get('error','未知')}"); return
        items = result.get("items", [])
        if not items:
            yield event.plain_result("📭 今日暂无影视更新。"); return
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        src_label = result.get("source", "pdy0")
        html = build_glass_html(items, date_label, source_label=src_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        try:
            img_bytes = await asyncio.to_thread(render_glass_to_png, html, font_path, 720, channel, exe)
        except Exception as e: logger.error(f"[影视日报] 渲染异常: {e}")
        if not img_bytes:
            # ① AstrBot 内置 html_renderer（云端 T2I，无需本机浏览器）
            logger.info("[影视日报] Playwright 不可用，尝试 AstrBot 内置渲染")
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            # ② Pillow 纯 Python 兜底（永远可用）
            logger.info("[影视日报] 尝试 Pillow 兜底渲染")
            cards = []
            for it in items:
                chips = []
                if it.get("status"):
                    chips.append(str(it["status"]))
                db = it.get("douban", "")
                if db and str(db) not in ("0", "0.0", ""):
                    chips.append("豆瓣 " + str(db))
                im = it.get("imdb", "")
                if im and str(im) not in ("0", "0.0", ""):
                    chips.append("IMDb " + str(im))
                for q in (it.get("quality") or []):
                    chips.append(str(q))
                cards.append({
                    "cover": it.get("cover_b64") or "",
                    "title": it.get("title") or "未知",
                    "chips": chips,
                    "desc": (it.get("synopsis") or "暂无简介")[:160],
                })
            img_bytes = await self._report_pil_fallback(
                cards, date_label, src_label, font_path, 720, "影视日报")
        ts = datetime.date.today().strftime("%Y%m%d")
        fn = f"暮黎影视日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        if img_bytes:
            ok = await self._send_event_file(event, img_bytes, fn, "", "影视日报")
            if not ok:
                yield event.plain_result("⚠️ 日报图片发送失败，已尝试降级发图/文字版。")
        else:
            await event.send(MessageChain([Plain(
                "⚠️ 图片渲染失败，改为文字版：\n"
                + "\n".join(f"{i}. {it.get('title','')}（{it.get('type_name','')}）{(' '+it.get('status','')) if it.get('status') else ''}"
                             for i, it in enumerate(items, 1)))]))

    def _drama_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir, f"drama_report_{ds}.zip") if self._reports_dir else ""

    async def _drama_send_report(self, img_bytes, ts, text: str = "", gids=None):
        if gids is None:
            gids = await self._resolve_report_groups("drama_group_ids")
        if not gids: return 0
        apid = self._resolve_report_platform()
        logger.info(f"[暮黎资源] 短剧日报推送目标平台: {apid} | 目标群: {gids}")
        fn = f"暮黎短剧日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        sent = 0
        for gid in gids:
            umo = f"{apid}:GroupMessage:{gid}"
            if await self._try_send_group_file(umo, img_bytes, fn, text, "短剧日报"):
                sent += 1
        logger.info(f"[暮黎资源] 短剧日报本次成功推送 {sent}/{len(gids)} 个群")
        return sent

    async def _drama_build_and_send(self, items: list, ts: str, gids=None):
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        html = build_drama_html(items, date_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        config = self._get_config()
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[短剧日报] 开始渲染，共 {len(items)} 部，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_drama_to_png, html, font_path, 720, channel, exe)
            logger.info(f"[短剧日报] 渲染完成" + (f"，原始图片体积 {len(img_bytes)//1024}KB" if img_bytes else "，但未返回图片(将用兜底渲染)"))
        except Exception as e:
            logger.error(f"[短剧日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
        if not img_bytes:
            # ① AstrBot 内置 html_renderer（云端 T2I，无需本机浏览器）
            logger.info("[短剧日报] Playwright 不可用，尝试 AstrBot 内置渲染")
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            # ② Pillow 纯 Python 兜底（永远可用）
            logger.info("[短剧日报] 尝试 Pillow 兜底渲染")
            cards = []
            for it in items:
                chips = [c for c in (it.get("category") or "短剧",
                                     it.get("date") or "",
                                     it.get("disk") or "夸克") if c]
                cards.append({"cover": "", "title": it.get("title") or "未知",
                              "chips": chips, "desc": (it.get("link") or "暂无链接")[:160]})
            img_bytes = await self._report_pil_fallback(
                cards, date_label, "网盘贴吧", font_path, 720, "短剧日报")
        if img_bytes and len(img_bytes) > 2 * 1024 * 1024:
            logger.info(f"[短剧日报] 原始图 {len(img_bytes)//1024}KB 超过 2MB，开始压缩...")
            img_bytes = self._compress_game_image(img_bytes)
            logger.info(f"[短剧日报] 压缩后体积 {len(img_bytes)//1024}KB")
        # 始终构建文字版，作为图片上传失败时的兜底（定时任务无 event 可用）
        text = (f"🎬 暮黎短剧日报 {date_label}\n今日上新 {len(items)} 部：\n"
                + "\n".join(f"{i}. {it.get('title','')}  {it.get('link','')}"
                             for i, it in enumerate(items, 1)))
        if not img_bytes:
            logger.warning("[短剧日报] 图片渲染失败，将改用文字版推送")
        return await self._drama_send_report(img_bytes, ts, text, gids=gids)

    async def _drama_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._drama_last_run_date == ts:
                logger.info(f"[暮黎资源] 短剧日报今日({ts})已运行过，跳过")
                return
            config = self._get_config()
            if not (config.get("drama_report_enabled", True) if isinstance(config, dict) else True):
                logger.warning("[暮黎资源] 短剧日报已触发，但 drama_report_enabled 关闭，跳过")
                self._mark_report_ran("drama", ts)
                return
            gs_list = await self._resolve_report_groups("drama_group_ids")
            if not gs_list:
                logger.warning("[暮黎资源] 短剧日报未能获取目标群（留空=全部群），等待兜底重试")
                return
            self._mark_report_ran("drama", ts)  # 先占位，防止并发重入（并持久化）
        logger.info(f"[暮黎资源] ⏰ 短剧日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        try:
            mx = int(config.get("drama_report_max", 12) or 12)
        except (TypeError, ValueError):
            mx = 12
        try:
            timeout = int(config.get("drama_timeout", 15) or 15)
        except (TypeError, ValueError):
            timeout = 15
        result = await asyncio.to_thread(fetch_latest_dramas, mx, True, timeout)
        if not result.get("success"):
            logger.warning(f"[短剧日报] 抓取失败: {result.get('error','')}（不标记今日完成，兜底守护将重试）")
            return
        items = result.get("items", [])
        if not items:
            logger.info("[短剧日报] 今日暂无更新，标记今日已完成")
            self._mark_report_ran("drama", ts); return
        # 缓存 zip 供面板回看
        try:
            date_label = datetime.date.today().strftime("%Y年%m月%d日")
            html = build_drama_html(items, date_label)
            zp = await asyncio.to_thread(gen_drama_report_zip, items, html, ts)
            if zp:
                import shutil
                shutil.copy2(zp, self._drama_cached_path(ts))
                self._sw_cleanup_reports()
        except Exception as e:
            logger.warning(f"[短剧日报] 缓存 zip 失败: {e}")
        sent = await self._drama_build_and_send(items, ts, gids=gs_list)
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._mark_report_ran("drama", ts)
            logger.info(f"[短剧日报] 今日推送完成（{sent} 群）")
        else:
            logger.error("[短剧日报] 抓取成功但发送 0 群，兜底守护将重试")
        self._schedule_drama_next()

    async def _sw_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        # 防重锁：cron 与兜底守护可能在同一时刻同时触发，避免重复发送
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._last_run_date == ts:
                logger.info(f"[暮黎资源] 软件日报今日({ts})已运行过，跳过")
                return
            config = self._get_config()
            gids = await self._resolve_report_groups("group_ids")
            if not gids:
                logger.warning("[暮黎资源] 软件日报未能获取目标群（留空=全部群），等待兜底重试")
                return
            self._mark_report_ran("sw", ts)  # 先占位，防止并发重入（并持久化）
        logger.info(f"[暮黎资源] ⏰ 软件日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        mx = 24  # max_softwares 配置已移除，固定默认 24
        result = await asyncio.to_thread(sync_scrape, mx)
        if not result["success"]:
            logger.warning(f"[软件日报] 抓取失败: {result.get('error','')}（不标记今日完成，兜底守护将重试）")
            return
        sws = result.get("softwares",[])
        if not sws:
            logger.info("[软件日报] 今日暂无更新，标记今日已完成")
            self._mark_report_ran("sw", ts); return
        # 橙色夏日风格：HTML → 图片（替代旧的 Pillow 手绘）
        img_bytes = await self._sw_render_image(sws)
        zp = await asyncio.to_thread(gen_report_zip, sws, io.BytesIO(img_bytes) if img_bytes else None)
        # 文字版兜底内容（图片渲染失败或图片上传失败时使用）
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        text = (f"📦 暮黎软件日报 {date_label}\n今日共 {len(sws)} 款更新：\n"
                + "\n".join(f"{i}. {s.get('name','')} - {(s.get('desc','') or '')[:40]}"
                            for i, s in enumerate(sws, 1)))
        # 仅发送图片/文字，不再向群发送自包含 zip 文件
        sent = await self._sw_send_report(img_bytes, None, text, gids=gids)
        # 缓存 zip 仅供面板本地回看（不会发送给用户/群）
        if zp:
            try:
                import shutil
                shutil.copy2(zp, self._sw_cached_path(ts))
                self._sw_cleanup_reports()
            except: pass
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._mark_report_ran("sw", ts)
            logger.info(f"[软件日报] 今日推送完成（{sent} 群）")
        else:
            logger.error("[软件日报] 抓取成功但发送 0 群，兜底守护将重试")

    def _resolve_report_platform(self) -> str:
        """解析日报推送应使用的平台 ID（unified_msg_origin 的平台前缀）。

        历史 bug：原先取「第一个非 webchat 平台」，若 AstrBot 同时挂了
        飞书(Lark) 且排在 QQ 之前，会把 group_ids 里的 QQ 群号当作飞书
        receive_id 推送，导致 [Lark] 发送失败(invalid receive_id)。

        修复策略：优先选择 QQ 类平台（cqhttp/onebot/qq），其次才回退到
        任意非 webchat 平台；亦可通过配置 report_platform 显式指定。
        """
        try:
            config = self._get_config()
            explicit = (config.get("report_platform", "") or "").strip() if isinstance(config, dict) else ""
            if explicit:
                return explicit
        except Exception:
            pass
        try:
            for p in self.context.platform_manager.get_insts():
                pid = p.meta().id.lower()
                if "webchat" in pid:
                    continue
                if any(k in pid for k in ("cqhttp", "onebot", "qq")):
                    return p.meta().id
            for p in self.context.platform_manager.get_insts():
                pid = p.meta().id.lower()
                if "webchat" in pid:
                    continue
                return p.meta().id
        except Exception:
            pass
        return "aiocqhttp"

    @staticmethod
    def _image_size(img_bytes: bytes):
        """读取图片像素尺寸；失败返回 None。"""
        try:
            from PIL import Image
            with Image.open(io.BytesIO(img_bytes)) as im:
                return im.size
        except Exception:
            return None

    async def _finalize_report_image(self, img_bytes: bytes | None,
                                     tag: str = "日报") -> bytes | None:
        """日报出图后的统一后处理：裁掉底部与页面底色一致的空白（自适应）。

        无论图片来自本地 Playwright、AstrBot 内置 T2I 还是 Pillow 兜底，
        都在这里过一遍，避免「固定视口渲染器」在内容不足一屏时留下大片底色。
        """
        if not img_bytes or not trim_uniform_bottom:
            return img_bytes
        before = self._image_size(img_bytes)
        try:
            out = await asyncio.to_thread(trim_uniform_bottom, img_bytes)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{tag}] 底部留白裁剪失败(忽略): {e!r}")
            return img_bytes
        after = self._image_size(out)
        if before and after:
            pct = 100 * (before[1] - after[1]) // max(before[1], 1)
            logger.info(f"[{tag}] 出图尺寸 {before[0]}x{before[1]} → {after[0]}x{after[1]}"
                        + (f"（裁掉底部留白 {pct}%）" if after != before else "（无留白）"))
        return out

    async def _try_send_group_file(self, umo: str, img_bytes: bytes | None, file_name: str, text: str, label: str) -> bool:
        """以「文件」形式发送日报图片（绕开 onebot 发图体积上限，杜绝大图被平台静默拒收）。

        与小说 _upload_zip 一致，走 client.call_action(upload_group_file, base64://..., name=...)。
        群文件发送失败 → 降级文字版兜底；无图片则直接发文字版。
        """
        img_bytes = await self._finalize_report_image(img_bytes, label)
        gid = umo.split(":")[-1]
        if img_bytes:
            client = self._get_best_client()
            if client:
                try:
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    await client.call_action(action="upload_group_file", group_id=int(gid),
                                             file=f"base64://{b64}", name=file_name)
                    await asyncio.sleep(0.5)
                    logger.info(f"[暮黎资源] {label} 已以文件形式发送到 {umo}（{file_name}, {len(img_bytes)//1024}KB）")
                    return True
                except Exception as e:  # noqa: BLE001
                    logger.error(f"[暮黎资源] {label} 群文件发送失败: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
            else:
                logger.error(f"[暮黎资源] {label} 未找到可用客户端，无法以文件形式发送")
            # 文件发送失败 → 降级文字版
            if text:
                try:
                    await self.context.send_message(umo, MessageChain([Plain(text)]))
                    await asyncio.sleep(0.3)
                    logger.warning(f"[暮黎资源] {label} 文件发送失败，已回退文字版到 {umo}")
                    return True
                except Exception as e:  # noqa: BLE001
                    logger.error(f"[暮黎资源] {label} 文字回退发送到 {umo} 失败: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
            return False
        # 无图片：直接发文字版
        if text:
            try:
                await self.context.send_message(umo, MessageChain([Plain(text)]))
                await asyncio.sleep(0.3)
                logger.info(f"[暮黎资源] {label} 文字版已发送到 {umo}")
                return True
            except Exception as e:  # noqa: BLE001
                logger.error(f"[暮黎资源] {label} 文字发送到 {umo} 失败: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
                return False
        logger.error(f"[暮黎资源] {label} 既无图片也无文字内容，无法发送到 {umo}")
        return False

    async def _send_event_file(self, event, img_bytes: bytes | None, file_name: str, text: str, label: str) -> bool:
        """手动指令：把日报图以「文件」形式发到当前会话（与定时日报一致，绕开发图体积上限）。

        群内且 OneBot(aiocqhttp) → upload_group_file；
        其余平台先尝试 FileComponent 文件发送，不支持文件的平台（企微/QQ官方/TG 等）
        自动降级为「当前会话直接发图片」，再不行才用 text 兜底。
        """
        img_bytes = await self._finalize_report_image(img_bytes, label)
        if not img_bytes:
            if text:
                await event.send(MessageChain([Plain(text)]))
            return bool(text)
        gid = event.get_group_id()
        client = self._get_best_client(event)
        # ① 群内 + OneBot(aiocqhttp) → 上传群文件
        if gid and client:
            try:
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                await client.call_action(action="upload_group_file", group_id=int(gid),
                                         file=f"base64://{b64}", name=file_name)
                await asyncio.sleep(0.4)
                logger.info(f"[暮黎资源] {label} 手动指令已以文件形式发送到群 {gid}（{file_name}）")
                return True
            except Exception as e:  # noqa: BLE001
                logger.error(f"[暮黎资源] {label} 手动指令群文件发送失败: {type(e).__name__}: {e!r}")
        # 写临时文件（文件发送 / 图片发送共用）
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=_img_ext(img_bytes), prefix="report_"); os.close(fd)
            with open(tmp, "wb") as f:
                f.write(img_bytes)
            # ② 尝试按文件发送（FileComponent）
            try:
                await self.context.send_message(
                    f"{event.get_platform_id()}:FriendMessage:{event.get_sender_id()}",
                    MessageChain([FileComponent(file=tmp, name=file_name)]))
                logger.info(f"[暮黎资源] {label} 手动指令已以文件形式发送（FileComponent, {file_name}）")
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[暮黎资源] {label} FileComponent 发送失败，降级为图片发送: {type(e).__name__}: {e!r}")
            # ③ 不支持文件的平台（企微/QQ官方/TG 等）→ 当前会话直接发图片
            try:
                await event.send(MessageChain([ImageComponent(file=tmp)]))
                logger.info(f"[暮黎资源] {label} 已降级为当前会话发图片（{file_name}）")
                return True
            except Exception as e:  # noqa: BLE001
                logger.error(f"[暮黎资源] {label} 图片发送也失败: {type(e).__name__}: {e!r}")
            # ④ 最后文字兜底
            if text:
                await event.send(MessageChain([Plain(text)]))
            return bool(text)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[暮黎资源] {label} 手动指令发送异常: {type(e).__name__}: {e!r}")
            if text:
                await event.send(MessageChain([Plain(text)]))
            return bool(text)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    # ==================== 长列表图片卡片（小说 / 网盘资源）====================
    # 列表条目多时纯文本刷屏、扫读费劲，这里把整页列表渲染成一张图。
    # 图片只负责「好看好读」，回复数字选条目 / 翻页指令的交互完全不变。

    def _list_card_cfg(self):
        """读取列表卡片配置：(是否启用, 触发条数阈值)。"""
        c = self._get_config()
        enabled = c.get("list_card_enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ("", "0", "false", "no", "off")
        try:
            threshold = int(c.get("list_card_threshold", 5) or 5)
        except (TypeError, ValueError):
            threshold = 5
        return bool(enabled), max(1, threshold)

    async def _send_card_image(self, event: AstrMessageEvent, img_bytes: bytes,
                               name: str = "", want_mid: bool = False) -> bool:
        """把卡片图片发到当前会话，失败返回 False。

        want_mid=True 时优先走 OneBot 原生发送并记录 message_id，供「引用本条
        消息」时精确识别断点；拿不到 message_id 会回退普通 event.send。
        """
        if not img_bytes:
            return False
        if len(img_bytes) > 3 * 1024 * 1024 and hasattr(self, "_compress_game_image"):
            try:
                img_bytes = await asyncio.to_thread(self._compress_game_image, img_bytes)
            except Exception:
                pass
        if want_mid:
            mid = await self._send_image_raw(event, img_bytes)
            if mid:
                try:
                    event.set_extra("_muliy_last_card_mid", str(mid))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    event._has_send_oper = True
                except Exception:  # noqa: BLE001
                    pass
                return True
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=_img_ext(img_bytes), prefix="listcard_")
            os.close(fd)
            with open(tmp, "wb") as f:
                f.write(img_bytes)
            await event.send(MessageChain([ImageComponent(file=tmp)]))
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[列表卡片] 图片发送失败，回退文本: {type(e).__name__}: {e!r}")
            return False
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    async def _send_image_raw(self, event: AstrMessageEvent,
                              img_bytes: bytes) -> str:
        """经 OneBot 原生发图并返回 message_id；非 aiocqhttp 平台返回空串。"""
        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "call_action"):
            return ""
        try:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            payload = [{"type": "image", "data": {"file": f"base64://{b64}"}}]
            kw = {}
            sid = str(event.get_self_id() or "")
            if sid.isdigit():
                kw["self_id"] = int(sid)
            gid = event.get_group_id()
            if gid:
                ret = await bot.call_action(
                    action="send_group_msg", group_id=int(gid),
                    message=payload, **kw)
            else:
                ret = await bot.call_action(
                    action="send_private_msg",
                    user_id=int(event.get_sender_id()), message=payload, **kw)
            if isinstance(ret, dict):
                mid = ret.get("message_id")
                if mid is None and isinstance(ret.get("data"), dict):
                    mid = ret["data"].get("message_id")
                if mid is not None:
                    return str(mid)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[列表卡片] 原生发图未取到 message_id，回退 event.send: {e}")
        return ""

    async def _send_list_card(self, event: AstrMessageEvent, *, html: str, text: str,
                              total: int, label: str = "列表",
                              force: bool = False, hint: str = "") -> bool:
        """超长列表优先发图片卡片；未启用 / 条目不多 / 渲染失败时发文本。

        触发条件：条目数超过阈值，**或**文本已经很长（长标题 4~5 条就够刷屏）。
        force=True 时忽略条目数阈值（选集卡片即使只有 2 集也出图）。
        hint 会渲染到底部（图片模式）或文本末尾（文本模式），用于引用断点。
        返回是否成功发了图片。无论走哪条路都只发一条消息。
        """
        body = text + (f"\n{hint}" if hint else "")
        enabled, threshold = self._list_card_cfg()
        long_text = len(text) > 400   # 纯文本超过约 400 字，即使条目少也出图
        if (not enabled or not html or render_list_card is None
                or (not force and total <= threshold and not long_text)):
            await event.send(MessageChain([Plain(body)]))
            return False
        img = None
        try:
            page_html = self._inject_card_hint(html, hint)
            img = await asyncio.to_thread(render_list_card, page_html)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[列表卡片] {label} 渲染异常，回退文本: {e}")
        if not img:
            await event.send(MessageChain([Plain(body)]))
            return False
        try:
            event.set_extra("_muliy_last_card_mid", "")
        except Exception:  # noqa: BLE001
            pass
        if await self._send_card_image(event, img, f"暮黎_{label}.jpg",
                                       want_mid=True):
            logger.info(f"[列表卡片] {label} 已发图片（{total} 条，{len(img) // 1024}KB）")
            return True
        await event.send(MessageChain([Plain(body)]))
        return False

    @staticmethod
    def _inject_card_hint(html: str, hint: str) -> str:
        """把断点提示渲染进卡片底部，避免在聊天里多发一条文字。"""
        hint = (hint or "").strip()
        if not html or not hint:
            return html
        line = ('<div style="margin-top:12px;padding:0 18px;font-size:14px;'
                'color:#9a9a9a;line-height:1.65">'
                + escape(hint) + '</div>')
        needle = "\n  </div>\n</div>\n</body></html>"
        if needle in html:
            return html.replace(needle, "\n" + line + needle, 1)
        return html.replace("</body>", line + "</body>", 1)

    async def _send_search_page(self, event: AstrMessageEvent, kind: str, text: str,
                                ses: dict | None = None, *,
                                results: list | None = None, keyword: str = "",
                                page: int = 0, page_size: int = 8,
                                note: str = "") -> None:
        """游戏 / 软件 / 影视 / 短剧搜索列表：统一走长列表图片卡片。"""
        ses = ses or {}
        total = (len(results) if results is not None
                 else len(ses.get("results") or []))
        html = ""
        covers: dict = {}
        try:
            # 只给当前页预取封面，避免一次性下载几十张图拖慢响应
            enabled, threshold = self._list_card_cfg()
            if (enabled and render_list_card is not None
                    and (total > threshold or len(text) > 400)):
                all_results = (results if results is not None
                               else (ses.get("results") or []))
                p = page if results is not None else ses.get("page", 0)
                ps = page_size if results is not None else ses.get("page_size", 8)
                ps = max(1, int(ps or 8))
                st = max(0, int(p or 0)) * ps
                page_items = all_results[st:st + ps]
                if kind == "game":
                    referer = ("https://www.switch618.com/"
                               if self._game_source() == "switch618"
                               else GAME_BASE_URL + "/")
                else:
                    referer = {"movie": MV_BASE_URL + "/"}.get(kind, "")
                covers = (await self._prefetch_covers(page_items, referer=referer)
                          if kind in ("movie", "movie_new", "game") else {})

            if kind == "game" and game_card_html:
                html = game_card_html(ses, note=note, covers=covers)
            elif kind == "software" and software_card_html:
                html = software_card_html(ses, note=note, covers=covers)
            elif kind == "movie" and movie_card_html:
                html = movie_card_html(ses, note=note, covers=covers)
            elif kind == "movie_new" and movie_new_card_html:
                html = movie_new_card_html(results or [], keyword, page, page_size,
                                           note=note, covers=covers)
            elif kind == "drama" and drama_card_html:
                html = drama_card_html(ses, note=note, covers=covers)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[列表卡片] {kind} 卡片构建失败，回退文本: {e}")
        label = {"game": "游戏列表", "software": "软件列表", "movie": "影视列表",
                 "movie_new": "影视列表", "drama": "短剧列表"}.get(kind, "列表")
        kw = str(keyword or (ses or {}).get("keyword") or "").strip()
        page_now = int(page or (ses or {}).get("page", 0) or 0)
        hint = f"💡 引用本条消息可继续选择 · {kw or label} · 第{page_now + 1}页"
        await self._send_list_card(event, html=html, text=text, total=total,
                                   label=label, hint=hint)
        # 断点：引用搜索结果列表可直接继续选序号（无需重新搜索）
        mid = str(event.get_extra("_muliy_last_card_mid", "") or "")
        mgr = {
            "game": ("game", self._sessions),
            "software": ("software", self._search_sessions),
            "movie": ("movie_old", self._movie_sessions),
            "movie_new": ("movie", self._movie_sessions_new),
            "drama": ("drama", self._drama_sessions),
        }.get(kind)
        if mgr:
            mgr_name, manager = mgr
            state = manager.get(event)
            if state:
                try:
                    snap = copy.deepcopy(state)
                except Exception:  # noqa: BLE001
                    snap = dict(state)
                self._register_breakpoint(event, mgr_name, snap, [hint, text],
                                          mid=mid)

    # ——— 网盘资源过期判断（本地概率 + 选中时真实校验） ———

    def _pan_expiry_hint_enabled(self) -> bool:
        cfg = self._get_config()
        return bool(cfg.get("pan_expiry_hint", True)) if isinstance(cfg, dict) else True

    def _pan_link_check_enabled(self) -> bool:
        cfg = self._get_config()
        return bool(cfg.get("pan_link_check", True)) if isinstance(cfg, dict) else True

    def _pan_reports_store(self) -> PanReportStore:
        if self._pan_reports is None:
            self._pan_reports = PanReportStore(
                os.path.join(self._plugin_data_dir(), "pan_reports.json"))
        return self._pan_reports

    def _annotate_pan_resources(self, panlist, sort: bool = True,
                                force: bool = False) -> list:
        """给网盘资源列表打过期概率标签；关闭该功能时原样返回。

        sort=True 会把「过期概率」低的排前面、高危置底。
        注意：只有写入会话的列表才能排序，展示兜底必须 sort=False，
        否则列表顺序会和用户回复的序号对不上。
        force=True 强制重算（失效反馈更新后需要重新评分）。
        """
        if not panlist or not self._pan_expiry_hint_enabled():
            return list(panlist or [])
        try:
            return annotate_panlist(panlist, self._pan_reports_store().items,
                                    sort=sort, force=force)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源·网盘] 过期概率评估失败(已忽略): {e}")
            return list(panlist or [])

    @staticmethod
    def _pan_risk_text(pan: dict) -> str:
        h = pan.get("_health") if isinstance(pan.get("_health"), dict) else {}
        if not h:
            return ""
        return f"{h.get('emoji', '')}{h.get('label', '')} · 过期概率约 {h.get('score', '?')}%"

    async def _check_selected_pan(self, pan: dict) -> str:
        """选中网盘时做一次真实链接校验，返回 ok / dead / unknown。"""
        url = (pan or {}).get("url") or ""
        if not url or not self._pan_link_check_enabled():
            return "unknown"
        try:
            return await asyncio.to_thread(check_pan_link, url, pan.get("type", ""))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[暮黎资源·网盘] 链接校验异常(按未知处理): {e}")
            return "unknown"

    def _pan_scan_enabled(self) -> bool:
        cfg = self._get_config()
        return bool(cfg.get("pan_link_scan", True)) if isinstance(cfg, dict) else True

    async def _scan_pan_links(self, pans, cap: int = 60):
        """并发检测一批网盘链接，返回 (alive, dead, checked, unknown)。

        - alive：正常 + 无法判断的条目（保持原对象，避免丢标签）；
        - dead：确认失效的条目（带 🔴已失效 标签）；
        - checked：拿到明确结果（ok/dead）的数量。
        """
        pans = list(pans or [])
        targets = [p for p in pans
                   if (p.get("url") or "").startswith(("http://", "https://"))][:cap]
        if not targets:
            return pans, [], 0, 0
        try:
            result = await asyncio.to_thread(check_many, targets, 8, 5, 25)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源·网盘] 批量检测失败(已忽略): {e}")
            return pans, [], 0, 0

        alive, dead = [], []
        checked = unknown = 0
        for p in pans:
            u = p.get("url") or ""
            st = result.get(u)
            if st == "dead":
                checked += 1
                dead.append(p)
            elif st == "unknown":
                unknown += 1
                alive.append(p)
            else:
                if st == "ok":
                    checked += 1
                alive.append(p)

        dead_items = []
        if dead:
            rep = self._pan_reports_store()
            try:
                counts = rep.add_many([p.get("url") or "" for p in dead])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[暮黎资源·网盘] 失效反馈保存失败(已忽略): {e}")
                counts = {}
            for p in dead:
                u = p.get("url") or ""
                q = dict(p)
                q["_health"] = {
                    "score": 100, "level": "high", "emoji": "🔴",
                    "label": "已失效", "age_days": None, "lifetime": None,
                    "reports": int(counts.get(u) or 1),
                    "detail": "链接已确认失效",
                }
                q["_dead"] = True
                dead_items.append(q)
        return alive, dead_items, checked, unknown

    async def _scan_pan_type(self, event: AstrMessageEvent, ses: dict,
                             sel_type: str, tag: str) -> tuple:
        """选定网盘分类后遍历检测该类全部链接，过滤失效项。

        返回 (最终使用的网盘类型, 更新后的完整网盘列表)；
        该类型全部失效时返回 ("", 列表) 并让用户重新选分类。
        """
        resources = dict(ses.get("resources") or {})
        all_pan = list(resources.get("panlist") or [])
        targets = [p for p in all_pan if p.get("type", "") == sel_type]
        if not targets:
            return sel_type, all_pan

        await event.send(MessageChain([Plain(
            f"{tag} ⏳ 正在检测「{sel_type}」的 {len(targets)} 个链接有效性，请稍候…")]))
        alive, dead, checked, unknown = await self._scan_pan_links(targets)

        others = [p for p in all_pan if p.get("type", "") != sel_type]
        resources["panlist"] = self._annotate_pan_resources(alive + others)
        if dead:
            resources["pan_dead"] = list(resources.get("pan_dead") or []) + dead
        ses["resources"] = resources

        if dead:
            tip = f"🧹 已检测 {checked} 个链接，过滤 {len(dead)} 个失效资源。"
            if unknown:
                tip += f"\n（另有 {unknown} 个暂时无法确认，已保留）"
            await event.send(MessageChain([Plain(f"{tag} {tip}")]))
        elif unknown:
            await event.send(MessageChain([Plain(
                f"{tag} ⚠️ {unknown} 个链接暂时无法确认有效性（已保留），可点开后自行判断。")]))

        if alive:
            self._movie_sessions_new.update(
                event, resources=resources, stage="select_pan",
                selected_pan_type=sel_type, page=0, _llm_handled=True)
            return sel_type, resources["panlist"]

        # 该类型全部失效：退回分类选择（按剩余资源重新统计）
        remaining = group_panlist_by_type(resources["panlist"])
        if remaining:
            self._movie_sessions_new.update(
                event, resources=resources, stage="select_pan_type",
                pan_type_counts=remaining, page=0, _llm_handled=True)
            await self._send_movie_pan_types(
                event, ses, tag,
                note=f"⚠️「{sel_type}」检测到的资源均已失效，请换一个网盘类型：\n")
        else:
            self._movie_sessions_new.delete(event)
            await event.send(MessageChain([Plain(
                f"{tag} ❌ 该影视的所有网盘资源均检测为失效（已记录），"
                f"建议换个片源或稍后再试。")]))
        return "", resources["panlist"]

    async def _handle_dead_pan(self, event: AstrMessageEvent, ses: dict,
                               pan: dict, link: str) -> None:
        """确认网盘已失效：记录反馈 → 重新评分置底 → 推荐其他可用资源。"""
        tag = "【暮黎资源】"
        try:
            self._pan_reports_store().add(link)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[暮黎资源·网盘] 失效反馈保存失败(已忽略): {e}")
        try:
            resources = dict(ses.get("resources") or {})
            # 把刚确认失效的这条从列表移除，避免它继续占用序号
            kept = [p for p in (resources.get("panlist") or [])
                    if (p.get("url") or "") != link]
            if len(kept) != len(resources.get("panlist") or []):
                dead_item = dict(pan)
                dead_item["_dead"] = True
                dead_item["_health"] = {
                    "score": 100, "level": "high", "emoji": "🔴",
                    "label": "已失效", "age_days": None, "lifetime": None,
                    "reports": self._pan_reports_store().count(link),
                    "detail": "链接已确认失效",
                }
                resources["pan_dead"] = list(resources.get("pan_dead") or []) + [dead_item]
            resources["panlist"] = self._annotate_pan_resources(kept, force=True)
            ses["resources"] = resources
            sel_type = ses.get("selected_pan_type", "") or ""
            same_type = [p for p in resources["panlist"]
                         if p.get("type", "") == sel_type] if sel_type else list(resources["panlist"])
            alive = [p for p in same_type
                     if (p.get("_health") or {}).get("level") != "high"]
            if len(same_type) <= 1 or not alive:
                # 该网盘类型已无可用资源：退回全部网盘类型重新推荐
                sel_type = ""
            self._movie_sessions_new.update(
                event, resources=resources, page=0,
                stage="select_pan", selected_pan_type=sel_type, _llm_handled=True)
            await event.send(MessageChain([Plain(
                f"{tag} ❌ 该网盘链接已失效（分享已过期或被取消）。\n"
                f"💡 已记录并从列表移除，下面重新为你列出可用资源：")]))
            await self._send_pan_list_card(
                event, ses.get("detail", {}), resources["panlist"], 0, sel_type,
                prefix=tag + "\n")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[暮黎资源·网盘] 失效资源兜底处理失败: {e}")
            await event.send(MessageChain([Plain(
                f"{tag} 该网盘链接可能已失效，请回复「网盘资源」重新选择其他资源。")]))

    async def _send_novel_list(self, event: AstrMessageEvent, ses: dict | None,
                               card: str, text: str, total: int) -> None:
        """小说列表：发送并绑定引用断点（引用后可继续选书，不用重新搜索）。"""
        kw = str((ses or {}).get("keyword") or "小说").strip()
        page = int((ses or {}).get("page", 0) or 0)
        hint = f"💡 引用本条消息可继续选择 · {kw} · 小说列表 · 第{page + 1}页"
        await self._send_list_card(event, html=card, text=text, total=total,
                                   label="小说列表", hint=hint)
        mid = str(event.get_extra("_muliy_last_card_mid", "") or "")
        if ses:
            try:
                snap = copy.deepcopy(ses)
            except Exception:  # noqa: BLE001
                snap = dict(ses)
            snap["stage"] = "select_novel"
            snap["page"] = page
            self._register_breakpoint(event, "novel", snap, [hint, text], mid=mid)

    async def _send_movie_pan_types(self, event: AstrMessageEvent, ses: dict,
                                    tag: str = "", note: str = "") -> None:
        """发送网盘分类列表，并绑定引用断点。"""
        panlist = (ses.get("resources") or {}).get("panlist") or []
        tc = group_panlist_by_type(panlist)
        text = format_pan_types(tc)
        title = str((ses.get("detail") or {}).get("name") or "").strip() or "影视"
        hint = f"💡 引用本条消息可换网盘类型 · {title}"
        await event.send(MessageChain([Plain(
            (tag or "") + "\n" + (note or "") + text + (f"\n{hint}" if hint else ""))]))
        try:
            snap = copy.deepcopy(ses)
        except Exception:  # noqa: BLE001
            snap = dict(ses)
        snap["stage"] = "select_pan_type"
        snap["pan_type_counts"] = tc
        snap["page"] = 0
        self._register_breakpoint(event, "movie", snap, [hint, text])

    async def _send_movie_nodes(self, event: AstrMessageEvent, ses: dict,
                                tag: str = "") -> None:
        """发送播放节点列表，并绑定引用断点。"""
        playlist = (ses.get("resources") or {}).get("playlist") or []
        text = format_play_nodes(playlist)
        title = str((ses.get("detail") or {}).get("name") or "").strip() or "影视"
        hint = f"💡 引用本条消息可换播放节点 · {title}"
        await event.send(MessageChain([Plain(
            (tag or "") + ("\n" if tag else "") + text
            + (f"\n{hint}" if hint else ""))]))
        try:
            snap = copy.deepcopy(ses)
        except Exception:  # noqa: BLE001
            snap = dict(ses)
        snap["stage"] = "select_play_node"
        snap["page"] = 0
        self._register_breakpoint(event, "movie", snap, [hint, text])

    async def _send_pan_list_card(self, event: AstrMessageEvent, detail: dict,
                                  panlist: list, page: int = 0,
                                  type_filter: str = "", prefix: str = "") -> bool:
        """网盘资源列表：整页渲染成图片（分页口径与 format_pan_list 一致）。"""
        panlist = panlist or []
        if panlist and not all(isinstance(p.get("_health"), dict) for p in panlist):
            # 兜底：会话里的列表理论上已打过标；这里只补标签、不改顺序
            panlist = self._annotate_pan_resources(panlist, sort=False)
        filtered = ([p for p in panlist if p.get("type", "") == type_filter]
                    if type_filter else panlist)
        text = prefix + format_pan_list(panlist, page, type_filter=type_filter)
        html = ""
        if pan_card_html:
            try:
                html = pan_card_html(
                    panlist, page=page, page_size=12, type_filter=type_filter,
                    title=(detail or {}).get("name", ""),
                    year=str((detail or {}).get("year", "") or ""),
                    timeout=120)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 网盘卡片构建失败，回退文本: {e}")
        title = str((detail or {}).get("name") or "").strip() or "影视"
        pages = max(1, (len(filtered) + 11) // 12)
        page_now = max(0, min(int(page or 0), pages - 1))
        hint = (f"💡 引用本条消息可换资源 · {title} · "
                f"{type_filter or '全部网盘'} · 第{page_now + 1}/{pages}页")
        sent = await self._send_list_card(event, html=html, text=text,
                                          total=len(filtered), label="网盘列表",
                                          hint=hint)
        # 断点：引用这条消息回复序号，可从当前网盘列表继续换资源
        mid = str(event.get_extra("_muliy_last_card_mid", "") or "")
        ses = self._movie_sessions_new.get(event)
        if ses:
            try:
                snap = copy.deepcopy(ses)
            except Exception:  # noqa: BLE001
                snap = dict(ses)
            snap["stage"] = "select_pan"
            snap["page"] = page_now
            snap["selected_pan_type"] = type_filter
            self._register_breakpoint(event, "movie", snap, [hint, text], mid=mid)
        return sent

    async def _send_episode_card(self, event: AstrMessageEvent, detail: dict,
                                 node: dict, page: int = 0,
                                 prefix: str = "") -> bool:
        """在线播放选集：整页集数渲染成图片（剧集只显示数字，综艺显示集名）。"""
        eps = node_episodes(node)
        text = prefix + format_episode_list(detail, node, page)
        html = ""
        if episode_card_html:
            try:
                html = episode_card_html(detail, node, page=page, timeout=120)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[列表卡片] 选集卡片构建失败，回退文本: {e}")
        title = str((detail or {}).get("name") or "").strip() or "影视"
        node_t = str((node or {}).get("t") or "").strip()
        size = episode_page_size(eps)
        pages = episode_pages(len(eps), size)
        page_now = normalize_ep_page(page, len(eps), size)
        hint = (f"💡 引用本条消息可换集 · {title}"
                + (f" · {node_t}" if node_t else "")
                + f" · 第{page_now + 1}/{pages}页")
        sent = await self._send_list_card(event, html=html, text=text,
                                          total=len(eps), label="选集列表",
                                          force=True, hint=hint)
        # 断点：引用选集消息回复集数，可直接换一集
        mid = str(event.get_extra("_muliy_last_card_mid", "") or "")
        ses = self._movie_sessions_new.get(event)
        if ses:
            try:
                snap = copy.deepcopy(ses)
            except Exception:  # noqa: BLE001
                snap = dict(ses)
            snap["stage"] = "select_episode_new"
            snap["ep_page"] = page_now
            snap["selected_node"] = node
            self._register_breakpoint(event, "movie", snap, [hint, text], mid=mid)
        return sent

    async def _sw_send_report(self, img_bytes, zp, text: str = "", gids=None):
        if gids is None:
            gids = await self._resolve_report_groups("group_ids")
        if not gids: return 0
        ts = datetime.date.today().strftime("%Y%m%d")
        apid = self._resolve_report_platform()
        logger.info(f"[暮黎资源] 软件日报推送目标平台: {apid} | 目标群: {gids}")
        fn = f"暮黎软件日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        sent = 0
        for gid in gids:
            umo = f"{apid}:GroupMessage:{gid}"
            # 以文件形式发送（zp 仅用于本地缓存回看，不发送）
            if await self._try_send_group_file(umo, img_bytes, fn, text, "软件日报"):
                sent += 1
        logger.info(f"[暮黎资源] 软件日报本次成功推送 {sent}/{len(gids)} 个群")
        return sent

    async def _send_file_to_chat(self, path: str, name: str, event=None,
                                 gid=None, uid=None,
                                 label: str = "文件") -> tuple[bool, str]:
        """把本地文件发到当前会话，返回 (是否成功, 失败原因)。

        发送顺序：
          ① OneBot upload_group_file / upload_private_file（base64 内嵌，
             规避「napcat 读不到 AstrBot 容器内 /tmp」的 ENOENT）；
          ② AstrBot FileComponent（机器人与客户端同机/共享挂载时可用）。

        旧实现对异常 `except: pass`，所有失败都被统一报成
        「OneBot 客户端不可达」，用户无法排查；这里把真实原因记日志并回传。
        """
        if not path or not os.path.exists(path):
            return False, "临时文件已丢失，请重试"
        size = os.path.getsize(path)
        gg = gid or (event.get_group_id() if event else None)
        uu = uid or (event.get_sender_id() if event else None)
        pid = (event.get_platform_id() or "") if event else ""
        errors: list[str] = []

        client = self._get_best_client(event)
        if client and size <= 40 * 1024 * 1024:
            try:
                if event and size > 8 * 1024 * 1024:
                    await event.send(MessageChain([Plain(
                        f"📤 正在上传 {label}（{_format_size(size)}），大文件请稍候…")]))
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                if gg:
                    await client.call_action(action="upload_group_file", group_id=int(gg),
                                             file=f"base64://{b64}", name=name)
                    return True, ""
                if uu and str(uu).isdigit():
                    await client.call_action(action="upload_private_file", user_id=int(uu),
                                             file=f"base64://{b64}", name=name)
                    return True, ""
            except Exception as e:  # noqa: BLE001
                errors.append(f"OneBot 直传失败（{type(e).__name__}）")
                logger.warning(f"[暮黎资源] {label} OneBot 直传失败: "
                               f"{type(e).__name__}: {e!r}")
        elif client:
            errors.append(f"文件较大（{_format_size(size)}），跳过 base64 直传")

        # ② AstrBot 文件组件兜底
        targets = []
        if event is not None:
            targets.append(("event", ""))
        if pid and uu:
            targets.append(("context", f"{pid}:FriendMessage:{uu}"))
        if pid and gg:
            targets.append(("context", f"{pid}:GroupMessage:{gg}"))
        for kind, umo in targets:
            try:
                chain = MessageChain([FileComponent(file=path, name=name)])
                if kind == "event":
                    await event.send(chain)
                else:
                    await self.context.send_message(umo, chain)
                return True, ""
            except Exception as e:  # noqa: BLE001
                errors.append(f"文件组件发送失败（{type(e).__name__}）")
                logger.warning(f"[暮黎资源] {label} 文件组件发送失败({kind}): "
                               f"{type(e).__name__}: {e!r}")
        # 去重保序，避免提示里重复同一句
        reason = "；".join(dict.fromkeys(errors))
        return False, reason or "当前平台不支持文件发送"

    async def _upload_zip(self, zp, zn, event=None, gid=None, uid=None):
        """兼容旧调用：只关心成功/失败。"""
        ok, _reason = await self._send_file_to_chat(
            zp, zn, event=event, gid=gid, uid=uid, label="文件")
        return ok

    # ==================== 游戏日报（XDGAME） ====================
    def _game_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir, f"game_report_{ds}.zip") if self._reports_dir else ""

    async def _game_send_report(self, img_bytes, ts, text: str = "", gids=None):
        logger.info(f"[游戏日报] 进入发送阶段：图片={'有 %dKB' % (len(img_bytes)//1024) if img_bytes else '无'} | 文字版={'有 %d字' % len(text) if text else '无'}")
        if gids is None:
            gids = await self._resolve_report_groups("game_group_ids")
        logger.info(f"[游戏日报] 解析到的目标群: {gids}")
        if not gids: return 0
        apid = self._resolve_report_platform()
        logger.info(f"[暮黎资源] 游戏日报推送目标平台: {apid} | 目标群: {gids}")
        fn = f"暮黎游戏日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        sent = 0
        for gid in gids:
            umo = f"{apid}:GroupMessage:{gid}"
            if await self._try_send_group_file(umo, img_bytes, fn, text, "游戏日报"):
                sent += 1
        logger.info(f"[暮黎资源] 游戏日报本次成功推送 {sent}/{len(gids)} 个群")
        return sent

    async def _game_build_and_send(self, games: list, ts: str, gids=None):
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        src_label = "switch618" if self._game_source() == "switch618" else "XDGAME"
        html = build_cartoon_html(games, date_label, source_label=src_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        config = self._get_config()
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[游戏日报] 开始渲染，共 {len(games)} 款游戏，html 长度 {len(html)} 字符，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_html_to_png, html, font_path, 700, channel, exe)
            logger.info(f"[游戏日报] 渲染完成" + (f"，原始图片体积 {len(img_bytes)//1024}KB" if img_bytes else "，但未返回图片(将用兜底渲染)"))
        except Exception as e:
            logger.error(f"[游戏日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
        if not img_bytes:
            # ① AstrBot 内置 html_renderer（云端 T2I，无需本机浏览器）
            logger.info("[游戏日报] Playwright 不可用，尝试 AstrBot 内置渲染")
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            # ② Pillow 纯 Python 兜底（永远可用）
            logger.info("[游戏日报] 尝试 Pillow 兜底渲染")
            cards = []
            for g in games:
                chips = []
                if g.get("category"):
                    chips.append(str(g["category"]))
                if g.get("rank"):
                    chips.append("排行 " + str(g["rank"]))
                if g.get("size"):
                    chips.append(str(g["size"]))
                cards.append({
                    "cover": g.get("cover_b64") or "",
                    "title": g.get("title") or "未知",
                    "chips": chips,
                    "desc": (g.get("intro") or "暂无简介")[:200],
                })
            img_bytes = await self._report_pil_fallback(
                cards, date_label, src_label, font_path, 720, "游戏日报")
        # 体积过大（24 款×封面+截图常达数 MB）会被平台静默拒收，先压缩到安全上限
        if img_bytes and len(img_bytes) > 2 * 1024 * 1024:
            logger.info(f"[游戏日报] 原始图 {len(img_bytes)//1024}KB 超过 2MB，开始压缩...")
            img_bytes = self._compress_game_image(img_bytes)
            logger.info(f"[游戏日报] 压缩后体积 {len(img_bytes)//1024}KB")
        # 始终构建文字版，作为图片上传失败时的兜底（定时任务无 event 可用）
        text = (f"🎮 暮黎游戏日报 {date_label}\n今日共 {len(games)} 款新游戏：\n"
                + "\n".join(f"{i}. {g.get('title','')}（{g.get('category','')}）" for i, g in enumerate(games, 1)))
        if not img_bytes:
            logger.warning("[游戏日报] 图片渲染失败，将改用文字版推送")
        else:
            logger.info(f"[游戏日报] 准备发送，最终图片体积 {len(img_bytes)//1024}KB")
        return await self._game_send_report(img_bytes, ts, text, gids=gids)

    async def _game_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._game_last_run_date == ts:
                logger.info(f"[暮黎资源] 游戏日报今日({ts})已运行过，跳过")
                return
            config = self._get_config()
            if not (config.get("game_report_enabled", True) if isinstance(config, dict) else True):
                logger.warning("[暮黎资源] 游戏日报已触发，但 game_report_enabled 关闭，跳过")
                self._mark_report_ran("game", ts)
                return
            gs_list = await self._resolve_report_groups("game_group_ids")
            if not gs_list:
                logger.warning("[暮黎资源] 游戏日报未能获取目标群（留空=全部群），等待兜底重试")
                return
            self._mark_report_ran("game", ts)  # 先占位，防止并发重入（并持久化）
        logger.info(f"[暮黎资源] ⏰ 游戏日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        mx = int(config.get("game_report_max", 24) or 24)
        logger.info(f"[游戏日报] 本次抓取：数据源={self._game_source()} | 上限={mx} 款 | 目标群={gs_list}")
        if self._game_source() == "switch618":
            cookie = self._g_cookie()
            # switch618 源同样受 game_report_max 上限约束（不再抓全）
            result = await asyncio.to_thread(get_today_games_618, mx, cookie)
        else:
            cookie = (config.get("cookie", "") or "") if isinstance(config, dict) else ""
            result = await asyncio.to_thread(get_today_games, mx, cookie)
        if not result["success"]:
            logger.warning(f"[游戏日报] 抓取失败: {result.get('error','')}（不标记今日完成，兜底守护将重试）")
            return
        games = result.get("games", [])
        if not games:
            logger.info("[游戏日报] 今日暂无更新，标记今日已完成")
            self._mark_report_ran("game", ts); return
        sent = await self._game_build_and_send(games, ts, gids=gs_list)
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._mark_report_ran("game", ts)
            logger.info(f"[游戏日报] 今日推送完成（{sent} 群）")
        else:
            logger.error("[游戏日报] 抓取成功但发送 0 群，兜底守护将重试")

    @staticmethod
    def _compress_game_image(img_bytes: bytes, max_bytes: int = 2 * 1024 * 1024) -> bytes:
        """把渲染出的大图压缩到 ≤ max_bytes（先降质量再缩放），失败返回原图。

        日报整页图（24 款×封面+截图）常达数 MB，超过 QQ/onebot 发图体积上限，
        导致 event.send(Image) 被平台拒绝却只静默告警、群里收不到任何内容。
        """
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(img_bytes))
            out = img_bytes
            for q in (80, 70, 60, 50):
                buf = _io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=q, optimize=True)
                out = buf.getvalue()
                if len(out) <= max_bytes:
                    return out
            w, h = img.size
            scale = 0.9
            while len(out) > max_bytes and scale > 0.4:
                scale -= 0.1
                nw, nh = max(120, int(w * scale)), max(120, int(h * scale))
                buf = _io.BytesIO()
                img.resize((nw, nh), Image.LANCZOS).convert("RGB").save(
                    buf, format="JPEG", quality=55, optimize=True)
                out = buf.getvalue()
            return out
        except Exception as e:
            logger.warning(f"[游戏日报] 压缩图片失败: {e}")
            return img_bytes

    @filter.command("game_report")
    async def cmd_game_report(self, event: AstrMessageEvent):
        config = self._get_config()
        mx = int(config.get("game_report_max", 24) or 24)
        source = self._game_source()
        label = "switch618.com" if source == "switch618" else "XDGAME"
        # 先立即给出一条反馈，避免下方抓取（switch 源约 1~2 分钟，含大量封面/截图下载）期间无任何响应
        yield event.plain_result(f"⏳ 正在抓取 {label} 今日新游...")
        # 在子线程跑抓取。进度只写入 log.txt（get_today_games* 内部已用 logger.info 记录），
        # 不向群里刷屏；主协程等待完成，设总超时防止 worker 卡在图床时无限等待。
        state = {"done": False, "result": None, "err": None}
        def _worker():
            try:
                if source == "switch618":
                    cookie = self._g_cookie()
                    # 受 game_report_max 上限约束（不再抓全）；进度写入 log.txt
                    state["result"] = get_today_games_618(mx, cookie)
                else:
                    cookie = (config.get("cookie", "") or "") if isinstance(config, dict) else ""
                    state["result"] = get_today_games(mx, cookie)
            except Exception as e:
                state["err"] = str(e)
            state["done"] = True
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _worker)
        waited = 0
        while not state["done"] and waited < 600:
            await asyncio.sleep(2)
            waited += 2
        if not state["done"]:
            yield event.plain_result("⚠️ 抓取超时（超过 10 分钟，请检查网络/图床连通性，详见 log.txt）"); return
        if state["err"]:
            yield event.plain_result(f"⚠️ 抓取异常: {state['err'][:200]}"); return
        result = state["result"]
        if not result["success"]:
            yield event.plain_result(f"⚠️ {result.get('error','未知')}"); return
        games = result.get("games", [])
        if not games:
            yield event.plain_result("📭 今日暂无游戏更新。"); return
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        src_label = "switch618" if self._game_source() == "switch618" else "XDGAME"
        html = build_cartoon_html(games, date_label, source_label=src_label)
        font_path = os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        try:
            img_bytes = await asyncio.to_thread(render_html_to_png, html, font_path, 700, channel, exe)
        except Exception as e: logger.error(f"[游戏日报] 渲染异常: {e}")
        if not img_bytes:
            # ① AstrBot 内置 html_renderer（云端 T2I，无需本机浏览器）
            logger.info("[游戏日报] Playwright 不可用，尝试 AstrBot 内置渲染")
            img_bytes = await self._html_render_astrbot(html, 720)
        if not img_bytes:
            # ② Pillow 纯 Python 兜底（永远可用）
            logger.info("[游戏日报] 尝试 Pillow 兜底渲染")
            cards = []
            for g in games:
                chips = []
                if g.get("category"):
                    chips.append(str(g["category"]))
                if g.get("size"):
                    chips.append(str(g["size"]))
                cards.append({
                    "cover": g.get("cover_b64") or "",
                    "title": g.get("title") or "未知",
                    "chips": chips,
                    "desc": (g.get("intro") or "暂无简介")[:200],
                })
            img_bytes = await self._report_pil_fallback(
                cards, date_label, src_label, font_path, 720, "游戏日报")
        # 体积过大（如 24 款×封面+截图常达数 MB）会被平台拒收，先压缩到安全上限
        if img_bytes and len(img_bytes) > 2 * 1024 * 1024:
            logger.info(f"[游戏日报] 渲染图 {len(img_bytes)//1024}KB，超过 2MB，尝试压缩...")
            img_bytes = self._compress_game_image(img_bytes)
            logger.info(f"[游戏日报] 压缩后 {len(img_bytes)//1024}KB")
        img_path = None
        html_path = None
        ts = datetime.date.today().strftime("%Y%m%d")
        fn = f"暮黎游戏日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        text_fallback = ("⚠️ 日报图片渲染/发送失败，已降级为文字版：\n"
                         + "\n".join(f"{i}. {g.get('title','')}（{g.get('category','')}）" for i, g in enumerate(games, 1)))
        try:
            # 以文件形式发送（绕开发图体积上限）；失败则降级文字版
            await self._send_event_file(event, img_bytes, fn, text_fallback, "游戏日报")
        finally:
            for p in (img_path, html_path):
                if p and os.path.exists(p):
                    try: os.unlink(p)
                    except Exception: pass

    # ==================== 入群审核（QQ / aiocqhttp / OneBot v11） ====================
    #
    # 流程：新成员入群 notice → 群里 @ 他并发送「20-100 以内加减法」图形验证码 →
    #       限时内回复正确答案即通过；答错达上限或超时 → 移出群聊。
    # 注：QQ 被禁言的成员无法发送任何群消息，因此本功能「不禁言」，
    #     改为验证期间撤回该成员的非答案发言来防刷屏。

    def _raw_notice(self, event):
        """取出平台原始事件（OneBot 的 notice/request 等），取不到返回 None。

        aiocqhttp 适配器会把 notice/request 也包装成 AstrMessageEvent，
        原始 OneBot 事件保留在 event.message_obj.raw_message 中。
        """
        try:
            raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        except Exception:
            return None
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if hasattr(raw, "get") and hasattr(raw, "__getitem__"):
            return raw
        return None

    def _join_verify_font(self) -> str:
        return os.path.join(os.path.dirname(__file__), "assets", "fonts", "MuliHeavy.ttf")

    async def _send_group_msg(self, client, group_id, text: str = "",
                              at_user: str = "", image_b64: str = ""):
        """经 OneBot 直接发群消息（notice 事件与后台任务里都可用）。

        返回 message_id（能取到时），发送失败返回 None。
        """
        msg = []
        if at_user:
            msg.append({"type": "at", "data": {"qq": str(at_user)}})
        if text:
            msg.append({"type": "text", "data": {"text": text}})
        if image_b64:
            msg.append({"type": "image", "data": {"file": f"base64://{image_b64}"}})
        if not msg:
            return None
        try:
            ret = await client.call_action(action="send_group_msg",
                                           group_id=int(group_id), message=msg)
            if isinstance(ret, dict):
                return ret.get("message_id")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[入群审核] 群消息发送失败 group={group_id}: {type(e).__name__}: {e!r}")
        return None

    def _cancel_join_verify_task(self, key: str):
        t = self._join_verify_tasks.pop(key, None)
        if t and not t.done():
            t.cancel()

    async def _join_verify_send(self, st: dict, text: str, at_user: str = "",
                                image_b64: str = ""):
        """发送一条验证相关消息并记录其 message_id，便于验证结束时统一撤回。"""
        client = self._get_best_client()
        if client is None:
            return None
        mid = await self._send_group_msg(client, st.get("group_id"), text=text,
                                         at_user=at_user or st.get("user_id"),
                                         image_b64=image_b64)
        if mid is not None:
            st.setdefault("msg_ids", []).append(mid)
        return mid

    async def _join_verify_recall_ids(self, st: dict):
        """撤回本次验证里机器人自己发出的所有消息（清屏）。"""
        if not self._get_config().get("join_verify_recall", True):
            return
        client = self._get_best_client()
        ids = list(st.get("msg_ids") or [])
        st["msg_ids"] = []
        if client is None or not ids:
            return
        for mid in ids:
            try:
                await client.call_action(action="delete_msg", message_id=int(mid))
                await asyncio.sleep(0.25)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[入群审核] 撤回机器人消息失败(可忽略): {e!r}")

    async def _start_join_verify(self, group_id: str, user_id: str):
        """发起一次入群验证：发验证码图片 + 记录状态 + 启动超时任务。"""
        cfg = self._get_config()
        try:
            timeout = max(30, int(cfg.get("join_verify_timeout") or 120))
        except (TypeError, ValueError):
            timeout = 120
        try:
            max_attempts = max(1, int(cfg.get("join_verify_max_attempts") or 2))
        except (TypeError, ValueError):
            max_attempts = 2

        client = self._get_best_client()
        if client is None:
            logger.warning("[入群审核] 未找到可用的 OneBot 客户端，跳过本次验证")
            return

        key = f"{group_id}:{user_id}"
        self._join_verify.pop(key, None)
        self._cancel_join_verify_task(key)
        # 顺手清理已结束的后台任务引用，避免 _bg_tasks 无限增长
        self._bg_tasks = [t for t in self._bg_tasks if not t.done()]

        question, answer = generate_arithmetic()
        img = render_captcha(question, self._join_verify_font()) if VERIFY_PIL_AVAILABLE else None
        image_b64 = base64.b64encode(img).decode("utf-8") if img else ""

        now = time.time()
        st = {
            "group_id": str(group_id), "user_id": str(user_id),
            "question": question, "answer": int(answer),
            "attempts": 0, "max_attempts": max_attempts,
            "deadline": now + timeout, "last_hint": 0.0,
            "msg_ids": [],  # 机器人本次发出的消息，验证结束/取消时一并撤回
        }
        self._join_verify[key] = st

        tip = (f" 欢迎加入本群！请在 {timeout} 秒内回复下面算式的答案完成验证"
               f"（共 {max_attempts} 次机会，超时或答错将移出群聊）。"
               + ("" if image_b64 else f"\n题目：{question} = ?"))
        await self._join_verify_send(st, tip, at_user=user_id, image_b64=image_b64)

        task = asyncio.create_task(self._join_verify_timeout(key, timeout))
        self._join_verify_tasks[key] = task
        self._bg_tasks.append(task)
        logger.info(f"[入群审核] 向 {key} 发起验证：{question} = {answer}（{timeout}s / {max_attempts} 次机会）")

    async def _join_verify_timeout(self, key: str, timeout: int):
        """超时未验证 → 撤回首屏消息并移出群聊。"""
        try:
            await asyncio.sleep(timeout + 1)
        except asyncio.CancelledError:
            return
        self._join_verify_tasks.pop(key, None)
        st = self._join_verify.get(key)
        if not st:
            return
        if time.time() < st.get("deadline", 0):
            return
        self._join_verify.pop(key, None)
        await self._join_verify_fail(st, "timeout")

    async def _join_verify_fail(self, st: dict, reason: str):
        """验证失败：撤回本次验证中机器人发出的所有消息（不留痕），再移出群聊。"""
        cfg = self._get_config()
        gid, uid = st.get("group_id"), st.get("user_id")
        key = f"{gid}:{uid}"
        self._join_verify.pop(key, None)
        self._cancel_join_verify_task(key)
        await self._join_verify_recall_ids(st)
        client = self._get_best_client()
        if cfg.get("join_verify_kick", True) and client:
            try:
                await client.call_action(action="set_group_kick", group_id=int(gid),
                                         user_id=int(uid), reject_add_request=False)
                logger.info(f"[入群审核] {key} 验证失败({reason})，已撤回首屏消息并移出群聊")
            except Exception as e:  # noqa: BLE001
                logger.error(f"[入群审核] 踢出 {key} 失败: {type(e).__name__}: {e!r}")
        else:
            logger.info(f"[入群审核] {key} 验证失败({reason})，已撤回首屏消息（未开启踢人）")

    async def _join_verify_pass(self, st: dict):
        """验证通过：撤回所有验证消息，只保留一条可配置的欢迎语。"""
        gid, uid = st.get("group_id"), st.get("user_id")
        key = f"{gid}:{uid}"
        self._join_verify.pop(key, None)
        self._cancel_join_verify_task(key)
        await self._join_verify_recall_ids(st)
        welcome = (self._get_config().get("join_verify_welcome_text") or "").strip()
        logger.info(f"[入群审核] {key} 验证通过" + ("（已发送欢迎语）" if welcome else "（未配置欢迎语，静默通过）"))
        if welcome:
            client = self._get_best_client()
            if client:
                await self._send_group_msg(client, gid, text=(" " + welcome), at_user=uid)

    async def _join_verify_wrong(self, st: dict):
        """答案错误：未达上限则提示剩余次数，达上限则撤屏 + 踢出。"""
        st["attempts"] = int(st.get("attempts", 0)) + 1
        left = int(st.get("max_attempts", 2)) - st["attempts"]
        gid, uid = st.get("group_id"), st.get("user_id")
        if left <= 0:
            key = f"{gid}:{uid}"
            self._join_verify.pop(key, None)
            self._cancel_join_verify_task(key)
            await self._join_verify_fail(st, "wrong")
            return
        remain = max(0, int(st.get("deadline", 0) - time.time()))
        await self._join_verify_send(st, f" ❌ 答案错误，还有 {left} 次机会（剩余 {remain} 秒）。")

    async def _join_verify_recall(self, event):
        """撤回验证期间的非答案发言（需机器人有管理权限，失败静默忽略）。"""
        if not self._get_config().get("join_verify_recall", True):
            return
        try:
            mid = getattr(getattr(event, "message_obj", None), "message_id", None)
            client = self._get_best_client()
            if mid is None or client is None:
                return
            await client.call_action(action="delete_msg", message_id=int(mid))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[入群审核] 撤回消息失败(可忽略): {e!r}")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1)
    async def on_group_member_notice(self, event: AstrMessageEvent):
        """群成员入/退群 notice：新成员触发入群验证；退群/被踢清理验证状态。"""
        try:
            raw = self._raw_notice(event)
            if raw is None or raw.get("post_type") != "notice":
                return
            notice_type = raw.get("notice_type")
            if notice_type not in ("group_increase", "group_decrease"):
                return
            gid = str(raw.get("group_id") or "")
            uid = str(raw.get("user_id") or "")
            if not gid or not uid:
                return
            if notice_type == "group_decrease":
                key = f"{gid}:{uid}"
                st_left = self._join_verify.pop(key, None)
                if st_left:
                    self._cancel_join_verify_task(key)
                    await self._join_verify_recall_ids(st_left)
                    logger.info(f"[入群审核] {key} 已离群，清理验证状态并撤回首屏消息")
                return
            # group_increase
            if uid == str(raw.get("self_id") or ""):
                return  # 机器人自己被拉进群，不验证自己
            cfg = self._get_config()
            if not cfg.get("join_verify_enabled", False):
                return
            groups = self._parse_multi(cfg.get("join_verify_group_ids", []))
            if groups and gid not in groups:
                return
            event.stop_event()
            await self._start_join_verify(gid, uid)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[入群审核] 处理群成员事件失败: {type(e).__name__}: {e!r}")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1)
    async def on_group_verify_reply(self, event: AstrMessageEvent):
        """入群验证期间拦截新成员的发言：答对通过、答错计数、其他撤回不计数。"""
        try:
            gid = event.get_group_id()
            uid = str(event.get_sender_id() or "")
            if not gid or not uid:
                return
            key = f"{gid}:{uid}"
            st = self._join_verify.get(key)
            if not st:
                return
            # 只处理真正的消息事件，notice/request 不参与答题
            raw = self._raw_notice(event)
            if raw is not None:
                pt = raw.get("post_type")
                if pt and pt != "message":
                    return
            event.stop_event()
            text = (event.message_str or "").strip()
            nums = re.findall(r"-?\d+", text)
            if not nums:
                # 非答案发言：撤回防刷屏；必要时（带冷却）温和提醒一次
                await self._join_verify_recall(event)
                now = time.time()
                if text and now - float(st.get("last_hint", 0.0)) > 15:
                    st["last_hint"] = now
                    await self._join_verify_send(st, " 请直接回复算式答案（纯数字）。")
                return
            await self._join_verify_recall(event)
            try:
                guess = int(nums[-1])
            except (TypeError, ValueError):
                return
            if guess == int(st.get("answer", -1)):
                await self._join_verify_pass(st)
            else:
                await self._join_verify_wrong(st)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[入群审核] 处理验证回复失败: {type(e).__name__}: {e!r}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("入群验证")
    async def cmd_join_verify(self, event: AstrMessageEvent):
        """入群审核状态与自测（管理员）。

        用法：/入群验证 状态   查看当前配置与验证中人数
              /入群验证 测试   发送一张示例验证码图片
        """
        arg = re.sub(r"^/?入群验证", "", event.message_str or "").strip()
        cfg = self._get_config()
        if arg in ("测试", "test"):
            if not VERIFY_PIL_AVAILABLE:
                yield event.plain_result("⚠️ Pillow 不可用，无法渲染验证码图片。请先安装依赖后重载插件。")
                return
            q, a = generate_arithmetic()
            img = render_captcha(q, self._join_verify_font())
            if not img:
                yield event.plain_result("⚠️ 验证码图片渲染失败。")
                return
            tmp = tempfile.mktemp(suffix=".png", prefix="join_verify_test_")
            try:
                with open(tmp, "wb") as f:
                    f.write(img)
                await event.send(MessageChain([ImageComponent(file=tmp)]))
                yield event.plain_result(f"📋 验证码自测：题目 {q} = ?（答案 {a}）")
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
            return
        groups = self._parse_multi(cfg.get("join_verify_group_ids", []))
        yield event.plain_result(
            "🔐 入群审核状态\n"
            f"开关：{'✅ 已开启' if cfg.get('join_verify_enabled') else '⛔ 已关闭'}\n"
            f"生效群：{'全部群' if not groups else '、'.join(groups)}\n"
            f"超时：{int(cfg.get('join_verify_timeout') or 120)} 秒\n"
            f"机会：{int(cfg.get('join_verify_max_attempts') or 2)} 次（答错达上限即踢）\n"
            f"失败处理：{'撤回首屏消息并移出群聊' if cfg.get('join_verify_kick', True) else '撤回首屏消息（不踢人）'}\n"
            f"通过欢迎词：{((cfg.get('join_verify_welcome_text') or '').strip() or '（静默通过，不发送）')[:40]}\n"
            f"撤回机制：{'开启（成员发言 + 机器人验证消息）' if cfg.get('join_verify_recall', True) else '关闭'}\n"
            f"当前验证中：{len(self._join_verify)} 人\n"
            "—\n"
            "用法：/入群验证 状态 | /入群验证 测试"
        )

    def _get_best_client(self, event=None):
        try:
            platforms = list(self.context.platform_manager.get_insts())
            cid = "aiocqhttp"  # 平台 ID 无需配置，默认匹配 QQ/aiocqhttp/onebot
            for p in platforms:
                pid = p.meta().id
                if pid==cid or pid==cid.replace("aiocqhttp","qq"):
                    c = p.get_client()
                    if hasattr(c,"call_action"): return c
            for p in platforms:
                pid = p.meta().id.lower()
                if "webchat" in pid: continue
                if any(k in pid for k in ["cqhttp","onebot","qq"]):
                    c = p.get_client()
                    if hasattr(c,"call_action"): return c
            for p in platforms:
                pid = p.meta().id
                if "webchat" in pid: continue
                c = p.get_client()
                if hasattr(c,"call_action"): return c
            if event:
                pl = self.context.get_platform_inst(event.get_platform_id())
                if pl:
                    c = pl.get_client()
                    if c and hasattr(c,"call_action"): return c
        except: pass
        return None


plugin = MuliyResourcesPlugin

# -*- coding: utf-8 -*-
"""
暮黎资源聚合 AstrBot 插件 v1.7.0 (含 NDJSON 埋点)
=================================
整合影视搜索 + 游戏搜索 + 软件日报&搜索

core/constants.py  — 常量定义
core/session.py    — 会话管理器
core/game.py       — 游戏搜索相关函数
core/software.py   — 软件日报&搜索相关函数
core/movie.py      — 影视搜索相关函数 (a123tv.com)
"""

import asyncio, base64, concurrent.futures, datetime, io, json, os, re, sys, tempfile, time, traceback, zipfile, zoneinfo
from typing import Optional

# === DEBUG INSTRUMENTATION (debug session c4a65f) ===
import threading as _thr, pathlib as _pl
_DBGL = threading.Lock() if hasattr(threading := __import__('threading'), 'Lock') else _thr.Lock()
def _dbg_log(hid, msg, data):
    try:
        line = json.dumps({
            "sessionId": "c4a65f",
            "location": "main.py",
            "message": msg,
            "data": data,
            "hypothesisId": hid,
            "runId": "initial",
            "timestamp": int(time.time() * 1000),
        }, ensure_ascii=False)
        # 优先写容器内路径（Docker 部署）；宿主机回退；桌面调试最后回退
        for _p in ("/AstrBot/data/plugins/astrbot_plugin_muliyresources/debug-c4a65f.log",
                   "/www/dk_project/dk_app/astrbot/astrbot_RLHF/data/plugins/astrbot_plugin_muliyresources/debug-c4a65f.log",
                   r"C:\Users\Administrator\debug-c4a65f.log"):
            try:
                _pl.Path(_p).parent.mkdir(parents=True, exist_ok=True)
                with open(_p, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                break
            except Exception:
                continue
    except Exception:
        pass
# === END DEBUG INSTRUMENTATION ===

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
)
from .core.qr_login import (
    format_cookie_string, extract_xdgame_cookies,
    login_with_password_async, submit_captcha_async,
)
from .core.software import (
    search_software, get_search_detail, generate_search_html,
    get_software_list, get_detail, sync_scrape, gen_list_image, gen_report_zip,
    build_summer_html, download_summer_assets
)
from .core.game_daily import (
    get_today_games, build_cartoon_html, render_html_to_png
)
from .core.movie_daily import (
    fetch_movie_daily, fetch_movie_daily_auto, build_glass_html,
    render_glass_to_png, gen_report_zip as gen_movie_report_zip
)
from .core.movie import (
    search_movies, get_movie_detail,
    format_movie_list, format_episodes, format_sources,
    select_episode, select_source,
    parse_play_page, build_play_url,
    MV_BASE_URL,
)
from .core.novel import (
    search_novels, fetch_novel, download_novel_file,
    check_sources, NovelApiError, NOVEL_FORMATS,
)
from .core.muliy_site import (
    MuliySiteClient, discover_best_domain, cover_url as muliy_cover_url,
    play_url as muliy_play_url, format_movie_list_new, format_resource_type,
    format_play_nodes, format_pan_list, format_pan_types, group_panlist_by_type,
    extract_pwd, build_merged_text,
)

from .core.netease import (
    NeteaseParser, extract_netease_id, extract_from_miniapp,
    looks_like_netease, resolve_shortlink, download_mp3,
    normalize_api_base, qr_login_key, qr_login_create, qr_login_check,
    qrimg_to_bytes, extract_music_cookie, get_login_nickname,
)
from .core.audio_clip import ffmpeg_available, get_duration_seconds, compute_clip_range, cut_clip
from .core.vip_capture import (
    is_vip_video_url, analyze_vip_link, build_interface_link,
    verify_interface_playable, VIP_INTERFACES,
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
        "movie_source", "muliy_cache_ttl",
        "movie_report_enabled", "movie_report_max",
        "movie_schedule_hour", "movie_schedule_minute", "movie_group_ids", "movie_sections",
        "muliy_cookie",
    ],
    "music": [
        "wyy_auto_parse", "wyy_music_type", "wyy_custom_url",
        "wyy_clip_seconds", "wyy_audio_format", "wyy_cookie",
    ],
    "vip_video": ["video_vip_parse", "video_vip_timeout"],
    "browser": ["browser_channel", "browser_exe"],
    "novel": [
        "sonovel_base_url", "sonovel_token", "sonovel_search_limit",
        "sonovel_format", "sonovel_timeout", "sonovel_download_timeout",
    ],
}
_KEY_TO_GROUP = {k: g for g, ks in _CONF_GROUPS.items() for k in ks}


# ========================================================================
#  AstrBot 插件类
# ========================================================================

@register("astrbot_plugin_muliyresources", "暮黎 Muliy",
          "暮黎资源聚合 - 影视搜索(教父.com新站/a123tv) / 游戏搜索 / 软件日报&搜索 / 网易云语音名片 / 摸头杀GIF / 舔狗表情", "1.9.17")
class MuliyResourcesPlugin(Star):

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self._plugin_config = self._migrate_config(config)
        _dbg_log("H0", "plugin __init__ called", {
            "config_type": str(type(config).__name__) if config is not None else "None",
            "has_xdgame_username": config.get("xdgame_username") if isinstance(config, dict) else "N/A",
        })
        self._sessions = SessionManager()
        self._search_sessions = SearchSessionManager()
        self._movie_sessions = SearchSessionManager()   # 影视会话 (a123tv)
        self._movie_sessions_new = SearchSessionManager()  # 影视会话 (教父.com 新站)
        self._novel_sessions = SearchSessionManager()  # 小说会话 (so-novel)
        self._muliy_client: MuliySiteClient | None = None  # 新站客户端（懒加载）
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
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._fallback_task: Optional[asyncio.Task] = None
        self._sw_job_lock = None  # 懒初始化（需在事件循环内创建 asyncio.Lock）
        # 定时调度模式：优先用 AstrBot 官方 context.cron_manager.scheduler（可靠），
        # 不可用时回退到自建 AsyncIOScheduler（旧逻辑）
        self._using_framework_scheduler: bool = False
        self._scheduled_job_ids: list[str] = []
        # VIP 解析：等待用户「选接口」的待处理会话 {unified_msg_origin: {...}}
        self._vip_pending: dict = {}
        self._last_run_date: str = ""
        self._debug_log_path: str = ""
        self._reports_dir: str = ""
        self._reports_retention_days: int = 5

    # ==================== 生命周期 ====================

    async def initialize(self):
        logger.info("暮黎资源聚合插件初始化")
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
        await self._start_sw_scheduler()
        # 影视源 / 游戏源：按 cookie 是否配置自动决定（替代手动 movie_source 切换）
        try:
            cfg = self._get_config()
            # 影视源：cookie 登录模式（绕过 PoW+验证码），否则回退 a123tv 旧站
            cookies = (cfg.get("muliy_cookie") or "").strip()
            ttl = int(cfg.get("muliy_cache_ttl") or 3600)
            if cookies:
                self._muliy_client = MuliySiteClient(base_url="", cache_ttl=ttl, cookies=cookies)
                logger.info("[暮黎资源] 影视源=教父.com新站 (cookie登录模式)")
            else:
                logger.warning("[暮黎资源] 未配置教父.com Cookie，影视搜索回退 a123tv 旧站")
                self._muliy_client = None
        except Exception as e:
            logger.warning(f"[暮黎资源] 客户端初始化失败: {e}")
            self._muliy_client = None

    def _get_muliy_client(self) -> MuliySiteClient | None:
        """获取新站客户端；cookie 配置变更则重建。"""
        try:
            cfg = self._get_config()
            cookies = (cfg.get("muliy_cookie") or "").strip()
            if not cookies:
                return None
            if self._muliy_client is None or self._muliy_client._cookie_str != cookies:
                ttl = int(cfg.get("muliy_cache_ttl") or 3600)
                self._muliy_client = MuliySiteClient(base_url="", cache_ttl=ttl, cookies=cookies)
        except Exception:
            return None
        return self._muliy_client

    async def terminate(self):
        logger.info("暮黎资源聚合插件终止")
        await self._stop_sw_scheduler()

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

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        """当用户消息包含资源搜索意图时，向 system prompt 注入工具调用规则。

        设计原则（参考 Spotify 插件的「被动视野」思路）：
        - LLM 只负责「判断意图 + 调用工具 + 排版润色」
        - 插件只负责「执行实际搜索/翻页/下载」
        - 工具的返回文本就是 LLM 看到的事实，LLM 可以自由排版
        """
        # ★新站影视会话兜底拦截：LLM 可能偷懒不调工具，在 LLM 前直接处理
        raw_text = event.message_str.strip()
        ses_mn = self._movie_sessions_new.get(event)
        if ses_mn and ses_mn.get("stage") in ("select_movie_new", "select_res_type",
                                               "select_pan_type", "select_play_node", "select_episode_new", "select_pan"):
            is_cmd = (raw_text in ("0", "取消")
                      or re.match(r'^[1-9]\d*$', raw_text)
                      or raw_text in ("下一页", "上一页")
                      or raw_text.startswith("跳"))
            if is_cmd:
                try:
                    logger.info(f"[暮黎资源] 新站会话兜底拦截 stage={ses_mn.get('stage')} text={raw_text}")
                    await self._handle_movie_new_selection(event, raw_text)
                except Exception as e:
                    logger.error(f"[暮黎资源] 新站会话兜底处理失败: {e}")
                    await event.send(MessageChain([Plain(f"【暮黎资源】 处理失败：{str(e)[:120]}")]))
                event.stop_event()
                return

        # ★影视搜索意图拦截：用户说"我想看XX/观看XX"时，LLM 可能误调 search_resource，
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
            if _mn and len(_mn) >= 2 and not re.search(r'(游戏|软件|app|APP|工具)', _mn):
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

        # ★小说搜索意图拦截：用户说"找小说XX/搜小说XX/我想看小说XX"时，LLM 可能误调
        #   search_resource/search_movie，这里直接强制调 search_novel，不依赖 LLM 选工具。
        #   有旧会话时自动清除（用户要搜新的了，不必手动取消）。
        _novel_intent_kws = ('找小说', '搜小说', '看小说', '读小说', '听小说',
                             '小说搜索', '本小说', '想看小说', '我想看小说')
        if any(k in raw_text for k in _novel_intent_kws):
            nses0 = self._novel_sessions.get(event)
            if nses0:
                self._novel_sessions.delete(event)
                logger.info(f"[暮黎资源] 新小说搜索自动清除旧会话 (stage={nses0.get('stage')})")
            _nn = re.sub(r'^(我想看|我要看|想看|要看|帮我找|帮我搜|帮我看|找|搜|看|读|听|我|要|想|帮我|能不能|可以|麻烦|请)\s*', '', raw_text)
            _nn = re.sub(r'^(一下|一本|本|部|下|个)\s*', '', _nn)  # 去量词
            _nn = re.sub(r'小说\s*', '', _nn)  # 去"小说"统称
            _nn = re.sub(r'[的啊呢吧呀哦！。.,，]+$', '', _nn).strip()
            if _nn:
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

        text = event.message_str.strip().lower()
        # 资源搜索关键词 + 翻页/取消关键词（任一匹配就注入）
        resource_kw = (
            "找", "搜索", "下载", "资源", "游戏", "软件",
            "影视", "电影", "电视剧", "综艺", "动漫", "追剧", "看片",
            "想看", "观看", "看剧", "看一", "看个", "看部", "看番", "追番",
            "找小说", "搜小说", "看小说", "读小说", "听小说",
            "wps", "office", "微信", "qq", "钉钉",
            "有没有", "给个", "给我", "想要",
            "下一页", "上一页", "跳转", "跳到", "翻页",
            "取消", "算", "不要",
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
            "第一个", "第二个", "第三个", "第四个", "第五个",
            "百度", "天翼", "夸克", "阿里", "迅雷", "123", "uc", "磁力",
        )
        if not any(k in text for k in resource_kw):
            return

        # 负向意图：明显的非搜索类请求（生成封面/图片、写介绍、宣传、公告等）。
        # 这类消息常含"小说/游戏/影视/搜索/下载"等词，会被上方 resource_kw 误命中；
        # 若仍注入资源搜索引导，LLM 可能把"介绍里提到的'小说'"误判为小说搜索而误调工具。
        _non_search_intent = (
            "封面", "生成", "画一张", "画个", "画图", "做一张", "做图",
            "介绍", "宣传", "公告", "海报", "banner", "logo",
            "文案", "宣传语", "配图", "插图",
        )
        if any(k in text for k in _non_search_intent):
            return

        instruction = '''

【暮黎资源 — 工具调用规则（务必严格遵守）】

■ 你的工作模式
你是一个资源检索助手。用户说"找资源/翻页/选资源/选网盘"时，**必须调用下方对应工具**，
**严禁**自己编造资源列表、网盘名称或下载链接。**严禁**联网搜索。

■ 你的回复格式（非常重要！用户最在意的两点）
1. **每次回复搜索结果时**第一行必须写明「共 X 个 / 第 M/N 页」——告诉用户一共有多少结果、当前第几页、共几页
2. **每次回复末尾**必须提示用户可以怎么操作，例如：
   - 只有1页时：「回复数字选一个吧～😊」
   - 多页时：「共10个资源，当前第1/2页哦～想要下一页就跟我说'下一页'😆」
3. emoji、亲切语气都可以自由发挥，但**上述两个要点不可省略**

■ 可用工具与触发场景
| 用户输入                                | 你必须调用的工具                          | 参数填什么                          |
|----------------------------------------|------------------------------------------|-------------------------------------|
| "帮我找 XX"（不明确类型）                | search_resource                          | keyword=用户想找的名称（去掉"游戏""软件""影视"等统称） |
| "找游戏 XX" / 游戏关键词（王者、原神）   | search_game                              | game_name=游戏名                    |
| "找软件 XX" / 软件关键词（微信、wps）   | search_software                          | software_name=软件名                |
| "找影视 XX" / "我想看 XX" / "观看 XX" / 影视名（庆余年、怪奇物语、黑袍、星际穿越）| search_movie | movie_name=影视名 |
| "找小说 XX" / "搜小说 XX" / "我想看小说 XX" / "看小说 XX"（明确要搜/看小说）| search_novel | novel_name=小说名或作者名 |
| "下一页" / "上一页" / "跳转 3"          | paginate_results                         | action=下一页/上一页/跳转3          |
| 用户回复数字（1、2、3、第一个…）         | select_search_result                     | selection=数字或中文序数             |
| 用户选网盘（百度网盘、夸克、1）         | select_download_link                     | selection=网盘名或数字              |

■ ⚠️ 影视搜索优先（重要！）
- 用户说"我想看XX""观看XX""找影视XX"或提到任何影视/剧/电影名 → **必须调 search_movie**，不要调 search_resource 或 web_search
- 影视名示例：庆余年、怪奇物语、黑袍纠察队、星际穿越、流浪地球、庆余年第二季
- 只有用户明确说"找游戏""找软件"或游戏/软件名时，才调 search_resource/search_game/search_software

■ ⚠️ 影视工具的特殊说明
- **影视**默认走教父.com 新站（需登录），搜索结果后用户选影视 → 选资源类型：
  - **[1] 在线播放** → 选播放节点(1-N) → 系统合并转发(标题+封面+简介+播放链接)
  - **[2] 网盘资源** → 选网盘(1-N，可翻页) → 系统合并转发(标题+封面+简介+网盘链接)
- 旧站(a123tv)模式：选影视后自动判断电影/剧，剧先选集数再选线路
- **严禁**对影视调用 `select_download_link`（影视有自己的流程，调用会被拒绝）
- 用户选影视/资源类型/节点/网盘时，**只需调 select_search_result(selection=数字)**，系统自动走对应阶段

■ ⚠️ 小说工具的特殊说明
- **仅当用户明确要搜索/阅读/下载小说时**才调 search_novel（如"找小说XX""搜小说XX""我想看小说XX"）。
- ⚠️ 介绍、宣传、公告、封面生成类话语里提到"小说"（如"新增小说搜索下载""本插件支持小说功能"）**不是小说搜索意图**，严禁调用 search_novel，也不要调其它 search_* 工具，直接按普通对话/画图处理。
- 用户给出明确的书名或作者名且意图是"看/搜/下"时才算；纯宣传提到"小说"二字不算。
- 小说名示例：斗破苍穹、我有一座冒险屋、诡秘之主、天蚕土豆（作者）
- 小说流程：选小说(回复数字) → 选格式(TXT/EPUB/HTML/PDF，回复数字或"下载/确认"用默认 TXT) → 系统拉取文件流以**文件形式**直接发送（不走 localhost 链接、不依赖 WebUI 预览）
- 用户选小说/格式时，**由 on_any_message 直接处理**（无需再调工具），系统自动走对应阶段

■ ⚠️ 翻页规则（最容易踩坑）
- 用户**首次**说"下一页/上一页" → **必须**调 paginate_results(action="下一页")
- **绝对不要**在用户说翻页时重新调 search_*（资源列表已存在会话中）
- 工具返回的就是下一页的完整数据（已带「共 X 个 / 第 M/N 页」），你可以**自由排版**（加 emoji、改格式都行）
- **再次强调**：排版时第一行必须保留「共 X 个 第 M/N 页」信息

■ 关键词清洗（重要）
- 用户说"我想玩赛车游戏" → 传 game_name="赛车"（去掉"游戏"后缀）
- 用户说"下载微信软件" → 传 software_name="微信"（去掉"软件"后缀）
- 工具内部已自动清洗，但你也要保持传入简洁

■ 选择规则
- 用户说数字（1、2、3） → 调 select_search_result(selection="1")
- 用户说"第一个/最后一个" → select_search_result(selection="第一个")
- 用户说网盘名（百度网盘、夸克） → 调 select_download_link(selection="百度网盘")
- 用户说数字（选了网盘后的 1、2、3） → 也调 select_download_link(selection="1")

■ 绝对禁止
1. 禁止编造任何资源标题、网盘名、下载链接
2. 禁止在用户说翻页/选择时重搜（已经搜过了！）
3. 禁止使用 markdown 表格（QQ 客户端会乱码）
'''
        req.system_prompt += "\n" + instruction
        logger.debug(f"[暮黎资源] LLM请求拦截，注入工具调用指令 text_len={len(text)}")

    # ==================== LLM 响应拦截：禁用 LLM 中间总结 ====================

    @filter.on_decorating_result()
    async def _strip_llm_chitchat_after_tool(self, event: AstrMessageEvent):
        """当 LLM 完成工具调用后，如果插件已经直接发了消息（event.send），
        清空 LLM 后续的"多嘴总结"文本，避免重复发送。

        触发条件：当前 session 上有 _llm_handled 标记
        - search_software / search_game / paginate_results：插件直接 send 了格式化页面
        - select_search_result / select_download_link：插件直接 send 了详情/网盘列表
        → 清空 LLM 的二次总结
        """
        try:
            ses_sw = self._search_sessions.get(event)
            ses_g = self._sessions.get(event)
            ses_mv = self._movie_sessions.get(event)
            ses_mv_new = self._movie_sessions_new.get(event)
            ses_nv = self._novel_sessions.get(event)
            target_ses = ses_sw or ses_g or ses_mv or ses_mv_new or ses_nv
            if not target_ses or not target_ses.get("_llm_handled"):
                return
            target_ses["_llm_handled"] = False
            result = event.get_result()
            if result is not None and result.chain:
                logger.info(f"[LLM-STRIP] 清空 LLM 中间总结 (stage={target_ses.get('stage')})")
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
            _dbg_log("H1", "_get_config: _plugin_config is None", {})
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
        _dbg_log("H1", "_get_config: config type", {
            "type": str(type(raw).__name__),
            "xdgame_username_present": flat.get("xdgame_username") is not None,
        })
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

        - 仅读取各自专属键（game_group_ids / movie_group_ids）；
        - 不回退软件群 group_ids（用户要求三日报群号分开）；
        - 返回 (群列表, 是否走了回退) —— 当前不共享，fb 恒为 False。
        """
        config = self._get_config()
        raw = config.get(specific_key, []) if isinstance(config, dict) else []
        return self._parse_multi(raw), False

    def _get_cookie(self) -> str:
        return self._get_config().get("cookie", "").strip()

    async def _update_config(self, key: str, value: object):
        """持久化更新插件配置中的某个字段（issue4 修复：用插件 id 持久化 + 本地文件兜底）"""
        cfg = self._plugin_config
        if not isinstance(cfg, dict):
            cfg = {}
        g = _KEY_TO_GROUP.get(key)
        if g is not None:
            if not isinstance(cfg.get(g), dict):
                cfg[g] = {}
            cfg[g][key] = value
        else:
            cfg[key] = value
        self._plugin_config = cfg
        try:
            if hasattr(self.context, 'update_plugin_config'):
                pid = self._plugin_id()
                # AstrBot 签名：update_plugin_config(plugin_id: str, config: dict)
                await self.context.update_plugin_config(pid, cfg)
                logger.info(f"[暮黎资源] 配置已持久化: {key}=已更新 (pid={pid})")
        except Exception as e:
            logger.warning(f"[暮黎资源] 配置持久化(update_plugin_config)失败: {e}")
        # 兜底：写入本地文件，防止 AstrBot 配置未落盘导致重装/重启后 Cookie 丢失
        try:
            self._persist_config_file(cfg)
        except Exception as e:
            logger.warning(f"[暮黎资源] 配置本地文件写入失败: {e}")

    def _plugin_id(self) -> str:
        """返回插件 id（即插件目录名，也是 AstrBot 配置存储键）"""
        mod = self.__class__.__module__  # 形如 astrbot_plugin_muliyresources.main
        return mod.split(".")[0] if "." in mod else str(mod)

    def _config_file_path(self) -> str:
        """Cookie 等敏感配置的兜底文件路径。

        关键：必须放在【插件目录之外】的 AstrBot data 目录下，
        否则「卸载/覆盖重装插件」会把插件目录一起删掉，兜底文件也跟着没了
        （这正是之前 switch618_cookie 重装必丢的根因）。
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
                return os.path.join(dd, "plugin_data", "astrbot_plugin_muliyresources",
                                    "config_override.json")
        except Exception:
            pass
        # 兜底：从插件目录向上找包含 plugins/ 的目录（即 AstrBot data 目录）
        cur = base
        for _ in range(6):
            if os.path.isdir(os.path.join(cur, "plugins")):
                return os.path.join(cur, "plugin_data", "astrbot_plugin_muliyresources",
                                    "config_override.json")
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        # 最终兜底：插件目录内（覆盖重装会丢，仅作最后的兼容）
        return os.path.join(base, "data", "plugin_config_override.json")

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

    async def _g_check_cookie(self):
        """路由 Cookie 有效性检查。返回 None=有效，字符串=失效原因('expired'|'invalid'|'error:..')。"""
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
        return await self._check_cookie_silent()

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

    @filter.llm_tool(name="search_resource")
    async def llm_search_resource(self, event: AstrMessageEvent, keyword: str):
        """综合搜索游戏、软件与影视资源。当用户想找资源、且类型不明确时调用。

        会同时搜索游戏库（xdgame.com / switch618.com）、软件库（x6d.com）与影视库
        （教父.com 新站或 a123tv 旧站），结果分类型展示。
        - 仅命中某一类型时，直接展示该类型完整列表（含翻页）。
        - 同时命中多种类型时，先给出各类型前几条预览，用户回复「游戏」/「软件」/「影视」
          即可查看对应类型的完整列表（含翻页）。
        翻页：用户说"下一页/上一页/跳转N"时，**必须调 paginate_results**。
        选择：用户说数字时，**必须调 select_search_result**。

        Args:
            keyword(string): 用户想找的资源名称（去掉了"游戏""软件""影视"等统称后缀）
        """
        keyword = clean_search_keyword(keyword)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, keyword)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        config = self._get_config()
        fm = min(int(config.get("max_search_results", 32) if isinstance(config, dict) else 32), 48)
        ps = 8
        tag = "【暮黎资源】"

        # 检查 xdgame Cookie 有效性
        cookie_bad = await self._g_check_cookie()
        if cookie_bad in ("expired", "invalid"):
            logger.info(f"[暮黎资源] search_resource('{keyword}') → Cookie {cookie_bad}，跳过游戏搜索")
            game_results = []
        else:
            # 并行搜索
            try: game_results = await asyncio.to_thread(self._g_search, keyword, max(4, fm // 2))
            except Exception: game_results = []
        try: sw_results = await asyncio.to_thread(search_software, keyword, max(4, fm // 2))
        except Exception: sw_results = []

        has_game, has_sw = len(game_results) > 0, len(sw_results) > 0

        # ===== 影视搜索（教父.com 新站优先，否则 a123tv 旧站）=====
        cfg = self._get_config()
        forced_a123 = (cfg.get("movie_source") or "").strip().lower() == "a123tv"
        mv_client = self._get_muliy_client() if not forced_a123 else None
        mv_results, mv_new = [], False
        try:
            if mv_client:
                mv_results = await asyncio.to_thread(mv_client.search, keyword, fm)
                mv_new = True
            else:
                mv_results = await asyncio.to_thread(search_movies, keyword, fm)
        except Exception as e:
            logger.error(f"[暮黎资源] search_resource 影视搜索失败: {e}")
            mv_results = []
        has_mv = len(mv_results) > 0
        logger.info(f"[暮黎资源] search_resource('{keyword}') → 游戏{len(game_results)} 软件{len(sw_results)} 影视{len(mv_results)}")

        # Cookie 失效提示（仅影响游戏）
        cookie_warn = ""
        if not has_game and cookie_bad in ("expired", "invalid"):
            cookie_warn = ("⚠️ 游戏资源 Cookie 未生效，无法搜索游戏。"
                           + ("请联系管理员发送 /game_cookie_refresh 获取 Cookie"
                              if self._game_source() == "switch618"
                              else "请发送 /game_cookie_refresh 更新 Cookie")
                           + "\n")

        # —— 辅助：建立影视会话（供 select_search_result 路由）——
        def _setup_movie_ses():
            if mv_new:
                self._movie_sessions_new.set(event, {"stage": "select_movie_new", "keyword": keyword,
                    "results": mv_results, "page": 0, "page_size": ps, "_updated": time.time()})
            else:
                self._movie_sessions.set(event, {"stage": "select_movie", "keyword": keyword,
                    "results": mv_results, "page": 0, "page_size": ps, "_updated": time.time()})

        # 无游戏+无软件时重试（影视已搜过，不再重试）
        if not has_game and not has_sw:
            # 重试：若首次游戏失败是因为 cookie 过期就不再重试
            if cookie_bad not in ("expired", "invalid"):
                try: game_results = await asyncio.to_thread(self._g_search, keyword, fm)
                except Exception: game_results = []
            try: sw_results = await asyncio.to_thread(search_software, keyword, fm)
            except Exception: sw_results = []
            has_game, has_sw = len(game_results) > 0, len(sw_results) > 0

        if not has_game and not has_sw and not has_mv:
            return f"{tag} 未找到与「{keyword}」相关的游戏、软件或影视资源。请确认名称是否正确。"

        # ===== 单一类型：直接 send 完整列表（不把资源列表回传给 LLM）=====
        if has_mv and not has_game and not has_sw:
            _setup_movie_ses()
            t = len(mv_results); pt = (t + ps - 1) // ps
            page_txt = (format_movie_list_new(mv_results, keyword, 0, ps)
                        if mv_new else self._format_mv_page(self._movie_sessions.get(event)))
            await event.send(MessageChain([Plain(
                tag + f" 🎬 影视搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt)]))
            if self._movie_sessions.get(event): self._movie_sessions.update(event, _llm_handled=True)
            if mv_new and self._movie_sessions_new.get(event): self._movie_sessions_new.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] → 影视命中{len(mv_results)}条 → 直接 send")
            return f"[已发送给用户] 影视搜索结果共 {len(mv_results)} 个（已直接发送，含翻页与选择提示）。用户后续操作由 on_any_message 直接处理，无需 LLM 再调用工具。"

        if has_game and not has_sw and not has_mv:
            self._sessions.set(event, {"stage":"select_game","keyword":keyword,"results":game_results,
                                        "page":0,"page_size":ps,"selected_index":-1,"game_detail":None,"selected_link":None})
            t = len(game_results); pt = (t + ps - 1) // ps
            await event.send(MessageChain([Plain(
                tag + f" 🎮 游戏搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + self._format_game_page(self._sessions.get(event)))]))
            self._sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] → 游戏命中{len(game_results)}条 → 直接 send")
            return f"[已发送给用户] 游戏搜索结果共 {len(game_results)} 个（已直接发送，含翻页与选择提示）。用户后续操作由 on_any_message 直接处理，无需 LLM 再调用工具。"

        if has_sw and not has_game and not has_mv:
            self._search_sessions.set(event, {"stage":"select_software","keyword":keyword,"results":sw_results,
                                               "page":0,"page_size":ps,"selected_index":-1,"detail":None,"selected_link":None})
            t = len(sw_results); pt = (t + ps - 1) // ps
            await event.send(MessageChain([Plain(
                tag + f" 💿 软件搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + self._format_sw_page(self._search_sessions.get(event)))]))
            self._search_sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] → 软件命中{len(sw_results)}条 → 直接 send")
            return f"[已发送给用户] 软件搜索结果共 {len(sw_results)} 个（已直接发送，含翻页与选择提示）。用户后续操作由 on_any_message 直接处理，无需 LLM 再调用工具。"

        # ===== 多类型组合：直接 send 预览，回复「游戏/软件/影视」路由（对应工具再发完整列表）=====
        if has_game:
            self._sessions.set(event, {"stage":"select_game","keyword":keyword,"results":game_results,
                                        "page":0,"page_size":ps,"selected_index":-1,"game_detail":None,"selected_link":None})
        if has_sw:
            self._search_sessions.set(event, {"stage":"select_software","keyword":keyword,"results":sw_results,
                                               "page":0,"page_size":ps,"selected_index":-1,"detail":None,"selected_link":None})
        if has_mv:
            _setup_movie_ses()

        lines = [f"{tag} 🔍 「{keyword}」的综合搜索结果：\n"]
        if cookie_warn:
            lines.append(cookie_warn.strip() + "\n")

        def _snip(items):
            out = []
            for i, x in enumerate(items[:4], 1):
                title = x.get("title", "")
                title = (title[:40] + "...") if len(title) > 43 else title
                out.append(f"  {emoji_index(i)} {title}")
            if len(items) > 4:
                out.append(f"  ...还有{len(items) - 4}个（共{len(items)}个）")
            return out

        if has_game:
            lines.append("🎮 【游戏结果】"); lines += _snip(game_results); lines.append("")
        if has_sw:
            lines.append("💿 【软件结果】"); lines += _snip(sw_results); lines.append("")
        if has_mv:
            lines.append("🎬 【影视结果】")
            for i, m in enumerate(mv_results[:4], 1):
                title = m.get("title", "")
                title = (title[:30] + "...") if len(title) > 33 else title
                extra = ""
                if m.get("type"): extra += f" 【{m['type']}】"
                if m.get("year"): extra += f"·{m['year']}"
                if m.get("score"): extra += f" ⭐{m['score']}"
                lines.append(f"  {emoji_index(i)} {title}{extra}")
            if len(mv_results) > 4:
                lines.append(f"  ...还有{len(mv_results) - 4}个（共{len(mv_results)}个影视）")
            lines.append("")

        nav = []
        if has_game: nav.append("「游戏」")
        if has_sw: nav.append("「软件」")
        if has_mv: nav.append("「影视」")
        lines.append(f"\n回复{nav}查看对应类型的完整列表（含翻页），回复0取消。{SESSION_TIMEOUT}秒超时。")
        hints = []
        if has_game: hints.append(f"回复「游戏」时调 search_game(game_name={keyword})")
        if has_sw: hints.append(f"回复「软件」时调 search_software(software_name={keyword})")
        if has_mv: hints.append(f"回复「影视」时调 search_movie(movie_name={keyword})")
        lines.append(f"\n[系统提示] {'；'.join(hints)}。翻页调 paginate_results；数字选择调 select_search_result。已把预览直接发给用户，请勿再把列表回发给用户。")
        logger.info(f"[暮黎资源] → 综合命中 游戏{len(game_results)} 软件{len(sw_results)} 影视{len(mv_results)} → 预览直接 send")
        await event.send(MessageChain([Plain("\n".join(lines))]))
        # 预览模式下标记 _llm_handled，避免 LLM 再复述列表
        for _m in (self._sessions, self._search_sessions, self._movie_sessions, self._movie_sessions_new):
            _s = _m.get(event)
            if _s: _s["_llm_handled"] = True
        return f"[已发送给用户] 综合搜索结果预览：游戏{len(game_results)}个、软件{len(sw_results)}个、影视{len(mv_results)}个（已直接发送预览）。用户回复「游戏/软件/影视」时请分别调 search_game/search_software/search_movie 获取完整列表，不要重搜、不要把列表再发给用户。"

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
            await event.send(MessageChain([Plain(self._format_sw_page(ses))])); return
        if text.startswith("跳"):
            m = re.search(r"\d+", text)
            if m:
                ps = ses.get("page_size", 8); t = len(ses["results"]); pt = (t + ps - 1) // ps; n = int(m.group())
                if 1 <= n <= pt: ses["page"] = n - 1; ses["_updated"] = time.time(); await event.send(MessageChain([Plain(self._format_sw_page(ses))])); return
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
        links = detail["download_links"]
        txt = "📦 " + (detail.get("name") or sel["title"]) + "\n" + "=" * 30 + f"\n找到{len(links)}个下载链接：\n\n"
        for i, lk in enumerate(links, 1): txt += f"{emoji_index(i, len(links))} {SW_DISK_ICONS.get(lk['pan'], '📥')} {lk['pan']}\n"
        txt += f"\n请回复数字或网盘名（1-{len(links)}），回复0取消。"
        await event.send(MessageChain([Plain(txt)])); return

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
            await event.send(MessageChain([Plain(self._format_game_page(ses))])); return
        if text.startswith("跳"):
            m = re.search(r"\d+", text)
            if m:
                ps = ses.get("page_size", 8); t = len(ses["results"]); pt = (t + ps - 1) // ps; n = int(m.group())
                if 1 <= n <= pt: ses["page"] = n - 1; ses["_updated"] = time.time(); await event.send(MessageChain([Plain(self._format_game_page(ses))])); return
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
        links = detail["download_links"]
        txt = "📦 " + (detail.get("name") or sel["title"]) + "\n" + "=" * 30 + f"\n找到{len(links)}个下载链接：\n\n"
        for i, lk in enumerate(links, 1): txt += f"{emoji_index(i, len(links))} {GAME_PAN_ICONS.get(lk['pan'], '📥')} {lk['pan']}\n"
        txt += f"\n请回复数字或网盘名（1-{len(links)}），回复0取消。"
        await event.send(MessageChain([Plain(txt)])); return

    @filter.llm_tool(name="search_game")
    async def llm_search_game(self, event: AstrMessageEvent, game_name: str):
        """专门搜索游戏资源。当用户明确说"找游戏"或游戏关键词时调用。

        翻页：用户说"下一页/上一页/跳转N"时，**必须调 paginate_results**。
        选择：用户说数字时，**必须调 select_search_result**。

        Args:
            game_name(string): 游戏名称（已自动去掉"游戏"后缀）
        """
        game_name = clean_search_keyword(game_name)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, game_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
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
            return f"{tag} 未找到与「{game_name}」相关的游戏。请尝试 search_resource 综合搜索。"
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
        final_txt = tag + f" 🎮 游戏搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt
        await event.send(MessageChain([Plain(final_txt)]))
        # 标记 _llm_handled 让 _strip_llm_chitchat_after_tool 清空 LLM 后续多嘴输出
        self._sessions.update(event, _llm_handled=True)
        logger.info(f"[暮黎资源] search_game('{game_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个游戏结果，当前第 1/{pt} 页。用户的下一步操作（翻页、选数字、选网盘）由 on_any_message 直接处理，无需 LLM 再调用工具。"

    @filter.llm_tool(name="search_software")
    async def llm_search_software(self, event: AstrMessageEvent, software_name: str):
        """专门搜索软件资源。当用户明确说"找软件"或软件关键词时调用。

        翻页：用户说"下一页/上一页/跳转N"时，**必须调 paginate_results**。
        选择：用户说数字时，**必须调 select_search_result**。

        Args:
            software_name(string): 软件名称（已自动去掉"软件""应用"后缀）
        """
        software_name = clean_search_keyword(software_name)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, software_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        ps = 8; tag = "【暮黎资源】"
        try: results = await asyncio.to_thread(search_software, software_name, 32)
        except Exception as e:
            logger.error(f"[暮黎资源] search_software('{software_name}') 失败: {e}")
            return f"{tag} 搜索失败：{str(e)[:100]}"
        if not results:
            logger.info(f"[暮黎资源] search_software('{software_name}') → 0条")
            return f"{tag} 未找到与「{software_name}」相关的资源。请尝试 search_resource 综合搜索。"
        existing = self._search_sessions.get(event)
        if existing and existing.get("keyword") == software_name:
            logger.info(f"[暮黎资源] search_software('{software_name}') → 复用已有会话")
        else:
            self._search_sessions.set(event, {"stage":"select_software","keyword":software_name,"results":results,
                                               "page":0,"page_size":ps,"selected_index":-1,"detail":None,"selected_link":None})
        t = len(results); pt = (t + ps - 1) // ps
        # ★v4 关键修复：工具自己直接发格式化页面（和翻页走同一条路径，风格 100% 一致）
        page_txt = self._format_sw_page(self._search_sessions.get(event))
        final_txt = tag + f" 💿 软件搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt
        await event.send(MessageChain([Plain(final_txt)]))
        # 标记 _llm_handled 让 _strip_llm_chitchat_after_tool 清空 LLM 后续多嘴输出
        self._search_sessions.update(event, _llm_handled=True)
        logger.info(f"[暮黎资源] search_software('{software_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个软件结果，当前第 1/{pt} 页。用户的下一步操作（翻页、选数字、选网盘）由 on_any_message 直接处理，无需 LLM 再调用工具。"

    @filter.llm_tool(name="search_movie")
    async def llm_search_movie(self, event: AstrMessageEvent, movie_name: str):
        """专门搜索影视资源。当用户说"找影视/我想看/观看/看电影"或提到影视名时调用。

        默认走教父.com 新站（需登录，含在线播放+网盘双模式）；可在插件配置 movie_source
        切换为 a123tv（旧站，仅在线播放线路）。

        流程（新站）：
        1. 搜索 → 列出结果（【类型·年份·评分】），让用户选序号
        2. 用户选影视 → 获取详情+资源 → 询问选 [1]在线播放 / [2]网盘资源
        3. 在线播放 → 列出节点 → 选节点 → 合并转发（标题+封面+简介+播放链接）
           网盘资源 → 列出网盘（分页）→ 选网盘 → 合并转发（标题+封面+简介+网盘链接）

        返回列表格式：每行 `[N] 影视名  【类型·年份】 ⭐评分`
        翻页：用户说"下一页/上一页/跳转N"时，**必须调 paginate_results**。
        选择：用户说数字时，由 on_any_message / select_search_result 直接处理（无需再调工具）。

        Args:
            movie_name(string): 影视名称（如"怪物"、"庆余年"、"星际穿越"）
        """
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, movie_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
        ps = 8; tag = "【暮黎资源】"
        # 影视源自动切换：配置了教父.com 账号密码 → 新站（在线播放+网盘）；
        # 未配置账号密码 → 自动回退 a123tv 旧站（仅在线播放）。
        # movie_source 配置若显式设为 "a123tv" 则强制旧站（向后兼容）。
        cfg = self._get_config()
        forced_a123 = (cfg.get("movie_source") or "").strip().lower() == "a123tv"
        client = self._get_muliy_client() if not forced_a123 else None
        if client:
            # ===== 新站流程 =====
            try:
                results = await asyncio.to_thread(client.search, movie_name, 24)
            except Exception as e:
                logger.error(f"[暮黎资源] search_movie(新站,'{movie_name}') 失败: {e}")
                return f"{tag} 影视搜索失败：{str(e)[:120]}"
            if not results:
                return f"{tag} 未找到与「{movie_name}」相关的影视。请换个关键词。"
            self._movie_sessions_new.set(event, {
                "stage": "select_movie_new", "keyword": movie_name,
                "results": results, "page": 0, "page_size": ps,
                "_updated": time.time(), "_llm_handled": True,
            })
            t = len(results); pt = (t + ps - 1) // ps
            page_txt = format_movie_list_new(results, movie_name, 0, ps)
            final_txt = tag + f" 🎬 影视搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt
            await event.send(MessageChain([Plain(final_txt)]))
            logger.info(f"[暮黎资源] search_movie(新站,'{movie_name}') → {len(results)}条 → 直接 send")
            return f"[已发送给用户] {len(results)} 个影视结果，当前第 1/{pt} 页。用户的下一步操作（选序号/翻页）由 on_any_message 直接处理。"

        # ===== 旧站 a123tv 流程（保留） =====
        try:
            results = await asyncio.to_thread(search_movies, movie_name, 24)
        except Exception as e:
            logger.error(f"[暮黎资源] search_movie('{movie_name}') 失败: {e}")
            return f"{tag} 影视搜索失败：{str(e)[:120]}"
        if not results:
            return f"{tag} 未找到与「{movie_name}」相关的影视。请换个关键词。"
        self._movie_sessions.set(event, {"stage": "select_movie", "keyword": movie_name,
                                         "results": results, "page": 0, "page_size": ps,
                                         "_updated": time.time(), "_llm_handled": True})
        t = len(results); pt = (t + ps - 1) // ps
        page_txt = self._format_mv_page(self._movie_sessions.get(event))
        final_txt = tag + f" 🎬 影视搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt
        await event.send(MessageChain([Plain(final_txt)]))
        logger.info(f"[暮黎资源] search_movie('{movie_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个影视结果，当前第 1/{pt} 页。用户的下一步操作（选序号/翻页）由 on_any_message 直接处理。"

    @filter.llm_tool(name="search_novel")
    async def llm_search_novel(self, event: AstrMessageEvent, novel_name: str):
        """专门搜索小说资源（so-novel 多源聚合）。**仅当用户明确要搜索/阅读/下载小说时**调用
        （如"找小说XX""搜小说XX""我想看小说XX""看小说XX""读小说XX"）。
        ⚠️ 介绍、宣传、公告、封面生成类话语里提到"小说"（如"新增小说搜索下载"）不算小说搜索，不要调用本工具。

        流程：
        1. 搜索 → 列出结果（每行：序号 + 书名 ；下一行：作者 ；再下一行：书源），
           让用户选序号
        2. 用户选小说 → 询问下载格式（TXT/EPUB/HTML/PDF）→ 插件拉取文件流以文件形式发送

        返回列表格式：每条 `[N] 书名` / `  👤 作者` / `  🏷️ 书源：xxx`
        翻页：用户说"下一页/上一页/跳转N"时，**必须调 paginate_results**。
        选择：用户说数字时，由 on_any_message / select_search_result 直接处理（无需再调工具）。

        Args:
            novel_name(string): 小说名称或作者名（如"斗破苍穹"、"我有一座冒险屋"、"天蚕土豆"）
        """
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, novel_name)
        if not allowed:
            return f"【暮黎资源】⚠️ {reason}"
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
        self._novel_sessions.set(event, {
            "keyword": novel_name, "results": results, "page": 0,
            "page_size": ps, "stage": "select_novel", "_updated": time.time(),
            "_llm_handled": True,
        })
        t = len(results); pt = (t + ps - 1) // ps
        page_txt = self._format_novel_page(self._novel_sessions.get(event))
        final_txt = tag + f" 📚 小说搜索结果（共 {t} 个，第 1/{pt} 页）：\n\n" + page_txt
        await event.send(MessageChain([Plain(final_txt)]))
        logger.info(f"[暮黎资源] search_novel('{novel_name}') → {len(results)}条 → 直接 send")
        return f"[已发送给用户] {len(results)} 个小说结果，当前第 1/{pt} 页。用户的下一步操作（选序号/翻页）由 on_any_message 直接处理。"

    # ==================== 新站影视会话状态机 ====================

    async def _handle_movie_new_selection(self, event: AstrMessageEvent, selection: str):
        """新站影视会话状态机：select_movie_new → select_res_type →
        select_play_node / select_pan → 合并转发。"""
        tag = "【暮黎资源】"
        ses = self._movie_sessions_new.get(event)
        if not ses:
            return f"{tag} 会话已失效，请重新搜索影视。"
        stage = ses.get("stage")
        text = selection.strip()
        client = self._get_muliy_client()
        if not client:
            self._movie_sessions_new.delete(event)
            return f"{tag} 新站客户端未配置，请在插件配置填写账号密码。"

        num0 = self._parse_natural_number(text)
        if num0 == 0 or text in ("取消", "不要", "不要了", "算了", "取消搜索"):
            self._movie_sessions_new.delete(event)
            await event.send(MessageChain([Plain(f"{tag} 已取消。")]))
            return f"{tag} 用户取消。"

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
                    await event.send(MessageChain([Plain(tag + f" 🎬 影视搜索结果（第 {new_page+1}/{pt} 页）：\n\n" + new_txt)]))
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
            if n_play == 0 and n_pan == 0:
                self._movie_sessions_new.delete(event)
                await event.send(MessageChain([Plain(f"{tag} 「{sel['title']}」暂无任何资源。")]))
                return f"{tag} 该影视暂无资源。"
            self._movie_sessions_new.set(event, {
                "stage": "select_res_type", "detail": detail, "resources": resources,
                "selected": sel, "page": 0, "_updated": time.time(), "_llm_handled": True,
            })
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
                await event.send(MessageChain([Plain(tag + "\n" + format_play_nodes(playlist))]))
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
                await event.send(MessageChain([Plain(tag + "\n" + format_pan_types(type_counts))]))
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
            await event.send(MessageChain([Plain(tag + "\n" + format_pan_list(panlist, 0, type_filter=sel_type))]))
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
            ep_end = node.get("ep_end", 0)
            if ep_end and ep_end > 1:
                # 剧集：让用户选集数
                self._movie_sessions_new.update(event, stage="select_episode_new",
                                                selected_node=node, _llm_handled=True)
                txt = f"📺 「{detail.get('name', '')}」共 {ep_end} 集\n" + "=" * 36 + "\n\n"
                txt += f"💬 请输入想看的集数（1-{ep_end}），例如「5」= 第5集\n"
                txt += "⏱️ 120秒无操作自动取消。回复 0 取消。"
                await event.send(MessageChain([Plain(tag + "\n" + txt)]))
                return f"{tag} 已发送选集提示（共{ep_end}集）。等待用户选集。"
            else:
                # 电影：直接获取 m3u8 直链
                await event.send(MessageChain([Plain(f"▶ 已选择：{node['t']}\n⏳ 正在获取播放直链...")]))
                link = await self._get_play_link(client, node["i"], 1)
                if not link:
                    await event.send(MessageChain([Plain(f"{tag} ❌ 获取播放直链失败，请稍后重试或换一个播放节点。")]))
                    self._movie_sessions_new.delete(event)
                    return f"{tag} 播放直链获取失败。"
                await self._send_movie_merged(event, detail, link, "在线播放(直链)")
                self._movie_sessions_new.delete(event)
                return f"{tag} 已发送「{detail.get('name', '')}」在线播放合并转发。"

        # ===== 阶段3a-2：选集（剧集）=====
        if stage == "select_episode_new":
            node = ses.get("selected_node", {})
            detail = ses.get("detail", {})
            ep_end = node.get("ep_end", 0)
            num = num0 if num0 != -2 else 1
            if num < 1 or (ep_end and num > ep_end):
                await event.send(MessageChain([Plain(f"{tag} 集数超出范围（1-{ep_end}），请重新输入。回复0取消。")]))
                self._movie_sessions_new.update(event, _llm_handled=True)
                return f"{tag} 集数超出范围。"
            await event.send(MessageChain([Plain(f"▶ 第 {num} 集\n⏳ 正在获取播放直链...")]))
            link = await self._get_play_link(client, node["i"], num)
            if not link:
                await event.send(MessageChain([Plain(f"{tag} ❌ 获取播放直链失败，请稍后重试或换一个播放节点。")]))
                self._movie_sessions_new.delete(event)
                return f"{tag} 播放直链获取失败。"
            await self._send_movie_merged(event, detail, link, f"在线播放(第{num}集直链)")
            self._movie_sessions_new.delete(event)
            return f"{tag} 已发送「{detail.get('name', '')}」第{num}集在线播放合并转发。"

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
                    await event.send(MessageChain([Plain(tag + "\n" + format_pan_list(panlist, new_page, type_filter=sel_type))]))
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
            await event.send(MessageChain([Plain(f"📁 已选择：{pan.get('type', '')} - {pan.get('name', '')[:30]}{pwd_hint}\n⏳ 正在生成资源卡片...")]))
            await self._send_movie_merged(event, detail, link, "网盘下载")
            self._movie_sessions_new.delete(event)
            return f"{tag} 已发送「{detail.get('name', '')}」网盘合并转发。"

        return f"{tag} 未知会话状态，请重新搜索。"

    async def _send_movie_merged(self, event: AstrMessageEvent, detail: dict,
                                 link: str, link_label: str):
        """新站影视合并转发：标题+封面+简介+链接。群聊用 Nodes，私聊降级文本+图片。

        封面图先 HEAD 验证可达性，404 则跳过避免拖垮整个合并转发；
        合并转发整体 try-except，失败降级纯文本。
        """
        text = build_merged_text(detail, link, link_label)
        cover = detail.get("cover", "")
        gid = event.get_group_id()
        sid = event.get_self_id()
        # 封面可达性验证（HEAD 不可靠，用 GET stream；避免 404 拖垮合并转发）
        if cover and requests:
            try:
                _r = requests.get(cover, timeout=6, verify=False, stream=True)
                _ok = _r.status_code == 200 and "image" in (_r.headers.get("content-type", ""))
                _r.close()
                if not _ok:
                    logger.warning(f"[暮黎资源] 封面不可达 {cover} status={_r.status_code}，跳过封面")
                    cover = ""
            except Exception as e:
                logger.warning(f"[暮黎资源] 封面验证失败: {e}，跳过封面")
                cover = ""
        if gid and Nodes and Node:
            nd = Nodes([])
            nd.nodes.append(Node(uin=sid, name="暮黎影视", content=[Plain(text)]))
            if cover:
                nd.nodes.append(Node(uin=sid, name="暮黎影视", content=[ImageComponent(file=cover)]))
            try:
                await event.send(MessageChain([nd]))
                logger.info(f"[暮黎资源] 新站影视合并转发已发送 (gid={gid} cover={'有' if cover else '无'})")
            except Exception as e:
                # 合并转发失败 → 降级纯文本（可能图片节点导致）
                logger.error(f"[暮黎资源] 合并转发失败，降级纯文本: {e}")
                try:
                    await event.send(MessageChain([Plain(text)]))
                except Exception as e2:
                    logger.error(f"[暮黎资源] 降级纯文本也失败: {e2}")
        else:
            await event.send(MessageChain([Plain(text)]))
            if cover:
                try:
                    await event.send(MessageChain([ImageComponent(file=cover)]))
                except Exception as e:
                    logger.warning(f"[暮黎资源] 私聊封面发送失败: {e}")

    async def _get_play_link(self, client, node_i: str, ep: int) -> str:
        """健壮获取播放直链：先取，失败则强制刷新登录再取一次。
        返回空串表示确实拿不到（调用方应提示用户，而非发登录墙网站链接）。"""
        m3u8 = await asyncio.to_thread(client.get_play_m3u8, node_i, ep)
        if m3u8:
            return m3u8
        logger.warning("[暮黎资源] 首次取 m3u8 失败，强制刷新登录重试")
        client._relogin_on_fail()
        return await asyncio.to_thread(client.get_play_m3u8, node_i, ep)

    @filter.llm_tool(name="paginate_results")
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
            await event.send(MessageChain([Plain(final_txt)]))
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
            await event.send(MessageChain([Plain(final_txt)]))
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
            await event.send(MessageChain([Plain(final_txt)]))
            self._movie_sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 翻页 影视 第{cur+1}→{new_page+1}页 (共{t}条) → 直接 send")
            return f"[已发送给用户] 第 {new_page+1}/{pt} 页，共 {t} 个结果。用户后续操作由 on_any_message 处理。"

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
            else:
                page_txt = format_pan_list(r, new_page, type_filter=sel_type)
            await event.send(MessageChain([Plain(tag + "\n" + page_txt)]))
            logger.info(f"[暮黎资源] 翻页 新站影视 第{cur+1}→{new_page+1}页")
            return f"[已发送给用户] 第 {new_page+1}/{pt} 页。用户后续操作由 on_any_message 处理。"

        return f"{tag} 当前没有活跃的搜索结果会话，无法翻页。请先调 search_resource / search_game / search_software / search_movie 搜索。"

    @filter.llm_tool(name="select_search_result")
    async def llm_select_search_result(self, event: AstrMessageEvent, selection: str):
        """用户选择搜索结果后调用，获取资源详情和下载链接。

        Args:
            selection(string): 用户的选择（数字如"1"、"2"，或"第一个"、"第二个"等中文序数）
        """
        tag = "【暮黎资源】"
        # ★新站影视会话（教父.com）：独立状态机，优先处理
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
            links = detail["download_links"]
            txt = (tag + " 📦 " + (detail.get("name") or sel["title"]) + "\n" + "="*30 +
                   f"\n共 {len(links)} 个下载链接：\n\n")
            for i, lk in enumerate(links, 1):
                txt += f"{emoji_index(i, len(links))} {GAME_PAN_ICONS.get(lk['pan'],'📥')} {lk['pan']}\n"
            txt += f"\n请回复数字或网盘名选择（1-{len(links)}），回复0取消。"
            await event.send(MessageChain([Plain(txt)]))
            self._sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 游戏 '{sel['title']}' → {len(links)}个下载链接")
            return f"{tag} 已发送{len(links)}个下载链接给用户。请等待用户回复数字或网盘名，**不要**自行调用 select_download_link。"

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
            links = detail["download_links"]
            txt = (tag + " 📦 " + (detail.get("name") or sel["title"]) + "\n" + "="*30 +
                   f"\n共 {len(links)} 个下载链接：\n\n")
            for i, lk in enumerate(links, 1):
                txt += f"{emoji_index(i, len(links))} {SW_DISK_ICONS.get(lk['pan'],'📥')} {lk['pan']}\n"
            txt += f"\n请回复数字或网盘名选择（1-{len(links)}），回复0取消。"
            await event.send(MessageChain([Plain(txt)]))
            self._search_sessions.update(event, _llm_handled=True)
            logger.info(f"[暮黎资源] 软件 '{sel['title']}' → {len(links)}个下载链接")
            return f"{tag} 已发送{len(links)}个下载链接给用户。请等待用户回复数字或网盘名，**不要**自行调用 select_download_link。"

        logger.warning(f"[暮黎资源] select_search_result({number}) → 无活跃会话")
        return f"{tag} 当前没有活跃的搜索结果。请先使用 search_resource 搜索，或回复0取消。"

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
            gid = event.get_group_id(); uid = event.get_sender_id()
            logger.info(f"[暮黎资源] 发送资源 '{gn}' → {rlink.get('pan','?')} gid={gid} uid={uid}")
            if gid:
                await self._send_sw_merged(event, gn, detail, rlink, GAME_PAN_ICONS, GAME_BASE_URL, "暮黎游戏搜索", gid, "g_")
                self._sessions.delete(event)
                return f"{tag} 已发送「{gn}」合并转发资源到群。"
            elif uid:
                safe_name = re.sub(r'[\\/:*?"<>|]',"_",gn)[:30]
                hc = await asyncio.to_thread(generate_game_html, gn, detail.get("desc","") or "",
                                               detail.get("cover","") or "",
                                               detail.get("screenshots",[]) or [], rlink, ses["keyword"])
                fd, tp = tempfile.mkstemp(suffix=f"_{safe_name}.html",prefix="g_"); os.close(fd)
                with open(tp,"w",encoding="utf-8") as f: f.write(hc)
                fn = f"{gn[:30]}.html"; cl = self._get_best_client(event)
                logger.info(f"[暮黎资源] 私聊HTML: {fn}")
                if cl:
                    with open(tp,"rb") as f: b64 = base64.b64encode(f.read()).decode("utf-8")
                    if str(uid).isdigit(): await cl.call_action(action="upload_private_file",user_id=int(uid),file=f"base64://{b64}",name=fn)
                    else: await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}",MessageChain([FileComponent(file=tp,name=fn)]))
                else: await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}",MessageChain([Plain(f"📄 {gn}\n\n"),FileComponent(file=tp,name=fn)]))
                if os.path.exists(tp):
                    try: os.unlink(tp)
                    except Exception: pass
                self._sessions.delete(event)
                return f"{tag} 已发送「{gn}」的资源文件到私聊。"
            self._sessions.delete(event)
            return f"{tag} 无法确定发送目标。"

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
            gid = event.get_group_id(); uid = event.get_sender_id()
            logger.info(f"[暮黎资源] 发送软件 '{sn}' → {sl['pan']} gid={gid} uid={uid}")
            if gid:
                await self._send_sw_merged(event, sn, detail, sl, SW_DISK_ICONS, SW_BASE_URL, "暮黎软件搜索", gid, "sw_")
                self._search_sessions.delete(event)
                return f"{tag} 已发送「{sn}」合并转发资源到群。"
            elif uid:
                safe_name = re.sub(r'[\\/:*?"<>|]',"_",sn)[:30]
                hc = await asyncio.to_thread(generate_search_html, sn, detail.get("desc","") or "",
                                               detail.get("cover","") or "",
                                               detail.get("screenshots",[]) or [], sl, ses2["keyword"])
                fd, tp = tempfile.mkstemp(suffix=f"_{safe_name}.html",prefix="sw_"); os.close(fd)
                with open(tp,"w",encoding="utf-8") as f: f.write(hc)
                fn = f"{sn[:30]}.html"; cl = self._get_best_client(event)
                logger.info(f"[暮黎资源] 私聊HTML: {fn}")
                if cl:
                    with open(tp,"rb") as f: b64 = base64.b64encode(f.read()).decode("utf-8")
                    if str(uid).isdigit(): await cl.call_action(action="upload_private_file",user_id=int(uid),file=f"base64://{b64}",name=fn)
                    else: await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}",MessageChain([FileComponent(file=tp,name=fn)]))
                else: await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}",MessageChain([Plain(f"📄 {sn}\n\n"),FileComponent(file=tp,name=fn)]))
                if os.path.exists(tp):
                    try: os.unlink(tp)
                    except Exception: pass
                self._search_sessions.delete(event)
                return f"{tag} 已发送「{sn}」的资源文件到私聊。"
            self._search_sessions.delete(event)
            return f"{tag} 无法确定发送目标。"

        logger.warning(f"[暮黎资源] select_download_link('{selection}') → 无活跃会话")
        return f"{tag} 当前没有活跃的下载选择会话。请先搜索并选择资源，或回复0取消。"

    async def _send_sw_merged(self, event, name: str, detail: dict, link: dict, icons: dict, referer: str, source_name: str, gid: str, prefix: str):
        """合并转发：标题文字 + 截图列表，私聊用 HTML 文件。"""
        tag = "【暮黎资源】"
        t2 = (tag + " 📦 " + name + "\n📖 " + (detail.get("desc","暂无简介") or "暂无简介")[:400] +
              "\n📥 " + icons.get(link["pan"],"📥") + " " + link["pan"] +
              "\n🔗 " + (link.get("real_url") or link.get("url","")))
        if link.get("code"): t2 += "\n🔑 提取码: " + link["code"]
        if Nodes and Node:
            sid = event.get_self_id(); nd = Nodes([]); nd.nodes.append(Node(uin=sid, name=source_name, content=[Plain(t2)]))
            imgs = []
            for u in (detail.get("screenshots") or []):
                try:
                    ir = requests.get(u, headers={"User-Agent":"Mozilla/5.0","Referer":referer+"/"}, timeout=15)
                    if ir.status_code == 200:
                        fd2, ip = tempfile.mkstemp(suffix=".jpg", prefix=prefix); os.close(fd2)
                        with open(ip,"wb") as f: f.write(ir.content)
                        imgs.append(ip)
                        nd.nodes.append(Node(uin=sid, name=source_name, content=[ImageComponent(file=ip)]))
                except Exception: pass
            logger.info(f"[暮黎资源] 合并转发 +{len(imgs)}张截图")
            await event.send(MessageChain([nd]))
            for p in imgs:
                try: os.unlink(p)
                except Exception: pass
        else:
            await event.send(MessageChain([Plain(t2)]))

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
        """影视搜索（a123tv.com）— 自动登录态 + 一步走选节点。"""
        keyword = event.message_str.strip()
        keyword = re.sub(r"^/?找影视\s*", "", keyword)
        # —— 关键词审核：大模型判定涉黄/违禁，命中则拦截，不执行搜索 ——
        allowed, reason, _ = await self._audit_search_keyword(event, keyword)
        if not allowed:
            yield event.plain_result(f"⚠️ {reason}"); return
        logger.info(f"影视搜索: 关键词=[{keyword}]")
        if not keyword:
            yield event.plain_result("请发送：/找影视 <影视名>"); return
        if not requests:
            yield event.plain_result("❌ 缺少 requests"); return
        if not BeautifulSoup:
            yield event.plain_result("❌ 缺少 beautifulsoup4"); return
        async for result in self._run_movie_search_flow(event, keyword):
            yield result

    @filter.command("movie_status")
    async def cmd_movie_status(self, event: AstrMessageEvent):
        """检查 a123tv.com 是否可达 + 当前搜索状态。"""
        try:
            r = requests.get(MV_BASE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            ok = r.status_code == 200 and "A123TV" in r.text
            if ok:
                yield event.plain_result(
                    f"✅ a123tv.com 状态：可访问\n"
                    f"🌐 {MV_BASE_URL}\n"
                    f"📋 HTTP {r.status_code}  响应 {len(r.text)//1024}KB\n"
                    f"🟢 影视搜索可用，无需登录。"
                )
            else:
                yield event.plain_result(
                    f"❌ a123tv.com 状态：异常\n"
                    f"📋 HTTP {r.status_code}  响应 {len(r.text)}B\n"
                    f"💡 站点可能下线或被 Cloudflare 拦截，请稍后重试。"
                )
        except Exception as e:
            yield event.plain_result(f"❌ a123tv.com 不可达：{str(e)[:120]}")

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
        sep = "────────────"
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
        yield event.plain_result(self._format_novel_page(self._novel_sessions.get(event)))

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
        刷新 xdgame.com Cookie（仅 AstrBot 管理员可用）：
        1. 从插件配置读取账号密码
        2. 自动填入账密登录
        3. 有验证码 → 发图让你输入 → 自动提交
        4. 登录成功后自动更新 Cookie 配置

        ⚠️ 首次使用需先在 WebUI 插件设置中填写 xdgame_username 和 xdgame_password
        """
        gid = event.get_group_id()
        uid_full = event.get_sender_id()
        pid = event.get_platform_id()
        target = f"{pid}:GroupMessage:{gid}" if gid else f"{pid}:FriendMessage:{uid_full}"

        # ——— 读取配置中的账密 ———
        config = self._get_config()
        username = (config.get("xdgame_username") or "").strip()
        password = (config.get("xdgame_password") or "").strip()

        if not username or not password:
            await self._run_switch618_login_flow(event, target)
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
            # === DEBUG H4/H2: 入参与提取 ===
            _dbg_log("H2", "_handle_login_result 入参", {
                "input_n": len(cookies),
                "input_names": list(cookies.keys()),
                "xd_nick": xd_nick,
            })
            _dbg_log("H2", "extract_xdgame_cookies 后", {
                "filtered_keys": list(extract_xdgame_cookies(cookies).keys()),
                "cookie_str_len": len(cookie_str),
                "cookie_str_preview": cookie_str[:200],
            })
            if cookie_str:
                await self._update_config("cookie", cookie_str)
                # === DEBUG H4: 验证持久化真的写入了 ===
                saved = self._get_config().get("cookie", "")
                _dbg_log("H4", "_update_config 后回读", {
                    "saved_len": len(saved),
                    "saved_first60": saved[:60],
                    "saved_has_DedeUserID": "DedeUserID" in saved,
                })
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
        font_path = os.path.join(os.path.dirname(__file__), "SourceHanSansCN-Heavy.otf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[软件日报] 开始渲染，共 {len(sws)} 款，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_html_to_png, html, font_path, 720, channel, exe)
            logger.info(f"[软件日报] 渲染完成，原始图片体积 {len(img_bytes)//1024}KB")
        except Exception as e:
            logger.error(f"[软件日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
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
                yield event.plain_result("⚠️ 日报图片发送失败，请确认已执行 playwright install chromium。")
        else:
            yield event.plain_result("⚠️ 日报图片渲染失败，请确认已执行 playwright install chromium。")

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
                        j = sch.get_job(jid)
                        if j and j.next_run_time: return j.next_run_time.strftime("%Y-%m-%d %H:%M")
                elif self._apscheduler:
                    j = self._apscheduler.get_job(jid)
                    if j and j.next_run_time: return j.next_run_time.strftime("%Y-%m-%d %H:%M")
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
        yield event.plain_result(
            f"📊 暮黎资源聚合\n{'='*30}\n"
            f"🌍 时区: {tz} | 调度: {'✅' if sk else '❌'} | 模式: {mode}\n"
            f"📦 软件日报: 每日 {h:02d}:{m:02d} | 群{len(groups)}个 | 上次:{lr} | 下次:{nxt}\n"
            f"🎮 游戏日报: {'✅开' if gen else '❌关'} 每日 {gh:02d}:{gm:02d} | 群{len(ggroups)}个{'（共享）' if gfb else ''} | 上限{gmx}\n"
            f"   上次:{glr} | 下次:{gnxt}\n"
            f"🎬 影视日报: {'✅开' if men else '❌关'} 每日 {int(mh):02d}:{int(mm):02d} | 群{len(mgroups)}个{'（共享）' if mfb else ''} | 上限{mmx}\n"
            f"   区块:{msec} | 上次:{mlr} | 下次:{mnxt}\n"
            f"🖼️ 软件图片: {'是' if ei else '否'} | 软件上限: {mx}\n"
            f"⚡ 命令: /找软件 | /找游戏 | /game_report | /movie_report")

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
        lines.append("─" * 36)
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
        lines.append("─" * 36)
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
        lines.append("─" * 36)
        nav = []
        if st > 0: nav.append("「上一页」")
        if ed < t: nav.append("「下一页」")
        if pt > 1: nav.append(f"「跳转 1~{pt}」")
        if nav:
            lines.append("💡 翻页指令： " + " ｜ ".join(nav))
        lines.append(f"⏱️ {SESSION_TIMEOUT}秒无操作自动取消。")
        lines.append("回复数字选择影视，回复0取消。")
        return "\n".join(lines)

    # ==================== 游戏搜索交互流程 (session_waiter) ====================

    async def _run_game_search_flow(self, event: AstrMessageEvent, keyword: str):
        """完整的游戏搜索交互流程（async generator）。
        使用 session_waiter 拦截后续用户输入，阻止 AngelHeart 介入。"""
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
                    yield event.plain_result(f"🎮 游戏库未找到「{keyword}」，但在软件库找到：\n\n" + self._format_sw_page(s))
                    self._search_sessions.set(event, {"stage": "select_software", **s})
                    return
                yield event.plain_result(f"😕 未找到「{keyword}」的游戏或软件资源。")
                return
            s = {"keyword": keyword, "results": results, "page": 0, "page_size": 8}
            yield event.plain_result(self._format_game_page(s))
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
        yield event.plain_result(self._format_game_page(session))

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
                await ev.send(MessageChain([Plain(self._format_game_page(session))]))
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
                        await ev.send(MessageChain([Plain(self._format_game_page(session))]))
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

            # 展示下载链接列表
            links = game_detail["download_links"]
            txt = ("📦 " + (game_detail.get("name") or selected_game["title"]) + "\n" +
                   "=" * 30 + f"\n找到 {len(links)} 个下载链接：\n\n")
            for i, lk in enumerate(links, 1):
                extra = ""
                if lk.get("code"):
                    extra += f"  提取码:{lk['code']}"
                if lk.get("password"):
                    extra += f"  游戏密码:{lk['password']}"
                txt += f"{emoji_index(i, len(links))} {GAME_PAN_ICONS.get(lk['pan'], '📥')} {lk['pan']}{extra}\n"
            txt += f"\n请直接回复数字选择下载链接（1-{len(links)}），回复 0 取消。"
            await ev.send(MessageChain([Plain(txt)]))
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
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", gn)[:30]
            gid = ev.get_group_id()
            uid = ev.get_sender_id()
            logger.info(f"[执行] 游戏 {gn} gid={gid} uid={uid} url={rlink.get('real_url', '')[:40]}")

            if gid:
                t2 = ("📦 " + gn + "\n📖 " + (game_detail.get("desc", "暂无简介") or "暂无简介")[:400] +
                      "\n📥 " + GAME_PAN_ICONS.get(rlink["pan"], "📥") + " " + rlink["pan"] +
                      "\n" + rlink.get("real_url", ""))
                if rlink.get("code"):
                    t2 += "  提取码: " + rlink["code"]
                await self._send_game_group_msg(ev, gn, game_detail, rlink, t2)
            elif uid:
                await self._send_game_private_msg(ev, gn, game_detail, rlink, keyword, safe_name, uid)

            selected_link = rlink
            controller.stop()

        try:
            await _link_waiter(event)
        except TimeoutError:
            yield event.plain_result("⏰ 选择超时，已自动取消。")

    async def _send_game_group_msg(self, event, gn, detail, rlink, text_content):
        """在群聊中发送游戏下载信息（合并转发或纯文本）"""
        if Nodes and Node:
            sid = event.get_self_id()
            nd = Nodes([])
            nd.nodes.append(Node(uin=sid, name="暮黎游戏搜索", content=[Plain(text_content)]))
            imgs = []
            for u in (detail.get("screenshots") or []):
                try:
                    ir = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Referer": GAME_BASE_URL + "/"}, timeout=15)
                    if ir.status_code == 200:
                        fd2, ip = tempfile.mkstemp(suffix=".jpg", prefix="g_")
                        os.close(fd2)
                        with open(ip, "wb") as f:
                            f.write(ir.content)
                        imgs.append(ip)
                        nd.nodes.append(Node(uin=sid, name="暮黎游戏搜索", content=[ImageComponent(file=ip)]))
                except Exception:
                    pass
            logger.info(f"[执行] 群聊合并转发 +{len(imgs)}张截图")
            await event.send(MessageChain([nd]))
            for p in imgs:
                try:
                    os.unlink(p)
                except Exception:
                    pass
        else:
            await event.send(MessageChain([Plain(text_content)]))

    async def _send_game_private_msg(self, event, gn, detail, rlink, keyword, safe_name, uid):
        """在私聊中发送游戏 HTML 文件"""
        hc = await asyncio.to_thread(
            generate_game_html, gn,
            detail.get("desc", "") or "",
            detail.get("cover", "") or "",
            detail.get("screenshots", []) or [],
            rlink, keyword
        )
        fd, tp = tempfile.mkstemp(suffix=f"_{safe_name}.html", prefix="g_")
        os.close(fd)
        with open(tp, "w", encoding="utf-8") as f:
            f.write(hc)
        fn = f"{gn[:30]}.html"
        cl = self._get_best_client(event)
        logger.info(f"[执行] 私聊HTML {fn}")
        if cl:
            with open(tp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            if str(uid).isdigit():
                await cl.call_action(action="upload_private_file", user_id=int(uid), file=f"base64://{b64}", name=fn)
            else:
                await self.context.send_message(
                    f"{event.get_platform_id()}:FriendMessage:{uid}",
                    MessageChain([FileComponent(file=tp, name=fn)])
                )
        else:
            await self.context.send_message(
                f"{event.get_platform_id()}:FriendMessage:{uid}",
                MessageChain([Plain(f"📄 {gn}\n\n"), FileComponent(file=tp, name=fn)])
            )
        if os.path.exists(tp):
            try:
                os.unlink(tp)
            except Exception:
                pass

    # ==================== 软件搜索交互流程 (session_waiter) ====================

    async def _run_software_search_flow(self, event: AstrMessageEvent, keyword: str):
        """完整的软件搜索交互流程（async generator）。"""
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
                    yield event.plain_result(f"💿 软件库未找到「{keyword}」，但在游戏库找到：\n\n" + self._format_game_page(s))
                    self._sessions.set(event, {"stage": "select_game", **s})
                    return
                yield event.plain_result(f"😕 未找到「{keyword}」的软件或游戏资源。")
                return
            s = {"keyword": keyword, "results": results, "page": 0, "page_size": 8}
            yield event.plain_result(self._format_sw_page(s))
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
        yield event.plain_result(self._format_sw_page(session))

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
                await ev.send(MessageChain([Plain(self._format_sw_page(session))]))
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
                        await ev.send(MessageChain([Plain(self._format_sw_page(session))]))
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

            links = sw_detail["download_links"]
            txt = ("📦 " + (sw_detail.get("name") or selected_sw["title"]) + "\n" +
                   "=" * 30 + f"\n找到 {len(links)} 个下载链接：\n\n")
            for i, lk in enumerate(links, 1):
                txt += f"{emoji_index(i, len(links))} {SW_DISK_ICONS.get(lk['pan'], '📥')} {lk['pan']}\n"
            txt += f"\n请直接回复数字选择下载链接（1-{len(links)}），回复 0 取消。"
            await ev.send(MessageChain([Plain(txt)]))
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
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", sn)[:30]
            gid = ev.get_group_id()
            uid = ev.get_sender_id()
            logger.info(f"[执行] 软件 {sn} gid={gid} uid={uid}")

            if gid:
                t2 = ("📦 " + sn + "\n📖 " + (sw_detail.get("desc", "暂无简介") or "暂无简介")[:400] +
                      "\n📥 " + SW_DISK_ICONS.get(sl["pan"], "📥") + " " + sl["pan"] +
                      "\n" + (sl.get("url", "")))
                if Nodes and Node:
                    sid = ev.get_self_id()
                    nd = Nodes([])
                    nd.nodes.append(Node(uin=sid, name="暮黎软件搜索", content=[Plain(t2)]))
                    imgs = []
                    for u in (sw_detail.get("screenshots") or []):
                        try:
                            ir = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Referer": SW_BASE_URL + "/"}, timeout=15)
                            if ir.status_code == 200:
                                fd2, ip = tempfile.mkstemp(suffix=".jpg", prefix="sw_")
                                os.close(fd2)
                                with open(ip, "wb") as f:
                                    f.write(ir.content)
                                imgs.append(ip)
                                nd.nodes.append(Node(uin=sid, name="暮黎软件搜索", content=[ImageComponent(file=ip)]))
                        except Exception:
                            pass
                    logger.info(f"[执行] 群聊合并转发 +{len(imgs)}张截图")
                    await ev.send(MessageChain([nd]))
                    for p in imgs:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass
                else:
                    await ev.send(MessageChain([Plain(t2)]))
            elif uid:
                hc = await asyncio.to_thread(
                    generate_search_html, sn,
                    sw_detail.get("desc", "") or "",
                    sw_detail.get("cover", "") or "",
                    sw_detail.get("screenshots", []) or [],
                    sl, keyword
                )
                fd, tp = tempfile.mkstemp(suffix=f"_{safe_name}.html", prefix="sw_")
                os.close(fd)
                with open(tp, "w", encoding="utf-8") as f:
                    f.write(hc)
                fn = f"{sn[:30]}.html"
                cl = self._get_best_client(ev)
                logger.info(f"[执行] 私聊HTML {fn}")
                if cl:
                    with open(tp, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    if str(uid).isdigit():
                        await cl.call_action(action="upload_private_file", user_id=int(uid), file=f"base64://{b64}", name=fn)
                    else:
                        await self.context.send_message(
                            f"{ev.get_platform_id()}:FriendMessage:{uid}",
                            MessageChain([FileComponent(file=tp, name=fn)])
                        )
                else:
                    await self.context.send_message(
                        f"{ev.get_platform_id()}:FriendMessage:{uid}",
                        MessageChain([Plain(f"📄 {sn}\n\n"), FileComponent(file=tp, name=fn)])
                    )
                if os.path.exists(tp):
                    try:
                        os.unlink(tp)
                    except Exception:
                        pass

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
        yield event.plain_result(self._format_mv_page(session))

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
                await ev.send(MessageChain([Plain(self._format_mv_page(session))]))
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
                        await ev.send(MessageChain([Plain(self._format_mv_page(session))]))
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
            t2 = (
                f"🎬 {name}{ep_tag}\n"
                f"📡 {line_name}\n"
                + (f"🎭 主演：{cast}\n" if cast else "")
                + (f"📖 {desc[:200]}\n" if desc else "")
                + f"🔗 {chosen_url}"
            )
            if Nodes and Node:
                sid = event.get_self_id()
                nd = Nodes([])
                nd.nodes.append(Node(uin=sid, name="暮黎影视搜索", content=[Plain(t2)]))
                # 封面图（依然从 detail 拿，跟原流程一致）
                detail_obj = self._movie_sessions.get(event)
                detail = detail_obj.get("detail", {}) if detail_obj else {}
                cover = detail.get("cover") or ""
                if cover:
                    try:
                        ir = requests.get(cover, headers={"User-Agent": "Mozilla/5.0",
                                                          "Referer": MV_BASE_URL + "/"}, timeout=15)
                        if ir.status_code == 200:
                            fd2, ip = tempfile.mkstemp(suffix=".jpg", prefix="mv_")
                            os.close(fd2)
                            with open(ip, "wb") as f:
                                f.write(ir.content)
                            nd.nodes.append(Node(uin=sid, name="暮黎影视搜索",
                                                 content=[ImageComponent(file=ip)]))
                            await event.send(MessageChain([nd]))
                            try: os.unlink(ip)
                            except Exception: pass
                        else:
                            await event.send(MessageChain([Plain(t2)]))
                    except Exception:
                        await event.send(MessageChain([Plain(t2)]))
                else:
                    await event.send(MessageChain([Plain(t2)]))
            else:
                await event.send(MessageChain([Plain(t2)]))
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
            sel = text.strip()
            if re.fullmatch(r"\d{1,2}", sel):
                await self._handle_vip_selection(event, umo, int(sel))
            elif sel in ("/cancel", "取消", "cancel"):
                self._vip_pending.pop(umo, None)
                await event.send(MessageChain([Plain("已取消 VIP 解析。")]))
            else:
                await event.send(MessageChain([Plain("请回复要使用的解析接口序号（1-N），或发送 /cancel 取消。")]))
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

    def _get_interfaces(self, cfg: dict) -> list:
        """返回 [(名字, 模板), ...]。固定使用内置默认接口列表（video_vip_parser_urls 配置已移除）。"""
        return list(VIP_INTERFACES)

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
                r = resolve_iqiyi_share(link, proxy=proxy)
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
            normalized = normalize_video_url(link, proxy=proxy)
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

        # OG 没取到标题 → 浏览器兜底（优酷等可能需要）
        if not title:
            try:
                info = await analyze_vip_link(link, proxy=proxy, timeout_ms=timeout,
                                              channel=channel, exe=exe)
                if info.get("title"):
                    title = info["title"]
                if info.get("poster_url") and not cover:
                    cover = info["poster_url"]
            except Exception as e:  # noqa: BLE001
                logger.error(f"[VIP] 浏览器分析异常: {e}")

        interfaces = self._get_interfaces(cfg)
        umo = event.unified_msg_origin
        self._vip_pending[umo] = {
            "clean_url": link,
            "raw": link,
            "title": title,
            "desc": desc,
            "poster_url": cover,
            "poster_path": "",
            "resolved": True,
            "ts": time.time(),
        }

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
            lines.append(f"  {emoji_index(i, len(interfaces))} {name}")
        lines.append("")
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
            }, timeout=10, verify=False, proxies=proxies)
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

    async def _handle_vip_selection(self, event, umo: str, idx: int):
        """用户选了第 idx 个接口 → 校验 → 发送聊天记录格式结果。"""
        pending = self._vip_pending.pop(umo, None)
        if not pending:
            return
        cfg = self._get_config()
        interfaces = self._get_interfaces(cfg)
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

        # 直接发送解析结果（不做浏览器验证 — 接口就是 url+视频链接，验证没意义且慢）
        title = pending.get("title", "")
        desc = pending.get("desc", "")
        poster = pending.get("poster_url") or pending.get("poster_path")
        sid = event.get_self_id()
        gid = event.get_group_id()
        tlines = [
            "✅ VIP 解析完成",
            f"🎬 标题：{title}" if title else "🎬 标题：（未知）",
        ]
        if desc:
            tlines.append(f"📝 简介：{desc[:300]}")
        tlines.append(f"🛰️ 接口：{name}")
        tlines.append(f"🎞️ 解析直链（浏览器/播放器打开即看）：")
        tlines.append(play_url)
        text_node = Plain("\n".join(tlines))

        # 合并转发（聊天记录格式）：文本 + 封面图
        if gid and Nodes and Node and poster:
            nd = Nodes([])
            nd.nodes.append(Node(uin=sid, name="暮黎影视解析", content=[text_node]))
            nd.nodes.append(Node(uin=sid, name="暮黎影视解析", content=[ImageComponent(file=poster)]))
            try:
                await event.send(MessageChain([nd]))
                return
            except Exception as e:  # noqa: BLE001
                logger.error(f"[VIP] 合并转发失败，降级普通消息: {e}")
        # 降级：普通消息（文本 + 图片）
        chain = [text_node]
        if poster:
            try:
                chain.append(ImageComponent(file=poster))
            except Exception:
                pass
        await event.send(MessageChain(chain))

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
        base = normalize_api_base(cfg.get("wyy_custom_url") or "")
        if not base:
            await event.send(MessageChain([Plain(
                "❌ 未配置 wyy_custom_url（自建 NeteaseCloudMusicApi 实例地址）。\n"
                "请先在插件配置填写 wyy_custom_url，并确保该实例已运行。\n"
                "部署见插件 tools/netease-api/ 目录。")]))
            return

        await event.send(MessageChain([Plain("🔳 正在获取网易云登录二维码，请稍候…")]))
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
        # 后台轮询，不阻塞命令返回
        asyncio.create_task(self._wyy_login_poll(event, base, key))

    async def _wyy_login_poll(self, event: AstrMessageEvent, base: str, key: str):
        """后台轮询扫码状态，code=803 时提取会员 Cookie 写入 wyy_cookie。"""
        last_tip = ""
        for _ in range(60):  # 60 * 2s = 120s
            await asyncio.sleep(2)
            try:
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
                    await event.send(MessageChain([Plain("⚠️ 扫码成功但未提取到会员 Cookie，请检查实例返回。")]))
                    return
                await self._update_config("wyy_cookie", music_cookie)
                nick = ""
                try:
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
                f"请确认已在插件配置中填写 wyy_custom_url（自建 NeteaseCloudMusicApi 实例地址），\n"
                f"部署见插件 tools/netease-api/docker-compose.yml。")]))
            return

        tmp_mp3 = None
        clip_path = None
        try:
            # 下载
            try:
                tmp_mp3 = await download_mp3(info["url"])
            except Exception as e:
                logger.warning(f"[网易云] 下载失败: {e}")
                await event.send(MessageChain([Plain(f"❌ 音频下载失败：{str(e)[:120]}")]))
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

    @filter.event_message_type(filter.EventMessageType.ALL, priority=999999)
    async def on_any_message(self, event: AstrMessageEvent):
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

        # ── 通用关键词 ──
        page_kw = ("下一页", "上一页")
        jump_kw = ("跳转", "跳到")
        cancel_kw = ("0", "取消", "算", "不要", "no")
        num_kw = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")

        # ══════════════════════════════════════════════
        # 残留会话自动清理（issue2 修复）
        # 若当前消息不是任何活跃会话的有效操作（翻页/选号/取消/网盘名），
        # 视为新意图，清理所有残留会话后放行给 LLM，避免“还要发0手动取消”的死循环。
        # ══════════════════════════════════════════════
        sel_like = (
            text in cancel_kw or text in page_kw
            or text.startswith("下一页") or text.startswith("上一页")
            or text.startswith("跳") or text in num_kw
            or text.startswith("第") or text.startswith("选") or text.startswith("最后")
            or any(k in text for k in ("夸克", "百度", "天翼", "迅雷", "阿里", "123", "uc", "磁力", "网盘", "线路"))
            or any(k in text for k in ("下载", "确认", "txt", "epub", "html", "pdf", "格式"))
        )
        _all_session_mgrs = (self._sessions, self._search_sessions,
                              self._movie_sessions, self._movie_sessions_new,
                              self._novel_sessions)
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
                self._sessions.delete(event)
                event.set_result(event.plain_result("已取消搜索。"))
                return

            # ── 2. select_game 阶段 ──
            if stage == "select_game":
                # 翻页/跳转 → ★插件自己发格式化页面（保证响应）
                if text in page_kw or text.startswith("跳"):
                    event.stop_event()
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
                    await event.send(MessageChain([Plain(self._format_game_page(ses))]))
                    return

                # 数字/自然语言选择 → 插件处理（调详情 + 列网盘）
                if text in num_kw or text.startswith("第") or text.startswith("选") or text.startswith("最后"):
                    event.stop_event()
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
                    links = detail["download_links"]
                    txt = "📦 " + (detail.get("name") or sel["title"]) + "\n" + "=" * 30 + f"\n找到{len(links)}个下载链接：\n\n"
                    for i, lk in enumerate(links, 1):
                        txt += f"{emoji_index(i, len(links))} {GAME_PAN_ICONS.get(lk['pan'], '📥')} {lk['pan']}\n"
                    txt += f"\n请回复数字或网盘名（1-{len(links)}），回复0取消。"
                    await event.send(MessageChain([Plain(txt)]))
                    return

            # ── 3. select_link 阶段 ──
            if stage == "select_link":
                event.stop_event()
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
                safe = re.sub(r'[\\/:*?"<>|]', "_", gn)[:30]
                gid = event.get_group_id(); uid = event.get_sender_id()
                logger.info(f"[执行] 游戏 {gn} gid={gid} uid={uid}")
                if gid:
                    t2 = "📦 " + gn + "\n📖 " + detail.get("desc", "暂无简介")[:400] + "\n📥 " + GAME_PAN_ICONS.get(rlink["pan"], "📥") + " " + rlink["pan"] + "\n" + rlink.get("real_url", "") + ((" 提取码:" + rlink.get("code", "")) if rlink.get("code") else "")
                    if Nodes and Node:
                        sid = event.get_self_id(); nd = Nodes([])
                        nd.nodes.append(Node(uin=sid, name="暮黎游戏搜索", content=[Plain(t2)]))
                        imgs = []
                        for u in detail.get("screenshots", []):
                            try:
                                # 用截图自身域名作为 Referer（兼容 xdgame / switch618 两种源），避免跨域 403
                                _ref = ("/".join(u.split("/")[:3]) + "/") if u.startswith("http") else GAME_BASE_URL + "/"
                                ir = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Referer": _ref}, timeout=15)
                                if ir.status_code == 200:
                                    fd2, ip = tempfile.mkstemp(suffix=".jpg", prefix="g_"); os.close(fd2)
                                    with open(ip, "wb") as f: f.write(ir.content); imgs.append(ip)
                                    nd.nodes.append(Node(uin=sid, name="暮黎游戏搜索", content=[ImageComponent(file=ip)]))
                            except Exception:
                                pass
                        logger.info(f"[执行] 群聊+{len(imgs)}张截图")
                        await event.send(MessageChain([nd]))
                        for p2 in imgs:
                            try: os.unlink(p2)
                            except Exception: pass
                    else:
                        await event.send(MessageChain([Plain(t2)]))
                elif uid:
                    hc = await asyncio.to_thread(generate_game_html, gn, detail.get("desc", ""), detail.get("cover", ""), detail.get("screenshots", []), rlink, ses.get("keyword", ""))
                    fd, tp = tempfile.mkstemp(suffix=f"_{safe}.html", prefix="g_"); os.close(fd)
                    with open(tp, "w", encoding="utf-8") as f: f.write(hc)
                    fn = f"{gn[:30]}.html"; cl = self._get_best_client(event)
                    if cl:
                        with open(tp, "rb") as f: b64 = base64.b64encode(f.read()).decode("utf-8")
                        if str(uid).isdigit():
                            await cl.call_action(action="upload_private_file", user_id=int(uid), file=f"base64://{b64}", name=fn)
                        else:
                            await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}", MessageChain([FileComponent(file=tp, name=fn)]))
                    else:
                        await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}", MessageChain([Plain(f"📄 {gn}\n\n"), FileComponent(file=tp, name=fn)]))
                    if os.path.exists(tp):
                        try: os.unlink(tp)
                        except Exception: pass
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
                    await event.send(MessageChain([Plain(self._format_sw_page(ses2))]))
                    return

                # 数字/自然语言选择 → 让插件处理（调详情 + 列网盘），保持原来逻辑
                if text in num_kw or text.startswith("第") or text.startswith("选") or text.startswith("最后"):
                    event.stop_event()
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
                    links = detail["download_links"]
                    txt = "📦 " + (detail.get("name") or sel["title"]) + "\n" + "=" * 30 + f"\n找到{len(links)}个下载链接：\n\n"
                    for i, lk in enumerate(links, 1):
                        txt += f"{emoji_index(i, len(links))} {SW_DISK_ICONS.get(lk['pan'], '📥')} {lk['pan']}\n"
                    txt += f"\n请回复数字或网盘名（1-{len(links)}），回复0取消。"
                    await event.send(MessageChain([Plain(txt)]))
                    return

            # ── 3. select_link 阶段 ──
            if stage == "select_link":
                event.stop_event()
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
                safe = re.sub(r'[\\/:*?"<>|]', "_", sn)[:30]
                gid = event.get_group_id(); uid = event.get_sender_id()
                logger.info(f"[执行] 软件 {sn} gid={gid} uid={uid}")
                if gid:
                    t2 = "📦 " + sn + "\n📖 " + (detail.get("desc") or "暂无简介")[:400] + "\n📥 " + SW_DISK_ICONS.get(sl["pan"], "📥") + " " + sl["pan"] + "\n" + (sl.get("url") or "")
                    if Nodes and Node:
                        sid = event.get_self_id(); nd = Nodes([])
                        nd.nodes.append(Node(uin=sid, name="暮黎软件搜索", content=[Plain(t2)]))
                        imgs = []
                        for u in detail.get("screenshots", []):
                            try:
                                ir = requests.get(u, headers={"User-Agent": "Mozilla/5.0", "Referer": SW_BASE_URL + "/"}, timeout=15)
                                if ir.status_code == 200:
                                    fd2, ip = tempfile.mkstemp(suffix=".jpg", prefix="sw_"); os.close(fd2)
                                    with open(ip, "wb") as f: f.write(ir.content); imgs.append(ip)
                                    nd.nodes.append(Node(uin=sid, name="暮黎软件搜索", content=[ImageComponent(file=ip)]))
                            except Exception:
                                pass
                        logger.info(f"[执行] 群聊+{len(imgs)}张截图")
                        await event.send(MessageChain([nd]))
                        for p2 in imgs:
                            try: os.unlink(p2)
                            except Exception: pass
                    else:
                        await event.send(MessageChain([Plain(t2)]))
                elif uid:
                    hc = await asyncio.to_thread(generate_search_html, sn, detail.get("desc") or "", detail.get("cover") or "", detail.get("screenshots") or [], sl, ses2.get("keyword", ""))
                    fd, tp = tempfile.mkstemp(suffix=f"_{safe}.html", prefix="sw_"); os.close(fd)
                    with open(tp, "w", encoding="utf-8") as f: f.write(hc)
                    fn = f"{sn[:30]}.html"; cl = self._get_best_client(event)
                    if cl:
                        with open(tp, "rb") as f: b64 = base64.b64encode(f.read()).decode("utf-8")
                        if str(uid).isdigit():
                            await cl.call_action(action="upload_private_file", user_id=int(uid), file=f"base64://{b64}", name=fn)
                        else:
                            await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}", MessageChain([FileComponent(file=tp, name=fn)]))
                    else:
                        await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uid}", MessageChain([Plain(f"📄 {sn}\n\n"), FileComponent(file=tp, name=fn)]))
                    if os.path.exists(tp):
                        try: os.unlink(tp)
                        except Exception: pass
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
                self._movie_sessions.delete(event)
                event.set_result(event.plain_result("已取消搜索。"))
                return

            # ★选影视：回复数字选影片 / 翻页（原依赖 LLM 调 select_search_result 工具，
            #   但该 AstrBot 版本工具循环不会实际执行该工具，导致选序号无响应。
            #   这里直接拦截处理，与 select_episode / select_source / 新站影视一致）
            if stage == "select_movie":
                event.stop_event()
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
                    await event.send(MessageChain([Plain(self._format_mv_page(self._movie_sessions.get(event)))]))
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
        # 小说会话 (so-novel)
        # ══════════════════════════════════════════════
        nses = self._novel_sessions.get(event)
        if nses:
            stage = nses.get("stage", "")
            # 取消（任意阶段通用）
            if text in cancel_kw:
                event.stop_event()
                self._novel_sessions.delete(event)
                event.set_result(event.plain_result("已取消小说下载。"))
                return
            # 翻页（仅 select_novel 阶段）
            if stage == "select_novel" and (text in page_kw or text.startswith("跳")):
                event.stop_event()
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
                await event.send(MessageChain([Plain(self._format_novel_page(self._novel_sessions.get(event)))]))
                return
            # 选书
            if stage == "select_novel":
                event.stop_event()
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
                    **nses, "stage": "select_format", "selected": sel, "_updated": time.time(),
                })
                fmt_menu = (
                    f"📚 已选择：《{sel.get('book_name') or '未知'}》／{sel.get('author') or '佚名'}\n"
                    f"请选择下载格式（回复数字或格式名）：\n"
                    + "\n".join(f"  {emoji_index(i, len(NOVEL_FORMATS))} {f.upper()}"
                                for i, f in enumerate(NOVEL_FORMATS, 1))
                    + f"\n\n回复 1-{len(NOVEL_FORMATS)} 选择；回复「下载 / 确认」使用默认 TXT；回复 0 取消。"
                )
                await event.send(MessageChain([Plain(fmt_menu)]))
                return
            # 选格式 → 触发下载（默认格式支持多选：回复「下载/确认」生成全部默认格式）
            if stage == "select_format":
                event.stop_event()
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
                await event.send(MessageChain([Plain(
                    f"⏳ 已提交《{sel.get('book_name', '')}》下载任务，"
                    f"生成格式：{fmt_label}{suffix}")]))
                book_name = sel.get("book_name", "") or "小说"
                author = sel.get("author", "") or ""
                results = []
                for fmt in fmt_list:
                    try:
                        # 1) 触发服务端抓取整本（同步）
                        res = await asyncio.to_thread(
                            fetch_novel, sel, base, token, fmt, dl_timeout)
                        # 2) 插件侧直接拉取文件字节（不再发 localhost 链接 / WebUI 预览）
                        dl = await asyncio.to_thread(
                            download_novel_file, base, res["file_name"], token, dl_timeout)
                        content = dl["content"]
                        fname = dl["file_name"] or res["file_name"]
                        if not content:
                            raise NovelApiError("下载到的文件内容为空，书源可能已失效",
                                                 stage="download")
                        # 3) 落盘后以 base64 经 OneBot 文件上传接口发送。
                        #    注意：群消息里若直接传绝对路径给 FileComponent，客户端
                        #    （napcat）读不到 AstrBot 容器内的 /tmp 而报 ENOENT；用
                        #    base64 内嵌可彻底规避。复用已验证的 _upload_zip。
                        ext = (fname.rsplit(".", 1)[-1].lower() if "." in fname
                               else fmt)
                        if ext not in NOVEL_FORMATS:
                            ext = fmt
                        fd, tp = tempfile.mkstemp(suffix=f".{ext}", prefix="novel_")
                        os.close(fd)
                        with open(tp, "wb") as f:
                            f.write(content)
                        try:
                            ok = await self._upload_zip(tp, fname, event=event)
                        finally:
                            if os.path.exists(tp):
                                try:
                                    os.unlink(tp)
                                except Exception:
                                    pass
                        if ok:
                            results.append((fmt, fname, None))
                        else:
                            results.append((fmt, None,
                                            "文件上传失败（OneBot 客户端不可达，请检查连接）"))
                    except Exception as e:
                        msg = e.message if isinstance(e, NovelApiError) else str(e)[:200]
                        results.append((fmt, None, msg))
                ok_count = sum(1 for r in results if r[1])
                lines = [
                    f"✅ 下载完成：《{book_name}》／{author}",
                    f"📦 已发送 {ok_count}/{len(fmt_list)} 个格式",
                ]
                for fmt, fname, err in results:
                    if err:
                        lines.append(f"❌ {fmt.upper()}：{err}（可换源/格式重试）")
                if ok_count == 0:
                    lines.append("💡 全部格式生成失败，请换一个书源或格式重试。")
                await event.send(MessageChain([Plain("\n".join(lines))]))
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
            ]
            for job_id, jh, jm, func, name in jobs:
                try:
                    sch.add_job(func, CronTrigger(hour=int(jh), minute=int(jm), **tz_kw),
                                id=job_id, replace_existing=True, misfire_grace_time=600)
                    self._scheduled_job_ids.append(job_id)
                    j = sch.get_job(job_id)
                    nxt = j.next_run_time.strftime("%Y-%m-%d %H:%M") if (j and j.next_run_time) else "?"
                    logger.info(f"[暮黎资源] 已注册官方定时任务: {name} @ {int(jh):02d}:{int(jm):02d} (Asia/Shanghai) 下次运行: {nxt}")
                except Exception as e:
                    logger.error(f"[暮黎资源] 注册官方定时任务失败 ({name}): {e}")
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
        try:
            d = os.path.join(os.path.dirname(__file__),"debug_logs"); os.makedirs(d,exist_ok=True)
            self._debug_log_path = os.path.join(d,"scheduler_debug.log")
        except Exception: pass
        try:
            self._reports_dir = os.path.join(os.path.dirname(__file__),"reports"); os.makedirs(self._reports_dir,exist_ok=True)
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
                except Exception:
                    nh,nm,ngh,ngm,nmh,nmm = 10,0,18,0,20,0
                changed = (nh != self._schedule_hour or nm != self._schedule_minute or
                           ngh != self._game_schedule_hour or ngm != self._game_schedule_minute or
                           nmh != self._movie_schedule_hour or nmm != self._movie_schedule_minute)
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
                    j = self._apscheduler.get_job(self._scheduler_job_id)
                    if not j or not j.next_run_time: self._schedule_sw_next()
                    jg = self._apscheduler.get_job(self._game_scheduler_job_id)
                    if not jg or not jg.next_run_time: self._schedule_game_next()
                    jm = self._apscheduler.get_job(self._movie_scheduler_job_id)
                    if not jm or not jm.next_run_time: self._schedule_movie_next()
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

    def _sw_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir,f"sw_report_{ds}.zip") if self._reports_dir else ""

    def _sw_cleanup_reports(self):
        if not self._reports_dir: return
        try:
            now = datetime.date.today(); cut = now - datetime.timedelta(days=self._reports_retention_days)
            for fn in os.listdir(self._reports_dir):
                if not fn.endswith(".zip"): continue
                if not (fn.startswith("sw_report_") or fn.startswith("game_report_")
                        or fn.startswith("movie_report_")): continue
                p = (fn.replace("sw_report_","").replace("game_report_","").replace("movie_report_","").replace(".zip",""))
                if len(p)!=8 or not p.isdigit(): continue
                fd = datetime.date(int(p[:4]),int(p[4:6]),int(p[6:8]))
                if fd < cut: os.remove(os.path.join(self._reports_dir,fn))
        except: pass

    def _movie_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir, f"movie_report_{ds}.zip") if self._reports_dir else ""

    async def _movie_send_report(self, img_bytes, ts, text: str = ""):
        config = self._get_config()
        gids, _fb = self._resolve_group_ids("movie_group_ids")
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

    async def _movie_build_and_send(self, items: list, ts: str):
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        html = build_glass_html(items, date_label, source_label="教父.com")
        font_path = os.path.join(os.path.dirname(__file__), "SourceHanSansCN-Heavy.otf")
        config = self._get_config()
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[影视日报] 开始渲染，共 {len(items)} 部，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_glass_to_png, html, font_path, 720, channel, exe)
            logger.info(f"[影视日报] 渲染完成，原始图片体积 {len(img_bytes)//1024}KB")
        except Exception as e:
            logger.error(f"[影视日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
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
        return await self._movie_send_report(img_bytes, ts, text)

    async def _movie_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._movie_last_run_date == ts:
                logger.info(f"[暮黎资源] 影视日报今日({ts})已运行过，跳过")
                return
            self._movie_last_run_date = ts
        logger.info(f"[暮黎资源] ⏰ 影视日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        config = self._get_config()
        if not (config.get("movie_report_enabled", True) if isinstance(config, dict) else True):
            logger.warning("[暮黎资源] 影视日报已触发，但 movie_report_enabled 关闭，跳过")
            return
        gs_list, fb = self._resolve_group_ids("movie_group_ids")
        if not gs_list:
            logger.warning("[暮黎资源] 影视日报已触发，但未配置 movie_group_ids，跳过发送")
            return
        cookie = (config.get("muliy_cookie", "") or "") if isinstance(config, dict) else ""
        # movie_source 显式设为 a123tv 则强制旧站；否则按 cookie 自动切换
        forced_a123 = (config.get("movie_source") or "").strip().lower() == "a123tv"
        mx = int(config.get("movie_report_max", 24) or 24)
        sections = self._parse_multi(config.get("movie_sections", ["mv", "tv", "ac"]) or ["mv", "tv", "ac"])
        sections_filter = [s for s in sections if s in ("mv", "tv", "ac")] or None
        # 自动选择影视源：配了教父.com Cookie 走新站，否则回退 a123tv 旧站（免登录）
        use_cookie = "" if forced_a123 else cookie
        logger.info(f"[影视日报] 开始抓取（源={'a123tv(强制)' if forced_a123 else ('教父.com' if cookie else 'a123tv(免登录)')}）")
        result = await asyncio.to_thread(fetch_movie_daily_auto, use_cookie, "", mx, sections_filter, True)
        if not result["success"]:
            logger.warning(f"[影视日报] 抓取失败: {result.get('error','')}（不标记今日完成，兜底守护将重试）")
            return
        items = result.get("items", [])
        if not items:
            logger.info("[影视日报] 今日暂无更新，标记今日已完成")
            self._movie_last_run_date = ts; return
        # 缓存 zip 供面板回看
        try:
            date_label = datetime.date.today().strftime("%Y年%m月%d日")
            src_label = result.get("source", "教父.com")
            html = build_glass_html(items, date_label, source_label=src_label)
            zp = await asyncio.to_thread(gen_movie_report_zip, items, html, ts)
            if zp:
                import shutil
                shutil.copy2(zp, self._movie_cached_path(ts))
                self._sw_cleanup_reports()
        except Exception as e: logger.warning(f"[影视日报] 缓存 zip 失败: {e}")
        sent = await self._movie_build_and_send(items, ts)
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._movie_last_run_date = ts
            logger.info(f"[影视日报] 今日推送完成（{sent} 群）")
        else:
            logger.error("[影视日报] 抓取成功但发送 0 群，兜底守护将重试")
        self._schedule_movie_next()

    @filter.command("movie_report")
    async def cmd_movie_report(self, event: AstrMessageEvent):
        config = self._get_config()
        cookie = (config.get("muliy_cookie", "") or "") if isinstance(config, dict) else ""
        forced_a123 = (config.get("movie_source") or "").strip().lower() == "a123tv"
        mx = int(config.get("movie_report_max", 24) or 24)
        sections = self._parse_multi(config.get("movie_sections", ["mv", "tv", "ac"]) or ["mv", "tv", "ac"])
        sections_filter = [s for s in sections if s in ("mv", "tv", "ac")] or None
        use_cookie = "" if forced_a123 else cookie
        src_hint = "a123tv 旧站（免登录）" if (forced_a123 or not cookie) else "教父.com 新站"
        yield event.plain_result(f"⏳ 正在抓取{src_hint}最近更新影视...")
        result = await asyncio.to_thread(fetch_movie_daily_auto, use_cookie, "", mx, sections_filter, True)
        if not result["success"]:
            yield event.plain_result(f"⚠️ {result.get('error','未知')}"); return
        items = result.get("items", [])
        if not items:
            yield event.plain_result("📭 今日暂无影视更新。"); return
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        src_label = result.get("source", "教父.com")
        html = build_glass_html(items, date_label, source_label=src_label)
        font_path = os.path.join(os.path.dirname(__file__), "SourceHanSansCN-Heavy.otf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        try:
            img_bytes = await asyncio.to_thread(render_glass_to_png, html, font_path, 720, channel, exe)
        except Exception as e: logger.error(f"[影视日报] 渲染异常: {e}")
        ts = datetime.date.today().strftime("%Y%m%d")
        fn = f"暮黎影视日报_{ts}{_img_ext(img_bytes)}" if img_bytes else ""
        if img_bytes:
            ok = await self._send_event_file(event, img_bytes, fn, "", "影视日报")
            if not ok:
                yield event.plain_result("⚠️ 日报图片发送失败，请确认已执行 playwright install chromium。")
        else:
            await event.send(MessageChain([Plain(
                "⚠️ 图片渲染失败（请确认已执行 playwright install chromium），改为文字版：\n"
                + "\n".join(f"{i}. {it.get('title','')}（{it.get('type_name','')}）{(' '+it.get('status','')) if it.get('status') else ''}"
                             for i, it in enumerate(items, 1)))]))

    async def _sw_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        # 防重锁：cron 与兜底守护可能在同一时刻同时触发，避免重复发送
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._last_run_date == ts:
                logger.info(f"[暮黎资源] 软件日报今日({ts})已运行过，跳过")
                return
            self._last_run_date = ts  # 先占位，防止并发重入
        logger.info(f"[暮黎资源] ⏰ 软件日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        config = self._get_config()
        gids = self._parse_multi(config.get("group_ids", []) if isinstance(config, dict) else [])
        if not gids:
            logger.warning("[暮黎资源] 软件日报已触发，但未配置 group_ids，跳过发送")
            return
        mx = 24  # max_softwares 配置已移除，固定默认 24
        result = await asyncio.to_thread(sync_scrape, mx)
        if not result["success"]:
            logger.warning(f"[软件日报] 抓取失败: {result.get('error','')}（不标记今日完成，兜底守护将重试）")
            return
        sws = result.get("softwares",[])
        if not sws:
            logger.info("[软件日报] 今日暂无更新，标记今日已完成")
            self._last_run_date = ts; return
        # 橙色夏日风格：HTML → 图片（替代旧的 Pillow 手绘）
        img_bytes = await self._sw_render_image(sws)
        zp = await asyncio.to_thread(gen_report_zip, sws, io.BytesIO(img_bytes) if img_bytes else None)
        # 文字版兜底内容（图片渲染失败或图片上传失败时使用）
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        text = (f"📦 暮黎软件日报 {date_label}\n今日共 {len(sws)} 款更新：\n"
                + "\n".join(f"{i}. {s.get('name','')} - {(s.get('desc','') or '')[:40]}"
                            for i, s in enumerate(sws, 1)))
        # 仅发送图片/文字，不再向群发送自包含 zip 文件
        sent = await self._sw_send_report(img_bytes, None, text)
        # 缓存 zip 仅供面板本地回看（不会发送给用户/群）
        if zp:
            try:
                import shutil
                shutil.copy2(zp, self._sw_cached_path(ts))
                self._sw_cleanup_reports()
            except: pass
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._last_run_date = ts
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

    async def _try_send_group_file(self, umo: str, img_bytes: bytes | None, file_name: str, text: str, label: str) -> bool:
        """以「文件」形式发送日报图片（绕开 onebot 发图体积上限，杜绝大图被平台静默拒收）。

        与小说 _upload_zip 一致，走 client.call_action(upload_group_file, base64://..., name=...)。
        群文件发送失败 → 降级文字版兜底；无图片则直接发文字版。
        """
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

        群内 → upload_group_file（与小说 _upload_zip 一致）；私聊/好友 → 临时文件 + FileComponent 兜底。
        任何失败都按 text 兜底（text 为空则仅返回 False）。
        """
        if not img_bytes:
            if text:
                await event.send(MessageChain([Plain(text)]))
            return bool(text)
        gid = event.get_group_id()
        client = self._get_best_client(event)
        if gid and client:
            try:
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                await client.call_action(action="upload_group_file", group_id=int(gid),
                                         file=f"base64://{b64}", name=file_name)
                await asyncio.sleep(0.4)
                logger.info(f"[暮黎资源] {label} 手动指令已以文件形式发送到群 {gid}（{file_name}）")
                return True
            except Exception as e:  # noqa: BLE001
                logger.error(f"[暮黎资源] {label} 手动指令群文件发送失败: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
                if text:
                    await event.send(MessageChain([Plain(text)]))
                return bool(text)
        # 私聊/好友：临时文件 + FileComponent 兜底
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=_img_ext(img_bytes), prefix="report_"); os.close(fd)
            with open(tmp, "wb") as f: f.write(img_bytes)
            await self.context.send_message(
                f"{event.get_platform_id()}:FriendMessage:{event.get_sender_id()}",
                MessageChain([FileComponent(file=tmp, name=file_name)]))
            logger.info(f"[暮黎资源] {label} 手动指令已以文件形式发送（FileComponent, {file_name}）")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"[暮黎资源] {label} 手动指令 FileComponent 发送失败: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
            if text:
                await event.send(MessageChain([Plain(text)]))
            return bool(text)
        finally:
            if tmp and os.path.exists(tmp):
                try: os.unlink(tmp)
                except Exception: pass

    async def _sw_send_report(self, img_bytes, zp, text: str = ""):
        config = self._get_config()
        gids = self._parse_multi(config.get("group_ids", []) if isinstance(config, dict) else [])
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

    async def _upload_zip(self, zp, zn, event=None, gid=None, uid=None):
        if not zp or not os.path.exists(zp): return False
        try:
            sz = _format_size(os.path.getsize(zp))
            gg = gid or (event and event.get_group_id()); uu = uid or (event and event.get_sender_id())
            if event: await event.send(MessageChain([Plain(f"📤 上传({sz})...")]))
            client = self._get_best_client(event)
            if not client: return False
            with open(zp,"rb") as f: b64=base64.b64encode(f.read()).decode("utf-8")
            if gg: await client.call_action(action="upload_group_file",group_id=int(gg),file=f"base64://{b64}",name=zn); return True
            elif uu:
                if str(uu).isdigit(): await client.call_action(action="upload_private_file",user_id=int(uu),file=f"base64://{b64}",name=zn)
                else: await self.context.send_message(f"{event.get_platform_id()}:FriendMessage:{uu}",MessageChain([FileComponent(file=zp,name=zn)]))
                return True
        except: pass
        return False

    # ==================== 游戏日报（XDGAME） ====================
    def _game_cached_path(self, ds: str) -> str:
        return os.path.join(self._reports_dir, f"game_report_{ds}.zip") if self._reports_dir else ""

    async def _game_send_report(self, img_bytes, ts, text: str = ""):
        logger.info(f"[游戏日报] 进入发送阶段：图片={'有 %dKB' % (len(img_bytes)//1024) if img_bytes else '无'} | 文字版={'有 %d字' % len(text) if text else '无'}")
        config = self._get_config()
        gids, _fb = self._resolve_group_ids("game_group_ids")
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

    async def _game_build_and_send(self, games: list, ts: str):
        date_label = datetime.date.today().strftime("%Y年%m月%d日")
        src_label = "switch618" if self._game_source() == "switch618" else "XDGAME"
        html = build_cartoon_html(games, date_label, source_label=src_label)
        font_path = os.path.join(os.path.dirname(__file__), "SourceHanSansCN-Heavy.otf")
        config = self._get_config()
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        logger.info(f"[游戏日报] 开始渲染，共 {len(games)} 款游戏，html 长度 {len(html)} 字符，浏览器 channel={channel!r} exe={exe!r}")
        try:
            img_bytes = await asyncio.to_thread(render_html_to_png, html, font_path, 700, channel, exe)
            logger.info(f"[游戏日报] 渲染完成，原始图片体积 {len(img_bytes)//1024}KB")
        except Exception as e:
            logger.error(f"[游戏日报] 渲染异常: {type(e).__name__}: {e!r}\n{traceback.format_exc()}")
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
        return await self._game_send_report(img_bytes, ts, text)

    async def _game_daily_job(self):
        ts = datetime.date.today().strftime("%Y%m%d")
        if self._sw_job_lock is None:
            self._sw_job_lock = asyncio.Lock()
        async with self._sw_job_lock:
            if self._game_last_run_date == ts:
                logger.info(f"[暮黎资源] 游戏日报今日({ts})已运行过，跳过")
                return
            self._game_last_run_date = ts
        logger.info(f"[暮黎资源] ⏰ 游戏日报定时触发 @ {datetime.datetime.now()} (Asia/Shanghai)")
        config = self._get_config()
        if not (config.get("game_report_enabled", True) if isinstance(config, dict) else True):
            logger.warning("[暮黎资源] 游戏日报已触发，但 game_report_enabled 关闭，跳过")
            return
        gs_list, fb = self._resolve_group_ids("game_group_ids")
        if not gs_list:
            logger.warning("[暮黎资源] 游戏日报已触发，但未配置 game_group_ids，跳过发送")
            return
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
            self._game_last_run_date = ts; return
        sent = await self._game_build_and_send(games, ts)
        # 仅当成功推送到至少一个群才标记今日完成；否则留给兜底守护重试
        if sent > 0:
            self._game_last_run_date = ts
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
        font_path = os.path.join(os.path.dirname(__file__), "SourceHanSansCN-Heavy.otf")
        channel = (config.get("browser_channel", "") or "") if isinstance(config, dict) else ""
        exe = (config.get("browser_exe", "") or "") if isinstance(config, dict) else ""
        img_bytes = None
        try:
            img_bytes = await asyncio.to_thread(render_html_to_png, html, font_path, 700, channel, exe)
        except Exception as e: logger.error(f"[游戏日报] 渲染异常: {e}")
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

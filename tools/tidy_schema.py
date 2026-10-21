# -*- coding: utf-8 -*-
"""重排 _conf_schema.json 并给高级项加 collapsed / condition，缩短配置页。

AstrBot 的 object 分组本身不能折叠，但单个配置项支持：
  "collapsed": true   → 收进该分组的「更多配置」里
  "condition": {...}  → 条件不满足时整项隐藏
两者组合后，常用项一屏可见，高级项/账号凭据/定时设置默认收起。
"""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "_conf_schema.json")

GROUP_ORDER = [
    "list_card", "browser", "game", "software", "movie", "shortdrama",
    "novel", "music", "vip_video", "verify", "points",
]

ITEM_ORDER = {
    "game": ["game_source", "max_search_results",
             "xdgame_username", "xdgame_password", "cookie", "switch618_cookie",
             "game_report_enabled", "game_report_max",
             "game_schedule_hour", "game_schedule_minute", "game_group_ids"],
    "software": ["schedule_hour", "schedule_minute", "group_ids"],
    "movie": ["movie_source", "muliy_release_url", "muliy_cache_ttl",
              "muliy_username", "muliy_password", "muliy_cookie",
              "movie_report_enabled", "movie_report_max", "movie_sections",
              "movie_schedule_hour", "movie_schedule_minute", "movie_group_ids"],
    "shortdrama": ["drama_enabled", "drama_search_limit", "drama_timeout",
                   "drama_report_enabled", "drama_report_max",
                   "drama_schedule_hour", "drama_schedule_minute",
                   "drama_group_ids"],
    "novel": ["sonovel_base_url", "sonovel_format", "sonovel_token",
              "sonovel_search_limit", "sonovel_timeout",
              "sonovel_download_timeout"],
    "music": ["wyy_auto_parse", "wyy_backend", "wyy_music_type",
              "wyy_audio_format", "wyy_custom_url", "wyy_clip_seconds",
              "wyy_cookie", "wyy_proxy"],
    "vip_video": ["video_vip_parse", "video_vip_timeout"],
    "browser": ["browser_channel", "browser_exe"],
    "list_card": ["list_card_enabled", "list_card_threshold"],
    "verify": ["join_verify_enabled", "join_verify_group_ids",
               "join_verify_timeout", "join_verify_max_attempts",
               "join_verify_recall", "join_verify_kick",
               "join_verify_welcome_text"],
    "points": ["points_enabled", "points_initial", "checkin_points",
               "checkin_streak_bonus", "checkin_streak_max",
               "checkin_card_enabled", "checkin_info_module",
               "checkin_weather_city", "checkin_recommend_dynamic",
               "checkin_recommend_games", "checkin_recommend_software",
               "checkin_recommend_movies",
               "points_cost_game", "points_cost_software", "points_cost_movie",
               "points_cost_drama", "points_cost_novel"],
}

# 默认收进「更多配置」的项
COLLAPSED = {
    "game": {"xdgame_username", "xdgame_password", "cookie", "switch618_cookie",
             "game_report_max", "game_schedule_hour", "game_schedule_minute",
             "game_group_ids"},
    "software": {"group_ids"},
    "movie": {"muliy_release_url", "muliy_cache_ttl", "muliy_username",
              "muliy_password", "muliy_cookie", "movie_report_max",
              "movie_sections", "movie_schedule_hour", "movie_schedule_minute",
              "movie_group_ids"},
    "shortdrama": {"drama_timeout", "drama_report_max", "drama_schedule_hour",
                   "drama_schedule_minute", "drama_group_ids"},
    "novel": {"sonovel_token", "sonovel_search_limit", "sonovel_timeout",
              "sonovel_download_timeout"},
    "music": {"wyy_custom_url", "wyy_clip_seconds", "wyy_cookie", "wyy_proxy"},
    "vip_video": {"video_vip_timeout"},
    "verify": {"join_verify_timeout", "join_verify_max_attempts",
               "join_verify_recall", "join_verify_kick",
               "join_verify_welcome_text"},
    "points": {"points_initial", "checkin_streak_bonus", "checkin_streak_max",
               "checkin_weather_city", "checkin_recommend_dynamic",
               "checkin_recommend_games", "checkin_recommend_software",
               "checkin_recommend_movies", "points_cost_game",
               "points_cost_software", "points_cost_movie",
               "points_cost_drama", "points_cost_novel"},
}

# 条件显隐（与原 condition 合并，多个键为 AND）
CONDITIONS = {
    "game": {
        "game_report_max": {"game_report_enabled": True},
        "game_schedule_hour": {"game_report_enabled": True},
        "game_schedule_minute": {"game_report_enabled": True},
        "game_group_ids": {"game_report_enabled": True},
    },
    "movie": {
        "movie_report_max": {"movie_report_enabled": True},
        "movie_sections": {"movie_report_enabled": True},
        "movie_schedule_hour": {"movie_report_enabled": True},
        "movie_schedule_minute": {"movie_report_enabled": True},
        "movie_group_ids": {"movie_report_enabled": True},
    },
    "shortdrama": {
        "drama_report_max": {"drama_report_enabled": True},
        "drama_schedule_hour": {"drama_report_enabled": True},
        "drama_schedule_minute": {"drama_report_enabled": True},
        "drama_group_ids": {"drama_report_enabled": True},
    },
    "verify": {
        "join_verify_group_ids": {"join_verify_enabled": True},
        "join_verify_timeout": {"join_verify_enabled": True},
        "join_verify_max_attempts": {"join_verify_enabled": True},
        "join_verify_recall": {"join_verify_enabled": True},
        "join_verify_kick": {"join_verify_enabled": True},
        "join_verify_welcome_text": {"join_verify_enabled": True},
    },
    "points": {
        "points_initial": {"points_enabled": True},
        "checkin_points": {"points_enabled": True},
        "checkin_streak_bonus": {"points_enabled": True},
        "checkin_streak_max": {"points_enabled": True},
        "checkin_card_enabled": {"points_enabled": True},
        "checkin_info_module": {"points_enabled": True,
                                "checkin_card_enabled": True},
        "checkin_weather_city": {"points_enabled": True,
                                 "checkin_card_enabled": True,
                                 "checkin_info_module": "weather"},
        "checkin_recommend_dynamic": {"points_enabled": True,
                                      "checkin_card_enabled": True},
        "checkin_recommend_games": {"points_enabled": True,
                                    "checkin_card_enabled": True},
        "checkin_recommend_software": {"points_enabled": True,
                                       "checkin_card_enabled": True},
        "checkin_recommend_movies": {"points_enabled": True,
                                     "checkin_card_enabled": True},
        "points_cost_game": {"points_enabled": True},
        "points_cost_software": {"points_enabled": True},
        "points_cost_movie": {"points_enabled": True},
        "points_cost_drama": {"points_enabled": True},
        "points_cost_novel": {"points_enabled": True},
    },
}

HINTS = {
    "list_card": "搜索结果条目多时自动出图；关闭后全部回到纯文本。高级项已收起。",
    "browser": "本地 Chromium 渲染（可选）；留空使用插件自带浏览器或 AstrBot 内置渲染。",
    "game": "游戏搜索源、结果上限、账号凭据与游戏日报；凭据/日报时间在「更多配置」里。",
    "software": "软件日报的推送时间与目标群。",
    "movie": "影视搜索源、片库登录凭据与影视日报；高级项在「更多配置」里。",
    "shortdrama": "短剧搜索与短剧日报；日报时间/群在「更多配置」里。",
    "novel": "so-novel 服务地址与下载格式；令牌、超时在「更多配置」里。",
    "music": "网易云语音名片；自建接口、Cookie、代理在「更多配置」里。",
    "vip_video": "爱奇艺/腾讯/优酷/芒果 VIP 链接解析。",
    "verify": "QQ 新成员图形验证码审核；超时/机会/撤回等在「更多配置」里。",
    "points": "签到与积分系统；初始积分、连续加成、推荐清单、搜索消耗在「更多配置」里。",
}


def main():
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)

    old_keys = {(g, k) for g, v in data.items() for k in v.get("items", {})}
    new = {}
    for g in GROUP_ORDER:
        src = data[g]
        items = src.get("items", {})
        order = [k for k in ITEM_ORDER.get(g, []) if k in items]
        order += [k for k in items if k not in order]
        out_items = {}
        for k in order:
            it = dict(items[k])
            if k in COLLAPSED.get(g, set()):
                it["collapsed"] = True
            cond = dict(it.get("condition") or {})
            cond.update(CONDITIONS.get(g, {}).get(k, {}))
            if cond:
                it["condition"] = cond
            out_items[k] = it
        group = dict(src)
        group["items"] = out_items
        if g in HINTS:
            group["hint"] = HINTS[g]
        new[g] = group

    # 校验没有丢键
    new_keys = {(g, k) for g, v in new.items() for k in v.get("items", {})}
    missing = old_keys - new_keys
    extra = new_keys - old_keys
    assert not missing and not extra, (missing, extra)
    assert list(new.keys()) == GROUP_ORDER

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("groups:", GROUP_ORDER)
    print("items:", len(new_keys), "collapsed:",
          sum(1 for v in new.values() for it in v["items"].values()
              if it.get("collapsed")))


if __name__ == "__main__":
    main()

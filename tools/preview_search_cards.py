# -*- coding: utf-8 -*-
"""游戏 / 软件 / 影视 / 短剧搜索卡片预览。"""
import os
import sys
import types
import logging
import time

ROOT = r"D:\桌面\report pu\astrbot_plugin_muliyresources"
sys.path.insert(0, ROOT)
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("t")
sys.modules["astrbot"] = types.ModuleType("astrbot")
sys.modules["astrbot.api"] = api

from core.list_card import (
    game_card_html, software_card_html, movie_card_html,
    movie_new_card_html, drama_card_html, render_list_card,
)

OUT = os.path.join(ROOT, "assets", "preview")


def render(name, html):
    t0 = time.time()
    data = render_list_card(html)
    with open(os.path.join(OUT, name + ".jpg"), "wb") as f:
        f.write(data)
    with open(os.path.join(OUT, name + ".html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(name, f"{len(data)//1024}KB", f"{round((time.time()-t0)*1000)}ms")


games = [
    {"title": "艾尔登法环：黑夜君临", "type": "动作角色扮演", "date": "2026-10-21"},
    {"title": "寂静岭 f", "type": "恐怖生存", "date": "2026-10-20"},
    {"title": "空洞骑士：丝之歌", "type": "银河恶魔城", "date": "2026-10-18"},
    {"title": "战地 6", "type": "第一人称射击", "date": "2026-10-16"},
    {"title": "文明 7", "type": "策略", "date": "2026-10-12"},
    {"title": "双影奇境", "type": "双人合作", "date": "2026-10-08"},
]
render("card_game", game_card_html(
    {"keyword": "艾尔登法环", "results": games, "page": 0, "page_size": 8},
    timeout=300, note="本次搜索消耗 5 积分，剩余 96 积分"))

softs = [
    {"title": "PotPlayer 1.7.22354 中文绿色版", "update_time": "2026-10-21"},
    {"title": "Bandizip 7.36 正式版", "update_time": "2026-10-20"},
    {"title": "Everything 1.4.1 文件搜索", "update_time": "2026-10-19"},
    {"title": "IDM 6.42 下载工具", "update_time": "2026-10-17"},
    {"title": "Office 2021 批量授权版", "update_time": "2026-10-15"},
    {"title": "Photoshop 2025 精简版", "update_time": "2026-10-11"},
]
render("card_software", software_card_html(
    {"keyword": "播放器", "results": softs, "page": 0, "page_size": 8}, timeout=300))

movies_new = [
    {"title": "沙丘2", "type": "科幻片", "year": "2024", "score": "8.3"},
    {"title": "漫长的季节", "type": "国产剧", "year": "2023", "score": "9.4"},
    {"title": "蜘蛛侠：崭新之日", "type": "动作片", "year": "2026", "score": "7.9"},
    {"title": "繁花", "type": "国产剧", "year": "2023", "score": "8.7"},
    {"title": "奥本海默", "type": "传记片", "year": "2023", "score": "8.9"},
    {"title": "流浪地球3", "type": "科幻片", "year": "2027", "score": "8.1"},
]
render("card_movie", movie_new_card_html(movies_new, "沙丘", 0, 8, timeout=120))

movies_old = [
    {"title": "沙丘2", "category": "科幻片", "year": "2024"},
    {"title": "漫长的季节", "category": "国产剧", "year": "2023"},
    {"title": "奥本海默", "category": "传记片", "year": "2023"},
    {"title": "繁花", "category": "国产剧", "year": "2023"},
    {"title": "流浪地球2", "category": "科幻片", "year": "2023"},
    {"title": "狂飙", "category": "国产剧", "year": "2023"},
]
render("card_movie_old", movie_card_html(
    {"keyword": "沙丘", "results": movies_old, "page": 0, "page_size": 8}, timeout=300))

dramas = [
    {"title": "闪婚后，顾总每天都在吃醋", "category": "都市", "date": "10-21"},
    {"title": "重生之我在霸总家当保姆", "category": "逆袭", "date": "10-21"},
    {"title": "长嫂如母", "category": "家庭", "date": "10-20"},
    {"title": "千金归来", "category": "复仇", "date": "10-19"},
    {"title": "我的老板是首富", "category": "甜宠", "date": "10-18"},
    {"title": "离婚后她惊艳全球", "category": "爽文", "date": "10-17"},
]
render("card_drama", drama_card_html(
    {"keyword": "短剧", "results": dramas, "page": 0, "page_size": 8}, timeout=300))

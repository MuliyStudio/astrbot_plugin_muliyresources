# -*- coding: utf-8 -*-
"""预览四个日报 + 两张列表卡片的 logo 效果，渲染成图片。"""
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

from core.game_daily import build_cartoon_html
from core.movie_daily import build_glass_html
from core.software import build_summer_html
from core.shortdrama import build_drama_html
from core.list_card import novel_card_html, pan_card_html, render_list_card

OUT = os.path.join(ROOT, "assets", "preview")
os.makedirs(OUT, exist_ok=True)


def render(name, html):
    t0 = time.time()
    data = render_list_card(html)
    if not data:
        print(name, "渲染失败")
        return
    p = os.path.join(OUT, name + ".jpg")
    with open(p, "wb") as f:
        f.write(data)
    with open(os.path.join(OUT, name + ".html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(name, f"{len(data)//1024}KB", f"{round((time.time()-t0)*1000)}ms", p)


games = [
    {"title": "艾尔登法环：黑夜君临", "intro": "三人合作生存动作游戏，随机地图与夜之领主。",
     "size": "12.4GB", "date": "2026-10-21", "tags": ["动作", "联机"], "shots_b64": []},
    {"title": "寂静岭 f", "intro": "昭和日本背景的心理恐怖新作。",
     "size": "30.1GB", "date": "2026-10-21", "tags": ["恐怖"], "shots_b64": []},
]

movies = [
    {"name": "沙丘2", "year": "2024", "score_db": "8.3", "status": "HD中字",
     "leixing": ["科幻"], "diqu": ["美国"], "desc": "保罗·厄崔迪与弗雷曼人联手复仇。",
     "cover_b64": "", "section": "mv"},
    {"name": "漫长的季节", "year": "2023", "score_db": "9.4", "status": "全12集",
     "leixing": ["悬疑"], "diqu": ["中国大陆"], "desc": "一桩旧案牵出三个时代。",
     "cover_b64": "", "section": "tv"},
]

softwares = [
    {"title": "PotPlayer 1.7", "size": "42MB", "date": "2026-10-21",
     "tags": ["播放器"], "intro": "轻量本地视频播放器。", "cover_b64": "",
     "shots_b64": [], "downloads": [{"name": "百度网盘"}, {"name": "夸克网盘"}]},
    {"title": "Bandizip 7.36", "size": "8MB", "date": "2026-10-21",
     "tags": ["压缩"], "intro": "快速解压工具。", "cover_b64": "",
     "shots_b64": [], "downloads": [{"name": "迅雷网盘"}]},
]

dramas = [{"title": "闪婚后，顾总每天都在吃醋"}, {"title": "重生之我在霸总家当保姆"}]

render("report_game", build_cartoon_html(games, "2026年10月21日"))
render("report_movie", build_glass_html(movies, "2026年10月21日"))
render("report_software", build_summer_html(softwares, "2026年10月21日"))
render("report_drama", build_drama_html(dramas, "2026年10月21日"))

ses = {"keyword": "诡秘之主", "page_size": 8, "page": 0,
       "results": [{"book_name": f"诡秘之主 第{i}部", "author": "爱潜水的乌贼",
                    "source_name": "起点中文网"} for i in range(1, 9)]}
render("novel_list", novel_card_html(ses, timeout=300))

pan = [{"name": f"沙丘2 2160p HDR 版本{i}", "type": "夸克网盘", "user": "影迷小站",
        "time": "2026-08-1%d" % (i % 10)} for i in range(1, 13)]
render("pan_list", pan_card_html(pan, page=0, page_size=12, title="沙丘2", year="2024"))

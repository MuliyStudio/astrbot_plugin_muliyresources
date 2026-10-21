# -*- coding: utf-8 -*-
"""预览积分卡 / 积分排行榜卡片，输出到 assets/preview/。"""
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

from core.list_card import points_card_html, points_rank_html, render_list_card
from core.avatars import fetch_avatars

OUT = os.path.join(ROOT, "assets", "preview")
os.makedirs(OUT, exist_ok=True)
TODAY = "2026-10-21"


def render(name, html):
    t0 = time.time()
    data = render_list_card(html)
    if not data:
        print(name, "渲染失败")
        return
    with open(os.path.join(OUT, name + ".jpg"), "wb") as f:
        f.write(data)
    with open(os.path.join(OUT, name + ".html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(name, f"{len(data)//1024}KB", f"{round((time.time()-t0)*1000)}ms")


COSTS = {"game": 5, "software": 5, "movie": 5, "drama": 5, "novel": 5}
LABELS = {"game": "游戏", "software": "软件", "movie": "影视", "drama": "短剧", "novel": "小说"}
BASE = dict(name="暮黎Muliy", uid="10001", balance=128, streak=3,
            last_checkin=TODAY, total_earned=260, total_spent=132,
            costs=COSTS, labels=LABELS, enabled=True, today=TODAY,
            today_checked=True, date_label=TODAY)

render("points_card", points_card_html(**BASE))
render("points_card_off", points_card_html(**{
    **BASE, "today_checked": False, "streak": 0, "last_checkin": "",
    "balance": 12}))
render("points_card_disabled", points_card_html(**{**BASE, "enabled": False}))

# 排行榜：前 3 用真实 QQ 头像，其余用首字占位（两种状态都展示）
keys = ["aiocqhttp:10001", "aiocqhttp:10002", "aiocqhttp:10003"]
avatars = fetch_avatars(keys)
print("头像命中", len(avatars), "/", len(keys))
people = [
    ("暮黎Muliy", 128, 6), ("小明", 96, 3), ("阿伟", 88, 2),
    ("书虫本虫", 76, 5), ("追剧狂魔", 64, 1), ("夜猫子", 52, 0),
    ("一只栗子", 41, 3), ("老王", 30, 0), ("静音", 18, 1), ("新来的", 5, 0),
]
rows = []
for i, (nm, pts, st) in enumerate(people, 1):
    key = keys[i - 1] if i <= len(keys) else f"aiocqhttp:2000{i}"
    rows.append({"rank": i, "name": nm, "points": pts, "streak": st,
                 "avatar": avatars.get(key, ""), "me": i == 3})
render("points_rank", points_rank_html(
    rows=rows, total=26, me_key="aiocqhttp:10003", me_rank=3, me_points=88,
    date_label=TODAY))

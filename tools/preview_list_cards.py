# -*- coding: utf-8 -*-
"""生成长列表卡片预览：HTML + 渲染图片（开发用，不参与插件运行）。

用法（在仓库根目录）：
    python tools/preview_list_cards.py

产物写到 assets/preview/：
    novel_list.html / novel_list.jpg
    pan_list.html   / pan_list.jpg
"""
import os
import sys
import time
import types
import logging

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 脱离 AstrBot 运行时也能 import core.constants
if "astrbot" not in sys.modules:
    pkg = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("list-card-preview")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.modules["astrbot"] = pkg
    sys.modules["astrbot.api"] = api

from core.list_card import (  # noqa: E402
    novel_card_html, pan_card_html, render_list_card, prewarm,
)

OUT = os.path.join(ROOT, "assets", "preview")


def sample_novel_ses():
    raw = [
        ("诡秘之主", "爱潜水的乌贼", "起点中文网"),
        ("诡秘之主", "爱潜水的乌贼", "笔趣阁"),
        ("诡秘之主（精校版）", "爱潜水的乌贼", "顶点小说"),
        ("诡秘之主：倒吊人", "爱潜水的乌贼", "起点中文网"),
        ("诡秘之主 同人合集", "克莱恩", "番茄小说"),
        ("诡秘之主 番外·愚者的旅途", "爱潜水的乌贼", "七猫中文网"),
        ("诡秘之主（无删减）", "爱潜水的乌贼", "69书吧"),
        ("诡秘之主 第二部", "爱潜水的乌贼", "纵横中文网"),
    ]
    return {
        "keyword": "诡秘之主",
        "results": [{"book_name": n, "author": a, "source_name": s} for n, a, s in raw],
        "page": 0,
        "page_size": 8,
    }


def sample_novel_paged_ses():
    """22 条结果 → 3 页，用来确认页码与长标题换行。"""
    titles = [
        "诡秘之主", "诡秘之主（精校版）", "诡秘之主：倒吊人", "诡秘之主 同人合集",
        "诡秘之主 番外·愚者的旅途", "诡秘之主（无删减）", "诡秘之主 第二部",
        "诡秘之主 第一部 精校全集 含番外", "诡秘之主 同人 克莱恩与奥黛丽",
        "诡秘之主 前传·远古太阳神", "诡秘之主 番外·塔罗会日常", "诡秘之主（全本TXT）",
        "诡秘之主 改编版", "诡秘之主 修订版", "诡秘之主 完结精校",
        "诡秘之主 番外合集 全", "诡秘之主 章节目录", "诡秘之主 典藏版",
        "诡秘之主 无错字版", "诡秘之主 分卷精校", "诡秘之主 旧日之盒",
        "诡秘之主 外传·愚者与门",
    ]
    srcs = ["起点中文网", "笔趣阁", "顶点小说", "番茄小说", "七猫中文网",
            "69书吧", "纵横中文网", "17K小说网"]
    return {
        "keyword": "诡秘之主",
        "results": [{"book_name": t, "author": "爱潜水的乌贼",
                     "source_name": srcs[i % len(srcs)]}
                    for i, t in enumerate(titles)],
        "page": 1,
        "page_size": 8,
    }


def sample_panlist():
    base = [
        ("沙丘2 2160p HDR 杜比视界 内封简繁字幕", "夸克网盘", "影迷小站", "2026-08-19"),
        ("沙丘2 4K REMUX 原盘 61.2G", "115网盘", "蓝光收藏", "2026-08-17"),
        ("沙丘2 1080p 高码率 中英双字", "百度网盘", "老片新看", "2026-08-16"),
        ("沙丘2 完整版 2160p HDR10+ DDP5.1", "阿里网盘", "沙丘宇宙", "2026-08-15"),
        ("沙丘2 4K 60帧 修复版", "迅雷网盘", "资源搬运工", "2026-08-14"),
        ("沙丘2 1080p 国英双语 内嵌字幕", "夸克网盘", "追剧日常", "2026-08-13"),
        ("沙丘2 2160p 杜比全景声 收藏版", "天翼网盘", "高清影库", "2026-08-12"),
        ("沙丘2 720p 小体积 手机看片", "UC网盘", "轻量资源", "2026-08-12"),
        ("沙丘2 4K 导演剪辑加长版", "夸克网盘", "影迷小站", "2026-08-11"),
        ("沙丘2 1080p WEB-DL 官方中字", "百度网盘", "字幕组搬运", "2026-08-10"),
        ("沙丘2 2160p HDR 简繁英 多音轨", "115网盘", "蓝光收藏", "2026-08-09"),
        ("沙丘2 4K 高帧率 无删减", "夸克网盘", "沙丘宇宙", "2026-08-08"),
    ]
    # 补足到 34 条，模拟真实超长列表
    extra = [
        ("沙丘2 1080p 蓝光压制 中英字幕", "夸克网盘"),
        ("沙丘2 2160p 原盘 未压缩", "115网盘"),
        ("沙丘2 4K HDR 内封字幕 收藏", "百度网盘"),
        ("沙丘2 1080p 手机版 小容量", "UC网盘"),
        ("沙丘2 4K 杜比视界 全景声", "阿里网盘"),
        ("沙丘2 720p 快速下载版", "迅雷网盘"),
        ("沙丘2 2160p 10bit 高码", "夸克网盘"),
        ("沙丘2 1080p 完整未删减", "天翼网盘"),
        ("沙丘2 4K 中字 无广告", "夸克网盘"),
        ("沙丘2 2160p 多字幕 多音轨", "百度网盘"),
        ("沙丘2 1080p 修复版 60帧", "夸克网盘"),
        ("沙丘2 4K 蓝光原盘 全花絮", "115网盘"),
        ("沙丘2 1080p 纯净版", "夸克网盘"),
        ("沙丘2 2160p HDR 杜比", "阿里网盘"),
        ("沙丘2 4K 加长版 中英", "夸克网盘"),
        ("沙丘2 1080p 国配 双语", "百度网盘"),
        ("沙丘2 4K 收藏级 高码率", "夸克网盘"),
        ("沙丘2 720p 小屏优化", "UC网盘"),
        ("沙丘2 2160p 无删减 HDR", "115网盘"),
        ("沙丘2 1080p 导演剪辑", "夸克网盘"),
        ("沙丘2 4K 官方中字", "百度网盘"),
        ("沙丘2 2160p 全景声 收藏", "阿里网盘"),
    ]
    rows = list(base) + [(n, t, "资源分享", "2026-08-07") for n, t in extra]
    return [{"name": n, "type": t, "user": u, "time": d} for n, t, u, d in rows]


def save(name: str, html: str, do_render: bool = True):
    os.makedirs(OUT, exist_ok=True)
    html_path = os.path.join(OUT, name + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[preview] HTML -> {html_path}")
    if not do_render:
        return
    t0 = time.time()
    data = render_list_card(html)
    cost = time.time() - t0
    if not data:
        print(f"[preview] {name} 渲染失败（Playwright 不可用？）")
        return
    img_path = os.path.join(OUT, name + ".jpg")
    with open(img_path, "wb") as f:
        f.write(data)
    print(f"[preview] 图片 -> {img_path}  {len(data) / 1024:.0f}KB  本地渲染 {cost * 1000:.0f}ms")

    t1 = time.time()
    again = render_list_card(html)
    cached_ms = (time.time() - t1) * 1000
    print(f"[preview] 同图命中缓存 {len(again or b'') / 1024:.0f}KB  {cached_ms:.1f}ms")


def main():
    prewarm()
    time.sleep(3.0)  # 等后台预热跑完，测出来的才是「用户实际等待」
    save("novel_list", novel_card_html(
        sample_novel_paged_ses(), timeout=300,
        note="本次搜索消耗 5 积分，剩余 96 积分（发送 /签到 领取每日积分）"))
    save("pan_list", pan_card_html(
        sample_panlist(), page=0, page_size=12, type_filter="",
        title="沙丘2", year="2024", timeout=120))


if __name__ == "__main__":
    main()

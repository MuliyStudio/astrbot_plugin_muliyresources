# -*- coding: utf-8 -*-
"""选集列表工具：识别「集名是否有信息量」，以及分页 / 文本排版。

背景：
  不同影视站的选集标签差别很大——
  · 连续剧：`第1集` / `第01集` / `1` / `01`，名称就是序号，没必要展示；
  · 综艺：`20240621`、`20260419精编特辑`、`20260730上`、`2024_1`，
    这些日期篇 / 上下篇必须展示名称，否则用户根本分不清第几期；
  · 电影：只有 `HD中字` 一条，不走选集流程。

播放线路（playlist 元素）约定：
    {"i": "386760-1", "t": "暴风", "ep_start": 1, "ep_end": 59,
     "eps": [{"n": 1, "name": "第01集", "url": "https://.../py/..."}]}
`n` 是站点播放页里的集序号（不是列表下标），选集时要把它传给
`get_play_m3u8(node_i, n)`；`eps` 缺失时退回按 ep_end 生成纯数字列表。
"""
from __future__ import annotations

import re

# 纯序号：第1集 / 第01期 / 1 / 01（带「第」时后缀可省略）
_EP_WORD = "集期话回章节篇部季"
_SEQ_RE = re.compile(rf"^第\s*\d{{1,4}}\s*[{_EP_WORD}]?$")
_DIGITS_RE = re.compile(r"^\d{1,4}$")
# 8 位日期：20240621 / 2024-06-21 / 2024.6.21 / 2024_06_21
_DATE_RE = re.compile(r"^(\d{4})[-_.]?(\d{1,2})[-_.]?(\d{1,2})(.*)$")

NAMED_PAGE_SIZE = 30      # 有集名（综艺日期/上下篇）时每页 30 条，卡片 3 列
PLAIN_PAGE_SIZE = 60      # 纯序号时每页 60 条，卡片 6 列


def clean_ep_name(name: str) -> str:
    """压掉多余空白（含全角空格）。"""
    return re.sub(r"\s+", " ", str(name or "")).strip()


def episode_is_named(name: str) -> bool:
    """这个集名是否值得展示。

    返回 False：`第1集`、`第01期`、`1`、`01` 这类纯序号；
    返回 True ：日期篇、上下篇、先导片、特辑等带额外信息的名称。
    """
    raw = clean_ep_name(name)
    if not raw:
        return False
    if _DIGITS_RE.match(raw) or _SEQ_RE.match(raw):
        return False
    m = _DATE_RE.match(raw)
    if m:
        mm, dd = int(m.group(2)), int(m.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            # 纯日期（20240621）或日期+后缀（20260730上）都算有信息量
            return True
    return True


def episode_display_name(name: str) -> str:
    """把集名整理成适合展示的短文本；纯序号返回空串。

    `20240621`          -> `2024-06-21`
    `20260419精编特辑`  -> `2026-04-19 精编特辑`
    `第1集` / `1`       -> ``
    """
    raw = clean_ep_name(name)
    if not raw or not episode_is_named(raw):
        return ""
    m = _DATE_RE.match(raw)
    if m:
        y, mm, dd = m.group(1), int(m.group(2)), int(m.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            tail = m.group(4).strip(" \t_-·:：,，")
            date = f"{y}-{mm:02d}-{dd:02d}"
            return f"{date} {tail}".strip()
    return raw


def node_episodes(node: dict) -> list:
    """把播放线路统一成 [{"n": 播放页集序号, "name": 集名}]。

    · 新站（pdy）解析出真实集名时直接用；
    · 旧站（片库 API）只有 ep_end，这里补成纯序号，卡片显示数字键盘。
    """
    node = node or {}
    out = []
    for i, e in enumerate(node.get("eps") or [], 1):
        if isinstance(e, dict):
            name = clean_ep_name(e.get("name") or "")
            try:
                n = int(e.get("n") or i)
            except (TypeError, ValueError):
                n = i
        else:
            name, n = clean_ep_name(e), i
        out.append({"n": n, "name": name})
    if out:
        return out
    try:
        total = int(node.get("ep_end") or 0)
    except (TypeError, ValueError):
        total = 0
    return [{"n": i, "name": ""} for i in range(1, max(0, total) + 1)]


def episodes_are_named(eps: list) -> bool:
    return any(episode_is_named(e.get("name") or "") for e in (eps or []))


def episode_page_size(eps: list) -> int:
    return NAMED_PAGE_SIZE if episodes_are_named(eps) else PLAIN_PAGE_SIZE


def episode_pages(total: int, size: int) -> int:
    return max(1, (max(0, int(total)) + max(1, int(size)) - 1) // max(1, int(size)))


def normalize_ep_page(page: int, total: int, size: int) -> int:
    return max(0, min(int(page or 0), episode_pages(total, size) - 1))


def format_episode_list(detail: dict, node: dict, page: int = 0,
                        page_size: int = 0) -> str:
    """选集卡片的纯文本兜底（与 episode_card_html 同分页口径）。"""
    eps = node_episodes(node)
    total = len(eps)
    detail = detail or {}
    name = detail.get("name") or "未知影视"
    node_t = (node or {}).get("t") or ""
    if total <= 1:
        return f"📺 「{name}」只有 1 个播放片段。"
    named = episodes_are_named(eps)
    size = int(page_size or episode_page_size(eps))
    pages = episode_pages(total, size)
    page = normalize_ep_page(page, total, size)
    st, ed = page * size, min(page * size + size, total)

    head = f"📺 「{name}」共 {total} 集"
    if node_t:
        head += f" · {node_t} 线路"
    if pages > 1:
        head += f" · 第 {page + 1}/{pages} 页"
    lines = [head, "=" * 36, ""]

    if named:
        for i, ep in enumerate(eps[st:ed], st + 1):
            label = episode_display_name(ep.get("name"))
            lines.append(f"{i}  {label}" if label else str(i))
    else:
        nums = [str(i) for i in range(st + 1, ed + 1)]
        for k in range(0, len(nums), 10):
            lines.append("   ".join(nums[k:k + 10]))

    lines.append("")
    lines.append(f"💬 回复数字 1-{total} 选集，例如「5」= 第 5 集。")
    if pages > 1:
        lines.append(f"💡 翻页指令：「上一页」/「下一页」/「末页」/「跳 {page + 1}」")
    lines.append("⏱️ 120 秒无操作自动取消。回复 0 取消。")
    return "\n".join(lines)

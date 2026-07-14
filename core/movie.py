# -*- coding: utf-8 -*-
"""影视搜索 - 适配 a123tv.com (maccms 模板)

数据结构约定：
  search()   -> List[{"id","title","url","meta"}]
  detail()   -> {"name","desc","cover","screenshots",
                 "is_series": bool,
                 "episodes": [{"n","label","url"}] | [],
                 "sources":  [{"n","label","url"}]}     # 切换线路（采集源）
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from .constants import (
    MV_BASE_URL, MV_SEARCH_URL, MV_HEADERS, MV_SOURCE_ICON, logger, emoji_index,
)


# ==================== 通用工具 ====================

def _get_html(url: str, retries: int = 3, timeout: int = 15):
    """带重试的 GET。Cloudflare 拦截时返回 None。"""
    for i in range(retries):
        try:
            r = requests.get(url, headers=MV_HEADERS, timeout=timeout, allow_redirects=True)
            r.encoding = r.apparent_encoding or "utf-8"
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")
            if len(r.text) < 500:
                raise Exception(f"过短 len={len(r.text)}")
            # Cloudflare 拦截检测
            if "安全验证" in r.text and "浏览器安全验证" in r.text:
                raise Exception("Cloudflare拦截")
            return r.text
        except Exception as e:
            logger.debug(f"mv请求失败(第{i+1}次) {url}: {e}")
            if i < retries - 1:
                time.sleep(1.2)
    return None


def _fix_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return MV_BASE_URL + url
    return MV_BASE_URL + "/" + url


# 类别候选词（按从长到短排序，避免「韩国情色片」先被「韩国」截断）
CATEGORY_KEYWORDS = sorted([
    "4K电影", "邵氏电影",
    "韩国情色片", "日本情色片", "大陆情色片", "香港情色片", "台湾情色片",
    "美国情色片", "欧洲情色片", "印度情色片", "东南亚情色片", "其它情色片",
    "国产动漫", "日韩动漫", "欧美动漫", "海外动漫",
    "内地综艺", "港台综艺", "日韩综艺", "欧美综艺", "国外综艺",
    "国产剧", "香港剧", "台湾剧", "韩国剧", "欧美剧", "日本剧", "泰国剧",
    "港台剧", "日韩剧", "海外剧",
    "里番", "动作片", "喜剧片", "爱情片", "科幻片", "恐怖片", "剧情片",
    "战争片", "纪录片", "动画片", "犯罪片", "悬疑片", "奇幻片", "家庭片",
    "古装片", "历史片", "歌舞片",
    "电影", "连续剧", "综艺", "动漫", "福利",
], key=lambda x: -len(x))

# 用最长优先去匹配，避免 「日本情色片」被先匹配成「日本」或「情色片」
_CATEGORY_RE = re.compile(
    "(" + "|".join(re.escape(k) for k in CATEGORY_KEYWORDS) + ")"
)


def _clean_title(raw: str) -> tuple:
    """把 '1080p 89个线路 怪物 日本剧 / 2025年' 这种搜索列表的标题拆成 (title, category, year, meta)。

    - title: 干净的影视名（去掉画质/线路/类别/年份/分隔符）
    - category: 类别字符串，如「日本剧」「喜剧片」「国产动漫」，用于列表中显示【...】
    - year: 年份字符串，如「2025」/「2019」，列表里跟 category 拼成【类别·年份】
    - meta: 仅在类别为空时的兜底信息（如「1080p · 89线路」），一般不会用上
    """
    raw = re.sub(r"\s+", " ", raw).strip()

    # 类别（最长优先匹配）
    category = ""
    m = _CATEGORY_RE.search(raw)
    if m:
        category = m.group(1)

    # 画质
    quality = ""
    m = re.search(r"(4K|4k|HDR|1080p|720p|高清)", raw)
    if m:
        quality = m.group(1)

    # 线路数（保留原始 "1个线路" 用于后续 title.replace）
    sources = ""
    sources_raw = ""  # 形如 "1个线路"，用于在 title 中精确替换
    m = re.search(r"\d+\s*个线路", raw)
    if m:
        sources_raw = m.group(0)
        sources = f"{m.group(0).split('个')[0].strip()}线路"  # 仅用于显示

    # 年份：从 raw 中剔除画质和线路数后再匹配（防止「1080p」被误判为「1080年」）
    raw_no_qs = raw
    if quality:
        raw_no_qs = raw_no_qs.replace(quality, " ")
    if sources:
        raw_no_qs = re.sub(r"\d+\s*个线路", " ", raw_no_qs)
    year = ""
    m = re.search(r"(\d{4})\s*年?", raw_no_qs)
    if m:
        year = m.group(1)

    # 标题：从 raw 里逐个剔除
    title = raw
    for tag in (quality, sources_raw, category, year):
        if tag:
            title = title.replace(tag, "")
    # 二次清理：可能漏掉的画质/线路/年份
    title = re.sub(r"\b(4K|4k|HDR|1080p|720p|高清)\b", "", title)
    title = re.sub(r"\d+\s*个线路", "", title)
    # ★关键修复：raw 形如「庆余年 2 国产剧 / 2024年」, 上面剔除后剩「庆余年 2  / 年」,
    # 之前的 `\d{4}\s*年?` 只能剔「2024年」, 留下孤立的「年」+ 前面的分隔符.
    # 这里直接把 "/ 2024年" 这类尾巴清掉, 然后再清孤立"年"字.
    title = re.sub(r"[\s/·\-—_|]*\d{4}\s*年?[\s/·\-—_|]*", " ", title)
    # 末端 / 中部 孤立的 "年" 字（要求前面是分隔符，不能吞掉 "余年"）
    title = re.sub(r"[\s/·\-—_|]年\s*[\s/·\-—_|]*", " ", title)
    title = re.sub(r"[\s/·\-—_|]*年\s*$", "", title)  # 字符串末尾的孤立"年"
    for kw in CATEGORY_KEYWORDS:
        title = title.replace(kw, "")
    title = re.sub(r"[\s/·\-—_|]+", " ", title).strip(" 《》（）()-—_")

    # meta 只在类别为空时附画质/线路（年份独立返回）
    if category:
        meta = ""
    else:
        meta_parts = [p for p in (quality, sources) if p]
        meta = " · ".join(meta_parts)
    return title, category, year, meta


# ==================== 搜索 ====================

_RE_DETAIL = re.compile(r"^/v/[A-Za-z0-9\-]+\.html$")


def search_movies(keyword: str, max_results: int = 24) -> list:
    """GET a123tv 搜索页，解析结果列表。

    URL 格式：https://a123tv.com/s/{URL编码关键词}.html
    - 注意：之前用的 /index.php?m=vod-search&wd= 实际返回首页热度，不是真搜索
    - 现在用 /s/{kw}.html 才是真搜索接口（如 /s/庆余年.html → 8 部庆余年系列）
    - 该站搜索结果一次性返回，无翻页（最多 36 条）
    """
    # safe="" 让 / 不被编码；不过关键词里基本不会含 / 或其他保留字符
    encoded = requests.utils.quote(keyword, safe="")
    url = MV_SEARCH_URL.format(keyword=encoded)
    logger.info(f"影视搜索URL: {url}")
    html = _get_html(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _RE_DETAIL.match(href):
            continue
        title_raw = a.get_text(" ", strip=True)
        if not title_raw or len(title_raw) < 2:
            continue
        if href in seen:
            continue
        seen.add(href)
        title, category, year, meta = _clean_title(title_raw)
        if not title or len(title) < 1:
            continue
        rid = "mv_" + href.rsplit("/", 1)[-1].replace(".html", "")
        results.append({
            "id": rid,
            "title": title,
            "category": category,
            "year": year,
            "meta": meta,
            "raw_title": title_raw,
            "url": _fix_url(href),
        })
        if len(results) >= max_results:
            break
    logger.info(f"影视搜索完成: {len(results)} 个结果")
    return results


# ==================== 详情 ====================

_RE_PLAY = re.compile(r"^/v/([A-Za-z0-9\-]+)/([A-Za-z0-9]+)\.html$")
_RE_EPISODE = re.compile(r"第\s*(\d{1,3})\s*集\s*$")
_RE_SOURCE_LINE = re.compile(r"线路\s*(\d{1,3})")


def get_movie_detail(url: str) -> dict:
    """GET 详情页，解析：标题/封面/简介/集数列表/切换线路列表。"""
    html = _get_html(url)
    if not html:
        return {
            "name": "获取失败", "desc": "请求失败", "cover": "", "screenshots": [],
            "is_series": False, "episodes": [], "sources": [],
        }

    soup = BeautifulSoup(html, "html.parser")

    # 标题
    name = ""
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        # 兜底：从 <title> 里拆 "《xxx》 - 类别 - 年份 - A123TV"
        t = soup.find("title")
        if t:
            m = re.search(r"《([^》]+)》", t.get_text())
            if m:
                name = m.group(1)

    # 封面：详情页通常只有一张海报图
    cover = ""
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if re.search(r"\.(jpg|jpeg|png|webp)$", src, re.I):
            cover = _fix_url(src)
            break

    # 简介：尝试多种容器
    desc = ""
    for sel in [".desc", ".text", ".info", ".myui-content__text",
                ".detail-content", ".vod-info p", ".content-intro",
                ".module-info .text"]:
        e = soup.select_one(sel)
        if e:
            t = e.get_text(" ", strip=True)
            if len(t) > 20:
                desc = t
                break
    # 也试 meta description
    if not desc:
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            desc = md.get("content", "")

    # 收集所有 /v/xxx/yyy.html 链接，按 URL path 第一段分组
    episodes_map = {}     # n -> {"label","url"}
    sources_map = {}      # n -> {"label","url"}
    # 同一篇详情页里同一部影视，id 是共享前缀 /v/{base}/...
    base_path = None
    m = re.search(r"(/v/([A-Za-z0-9\-]+)/?)", url)
    if m:
        base_path = m.group(1)

    # 取详情页所有 a，分类
    all_play = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m2 = _RE_PLAY.match(href)
        if not m2:
            continue
        if base_path and not href.startswith(base_path):
            # 忽略"相关推荐"里别的影视
            continue
        text = a.get_text(" ", strip=True)
        all_play.append((href, text))

    # 在 all_play 里区分 集数 vs 线路
    for href, text in all_play:
        me = _RE_EPISODE.match(text)
        ms = _RE_SOURCE_LINE.search(text)
        if me:
            n = int(me.group(1))
            if n not in episodes_map or len(text) > len(episodes_map[n]["label"]):
                episodes_map[n] = {"n": n, "label": text, "url": _fix_url(href)}
        elif ms:
            n = int(ms.group(1))
            if n not in sources_map or len(text) > len(sources_map[n]["label"]):
                sources_map[n] = {"n": n, "label": text, "url": _fix_url(href)}
        else:
            # 兜底：看是不是带"第XX集"
            m3 = re.search(r"第\s*(\d{1,3})\s*集", text)
            if m3:
                n = int(m3.group(1))
                if n not in episodes_map or len(text) > len(episodes_map[n]["label"]):
                    episodes_map[n] = {"n": n, "label": text, "url": _fix_url(href)}
            elif "线路" in text or "HD" in text or "1080p" in text or "720p" in text:
                # 算作线路（兜底）
                key = len(sources_map) + 1
                sources_map[key] = {"n": key, "label": text, "url": _fix_url(href)}

    episodes = sorted(episodes_map.values(), key=lambda x: x["n"])
    sources = sorted(sources_map.values(), key=lambda x: x["n"])

    is_series = len(episodes) >= 2  # >=2 集才算剧
    # 剧但只识别到 1 集 → 可能是抓不到，标 None 让用户用兜底
    if episodes and not is_series:
        is_series = True

    # === 解析全剧状态：选集区"共 N 集" + 线路标签里的"全X集完结"/"更新至X集" ===
    total_eps = len(episodes)
    series_status = ""  # "全N集" / "更新至N集" / "完结"

    # 1) 优先从选集区拿总数：<span>选集（共10集）</span>
    head = soup.select_one(".w4-episode-head span, .w4-episode-head")
    if head:
        m_total = re.search(r"共\s*(\d+)\s*集", head.get_text(" ", strip=True))
        if m_total:
            total_eps = int(m_total.group(1))

    # 2) 判断剧集状态：扫描所有 w4-line-item 文本
    #    多种状态可能同时存在（不同线路有不同状态），按"出现次数最多的状态"判定
    #    a123tv 网站自身数据混乱（已完结/更新至可能同时出现），用以下规则：
    #    - "已完结" / "全N集完结" 视为完结
    #    - "更新至 M 集"：若 M == total_eps 也视为完结（"更新至 10 集"+"共 10 集"=已更完）
    if is_series and total_eps:
        all_line_text = " ".join(x["label"] for x in sources)

        # 完结信号 1：显式完结标记
        finished_matches = re.findall(
            r"全\s*\d+\s*集\s*完\s*结|已\s*完\s*结|\[\s*全\s*集\s*\]", all_line_text
        )
        finished_cnt = len(finished_matches)

        # 未完结信号：更新至 N 集
        ongoing_matches = re.findall(r"更新\s*(?:至|第)\s*(\d+)\s*集", all_line_text)
        ongoing_cnt = len(ongoing_matches)

        # 智能归并：
        #   a) 若有"已完结"标记 → 完结
        #   b) 若有"更新至 N 集"且 N < total_eps → 真的还在更新
        #   c) 若有"更新至 total_eps 集" → 实际已更完（a123tv 数据滞后）
        max_updated = max((int(x) for x in ongoing_matches), default=0)

        if finished_cnt >= 1 and ongoing_cnt == 0:
            series_status = "全{}集".format(total_eps)
        elif finished_cnt >= 1 and ongoing_cnt >= 1:
            # 同时存在 → 按 a123tv 数据滞后规律，finished 是真完结信号
            series_status = "全{}集".format(total_eps)
        elif ongoing_cnt >= 1 and max_updated < total_eps:
            series_status = "更新至{}集".format(max_updated)
        elif ongoing_cnt >= 1 and max_updated == total_eps:
            # "更新至10集"+"共10集" → 实际已更完
            series_status = "全{}集".format(total_eps)
        else:
            # 都没识别出来，但既然 total_eps 已知 → 兜底
            series_status = "全{}集".format(total_eps)
    elif is_series and not total_eps:
        series_status = "集数未知"

    return {
        "name": name or "未知影视",
        "desc": (desc or "暂无简介").strip()[:1500],
        "cover": cover,
        "screenshots": [cover] if cover else [],
        "is_series": is_series,
        "episodes": episodes,
        "sources": sources,
        "total_eps": total_eps,
        "series_status": series_status,
    }


# ==================== 播放页 → 真实 m3u8 直链 ====================

_RE_PLAY_PAGE = re.compile(r"^/v/([A-Za-z0-9\-]+)/([A-Za-z0-9]+)z(\d+)\.html$")


def parse_play_page(play_url: str, timeout: int = 12) -> dict:
    """GET a123tv 播放页（形如 /v/{base}/{ld}z{idx}.html），提取 pp.la[] → 所有线路的 m3u8。

    Returns:
        {
          "ld": "6ez6ms",         # 当前线路 id
          "idx": 0,                # 当前集 0-based
          "ep_n": 1,               # 当前集 1-based
          "lines": [
            {"ld": "6ez6ms", "name": "线路224", "eps": 36, "m3u8": "https://..."},
            ...
          ]
        }
        失败时返回 {}。
    """
    empty = {"ld": "", "idx": 0, "ep_n": 0, "lines": []}
    if not play_url:
        return empty
    url = play_url if play_url.startswith("http") else _fix_url(play_url)
    try:
        html = _get_html(url, timeout=timeout)
    except Exception as e:
        logger.warning(f"播放页 {url} 拉取失败: {e}")
        return empty
    if not html:
        return empty
    # 抓 var pp={...};
    m = re.search(r"var\s+pp=(\{.*?\});", html, re.S)
    if not m:
        logger.warning(f"播放页 {url} 找不到 pp 对象")
        return empty
    import json as _json
    try:
        data = _json.loads(m.group(1))
    except Exception as e:
        logger.warning(f"播放页 {url} pp JSON 解析失败: {e}")
        return empty
    la = data.get("la", [])
    ld = data.get("ld", "")
    # 从 URL 拿 idx
    idx = 0
    path_m = re.search(r"/([A-Za-z0-9]+)z(\d+)\.html", url)
    if path_m:
        idx = int(path_m.group(2))
    lines = []
    for item in la:
        try:
            lines.append({
                "ld": item[0],
                "name": item[1],
                "eps": int(item[2]) if item[2] else 0,
                "m3u8": item[4],
            })
        except (IndexError, TypeError):
            continue
    return {
        "ld": ld,
        "idx": idx,
        "ep_n": idx + 1,
        "lines": lines,
    }


def build_play_url(base: str, ld: str, idx_0based: int) -> str:
    """构造 /v/{base}/{ld}z{idx}.html 形式 URL。"""
    return f"/v/{base}/{ld}z{idx_0based}.html"


# ==================== 列表格式化 ====================

def format_movie_list(s: dict) -> str:
    """格式化搜索列表（与 _format_sw_page 同风格）。

    每行格式：`[序号] 影视名  【类别·年份】`
    例：`[1] 怪物  【日本剧·2025】`
    """
    r = s["results"]
    t = len(r)
    p = s.get("page", 0)
    ps = s.get("page_size", 8)
    pt = (t + ps - 1) // ps
    st = p * ps
    ed = min(st + ps, t)
    lines = [f"🎬 共找到 {t} 个「{s.get('keyword','')}」相关影视，当前第 {p+1}/{pt} 页"]
    lines.append("=" * 36)
    lines.append("")
    for i in range(st, ed):
        x = r[i]
        title = x["title"]
        # 标题 32 字以内（中文）
        title_trim = (title[:32] + "...") if len(title) > 35 else title
        category = x.get("category", "")
        year = x.get("year", "")
        # 拼【类别·年份】（缺年份时只显示【类别】）
        if category and year:
            tag = f" 【{category}·{year}】"
        elif category:
            tag = f" 【{category}】"
        elif year:
            tag = f" 【{year}】"
        else:
            tag = ""
        lines.append(f"{emoji_index(i - st + 1, ed - st)} {title_trim}{tag}")
    lines.append("")
    lines.append("─" * 36)
    nav = []
    if st > 0:
        nav.append("「上一页」")
    if ed < t:
        nav.append("「下一页」")
    if pt > 1:
        nav.append(f"「跳转 1~{pt}」")
    if nav:
        lines.append("💡 翻页指令： " + " ｜ ".join(nav))
    lines.append(f"⏱️ {120}秒无操作自动取消。")
    lines.append("回复数字选择影视，回复0取消。")
    return "\n".join(lines)


def format_episodes(detail: dict, max_show: int = 30) -> str:
    """列出选集数（剧时使用）。

    新版（v1.7.5）：只显示总数 + 提示，不再列 [1][2][3] 长列表。
    用户回复任意数字 (1-N) 即可选集。
    """
    eps = detail.get("episodes", [])
    status = detail.get("series_status", "")
    name = detail.get("name", "未知")
    total = len(eps)
    if status:
        head_line = f"📺 「{name}」{status}"
    else:
        head_line = f"📺 「{name}」共 {total} 集"
    lines = [head_line, "=" * 36, ""]
    lines.append(f"💬 请输入想看的集数（1-{total}），例如「5」= 第 5 集")
    lines.append("")
    lines.append("⏱️ 120 秒无操作自动取消。回复 0 取消。")
    return "\n".join(lines)


def _clean_source_label(label: str, name: str, fallback_n: int) -> str:
    """把 '怪物 [2025][更新第10集] 共10集 / 720p ... 线路8' 清洗成 'HD · 720p' 之类。"""
    s = label
    # 1. 去掉标题前缀（如果出现）
    if name:
        s = re.sub(re.escape(name), "", s)
    # 2. 提取画质和标签
    quality_kw = []
    if re.search(r"1080p", s):
        quality_kw.append("1080p")
    if re.search(r"720p", s):
        quality_kw.append("720p")
    if re.search(r"\b4K\b", s):
        quality_kw.append("4K")
    if re.search(r"HDR", s):
        quality_kw.append("HDR")
    # 标签（HD中字 / 更新HD / 正片 / HD / 已完结 / 第N集完结 等）
    tag = ""
    if re.search(r"HD中字", s):
        tag = "HD中字"
    elif re.search(r"更新HD", s):
        tag = "更新HD"
    elif re.search(r"\[HD\]|更新至HD", s):
        tag = "HD"
    elif re.search(r"正片", s):
        tag = "正片"
    elif re.search(r"已完结|完结", s):
        tag = "完结"
    elif re.search(r"更新", s):
        tag = "更新"
    # 3. 清洗：去掉所有方括号内容（包括残缺的）、共N集、年份、线路X、...
    s = re.sub(r"\[[^\]]*\]", "", s)         # 任意 [xxx]
    s = re.sub(r"共\s*\d+\s*集", "", s)
    s = re.sub(r"\[\d{4}\]|\d{4}", "", s)
    s = re.sub(r"线路\s*\d+", "", s)
    s = re.sub(r"\.\.\.", "", s)
    s = re.sub(r"\s+", " ", s).strip(" []·/")
    # 4. 组合
    parts = []
    if tag:
        parts.append(tag)
    if quality_kw:
        # 优先 1080p > 720p > 4K > HDR，取一个
        for q in ["1080p", "4K", "720p", "HDR"]:
            if q in quality_kw:
                parts.append(q)
                break
    if not parts:
        return f"线路{fallback_n}"
    return " · ".join(parts)


def format_sources(detail: dict, page: int = 0, page_size: int = 15) -> str:
    """列出切换线路，按页码返回 15 条/页。

    序号用列表里的位置（1, 2, 3, ...）而不是 a123tv 原始的线路号（8, 21, 32, 134 ...）。
    原始线路号保存到 s["n"] 中，由用户回复时用 index 选中 → 再映射回真实 url。
    """
    srcs = detail.get("sources", [])
    total = len(srcs)
    pt = (total + page_size - 1) // page_size  # 总页数
    page = max(0, min(page, pt - 1))
    st = page * page_size
    ed = min(st + page_size, total)
    show = srcs[st:ed]
    name = detail.get("name", "")
    if pt > 1:
        head = f"🎬 「{name}」共 {total} 条播放线路（第 {page+1}/{pt} 页，每页 {page_size} 条）："
    else:
        head = f"🎬 「{name}」共 {total} 条播放线路："
    lines = [head, "=" * 36, ""]
    for idx, s in enumerate(show, 1):
        clean = _clean_source_label(s["label"], name, s["n"])
        lines.append(f"{emoji_index(idx, ed - st)} {clean}")
    lines.append("")
    if pt > 1:
        lines.append(f"💬 请输入线路序号（1-{ed-st}）选线路；输入「下一页」「上一页」翻页；回复 0 取消。")
    else:
        lines.append(f"💬 请输入线路序号（1-{total}）选线路；回复 0 取消。")
    lines.append("")
    lines.append("⏱️ 120 秒无操作自动取消。")
    return "\n".join(lines)


# ==================== 文本清洗帮助 ====================

def select_episode(detail: dict, num: int):
    """根据用户输入数字取集数。"""
    eps = detail.get("episodes", [])
    for e in eps:
        if e["n"] == num:
            return e
    return None


def select_source(detail: dict, num: int):
    """根据用户输入数字取线路。"""
    srcs = detail.get("sources", [])
    for s in srcs:
        if s["n"] == num:
            return s
    return None
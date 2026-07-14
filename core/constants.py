# -*- coding: utf-8 -*-
"""常量定义"""
import logging

logger = logging.getLogger("astrbot_plugin_muliyresources")

# ==================== 游戏搜索常量 ====================
GAME_BASE_URL = "https://www.xdgame.com"
GAME_SEARCH_URL = GAME_BASE_URL + "/so/{}.html"

GAME_PAN_ICONS = {
    "百度网盘": "☁️", "天翼网盘": "🌤️", "迅雷网盘": "⚡",
    "夸克网盘": "🟣", "阿里网盘": "🟠", "移动网盘": "📱",
    "123网盘": "🔑", "UC网盘": "📂", "磁力下载": "🧲", "正版购买": "💎",
}
GAME_PAN_COLORS = {
    "百度网盘": "#3b82f6", "天翼网盘": "#06b6d4", "迅雷网盘": "#f59e0b",
    "夸克网盘": "#8b5cf6", "阿里网盘": "#f97316", "移动网盘": "#10b981",
    "123网盘": "#6366f1", "UC网盘": "#64748b", "磁力下载": "#ef4444", "其他": "#6b7280",
}
GAME_PAN_DOMAINS = [
    "pan.baidu.com", "cloud.189.cn", "pan.xunlei.com",
    "pan.quark.cn", "aliyundrive.com", "caiyun.139.com",
    "share.123pan.com", "uc.cn", "drive.uc.cn",
]

# ==================== 软件常量 ====================
SW_BASE_URL = "https://www.x6d.com"
SW_LIST_URL = "https://www.x6d.com/html/23.html"
SW_SEARCH_URL = SW_BASE_URL + "/daowangsousuo?q={}"

SW_DISK_ICONS = {
    "百度网盘": "☁️", "天翼网盘": "📱", "夸克网盘": "🚀",
    "蓝奏网盘": "💾", "迅雷网盘": "⚡", "123网盘": "🔑",
    "阿里网盘": "🟠", "UC网盘": "📂", "移动网盘": "📱", "移动云盘": "📱",
}
SW_PAN_COLORS = {
    "百度网盘": "#3b82f6", "天翼网盘": "#06b6d4", "夸克网盘": "#8b5cf6",
    "蓝奏网盘": "#10b981", "迅雷网盘": "#f59e0b", "123网盘": "#6366f1",
    "阿里网盘": "#f97316", "移动云盘": "#e94560", "移动网盘": "#e94560",
    "UC网盘": "#64748b", "其他": "#6b7280",
}
SW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": SW_BASE_URL + "/",
}

# ==================== 影视搜索常量 (a123tv.com) ====================
MV_BASE_URL = "https://a123tv.com"
# a123tv 真搜索接口：/s/{URL编码关键词}.html（之前用的 /index.php?m=vod-search&wd= 返回首页热度列表，不是真搜索）
MV_SEARCH_URL = MV_BASE_URL + "/s/{keyword}.html"
MV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": MV_BASE_URL + "/",
}
# 单行展示用图标（仅一种资源类型：在线播放 → 切换线路）
MV_SOURCE_ICON = "🎬"

# ==================== 新站影视 (教父.com / 挂了.com) ====================
# 挂了.com：域名存活监控站，check.js 里列出所有备用影视域名
MULIY_GUALE_URL = "https://www.xn--ykq321c.com"
# 封面图主机
MULIY_IMG_HOST = "https://s.tutu.pm"
# 默认固定域名（留空则自动从挂了.com 探测最低延迟）；教父.com 的 Punycode
MULIY_DEFAULT_DOMAIN = "https://www.xn--wcv59z.com"
# 网盘类型图标
MULIY_PAN_ICONS = {
    "迅雷网盘": "⚡", "百度网盘": "☁️", "夸克网盘": "🟣",
    "天翼网盘": "🌤️", "115网盘": "🗂️", "UC网盘": "📂", "阿里网盘": "🟠",
}
MULIY_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ==================== 通用常量 ====================
SESSION_TIMEOUT = 300


def parse_cookie_string(raw: str) -> dict:
    """将 document.cookie 字符串解析为字典"""
    result = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


# ——— 搜索关键词清洗 ———
# 去掉常见的统称后缀，保留具体名称
# 例如："赛车游戏" → "赛车"，"微信软件" → "微信"
_SEARCH_SUFFIX_RE = __import__("re").compile(
    r"(?:游戏|游戏软件|电脑游戏|pc游戏|端游|手游|软件|应用|工具|程序|app|APP)?$",
    __import__("re").IGNORECASE
)


def clean_search_keyword(keyword: str) -> str:
    """
    从用户输入中提取纯粹的搜索关键词。
    - 去掉「游戏」「软件」「应用」等统称后缀
    - 去掉首尾空格
    - 若全部被去掉则返回原词（不返回空字符串）

    示例：
        "赛车游戏"    → "赛车"
        "微信软件"    → "微信"
        "Photoshop"  → "Photoshop"
        "原神"        → "原神"
        "游戏软件"    → "游戏软件"
    """
    keyword = keyword.strip()
    cleaned = _SEARCH_SUFFIX_RE.sub("", keyword).strip()
    return cleaned if cleaned else keyword


# ==================== 游戏简介提取 ====================
# 描述标题关键词（命中则其后为游戏简介）
_DESC_HEAD_PATTERNS = ["游戏介绍", "游戏简介", "关于这款游戏", "关于游戏", "游戏说明",
                       "剧情简介", "游戏背景", "背景故事", "游戏详情", "游戏故事"]
# 截止标题/标记关键词（命中则描述结束，其后多为下载/补丁/截图/版本等非描述区块）
# 注意：不要放「版本信息」这类描述正文里常见开头词，否则会把以它开头的正文截断为空
_DESC_CUTOFF = ["游戏视频", "游戏截图", "版本介绍", "游戏特色", "配置要求",
               "配置需求", "下载地址", "下载方式", "下载链接", "网盘", "联机补丁", "修改器",
               "安装说明", "网友评论", "相关游戏", "游戏评分", "游戏资讯", "同类推荐",
               "游戏补丁", "更新日志", "游戏模组", "汉化说明"]

_HEAD_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _clean_game_desc(t: str) -> str:
    """清洗简介文本：去除残留标题行、合并多余空行、限制长度。保留 \n 作为分段。"""
    import re as _re
    t = (t or "").strip()
    # 去掉开头的「游戏介绍：/关于这款游戏：」等残留标题
    t = _re.sub(r"^(游戏介绍|游戏简介|关于这款游戏|关于游戏|游戏说明|剧情简介|游戏背景|游戏详情|游戏故事)[：:、\s]*", "", t)
    # 合并 3+ 连续空行
    t = _re.sub(r"\n{3,}", "\n\n", t).strip()
    # 去掉每段首尾空白
    t = "\n".join(p.strip() for p in t.split("\n") if p.strip())
    return t[:2000]


def extract_game_description(soup) -> str:
    """从游戏详情页 soup 中提取游戏简介。

    策略（优先到兜底）：
      1) 专有简介容器（.game-desc / .desc / .game-intro 等）
      2) 正文容器内按标题（h1-h6）定位「游戏介绍/关于这款游戏」等，抽取其后
         的 <p>/<div> 文本，直到下一个标题或截止标记（联机补丁/修改器/下载等）
         —— 这样能自动排除「联机补丁/修改器/版本介绍」等非描述区块，并保留分段
      3) 文本级兜底：在整段文本中定位描述标记，截到第一个截止标记
      4) 整块正文兜底：截到第一个截止标记
    返回的字符串以 \\n 分隔段落（供 HTML 卡片渲染为 <p>，纯文本消息中显示为换行）。
    """
    import re as _re
    # 1) 专有简介容器
    for sel in (".game-info .info", ".game-desc", ".desc", ".info-text", ".game-intro",
                ".intro", ".summary", ".game-summary", ".article-content .desc"):
        node = soup.select_one(sel)
        if node:
            t = node.get_text("\n", strip=True)
            if len(t.strip()) > 10:
                return _clean_game_desc(t)

    cont = soup.select_one(".content, .single-content, .entry-content, .post-content, article, .article")
    if not cont:
        cont = soup

    # 2) 按标题定位描述段落
    head = None
    for h in cont.find_all(_HEAD_TAGS):
        ht = h.get_text(strip=True)
        if any(p in ht for p in _DESC_HEAD_PATTERNS) and not any(c in ht for c in _DESC_CUTOFF):
            head = h
            break
    if head:
        parts = []
        nxt = head.find_next_sibling()
        while nxt:
            if nxt.name in _HEAD_TAGS:
                htext = nxt.get_text(strip=True)
                # 遇到任何标题都停止（无论是截止类还是其它副标题）
                break
            if nxt.name == "p":
                t = nxt.get_text(" ", strip=True)
                if t:
                    parts.append(t)
            elif nxt.name == "div":
                ps = nxt.find_all("p")
                if ps:
                    for p in ps:
                        t = p.get_text(" ", strip=True)
                        if t:
                            parts.append(t)
                else:
                    t = nxt.get_text(" ", strip=True)
                    if t and len(t) > 5:
                        parts.append(t)
            elif nxt.name in ("ul", "ol", "blockquote"):
                t = nxt.get_text("\n", strip=True)
                if t:
                    parts.append(t)
            nxt = nxt.find_next_sibling()
        if parts:
            return _clean_game_desc("\n".join(parts))

    # 3) 文本级兜底：整段文本中定位描述标记
    full = cont.get_text("\n", strip=True)
    for pat in _DESC_HEAD_PATTERNS:
        mm = _re.search(pat + r"[:：]?\s*(.+)", full, _re.S)
        if mm:
            seg = mm.group(1)
            cut = None
            for c in _DESC_CUTOFF:
                idx = seg.find(c)
                if idx != -1:
                    cut = idx if cut is None else min(cut, idx)
            if cut is not None:
                seg = seg[:cut]
            return _clean_game_desc(seg)

    # 4) 整块正文兜底：截到第一个截止标记
    cut = None
    for c in _DESC_CUTOFF:
        idx = full.find(c)
        if idx != -1:
            cut = idx if cut is None else min(cut, idx)
    if cut is not None:
        full = full[:cut]
    return _clean_game_desc(full)


# ==================== emoji 序号 ====================
# 用于「不超过 9 个」的待选项列表，把前缀 [1]/[2]… 换成 1⃣2⃣3⃣…，
# 方便用户在 QQ/微信里可视化点选。超过 9 个（翻页后）回落纯数字 [n]。
_EMOJI_INDEX = ["", "1⃣", "2⃣", "3⃣", "4⃣", "5⃣", "6⃣", "7⃣", "8⃣", "9⃣"]


def emoji_index(n: int, total: int | None = None) -> str:
    """生成带序号前缀的标签。

    - total 给定且 <=9（或 total 未给且 n<=9）时：1~9 返回 emoji 序号 1⃣2⃣3⃣…
    - 否则回落为纯数字 [n]
    这样「不超过 9 个」的列表用 emoji 直观展示，超过 9 个（翻页后）仍用 [n]，不会混排。
    """
    use_emoji = (total is not None and total <= 9) or (total is None and n <= 9)
    if use_emoji and 1 <= n <= 9:
        return _EMOJI_INDEX[n]
    return f"[{n}]"


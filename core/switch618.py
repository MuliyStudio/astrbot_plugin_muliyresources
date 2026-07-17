# -*- coding: utf-8 -*-
"""switch618.com 游戏搜索源（自动过数学验证码 + 扫码关注登录获取 Cookie）

与 xdgame.com 源并列，由插件配置 game_source=auto 自动切换：
  - 配置了 xdgame 账号密码 → 用 xdgame 源
  - 未配置 → 用 switch618 源（免 xdgame 账号，但需登录 Cookie 才能拿下载链接）

搜索流程（已实测破解）：
  1. GET /?s=关键词 → 数学验证码页（诱饵题恒定 44，不能直接答）
  2. 连续 POST result=当前页题答案，跟随 esc_search_result，2~3 次通过
  3. 拿到真实搜索结果

详情/下载流程：
  1. 进详情页 → 提取 erphpdown 中转页 download.php?postid=xxx
  2. 中转页 JS 跳转 window.location='down/like.switch618.com/xxx.html'
  3. down 页提取 pan.quark/baidu 真实链接 + 提取码

登录流程（扫码关注 → 验证码 → ews_login）：
  1. GET /login?action=mp（二维码为固定公众号图片）
  2. 管理员扫码关注公众号 → 公众号自动回复验证码
  3. 管理员把验证码发给机器人
  4. POST /wp-admin/admin-ajax.php?action=ews_login&code=验证码
  5. status=1 成功 → 提取 wordpress_logged_in_xxx Cookie
"""
import re
import time
import datetime
import io
import base64
from urllib.parse import unquote, urlparse
from .constants import logger, parse_cookie_string, extract_game_description

try:
    import requests
except ImportError:
    requests = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
try:
    from PIL import Image
except ImportError:
    Image = None

S618_BASE = "https://www.switch618.com/"
S618_AJAX = S618_BASE + "wp-admin/admin-ajax.php"
S618_QR_IMG = S618_BASE + "wp-content/uploads/2023/04/02122726137.jpg"
S618_LOGIN_MP = S618_BASE + "login?action=mp"

S618_PAN_ICONS = {
    "夸克网盘": "🟣", "百度网盘": "☁️", "天翼网盘": "🌤️", "迅雷网盘": "⚡",
    "阿里网盘": "🟠", "123网盘": "🔑", "UC网盘": "📂", "磁力下载": "🧲", "其他": "📥",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ====================================================================
#  会话 / 验证码
# ====================================================================

def _session(cookie_str: str = "") -> "requests.Session":
    s = requests.Session()
    s.headers.update(HEADERS)
    if cookie_str:
        s.cookies.update(parse_cookie_string(cookie_str))
    return s


def solve_math_captcha(html: str):
    """从 HTML 提取 N + M 算式并返回 (算式文本, 答案)。"""
    m = re.search(r'(\d+)\s*\+\s*(\d+)', html)
    if not m:
        return None, None
    a, b = int(m.group(1)), int(m.group(2))
    return f"{a}+{b}", a + b


def is_captcha(text: str) -> bool:
    return "人机验证" in text or "erphp-search-captcha" in text


# ====================================================================
#  标题清洗：版本号 / 平台 / 语言 / 类型 等元信息整理
# ====================================================================

# 标题清洗模式："parenthesize"=把元信息用括号括起来；"remove"=直接删除
TITLE_CLEAN_MODE = "parenthesize"

# 版本号：v1.72.3717 / v889.22 / 1.0.8 / 1.0.1013.17
_VER_RE = re.compile(r'(?<![A-Za-z0-9])v?\d+(?:\.\d+){1,3}(?![A-Za-z])', re.I)
# 英文副标题：(Grand Theft Auto V)
_ENG_SUB_RE = re.compile(r'\([^()]*[A-Za-z][^()]*\)')

# 登录二维码图片（需从截图中排除）
_QR_IMG_MARK = "02122726137"


def clean_game_title(title: str, mode: str = None) -> str:
    """清洗 switch618 游戏/软件标题。

    处理对象：开头数字ID、版本号、平台/语言/类型元信息、英文副标题。
    mode="parenthesize"（默认）：主名 + 元信息括号，如
        《侠盗猎车手5传承版/GTA5传承版》 (v3725.0 | 中文 | 免安装硬盘版)
    mode="remove"：仅保留主名，去掉版本号/平台/语言/类型及英文副标题。
    """
    if mode is None:
        mode = TITLE_CLEAN_MODE
    if not title:
        return title
    t = title.strip()
    # 1) 去掉开头的数字ID（如 1219、1211）
    t = re.sub(r'^\s*\d+\s*', '', t)
    # 2) 按 | 或 ｜ 分段：第一段为主名候选，其余为元信息
    segs = [s.strip() for s in re.split(r'\s*[｜|]\s*', t) if s.strip()]
    main = segs[0] if segs else t
    meta = list(segs[1:])

    # 3) 主名里的版本号：提取到元信息并从主名移除
    for ver in _VER_RE.findall(main):
        if ver not in meta:
            meta.append(ver)
    main = _VER_RE.sub('', main)

    # 4) 主名里的英文副标题
    main = _ENG_SUB_RE.sub('', main)
    main = re.sub(r'\s+', ' ', main).strip()
    main = re.sub(r'[（(]\s*[）)]', '', main).strip()  # 去掉残留空壳 ()

    # 5) 元信息清洗：空壳只保留其中的版本号
    clean_meta = []
    for m in meta:
        mv = _VER_RE.search(m)
        core = _VER_RE.sub('', m).strip(' |｜+（）()')
        keep = mv.group(0) if (mv and not core) else m.strip(' |｜+')
        if keep and keep not in clean_meta:
            clean_meta.append(keep)
    clean_meta = list(dict.fromkeys(clean_meta))

    if mode == "remove":
        return main
    if clean_meta:
        return f"{main} ({' | '.join(clean_meta)})"
    return main


# Steam CDN（截图/封面实际托管处，页面里是 <img> 直链）
_STEAM_CDN_RE = re.compile(
    r'(?:shared\.cdn\.queniuqe\.com|cdn\.cloudflare\.steamstatic\.com|'
    r'shared\.akamai\.steamstatic\.com|steamcdn-a\.akamaihd\.net)/', re.I)
# 站内真实图片：www.switch618.com/<数字>.webp|jpg|png 或 wp-content/uploads/<年>/<月>/...
_S618_IMG_RE = re.compile(
    r'(?:www\.switch618\.com/\d+\.(?:webp|jpe?g|png))|'
    r'wp-content/uploads/\d{4}/\d{2}/[^\s"\'<>)]+\.(?:webp|jpe?g|png)', re.I)
# 需排除的非内容图
_IMG_EXCLUDE = ("/avatar/", "/gravatar/", "wp-content/themes/", "logo", "favicon",
                "icon", "banner", _QR_IMG_MARK, "cropped-")


def extract_detail_images(soup, url: str):
    """从 switch618 详情页提取游戏图（封面 + 截图）。返回 (cover, screenshots)。

    真实页面结构（已实测 for /14771.html 等）：
      - 封面：站内 https://www.switch618.com/<数字>.webp 或 wp-content/uploads/YYYY/MM/header-*.jpg
      - 截图：Steam CDN https://shared.cdn.queniuqe.com/store_item_assets/steam/apps/<appid>/ss_*.1920x1080.jpg
              （也可能为 cdn.cloudflare.steamstatic.com / shared.akamai.steamstatic.com）
    旧逻辑只认 wp-content/uploads，导致 Steam CDN 截图一张都拿不到；这里两种都抓。
    始终排除主题头像/logo/二维码/裁剪 favicon 等。
    """
    cover = ""
    screenshots = []
    seen = set()

    for im in soup.find_all("img"):
        src = (im.get("data-src") or im.get("src") or im.get("data-original")
               or im.get("data-lazy-src") or "")
        if not src:
            continue
        low = src.lower()
        if any(k in low for k in _IMG_EXCLUDE):
            continue
        if "avatar" in (im.get("class") or []):
            continue
        # 只接受「看起来是图片」的 URL：Steam CDN / 站内 uploads·数字图 / 带扩展名
        if not (_STEAM_CDN_RE.search(low) or _S618_IMG_RE.search(low)
                or re.search(r'\.(webp|jpe?g|png)', low)):
            continue
        u = src if src.startswith("http") else (S618_BASE + src if src.startswith("/") else src)
        if u in seen:
            continue
        seen.add(u)

        if _STEAM_CDN_RE.search(low) and re.search(r'/ss_', low):
            # Steam 截图（ss_ 前缀）
            screenshots.append(u)
        elif _STEAM_CDN_RE.search(low):
            # 其它 Steam CDN 图（capsule/header 等）作为封面候选
            if not cover:
                cover = u
        else:
            # 站内 uploads / 数字图：第一张当封面，其余当截图补充
            if not cover:
                cover = u
            else:
                screenshots.append(u)

    screenshots = screenshots[:8]
    if not cover and screenshots:
        cover = screenshots[0]
    return cover, screenshots


# ====================================================================
#  游戏搜索（自动过数学验证码）
# ====================================================================

def search_games_618(keyword: str, max_results: int = 32, max_try: int = 8) -> list:
    """搜索游戏(switch618.com)。返回 [{id,title,url,type,date},...] 与 xdgame 结构兼容。"""
    if not requests or not BeautifulSoup:
        logger.warning("[switch618] 缺少 requests/bs4")
        return []
    s = _session()
    try:
        r = s.get(S618_BASE, params={"s": keyword}, timeout=30)
    except Exception as e:
        logger.error(f"[switch618] 搜索请求失败: {e}")
        return []
    for _ in range(max_try):
        if not is_captcha(r.text):
            break
        _, ans = solve_math_captcha(r.text)
        if ans is None:
            break
        r = s.post(S618_BASE, params={"s": keyword}, data={"result": str(ans)},
                   headers={**HEADERS, "Referer": r.url}, timeout=30)
    if is_captcha(r.text):
        logger.warning("[switch618] 多次尝试仍未通过验证码")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if re.search(r'/\d+\.html', href) and text and len(text) > 3:
            if href not in seen and not re.match(r'^\d+$', text):
                seen.add(href)
                m = re.search(r'/(\d+)\.html', href)
                gid = m.group(1) if m else str(len(results) + 1)
                # 清洗标题：去掉数字ID、版本号、平台/语言/类型元信息、英文副标题
                title = clean_game_title(text)
                results.append({"id": gid, "title": title, "url": href, "type": "", "date": ""})
            if len(results) >= max_results:
                break
    logger.info(f"[switch618] 搜索 '{keyword}' 完成: {len(results)} 条")
    return results


# ====================================================================
#  详情 / 下载链接解析
# ====================================================================

def _pan_name(href: str) -> str:
    h = href.lower()
    if "pan.quark.cn" in h: return "夸克网盘"
    if "pan.baidu.com" in h: return "百度网盘"
    if "pan.xunlei.com" in h: return "迅雷网盘"
    if "cloud.189" in h: return "天翼网盘"
    if "123pan" in h or "share.123pan" in h: return "123网盘"
    if "lanzou" in h: return "蓝奏网盘"
    if "aliyun" in h or "aliyundrive" in h: return "阿里网盘"
    if "ed2k://" in h: return "其他"
    if "magnet:" in h: return "磁力下载"
    return "其他"


def _resolve_dl_all(session, dl_url: str, referer: str) -> list:
    """访问中转页 → 提取 window.location 跳转 → down 页提取【所有】真实网盘链接。"""
    out = []
    seen = set()
    try:
        r2 = session.get(dl_url, headers={**HEADERS, "Referer": referer},
                         allow_redirects=False, timeout=20)
        m = re.search(r"window\.location\s*=\s*['\"](https?://[^'\"]+)['\"]", r2.text)
        if not m:
            return out
        down_url = m.group(1)
        r3 = requests.get(down_url, headers={**HEADERS, "Referer": dl_url}, timeout=20)
        soup = BeautifulSoup(r3.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(d in href for d in ["pan.quark.cn", "pan.baidu.com", "pan.xunlei.com",
                                       "cloud.189", "123pan", "lanzou", "aliyundrive",
                                       "caiyun", "uc.cn", "drive.uc"]):
                if href in seen:
                    continue
                seen.add(href)
                ctx = r3.text[r3.text.find(href): r3.text.find(href) + 180]
                mc = re.search(r'提取码[:：]\s*([A-Za-z0-9]+)', ctx)
                code = mc.group(1) if mc else ""
                out.append({"pan": _pan_name(href), "real_url": href, "code": code})
        # 兜底：磁力 / ed2k
        for pat in [r'magnet:\?xt=urn:btih:[A-Za-z0-9]+', r'ed2k://[^\s"\'<>]+']:
            mm = re.search(pat, r3.text)
            if mm and mm.group(0) not in seen:
                out.append({"pan": "磁力下载", "real_url": mm.group(0), "code": ""})
                break
    except Exception as e:
        logger.error(f"[switch618] 解析下载链接异常: {e}")
    return out


def get_game_detail_618(url: str, cookie_str: str = "") -> dict:
    """获取游戏详情(switch618.com)。返回 {name,desc,cover,screenshots,download_links,need_login}。

    need_login=True 表示详情页要求登录才能看到下载区（Cookie 失效或未配置），
    调用方应提示用户刷新 Cookie。
    """
    if not requests or not BeautifulSoup:
        return {"name": "获取失败", "desc": "缺少依赖", "cover": "", "screenshots": [], "download_links": [], "need_login": False}
    s = _session(cookie_str)
    try:
        resp = s.get(url, timeout=30)
    except Exception as e:
        return {"name": "获取失败", "desc": str(e)[:100], "cover": "", "screenshots": [], "download_links": [], "need_login": False}

    # 详情页若也有验证码，跟随
    for _ in range(8):
        if not is_captcha(resp.text):
            break
        _, ans = solve_math_captcha(resp.text)
        if ans is None:
            break
        resp = s.post(url, data={"result": str(ans)},
                      headers={**HEADERS, "Referer": resp.url}, timeout=30)

    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("title")
    raw_name = re.sub(r"\s*[-–|]\s*.*$", "", title_tag.get_text(strip=True)).strip() if title_tag else ""
    name = clean_game_title(raw_name)

    # 封面 + 截图：从正文容器抓取所有 uploads 图片（兼容两种页面布局）
    cover, screenshots = extract_detail_images(soup, url)

    # 简介：基于 DOM 标题定位「关于这款游戏/游戏介绍」段落，排除联机补丁/修改器等区块，保留分段
    desc = extract_game_description(soup)
    if not desc or len(desc) < 20:
        md = soup.find("meta", attrs={"name": "description"})
        desc = md.get("content", "") if md else (desc or "暂无简介")
    desc = desc.strip()[:2000]

    # 提取 erphpdown 中转页链接
    dl_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "erphpdown/download.php" in href or "download.php?postid" in href:
            dl_urls.append(href if href.startswith("http") else S618_BASE + href)
    dl_urls = list(dict.fromkeys(dl_urls))

    links = []
    seen_urls = set()
    for du in dl_urls[:2]:
        for sub in _resolve_dl_all(s, du, url):
            if sub["real_url"] in seen_urls:
                continue
            seen_urls.add(sub["real_url"])
            links.append({"pan": sub["pan"], "api_url": du,
                          "real_url": sub["real_url"], "code": sub["code"]})
        if links:
            break

    # 是否需要登录：下载区要求登录（Cookie 失效）时详情页正文含「请先登录」
    need_login = (len(links) == 0) and bool(
        re.search(r'请先登录', (cont.get_text() if cont else resp.text))
    )

    return {"name": name, "desc": desc, "cover": cover,
            "screenshots": screenshots, "download_links": links, "need_login": need_login}


def resolve_download_link_618(link: dict, cookie_str: str = "") -> dict:
    """解析 switch618 下载链接的真实地址和提取码（详情阶段已解析则可跳过）。"""
    ru = link.get("real_url", "")
    if ru and ru.startswith("http"):
        return link  # 详情阶段已拿到真实地址
    s = _session(cookie_str)
    subs = _resolve_dl_all(s, link.get("api_url", ""), "")
    for sub in subs:
        if sub["real_url"] == ru or (not ru):
            link["real_url"] = sub["real_url"]
            link["code"] = sub.get("code", "")
            link["pan"] = sub.get("pan", link.get("pan", "其他"))
            return link
    if subs:
        link["real_url"] = subs[0]["real_url"]
        link["code"] = subs[0].get("code", "")
        link["pan"] = subs[0].get("pan", link.get("pan", "其他"))
    else:
        link["real_url"] = "(获取失败)"
        link["code"] = ""
    return link


# ====================================================================
#  Cookie 有效性检查
# ====================================================================

def check_618_cookie(cookie_str: str):
    """检测 switch618 Cookie 有效性。返回 (status, message)
       status: True=有效, False=失效, None=无法确认"""
    if not cookie_str:
        return False, "Cookie 未配置"
    if not requests:
        return None, "缺少 requests"
    s = _session(cookie_str)
    try:
        resp = s.get(S618_BASE, timeout=15)
        resp.encoding = "utf-8"
        t = resp.text
        if "请先登录" in t or "登录后可见" in t or "down signin-loader" in t:
            return False, "Cookie 已失效"
        if "action=logout" in t or "我的账户" in t or "用户中心" in t or "退出登录" in t:
            return True, "Cookie 有效"
        return None, "无法确认登录态"
    except Exception as e:
        return False, f"检测失败: {e}"


# ====================================================================
#  扫码关注登录（ews_login）
# ====================================================================

def get_qr_image_bytes() -> bytes:
    """返回 switch618 公众号二维码图片字节（JPEG，固定图片）。失败返回 b''。"""
    try:
        r = requests.get(S618_QR_IMG,
                         headers={"User-Agent": HEADERS["User-Agent"], "Referer": S618_BASE},
                         timeout=15)
        if r.status_code == 200 and len(r.content) > 100:
            logger.info(f"[switch618] 二维码下载成功 {len(r.content)} 字节")
            return r.content
    except Exception as e:
        logger.warning(f"[switch618] 二维码下载失败: {e}")
    return b""


def submit_618_login(code: str):
    """用验证码提交 ews_login 登录。
    返回 (ok:bool, cookie_str_or_error:str)。成功时 cookie_str 为 'wordpress_logged_in_xxx=...'。"""
    if not requests:
        return False, "缺少 requests"
    s = _session()
    try:
        # 先 GET mp 页面建立基础会话
        s.get(S618_LOGIN_MP, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
        r = s.post(S618_AJAX,
                   data={"action": "ews_login", "code": (code or "").strip()},
                   headers={**HEADERS, "Referer": S618_LOGIN_MP,
                            "X-Requested-With": "XMLHttpRequest"},
                   timeout=15)
        try:
            data = r.json()
        except Exception:
            return False, f"响应非 JSON: {r.text[:100]}"
        if str(data.get("status")) != "1":
            return False, "验证码错误或未关注公众号"
        # 登录成功，提取 wordpress_logged_in cookie
        cookie_str = _extract_logged_in(s)
        if cookie_str:
            return True, cookie_str
        # 兜底：再 GET 一次首页让 cookie 落袋
        s.get(S618_BASE, timeout=15)
        cookie_str = _extract_logged_in(s)
        if cookie_str:
            return True, cookie_str
        return False, "登录成功但未提取到 Cookie"
    except Exception as e:
        return False, f"提交异常: {e}"


def _extract_logged_in(session) -> str:
    for name, value in session.cookies.items():
        if name.startswith("wordpress_logged_in_"):
            return f"{name}={value}"
    return ""


# ====================================================================
#  游戏日报（每日新增抓取，与 xdgame 日报模板共用卡通 HTML）
#  列表页 https://www.switch618.com/pcgames/page/N/ 每页 15 款，通常前三页为今日新增。
#  判定今日：取首款游戏 span.post-sign 文本，含「新游」或今日日期(月日) 即视为今日新增。
#  简介：优先取详情页「玩法深度解析」区块。
# ====================================================================

S618_PCGAMES_TPL = S618_BASE + "pcgames/page/{}/"


def fetch_618(url: str, cookie_str: str = "", retries: int = 3):
    """带 Cookie 反爬挑战的 GET（switch618 首次请求 403 并返回 window.location 重定向，
    带 Set-Cookie 再请求一次即返回真页）。返回 HTML 文本或 None。

    说明：列表页/详情页的简介与截图均为公开内容，无需登录 Cookie；
    传入的 cookie_str 仅用于详情页若要求登录时透传（不影响日报基本抓取）。
    """
    for _ in range(retries):
        try:
            s = _session(cookie_str)
            r1 = s.get(url, timeout=30)
            r1.encoding = "utf-8"
            if r1.status_code == 403 and "window.location" in r1.text:
                # 挑战：带服务器下发的 Set-Cookie 重新请求
                r2 = s.get(url, timeout=30)
                r2.encoding = "utf-8"
                if len(r2.text) > 500:
                    return r2.text
                r3 = s.get(url, timeout=30)  # 极少数情况需第三次（cookie 未落稳）
                r3.encoding = "utf-8"
                if len(r3.text) > 500:
                    return r3.text
            elif len(r1.text) > 500:
                return r1.text
        except Exception as e:
            logger.debug(f"[switch618日报] 请求失败: {e}")
            time.sleep(2)
    return None


def parse_618_list(html: str) -> list:
    """解析 switch618 pcgames 列表页，返回每款游戏基础信息（含 span 标记用于今日判定）。"""
    soup = BeautifulSoup(html, "html.parser")
    posts = soup.select("#posts > div")
    games = []
    for div in posts:
        a = div.select_one("h3 > a") or div.select_one("a[href*='.html']")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href or not re.search(r"/\d+\.html", href):
            continue
        detail_url = (href if href.startswith("http")
                      else (S618_BASE + href if href.startswith("/") else S618_BASE + "/" + href))
        # span.post-sign：如「新游」或日期标记，移除后再清洗标题
        span = a.select_one("span.post-sign")
        span_text = span.get_text(strip=True) if span else ""
        raw_title = a.get_text(" ", strip=True)
        if span_text and span_text in raw_title:
            raw_title = raw_title.replace(span_text, "")
        title = clean_game_title(raw_title)
        # 封面：优先 data-lazy-src（<noscript> 兜底 src 是直链，但 data-lazy-src 更稳）
        img = div.select_one("div.img img.thumb") or div.select_one("div.img img")
        cover = ""
        if img:
            cover = (img.get("data-lazy-src") or img.get("data-src")
                     or img.get("src", "")).strip()
            if cover.startswith("data:image"):
                cover = ""
            if cover and not cover.startswith("http"):
                cover = S618_BASE + cover if cover.startswith("/") else S618_BASE + "/" + cover
        cat = div.select_one("div.cat a")
        category = cat.get_text(strip=True) if cat else ""
        time_el = div.select_one("div.grid-meta span.time")
        time_text = time_el.get_text(strip=True) if time_el else ""
        if title and detail_url:
            games.append({
                "title": title, "detail_url": detail_url, "cover": cover,
                "category": category, "time_text": time_text, "span_text": span_text,
                "intro": "", "cover_b64": "", "shots_b64": [],
            })
    return games


def _is_today_618(span_text: str) -> bool:
    """依据首款游戏 span 标记判断本页是否为今日新增。

    命中条件：含「新游」或含今日日期（支持 07-16 / 7-16 / 2026-07-16 等写法）。
    """
    if not span_text:
        return False
    t = span_text.strip()
    if "新游" in t:
        return True
    today = datetime.date.today()
    candidates = {
        today.strftime("%m%d"),            # 0716
        f"{today.month}{today.day}",        # 716
        today.strftime("%m-%d"),           # 07-16
        f"{today.month}-{today.day}",      # 7-16
        today.strftime("%Y-%m-%d"),        # 2026-07-16
        today.strftime("%Y年%m月%d日"),
    }
    return any(c in t for c in candidates)


def extract_wanfa(soup) -> str:
    """从详情页提取「玩法深度解析」区块正文（连续 <p> 直到下一个标题）。"""
    for h in soup.find_all(["h2", "h3", "h4"]):
        if "玩法深度解析" in h.get_text(strip=True):
            parts = []
            nxt = h.find_next_sibling()
            while nxt and nxt.name not in ("h2", "h3", "h4"):
                if nxt.name == "p":
                    t = nxt.get_text(" ", strip=True)
                    if t:
                        parts.append(t)
                nxt = nxt.find_next_sibling()
            if parts:
                from .constants import _clean_game_desc
                return _clean_game_desc("\n".join(parts))
            break
    return ""


# 图床熔断：同一 host 连续下载失败达到阈值后，跳过该 host 后续所有图片。
# 常见于 Steam CDN（shared.cdn.queniuqe.com 等）在部分服务器网络被墙/极慢，
# 若不加熔断，每款游戏 3 张图 × 15s 超时会导致整条日报卡死数分钟。
_IMG_FAIL_THRESHOLD = 3


def _dl_and_b64_618(url: str, fail_tracker: dict = None) -> str:
    """下载 switch618 图片并压缩为 base64 data URI（离线渲染用）。失败返回空串。

    fail_tracker: 可选 {host: 连续失败次数} 字典，用于跨图片共享熔断状态；
    某 host 连续失败达到 _IMG_FAIL_THRESHOLD 后，直接跳过该 host 余下图以节省时间。
    """
    if not url or not url.startswith("http") or Image is None:
        return ""
    host = ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        pass
    if fail_tracker is not None and host in fail_tracker and fail_tracker[host] >= _IMG_FAIL_THRESHOLD:
        logger.info(f"[switch618日报] 跳过图片（{host} 已连续失败 {fail_tracker[host]} 次，疑似被墙/超时）: {str(url)[:50]}")
        return ""
    try:
        r = requests.get(url, headers={**HEADERS, "Referer": S618_BASE,
                                       "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
                         timeout=10)
        if r.status_code != 200 or not r.content:
            raise ValueError(f"status={r.status_code}")
        img = Image.open(io.BytesIO(r.content))
        if img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            mask = img.split()[-1] if img.mode == "RGBA" else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w = img.width
        if w > 360:
            img = img.resize((360, int(img.height * 360 / w)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        b = base64.b64encode(buf.getvalue()).decode("ascii")
        if fail_tracker is not None and host:
            fail_tracker[host] = 0  # 成功，重置该 host 失败计数
        return f"data:image/jpeg;base64,{b}"
    except Exception as e:
        if fail_tracker is not None and host:
            fail_tracker[host] = fail_tracker.get(host, 0) + 1
        logger.debug(f"[switch618日报] 图片下载失败 {str(url)[:50]}: {e}")
        return ""


def _has_meaningful_title(title: str) -> bool:
    """判断清洗后的标题是否含真实游戏名，排除只有《》壳或纯元数据的脏数据。

    例如站点上某游戏名为空，清洗后变成「《》 (Build 24184901 | 中文 | 免安装硬盘版)」，
    其主名（《》内）为空，应被过滤掉避免日报出现空标题卡片。
    """
    if not title or not title.strip():
        return False
    m = re.search(r'《([^》]*)》', title)
    name = m.group(1).strip() if m else re.split(r'[（(]', title)[0].strip()
    # 主名至少含一个非空白/非括号/非纯标点的字符才算有效
    return bool(re.search(r'[^\s《》（）()|｜+\-—·.、,，:：]', name))


def get_today_games_618(max_games: int = None, cookie: str = "", progress_cb=None) -> dict:
    """抓取 switch618.com 今日新增游戏（含简介 + 截图 base64）。

    判定逻辑（逐款，非仅首款）：游戏自身 span 文本含「新游」或今日日期
    （MMDD 如 0716 / M-D 如 07-16 / 2026-07-16 等）即视为今日更新。
    同一列表页是混合排序（新游/0716 与 0715/0714 同页），故逐款过滤，
    并持续翻页直到连续 2 页没有任何今日游戏才停止（避免漏抓）。

    max_games=None 表示抓全（内部安全上限 HARD_CAP=80）；传入正整数则只取前 N 款。
    progress_cb: 可选回调，用于在抓取过程中回报进度，签名 progress_cb(msg:str)。

    返回 {"success":bool,"games":[...],"error":""}
    - success=True 且 games=[] 表示今日暂无更新（error="今日暂无更新"）
    游戏卡字典结构与 xdgame 日报兼容（title/cover/cover_b64/intro/category/shots_b64），
    因此可直接复用 build_cartoon_html / render_html_to_png。
    """
    res = {"success": False, "games": [], "error": ""}
    HARD_CAP = 80
    fail_tracker = {}  # host -> 连续失败次数（图床熔断，跨多款游戏共享）
    def _prog(msg):
        logger.info(f"[switch618日报] {msg}")
        if callable(progress_cb):
            try: progress_cb(msg)
            except Exception: pass
    try:
        collected = []
        empty_streak = 0
        for page in range(1, 15):
            url = S618_PCGAMES_TPL.format(page)
            _prog(f"📄 正在获取新游列表第 {page} 页...")
            html = fetch_618(url, cookie)
            if not html:
                if not collected:
                    res["error"] = "列表页获取失败（被反爬拦截或网络异常）"
                break
            games = parse_618_list(html)
            if not games:
                break
            # 逐款过滤：仅保留 span 命中今日的游戏（span 在每款上，不只看首款），并剔除空标题脏数据
            page_today = [g for g in games
                          if g.get("title") and _has_meaningful_title(g["title"])
                          and g["title"] not in ("《》", "()", "")
                          and _is_today_618(g.get("span_text", ""))]
            if page_today:
                collected.extend(page_today)
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            if max_games and len(collected) >= max_games:
                collected = collected[:max_games]
                break
            if len(collected) >= HARD_CAP:
                collected = collected[:HARD_CAP]
                break
        if not collected:
            res["success"] = True
            if not res["error"]:
                res["error"] = "今日暂无更新"
            _prog("未找到今日更新的游戏")
            return res
        total = len(collected)
        _prog(f"📋 共找到 {total} 款今日新游，开始抓取封面/截图与简介...")
        # 逐个抓取详情（封面/截图/简介）
        for idx, g in enumerate(collected, 1):
            try:
                _prog(f"⏳ 抓取详情 ({idx}/{total})：{g.get('title','?')[:24]}")
                dhtml = fetch_618(g["detail_url"], cookie)
                if not dhtml:
                    g["intro"] = g.get("intro") or "暂无简介"
                    continue
                soup = BeautifulSoup(dhtml, "html.parser")
                cover, shots = extract_detail_images(soup, g["detail_url"])
                if not g.get("cover") and cover:
                    g["cover"] = cover
                intro = extract_wanfa(soup) or extract_game_description(soup)
                if not intro:
                    md = soup.find("meta", attrs={"name": "description"})
                    intro = md.get("content", "") if md else ""
                g["intro"] = intro or "暂无简介"
                g["cover_b64"] = _dl_and_b64_618(g.get("cover", ""), fail_tracker) if g.get("cover") else ""
                g["shots_b64"] = []
                for u in shots[:2]:
                    b = _dl_and_b64_618(u, fail_tracker)
                    if b:
                        g["shots_b64"].append(b)
            except Exception as e:
                logger.warning(f"[switch618日报] 详情失败 [{g.get('title','?')[:30]}]: {e}")
                g["intro"] = g.get("intro") or "暂无简介"
                g["cover_b64"] = ""
                g["shots_b64"] = []
            time.sleep(0.3)
        res["success"] = True
        res["games"] = collected
        _prog(f"✅ 抓取完成，共 {total} 款（含封面 {sum(1 for g in collected if g.get('cover_b64'))} 款）")
    except Exception as e:
        logger.error(f"[switch618日报] 抓取失败: {e}")
        res["error"] = str(e)[:200]
    return res


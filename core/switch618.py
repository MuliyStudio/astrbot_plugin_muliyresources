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
from urllib.parse import unquote
from .constants import logger, parse_cookie_string, extract_game_description

try:
    import requests
except ImportError:
    requests = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

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

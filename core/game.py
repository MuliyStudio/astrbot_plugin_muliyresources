# -*- coding: utf-8 -*-
"""游戏搜索相关函数"""
import re, datetime, requests
from bs4 import BeautifulSoup
from .constants import (
    GAME_BASE_URL, GAME_SEARCH_URL, GAME_PAN_ICONS, GAME_PAN_COLORS, GAME_PAN_DOMAINS,
    parse_cookie_string, logger, extract_game_description
)


def _game_session(cookie_str: str = "") -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": GAME_BASE_URL + "/",
    })
    if cookie_str:
        s.cookies.update(parse_cookie_string(cookie_str))
    return s


def check_cookie(cookie_str: str) -> tuple:
    """检测 Cookie 有效性。返回 (status, message)"""
    if not cookie_str or "DedeUserID" not in cookie_str:
        return False, "Cookie 未配置或缺少 DedeUserID"
    s = _game_session(cookie_str)
    try:
        resp = s.get(GAME_BASE_URL, timeout=15)
        resp.encoding = "utf-8"; text = resp.text
        if 'class="index-login"' in text and "登录免费享受更多权限" in text:
            soup = BeautifulSoup(text, "html.parser")
            today_section = soup.select_one(".index-new-list")
            links = []
            if today_section:
                for a in today_section.select('a[href*="/game/"]'):
                    h = a.get("href", "")
                    if h: links.append(GAME_BASE_URL + h if h.startswith("/") else h)
            if not links: links = [GAME_BASE_URL + "/game/13641.html"]
            try:
                r2 = s.get(links[0], timeout=10); r2.encoding = "utf-8"
                btn = BeautifulSoup(r2.text, "html.parser").select_one("a.downbtn[data-url]")
                if btn:
                    u = btn.get("data-url", "")
                    u = GAME_BASE_URL + u if u.startswith("/") else GAME_BASE_URL + "/" + u
                    r3 = s.get(u, timeout=10, allow_redirects=True); r3.encoding = "utf-8"; t3 = r3.text
                    for d in GAME_PAN_DOMAINS:
                        if d in r3.url or d in t3: return True, "Cookie 有效"
                    if "登录签到" in t3 or "下载次数" in t3:
                        m = re.search(r"下载次数已到达(\d+)次", t3)
                        return "limit", f"已达{m.group(1)}次" if m else "已达上限"
                    if "请先登录" in t3: return False, "Cookie 已失效"
            except: pass
            return False, "Cookie 已失效"
        for sig in ["action=logout", "/space/uid-"]:
            if sig in text: return True, "Cookie 有效"
        return None, "无法确认"
    except Exception as e:
        return False, f"检测失败: {e}"


def search_games(keyword: str, max_results: int = 32) -> list:
    """搜索游戏(xdgame.com)。返回 [{"id","title","url","type","date"},...]"""
    url = GAME_SEARCH_URL.format(keyword.replace(" ", "+"))
    logger.info(f"游戏搜索URL: {url}")
    s = _game_session()
    try:
        resp = s.get(url, timeout=15); resp.encoding = "utf-8"
    except Exception as e:
        logger.error(f"游戏搜索请求失败: {e}"); return []
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []; skipped = 0
    for li in soup.find_all("li"):
        a = li.find("a", href=re.compile(r"/game/\d+\.html"))
        if not a: continue
        if not li.find("time"): skipped += 1; continue
        href, name = a.get("href", ""), a.get_text(strip=True)
        if not href or not name: continue
        m = re.search(r"/game/(\d+)\.html", href)
        if not m: continue
        gid = m.group(1)
        type_text = ""
        for sp in li.find_all("span"):
            t = sp.get_text(strip=True)
            if t and not t.startswith("http") and len(t) < 10: type_text = t; break
        if not type_text:
            parts = li.get_text(separator=" ", strip=True).split(name)
            if parts and len(parts[0].strip()) < 10: type_text = parts[0].strip()
        date_text = ""
        tt = li.find("time")
        if tt: date_text = tt.get_text(strip=True)
        name = re.sub(r"^\d{1,2}\s*", "", name)
        fu = href if href.startswith("http") else GAME_BASE_URL + href
        if gid not in [r["id"] for r in results]:
            logger.debug(f"游戏命中: [{type_text}] {name} ({date_text})")
            results.append({"id": gid, "title": name, "url": fu, "type": type_text, "date": date_text})
        if len(results) >= max_results: break
    logger.info(f"游戏搜索完成: 结果={len(results)}, 跳过={skipped}")
    return results


def get_game_detail(game_url: str, cookie_str: str = "") -> dict:
    """获取游戏详情(xdgame.com)。返回 {"name","desc","cover","screenshots","download_links"}"""
    s = _game_session(cookie_str)
    try:
        resp = s.get(game_url, timeout=15); resp.encoding = "utf-8"
    except Exception as e:
        return {"name":"获取失败","desc":str(e)[:100],"cover":"","screenshots":[],"download_links":[]}
    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("title")
    name = re.sub(r"\s*[-–|]\s*.*$", "", title_tag.get_text(strip=True)).strip() if title_tag else ""
    # ── 封面 + 截图：优先 steam 资源，兜底扫描全页游戏图 ──
    raw_imgs, seen = [], set()
    for img in soup.find_all("img"):
        src = img.get("data-original") or img.get("data-src") or img.get("src", "")
        if src:
            raw_imgs.append(src if src.startswith("http") else GAME_BASE_URL + src)
    steam_caps = [u for u in raw_imgs if "steamcommunity/public/images/apps/" in u]
    steam_shots = [u for u in raw_imgs if "store_item_assets" in u and "steam/apps" in u]
    cover = (steam_caps or steam_shots or [""])[0]
    if not cover:
        ci = soup.select_one(".game-info img, .pic img, .cover img, .info-img img, .post-thumb img, .entry-content img")
        if ci:
            src = ci.get("data-original") or ci.get("data-src") or ci.get("src", "")
            if src: cover = GAME_BASE_URL + src if not src.startswith("http") else src

    # 截图：扫描正文中所有游戏截图（排除 logo/图标/头像/静态/二维码等）
    _EXCLUDE = ("logo", "icon", "avatar", "static/images", "defaultpic", "/uploads/emoji",
                "qrcode", "qr", "weixin", "loading", "spinner", "1x1", "blank",
                "ad.", "banner", "button", "arrow", "bg.", "background")
    cont = soup.select_one(".content, .game-info, .entry-content, .post-content, .single-content, article")
    pools = [cont, soup] if cont else [soup]
    for pool in pools:
        for img in pool.find_all("img"):
            src = img.get("data-original") or img.get("data-src") or img.get("src", "")
            if not src:
                continue
            low = src.lower()
            if any(k in low for k in _EXCLUDE):
                continue
            # 仅保留看起来像游戏截图/封面的（含 uploads 或图片扩展名）
            if ("wp-content/uploads" not in low and "upload" not in low
                    and not re.search(r"\.(?:webp|jpe?g|png)", low)):
                continue
            u = src if src.startswith("http") else GAME_BASE_URL + src
            if u not in seen and u != cover:
                seen.add(u); raw_imgs.append(u)
        if len([x for x in raw_imgs if x != cover]) >= 6:
            break
    screenshots = [u for u in raw_imgs if u != cover][:8]

    # ── 简介：基于 DOM 标题定位描述段落，排除联机补丁/修改器/下载等区块，保留分段 ──
    desc = extract_game_description(soup)
    if not desc:
        md = soup.find("meta", attrs={"name": "description"})
        desc = md.get("content", "") if md else "暂无简介"
    desc = desc[:2000]
    links = []
    for btn in soup.select("a.downbtn"):
        du = btn.get("data-url", ""); pn = btn.get_text(strip=True)
        if du and pn: links.append({"pan":pn,"api_url":du,"real_url":"","code":""})
    if not links:
        for du, pn in re.findall(r'data-url="([^"]+)"[^>]*>\s*<i></i>\s*([^<]+)</a>', resp.text):
            links.append({"pan":pn.strip(),"api_url":du,"real_url":"","code":""})
    return {"name":name,"desc":desc,"cover":cover,"screenshots":screenshots,"download_links":links}


def resolve_download_link(link_info: dict, cookie_str: str = "") -> dict:
    """解析下载链接的真实地址和提取码(xdgame.com)"""
    ap = link_info["api_url"]
    url = GAME_BASE_URL + ap if ap.startswith("/") else GAME_BASE_URL + "/" + ap
    s = _game_session(cookie_str)
    try:
        resp = s.get(url, timeout=15, allow_redirects=True); resp.encoding = "utf-8"; fu = resp.url
        real_url = ""; code = ""
        for d in GAME_PAN_DOMAINS:
            if d in fu: real_url = fu; break
        if not real_url:
            m = re.search(r'href="(https?://[^"]*(?:pan\.baidu|cloud\.189|pan\.xunlei|pan\.quark|aliyundrive|caiyun\.139|share\.123pan|drive\.uc)[^"]*)"', resp.text)
            if m: real_url = m.group(1)
        if "pan.baidu.com" in (real_url or fu):
            p = re.search(r"pwd=([a-zA-Z0-9]{4})", real_url or fu)
            if p: code = p.group(1)
            else:
                c = re.search(r"(?:提取码|密码|pwd)[：:\s]*([a-zA-Z0-9]{4})", resp.text, re.IGNORECASE)
                if c: code = c.group(1)
        if "cloud.189.cn" in (real_url or fu):
            p = re.search(r"[?&]code=([a-zA-Z0-9]{4,6})", real_url or fu)
            if p: code = p.group(1)
            else:
                p2 = re.search(r"/t/([a-zA-Z0-9]+)", real_url or fu)
                if p2: code = p2.group(1)
                else:
                    c = re.search(r"(?:提取码|访问码)[：:\s]*([a-zA-Z0-9]{4,6})", resp.text)
                    if c: code = c.group(1)
        if "pan.xunlei.com" in (real_url or fu):
            p = re.search(r"pwd=([a-zA-Z0-9]{4})", real_url or fu)
            if p: code = p.group(1)
            else:
                c = re.search(r"(?:提取码|密码)[：:\s]*([a-zA-Z0-9]{4})", resp.text, re.IGNORECASE)
                if c: code = c.group(1)
        link_info["real_url"] = real_url if real_url else "(获取失败)"
        link_info["code"] = code
    except Exception as e:
        link_info["real_url"] = f"(错误: {str(e)[:40]})"
        link_info["code"] = ""
    return link_info


def generate_game_html(name: str, desc: str, cover: str, screenshots: list, link: dict, keyword: str) -> str:
    """生成游戏详情 HTML 页面(xdgame.com)"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    bg = f'style="background-image: url(\'{cover}\')"' if cover else 'style="background: linear-gradient(135deg, #1a1a2e, #16213e)"'
    pan = link.get("pan", "下载链接"); ru = link.get("real_url", ""); cd = link.get("code", "")
    icon = GAME_PAN_ICONS.get(pan, "📥"); color = GAME_PAN_COLORS.get(pan, "#6b7280")
    ok = ru.startswith("http")
    shots = "".join(f'<div class="shot-item"><img src="{s}" alt="截图" loading="lazy" onclick="openLightbox(this.src)"></div>\n' for s in screenshots[:6]) if screenshots else '<div class="no-shots">暂无截图</div>'
    dp = desc.replace("\n", "</p><p>")
    if not dp.startswith("<p"): dp = f"<p>{dp}</p>"
    cd_str = f"提取码：{cd}" if cd else ""
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{name} - 游戏资源</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#0a0a0f;color:#e0e0e0;min-height:100vh}}
.hero{{position:relative;height:360px;display:flex;align-items:center;justify-content:center;overflow:hidden}}
.hero-bg{{position:absolute;top:0;left:0;right:0;bottom:0;background-size:cover;background-position:center;filter:blur(8px) brightness(0.3);transform:scale(1.1)}}
.hero-overlay{{position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(180deg,rgba(10,10,15,0.3)0%,rgba(10,10,15,0.8)100%)}}
.hero-content{{position:relative;z-index:1;text-align:center;padding:20px;max-width:800px}}
.hero-cover{{width:180px;height:240px;border-radius:16px;object-fit:cover;box-shadow:0 20px 60px rgba(0,0,0,0.6);margin-bottom:20px;border:2px solid rgba(255,255,255,0.1)}}
.hero h1{{font-size:32px;font-weight:800;background:linear-gradient(90deg,#fff,#a0c4e8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}}
.hero .subtitle{{font-size:14px;color:#8892a0}}
.container{{max-width:900px;margin:-60px auto 40px;padding:0 20px;position:relative;z-index:2}}
.card{{background:linear-gradient(145deg,#14141e,#1a1a28);border-radius:20px;padding:30px;margin-bottom:24px;border:1px solid rgba(255,255,255,0.06)}}
.card-title{{font-size:18px;font-weight:700;color:#e94560;margin-bottom:16px;display:flex;align-items:center;gap:10px}}
.card-title .line{{flex:1;height:1px;background:linear-gradient(90deg,rgba(233,69,96,0.3),transparent)}}
.desc-card p{{font-size:15px;line-height:1.9;color:#b0b8c8;margin-bottom:12px}}
.shots-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.shot-item{{border-radius:12px;overflow:hidden;aspect-ratio:16/9;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);cursor:pointer;transition:transform 0.3s}}
.shot-item:hover{{transform:translateY(-4px);border-color:rgba(233,69,96,0.3)}}
.shot-item img{{width:100%;height:100%;object-fit:cover;transition:transform 0.3s}}
.no-shots{{text-align:center;padding:40px;color:#6b7585;font-size:14px}}
.download-box{{background:linear-gradient(135deg,rgba(233,69,96,0.08),rgba(233,69,96,0.02));border:1px solid rgba(233,69,96,0.2);border-radius:16px;padding:28px;text-align:center}}
.download-icon{{font-size:48px;margin-bottom:12px}}
.download-pan{{font-size:20px;font-weight:700;color:{color};margin-bottom:8px}}
.download-link{{display:inline-block;margin-top:16px;padding:14px 40px;background:linear-gradient(135deg,{color},{color}dd);color:#fff;font-size:16px;font-weight:700;border-radius:50px;text-decoration:none;transition:all 0.3s;box-shadow:0 8px 30px {color}44}}
.download-link:hover{{transform:translateY(-3px);box-shadow:0 12px 40px {color}66}}
.download-code{{display:inline-block;margin-top:12px;padding:6px 20px;background:rgba(255,193,7,0.12);color:#ffc107;border-radius:20px;font-size:13px;font-weight:600}}
.download-fail{{color:#ef4444;font-size:14px;margin-top:12px}}
.source-info{{text-align:center;padding:16px;color:#4a5568;font-size:12px}}
.source-info a{{color:#e94560;text-decoration:none}}
.lightbox{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.92);z-index:9999;justify-content:center;align-items:center;cursor:pointer}}
.lightbox.active{{display:flex}}.lightbox img{{max-width:90vw;max-height:90vh;border-radius:8px}}
.lightbox-close{{position:absolute;top:20px;right:30px;color:#fff;font-size:36px;cursor:pointer;opacity:0.6}}
@media(max-width:600px){{.hero{{height:280px}}.hero h1{{font-size:24px}}.hero-cover{{width:130px;height:173px}}}}
@keyframes fadeInUp{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
.card{{animation:fadeInUp 0.5s ease forwards}}</style></head>
<body><div class="lightbox" id="lightbox" onclick="this.classList.remove('active')"><div class="lightbox-close">&times;</div><img id="lightbox-img" src="" alt="preview"></div>
<div class="hero"><div class="hero-bg {bg}"></div><div class="hero-overlay"></div><div class="hero-content"><img class="hero-cover" src="{cover}" alt="{name}" onerror="this.style.display='none'"><h1>{name}</h1><div class="subtitle">暮黎资源聚合 · 游戏搜索</div></div></div>
<div class="container">
<div class="card desc-card"><div class="card-title">📖 游戏简介<span class="line"></span></div>{dp}</div>
<div class="card"><div class="card-title">🎮 游戏截图<span class="line"></span></div><div class="shots-grid">{shots}</div></div>
<div class="card"><div class="card-title">📥 网盘下载<span class="line"></span></div>
<div class="download-box"><div class="download-icon">{icon}</div><div class="download-pan">{pan}</div>''' + (
    f'<a class="download-link" href="{ru}" target="_blank" rel="noopener">📥 点击下载</a>' + (f'<div class="download-code">🔑 {cd_str}</div>' if cd_str else "") if ok else
    f'<div class="download-fail">⚠️ 链接获取失败</div>'
) + f'''</div></div>
<div class="source-info"><p>数据来源：<a href="https://www.xdgame.com" target="_blank">XDGAME</a></p><p style="margin-top:4px;">搜索关键词：{keyword} ｜ 生成时间：{now}</p></div>
</div>
<script>function openLightbox(src){{document.getElementById('lightbox-img').src=src;document.getElementById('lightbox').classList.add('active')}}</script>
</body>
</html>'''

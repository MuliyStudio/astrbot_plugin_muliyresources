# -*- coding: utf-8 -*-
"""软件日报&搜索相关函数"""
import re, datetime, time, io, base64, os, tempfile, zipfile, requests
from bs4 import BeautifulSoup
from .constants import (
    SW_BASE_URL, SW_LIST_URL, SW_SEARCH_URL, SW_DISK_ICONS, SW_PAN_COLORS, SW_HEADERS, logger
)
from .mdi_icons import svg as _svg

# ==================== 通用工具 ====================

def _get_html(url: str, retries: int = 3, timeout: int = 20):
    for i in range(retries):
        try:
            r = requests.get(url, headers=SW_HEADERS, timeout=timeout)
            r.encoding = "utf-8"
            if r.status_code != 200: raise Exception(f"HTTP {r.status_code}")
            if len(r.text) < 500: raise Exception("过短")
            return r.text
        except Exception as e:
            logger.debug(f"sw请求失败(第{i+1}次): {e}")
            if i < retries - 1: time.sleep(2)
    return None

def _fix_url(url: str) -> str:
    if not url: return ""
    if url.startswith("http://") or url.startswith("https://"): return url
    if url.startswith("//"): return "https:" + url
    if url.startswith("/"): return SW_BASE_URL + url
    return SW_BASE_URL + "/" + url

# ==================== 软件日报 ====================

def _extract_description(article):
    if not article: return []
    sections = []; cur_title = None; cur_content = []
    skip_kw = ["下载地址", "网盘", "点击下载"]
    for elem in article.find_all(["h2","h3","h4","h5","p","div","span","ul","li","blockquote"]):
        tag = elem.name; text = elem.get_text(strip=True)
        if tag in ["h2","h3","h4","h5"]:
            if cur_title and cur_content: sections.append({"title":cur_title,"content":"\n\n".join(cur_content)})
            cur_title = text; cur_content = []; continue
        if tag == "img" or not text or len(text) < 5: continue
        if any(k in text for k in skip_kw): continue
        cur_content.append(text)
    if cur_title and cur_content: sections.append({"title":cur_title,"content":"\n\n".join(cur_content)})
    return sections

def get_software_list(max_softwares: int = 24) -> list:
    today_str = f"时间：{datetime.date.today().strftime('%Y-%m-%d')}"
    html = _get_html(SW_LIST_URL)
    if not html: return []
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.find("ul", class_="list-soft")
    if not ul: return []
    softwares = []
    for item in ul.find_all("li", class_="layui-clear"):
        te = item.find("a", class_="soft-title")
        title = te.get_text(strip=True) if te else ""
        time_elem = item.find("div", class_="list-ca")
        ut = time_elem.get_text(strip=True) if time_elem else ""
        if today_str not in ut: continue
        le = item.find("div", class_="list-btn")
        le = le.find("a") if le else None
        du = _fix_url(le.get("href","")) if le else ""
        ie = item.find("a", class_="list-img")
        ie = ie.find("img") if ie else None
        ci = _fix_url(ie.get("src","")) if ie else ""
        if title and du:
            softwares.append({"title":title,"update_time":ut,"detail_url":du,"cover_img":ci,"description":"","sections":[],"images":[],"downloads":[]})
    return softwares[:max_softwares]

def get_detail(sw: dict) -> dict:
    html = _get_html(sw["detail_url"], retries=3, timeout=25)
    if not html: return sw
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("div", class_="article-content")
    if article:
        sections = _extract_description(article)
        sw["sections"] = sections
        ft = "\n\n".join(f"{s['title']}\n\n{s['content']}" for s in sections)
        sw["description"] = ft[:1500] if len(ft) > 1500 else ft
    images = []
    if article:
        for img in article.find_all("img"):
            src = img.get("src","") or img.get("data-original","")
            if src: src = _fix_url(src); images.append(src)
    sw["images"] = images[:10]
    downloads = []
    for a in soup.find_all("a", attrs={"data-url": True}):
        du = a.get("data-url","")
        if du and not du.startswith("javascript:"): downloads.append({"name":a.get_text(strip=True) or "下载链接","url":du})
    if not downloads:
        text = soup.get_text()
        for pat, name in [(r'(https?://pan\.baidu\.com/[^\s<>"\']+)',"百度网盘"),(r'(https?://pan\.quark\.cn/[^\s<>"\']+)',"夸克网盘"),(r'(https?://cloud\.189\.cn/[^\s<>"\']+)',"天翼网盘"),(r'(https?://[^\s<>"\']*lanzou[^\s<>"\']*)',"蓝奏网盘")]:
            for link in re.findall(pat, text)[:3]: downloads.append({"name":name,"url":link})
    sw["downloads"] = downloads[:10]
    return sw

def sync_scrape(max_softwares: int = 24) -> dict:
    result = {"success":False,"softwares":[],"error":""}
    try:
        softwares = get_software_list(max_softwares)
        if not softwares: result["success"]=True; result["error"]="今日暂无更新"; return result
        for i, sw in enumerate(softwares, 1):
            logger.debug(f"  [{i}/{len(softwares)}] {sw.get('title','?')[:35]}")
            try: sw = get_detail(sw); time.sleep(0.8)
            except Exception as e: logger.warning(f"详情失败 [{sw.get('title','?')[:30]}]: {e}")
        result["success"]=True; result["softwares"]=softwares
    except Exception as e: logger.error(f"抓取失败: {e}"); result["error"]=str(e)[:200]
    return result

def gen_list_text(softwares: list) -> str:
    t = datetime.date.today()
    text = f"📦 暮黎软件日报\n{'='*40}\n📅 {t.strftime('%Y年%m月%d日')}  | 共 {len(softwares)} 款\n{'='*40}\n\n"
    for i, sw in enumerate(softwares, 1):
        text += f"{i}. {sw['title']}\n"
        for dl in sw.get("downloads",[])[:3]: text += f"   {SW_DISK_ICONS.get(dl['name'],'📥')} {dl['name']}: {dl['url']}\n"
        d = sw.get("description","")
        if len(d) > 10: text += f"   📝 {d[:120]}{'...' if len(d)>120 else ''}\n"
    text += f"\n{'='*40}\n🎯 暮黎社群: 1084453386\n🌐 muliy.cn | By: 暮黎 Muliy\n"
    return text

def _find_font():
    d = os.path.dirname(os.path.dirname(__file__)); exts = (".otf",".ttf",".ttc"); best=None
    for fname in os.listdir(d):
        if fname.lower().endswith(exts):
            fp=os.path.join(d,fname)
            if os.path.isfile(fp):
                if any(k in fname.lower() for k in ["sourcehan","noto","wenquanyi","wqy","cjk","chinese","sc","cn"]): return fp
                if best is None: best=fp
    if best: return best
    try:
        import subprocess
        r=subprocess.run(["fc-list",":lang=zh","-f","%{file}\n"],capture_output=True,text=True,timeout=5)
        if r.returncode==0:
            for line in r.stdout.strip().split("\n"):
                if line and os.path.isfile(line.strip()): return line.strip()
    except: pass
    for dd in ["/usr/share/fonts","/usr/local/share/fonts"]:
        if os.path.isdir(dd):
            for root, dirs, files in os.walk(dd):
                for f in files:
                    if f.lower().endswith(exts) and any(k in f.lower() for k in ["noto","cjk","wenquanyi","wqy","sourcehan"]):
                        return os.path.join(root,f)
    return None

def gen_list_image(softwares: list):
    try: from PIL import Image, ImageDraw, ImageFont
    except: return None
    t=datetime.date.today()
    width,pad,lh=800,40,60; hh,sh,fh=180,100,120
    ch=len(softwares)*lh+40; height=hh+sh+ch+fh+pad*2
    img=Image.new("RGB",(width,height),color="#667eea")
    draw=ImageDraw.Draw(img)
    ff=_find_font()
    if ff: tf=ImageFont.truetype(ff,28); xt=ImageFont.truetype(ff,18); sf=ImageFont.truetype(ff,14)
    else: tf=xt=sf=ImageFont.load_default()
    cy=pad; draw.rectangle([pad,cy,width-pad,cy+height-pad*2],fill="white")
    hy=cy+20; draw.rectangle([pad,cy,width-pad,hy+130],fill="#667eea")
    draw.text((width//2,hy+35),"暮黎软件日报",fill="white",font=tf,anchor="mm")
    draw.text((width//2,hy+85),t.strftime("%Y年%m月%d日"),fill="white",font=xt,anchor="mm")
    sy=hy+150; draw.rectangle([pad+20,sy,width-pad-20,sy+sh-20],fill="#f8f9fa")
    draw.text((width//2,sy+50),f"{len(softwares)} 款软件",fill="#667eea",font=tf,anchor="mm")
    content_y=sy+90; draw.text((pad+40,content_y),"今日更新列表",fill="#667eea",font=tf)
    lsy=content_y+40
    for i,sw in enumerate(softwares,1):
        iy=lsy+(i-1)*lh; draw.rectangle([pad+20,iy,width-pad-20,iy+50],fill="#f5f7fa")
        draw.rectangle([pad+20,iy,pad+24,iy+50],fill="#667eea")
        cx,cy2=pad+50,iy+25; draw.ellipse([cx-16,cy2-16,cx+16,cy2+16],fill="#667eea")
        draw.text((cx,cy2),str(i),fill="white",font=xt,anchor="mm")
        draw.text((cx+35,cy2),sw["title"],fill="#333",font=xt,anchor="lm")
    fy=lsy+len(softwares)*lh+20; draw.rectangle([pad+20,fy,width-pad-20,fy+90],fill="#f8f9fa")
    ft_y=fy+25; draw.text((width//2,ft_y),"暮黎社群 · 免费分享 · 每日更新",fill="#666",font=sf,anchor="mm")
    draw.text((width//2,ft_y+20),"暮黎社群：1084453386 | muliy.cn",fill="#667eea",font=sf,anchor="mm")
    draw.text((width//2,ft_y+40),f"By：暮黎 Muliy · {t.strftime('%Y-%m-%d')}",fill="#999",font=sf,anchor="mm")
    buf=io.BytesIO(); img.save(buf,format="JPEG",quality=85,optimize=True); buf.seek(0)
    return buf

def _compress_image(img_bytes: bytes, max_width: int = 800, quality: int = 70) -> bytes:
    try:
        from PIL import Image
        img=Image.open(io.BytesIO(img_bytes))
        if img.mode in ("RGBA","P"):
            bg=Image.new("RGB",img.size,(255,255,255)); bg.paste(img,mask=img.split()[-1] if img.mode=="RGBA" else None); img=bg
        elif img.mode!="RGB": img=img.convert("RGB")
        if img.width>max_width: r=max_width/img.width; img=img.resize((max_width,int(img.height*r)),Image.LANCZOS)
        buf=io.BytesIO(); img.save(buf,format="JPEG",quality=quality,optimize=True); return buf.getvalue()
    except: return img_bytes

def _dl_image(url: str, compress: bool = True):
    try:
        r=requests.get(url,headers={**SW_HEADERS,"Referer":SW_BASE_URL+"/"},timeout=15)
        if r.status_code!=200: return None
        ct=r.headers.get("Content-Type","image/jpeg"); ext=".png" if "png" in ct else ".gif" if "gif" in ct else ".webp" if "webp" in ct else ".jpg"
        data=r.content
        if compress and ext!=".gif": data=_compress_image(data,max_width=800,quality=70); ext=".jpg"
        return (data,ext)
    except: return None

def gen_report_zip(softwares: list, image_buffer=None):
    t=datetime.date.today().strftime("%Y年%m月%d日"); ts=datetime.date.today().strftime("%Y%m%d")
    urls=[]
    for sw in softwares:
        for u in sw.get("images",[])[:6]:
            if u not in urls: urls.append(u)
    img_map={}; cnt=0
    for u in urls:
        r=_dl_image(u)
        if r:
            data,ext=r; ct="image/png" if ext==".png" else "image/gif" if ext==".gif" else "image/webp" if ext==".webp" else "image/jpeg"
            img_map[u]=f"data:{ct};base64,{base64.b64encode(data).decode('utf-8')}"; cnt+=1
    hdi=SW_DISK_ICONS
    html=_build_report_html(t, softwares, img_map, hdi)
    try:
        fd,path=tempfile.mkstemp(suffix=f"_{ts}.zip",prefix="sw_report_"); os.close(fd)
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"暮黎软件日报_{ts}.html",html)
            if image_buffer is not None: zf.writestr(f"暮黎软件日报_{ts}.png",image_buffer.getvalue())
        return path
    except Exception as e: logger.error(f"ZIP生成失败: {e}"); return None

def _build_report_html(t, softwares, img_map, hdi):
    html=f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>暮黎软件日报 - {t}</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:20px 15px;line-height:1.6}}
.container{{max-width:900px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,0.2);overflow:hidden}}
.header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:30px 20px;text-align:center}}
.header h1{{font-size:24px;margin-bottom:8px;font-weight:600}}
.content{{padding:25px 20px}}
.software-card{{background:#f8f9fa;border-radius:12px;padding:20px;margin-bottom:25px;border-left:4px solid #667eea}}
.software-title{{font-size:18px;font-weight:600;color:#333;margin-bottom:12px}}
.software-meta{{font-size:13px;color:#666;margin-bottom:15px;display:flex;flex-wrap:wrap;gap:10px}}
.software-meta span{{background:#e9ecef;padding:4px 10px;border-radius:20px}}
.software-description{{font-size:14px;color:#555;line-height:1.8;margin-bottom:15px;max-height:300px;overflow-y:auto;background:#fff;padding:15px;border-radius:8px;border:1px solid #e9ecef}}
.section-title{{font-size:16px;font-weight:600;color:#667eea;margin:20px 0 12px 0;padding-bottom:8px;border-bottom:2px solid #667eea}}
.screenshots{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:15px}}
.screenshot-item{{border-radius:8px;overflow:hidden;aspect-ratio:16/9;background:#e9ecef}}
.screenshot-item img{{width:100%;height:100%;object-fit:cover;cursor:pointer}}
.downloads{{background:#fff;border-radius:8px;padding:12px}}
.downloads-title{{font-size:14px;font-weight:600;color:#333;margin-bottom:10px}}
.download-list{{display:flex;flex-direction:column;gap:8px}}
.download-item{{display:flex;align-items:center;padding:10px 12px;background:#f8f9fa;border-radius:8px;text-decoration:none;color:#333;transition:all 0.2s;border:1px solid #e9ecef}}
.download-item:hover{{background:#667eea;color:#fff}}
.download-icon{{font-size:18px;margin-right:10px}}
.download-name{{font-size:14px;font-weight:500;flex:1}}
.footer{{background:#f8f9fa;padding:20px;text-align:center;font-size:13px;color:#666;border-top:1px solid #e9ecef}}
</style></head><body><div class="container"><div class="header"><h1>{_svg("package", 22, "currentColor")} 暮黎软件日报</h1><div class="date">{t}</div></div><div class="content">'''
    for i,sw in enumerate(softwares,1):
        html+=f'<div class="software-card"><div class="software-title">{_svg("package", 16, "currentColor")} {i}. {sw["title"]}</div><div class="software-meta"><span>{_svg("event", 13, "currentColor")} {sw["update_time"]}</span><span>{_svg("camera", 13, "currentColor")} {len(sw["images"])}张截图</span><span>{_svg("link", 13, "currentColor")} {len(sw["downloads"])}个下载</span></div>'
        if sw.get('sections'):
            html+='<div class="software-description">\n'
            for sec in sw['sections']: html+=f'<div class="section-title">### {sec["title"]}</div>\n<div class="section-content">{sec["content"].replace(chr(10),"<br>")}</div>\n'
            html+='</div>\n'
        elif sw.get('description'): html+=f'<div class="software-description">{sw["description"].replace(chr(10),"<br>")}</div>\n'
        if sw.get('images'):
            html+='<div class="screenshots">\n'
            for u in sw['images'][:6]:
                entry=img_map.get(u)
                if entry: html+=f'<div class="screenshot-item"><img src="{entry}" alt="截图"></div>\n'
            html+='</div>\n'
        if sw.get('downloads'):
            html+=f'<div class="downloads"><div class="downloads-title">{_svg("link", 14, "currentColor")} 下载地址</div><div class="download-list">\n'
            for dl in sw['downloads']:
                icon=_svg("download", 18, "currentColor")
                html+=f'<a class="download-item" href="{dl["url"]}" target="_blank"><span class="download-icon">{icon}</span><span class="download-name">{dl["name"]}</span></a>\n'
            html+='</div></div>\n'
        html+='</div>\n'
    html+=f'</div><div class="footer"><p>共 {len(softwares)} 款资源 | 暮黎社群:1084453386</p></div></div></body></html>'
    return html

# ====================================================================
#  软件日报分享图（HTML → 图片，橙色青年 / 橘子味汽水 / 夏日风情）
#  弃用 Pillow 手绘，改用与游戏/影视日报一致的 HTML 排版 + Playwright 渲染。
#  图标统一使用 Material Design Icons（google/material-design-icons）内联 SVG，
#  避免服务器缺 emoji 字体导致图标乱码。
# ====================================================================

# 图标统一使用 Material Design Icons：core/mdi_icons 模块，已随顶部 `from .mdi_icons import svg as _svg` 引入。

# 卡片配色（橙/橘/柠系，循环使用）——橘子味汽水、夏日风情
_SUMMER_PALETTE = ["#ff7a00", "#ff9500", "#ffb300", "#ff6f3c", "#ff8f00", "#f4511e"]


def _dl_b64_sw(url: str, max_w: int = 360, fail_tracker: dict = None) -> str:
    """下载软件日报图片并压缩为 base64 data URI（离线内联渲染）。失败返回空串。

    带图床 host 熔断（同一 host 连续失败 3 次后跳过），避免个别慢/被墙图床拖垮整条日报。
    """
    if not url or not url.startswith("http"):
        return ""
    host = ""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
    except Exception:
        pass
    if fail_tracker is not None and host in fail_tracker and fail_tracker[host] >= 3:
        return ""
    try:
        from PIL import Image
        r = requests.get(url, headers={**SW_HEADERS, "Referer": SW_BASE_URL + "/"}, timeout=10)
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
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        b = base64.b64encode(buf.getvalue()).decode("ascii")
        if fail_tracker is not None and host:
            fail_tracker[host] = 0
        return f"data:image/jpeg;base64,{b}"
    except Exception as e:
        if fail_tracker is not None and host:
            fail_tracker[host] = fail_tracker.get(host, 0) + 1
        logger.debug(f"[软件日报] 图片下载失败 {str(url)[:50]}: {e}")
        return ""


def download_summer_assets(softwares: list) -> None:
    """为每款软件下载封面 + 最多 2 张截图并内联为 base64，写入 sw['cover_b64']/sw['shots_b64']。

    就地修改 softwares；带图床熔断，控制整体耗时与图片体积。
    """
    fail_tracker = {}
    for sw in softwares:
        imgs = sw.get("images", []) or []
        cover_src = imgs[0] if imgs else sw.get("cover_img", "")
        sw["cover_b64"] = _dl_b64_sw(cover_src, 360, fail_tracker) if cover_src else ""
        shots = []
        for u in imgs[1:3]:
            b = _dl_b64_sw(u, 480, fail_tracker)
            if b:
                shots.append(b)
        sw["shots_b64"] = shots


def _sw_intro(sw: dict, limit: int = 160) -> str:
    """从 description/sections 提取一段简介摘要（纯文本，截断）。"""
    txt = (sw.get("description", "") or "").strip()
    if not txt and sw.get("sections"):
        txt = " ".join(s.get("content", "") for s in sw["sections"])
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > limit:
        txt = txt[:limit] + "…"
    return txt


def build_summer_html(softwares: list, date_label: str, source_label: str = "小刀娱乐网") -> str:
    """把软件日报排版成【橙色青年 / 橘子味汽水 / 夏日风情】HTML（封面已内联 base64）。

    需先调用 download_summer_assets 填充 cover_b64/shots_b64；随后交给
    game_daily.render_html_to_png 渲染为图片。图标全部使用 Material Design Icons 内联 SVG。
    """
    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    cards = []
    for i, sw in enumerate(softwares, 1):
        color = _SUMMER_PALETTE[(i - 1) % len(_SUMMER_PALETTE)]
        cover = sw.get("cover_b64") or ""
        cover_html = (
            f'<img class="cover" src="{cover}" alt="封面">'
            if cover else
            f'<div class="cover noimg" style="color:{color}">{_svg("apps", 40, color)}</div>'
        )
        chips = []
        ut = (sw.get("update_time", "") or "").replace("时间：", "").strip()
        if ut:
            chips.append(f'<span class="chip">{_svg("event", 13)} {esc(ut)}</span>')
        if sw.get("images"):
            chips.append(f'<span class="chip">{_svg("camera", 13)} {len(sw["images"])}图</span>')
        if sw.get("downloads"):
            chips.append(f'<span class="chip">{_svg("download", 13)} {len(sw["downloads"])}源</span>')
        chips_html = "".join(chips)

        intro = esc(_sw_intro(sw))
        intro_html = f'<div class="intro">{intro}</div>' if intro else ""

        shots = sw.get("shots_b64", []) or []
        shots_html = ""
        if shots:
            shots_html = '<div class="shots">' + "".join(
                f'<div class="shot"><img src="{s}" alt="截图"></div>' for s in shots) + "</div>"

        pans = []
        for dl in (sw.get("downloads", []) or [])[:6]:
            name = esc(dl.get("name", "下载"))
            pan_color = SW_PAN_COLORS.get(dl.get("name", ""), color)
            pans.append(f'<span class="pan" style="background:{pan_color}">{_svg("download", 12, "#fff")} {name}</span>')
        pans_html = f'<div class="pans">{"".join(pans)}</div>' if pans else ""

        cards.append(f'''
<div class="card" style="border-color:{color}">
  <div class="idx" style="background:{color}">{i:02d}</div>
  <div class="card-head">
    <div class="cover-wrap">{cover_html}</div>
    <div class="head-right">
      <div class="title">{esc(sw.get("title", ""))}</div>
      <div class="chips">{chips_html}</div>
      {pans_html}
    </div>
  </div>
  {intro_html}
  {shots_html}
</div>''')

    cards_html = "\n".join(cards)
    n = len(softwares)
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>暮黎软件日报 - {date_label}</title>
<style>
@font-face{{font-family:'reportfont';src:url('report.otf') format('opentype');font-weight:normal;font-display:swap}}
*{{margin:0;padding:0;box-sizing:border-box}}
.mdi{{vertical-align:middle;margin-right:2px}}
body{{font-family:'reportfont','PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif;
  color:#4a2c00;line-height:1.6;padding:24px 14px 34px;
  background:
    radial-gradient(circle at 15% 20%, rgba(255,255,255,0.45) 0 7px, transparent 8px),
    radial-gradient(circle at 78% 42%, rgba(255,255,255,0.35) 0 5px, transparent 6px),
    radial-gradient(circle at 40% 78%, rgba(255,255,255,0.30) 0 6px, transparent 7px),
    linear-gradient(160deg,#ffd452 0%,#ff9a3c 46%,#ff6f3c 100%);
  background-size:52px 52px,60px 60px,48px 48px,100% 100%}}
.wrap{{max-width:720px;margin:0 auto}}
.header{{position:relative;background:linear-gradient(135deg,#ff8f00,#ff6f3c);border-radius:30px;
  padding:30px 24px;text-align:center;color:#fff;overflow:hidden;
  box-shadow:0 14px 34px rgba(255,111,60,0.45), inset 0 1px 0 rgba(255,255,255,0.4)}}
.header::before{{content:"";position:absolute;left:-40px;top:-40px;width:140px;height:140px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,255,255,0.5),transparent 70%)}}
.header::after{{content:"";position:absolute;right:-30px;bottom:-50px;width:160px;height:160px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,255,255,0.28),transparent 70%)}}
.header .logo{{position:relative;z-index:1;margin-bottom:6px}}
.header h1{{position:relative;z-index:1;font-size:32px;font-weight:800;letter-spacing:3px;
  text-shadow:0 3px 0 rgba(180,70,0,0.25)}}
.header .date{{position:relative;z-index:1;margin-top:10px;display:inline-block;background:rgba(255,255,255,0.28);
  padding:6px 20px;border-radius:22px;font-size:16px;font-weight:700}}
.header .sub{{position:relative;z-index:1;margin-top:9px;font-size:13px;opacity:0.95;letter-spacing:1px}}
.count{{text-align:center;margin:20px 0 8px;font-size:16px;font-weight:800;color:#e2570b;
  text-shadow:0 2px 6px rgba(255,255,255,0.6)}}
.card{{position:relative;background:#fffdf8;border:3px solid #ff9500;border-radius:24px;
  padding:18px 18px 16px;margin-bottom:20px;
  box-shadow:0 10px 24px rgba(220,110,40,0.20)}}
.idx{{position:absolute;left:-8px;top:-12px;min-width:34px;height:34px;padding:0 8px;border-radius:17px;
  display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800;color:#fff;
  box-shadow:0 5px 12px rgba(0,0,0,0.18)}}
.card-head{{display:flex;gap:16px;align-items:flex-start}}
.cover-wrap{{flex:0 0 96px}}
.cover{{width:96px;height:96px;object-fit:cover;border-radius:18px;
  border:3px solid #ffe0a3;box-shadow:0 6px 14px rgba(0,0,0,0.12);background:#fff}}
.cover.noimg{{width:96px;height:96px;display:flex;align-items:center;justify-content:center;
  background:#fff6e6;border:3px dashed #ffc470;border-radius:18px}}
.head-right{{flex:1;min-width:0}}
.title{{font-size:20px;font-weight:800;color:#3a2400;line-height:1.35;word-break:break-word}}
.chips{{margin-top:9px;display:flex;flex-wrap:wrap;gap:7px}}
.chip{{background:#fff1d6;color:#b25a00;font-size:12.5px;font-weight:700;padding:3px 11px;border-radius:14px;
  border:1px solid #ffdca0}}
.pans{{margin-top:9px;display:flex;flex-wrap:wrap;gap:7px}}
.pan{{color:#fff;font-size:12px;font-weight:700;padding:3px 11px;border-radius:14px;
  box-shadow:0 3px 8px rgba(0,0,0,0.12)}}
.intro{{margin-top:13px;background:#fff6e6;border:2px solid #ffe2ad;border-radius:16px;
  padding:11px 14px;font-size:13.5px;line-height:1.85;color:#6b4a1f}}
.shots{{margin-top:13px;display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}
.shot{{border-radius:14px;overflow:hidden;aspect-ratio:16/10;background:#fff0d6;border:2px solid #ffe2ad}}
.shot img{{width:100%;height:100%;object-fit:cover;display:block}}
.footer{{text-align:center;margin-top:12px;padding:16px;color:#8a5a1f;font-size:13px}}
.footer b{{color:#e2570b}}
</style></head>
<body><div class="wrap">
<div class="header">
  <div class="logo">{_svg("drink", 40, "#fff")}</div>
  <h1>暮黎软件日报</h1>
  <div class="date">{date_label}</div>
  <div class="sub">夏日限定 · 每日精选软件 · @机器人搜索软件名即可下载</div>
</div>
<div class="count">{_svg("fire", 17, "#e2570b")} 今日共 {n} 款软件更新</div>
{cards_html}
<div class="footer">数据来源 <b>{source_label}</b> ｜ 由「暮黎资源聚合」插件自动生成<br>By：暮黎 Muliy</div>
</div></body></html>'''


# ==================== 软件搜索 ====================

def search_software(keyword: str, max_results: int = 32) -> list:
    url = SW_SEARCH_URL.format(keyword)
    logger.info(f"软件搜索URL: {url}")
    html = _get_html(url)
    if not html: return []
    soup = BeautifulSoup(html, "html.parser"); results=[]
    for div in soup.find_all("div",class_="info-tit"):
        if "fr" not in div.get("class",[]): continue
        a=div.find("a",href=re.compile(r"/i-wz-\d+"))
        if not a: continue
        href,title=a.get("href",""),a.get_text(strip=True)
        if not href or not title: continue
        m=re.search(r"/i-wz-(\d+)",href)
        if not m: continue
        sid=f"sw_{m.group(1)}"; ft=div.get_text(separator=" ",strip=True); dt=""; cat=""
        dm=re.search(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})",ft)
        if dm: dt=dm.group(1); cat=re.sub(r"\s*立即查看\s*","",ft.split(dt,1)[-1].strip())
        if sid not in [r["id"] for r in results]:
            results.append({"id":sid,"title":title,"url":_fix_url(href),"category":cat,"date":dt})
        if len(results)>=max_results: break
    logger.info(f"软件搜索完成: {len(results)}个结果")
    return results

def get_search_detail(url: str) -> dict:
    html=_get_html(url)
    if not html: return {"name":"获取失败","desc":"请求失败","cover":"","screenshots":[],"download_links":[]}
    soup=BeautifulSoup(html,"html.parser")
    title_tag=soup.find("title")
    name=re.sub(r"\s*[-–|_]+\s*小刀娱乐网.*$","",title_tag.get_text(strip=True)).strip() if title_tag else ""
    article=soup.find("div",class_="article-content") or soup.find("div",class_="content")
    desc=article.get_text(strip=True)[:500] if article else ""
    if not desc:
        md=soup.find("meta",attrs={"name":"description"})
        if md: desc=md.get("content","")[:500]
    shots=[]
    if article:
        for img in article.find_all("img"):
            src=img.get("src") or img.get("data-original") or ""
            if src: src=_fix_url(src); shots.append(src)
    shots=shots[:6]; cover=shots[0] if shots else ""
    links=[]
    for a in soup.find_all("a",attrs={"data-url":True}):
        du=a.get("data-url","").strip()
        if du and not du.startswith("javascript:"): links.append({"pan":a.get_text(strip=True) or "下载链接","url":du})
    if not links and article:
        txt=article.get_text()
        for pat,pn in [(r"(https?://pan\.baidu\.com/[^\s<>\"']+)","百度网盘"),(r"(https?://pan\.quark\.cn/[^\s<>\"']+)","夸克网盘"),(r"(https?://cloud\.189\.cn/[^\s<>\"']+)","天翼网盘"),(r"(https?://[^\s<>\"']*lanzou[^\s<>\"']*)","蓝奏网盘")]:
            for link in re.findall(pat,txt)[:1]: links.append({"pan":pn,"url":link})
    return {"name":name,"desc":desc,"cover":cover,"screenshots":shots,"download_links":links}

def generate_search_html(name:str,desc:str,cover:str,screenshots:list,link:dict,keyword:str)->str:
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    bg=f'style="background-image: url(\'{cover}\')"' if cover else 'style="background: linear-gradient(135deg, #667eea, #764ba2)"'
    pan=link.get("pan","下载链接"); ru=link.get("url","")
    icon=_svg("download", 48, "currentColor"); color=SW_PAN_COLORS.get(pan,"#6b7280")
    ok=ru.startswith("http")
    shots="".join(f'<div class="shot-item"><img src="{s}" alt="截图" loading="lazy" onclick="openLightbox(this.src)"></div>\n' for s in screenshots[:6]) if screenshots else '<div class="no-shots">暂无截图</div>'
    dp=desc.replace("\n","</p><p>")
    if not dp.startswith("<p"): dp=f"<p>{dp}</p>"
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{name} - 软件资源</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#0a0a0f;color:#e0e0e0;min-height:100vh}}
.hero{{position:relative;height:340px;display:flex;align-items:center;justify-content:center;overflow:hidden}}
.hero-bg{{position:absolute;top:0;left:0;right:0;bottom:0;background-size:cover;background-position:center;filter:blur(12px) brightness(0.25);transform:scale(1.1)}}
.hero-overlay{{position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(180deg,rgba(10,10,15,0.2)0%,rgba(10,10,15,0.85)100%)}}
.hero-content{{position:relative;z-index:1;text-align:center;padding:20px;max-width:800px}}
.hero h1{{font-size:30px;font-weight:800;background:linear-gradient(90deg,#fff,#c4b5fd);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}}
.hero .subtitle{{font-size:14px;color:#8892a0}}
.container{{max-width:900px;margin:-50px auto 40px;padding:0 20px;position:relative;z-index:2}}
.card{{background:linear-gradient(145deg,#14141e,#1a1a28);border-radius:20px;padding:30px;margin-bottom:24px;border:1px solid rgba(255,255,255,0.06)}}
.card-title{{font-size:18px;font-weight:700;color:#8b5cf6;margin-bottom:16px;display:flex;align-items:center;gap:10px}}
.card-title .line{{flex:1;height:1px;background:linear-gradient(90deg,rgba(139,92,246,0.3),transparent)}}
.desc-card p{{font-size:15px;line-height:1.9;color:#b0b8c8;margin-bottom:12px}}
.shots-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.shot-item{{border-radius:12px;overflow:hidden;aspect-ratio:16/9;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);cursor:pointer;transition:transform 0.3s}}
.shot-item:hover{{transform:translateY(-4px);border-color:rgba(139,92,246,0.3)}}
.shot-item img{{width:100%;height:100%;object-fit:cover;transition:transform 0.3s}}
.no-shots{{text-align:center;padding:40px;color:#6b7585;font-size:14px}}
.download-box{{background:linear-gradient(135deg,rgba(139,92,246,0.08),rgba(139,92,246,0.02));border:1px solid rgba(139,92,246,0.2);border-radius:16px;padding:28px;text-align:center}}
.download-icon{{font-size:48px;margin-bottom:12px}}
.download-pan{{font-size:20px;font-weight:700;color:{color};margin-bottom:8px}}
.download-link{{display:inline-block;margin-top:16px;padding:14px 40px;background:linear-gradient(135deg,{color},{color}dd);color:#fff;font-size:16px;font-weight:700;border-radius:50px;text-decoration:none;transition:all 0.3s;box-shadow:0 8px 30px {color}44}}
.download-link:hover{{transform:translateY(-3px);box-shadow:0 12px 40px {color}66}}
.download-fail{{color:#ef4444;font-size:14px;margin-top:12px}}
.source-info{{text-align:center;padding:16px;color:#4a5568;font-size:12px}}
.source-info a{{color:#8b5cf6;text-decoration:none}}
.lightbox{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.92);z-index:9999;justify-content:center;align-items:center;cursor:pointer}}
.lightbox.active{{display:flex}}.lightbox img{{max-width:90vw;max-height:90vh;border-radius:8px}}
.lightbox-close{{position:absolute;top:20px;right:30px;color:#fff;font-size:36px;cursor:pointer;opacity:0.6}}
@media(max-width:600px){{.hero{{height:260px}}.hero h1{{font-size:22px}}}}
@keyframes fadeInUp{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
.card{{animation:fadeInUp 0.5s ease forwards}}</style></head>
<body><div class="lightbox" id="lightbox" onclick="this.classList.remove('active')"><div class="lightbox-close">&times;</div><img id="lightbox-img" src="" alt="preview"></div>
<div class="hero"><div class="hero-bg {bg}"></div><div class="hero-overlay"></div><div class="hero-content"><h1>{name}</h1><div class="subtitle">暮黎资源聚合 · 软件搜索</div></div></div>
<div class="container">
<div class="card desc-card"><div class="card-title">{_svg("book", 20, "currentColor")} 资源简介<span class="line"></span></div>{dp}</div>
<div class="card"><div class="card-title">{_svg("image", 20, "currentColor")} 资源截图<span class="line"></span></div><div class="shots-grid">{shots}</div></div>
<div class="card"><div class="card-title">{_svg("download", 20, "currentColor")} 网盘下载<span class="line"></span></div>
<div class="download-box"><div class="download-icon">{icon}</div><div class="download-pan">{pan}</div>'''+(f'<a class="download-link" href="{ru}" target="_blank" rel="noopener">{_svg("download", 14, "currentColor")} 点击下载</a>' if ok else f'<div class="download-fail">{_svg("warning", 14, "currentColor")} 链接获取失败</div>')+f'''</div></div>
<div class="source-info"><p>数据来源：<a href="https://www.x6d.com" target="_blank">小刀娱乐网</a></p><p style="margin-top:4px;">搜索关键词：{keyword} ｜ 生成时间：{now}</p></div>
</div>
<script>function openLightbox(src){{document.getElementById('lightbox-img').src=src;document.getElementById('lightbox').classList.add('active')}}</script>
</body>
</html>'''

# -*- coding: utf-8 -*-
"""pdy0 影视站（苹果CMS / maccms）适配。

站点：https://www.pdy0.com （片库的注册站，注册开放；主站片库需登录且已关闭注册）
地址发布页：https://www.988lm.com/ （check.js 列出当前所有可用站点 pdy0~6 / pys1~3）
插件会从发布页自动探测可用站点并按延迟选站，站点失效时自动切换。

能力：
  search(keyword)        -> [{id,title,year,type,dir,score,status,cover}]
                           搜索页可能要求「系统安全验证」图片验证码，
                           此时抛出 PdyCaptchaRequired(image_bytes)，由上层决定
                           自动 OCR 或把图片发给用户手动输入。
  fetch_captcha()        -> 验证码图片 bytes
  verify(code)           -> 提交验证码；成功后会记住登录态（session cookie）
  get_detail(dir, id)    -> 与片库新站同结构（name/desc/cover/year/...）
  get_resources(dir, id) -> {"playlist":[{"i","t","ep_start","ep_end"}],
                             "panlist":[{"name","url","type","user","time"}]}
  get_play_m3u8(node_i, ep) -> m3u8 直链（node_i 形如 "386760-1"）

所有解析都基于 maccms 默认模板 + 本站 mds 模板，页面改版时只需调整本文件。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .constants import logger

PDY_BASE_URL = "https://www.pdy0.com"
# 片库注册站（pdy0）的地址发布页：check.js 里列出当前所有可用站点
PDY_RELEASE_URL = "https://www.988lm.com"
# 同后台域名（发布页解析失败时的兜底列表）
PDY_MIRRORS = [
    "https://www.pdy0.com",
    "https://www.pys1.com",
    "https://www.pys2.com",
    "https://www.pys3.com",
    "https://www.pdy2.com",
    "https://www.pdy3.com",
    "https://www.pdy4.com",
    "https://www.pdy5.com",
    "https://www.pdy6.com",
]
PDY_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 影视日报区块：标准 ty -> maccms 分类 tid
PDY_TID = {"mv": 1, "tv": 2, "ac": 4}
# 详情页路径前缀 -> 展示类型
PDY_DIR_TYPE = {
    "mv": "电影", "tv": "剧集", "ac": "动漫",
    "va": "综艺", "vv": "综艺", "short": "短剧",
}
# 网盘标签 -> 统一名称（与 muliy 的图标表对齐）
_PAN_ALIAS = {
    "磁力资源": "磁力", "磁力": "磁力", "迅雷": "迅雷网盘",
    "百度": "百度网盘", "夸克": "夸克网盘", "阿里": "阿里网盘",
    "UC": "UC网盘", "天翼": "天翼网盘", "115": "115网盘",
}


class PdyCaptchaRequired(Exception):
    """搜索需要图片验证码。image 为验证码 PNG 字节。"""

    def __init__(self, image: bytes, keyword: str = ""):
        super().__init__("需要图片验证码")
        self.image = image
        self.keyword = keyword


def _norm_pan_type(label: str) -> str:
    label = re.sub(r"\s+", "", label or "")
    label = re.sub(r"\d+$", "", label)
    for k, v in _PAN_ALIAS.items():
        if label == k or label.startswith(k):
            return v
    return label or "其他"


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _fix_url(url: str, base: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base.rstrip("/") + url
    return url


# ==================== 站点自动发现（988lm.com 发布页） ====================

_DOMAIN_CACHE = {"domains": [], "ts": 0.0}
_DOMAIN_TTL = 3600          # 发布页探测结果缓存 1 小时
_DOMAIN_LOCK = threading.Lock()


def _parse_release_domains(js: str) -> list:
    """从 988lm 发布页 check.js 里解析 urlData 的所有站点。"""
    return [u.rstrip("/") for u in re.findall(r"url:\s*'([^']+)'", js or "")]


def _probe_latency(url: str, timeout: int = 4) -> Optional[int]:
    """测站点首页首字节延迟（ms）；失败返回 None。"""
    try:
        t0 = time.time()
        r = requests.get(url + "/", headers={"User-Agent": PDY_UA},
                         timeout=timeout, allow_redirects=False, stream=True)
        r.close()
        ms = round((time.time() - t0) * 1000)
        if r.status_code in (200, 301, 302, 303):
            return ms
    except Exception:
        return None
    return None


def discover_domains(force: bool = False, exclude: set = None) -> list:
    """从 988lm 发布会自动探测当前可用站点，按延迟升序返回 [(url, ms), ...]。

    - 解析 https://www.988lm.com/check.js 的 urlData；
    - 并发测各站点首页延迟，剔除连不上的站点；
    - 结果缓存 1 小时（force=True 强制刷新）。
    exclude 中的域名会被过滤（运行时标记失效的站点）。
    """
    exclude = set(exclude or [])
    now = time.time()
    with _DOMAIN_LOCK:
        if (not force and _DOMAIN_CACHE["domains"]
                and now - _DOMAIN_CACHE["ts"] < _DOMAIN_TTL):
            return [(u, ms) for u, ms in _DOMAIN_CACHE["domains"] if u not in exclude]

        domains = []
        try:
            r = requests.get(PDY_RELEASE_URL + "/check.js",
                             headers={"User-Agent": PDY_UA,
                                      "Referer": PDY_RELEASE_URL + "/"},
                             timeout=10)
            if r.status_code == 200:
                domains = _parse_release_domains(r.text)
                logger.info(f"[pdy_site] 发布页解析到 {len(domains)} 个站点")
            else:
                logger.warning(f"[pdy_site] 发布页 HTTP {r.status_code}，使用兜底列表")
        except Exception as e:
            logger.warning(f"[pdy_site] 发布页获取失败，使用兜底列表: {e}")
        if not domains:
            domains = list(PDY_MIRRORS)
        # 去重保序
        domains = list(dict.fromkeys(domains))

        results = [None] * len(domains)

        def _test(i, u):
            results[i] = _probe_latency(u)

        threads = [threading.Thread(target=_test, args=(i, u))
                   for i, u in enumerate(domains)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=8)
        measured = [(u, ms) for u, ms in zip(domains, results) if ms is not None]
        measured.sort(key=lambda x: x[1])
        if not measured:
            logger.warning("[pdy_site] 所有站点探测失败，暂用兜底列表")
            measured = [(u, 9999) for u in domains]
        _DOMAIN_CACHE["domains"] = measured
        _DOMAIN_CACHE["ts"] = time.time()
        logger.info("[pdy_site] 可用站点(延迟升序): "
                    + ", ".join(f"{u}({ms}ms)" for u, ms in measured[:6]))
        return [(u, ms) for u, ms in measured if u not in exclude]


class PdySiteClient:
    """pdy0 影视站客户端（单实例共享 session / 验证状态）。"""

    def __init__(self, base_url: str = "", cookie_path: str = "",
                 timeout: int = 15):
        self.base_url = (base_url or PDY_BASE_URL).rstrip("/")
        self.cookie_path = cookie_path
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": PDY_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._verified = False
        self._failed_domains: set = set()
        self._load_cookies()

    # ---------- 会话 / cookie ----------
    def _load_cookies(self):
        if not self.cookie_path or not os.path.exists(self.cookie_path):
            return
        try:
            with open(self.cookie_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in (data.get("cookies") or {}).items():
                self._session.cookies.set(k, v)
            self._verified = bool(data.get("verified"))
            if data.get("base"):
                self.base_url = data["base"]
            logger.info(f"[pdy_site] 已载入 cookie（verified={self._verified}）")
        except Exception as e:
            logger.warning(f"[pdy_site] 载入 cookie 失败: {e}")

    def _save_cookies(self):
        if not self.cookie_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cookie_path) or ".", exist_ok=True)
            with open(self.cookie_path, "w", encoding="utf-8") as f:
                json.dump({
                    "base": self.base_url,
                    "verified": self._verified,
                    "cookies": self._session.cookies.get_dict(),
                    "updated": int(time.time()),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[pdy_site] 保存 cookie 失败: {e}")

    @property
    def verified(self) -> bool:
        return self._verified

    def _relogin_on_fail(self) -> bool:
        """兼容片库客户端接口：标记验证态失效，下次请求重新验证。"""
        self._verified = False
        self._save_cookies()
        return True

    def _candidates(self) -> list:
        """候选站点：发布页探测结果（延迟升序）→ 当前站点 → 静态兜底。"""
        bases = []
        try:
            bases = [u for u, _ in discover_domains(exclude=self._failed_domains)]
        except Exception:
            bases = []
        if self.base_url and self.base_url not in bases and self.base_url not in self._failed_domains:
            bases.append(self.base_url)
        for b in PDY_MIRRORS:
            if b not in bases and b not in self._failed_domains:
                bases.append(b)
        return bases

    def _request(self, path: str, *, method: str = "GET", referer: str = "",
                 headers: dict = None, data=None, allow_redirects=True,
                 as_text: bool = True, max_tries: int = 3):
        """带域名回退的请求；当前站点失败时自动从发布页重新选站。"""
        last_err = None
        for round_no in range(2):
            if round_no == 0:
                bases = self._candidates()[:max_tries]
            else:
                # 所有候选都失败：清空失效标记并强制刷新发布页，再试一轮
                self._failed_domains.clear()
                try:
                    bases = [u for u, _ in discover_domains(force=True)][:max_tries]
                except Exception:
                    bases = []
                if not bases:
                    break
                logger.warning("[pdy_site] 候选站点均失败，强制刷新发布页重试")
            for base in bases:
                url = path if path.startswith("http") else base + path
                hdrs = {"Referer": referer or (base + "/")}
                if headers:
                    hdrs.update(headers)
                try:
                    r = self._session.request(method, url, headers=hdrs, data=data,
                                              timeout=self.timeout,
                                              allow_redirects=allow_redirects)
                    if r.status_code >= 500:
                        last_err = f"HTTP {r.status_code}"
                        self._failed_domains.add(base)
                        continue
                    if self.base_url != base:
                        logger.info(f"[pdy_site] 切换域名 {self.base_url} -> {base}")
                        self.base_url = base
                    self._failed_domains.discard(base)
                    if as_text:
                        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                            r.encoding = "utf-8"
                        return r.text
                    return r.content
                except Exception as e:  # 连接级异常 → 换域名
                    last_err = str(e)
                    self._failed_domains.add(base)
                    logger.warning(f"[pdy_site] 请求失败 {url}: {e}")
        logger.error(f"[pdy_site] 所有域名均失败: {path} ({last_err})")
        return "" if as_text else b""

    # ---------- 验证码 ----------
    @staticmethod
    def is_captcha_page(html: str) -> bool:
        return bool(html) and (
            "系统安全验证" in html
            or "verify_check" in html
            or 'class="ewave-verify-img"' in html
        )

    # ---------- 搜索限流 / 缓存 ----------
    # 站点提示「搜索时间间隔为3秒」；搜索页与验证码预热都算搜索请求，
    # 因此所有 /vs/ 请求统一走 _wait_search_gap 串行限速。
    _SEARCH_GAP = 3.1
    _LAST_SEARCH_TS = 0.0
    _SEARCH_LOCK = threading.Lock()
    _SEARCH_CACHE: dict = {}
    _SEARCH_TTL = 300

    def _wait_search_gap(self):
        with PdySiteClient._SEARCH_LOCK:
            gap = time.time() - PdySiteClient._LAST_SEARCH_TS
            if gap < self._SEARCH_GAP:
                time.sleep(self._SEARCH_GAP - gap)
            PdySiteClient._LAST_SEARCH_TS = time.time()

    @staticmethod
    def is_rate_limited(html: str) -> bool:
        return bool(html) and (
            "请不要频繁操作" in html
            or "搜索时间间隔" in html
            or "系统提示......" in html
        )

    def fetch_captcha(self, prime: bool = True) -> bytes:
        """获取当前会话的验证码图片（PNG/JPEG 字节）。

        prime=True 时先访问一次搜索页让服务端把验证码写进 session；
        从 search() 的验证页异常里调用时应传 False（搜索页刚访问过，
        再访问一次会触发「3 秒内不要频繁搜索」）。
        """
        if prime:
            self._wait_search_gap()
            self._request("/vs/-------------.html?wd=" + quote("test"))
        return self._request(
            "/verify/index.html?r=" + str(time.time()),
            headers={"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
            as_text=False,
        )

    def verify(self, code: str) -> bool:
        """提交验证码。成功返回 True 并记住登录态。"""
        code = re.sub(r"\s+", "", code or "")
        if not code:
            return False
        txt = self._request(
            "/ajax/verify_check.html", method="POST",
            headers={"X-Requested-With": "XMLHttpRequest",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            data={"type": "search", "verify": code},
        )
        try:
            ok = json.loads(txt).get("code") == 1
        except Exception:
            ok = False
        if ok:
            self._verified = True
            self._save_cookies()
            logger.info("[pdy_site] 搜索验证码通过")
        else:
            logger.warning(f"[pdy_site] 验证码未通过: {code!r} -> {txt[:120]}")
        return ok

    # ---------- 搜索 ----------
    def search(self, keyword: str, max_results: int = 24) -> list:
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        hit = self._SEARCH_CACHE.get(keyword)
        if hit and hit[0] and time.time() - hit[1] < self._SEARCH_TTL:
            logger.debug(f"[pdy_site] 搜索 '{keyword}' 命中缓存 {len(hit[0])} 条")
            return hit[0][:max_results]
        for attempt in range(2):
            self._wait_search_gap()
            html = self._request("/vs/-------------.html?wd=" + quote(keyword))
            if not html:
                return []
            if self.is_captcha_page(html):
                raise PdyCaptchaRequired(self.fetch_captcha(prime=False), keyword)
            if self.is_rate_limited(html):
                logger.warning("[pdy_site] 触发搜索限流（3 秒间隔），稍后重试")
                if attempt == 0:
                    time.sleep(self._SEARCH_GAP)
                    continue
                return []
            results = self.parse_search(html, max_results)
            if results:
                self._SEARCH_CACHE[keyword] = (results, time.time())
            return results
        return []

    def parse_search(self, html: str, max_results: int = 24) -> list:
        soup = BeautifulSoup(html, "html.parser")
        box = soup.select_one("div.vod-list") or soup
        results = []
        for li in box.select("ul.row > li"):
            a = li.select_one("div.name h3 a") or li.select_one("div.pic a")
            if not a:
                continue
            href = a.get("href", "")
            m = re.search(r"/([a-z]{2,5})/(\d+)\.html", href)
            if not m:
                continue
            dir_, vid = m.group(1), m.group(2)
            title = _clean_text(a.get("title") or a.get_text(strip=True))
            if not title:
                continue
            cover_el = li.select_one("div.img-wrapper")
            cover = _fix_url(cover_el.get("data-original") if cover_el else "", self.base_url)
            s1 = li.select_one("span.s1")
            status = _clean_text(s1.get_text(strip=True)) if s1 else ""
            s2 = li.select_one("span.s2")
            score = _clean_text(s2.get_text(strip=True)) if s2 else ""
            if score in ("--", "-", "0.0", "0"):
                score = ""
            info_el = li.select_one("p.item-status")
            info = _clean_text(info_el.get_text(" ", strip=True)) if info_el else ""
            year = ""
            if info:
                year = info.split("/")[0].strip()
            results.append({
                "id": vid,
                "title": title,
                "year": year,
                "type": "",  # 搜索结果页不标类型，详情页再补
                "dir": dir_,
                "score": score,
                "status": status,
                "cover": cover,
            })
            if len(results) >= max_results:
                break
        return results

    # ---------- 详情 ----------
    def get_detail(self, dir_: str, id_: str) -> dict:
        html = self._request(f"/{dir_}/{id_}.html")
        if not html:
            return self._empty_detail(dir_, id_, "详情页获取失败")
        return self.parse_detail(html, dir_, id_)

    def parse_detail(self, html: str, dir_: str, id_: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        info = soup.select_one("div.info")
        name = ""
        year = ""
        if info:
            h3 = info.find("h3")
            if h3:
                a = h3.find("a")
                name = _clean_text(a.get_text(strip=True) if a else h3.get_text(strip=True))
                m = re.search(r"\(\s*(\d{4})\s*\)", h3.get_text(" ", strip=True))
                if m:
                    year = m.group(1)
        if not name:
            t = soup.find("title")
            name = _clean_text(t.get_text() if t else "") or "未知影视"
            name = re.sub(r"^《([^》]+)》.*$", r"\1", name) or name

        desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            desc = _clean_text(meta.get("content", ""))
            desc = re.sub(r"^《[^》]*》讲述的是：", "", desc).strip()
        if not desc and info:
            row = info.select_one("span.text-row")
            if row:
                desc = _clean_text(row.get_text(" ", strip=True))

        cover = ""
        pic = soup.select_one("div.detail-pic img") or soup.select_one("div.pic img")
        if pic is None:
            pic = soup.select_one("img[data-original]")
        if pic:
            cover = _fix_url(pic.get("data-original") or pic.get("src") or "", self.base_url)

        status = ""
        other = soup.select_one("div.otherbox")
        if other:
            em = other.find("em")
            status = _clean_text(em.get_text(strip=True) if em else other.get_text(" ", strip=True))

        daoyan, zhuyan, leixing, diqu = [], [], [], []
        if info:
            for span in info.select("span.text-row"):
                txt = _clean_text(span.get_text(" ", strip=True))
                for prefix, bucket in (("导演：", daoyan), ("主演：", zhuyan),
                                       ("类型：", leixing), ("地区：", diqu)):
                    if txt.startswith(prefix):
                        val = txt[len(prefix):]
                        parts = [x.strip() for x in re.split(r"[/,，、]", val) if x.strip()]
                        bucket.extend(parts[:12])
        if not leixing:
            cat = soup.select_one("div.info a[href*='/vod/show/type/']")
            if cat:
                leixing = [_clean_text(cat.get_text(strip=True))]
        if not leixing:
            tm = soup.find("title")
            if tm:
                m = re.search(r"-\s*([^-]+?)\s*-\s*片库", tm.get_text())
                if m:
                    leixing = [_clean_text(m.group(1))]

        score = ""
        for sel in ("div.score", "span.score", "div.rating"):
            el = soup.select_one(sel)
            if el:
                score = _clean_text(el.get_text(strip=True))
                if score:
                    break
        return {
            "name": name,
            "desc": desc or "暂无简介",
            "cover": cover,
            "year": year,
            "dir": dir_,
            "id": id_,
            "status": status,
            "daoyan": daoyan,
            "zhuyan": zhuyan,
            "leixing": leixing,
            "diqu": diqu,
            "score_db": score,
            "score_im": "",
        }

    @staticmethod
    def _empty_detail(dir_: str, id_: str, desc: str) -> dict:
        return {"name": "获取失败", "desc": desc, "cover": "", "year": "",
                "dir": dir_, "id": id_, "status": "", "daoyan": [], "zhuyan": [],
                "leixing": [], "diqu": [], "score_db": "", "score_im": ""}

    # ---------- 资源 ----------
    def get_resources(self, dir_: str, id_: str) -> dict:
        html = self._request(f"/{dir_}/{id_}.html")
        if not html:
            return {"playlist": [], "panlist": []}
        return self.parse_resources(html, id_)

    def parse_resources(self, html: str, id_: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        playlist, panlist = [], []

        # 在线播放：每个线路 tab 对应一个 ul#ewave-playlist-{sid}
        for tab in soup.select("li[data-target^='#ewave-playlist-']"):
            target = tab.get("data-target", "")
            m = re.search(r"ewave-playlist-(\d+)", target)
            if not m:
                continue
            sid = m.group(1)
            ul = soup.find("ul", id=f"ewave-playlist-{sid}")
            if not ul:
                continue
            eps = ul.select("li a[href]")
            label = _clean_text(tab.get_text(strip=True))
            label = re.sub(r"\d+$", "", label).strip() or f"线路{sid}"
            if not eps:
                continue
            playlist.append({
                "i": f"{id_}-{sid}",
                "t": label,
                "ep_start": 1,
                "ep_end": len(eps),
            })

        # 网盘 / 磁力：每个 tab 对应 ul#ewave-downlist-{sid}
        seen_url = set()
        for tab in soup.select("li[data-target^='#ewave-downlist-']"):
            target = tab.get("data-target", "")
            m = re.search(r"ewave-downlist-(\d+)", target)
            if not m:
                continue
            sid = m.group(1)
            ul = soup.find("ul", id=f"ewave-downlist-{sid}")
            if not ul:
                continue
            label = _norm_pan_type(tab.get_text(strip=True))
            links = []
            for a in ul.select("div.ewave-downlist-ep a[href], li a[href]"):
                url = (a.get("href") or "").strip()
                if not re.match(r"^(https?://|magnet:|ed2k:)", url, re.I):
                    continue
                name = _clean_text(a.get("title") or a.get_text(strip=True))
                links.append((url, name))
            if not links:
                continue
            # 磁力 tab 的标题常是画质（中字720P 等），且可能混入迅雷官网广告链接：
            # 磁力/ed2k 占多数时只保留磁力链接，统一归类为「磁力」
            magnet_links = [(u, n) for u, n in links
                            if u.startswith("magnet:") or u.startswith("ed2k:")]
            if magnet_links and len(magnet_links) * 2 >= len(links):
                links = magnet_links
                ptype = "磁力"
            else:
                ptype = label
            for url, name in links:
                if url in seen_url:
                    continue
                seen_url.add(url)
                panlist.append({
                    "name": name,
                    "url": url,
                    "type": ptype,
                    "user": "",
                    "time": "",
                })
        logger.info(f"[pdy_site] 资源: 播放线路 {len(playlist)} 个, 网盘/磁力 {len(panlist)} 个")
        return {"playlist": playlist, "panlist": panlist}

    # ---------- 播放直链 ----------
    def get_play_m3u8(self, node_i: str, ep: int = 1) -> str:
        """node_i 形如 "386760-1"（详情 id + 线路 sid），ep 为集数。"""
        node_i = str(node_i or "").strip()
        if not node_i:
            return ""
        html = self._request(f"/py/{node_i}-{int(ep or 1)}.html",
                             referer=self.base_url + "/")
        if not html:
            return ""
        m = re.search(r"player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>", html)
        if not m:
            logger.warning("[pdy_site] 播放页未找到 player_aaaa")
            return ""
        try:
            d = json.loads(m.group(1))
        except Exception as e:
            logger.warning(f"[pdy_site] player_aaaa 解析失败: {e}")
            return ""
        url = (d.get("url") or "").strip()
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.base_url + url
        logger.info(f"[pdy_site] m3u8 node={node_i} ep={ep} -> {url[:90]}")
        return url

    # ---------- 推荐 / 日报 ----------
    def latest(self, tid: int, limit: int = 30) -> list:
        """按分类取最新列表（ajax/data，无需验证码）。"""
        txt = self._request(
            f"/index.php/ajax/data?mid=1&tid={int(tid)}&limit={int(limit)}&page=1",
            headers={"X-Requested-With": "XMLHttpRequest"})
        try:
            data = json.loads(txt)
        except Exception:
            return []
        return data.get("list") or []

    def random_movie(self) -> Optional[dict]:
        """从最新列表随机取一部，供签到推荐。"""
        import random
        try:
            rows = self.latest(PDY_TID["mv"], 30) + self.latest(PDY_TID["tv"], 30)
            rows = [r for r in rows if r.get("vod_name")]
            if not rows:
                return None
            r = random.choice(rows)
            name = _clean_text(r.get("vod_name", ""))
            desc = " · ".join(x for x in (
                _clean_text(r.get("vod_class", "")),
                _clean_text(r.get("vod_year", "")),
            ) if x) or "pdy0 影视"
            return {"name": name, "desc": desc, "query": name}
        except Exception:
            return None

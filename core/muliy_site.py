# -*- coding: utf-8 -*-
"""新站影视搜索 - 适配 教父.com (挂了.com 发布的备用域名簇)

完整流程：
  discover_best_domain()  -> 从挂了.com 探测延迟最低的可用影视域名
  MuliySiteClient:
    ensure_session()       -> PoW(大整数模平方) + 登录，缓存复用
    search(keyword)        -> /res/search_suggest  [{title,id,year,type,dir,score}]
    get_detail(dir, id)    -> /{dir}/{id} 解析内联 _obj.d  {name,desc,cover,year,...}
    get_resources(dir,id)  -> /res/downurl/{dir}/{id}  {playlist,panlist}
    cover_url / play_url   -> 封面 / 播放页直链

数据结构约定：
  search()      -> List[{"id","title","year","type","dir","score"}]
  get_detail()  -> {"name","desc","cover","year","dir","id","status",
                    "daoyan","zhuyan","leixing","diqu","score_db","score_im"}
  get_resources()-> {"playlist":[{"i","t","ep_start","ep_end"}],
                     "panlist":[{"name","url","type","user","time"}]}
"""
import json
import re
import time
import threading
import requests
import urllib3
from urllib.parse import urlsplit, urlunsplit, quote
from .constants import (
    MULIY_GUALE_URL, MULIY_IMG_HOST, MULIY_DEFAULT_DOMAIN,
    MULIY_PAN_ICONS, MULIY_UA, logger, emoji_index,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _punycode_url(url: str) -> str:
    """把 URL 里的中文域名转成 Punycode（如 www.教父.com → www.xn--wcv59z.com）。

    HTTP header 只支持 latin-1，中文域名必须先转 Punycode。
    """
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        parts = host.split(".")
        enc = []
        for part in parts:
            if any(ord(c) > 127 for c in part):
                enc.append(part.encode("idna").decode("ascii"))
            else:
                enc.append(part)
        new_host = ".".join(enc)
        return urlunsplit((p.scheme, new_host, p.path or "", p.query or "", p.fragment or ""))
    except Exception:
        return url


# ==================== 有效域名探测 ====================

# 域名探测结果缓存 {url: (best_domain, ts)}
_DOMAIN_CACHE = {"domain": "", "ts": 0.0}
_DOMAIN_CACHE_TTL = 3600  # 1 小时


def _guale_get_checkjs(session: requests.Session) -> str:
    """访问挂了.com：先 /auth?count=1 拿 cookie，再取 check.js 文本。"""
    session.get(MULIY_GUALE_URL + "/auth?count=1", timeout=12, verify=False)
    r = session.get(MULIY_GUALE_URL + "/check.js?25", timeout=12, verify=False)
    return r.text


def _parse_domains(checkjs: str) -> list:
    """从 check.js 解析 urlData 里的所有域名（转 Punycode）。"""
    raw = re.findall(r"url:\s*'(https?://[^']+)'", checkjs)
    return [_punycode_url(u) for u in raw]


def _probe_latency(url: str) -> int | None:
    """测一个域名的首字节延迟(ms)，失败返回 None。"""
    try:
        t0 = time.time()
        r = requests.get(url + "/", timeout=7, verify=False,
                         allow_redirects=False, stream=True)
        r.close()
        ms = round((time.time() - t0) * 1000)
        if r.status_code in (200, 301, 302, 303):
            return ms
    except Exception:
        return None
    return None


def discover_best_domain(force: bool = False) -> str:
    """从挂了.com 探测延迟最低的可用影视域名。

    缓存 1 小时；force=True 强制刷新。
    返回形如 'https://www.xn--wcv59z.com' 的 URL（无尾斜杠）。
    """
    if not force and _DOMAIN_CACHE["domain"]:
        if time.time() - _DOMAIN_CACHE["ts"] < _DOMAIN_CACHE_TTL:
            return _DOMAIN_CACHE["domain"]

    s = requests.Session()
    s.headers.update({"User-Agent": MULIY_UA})
    try:
        checkjs = _guale_get_checkjs(s)
        domains = _parse_domains(checkjs)
    except Exception as e:
        logger.warning(f"[muliy_site] 挂了.com 探测失败: {e}，使用默认域名")
        _DOMAIN_CACHE["domain"] = MULIY_DEFAULT_DOMAIN
        _DOMAIN_CACHE["ts"] = time.time()
        return MULIY_DEFAULT_DOMAIN

    if not domains:
        _DOMAIN_CACHE["domain"] = MULIY_DEFAULT_DOMAIN
        _DOMAIN_CACHE["ts"] = time.time()
        return MULIY_DEFAULT_DOMAIN

    # 并发测延迟
    measured = []
    results = [None] * len(domains)

    def _test(i, u):
        results[i] = _probe_latency(u)

    threads = [threading.Thread(target=_test, args=(i, u)) for i, u in enumerate(domains)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    for u, ms in zip(domains, results):
        if ms is not None:
            measured.append((u, ms))
            logger.debug(f"[muliy_site] {u} -> {ms}ms")

    if not measured:
        logger.warning("[muliy_site] 所有域名探测失败，使用默认域名")
        _DOMAIN_CACHE["domain"] = MULIY_DEFAULT_DOMAIN
        _DOMAIN_CACHE["ts"] = time.time()
        return MULIY_DEFAULT_DOMAIN

    measured.sort(key=lambda x: x[1])
    best = measured[0][0]
    logger.info(f"[muliy_site] 选定延迟最低域名: {best} ({measured[0][1]}ms)")
    _DOMAIN_CACHE["domain"] = best
    _DOMAIN_CACHE["ts"] = time.time()
    return best


# ==================== PoW 解决器 ====================

def solve_pow(session: requests.Session, base: str) -> bool:
    """解决教父.com 的 PoW 工作量证明。

    算法（来自 powSolve.js）：GET /res/pow 拿 {N,x,t}，
    y=x 循环 t 次 y=(y*y)%N，POST /res/pow y=hex。
    必须先 GET 页面拿 browser_pow cookie 服务器才下发挑战。
    """
    try:
        # 先 GET 首页拿 browser_pow cookie，服务器才下发挑战
        session.get(base + "/", timeout=15, verify=False)
        time.sleep(0.3)
        chal = session.get(base + "/res/pow", timeout=15, verify=False).json()
    except Exception as e:
        logger.error(f"[muliy_site] 获取 PoW 挑战失败: {e}")
        return False

    if "error" in chal or "N" not in chal:
        # 已通过 PoW（browser_verified 存在）则跳过求解，直接复用会话。
        # 注意：绝不能在此 pop browser_pow/browser_verified，否则服务器不再
        # 下发挑战（报"未找到挑战"），导致 relogin 彻底失败、播放页判未登录。
        if "browser_verified" in session.cookies:
            logger.info("[muliy_site] 已有 browser_verified，跳过 PoW")
            return True
        logger.error(f"[muliy_site] PoW 挑战异常: {chal}")
        return False

    N = int(chal["N"], 16)
    x = int(chal["x"], 16)
    t = int(chal["t"])
    logger.debug(f"[muliy_site] PoW: N位数={N.bit_length()} t={t}")

    t0 = time.time()
    y = x
    for _ in range(t):
        y = (y * y) % N
    logger.debug(f"[muliy_site] PoW 计算耗时 {round(time.time()-t0,2)}s")

    try:
        vr = session.post(base + "/res/pow", data={"y": format(y, "x")},
                          timeout=15, verify=False)
        rj = vr.json()
        if rj.get("success"):
            logger.info("[muliy_site] PoW 验证通过")
            return True
        logger.error(f"[muliy_site] PoW 验证失败: {rj}")
        return False
    except Exception as e:
        logger.error(f"[muliy_site] PoW 提交失败: {e}")
        return False


# ==================== 详情页 _obj.d 解析 ====================

def _extract_balanced(s: str, start: int) -> str:
    """从 s[start]=='{' 开始，提取平衡的花括号块（含首尾 { }）。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
    return s[start:]


def parse_detail_html(html: str, dir_: str, id_: str) -> dict:
    """从详情页 HTML 解析内联的 _obj.d 对象。"""
    empty = {
        "name": "未知影视", "desc": "暂无简介", "cover": "",
        "year": "", "dir": dir_, "id": id_, "status": "",
        "daoyan": [], "zhuyan": [], "leixing": [], "diqu": [],
        "score_db": "", "score_im": "",
    }
    m = re.search(r"_obj\.d\s*=\s*(\{)", html)
    if not m:
        return empty
    block = _extract_balanced(html, m.start(1))
    try:
        d = json.loads(block)
    except Exception as e:
        logger.warning(f"[muliy_site] _obj.d 解析失败: {e}")
        return empty

    pf = d.get("pf", {}) or {}
    db = pf.get("db", {}) or {}
    im = pf.get("im", {}) or {}
    return {
        "name": d.get("title", "未知影视"),
        "desc": (d.get("summary", "") or "暂无简介").strip()[:1500],
        "cover": cover_url(dir_, id_),
        "year": str(d.get("year", "")),
        "dir": d.get("dir", dir_),
        "id": d.get("id", id_),
        "status": re.sub(r"<[^>]+>", "", d.get("status", "") or ""),
        "daoyan": d.get("daoyan", []) or [],
        "zhuyan": (d.get("zhuyan", []) or [])[:12],
        "leixing": d.get("leixing", []) or [],
        "diqu": d.get("diqu", []) or [],
        "score_db": str(db.get("s", "")) if db.get("s") else "",
        "score_im": str(im.get("s", "")) if im.get("s") else "",
    }


# ==================== 客户端 ====================

class MuliySiteClient:
    """教父.com 影视站客户端：PoW + 登录 + 搜索 + 详情 + 资源。

    session 缓存复用 cookie，避免每次都等 PoW(~3s)+登录。
    """

    def __init__(self, username: str, password: str,
                 base_url: str = "", cache_ttl: int = 3600):
        self.username = username
        self.password = password
        self.base_url = _punycode_url(base_url or "").rstrip("/")
        self.cache_ttl = cache_ttl
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": MULIY_UA})
        self._logged_in = False
        self._login_ts = 0.0
        self._lock = threading.Lock()
        self._session_searched = False  # 当前 session 是否已搜过（搜索限流追踪）

    # ---------- 会话管理 ----------
    def _get_base(self) -> str:
        if not self.base_url:
            self.base_url = discover_best_domain().rstrip("/")
        return self.base_url

    def _do_login(self) -> bool:
        """PoW + 登录。"""
        base = self._get_base()
        # PoW（已验证则内部跳过；失败也尝试登录，cookie 可能仍有效）
        solve_pow(self._session, base)
        try:
            self._session.headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "Referer": base + "/user/login",
                "Origin": base,
            })
            lr = self._session.post(
                base + "/user/login",
                data={
                    "code": "", "siteid": "1", "dosubmit": "1",
                    "username": self.username, "password": self.password,
                    "cookietime": "1",
                },
                timeout=15, verify=False,
            )
            rj = lr.json()
            if rj.get("code") == 200:
                self._logged_in = True
                self._login_ts = time.time()
                self._session_searched = False  # 新 session 重置搜索标记
                logger.info("[muliy_site] 登录成功")
                return True
            logger.error(f"[muliy_site] 登录失败: {rj}")
            return False
        except Exception as e:
            logger.error(f"[muliy_site] 登录异常: {e}")
            return False

    def ensure_session(self) -> bool:
        """确保已登录，过期则重新登录。线程安全。"""
        with self._lock:
            if self._logged_in and (time.time() - self._login_ts < self.cache_ttl):
                return True
            return self._do_login()

    def _relogin_on_fail(self) -> bool:
        """失效后重新登录一次。"""
        self._logged_in = False
        return self._do_login()

    def _api_get(self, path: str, referer: str = "", as_json: bool = True,
                 retry: bool = True):
        """带登录保障的 GET。"""
        base = self._get_base()
        if not self.ensure_session():
            return None
        hdrs = {"X-Requested-With": "XMLHttpRequest",
                "Referer": referer or (base + "/")}
        try:
            r = self._session.get(base + path, headers=hdrs,
                                  timeout=15, verify=False)
        except Exception as e:
            logger.error(f"[muliy_site] GET {path} 请求异常: {e}")
            if retry and self._relogin_on_fail():
                return self._api_get(path, referer, as_json, retry=False)
            return None

        if not as_json:
            return r.text

        try:
            return r.json()
        except Exception:
            txt = r.text[:300]
            low = txt.lower()
            # nologin / PoW 验证页 / 失效 → 重新登录重试
            need_relogin = ("nologin" in low or "powSolve" in txt
                            or "安全验证" in txt or "未登录" in txt
                            or r.status_code in (401, 403))
            logger.warning(f"[muliy_site] {path} 返回非JSON status={r.status_code} "
                           f"relogin={need_relogin}: {txt[:120]}")
            if retry and need_relogin and self._relogin_on_fail():
                return self._api_get(path, referer, as_json, retry=False)
            return None

    # ---------- 业务接口 ----------
    # 搜索结果缓存 {keyword: (results, ts)}，5分钟有效，避免频繁请求触发限流
    _SEARCH_CACHE: dict = {}
    _SEARCH_CACHE_TTL = 300
    _LAST_SEARCH_TS = 0.0

    def _do_search_once(self, keyword: str, max_results: int) -> list:
        """单次搜索（不缓存不降级）。

        网站搜索限流：同一 session 的 /res/search_suggest 只允许搜1次，
        第2次起返回空字符串。因此若当前 session 已搜过且返回空，
        自动 relogin 换新 session 重试一次。
        """
        data = self._api_get("/res/search_suggest?q=" + quote(keyword),
                             referer=self._get_base() + "/")
        if not isinstance(data, list):
            data = []
        # 限流检测：当前 session 已搜过 + 返回空 → relogin 换新 session 重试
        if not data and self._session_searched:
            logger.warning(f"[muliy_site] search_suggest 返回空(session已搜过，疑似限流)，relogin重试")
            if self._relogin_on_fail():
                data = self._api_get("/res/search_suggest?q=" + quote(keyword),
                                     referer=self._get_base() + "/")
                if not isinstance(data, list):
                    data = []
        self._session_searched = True  # 标记已搜过（后续搜索可能被限）
        results = []
        for item in data[:max_results]:
            results.append({
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "year": str(item.get("year", "")),
                "type": item.get("type", ""),
                "dir": item.get("dir", "mv"),
                "score": str(item.get("score", "")),
            })
        return results

    def search(self, keyword: str, max_results: int = 20) -> list:
        """搜索影视。联想接口是前缀匹配，对带后缀的查询返回空，
        因此自动降级（去空格后缀/去"第X季"/去末尾数字）重试。
        带缓存（5分钟）+ 请求间隔（1秒）防限流。"""
        cache_key = keyword.strip()
        # 缓存命中（注意：空结果不视为命中，避免限流瞬态空结果污染长缓存）
        cached = MuliySiteClient._SEARCH_CACHE.get(cache_key)
        if cached and cached[0] and (time.time() - cached[1] < MuliySiteClient._SEARCH_CACHE_TTL):
            logger.debug(f"[muliy_site] 搜索 '{keyword}' 缓存命中 {len(cached[0])} 条")
            return cached[0][:max_results]

        # 降级关键词候选（原词 → 逐步简化）
        candidates = [cache_key]
        s1 = re.sub(r"\s+\S+$", "", cache_key).strip()  # 去空格后缀
        if s1 and s1 not in candidates:
            candidates.append(s1)
        s2 = re.sub(r"\s*第[一二三四五六七八九十\d]+季\s*$", "", cache_key).strip()  # 去"第X季"
        if s2 and s2 not in candidates:
            candidates.append(s2)
        s3 = re.sub(r"[2-9]$", "", cache_key).strip()  # 去末尾数字
        if s3 and s3 not in candidates:
            candidates.append(s3)

        results = []
        for kw in candidates:
            # 降级时先查缓存（避免重复请求触发限流）；空结果不当命中
            cached = MuliySiteClient._SEARCH_CACHE.get(kw)
            if cached and cached[0] and (time.time() - cached[1] < MuliySiteClient._SEARCH_CACHE_TTL):
                results = cached[0]
                logger.info(f"[muliy_site] 搜索 '{kw}' 缓存命中 {len(results)} 条"
                            f"{' (降级)' if kw != cache_key else ''}")
                if results:
                    break
                continue  # 缓存空结果，跳过该候选词不重复请求
            # 请求间隔（至少1.5秒），避免触发联想接口限流
            gap = time.time() - MuliySiteClient._LAST_SEARCH_TS
            if gap < 1.5:
                time.sleep(1.5 - gap)
            MuliySiteClient._LAST_SEARCH_TS = time.time()
            results = self._do_search_once(kw, max_results)
            if results:
                MuliySiteClient._SEARCH_CACHE[kw] = (results, time.time())
                logger.info(f"[muliy_site] 搜索 '{kw}' -> {len(results)} 个结果"
                            f"{' (降级)' if kw != cache_key else ''}")
                break  # 有结果就不再降级
            logger.info(f"[muliy_site] 搜索 '{kw}' -> 0 个结果（空结果不写缓存，"
                        f"限流瞬态可自愈）")

        return results

    def get_detail(self, dir_: str, id_: str) -> dict:
        """获取详情（解析详情页内联 _obj.d）。带 nologin 重登重试。"""
        base = self._get_base()
        empty = {"name": "获取失败", "desc": "登录失败", "cover": "",
                 "year": "", "dir": dir_, "id": id_, "status": "",
                 "daoyan": [], "zhuyan": [], "leixing": [], "diqu": [],
                 "score_db": "", "score_im": ""}
        if not self.ensure_session():
            return empty
        for attempt in range(2):  # 最多重试一次（重登）
            try:
                r = self._session.get(
                    base + f"/{dir_}/{id_}",
                    headers={"Referer": base + "/"},
                    timeout=15, verify=False,
                )
                txt = r.text
                # 有效详情页必须含内联 _obj.d；否则一律视为未登录/安全验证页。
                # ★关键修复：检测必须扫整页文本（中文「未登录」+ 英文 nologin 可能在
                # 300 字符之后，旧逻辑只扫前300字符导致漏检，parse_detail_html 兜底成
                # "未知影视"）。
                if "_obj.d" not in txt:
                    blocked = ("未登录" in txt or "nologin" in txt.lower()
                               or "powSolve" in txt or "安全验证" in txt
                               or "访问受限" in txt or "pow" in txt.lower())
                    logger.warning(f"[muliy_site] 详情页非有效页(attempt={attempt}) "
                                   f"blocked={blocked} len={len(txt)}")
                    if self._relogin_on_fail():
                        continue
                    return empty
                detail = parse_detail_html(txt, dir_, id_)
                # 若解析出真实标题则成功；否则可能页面结构异常
                if detail.get("name") and detail["name"] != "未知影视":
                    return detail
                # 解析失败但页面非 nologin：可能是 _obj.d 结构异常，返回带 cover 的兜底
                detail["cover"] = cover_url(dir_, id_)
                return detail
            except Exception as e:
                logger.error(f"[muliy_site] 详情获取失败: {e}")
                if attempt == 0 and self._relogin_on_fail():
                    continue
                empty["desc"] = str(e)[:120]
                return empty
        return empty

    def get_resources(self, dir_: str, id_: str) -> dict:
        """获取在线播放节点 + 网盘资源。"""
        data = self._api_get(f"/res/downurl/{dir_}/{id_}",
                             referer=self._get_base() + f"/{dir_}/{id_}")
        if not isinstance(data, dict) or data.get("code") != 200:
            logger.warning(f"[muliy_site] 资源获取异常: {str(data)[:120]}")
            return {"playlist": [], "panlist": []}

        # 在线播放节点
        playlist = []
        for p in (data.get("playlist") or []):
            ep_start, ep_end = 1, 0
            try:
                for seg in (p.get("list") or []):
                    if len(seg) >= 2 and isinstance(seg[1], list) and len(seg[1]) == 2:
                        ep_start, ep_end = int(seg[1][0]), int(seg[1][1])
                        break
            except Exception:
                pass
            playlist.append({
                "i": p.get("i", ""),
                "t": p.get("t", ""),
                "ep_start": ep_start,
                "ep_end": ep_end,
            })

        # 网盘资源（并行数组）
        panlist = []
        pl = data.get("panlist") or {}
        tname = pl.get("tname", []) or []
        ids = pl.get("id", []) or []
        names = pl.get("name", []) or []
        urls = pl.get("url", []) or []
        types = pl.get("type", []) or []
        users = pl.get("user", []) or []
        times = pl.get("time", []) or []
        for k in range(len(ids)):
            t_idx = types[k] if k < len(types) and isinstance(types[k], int) else -1
            pan_name = tname[t_idx] if 0 <= t_idx < len(tname) else "网盘"
            panlist.append({
                "name": names[k] if k < len(names) else "",
                "url": urls[k] if k < len(urls) else "",
                "type": pan_name,
                "user": users[k] if k < len(users) else "",
                "time": times[k] if k < len(times) else "",
            })

        logger.info(f"[muliy_site] 资源: 播放节点 {len(playlist)} 个, 网盘 {len(panlist)} 个")
        return {"playlist": playlist, "panlist": panlist}

    def get_play_m3u8(self, node_i: str, ep: int = 1) -> str:
        """获取播放页的 m3u8 直链。

        播放页 /py/{node_i}/{ep} 内联 _obj.player.url 即 m3u8 直链。
        注意：该页在 cookie 失效时会返回「未登录，访问受限」或「浏览器安全验证」
        页（无 _obj.player），必须重做 PoW+登录后重试才能拿到直链。
        """
        base = self._get_base()
        if not self.ensure_session():
            return ""
        for attempt in range(3):
            try:
                r = self._session.get(
                    base + f"/py/{node_i}/{ep}",
                    headers={"Referer": base + "/"},
                    timeout=15, verify=False,
                )
                txt = r.text
                # 有效播放页必须含 _obj.player；否则一律视为未登录/安全验证页
                if "_obj.player" not in txt:
                    blocked = ("未登录" in txt or "nologin" in txt.lower()
                               or "powSolve" in txt or "安全验证" in txt
                               or "访问受限" in txt or "pow" in txt.lower())
                    logger.warning(f"[muliy_site] 播放页非有效页(attempt={attempt}) "
                                   f"blocked={blocked} len={len(txt)}")
                    # 强制刷新登录（solve_pow 已改为每次重算 PoW）后重试
                    if self._relogin_on_fail():
                        continue
                    return ""
                m = re.search(r"_obj\.player\s*=\s*(\{)", txt)
                if not m:
                    logger.warning(f"[muliy_site] 播放页无 _obj.player")
                    return ""
                block = _extract_balanced(txt, m.start(1))
                d = json.loads(block)
                url = d.get("url", "")
                if not url:
                    logger.warning(f"[muliy_site] _obj.player 无 url 字段")
                    return ""
                # 解析 302 得到最终可播放直链（如 svip.xgplayN.com → vipN.jimxtc.com）
                url = self._resolve_media_url(url, base)
                logger.info(f"[muliy_site] m3u8提取成功 node={node_i} ep={ep} -> {url[:80]}")
                return url
            except Exception as e:
                logger.error(f"[muliy_site] m3u8提取失败(attempt={attempt}): {e}")
                if attempt < 2 and self._relogin_on_fail():
                    continue
                return ""
        return ""

    def _resolve_media_url(self, url: str, base: str) -> str:
        """解析 m3u8 可能的 302 跳转，返回最终可直接播放的直链。失败则原样返回。"""
        if not url:
            return url
        try:
            rr = requests.get(
                url,
                headers={"User-Agent": MULIY_UA, "Referer": (base + "/")},
                timeout=15, verify=False, allow_redirects=True, stream=True,
            )
            final = rr.url
            rr.close()
            if final and final != url:
                logger.info(f"[muliy_site] m3u8 302 解析: {url[:60]} -> {final[:60]}")
            return final or url
        except Exception as e:
            logger.warning(f"[muliy_site] m3u8 跳转解析失败，沿用原链: {e}")
            return url


# ==================== VIP 解析（/zjx 解析页） ====================
#
# 教父.com（挂了.com 发布的域名簇）自带「VIP 解析」功能，解析页即 <域名>/zjx。
# 把外部视频分享链接（爱奇艺/腾讯视频/优酷/芒果TV/乐视/搜狐）提交到该页，
# 站点后端会还原出真实可播放直链（.m3u8 / .mp4），这正是视频链接解析想要的「直链」。
#
# 与影视搜索共用同一套 PoW+登录会话与域名探测，避免重复登录/探测。

_M3U8_MP4_RE = re.compile(r"\.m3u8|\.mp4", re.I)


def _extract_vip_media_urls(html: str) -> list:
    """从解析页 HTML 中提取候选直链（.m3u8 / .mp4）及解析 iframe/src。

    按「内联 player 对象 → iframe/source src → 裸链」的顺序收集，去重保序。
    """
    if not html:
        return []
    cands = []
    # 1) 内联 player 对象 / JSON url 字段：_obj.player = {url:"..."}、var url="..." 等
    for m in re.finditer(
        r'(?:url|src|playUrl|vurl|m3u8|play_url)\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4))(?:\?[^"\']*)?["\']',
        html, re.I):
        cands.append(m.group(1))
    # 2) iframe / source 标签的 src（可能是媒体，也可能是解析接口）
    for m in re.finditer(r'<(?:iframe|source)[^>]+src=["\']([^"\']+)["\']', html, re.I):
        cands.append(m.group(1))
    # 3) 裸链 .m3u8 / .mp4
    for m in re.finditer(r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)(?:\?[^"\'<>]*)?', html):
        cands.append(m.group(0))
    seen, out = set(), []
    for u in cands:
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_vip_url(video_url: str, username: str = "", password: str = "",
                 client: "MuliySiteClient" = None, base_url: str = "") -> dict:
    """把外部视频链接提交到教父.com 的 /zjx VIP 解析页，解析出可播放直链。

    参数：
      - video_url：待解析的视频分享链接（爱奇艺/腾讯/优酷/芒果TV/乐视/搜狐）
      - client：    已登录的 MuliySiteClient（优先复用其会话/域名）；为空则临时新建
      - username/password/base_url：新建 client 时使用（与影视搜索共用账号）
    返回 {"ok", "url", "platform_page", "candidates", "error", "raw"}。
      - ok=True 时 url 为真实可播放直链；ok=False 时 url 为空，error 说明原因，
        raw 附带解析页 HTML 前若干字符便于排障。
    """
    own = False
    if client is None:
        client = MuliySiteClient(username or "", password or "", base_url=base_url)
        own = True
    if not client.ensure_session():
        return {"ok": False, "url": "", "platform_page": "", "candidates": [],
                "error": "影视站登录失败（请检查 muliy_username/muliy_password 配置）", "raw": ""}
    base = client._get_base()
    page = base + "/zjx"
    encoded = quote(video_url, safe="")
    headers = {"Referer": base + "/", "X-Requested-With": "XMLHttpRequest"}
    candidates = []
    raw = ""
    try:
        # 方式1：GET ?url=（解析网最常见形态）
        get_url = page + "?url=" + encoded
        logger.info(f"[muliy_site] VIP 解析 GET {get_url[:120]}")
        r = client._session.get(get_url, headers=headers,
                                timeout=20, verify=False, allow_redirects=True)
        html = r.text or ""
        raw = html[:1200]
        logger.info(f"[muliy_site] VIP 解析 GET 结果 status={r.status_code} len={len(html)} final_url={r.url[:100]}")
        if r.url and _M3U8_MP4_RE.search(r.url):
            return {"ok": True, "url": r.url, "platform_page": page,
                    "candidates": [r.url], "error": "", "raw": raw}
        candidates += _extract_vip_media_urls(html)
        logger.info(f"[muliy_site] VIP 解析 GET candidates={candidates}")
        # 方式2：POST 表单（部分站点用表单提交）
        if not candidates:
            logger.info(f"[muliy_site] VIP 解析 POST {page} data=url={video_url[:60]}")
            rp = client._session.post(page, data={"url": video_url}, headers=headers,
                                      timeout=20, verify=False, allow_redirects=True)
            html2 = rp.text or ""
            raw = (raw + "\n--POST--\n" + html2[:1200])
            logger.info(f"[muliy_site] VIP 解析 POST 结果 status={rp.status_code} len={len(html2)} final_url={rp.url[:100]}")
            if rp.url and _M3U8_MP4_RE.search(rp.url):
                return {"ok": True, "url": rp.url, "platform_page": page,
                        "candidates": [rp.url], "error": "", "raw": raw}
            candidates += _extract_vip_media_urls(html2)
            logger.info(f"[muliy_site] VIP 解析 POST candidates={candidates}")
    except Exception as e:
        logger.exception(f"[muliy_site] VIP 解析请求异常: {e}")
        return {"ok": False, "url": "", "platform_page": page, "candidates": [],
                "error": f"请求解析页异常：{e}", "raw": raw}

    # 优先返回直接的媒体直链
    media = [u for u in candidates if _M3U8_MP4_RE.search(u)]
    if media:
        logger.info(f"[muliy_site] VIP 解析成功 media={media[0][:120]}")
        return {"ok": True, "url": media[0], "platform_page": page,
                "candidates": candidates, "error": "", "raw": raw}

    # 仅有解析接口 iframe/src（非媒体）：再追一层取媒体（最多 1 层，防死循环）
    for u in candidates:
        if u.startswith("http") and re.search(r"jx|parse|api|/zjx|player|vip", u, re.I):
            try:
                logger.info(f"[muliy_site] VIP 解析追一层 {u[:120]}")
                rr = client._session.get(u, headers={"Referer": page}, timeout=20,
                                         verify=False, allow_redirects=True)
                deeper = _extract_vip_media_urls(rr.text or "")
                media_deeper = [d for d in deeper if _M3U8_MP4_RE.search(d)]
                logger.info(f"[muliy_site] VIP 解析追一层 candidates={deeper}")
                if media_deeper:
                    return {"ok": True, "url": media_deeper[0], "platform_page": page,
                            "candidates": candidates + deeper, "error": "",
                            "raw": raw + "\n--deep--\n" + (rr.text or "")[:400]}
            except Exception:
                continue

    if candidates:
        # 有候选但都不是媒体（如解析页仅前端 JS 动态加载播放器，需浏览器渲染）
        logger.warning(f"[muliy_site] VIP 解析未命中媒体 candidates={candidates} raw[:200]={raw[:200]}")
        return {"ok": False, "url": "", "platform_page": page, "candidates": candidates,
                "error": "解析页未返回可直接播放的直链（可能为前端 JS 动态加载，需浏览器渲染）",
                "raw": raw}
    logger.warning(f"[muliy_site] VIP 解析无任何候选 raw[:300]={raw[:300]}")
    return {"ok": False, "url": "", "platform_page": page, "candidates": [],
            "error": "解析页未找到任何直链/解析接口", "raw": raw}


# ==================== URL 构造 ====================

def cover_url(dir_: str, id_: str, size: int = 256) -> str:
    """封面图 URL。格式：{imghost}/img/{dir}/{id}/{size}.webp"""
    return f"{MULIY_IMG_HOST}/img/{dir_}/{id_}/{size}.webp"


def play_url(base: str, node_i: str, ep: int = 1) -> str:
    """在线播放页 URL。"""
    return f"{base.rstrip('/')}/py/{node_i}/{ep}"


# ==================== 格式化函数 ====================

def format_movie_list_new(results: list, keyword: str, page: int = 0,
                          page_size: int = 8) -> str:
    """格式化搜索列表：[N] 标题 【类型·年份】。"""
    t = len(results)
    if t == 0:
        return f"🎬 搜索过于频繁，请稍后再试。"
    pt = (t + page_size - 1) // page_size
    page = max(0, min(page, pt - 1))
    st = page * page_size
    ed = min(st + page_size, t)
    lines = [f"🎬 共找到 {t} 个「{keyword}」相关影视，当前第 {page+1}/{pt} 页"]
    lines.append("=" * 36)
    lines.append("")
    for i in range(st, ed):
        x = results[i]
        title = x["title"]
        title_trim = (title[:30] + "...") if len(title) > 33 else title
        tp = x.get("type", "")
        yr = x.get("year", "")
        sc = x.get("score", "")
        tag = ""
        if tp and yr:
            tag = f" 【{tp}·{yr}】"
        elif tp:
            tag = f" 【{tp}】"
        elif yr:
            tag = f" 【{yr}】"
        if sc:
            tag += f" ⭐{sc}"
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
    lines.append(f"⏱️ 120秒无操作自动取消。")
    lines.append("回复数字选择影视，回复0取消。")
    return "\n".join(lines)


def format_resource_type(detail: dict, resources: dict) -> str:
    """格式化资源类型选择：[1]在线播放 [2]网盘资源。"""
    name = detail.get("name", "未知")
    year = detail.get("year", "")
    status = detail.get("status", "")
    score = detail.get("score_db", "")
    head = f"🎬 {name}"
    if year:
        head += f" ({year})"
    if score:
        head += f" 豆瓣{score}"
    lines = [head, "=" * 36]
    if status:
        lines.append(f"📺 {status}")
    leixing = detail.get("leixing", [])
    diqu = detail.get("diqu", [])
    info_parts = []
    if leixing:
        info_parts.append(" / ".join(leixing))
    if diqu:
        info_parts.append(" / ".join(diqu))
    if info_parts:
        lines.append("🏷️ " + " · ".join(info_parts))
    lines.append("")
    lines.append("本片提供以下资源：")
    n_play = len(resources.get("playlist", []))
    n_pan = len(resources.get("panlist", []))
    lines.append(f"{emoji_index(1, 2)} ▶ 在线播放 ({n_play}个节点)")
    lines.append(f"{emoji_index(2, 2)} 📁 网盘资源 ({n_pan}个)")
    lines.append("")
    lines.append("⏱️ 120秒无操作自动取消。回复 0 取消。")
    return "\n".join(lines)


def format_play_nodes(playlist: list) -> str:
    """格式化在线播放节点列表。"""
    n = len(playlist)
    if n == 0:
        return "😕 该影视暂无在线播放节点。"
    lines = [f"▶ 在线播放节点（共 {n} 个）：", "=" * 36, ""]
    for i, p in enumerate(playlist, 1):
        t = p.get("t", f"节点{i}")
        ep_end = p.get("ep_end", 0)
        ep_info = f"（共{ep_end}集）" if ep_end and ep_end > 1 else ""
        lines.append(f"{emoji_index(i, n)} {t}{ep_info}")
    lines.append("")
    lines.append(f"💬 请输入节点序号（1-{n}）选择；回复 0 取消。")
    lines.append("⏱️ 120秒无操作自动取消。")
    return "\n".join(lines)


def extract_pwd(url: str) -> str:
    """从网盘链接里解析提取码（?pwd=xxxx 或 &pwd=xxxx）。"""
    m = re.search(r'[?&]pwd=([a-zA-Z0-9]{4,8})', url or "")
    return m.group(1) if m else ""


def group_panlist_by_type(panlist: list) -> list:
    """按网盘类型分组统计，返回 [(类型, 数量), ...] 按数量降序。"""
    groups = {}
    for p in panlist:
        t = p.get("type", "其他")
        groups[t] = groups.get(t, 0) + 1
    return sorted(groups.items(), key=lambda x: -x[1])


def format_pan_types(type_counts: list) -> str:
    """格式化网盘分类选择列表：[1] ☁️百度网盘 (45个)。"""
    n = len(type_counts)
    if n == 0:
        return "😕 该影视暂无网盘资源。"
    lines = [f"📁 网盘资源分类（共 {n} 种网盘，选一个查看）：", "=" * 36, ""]
    for i, (t, cnt) in enumerate(type_counts, 1):
        icon = MULIY_PAN_ICONS.get(t, "💾")
        lines.append(f"{emoji_index(i, n)} {icon} {t} ({cnt}个)")
    lines.append("")
    lines.append(f"💬 请输入序号（1-{n}）选择网盘类型；回复 0 取消。")
    lines.append("⏱️ 120秒无操作自动取消。")
    return "\n".join(lines)


def format_pan_list(panlist: list, page: int = 0, page_size: int = 12,
                    type_filter: str = "") -> str:
    """格式化网盘资源列表（分页）。type_filter 非空时只显示该类型。"""
    if type_filter:
        panlist = [p for p in panlist if p.get("type", "") == type_filter]
    t = len(panlist)
    if t == 0:
        return f"😕 该影视暂无{type_filter}网盘资源。"
    pt = (t + page_size - 1) // page_size
    page = max(0, min(page, pt - 1))
    st = page * page_size
    ed = min(st + page_size, t)
    show = panlist[st:ed]
    head = f"📁 {type_filter + ' ' if type_filter else ''}网盘资源（共 {t} 个"
    if pt > 1:
        head += f"，第 {page+1}/{pt} 页"
    head += "）："
    lines = [head, "=" * 36, ""]
    for i, p in enumerate(show, 1):
        icon = MULIY_PAN_ICONS.get(p.get("type", ""), "💾")
        name = p.get("name", "")
        name_trim = (name[:34] + "...") if len(name) > 37 else name
        usr = p.get("user", "")
        tm = p.get("time", "")
        tail = ""
        if usr or tm:
            tail = f"  ({usr}·{tm})" if usr and tm else (f"  ({usr})" if usr else f"  ({tm})")
        lines.append(f"{emoji_index(i, ed - st)} {icon} {name_trim}{tail}")
    lines.append("")
    if pt > 1:
        nav = []
        if st > 0:
            nav.append("「上一页」")
        if ed < t:
            nav.append("「下一页」")
        lines.append("💡 翻页指令： " + " ｜ ".join(nav))
    lines.append(f"💬 请输入序号（1-{ed-st}）选择网盘；回复 0 取消。")
    lines.append("⏱️ 120秒无操作自动取消。")
    return "\n".join(lines)


def build_merged_text(detail: dict, link: str, link_label: str) -> str:
    """构建合并转发用的纯文本内容。"""
    name = detail.get("name", "未知影视")
    year = detail.get("year", "")
    lines = [f"🎬 {name}" + (f" ({year})" if year else "")]
    status = detail.get("status", "")
    if status:
        lines.append(f"📺 {status}")
    score_db = detail.get("score_db", "")
    score_im = detail.get("score_im", "")
    sc = []
    if score_db:
        sc.append(f"豆瓣{score_db}")
    if score_im:
        sc.append(f"IMDb{score_im}")
    if sc:
        lines.append("⭐ " + " · ".join(sc))
    leixing = detail.get("leixing", [])
    diqu = detail.get("diqu", [])
    info = []
    if leixing:
        info.append(" / ".join(leixing))
    if diqu:
        info.append(" / ".join(diqu))
    if info:
        lines.append("🏷️ " + " · ".join(info))
    zhuyan = detail.get("zhuyan", [])
    if zhuyan:
        lines.append("🎭 主演：" + " / ".join(zhuyan[:8]))
    desc = detail.get("desc", "")
    if desc and desc != "暂无简介":
        lines.append("")
        lines.append("📖 简介：")
        lines.append(desc[:600])
    lines.append("")
    lines.append(f"🔗 {link_label}：")
    lines.append(link)
    pwd = extract_pwd(link)
    if pwd:
        lines.append(f"🔑 提取码：{pwd}")
    return "\n".join(lines)

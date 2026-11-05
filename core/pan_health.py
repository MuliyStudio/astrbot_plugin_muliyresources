# -*- coding: utf-8 -*-
"""网盘资源过期概率评估 + 选中时真实链接校验。

影视网盘接口只返回 name / url / type / user / time，没有官方过期标记。
这里提供两级判断：

1. 本地概率模型（零延迟、不发请求）
   - 分享发布时间（time）越久，过期概率越高；
   - 不同网盘典型有效期不同（夸克/UC/阿里偏短，115/磁力偏长）；
   - 叠加历史失效反馈（用户实际点到失效链接后自动记录）。
   输出 0-100 的过期概率，列表里打标（🟢/🟡/🟠/🔴）并置底。

2. 真实链接校验（仅在用户选中某条网盘时触发）
   - 请求一次分享页，命中「分享已过期 / 已取消 / 不存在」等强标记 → dead；
   - 网络失败 / 403 / 风控 → unknown（不影响用户，按原流程继续）；
   - 确认失效后记录反馈，下次列表里该资源直接置底。

对外接口：
    annotate_panlist(panlist, reports=None) -> list[dict]   # 打标 + 按风险升序
    check_pan_link(url, pan_type="", timeout=6) -> str      # "ok"/"dead"/"unknown"
    score_pan(pan, reports=None) -> dict                    # 单条评分
    PanReportStore(path)                                    # 失效反馈持久化
"""
import json
import math
import os
import re
import time
from datetime import datetime, timedelta

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None


# ==================== 网盘典型有效期（天） ====================

# 估算用：资源站公开分享链接的常见存活周期。
# 命中顺序为「长关键词优先」（如「阿里云盘」先于「阿里」）。
PAN_LIFETIME_DAYS = (
    ("磁力", 3650), ("ed2k", 3650), ("迅雷", 90), ("115", 180),
    ("百度", 60), ("天翼", 45), ("123", 90), ("阿里", 30),
    ("夸克", 30), ("uc", 30), ("UC", 30), ("移动", 30),
)
DEFAULT_LIFETIME_DAYS = 45

LEVELS = (
    (35, "fresh", "🟢", "较新"),
    (65, "ok", "🟡", "一般"),
    (85, "risky", "🟠", "偏高"),
    (101, "high", "🔴", "极高"),
)

# 确认失效（用户点到 404 / 分享取消）后的保底分数
DEAD_SCORE = 97


def _now() -> float:
    return time.time()


# ==================== 时间解析 ====================

_REL_TIME_RE = re.compile(r"(\d+)\s*(秒|分钟|分|小时|时|天|周|个月|月|年)\s*前")


def parse_pan_time(value):
    """把网盘接口的 time 字段解析成 datetime；解析不了返回 None。

    兼容：10/13 位时间戳、"2025-08-19"、"2025/8/19"、"2025年8月19日"、
    "08-19"、"3天前"、"昨天"、"刚刚"、"2025"。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 1e11:      # 毫秒
                ts /= 1000.0
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None

    s = str(value).strip()
    if not s:
        return None

    # 纯时间戳
    if re.fullmatch(r"\d{10}|\d{13}", s):
        try:
            ts = float(s)
            if len(s) == 13:
                ts /= 1000.0
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None

    now = datetime.now()

    # 相对时间
    if any(k in s for k in ("刚刚", "刚才", "just now")):
        return now
    if "昨天" in s:
        return now - timedelta(days=1)
    if "前天" in s:
        return now - timedelta(days=2)
    if "今天" in s:
        return now
    m = _REL_TIME_RE.search(s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        factor = {
            "秒": 1 / 86400.0, "分钟": 1 / 1440.0, "分": 1 / 1440.0,
            "小时": 1 / 24.0, "时": 1 / 24.0, "天": 1.0,
            "周": 7.0, "个月": 30.0, "月": 30.0, "年": 365.0,
        }.get(unit, 1.0)
        return now - timedelta(days=n * factor)

    # 绝对日期：补齐时间部分
    s2 = re.sub(r"[年月]", "-", s)
    s2 = s2.replace("日", " ").replace("/", "-").replace(".", "-")
    s2 = re.sub(r"\s+", " ", s2).strip(" -")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s2)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4) or 0), int(m.group(5) or 0),
                            int(m.group(6) or 0))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})-(\d{1,2})$", s2)
    if m:
        try:
            return datetime(now.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.fullmatch(r"(20\d{2})", s2)
    if m:
        try:
            return datetime(int(m.group(1)), 1, 1)
        except ValueError:
            return None
    return None


def lifetime_days(pan_type: str) -> int:
    t = (pan_type or "").strip()
    low = t.lower()
    for key, days in PAN_LIFETIME_DAYS:
        if key.lower() in low:
            return days
    return DEFAULT_LIFETIME_DAYS


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    u = u.split("#", 1)[0].rstrip("/")
    return u.lower()


# ==================== 评分 ====================

def _level(score: int) -> tuple:
    for limit, key, emoji, label in LEVELS:
        if score < limit:
            return key, emoji, label
    return "high", "🔴", "极高"


def score_pan(pan: dict, reports=None) -> dict:
    """估算单条网盘资源的过期概率，返回打标信息。

    score: 0(很新鲜) ~ 100(基本确定过期)
    level: fresh / ok / risky / high
    """
    pan = pan or {}
    url = pan.get("url") or ""
    pan_type = pan.get("type") or ""
    reports = reports or {}

    if not url:
        return {"score": 100, "level": "high", "emoji": "🔴",
                "label": "无链接", "age_days": None, "lifetime": None,
                "reports": 0, "detail": "资源缺少链接"}

    rep_n = 0
    try:
        rep = reports.get(_normalize_url(url))
        if isinstance(rep, dict):
            rep_n = int(rep.get("n") or 0)
        elif isinstance(rep, (int, float)):
            rep_n = int(rep)
    except Exception:  # noqa: BLE001
        rep_n = 0

    dt = parse_pan_time(pan.get("time"))
    life = lifetime_days(pan_type)

    if dt is None:
        score = 45
        age_days = None
        detail = "发布时间未知"
    else:
        age_days = max(0.0, (_now() - dt.timestamp()) / 86400.0)
        ratio = age_days / max(1.0, float(life))
        # 指数曲线：刚发布≈0，达到典型有效期≈63，超过 2 倍≈86
        score = int(round(100 * (1 - math.exp(-ratio))))
        score = max(0, min(100, score))
        detail = f"已发布 {_age_text(age_days)}"

    # 历史失效反馈：1 次≈88（高危/置底），2 次≈97（基本确定）
    if rep_n > 0:
        score = max(score, min(DEAD_SCORE, 66 + 22 * rep_n))

    key, emoji, label = _level(score)
    return {
        "score": score, "level": key, "emoji": emoji, "label": label,
        "age_days": age_days, "lifetime": life, "reports": rep_n,
        "detail": detail,
    }


def _age_text(days: float) -> str:
    if days < 1:
        return "1 天内"
    if days < 30:
        return f"{int(days)} 天"
    if days < 365:
        return f"{int(days / 30)} 个月"
    return f"{days / 365:.1f} 年"


def annotate_panlist(panlist, reports=None, sort: bool = True,
                     force: bool = False) -> list:
    """给网盘列表逐条打标，并按其过期概率升序排列（高危置底）。

    - 不修改传入的原始列表（返回浅拷贝）；
    - 已带 _health 的条目不会重复计算（force=True 时强制重算）；
    - 稳定排序：同分保持原始顺序；
    - sort=False 时只打标不改顺序（用于展示兜底，避免与选择序号错位）。
    """
    items = []
    for idx, p in enumerate(panlist or []):
        q = dict(p or {})
        if force or not isinstance(q.get("_health"), dict):
            q["_health"] = score_pan(q, reports)
        q["_orig"] = idx
        items.append(q)
    if sort:
        items.sort(key=lambda x: (int((x.get("_health") or {}).get("score", 50)), x["_orig"]))
    return items


def health_summary(panlist) -> dict:
    """统计各风险等级数量，用于列表页脚提示。"""
    out = {"fresh": 0, "ok": 0, "risky": 0, "high": 0, "total": 0}
    for p in panlist or []:
        h = p.get("_health") if isinstance(p.get("_health"), dict) else {}
        lv = h.get("level") or "ok"
        if lv not in out:
            lv = "ok"
        out[lv] += 1
        out["total"] += 1
    return out


# ==================== 真实链接校验 ====================

# 强失效标记：只在分享页服务端渲染文本里出现，误判概率低。
_EXPIRED_MARKERS = (
    "分享已过期", "该分享已过期", "分享过期",
    "分享已被取消", "该分享已被取消", "已取消分享", "分享者已取消",
    "分享已失效", "该分享已失效", "分享不存在", "分享的文件已经被取消",
    "分享已被删除", "分享内容已被删除", "文件已被删除",
    "链接已失效", "该链接已失效", "链接不存在", "内容不存在",
    "啊哦，你来晚了", "你访问的页面不存在", "页面不存在",
)

# 命中这些说明页面仍需登录/风控，不能判定为失效（按 unknown 处理）
_INCONCLUSIVE_MARKERS = (
    "请输入提取码", "提取码错误", "访问码", "安全验证", "验证码",
    "登录后查看", "请先登录", "人机验证", "访问过于频繁",
)

_PAN_REFERER = {
    "百度": "https://pan.baidu.com/",
    "夸克": "https://pan.quark.cn/",
    "阿里": "https://www.aliyundrive.com/",
    "UC": "https://drive.uc.cn/",
    "uc": "https://drive.uc.cn/",
    "115": "https://115.com/",
    "迅雷": "https://pan.xunlei.com/",
    "天翼": "https://cloud.189.cn/",
    "123": "https://www.123pan.com/",
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# 校验结果缓存：{url: (ts, status)}
_CHECK_CACHE: dict = {}
_CHECK_TTL = 600

# 官方分享接口（比抓 HTML 准：夸克/UC 的分享页是前端渲染，页面里没有失效文案）
_QUARK_API = "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token?pr=ucpro&fr=pc"
_UC_API = "https://pc-api.uc.cn/1/clouddrive/share/sharepage/token?pr=UCBrowser&fr=pc"
_ALIYUN_API = "https://api.aliyundrive.com/adrive/v3/share_link/get_share_by_anonymous"

# 夸克/UC 分享接口的失效码（其余非 0 码多为要提取码/风控，按未知处理）
_DRIVE_DEAD_CODES = {41004, 41006, 41008, 41011}


def _cache_get(url: str):
    item = _CHECK_CACHE.get(url)
    if not item:
        return None
    ts, status = item
    if time.time() - ts > _CHECK_TTL:
        _CHECK_CACHE.pop(url, None)
        return None
    return status


def _cache_put(url: str, status: str):
    if len(_CHECK_CACHE) > 800:
        _CHECK_CACHE.clear()
    _CHECK_CACHE[url] = (time.time(), status)


def _referer_for(pan_type: str) -> str:
    t = pan_type or ""
    for key, ref in _PAN_REFERER.items():
        if key in t:
            return ref
    return ""


def _provider(url: str, pan_type: str = "") -> str:
    """按网盘类型/域名判断厂商，用于选择检测方式。"""
    s = f"{pan_type or ''} {url or ''}".lower()
    if "quark" in s or "夸克" in s:
        return "quark"
    if "drive.uc.cn" in s or "pc-api.uc.cn" in s or "uc网盘" in s or "uc盘" in s:
        return "uc"
    if "aliyundrive" in s or "alipan" in s or "阿里" in s:
        return "aliyun"
    if "pan.baidu" in s or "百度" in s:
        return "baidu"
    if "189.cn" in s or "天翼" in s:
        return "tianyi"
    if "123pan" in s or "123865" in s or "123912" in s or "123684" in s:
        return "123"
    if "115" in s:
        return "115"
    if "xunlei" in s or "迅雷" in s:
        return "xunlei"
    return ""


_PAN_SHARE_ID_RE = re.compile(r"/s/([A-Za-z0-9_-]{4,})")


def _share_id(url: str) -> str:
    m = _PAN_SHARE_ID_RE.search(url or "")
    return m.group(1) if m else ""


def _check_drive_share(url: str, api: str, referer: str, timeout: int) -> str:
    """夸克 / UC 分享 token 接口：code=0 → 正常；失效码/失效文案 → dead。"""
    sid = _share_id(url)
    if not sid:
        return "unknown"
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/json",
        "Referer": referer,
    }
    try:
        r = requests.post(api, json={"pwd_id": sid, "passcode": ""},
                          headers=headers, timeout=max(3, int(timeout)))
        data = r.json()
    except Exception:  # noqa: BLE001
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    code = data.get("code")
    msg = str(data.get("message") or "")
    if code == 0:
        return "ok"
    if any(k in msg for k in ("失效", "不存在", "取消", "过期", "删除")):
        return "dead"
    if code in _DRIVE_DEAD_CODES:
        return "dead"
    if "提取码" in msg or "密码" in msg:
        return "ok"       # 链接存在，只是需要提取码
    return "unknown"


def _check_aliyun(url: str, timeout: int) -> str:
    """阿里云盘匿名分享信息接口：NotFound.ShareLink → dead。"""
    sid = _share_id(url)
    if not sid:
        return "unknown"
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/json",
        "Origin": "https://www.aliyundrive.com",
        "Referer": "https://www.aliyundrive.com/",
    }
    try:
        r = requests.post(_ALIYUN_API, json={"share_id": sid},
                          headers=headers, timeout=max(3, int(timeout)))
        data = r.json()
    except Exception:  # noqa: BLE001
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    if data.get("share_name") or data.get("share_id") or not data.get("code"):
        return "ok"
    code = str(data.get("code") or "")
    msg = str(data.get("message") or "")
    if "NotFound" in code or "not found" in code.lower() or "不存在" in msg:
        return "dead"
    return "unknown"


def _check_share_page(url: str, pan_type: str, timeout: int) -> str:
    """通用兜底：请求分享页，按 HTTP 状态码 + 服务端渲染文案判断。

    适用范围：百度 / 天翼 / 123 / 115 / 迅雷，以及接口无法判断时的其他网盘。
    115 等纯前端渲染页面通常只能得到 unknown（不会误报失效）。
    """
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        # 百度等站点对 gzip 处理不规范，禁用压缩避免解码失败
        "Accept-Encoding": "identity",
    }
    ref = _referer_for(pan_type)
    if ref:
        headers["Referer"] = ref

    try:
        r = requests.get(url, headers=headers, timeout=max(3, int(timeout)),
                         allow_redirects=True)
    except Exception:  # noqa: BLE001
        return "unknown"

    status = r.status_code
    if status in (404, 410):
        return "dead"
    if status in (401, 403, 429) or status >= 500:
        return "unknown"

    try:
        text = r.text or ""
    except Exception:  # noqa: BLE001
        return "unknown"
    if not text:
        return "unknown"

    # 跳转到登录/风控页：无法判断，不要误报失效
    final_url = (getattr(r, "url", "") or "").lower()
    if any(k in final_url for k in ("passport", "/login", "wappass", "verify")):
        return "unknown"

    # 只检查服务端渲染的前 60KB：避免 SPA 的 JS bundle 里固定存在的
    # "分享已过期" 等文案造成误判（大部分误报来自整页文本扫描）。
    head = text[:60000]
    m = re.search(r"<title[^>]*>(.*?)</title>", head, re.S | re.I)
    title = (m.group(1) if m else "")

    # 风控/登录/提取码页：优先判为无法判断
    if any(k in head for k in _INCONCLUSIVE_MARKERS):
        return "unknown"

    if any(k in title for k in _EXPIRED_MARKERS) or any(k in head for k in _EXPIRED_MARKERS):
        return "dead"

    return "ok"


def check_pan_link(url: str, pan_type: str = "", timeout: int = 6) -> str:
    """检测网盘链接状态（优先官方分享接口，其次分享页兜底）。

    返回：
        "dead"    确认失效（分享已过期/取消/不存在）
        "ok"      正常（或未发现失效标记）
        "unknown" 无法判断（非 http 链接、网络异常、风控/登录页）
    """
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return "unknown"
    if requests is None:
        return "unknown"

    cached = _cache_get(u)
    if cached:
        return cached

    prov = _provider(u, pan_type)
    status = "unknown"
    if prov == "quark":
        status = _check_drive_share(u, _QUARK_API, "https://pan.quark.cn/", timeout)
    elif prov == "uc":
        status = _check_drive_share(u, _UC_API, "https://drive.uc.cn/", timeout)
    elif prov == "aliyun":
        status = _check_aliyun(u, timeout)

    # 接口判断不出（或不支持的网盘）时再抓分享页
    if status == "unknown":
        status = _check_share_page(u, pan_type, timeout)

    # 115 分享页是纯前端渲染，页面 200 不代表资源存在；
    # 抓不到失效文案时只能按「无法判断」处理，避免误报为正常。
    if prov == "115" and status == "ok":
        status = "unknown"

    if status in ("ok", "dead"):
        _cache_put(u, status)
    return status


def check_many(items, max_workers: int = 6, timeout: int = 5,
               deadline: int = 25) -> dict:
    """并发检测多条网盘资源，返回 {url: status}。

    - max_workers 控制并发，避免把网盘接口打出风控；
    - deadline 是整批的总时限（秒），超时未完成的按 unknown 处理；
    - 结果走 check_pan_link 的共享缓存，10 分钟内重复检测不再发请求。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pairs = []
    for p in items or []:
        u = (p.get("url") or "").strip() if isinstance(p, dict) else ""
        if u.startswith(("http://", "https://")):
            pairs.append((u, (p.get("type") or "") if isinstance(p, dict) else ""))
    result: dict = {}
    if not pairs:
        return result

    def _one(pair):
        u, t = pair
        try:
            return u, check_pan_link(u, t, timeout)
        except Exception:  # noqa: BLE001
            return u, "unknown"

    workers = max(1, min(int(max_workers or 6), len(pairs)))
    ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pan-check")
    futures = {ex.submit(_one, pair): pair[0] for pair in pairs}
    try:
        for fut in as_completed(futures, timeout=max(5, int(deadline))):
            u = futures[fut]
            try:
                _url, _status = fut.result()
                result[u] = _status
            except Exception:  # noqa: BLE001
                result[u] = "unknown"
    except Exception:  # noqa: BLE001  (TimeoutError: 剩余按未知处理)
        pass
    finally:
        for fut in futures:
            if not fut.done():
                fut.cancel()
        ex.shutdown(wait=False)
    return result


# ==================== 失效反馈持久化 ====================

class PanReportStore:
    """记录实际点开即失效的网盘链接，供下次列表评分使用。

    文件结构：
        {"updated": 1710000000, "items": {"<url>": {"n": 1, "ts": 1710000000}}}
    """

    def __init__(self, path: str):
        self.path = path
        self._data = None
        self._dirty = False

    def _load(self):
        if self._data is not None:
            return
        self._data = {"updated": 0, "items": {}}
        try:
            if self.path and os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("items"), dict):
                    self._data = {"updated": data.get("updated", 0),
                                  "items": data["items"]}
        except Exception:  # noqa: BLE001
            pass

    @property
    def items(self) -> dict:
        self._load()
        return self._data["items"]

    def count(self, url: str) -> int:
        rep = self.items.get(_normalize_url(url))
        if isinstance(rep, dict):
            return int(rep.get("n") or 0)
        return 0

    def add(self, url: str) -> int:
        added = self.add_many([url])
        return added.get(url, 0)

    def add_many(self, urls) -> dict:
        """批量记录失效链接，只写一次磁盘。返回 {url: 累计次数}。"""
        self._load()
        items = self._data["items"]
        now = time.time()
        out = {}
        touched = False
        for url in urls or []:
            key = _normalize_url(url)
            if not key:
                continue
            rep = items.get(key)
            if isinstance(rep, dict):
                rep["n"] = int(rep.get("n") or 0) + 1
                rep["ts"] = now
            else:
                items[key] = {"n": 1, "ts": now}
            out[url] = int(items[key]["n"])
            touched = True
        if touched:
            self._prune()
            self._save()
        return out

    def _prune(self, keep: int = 2000, days: int = 90):
        items = self._data["items"]
        if len(items) <= keep:
            return
        cutoff = time.time() - days * 86400
        for k, v in list(items.items()):
            ts = v.get("ts", 0) if isinstance(v, dict) else 0
            if ts and ts < cutoff:
                items.pop(k, None)
        if len(items) > keep:
            for k, _ in sorted(items.items(), key=lambda kv: kv[1].get("ts", 0) if isinstance(kv[1], dict) else 0)[:len(items) - keep]:
                items.pop(k, None)

    def _save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._data["updated"] = int(time.time())
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._dirty = False
        except Exception:  # noqa: BLE001
            pass

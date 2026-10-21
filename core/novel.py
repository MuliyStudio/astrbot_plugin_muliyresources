# -*- coding: utf-8 -*-
"""so-novel Web API 客户端：小说多源聚合搜索 + 下载。

so-novel 以 Web 模式（-Dmode=web）启动时，基于内嵌 Jetty 提供 REST 接口
（根路径 /，默认端口 7765，官方 servlet 不做 token 校验）：

  GET /search/aggregated?kw=关键词&searchLimit=N   -> SearchResult[]（书名/作者/来源/简介）
  GET /book-fetch?url=书页URL&format=txt           -> 触发服务端抓取（同步，抓取整本）
  GET /book-download?filename=书名(作者).txt        -> 文件流（即下载链接）
  GET /local-books                                  -> 已下载文件列表（用于回查真实文件名）
  GET /sources (/check)                             -> 书源列表 / 可用性

本模块被 AstrBot 插件以 asyncio.to_thread 调用（同步 requests），统一把
网络超时、连接失败、源失效、JSON 解析错误封装为 NovelApiError。
"""
import re
import time
import urllib.parse

import requests

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# so-novel 支持的下载格式白名单
NOVEL_FORMATS = ("txt", "epub", "html", "pdf")


class NovelApiError(Exception):
    """so-novel 接口调用异常（网络/解析/业务错误统一封装）。

    stage 用于区分出错阶段：search / fetch / download / source，
    便于在插件层给出更有针对性的提示。
    """

    def __init__(self, message: str, *, stage: str = "api"):
        super().__init__(message)
        self.message = message
        self.stage = stage


# ————————————————————————————————————————————————
# 底层请求
# ————————————————————————————————————————————————

def _build_headers(token: str) -> dict:
    h = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json, text/plain;q=0.8",
    }
    if token:
        # so-novel-web 等封装层可能要求 Bearer 鉴权；官方 servlet 忽略此头
        h["Authorization"] = f"Bearer {token}"
    return h


def _request_json(url: str, token: str, timeout: int, *, stage: str = "api"):
    """带超时/异常统一处理的 GET JSON 请求。失败时抛 NovelApiError。"""
    try:
        resp = requests.get(url, headers=_build_headers(token), timeout=timeout)
    except requests.exceptions.Timeout:
        raise NovelApiError(
            f"请求超时（>{timeout}s），so-novel 服务可能繁忙或不可达", stage=stage)
    except requests.exceptions.ConnectionError:
        raise NovelApiError(
            "无法连接 so-novel 服务，请确认其已以 Web 模式启动且地址正确", stage=stage)
    except requests.exceptions.RequestException as e:
        raise NovelApiError(f"网络请求失败：{e}", stage=stage)

    if resp.status_code != 200:
        raise NovelApiError(f"服务返回 HTTP {resp.status_code}", stage=stage)

    body = resp.text.strip()
    if not body:
        # 部分接口成功时返回空 body（如官方 /book-fetch）
        return None
    try:
        return resp.json()
    except ValueError:
        # 错误时某些封装以纯文本返回（如 400 的提示语）
        if len(body) < 300:
            raise NovelApiError(body, stage=stage)
        raise NovelApiError("返回内容不是合法 JSON", stage=stage)


def _normalize_items(raw) -> list:
    """兼容官方（裸 JSON 数组）与 so-novel-web 封装（{code,message,data}）。"""
    items = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        if "data" in raw:
            items = raw.get("data") or []
        elif raw.get("code") not in (None, 200):
            raise NovelApiError(raw.get("message", "请求失败"), stage="search")
        else:
            # 其它带 data 的包法兜底
            items = raw.get("data") or []
    return [it for it in items if isinstance(it, dict)]


# ————————————————————————————————————————————————
# 对外接口
# ————————————————————————————————————————————————

def search_novels(keyword: str, base_url: str, token: str = "",
                  search_limit: int = 20, timeout: int = 30) -> list:
    """聚合搜索。返回归一化列表：

    [{source_id, source_name, url, book_name, author,
      latest_chapter, last_update_time, intro}, ...]
    """
    base = (base_url or "http://127.0.0.1:7765").rstrip("/")
    q = requests.utils.quote(keyword)
    url = f"{base}/search/aggregated?kw={q}"
    if search_limit and search_limit > 0:
        url += f"&searchLimit={int(search_limit)}"

    data = _request_json(url, token, timeout, stage="search")
    items = _normalize_items(data)

    results = []
    for it in items:
        results.append({
            "source_id": it.get("sourceId"),
            "source_name": (it.get("sourceName") or it.get("source") or "").strip(),
            "url": (it.get("url") or "").strip(),
            "book_name": (it.get("bookName") or it.get("bookname")
                          or it.get("book_name") or "").strip(),
            "author": (it.get("author") or "").strip(),
            "latest_chapter": (it.get("latestChapter") or it.get("latestChapterTitle")
                               or "").strip(),
            "last_update_time": (it.get("lastUpdateTime") or it.get("lastUpdateTime")
                                 or "").strip(),
            "intro": (it.get("intro") or it.get("description") or "").strip(),
        })
    return results


def _derive_filename(book_name: str, author: str, fmt: str) -> str:
    """按 so-novel 命名规则推测输出文件名。

    so-novel 的最终产物：
      txt / epub / pdf → 下载目录下「书名(作者).格式」（无空格）
      html             → 章节目录被打包成「书名 (作者) HTML.zip」（有空格）
    """
    fmt = (fmt or "txt").lower()
    if fmt == "html":
        raw = f"{book_name or '小说'} ({author}) HTML.zip"
        return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", raw).strip()
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", f"{book_name}({author})").strip()
    if not safe:
        safe = "小说"
    return f"{safe}.{fmt}"


def _expected_exts(fmt: str) -> tuple:
    """请求格式 → 服务端实际产物的扩展名（html 在 so-novel 里是 zip 包）。"""
    fmt = (fmt or "txt").lower()
    return ("zip",) if fmt == "html" else (fmt,)


def _sniff_format(content: bytes) -> str:
    """按文件头判断真实格式。

    用途：/book-download 只给 application/octet-stream，且服务端可能匹配到
    同名旧文件（比如用户要 EPUB，却拿到上次的 TXT），必须自己校验，
    否则会把 txt 改名成 .epub 发出去（用户端直接打不开）。
    """
    head = content[:4096]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        # EPUB 本质是 zip，mimetype 条目必须排在最前且不压缩
        if b"application/epub+zip" in head or b"META-INF/container.xml" in content[:8192]:
            return "epub"
        return "zip"
    low = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html"):
        return "html"
    return "txt"


def _format_matches(fmt: str, real: str) -> bool:
    """请求的格式与嗅探出的真实格式是否相容。"""
    fmt = (fmt or "").lower()
    if not fmt:
        return True
    if fmt == "html":
        return real in ("html", "zip")   # HTML 版是 zip；旧版本可能单页 html
    if fmt == "epub":
        return real == "epub"
    if fmt == "pdf":
        return real == "pdf"
    if fmt == "txt":
        return real == "txt"
    return True


def _local_candidates(books: list, book_name: str, fmt: str,
                      start_ts: float) -> list:
    """从 /local-books 里挑出符合本次格式的候选文件名（新的在前）。

    关键：必须按格式过滤。旧逻辑只按书名匹配，于是「要 EPUB 却下发 TXT」
    「要 PDF 拿到别人的 HTML.zip」这类错配全部由这里来兜住。
    """
    exts = tuple("." + e for e in _expected_exts(fmt))
    rows = []
    for b in books or []:
        if not isinstance(b, dict):
            continue
        name = str(b.get("name") or "").strip()
        if not name or not name.lower().endswith(exts):
            continue
        if book_name and book_name not in name:
            continue
        try:
            ts = float(b.get("timestamp") or b.get("time") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts > 1e12:  # 毫秒时间戳归一化
            ts /= 1000.0
        rows.append((name, ts))
    # 本次请求新生成的文件优先，其次按时间倒序
    rows.sort(key=lambda x: (x[1] >= start_ts - 5, x[1]), reverse=True)
    return [n for n, _ in rows]


def _friendly_error(msg: str, fmt: str, status: int = 0) -> str:
    """把 so-novel 的原始报错翻译成用户能照着修的一句话。"""
    raw = (msg or "").strip()
    low = raw.lower()
    if fmt == "pdf" and ("字体" in raw or "font" in low or "sonovel.ttf" in low):
        return ("PDF 导出失败：so-novel 所在环境没有中文字体。"
                "把任意中文 TTF 字体改名为 SoNovel.ttf 放进 so-novel 的 fonts/ 目录"
                "（Docker 需挂载 -v /你的字体目录:/sonovel/fonts 后重启），"
                "或改用 EPUB / TXT。")
    if fmt == "html" and status == 404:
        return "HTML 包下载失败：so-novel 未生成 html 压缩包（版本过旧或章节目录为空）"
    return raw or f"服务端返回 HTTP {status}"



def fetch_novel(selected: dict, base_url: str, token: str = "",
                fmt: str = "txt", timeout: int = 600) -> dict:
    """触发整本下载，返回可下载文件名。

    先调用 /book-fetch（服务端同步抓取，可能耗时很长，用 timeout 控制）；
    再从 /local-books 回查真实文件名（最稳妥，规避命名差异）；
    回查失败则按命名规则推测。
    返回：{"success": True, "file_name": str, "format": str}
    """
    fmt = (fmt or "txt").lower()
    if fmt not in NOVEL_FORMATS:
        fmt = "txt"

    base = (base_url or "http://127.0.0.1:7765").rstrip("/")
    book_url = selected.get("url", "")
    if not book_url:
        raise NovelApiError("该书缺少可下载的书页地址（源可能未返回 url）", stage="fetch")

    book_name = selected.get("book_name", "") or ""
    author = selected.get("author", "") or ""
    start_ts = time.time()
    url = (f"{base}/book-fetch?url={requests.utils.quote(book_url)}&format={fmt}")
    try:
        resp = requests.get(url, headers=_build_headers(token), timeout=timeout)
    except requests.exceptions.Timeout:
        raise NovelApiError(
            f"下载超时（>{timeout}s）：本书体量较大或源站较慢，"
            f"可换其它书源或改用 TXT 格式重试", stage="fetch")
    except requests.exceptions.ConnectionError:
        raise NovelApiError("下载过程中连接中断，so-novel 服务不可达", stage="fetch")
    except requests.exceptions.RequestException as e:
        raise NovelApiError(f"下载请求失败：{e}", stage="fetch")

    # 兼容封装层返回 JSON（含 fileName / dlid / message）
    file_name = None
    if resp.status_code != 200:
        # 官方 servlet 出错时走 RespUtils.writeError
        msg = ""
        try:
            j = resp.json()
            msg = (j.get("message") or "") if isinstance(j, dict) else ""
        except ValueError:
            msg = resp.text.strip()
        raise NovelApiError(
            _friendly_error(msg, fmt, resp.status_code) or
            f"下载失败（HTTP {resp.status_code}），书源可能已失效", stage="fetch")

    body = resp.text.strip()
    if body:
        try:
            j = resp.json()
            if isinstance(j, dict):
                if j.get("code") not in (None, 200):
                    raise NovelApiError(
                        _friendly_error(j.get("message", ""), fmt) or "下载失败",
                        stage="fetch")
                d = j.get("data") or {}
                file_name = d.get("fileName") or d.get("filename")
        except ValueError:
            pass

    # 回查本地文件列表：必须按格式过滤（旧逻辑只按书名匹配，会把上次的
    # TXT / HTML.zip 当成 EPUB / PDF 发出去）。文件落盘有毫秒级延迟，轮询几次。
    cands = []
    for _ in range(8):
        try:
            books = list_local_books(base, token, timeout=30)
        except Exception:
            books = []
        cands = _local_candidates(books, book_name, fmt, start_ts)
        if cands:
            break
        time.sleep(0.4)

    names = list(cands)
    # 封装层直接报的文件名：仅当扩展名与请求格式相符才排在最前
    if file_name:
        n = str(file_name).strip()
        if n and n not in names:
            exts = tuple("." + e for e in _expected_exts(fmt))
            if n.lower().endswith(exts):
                names.insert(0, n)
            else:
                names.append(n)
    if not names:
        names = [_derive_filename(book_name, author, fmt)]

    return {"success": True, "file_name": names[0],
            "candidates": names[1:], "format": fmt, "start_ts": start_ts}


def list_local_books(base_url: str, token: str = "", timeout: int = 30) -> list:
    """已下载文件列表：[{name, size, timestamp}, ...]"""
    base = (base_url or "http://127.0.0.1:7765").rstrip("/")
    data = _request_json(f"{base}/local-books", token, timeout, stage="download")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data.get("data") or []
    return []


def get_download_url(base_url: str, file_name: str, token: str = "") -> str:
    """构造书籍文件下载直链。"""
    base = (base_url or "http://127.0.0.1:7765").rstrip("/")
    url = f"{base}/book-download?filename={requests.utils.quote(file_name)}"
    if token:
        url += f"&token={requests.utils.quote(token)}"
    return url


# 常见格式对应的下载 MIME 类型（用于把文件流作为附件发送）
_FORMAT_MIME = {
    "txt": "text/plain; charset=utf-8",
    "epub": "application/epub+zip",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "zip": "application/zip",
}


def download_novel_file(base_url: str, file_name: str, token: str = "",
                        timeout: int = 600, fmt: str = "") -> dict:
    """直接以文件流下载已抓取的小说（/book-download 返回文件本身，非 WebUI 预览页）。

    fmt 传入本次请求的格式时，会按文件头校验真实格式：so-novel 的
    /book-download 只回 application/octet-stream，且同名旧文件很容易被误取
    （要 EPUB 拿到 TXT、要 PDF 拿到上次的 HTML.zip），校验不过就抛错，
    由 download_novel() 换下一个候选文件，绝不把错格式改名发出去。

    返回：{"success": True, "content": bytes, "file_name": str, "mime": str,
           "ext": str, "real_format": str}
    失败抛 NovelApiError（stage="download"）。
    """
    base = (base_url or "http://127.0.0.1:7765").rstrip("/")
    url = f"{base}/book-download?filename={requests.utils.quote(file_name)}"
    if token:
        url += f"&token={requests.utils.quote(token)}"
    try:
        resp = requests.get(url, headers=_build_headers(token), timeout=timeout, stream=True)
    except requests.exceptions.Timeout:
        raise NovelApiError(f"文件下载超时（>{timeout}s）", stage="download")
    except requests.exceptions.ConnectionError:
        raise NovelApiError("下载中断，so-novel 服务不可达", stage="download")
    except requests.exceptions.RequestException as e:
        raise NovelApiError(f"文件下载请求失败：{e}", stage="download")

    if resp.status_code != 200:
        msg = ""
        try:
            j = resp.json()
            msg = (j.get("message") or "") if isinstance(j, dict) else ""
        except ValueError:
            msg = resp.text.strip()
        raise NovelApiError(
            _friendly_error(msg, fmt, resp.status_code) or
            f"文件下载失败（HTTP {resp.status_code}）", stage="download")

    content = resp.content
    if not content:
        raise NovelApiError("下载到的文件内容为空，书源可能已失效", stage="download")

    real = _sniff_format(content)
    if fmt and not _format_matches(fmt, real):
        raise NovelApiError(
            f"服务端返回的是 {real.upper()} 内容，不是请求的 {fmt.upper()}"
            f"（多半匹配到了同名旧文件）", stage="download")

    # 取文件名：优先使用「已能定位到服务端文件的干净文件名」file_name
    # （来自 fetch_novel / local-books 回查，不含 URL 编码、无「原名：」前缀）；
    # 服务端 Content-Disposition 常回传 **URL 编码** 文件名（如
    # %E5%BA%86%E4%B9%B4%E5%B9%B4.txt），直接当文件名发过去会变成一串百分号乱码，
    # 故仅作兜底，且必须先 urllib.parse.unquote 解码。
    disp = resp.headers.get("Content-Disposition", "")
    cd_name = ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", disp, re.IGNORECASE)
    if m:
        cd_name = urllib.parse.unquote(m.group(1).strip())
    fname = (file_name if file_name else cd_name).strip() or f"小说.{real}"
    fname = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", fname).strip() or f"小说.{real}"

    # 扩展名以「真实内容」为准：html 在 so-novel 里是 zip 包，
    # 旧逻辑会把书名.zip 改成 书名.zip.txt，发出去直接打不开。
    ext = real
    root = fname.rsplit(".", 1)[0] if "." in fname else fname
    if not fname.lower().endswith("." + ext):
        fname = f"{root}.{ext}"
    if len(fname) > 120:  # 部分客户端对超长文件名不友好
        keep = max(1, 120 - len(ext) - 1)
        fname = f"{fname[:keep]}.{ext}"

    mime = _FORMAT_MIME.get(ext, "application/octet-stream")
    return {"success": True, "content": content, "file_name": fname,
            "mime": mime, "ext": ext, "real_format": real}


def download_novel(selected: dict, base_url: str, token: str = "",
                   fmt: str = "txt", timeout: int = 600) -> dict:
    """抓取 + 下载 + 格式校验一体（推荐入口）。

    fetch_novel 返回「按格式过滤、新的在前」的候选文件名，这里逐个尝试：
    候选是旧文件或错格式时直接跳过，直到拿到真正匹配的文件。
    """
    fmt = (fmt or "txt").lower()
    res = fetch_novel(selected, base_url, token, fmt, timeout)
    names = []
    for n in [res.get("file_name")] + list(res.get("candidates") or []):
        n = str(n or "").strip()
        if n and n not in names:
            names.append(n)
    if not names:
        names = [_derive_filename(selected.get("book_name", ""),
                                  selected.get("author", ""), fmt)]

    errors = []
    for name in names[:6]:
        try:
            return download_novel_file(base_url, name, token, timeout, fmt=fmt)
        except NovelApiError as e:
            errors.append(f"{name}：{e.message}")
    if len(errors) == 1:
        raise NovelApiError(errors[0], stage="download")
    raise NovelApiError(
        "所有候选文件都不可用：" + "；".join(errors[:3]), stage="download")


def check_sources(base_url: str, token: str = "", timeout: int = 30) -> list:
    """书源可用性检查：[{sourceName, available, ...}, ...]"""
    base = (base_url or "http://127.0.0.1:7765").rstrip("/")
    try:
        data = _request_json(f"{base}/sources/check", token, timeout, stage="source")
    except NovelApiError:
        # /sources/check 不可用时回退到 /sources
        data = _request_json(f"{base}/sources", token, timeout, stage="source")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data.get("data") or []
    return []

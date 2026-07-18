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
    """按 so-novel 命名规则推测文件名：{书名}({作者}).{格式}。"""
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", f"{book_name}({author})").strip()
    if not safe:
        safe = "小说"
    return f"{safe}.{fmt}"


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
        raise NovelApiError(msg or f"下载失败（HTTP {resp.status_code}），书源可能已失效",
                             stage="fetch")

    body = resp.text.strip()
    if body:
        try:
            j = resp.json()
            if isinstance(j, dict):
                if j.get("code") not in (None, 200):
                    raise NovelApiError(j.get("message", "下载失败"), stage="fetch")
                d = j.get("data") or {}
                file_name = d.get("fileName") or d.get("filename")
        except ValueError:
            pass

    # 回查本地文件列表，按书名匹配（最稳妥）
    if not file_name:
        try:
            books = list_local_books(base, token, timeout=30)
            bn = selected.get("book_name", "")
            for b in books:
                name = b.get("name", "") if isinstance(b, dict) else str(b)
                if bn and bn in name:
                    file_name = name
                    break
        except Exception:
            file_name = None

    # 兜底：按命名规则推测
    if not file_name:
        file_name = _derive_filename(selected.get("book_name", ""),
                                     selected.get("author", ""), fmt)

    return {"success": True, "file_name": file_name, "format": fmt}


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
}


def download_novel_file(base_url: str, file_name: str, token: str = "",
                        timeout: int = 600) -> dict:
    """直接以文件流下载已抓取的小说（/book-download 返回文件本身，非 WebUI 预览页）。

    与单纯返回直链不同：本函数由插件侧（能访问 so-novel 服务網络）真正拉取
    文件字节，交由 AstrBot 以 File 消息组件直接发到会话，用户无需点击 localhost
    链接、也不依赖 so-novel 的 WebUI 预览。

    返回：{"success": True, "content": bytes, "file_name": str, "mime": str}
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
        raise NovelApiError(msg or f"文件下载失败（HTTP {resp.status_code}）",
                             stage="download")

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
    # 文件名原样保留（书名即使含「原名：xxx」也是书源正常表述，不做前缀清洗）；
    # 只优先用能定位服务端文件的干净 file_name，把已 URL 解码的 CD 名作兜底。
    fname = (file_name if file_name else cd_name).strip()
    # 兜底后缀（避免无扩展名导致客户端无法识别）
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if ext not in NOVEL_FORMATS:
        for k in NOVEL_FORMATS:
            if fname.lower().endswith(f".{k}"):
                ext = k
                break
        if ext not in NOVEL_FORMATS:
            suf = file_name.rsplit(".", 1)[-1].lower()
            ext = suf if suf in NOVEL_FORMATS else "txt"
            if not fname.endswith(f".{ext}"):
                fname = f"{fname}.{ext}"
    mime = _FORMAT_MIME.get(ext, "application/octet-stream")
    content = resp.content
    return {"success": True, "content": content, "file_name": fname, "mime": mime}


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

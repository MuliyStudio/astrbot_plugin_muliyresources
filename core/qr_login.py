# -*- coding: utf-8 -*-
"""xdgame.com 登录模块 — 用于 Cookie 刷新

v14.0 — 纯 HTTP 实现（httpx），无 Playwright 无浏览器

  流程：
  1. await login_with_password_async(username, password)
     → GET /user/index.php  让服务器 set server_session cookie
     → GET /include/vdimgck.php  拉验证码 PNG
     → 返回 {"ok": True, "needs_captcha": True, "captcha_image": bytes}
  2. await submit_captcha_async(captcha)
     → POST /user/index_do.php  form=diyform  (fmdo=login&dopost=login&userid=X&pwd=X&vdcode=X)
     → 服务器返回 "success" 或 "验证码错误！" 等错误字符串
     → 若成功，GET /user/index.php 解析昵称、抓 DedeUserID/PHPSESSID cookie

  为什么不需要 Playwright：
  - xdgame 是 dede（织梦）CMS，登录就是简单的 POST form
  - JS 里的 $.ajax({...}) 在浏览器里就是 XMLHttpRequest，curl 一样能复现
  - 服务器用 server_session_ab24c166 cookie 关联验证码会话，httpx cookie jar 自动处理
"""
import os, time, datetime, json, asyncio, re
from .constants import logger

# === DEBUG INSTRUMENTATION (session c4a65f) ===
def _qr_dbg(hid, msg, data):
    try:
        import pathlib
        line = json.dumps({"sessionId":"c4a65f","location":f"qr_login.py:{_qr_dbg.__code__.co_firstlineno}","message":msg,"data":data,"hypothesisId":hid,"runId":"initial","timestamp":int(time.time()*1000)}, ensure_ascii=False) + "\n"
        for target in ("/AstrBot/data/plugins/astrbot_plugin_muliyresources/debug-c4a65f.log",
                       "/www/dk_project/dk_app/astrbot/astrbot_RLHF/data/plugins/astrbot_plugin_muliyresources/debug-c4a65f.log",
                       r"C:\Users\Administrator\debug-c4a65f.log"):
            try:
                pathlib.Path(target).parent.mkdir(parents=True, exist_ok=True)
                with open(target, "a", encoding="utf-8") as f:
                    f.write(line)
                break
            except Exception:
                continue
    except Exception:
        pass
# === END DEBUG INSTRUMENTATION ===

XDGAME_BASE = "https://www.xdgame.com"
XDGAME_LOGIN_PAGE = XDGAME_BASE + "/user/index.php"
XDGAME_LOGIN_POST = XDGAME_BASE + "/user/index_do.php"
XDGAME_CAPTCHA_IMG = XDGAME_BASE + "/include/vdimgck.php"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

# ——— 状态回调 ———
_STATUS_CALLBACK = None


def set_status_callback(cb):
    global _STATUS_CALLBACK
    _STATUS_CALLBACK = cb


def _notify(state: str, detail: str = ""):
    if _STATUS_CALLBACK:
        try:
            _STATUS_CALLBACK(state, detail)
        except Exception:
            pass


# ——— 共享 httpx 客户端（每个登录流程创建独立的 AsyncClient 携带独立 CookieJar） ———
def _new_async_client():
    """创建一个新的异步 HTTP 会话（每个登录流程独立，避免 cookie 污染）。

    优先 httpx，回退 aiohttp（AstrBot 默认带）。"""
    try:
        import httpx
        return ("httpx", httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        ))
    except ImportError:
        pass
    try:
        import aiohttp
        return ("aiohttp", aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20, connect=10),
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        ))
    except ImportError:
        pass
    raise RuntimeError("缺少 httpx 或 aiohttp 依赖，请在 AstrBot 容器中 pip install httpx")


# ====================================================================
#  调试日志
# ====================================================================

_DEBUG_FILE = None


def _debug_log_init():
    global _DEBUG_FILE
    if _DEBUG_FILE is not None:
        return
    try:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "qr_debug_logs")
        os.makedirs(d, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _DEBUG_FILE = os.path.join(d, f"qr_login_{ts}.log")
        _wr(f"[INIT] v14.0 纯HTTP 调试日志: {_DEBUG_FILE}")
    except Exception as e:
        _DEBUG_FILE = ""
        logger.warning(f"[QR登录] 无法创建调试日志: {e}")


def _wr(msg: str):
    global _DEBUG_FILE
    if _DEBUG_FILE is None:
        _debug_log_init()
    if _DEBUG_FILE:
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:12]
            with open(_DEBUG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
                f.flush()
        except Exception:
            pass


# ====================================================================
#  共享上下文：每个登录流程用 _SessionCtx 携带异步 HTTP 客户端 + 账密
# ====================================================================

class _SessionCtx:
    """承载一个登录流程的所有状态（httpx 或 aiohttp 二选一）"""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.backend, self.client = _new_async_client()
        self.captcha_session_cookie = None  # server_session_ab24c166 字符串值（用于 debug）

    async def close(self):
        try:
            if self.backend == "aiohttp":
                await self.client.close()
            else:
                await self.client.aclose()
        except Exception:
            pass

    def _cookies_dict(self) -> dict:
        """导出 cookies 为 {name: value}"""
        d = {}
        try:
            if self.backend == "httpx":
                for c in self.client.cookies.jar:
                    d[c.name] = c.value
            else:
                # aiohttp CookieJar — 直接迭代 Morsel
                for c in self.client.cookie_jar:
                    d[c.key] = c.value
        except Exception:
            pass
        return d

    async def get(self, url: str) -> tuple:
        """GET 请求，返回 (status_code, content_bytes, headers_dict)"""
        if self.backend == "httpx":
            r = await self.client.get(url)
            return r.status_code, r.content, dict(r.headers)
        else:
            async with self.client.get(url) as r:
                content = await r.read()
                return r.status, content, dict(r.headers)

    async def post(self, url: str, data: dict) -> tuple:
        """POST 表单，返回 (status_code, content_bytes, headers_dict)"""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": XDGAME_LOGIN_PAGE,
            "X-Requested-With": "XMLHttpRequest",
        }
        if self.backend == "httpx":
            r = await self.client.post(url, data=data, headers=headers)
            return r.status_code, r.content, dict(r.headers)
        else:
            async with self.client.post(url, data=data, headers=headers) as r:
                content = await r.read()
                return r.status, content, dict(r.headers)

    def _log_cookies(self):
        """记录所有 cookie 到调试日志"""
        try:
            if self.backend == "httpx":
                for c in self.client.cookies.jar:
                    _wr(f"[Cookie] 当前: {c.name}={c.value[:40]}")
            else:
                for c in self.client.cookie_jar:
                    _wr(f"[Cookie] 当前: {c.key}={c.value[:40]}")
        except Exception:
            pass


# ——— 全局：当前活跃的登录流程上下文 ———
_CURRENT_CTX: _SessionCtx | None = None
_CURRENT_LOCK = asyncio.Lock()


# ====================================================================
#  步骤1：拉登录页 + 验证码图
# ====================================================================

async def login_with_password_async(username: str, password: str) -> dict:
    """
    初始化登录流程：
    - GET /user/index.php  → 服务器种 server_session_ab24c166 cookie
    - GET /include/vdimgck.php  → 拉验证码 PNG

    返回：
      {"ok": True, "needs_captcha": True, "captcha_image": bytes}
      {"ok": False, "error": str}
    """
    global _CURRENT_CTX

    async with _CURRENT_LOCK:
        # 清理上一次的 ctx
        if _CURRENT_CTX is not None:
            try:
                await _CURRENT_CTX.close()
            except Exception:
                pass
            _CURRENT_CTX = None

        _debug_log_init()
        _wr(f"=== login_with_password_async() v14.0 开始 ===")

        try:
            ctx = _SessionCtx(username, password)
            _CURRENT_CTX = ctx
            _wr(f"[启动] {ctx.backend} AsyncClient 已创建")

            # === 1. GET 登录页 → 让服务器 set server_session cookie ===
            try:
                status, content, headers = await ctx.get(XDGAME_LOGIN_PAGE)
                _wr(f"[GET {XDGAME_LOGIN_PAGE}] status={status} bytes={len(content)}")
            except Exception as e:
                _wr(f"[GET 登录页] 异常: {e}")
                await ctx.close()
                return {"ok": False, "error": f"无法访问登录页: {str(e)[:100]}"}

            if status != 200:
                await ctx.close()
                return {"ok": False, "error": f"登录页 HTTP {status}"}

            # 记录 captcha session cookie
            cookies = ctx._cookies_dict()
            for nm, vl in cookies.items():
                _wr(f"[Cookie] 收到: {nm}={vl[:30]}... ")
                if nm == "server_session_ab24c166":
                    ctx.captcha_session_cookie = vl

            if not ctx.captcha_session_cookie:
                _wr("[WARN] 未拿到 server_session_ab24c166 cookie — 验证码可能失效")

            # === 2. GET 验证码图 ===
            # 加时间戳避免缓存（与浏览器 JS 里 Math.random() 行为一致）
            import random as _rnd
            cap_url = f"{XDGAME_CAPTCHA_IMG}?tag={int(time.time() * 1000)}{_rnd.randint(100,999)}"
            try:
                status, content, headers = await ctx.get(cap_url)
                ct = headers.get("content-type", headers.get("Content-Type", "?"))[:40]
                _wr(f"[GET 验证码] status={status} bytes={len(content)} ct={ct}")
            except Exception as e:
                _wr(f"[GET 验证码] 异常: {e}")
                await ctx.close()
                return {"ok": False, "error": f"拉取验证码失败: {str(e)[:100]}"}

            if status != 200 or len(content) < 100:
                _wr(f"[GET 验证码] 返回异常 content_len={len(content)}")
                await ctx.close()
                return {"ok": False, "error": f"验证码图异常 (HTTP {status}, {len(content)}B, ct={ct})"}

            # dede vdimgck.php 可能是 JPEG 或 PNG，校验魔数
            png_magic = content[:4] == b"\x89PNG"
            jpg_magic = content[:3] == b"\xff\xd8\xff"
            if not png_magic and not jpg_magic:
                _wr(f"[GET 验证码] 非图片格式，前 16 字节: {content[:16]!r}")
                await ctx.close()
                return {"ok": False, "error": f"验证码图格式异常 (ct={ct}, len={len(content)})"}

            _wr(f"[验证码] 拉取成功 {len(content)} bytes")
            _notify("captcha", "")
            return {
                "ok": True,
                "needs_captcha": True,
                "captcha_image": content,
            }

        except Exception as e:
            _wr(f"[异常] login_with_password_async: {e}")
            logger.error(f"[QR登录] 拉验证码异常: {e}", exc_info=True)
            try:
                if _CURRENT_CTX:
                    await _CURRENT_CTX.close()
            except Exception:
                pass
            _CURRENT_CTX = None
            return {"ok": False, "error": str(e)[:200]}


# ====================================================================
#  步骤2：提交验证码，登录
# ====================================================================

async def submit_captcha_async(captcha: str) -> dict:
    """
    POST 登录表单，获取 Cookie。

    参数：captcha — 用户在群里输入的验证码（4字符左右）

    返回：
      {"ok": True, "cookies": {name: value}, "xd_nick": str}
      {"ok": False, "error": str}
    """
    global _CURRENT_CTX

    async with _CURRENT_LOCK:
        ctx = _CURRENT_CTX
        if ctx is None:
            _wr("[异常] submit_captcha_async: _CURRENT_CTX 为空")
            return {"ok": False, "error": "登录流程已失效，请重新发起 game_cookie_refresh"}

        captcha = (captcha or "").strip()
        if not captcha:
            _wr("[异常] submit_captcha_async: 验证码为空")
            return {"ok": False, "error": "验证码为空"}

        _wr(f"[提交验证码] captcha={captcha}")
        _notify("submitting", "正在提交验证码…")

        try:
            # === POST /user/index_do.php 表单 ===
            form_data = {
                "fmdo": "login",
                "dopost": "login",
                "gourl": "",
                "userid": ctx.username,
                "pwd": ctx.password,
                "vdcode": captcha,
            }
            try:
                status, content, headers = await ctx.post(XDGAME_LOGIN_POST, data=form_data)
            except Exception as e:
                _wr(f"[POST 登录] 异常: {e}")
                return {"ok": False, "error": f"POST 登录异常: {str(e)[:100]}"}

            _wr(f"[POST 登录] status={status} bytes={len(content)}")
            # 服务器返回纯文本（如 "success" 或 "验证码错误！"）
            try:
                resp_text = content.decode("utf-8", errors="ignore").strip()
            except Exception:
                resp_text = ""
            _wr(f"[POST 登录] resp: {resp_text!r}")

            # 记录 POST 后服务器可能 Set-Cookie 的关键 cookie
            ctx._log_cookies()

            if resp_text == "success":
                # 登录成功！
                cookies = ctx._cookies_dict()
                _qr_dbg("HTTP", "登录成功 cookies", {"n": len(cookies), "names": list(cookies.keys())})
                _wr(f"[完成] 登录成功，共 {len(cookies)} 个 cookie: {list(cookies.keys())}")

                # 拉一下登录后的页面，解析昵称（dede 用户中心可能有用户信息）
                xd_nick = await _fetch_nickname(ctx)
                _wr(f"[昵称] 解析: {xd_nick!r}")

                # 清理 ctx
                try:
                    await ctx.close()
                except Exception:
                    pass
                _CURRENT_CTX = None

                # 校验 dede 登录标志
                has_dede = "DedeUserID" in cookies or "PHPSESSID" in cookies
                if not has_dede:
                    _wr(f"[WARN] 服务器未返回 DedeUserID/PHPSESSID — 但 resp_text='success'，按服务器回应信任")

                return {
                    "ok": True,
                    "cookies": cookies,
                    "xd_nick": xd_nick,
                    "nickname": xd_nick,
                }
            else:
                # 错误响应
                err = resp_text or "未知错误"
                # 兜底映射
                if "验证码" in err:
                    err = f"验证码错误：{err}"
                elif "密码" in err:
                    err = f"密码错误：{err}"
                elif "账号" in err or "用户" in err:
                    err = f"账号问题：{err}"
                _wr(f"[失败] {err}")

                # 不清理 ctx — 让用户可以重试（同一 server_session 可以多次试）
                # 但实际上 dede 验证码错误后会换一张图，所以下次还要拉新图
                # 这里选择清理 ctx，强制用户重跑 game_cookie_refresh
                try:
                    await ctx.close()
                except Exception:
                    pass
                _CURRENT_CTX = None
                return {"ok": False, "error": err[:200]}

        except Exception as e:
            _wr(f"[异常] submit_captcha_async: {e}")
            logger.error(f"[QR登录] 提交验证码异常: {e}", exc_info=True)
            try:
                if _CURRENT_CTX:
                    await _CURRENT_CTX.close()
            except Exception:
                pass
            _CURRENT_CTX = None
            return {"ok": False, "error": str(e)[:200]}


async def _fetch_nickname(ctx: _SessionCtx) -> str:
    """登录成功后从用户中心页面解析昵称"""
    _wr(f"[昵称] 尝试 GET {XDGAME_LOGIN_PAGE} 解析昵称")
    try:
        status, content, headers = await ctx.get(XDGAME_LOGIN_PAGE)
        if status != 200:
            return "未知"
        html = content.decode("utf-8", errors="ignore")
        # dede 常见昵称模式：<span class="...">昵称</span> 或 input value
        # xdgame 用户中心 — 简单匹配 HTML 中用户名/昵称
        patterns = [
            r'<span[^>]*class=["\'][^"\']*user[^"\']*["\'][^>]*>([^<]{2,30})</span>',
            r'<span[^>]*class=["\'][^"\']*nick[^"\']*["\'][^>]*>([^<]{2,30})</span>',
            r'<div[^>]*class=["\'][^"\']*user[^"\']*["\'][^>]*>([^<]{2,30})</div>',
            r'欢迎.{0,4}?(.+?)[\s<]',
            r'class=["\']username["\'][^>]*>([^<]{2,30})<',
            r'class=["\']uname["\'][^>]*>([^<]{2,30})<',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                nick = m.group(1).strip()
                # 过滤掉 HTML 残留
                nick = re.sub(r'<[^>]+>', '', nick)
                nick = nick.strip()
                if 2 <= len(nick) <= 30 and not nick.startswith("$"):
                    return nick
        # 兜底：返回 dede 用户 ID
        cookies = ctx._cookies_dict()
        if "DedeUserID" in cookies:
            return f"用户#{cookies['DedeUserID']}"
        return "未知"
    except Exception as e:
        _wr(f"[昵称] 解析异常: {e}")
        return "未知"


# ====================================================================
#  Cookie 工具（保持兼容）
# ====================================================================

def format_cookie_string(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def extract_xdgame_cookies(cookies: dict) -> dict:
    """只提取 xdgame 站点的关键 cookie"""
    xd_keys = {
        "night", "Hm_lvt_1905089d52b6f08f01b437535400116c",
        "HMACCOUNT", "PHPSESSID", "DedeUserID",
        "DedeUserID__ckMd5", "DedeLoginTime", "DedeLoginTime__ckMd5",
        "Hm_lpvt_1905089d52b6f08f01b437535400116c",
        "server_session_ab24c166",
    }
    result = {k: v for k, v in cookies.items() if k in xd_keys}
    if result:
        return result
    return {k: v for k, v in cookies.items()
            if k.startswith("Dede") or k in ("PHPSESSID", "night", "HMACCOUNT",
                                             "server_session", "Hm_lvt", "Hm_lpvt",
                                             "Hm_lvt_1905089", "Hm_lpvt_1905089")}


# ====================================================================
#  废弃函数（保留避免旧代码导入报错）
# ====================================================================

def get_qrcode() -> dict:
    """废弃：QQ扫码登录已移除，请使用 login_with_password_async"""
    return {"ok": False, "error": "QQ扫码登录已移除，请使用账号密码登录", "image": None}


def poll_login(timeout: int = 120, **kwargs) -> dict:
    """废弃：QQ扫码登录已移除，请使用 login_with_password_async"""
    return {"ok": False, "status": "deprecated", "error": "QQ扫码登录已移除"}
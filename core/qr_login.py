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
import os, time, datetime, json, asyncio, re, hashlib
from .constants import logger

# ——— Cap「人机验证」求解器（xdgame 2026-08 起登录页新增 cap-widget 行为验证） ———
#
# 原理（来自 /static/cap/cap.brandless_20260805.js，v20260805）：
#   1. POST {cap-api}/challenge → {challenge:{c,s,d}, token, expires}（format 1）
#      或 {format:2, challenges:[{protocol,payload},...], token}（format 2）
#   2. format 1：生成 c 组 (salt, target)：
#        salt   = d(token+i, s)     （FNV1a 播种的 xorshift PRNG 输出 s 位 hex）
#        target = d(token+i+'d', d) （同上，d 位 hex，为 SHA-256 前缀目标）
#      求解 = 对每组找 nonce，使 SHA256(salt+nonce) 前 len(target)/2 字节 == target
#   3. format 2：按 protocol 求解：
#        sha256-pow   → 同上，payload={salt,target}
#        rsw          → y = x^(2^t) mod N（大整数模平方链）
#        instrumentation → 浏览器沙箱内执行 blob，纯 HTTP 无法复现（留空尝试）
#   4. POST {cap-api}/redeem {token, solutions} → {success, token, expires}
#     redeem 返回的 token 即登录表单里的 cap_token 字段
#
# 全程纯 Python 实现，无需浏览器/Playwright，仅在「管理员手动刷新 Cookie」时执行
# 一次（约 3-5s 纯 CPU 计算），不影响日常搜索。

_MASK32 = 0xFFFFFFFF


def _cap_i32(v: int) -> int:
    """模拟 JS 32 位有符号整数（位运算后强制 int32）。"""
    v &= _MASK32
    return v - 0x100000000 if v >= 0x80000000 else v


def _cap_fnv1a(s: str) -> int:
    """FNV-1a 32bit（与 cap.js 一致，输入按 JS charCodeAt 处理，ASCII 等价 UTF-8 字节）。"""
    h = 2166136261  # 0x811C9DC5
    for b in s.encode("utf-8"):
        t = _cap_i32(h) ^ b
        t += _cap_i32(t << 1) + _cap_i32(t << 4) + _cap_i32(t << 7) + _cap_i32(t << 8) + _cap_i32(t << 24)
        h = t
    return _cap_i32(h) & _MASK32


def _cap_prng(seed: int) -> int:
    """cap.js 的 xorshift 步进：i ^= i<<13; i ^= i>>>17; i ^= i<<5; return i>>>0"""
    i = seed
    i = _cap_i32(i) ^ _cap_i32(_cap_i32(i) << 13)
    i = _cap_i32(i) ^ ((i & _MASK32) >> 17)
    i = _cap_i32(i) ^ _cap_i32(_cap_i32(i) << 5)
    return _cap_i32(i) & _MASK32


def cap_gen(prefix: str, target_len: int) -> str:
    """cap.js 的 d(prefix, target)：FNV1a 播种 PRNG，产出 target_len 位 hex 字符串。"""
    i = _cap_fnv1a(prefix)
    out = ""
    while len(out) < target_len:
        i = _cap_prng(i)
        out += f"{i:08x}"
    return out[:target_len]


def cap_solve_pow_single(salt: str, target_hex: str) -> int:
    """sha256-pow：找 nonce 使 SHA256(salt+nonce) 前 len(target)/2 字节 == target。"""
    target = target_hex + ("0" if len(target_hex) % 2 else "")
    want = bytes.fromhex(target)
    a = len(want)
    sb = salt.encode("utf-8")
    n = 0
    while True:
        if hashlib.sha256(sb + str(n).encode("utf-8")).digest()[:a] == want:
            return n
        n += 1


def _cap_solve_batch(pairs: list) -> list:
    """批量求解 format 1 的 (salt, target) 对，返回 nonce 列表。纯 CPU，供 to_thread。"""
    return [cap_solve_pow_single(salt, tgt) for salt, tgt in pairs]


def _cap_solve_format2_batch(challenges: list) -> list:
    """批量求解 format 2 的 challenges，返回 solutions 列表（含 rsw/instrumentation）。"""
    out = []
    for c2 in challenges:
        p = c2.get("payload") or {}
        proto = c2.get("protocol")
        if proto == "sha256-pow":
            out.append({"nonce": cap_solve_pow_single(p["salt"], p["target"])})
        elif proto == "rsw":
            y = pow(int(p["x"], 16), 1 << int(p["t"]), int(p["N"], 16))
            out.append({"y": format(y, "x")})
        elif proto == "instrumentation":
            out.append({"instr": {}})  # 纯 HTTP 无法执行沙箱，空提交尝试
        else:
            raise RuntimeError(f"未知 Cap 协议: {proto}")
    return out

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

    async def post_json(self, url: str, data: dict) -> tuple:
        """POST JSON（Cap 验证接口用），返回 (status_code, content_bytes, headers_dict)"""
        headers = {
            "Content-Type": "application/json",
            "Referer": XDGAME_LOGIN_PAGE,
        }
        if self.backend == "httpx":
            r = await self.client.post(url, json=data, headers=headers)
            return r.status_code, r.content, dict(r.headers)
        else:
            async with self.client.post(url, json=data, headers=headers) as r:
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
#  步骤1：拉登录页 + 验证码图（自动优先 Cap 人机验证）
# ====================================================================

async def _cap_solve_for_login(ctx: _SessionCtx, ep: str) -> str:
    """在 ctx 会话上求解 Cap 人机验证，返回 redeem token（即 cap_token）。

    ep 形如 '/cap-test-api/fbb1c42b54/'（相对路径，自动拼到 xdgame 域名）。
    求解（SHA-256 PoW）放到线程池执行，避免阻塞事件循环。
    """
    if not ep:
        raise RuntimeError("Cap endpoint 为空")
    base = ep if ep.startswith("http") else XDGAME_BASE + ep
    base = base.rstrip("/")

    # 1) 取挑战
    status, content, headers = await ctx.post_json(base + "/challenge", {})
    if status != 200:
        raise RuntimeError(f"Cap challenge HTTP {status}")
    j = json.loads(content.decode("utf-8", errors="ignore") or "{}")
    token = j.get("token", "")
    ch = j.get("challenge")
    challenges_v2 = j.get("challenges")
    if not token:
        raise RuntimeError(f"Cap challenge 无 token: {str(j)[:120]}")

    # 2) 求解（纯 CPU，在线程池执行）
    if isinstance(challenges_v2, list) and j.get("format") == 2:
        solutions = await asyncio.to_thread(_cap_solve_format2_batch, challenges_v2)
    elif isinstance(ch, dict) and "c" in ch:
        pairs = [(cap_gen(token + str(i), ch["s"]),
                  cap_gen(token + str(i) + "d", ch["d"]))
                 for i in range(1, int(ch["c"]) + 1)]
        solutions = await asyncio.to_thread(_cap_solve_batch, pairs)
    else:
        raise RuntimeError(f"未知 Cap challenge 格式: {str(j)[:200]}")

    # 3) 赎回
    status, content, headers = await ctx.post_json(
        base + "/redeem", {"token": token, "solutions": solutions})
    if status != 200:
        raise RuntimeError(f"Cap redeem HTTP {status}")
    rj = json.loads(content.decode("utf-8", errors="ignore") or "{}")
    if not rj.get("success") or not rj.get("token"):
        raise RuntimeError(f"Cap redeem 失败: {str(rj)[:160]}")
    return rj["token"]


async def _post_login_form(ctx: _SessionCtx, cap_token: str = "", vdcode: str = "") -> dict:
    """提交登录表单，返回统一结果 dict（成功时清理 ctx 并置空 _CURRENT_CTX）。"""
    global _CURRENT_CTX
    form_data = {
        "fmdo": "login", "dopost": "login", "gourl": "",
        "cap_token": cap_token,
        "userid": ctx.username, "pwd": ctx.password,
        "vdcode": vdcode,
    }
    status, content, headers = await ctx.post(XDGAME_LOGIN_POST, data=form_data)
    _wr(f"[POST 登录] status={status} bytes={len(content)}")
    resp_text = content.decode("utf-8", errors="ignore").strip()
    _wr(f"[POST 登录] resp: {resp_text!r}")
    ctx._log_cookies()

    if resp_text != "success":
        err = resp_text or "未知错误"
        if "验证码" in err:
            err = f"验证码错误：{err}"
        elif "密码" in err:
            err = f"密码错误：{err}"
        elif "账号" in err or "用户" in err:
            err = f"账号问题：{err}"
        return {"ok": False, "error": err[:200]}

    cookies = ctx._cookies_dict()
    _qr_dbg("HTTP", "登录成功 cookies", {"n": len(cookies), "names": list(cookies.keys())})
    xd_nick = await _fetch_nickname(ctx)
    _wr(f"[昵称] 解析: {xd_nick!r}")
    try:
        await ctx.close()
    except Exception:
        pass
    _CURRENT_CTX = None
    has_dede = "DedeUserID" in cookies or "PHPSESSID" in cookies
    if not has_dede:
        _wr(f"[WARN] 服务器未返回 DedeUserID/PHPSESSID — 但 resp_text='success'，按服务器回应信任")
    return {
        "ok": True,
        "cookies": cookies,
        "xd_nick": xd_nick,
        "nickname": xd_nick,
    }


async def _setup_image_captcha(ctx: _SessionCtx) -> dict:
    """回退流程：拉取图片验证码，返回 needs_captcha=True 交用户输入。"""
    import random as _rnd
    cap_url = f"{XDGAME_CAPTCHA_IMG}?tag={int(time.time() * 1000)}{_rnd.randint(100,999)}"
    try:
        status, content, headers = await ctx.get(cap_url)
    except Exception as e:
        _wr(f"[GET 验证码] 异常: {e}")
        await ctx.close()
        return {"ok": False, "error": f"拉取验证码失败: {str(e)[:100]}"}
    ct = headers.get("content-type", headers.get("Content-Type", "?"))[:40]
    _wr(f"[GET 验证码] status={status} bytes={len(content)} ct={ct}")
    if status != 200 or len(content) < 100:
        await ctx.close()
        return {"ok": False, "error": f"验证码图异常 (HTTP {status}, {len(content)}B, ct={ct})"}
    png_magic = content[:4] == b"\x89PNG"
    jpg_magic = content[:3] == b"\xff\xd8\xff"
    if not png_magic and not jpg_magic:
        _wr(f"[GET 验证码] 非图片格式，前 16 字节: {content[:16]!r}")
        await ctx.close()
        return {"ok": False, "error": f"验证码图格式异常 (ct={ct}, len={len(content)})"}
    _wr(f"[验证码] 拉取成功 {len(content)} bytes")
    _notify("captcha", "")
    return {"ok": True, "needs_captcha": True, "captcha_image": content}


async def login_with_password_async(username: str, password: str) -> dict:
    """
    初始化登录流程（v14.1 — 支持 Cap 人机验证自动求解）：
    - GET /user/index.php → 解析 Cap 验证 API 地址（data-cap-api-endpoint）
    - 优先自动求解 Cap（纯 Python 复现 cap.js 的 FNV1a+xorshift+SHA-256 PoW），
      成功后直接 POST 登录，返回 {"ok": True, "cookies": {...}, "xd_nick": ...}
    - Cap 求解/登录失败 → 回退图片验证码（vdimgck.php），返回
      {"ok": True, "needs_captcha": True, "captcha_image": bytes}

    返回：
      {"ok": True, "cookies": {...}, "xd_nick": str}
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
        _wr(f"=== login_with_password_async() v14.1 开始 ===")

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

            cookies = ctx._cookies_dict()
            for nm, vl in cookies.items():
                _wr(f"[Cookie] 收到: {nm}={vl[:30]}... ")
                if nm == "server_session_ab24c166":
                    ctx.captcha_session_cookie = vl
            if not ctx.captcha_session_cookie:
                _wr("[WARN] 未拿到 server_session_ab24c166 cookie — 验证码可能失效")

            # === 2. 解析 Cap 验证 API 地址 ===
            html = content.decode("utf-8", errors="ignore")
            cap_ep = ""
            m = re.search(r'data-cap-api-endpoint="([^"]+)"', html)
            if m:
                cap_ep = m.group(1)
                _wr(f"[Cap] 检测到验证 API: {cap_ep}")

            # === 3. 优先 Cap 自动登录（最多重试 2 次） ===
            if cap_ep:
                cap_err = ""
                for attempt in range(2):
                    try:
                        _wr(f"[Cap] 第 {attempt+1} 次求解...")
                        cap_token = await _cap_solve_for_login(ctx, cap_ep)
                        _wr(f"[Cap] 求解成功 token={cap_token[:30]}...")
                        login = await _post_login_form(ctx, cap_token=cap_token)
                        if login.get("ok"):
                            return login
                        cap_err = login.get("error", "")
                        _wr(f"[Cap] 登录未成功: {cap_err}")
                        # 若被认定为验证码错误 → 重新求解重试；账号/密码类错误直接返回
                        if "验证码" not in cap_err:
                            await ctx.close()
                            _CURRENT_CTX = None
                            return login
                    except Exception as e:
                        cap_err = str(e)[:120]
                        _wr(f"[Cap] 求解/登录异常: {e}")
                # 两次 Cap 均失败 → 回退图片验证码（保留 ctx）
                logger.warning(f"[QR登录] Cap 自动登录失败({cap_err})，回退图片验证码")
                return await _setup_image_captcha(ctx)

            # === 4. 无 Cap 验证 → 直接图片验证码回退 ===
            return await _setup_image_captcha(ctx)

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
                "cap_token": "",  # 回退流程走图片验证码（vdcode），cap_token 留空
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
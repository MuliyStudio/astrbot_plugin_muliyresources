# -*- coding: utf-8 -*-
"""群聊小游戏：猜数字 + 封面猜猜（题库、像素化、积分台账）。

设计约束：
- 不依赖 AstrBot：纯逻辑 + 文件存储，方便单测；
- 群游戏会话在 main.py 里按「平台:群号」保存，本模块只负责题目和结算数据；
- 封面题库来自片库 pdy0 的 ajax 列表，按天缓存到插件 data 目录；
- 游戏奖励单独记每日额度，和 PointsStore 的签到/搜索扣费互不干扰。
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = ImageOps = None

from .constants import logger

# 封面猜猜领域：pdy 分类 tid / 展示名 / MDI 图标
COVER_KINDS = {
    "movie": {"label": "电影", "tid": 1, "icon": "movie"},
    "tv": {"label": "电视剧", "tid": 2, "icon": "tv"},
    "anime": {"label": "动漫", "tid": 4, "icon": "anime"},
}

# ==================== 猜数字 ====================

class BombGame:
    """1-N 猜数字：猜中即获胜；每次猜测返回 low / high 提示。

    名字保留 BombGame 是为了兼容旧调用；对外玩法已经是「猜数字」：
    不淘汰、不重埋，猜中的人直接获胜。
    """

    def __init__(self, low: int = 1, high: int = 100, value: int = 0,
                 rng: random.Random | None = None):
        self.low = int(low)
        self.high = int(high)
        self.rng = rng or random.Random()
        self.value = int(value) if value else self.rng.randint(self.low, self.high)

    def guess(self, number: int) -> dict:
        """返回 {type: hit/low/high/out, low, high, value}。"""
        n = int(number)
        if n < self.low or n > self.high:
            return {"type": "out", "low": self.low, "high": self.high,
                    "value": self.value}
        if n == self.value:
            return {"type": "hit", "low": self.low, "high": self.high,
                    "value": self.value}
        if n < self.value:
            self.low = n + 1
            return {"type": "low", "low": self.low, "high": self.high,
                    "value": self.value}
        self.high = n - 1
        return {"type": "high", "low": self.low, "high": self.high,
                "value": self.value}


# ==================== 封面题库 ====================

# 标题 / 分类命中这些词就不进题库（避免成人、预告片等不适合群聊的内容）
_BLOCK_RE = re.compile(
    r"情色|伦理|三级|成人|色情|裸露|裸体|裸照|性爱|做爱|强奸|乱伦|里番|无码|"
    r"预告|花絮|解说|抢先版|枪版|TS版|TC版",
    re.I,
)
_TITLE_BAD_RE = re.compile(r"^[\W_]+$", re.U)


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_genre(vod_class: str) -> str:
    parts = [p.strip() for p in re.split(r"[,，/、]", _clean(vod_class)) if p.strip()]
    return parts[0] if parts else ""


def build_pool(rows: list) -> list:
    """把 pdy ajax 行整理成去重后的封面题库。"""
    pool, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        title = _clean(r.get("vod_name"))
        pic = _clean(r.get("vod_pic"))
        if not title or len(title) < 2 or len(title) > 20:
            continue
        if _TITLE_BAD_RE.match(title) or title in seen:
            continue
        if not pic or pic in ("/", "-", "null"):
            continue
        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic.startswith("/"):
            pic = "https://www.pdy0.com" + pic
        genre = first_genre(r.get("vod_class"))
        blurb = f"{title} {genre} {_clean(r.get('vod_remarks'))}"
        if _BLOCK_RE.search(blurb):
            continue
        year = _clean(r.get("vod_year"))
        if not re.fullmatch(r"(19|20)\d{2}", year):
            year = ""
        area = _clean(r.get("vod_area"))
        area = re.split(r"[,，/、]", area)[0].strip() if area else ""
        try:
            score = float(r.get("vod_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            vod_id = int(r.get("vod_id") or 0)
        except (TypeError, ValueError):
            vod_id = 0
        seen.add(title)
        pool.append({
            "id": vod_id,
            "title": title,
            "year": year,
            "genre": genre or "影视",
            "area": area,
            "score": round(score, 1),
            "cover": pic,
        })
    return pool


def fetch_pool(fetch_page: Callable[[int, int], list],
               tids=(1, 2, 4), pages: int = 2, kind: str = "") -> list:
    """从片库分类接口抓题库。fetch_page(tid, page) -> rows。"""
    if isinstance(tids, int):
        tids = (tids,)
    rows = []
    for tid in tids:
        for page in range(1, max(1, int(pages)) + 1):
            try:
                rows.extend(fetch_page(int(tid), int(page)) or [])
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[小游戏] 题库抓取失败 tid={tid} page={page}: {e}")
    pool = build_pool(rows)
    if kind:
        for r in pool:
            r["kind"] = kind
    return pool


def read_pool_cache(path: str) -> tuple[list, float]:
    """返回 (题库, 时间戳)；文件不存在/损坏返回 ([], 0)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pool = data.get("pool") if isinstance(data, dict) else None
        ts = float(data.get("ts") or 0) if isinstance(data, dict) else 0
        return (pool if isinstance(pool, list) else []), ts
    except Exception:
        return [], 0.0


def save_pool_cache(path: str, pool: list) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "pool": pool}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[小游戏] 题库缓存写入失败: {e}")


# ==================== 封面图片 ====================

def pillow_available() -> bool:
    return Image is not None


def pixelate_cover(data: bytes, block: int = 12, max_width: int = 420) -> bytes | None:
    """把封面缩小再放大，做成马赛克 JPEG；失败返回 None。"""
    if not data or Image is None:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return None
        if w > max_width:
            img = img.resize((max_width, max(1, int(h * max_width / w))),
                             Image.LANCZOS)
        w, h = img.size
        b = max(4, min(int(block or 12), max(4, min(w, h) // 4)))
        small = img.resize((max(1, w // b), max(1, h // b)), Image.NEAREST)
        img = small.resize((w, h), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[小游戏] 封面像素化失败: {e}")
        return None


def fetch_cover_bytes(url: str, cache_path: str = "",
                      block: int = 12) -> bytes | None:
    """下载封面（优先读本地缓存）并返回马赛克图。"""
    raw = b""
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                raw = f.read()
        except Exception:
            raw = b""
    if len(raw) < 1024:
        if requests is None:
            return None
        try:
            r = requests.get(url, timeout=12, headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36"),
                "Referer": "https://www.pdy0.com/",
            })
            if r.status_code != 200 or len(r.content) < 1024:
                return None
            raw = r.content
            if cache_path:
                try:
                    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
                    with open(cache_path, "wb") as f:
                        f.write(raw)
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[小游戏] 封面下载失败: {e}")
            return None
    return pixelate_cover(raw, block=block)


def cleanup_cover_cache(cover_dir: str, keep: int = 240) -> None:
    """封面缓存只保留最近 keep 张，避免长期占用磁盘。"""
    try:
        files = [os.path.join(cover_dir, n) for n in os.listdir(cover_dir)]
        files = [p for p in files if os.path.isfile(p)]
        if len(files) <= keep:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[: len(files) - keep]:
            try:
                os.unlink(p)
            except Exception:
                pass
    except Exception:
        pass


# ==================== 题目 ====================

def _title_key(title: str) -> str:
    """去掉季数/续作标记/符号，用于避免同一部剧的两个条目同时出现在选项里。"""
    s = _clean(title)
    s = re.sub(r"第[一二三四五六七八九十0-9]+[季部篇章]", "", s)
    s = re.sub(r"其[之]?[一二三四五六七八九十0-9]+", "", s)
    s = re.sub(r"part[.．]?\s*[0-9]+", "", s, flags=re.I)
    s = re.sub(r"剧场版|电影版|特别篇|特别版", "", s)
    s = re.sub(r"[\W_]+", "", s, flags=re.UNICODE)
    return s.lower()


def _similar_title(key_a: str, title_b: str) -> bool:
    key_b = _title_key(title_b)
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    if len(key_a) >= 4 and len(key_b) >= 4:
        return key_a in key_b or key_b in key_a
    return False


def _take_decoys(pool: list, correct_key: str, count: int = 3) -> list:
    """挑干扰项：避开正确答案的续作，也避免干扰项彼此是同一部剧。"""
    picked = []
    for r in pool:
        title = r.get("title") or ""
        if not title or _similar_title(correct_key, title):
            continue
        key = _title_key(title)
        if any(_similar_title(_title_key(o.get("title") or ""), title)
               or _similar_title(key, o.get("title") or "") for o in picked):
            continue
        picked.append(r)
        if len(picked) >= count:
            break
    return picked


def pick_question(pool: list, used: set, rng: random.Random | None = None) -> dict | None:
    """从题库里抽 1 个正确答案 + 3 个同类型干扰项。"""
    rng = rng or random.Random()
    if not pool or len(pool) < 4:
        return None
    candidates = [r for r in pool if r.get("title") not in used]
    if not candidates:
        used.clear()
        candidates = list(pool)

    def _score(r):
        try:
            return float(r.get("score") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _year(r):
        try:
            return int(r.get("year") or 0)
        except (TypeError, ValueError):
            return 0

    # 优先「近几年的 + 高评分」的条目：最新列表里也会混入很冷门的老片，
    # 但四选一需要玩家至少对画面/年份有印象，所以尽量往热门现代作品靠。
    hot = [r for r in candidates if _score(r) >= 7.0 and _year(r) >= 2018]
    recent = [r for r in candidates if _score(r) >= 6.0 and _year(r) >= 2018]
    if len(hot) >= 4:
        preferred = hot
    elif len(recent) >= 4:
        preferred = recent
    else:
        preferred = [r for r in candidates if _score(r) >= 6.0]
    if len(preferred) < 4:
        preferred = candidates
    correct = rng.choice(preferred)
    correct_key = _title_key(correct.get("title") or "")
    genre = correct.get("genre") or ""
    others = [r for r in pool
              if r.get("title") != correct.get("title")
              and not _similar_title(correct_key, r.get("title") or "")]
    # 干扰项也优先用同一批「较热门」的条目，再退回全量
    decoy_pool = [r for r in preferred if r.get("title") != correct.get("title")
                  and not _similar_title(correct_key, r.get("title") or "")]
    same = [r for r in decoy_pool if (r.get("genre") or "") == genre]
    rest = [r for r in decoy_pool if r not in same]
    rng.shuffle(same)
    rng.shuffle(rest)
    decoys = _take_decoys(same + rest, correct_key, 3)
    if len(decoys) < 3:
        extra = [r for r in others if r not in decoys]
        rng.shuffle(extra)
        decoys = _take_decoys(decoys + extra, correct_key, 3)
    if len(decoys) < 3:
        return None
    options = [correct] + decoys
    rng.shuffle(options)
    answer = "ABCD"[options.index(correct)]
    used.add(correct.get("title"))
    hint = " · ".join(x for x in (
        correct.get("year"), correct.get("genre"), correct.get("area")) if x)
    return {
        "correct": correct,
        "options": options,
        "answer": answer,
        "hint": hint,
    }


def normalize_choice(text: str) -> str:
    """把 A/B/C/D、1/2/3/4、全角字母/数字统一成 A-D；无效返回空串。"""
    s = _clean(text).upper()
    for src, dst in (("Ａ", "A"), ("Ｂ", "B"), ("Ｃ", "C"), ("Ｄ", "D"),
                     ("１", "1"), ("２", "2"), ("３", "3"), ("４", "4")):
        s = s.replace(src, dst)
    s = s.strip(" .。:：,，、")
    if s in ("A", "B", "C", "D"):
        return s
    if s in ("1", "2", "3", "4"):
        return "ABCD"[int(s) - 1]
    return {"一": "A", "二": "B", "三": "C", "四": "D"}.get(s, "")


# ==================== 游戏台账（每日奖励额度 / 胜场） ====================

class MiniGameStore:
    """小游戏战绩 + 每日奖励额度。

    文件放在插件 data 目录，和 points.json 分开；损坏时自动备份重建。
    """

    def __init__(self, path: str, tz_getter: Optional[Callable[[], object]] = None):
        self.path = path
        self._tz_getter = tz_getter
        self._lock = threading.RLock()
        self._data = {"version": 1, "users": {}, "cover": {}, "uc": {}}
        self.load()

    def _now(self) -> datetime:
        tz = None
        if self._tz_getter:
            try:
                tz = self._tz_getter()
            except Exception:
                tz = None
        if tz is not None:
            try:
                return datetime.now(tz)
            except Exception:
                pass
        return datetime.now()

    def today(self) -> str:
        return self._now().date().isoformat()

    def load(self) -> None:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("users"), dict):
                    self._data = data
                    if not isinstance(self._data.get("cover"), dict):
                        self._data["cover"] = {}
                    if not isinstance(self._data.get("uc"), dict):
                        self._data["uc"] = {}
            except FileNotFoundError:
                return
            except Exception:
                try:
                    os.replace(self.path, f"{self.path}.bad.{int(time.time())}")
                except Exception:
                    pass

    def _save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def _ensure(self, key: str, name: str = "") -> dict:
        users = self._data.setdefault("users", {})
        user = users.get(key)
        if not isinstance(user, dict):
            user = {
                "name": name or "", "wins": 0, "plays": 0,
                "streak": 0, "best_streak": 0, "last_win": "",
                "daily": {},
            }
            users[key] = user
        user.setdefault("name", name or "")
        user.setdefault("wins", 0)
        user.setdefault("plays", 0)
        user.setdefault("streak", 0)
        user.setdefault("best_streak", 0)
        user.setdefault("last_win", "")
        user.setdefault("daily", {})
        if name and user.get("name") != name:
            user["name"] = name
        return user

    def today_awarded(self, key: str) -> int:
        with self._lock:
            user = self._data.get("users", {}).get(key)
            if not isinstance(user, dict):
                return 0
            try:
                return max(0, int((user.get("daily") or {}).get(self.today(), 0) or 0))
            except (TypeError, ValueError):
                return 0

    def award(self, key: str, name: str, amount: int, cap: int) -> tuple[int, int]:
        """发放奖励，返回 (实际发放, 今日累计)。积分本身由 PointsStore 加。"""
        amount = max(0, int(amount or 0))
        cap = max(0, int(cap or 0))
        with self._lock:
            user = self._ensure(key, name)
            today = self.today()
            daily = user.setdefault("daily", {})
            try:
                current = max(0, int(daily.get(today, 0) or 0))
            except (TypeError, ValueError):
                current = 0
            actual = max(0, min(amount, cap - current)) if cap > 0 else amount
            if actual > 0:
                daily[today] = current + actual
                # 只保留最近 14 天，避免文件无限增长
                keep = {(self._now().date() - timedelta(days=i)).isoformat()
                        for i in range(14)}
                for d in list(daily):
                    if d not in keep:
                        daily.pop(d, None)
                self._save()
            return actual, current + actual

    def record(self, key: str, name: str, win: bool = False) -> dict:
        """记一局：plays+1；win 时 wins/连胜 +1。返回用户快照。"""
        with self._lock:
            user = self._ensure(key, name)
            user["plays"] = max(0, int(user.get("plays", 0) or 0)) + 1
            if win:
                today = self.today()
                last = str(user.get("last_win") or "")
                try:
                    streak = max(0, int(user.get("streak", 0) or 0))
                except (TypeError, ValueError):
                    streak = 0
                yesterday = (self._now().date() - timedelta(days=1)).isoformat()
                streak = streak + 1 if last == yesterday else 1
                user["streak"] = streak
                user["best_streak"] = max(
                    int(user.get("best_streak", 0) or 0), streak)
                user["last_win"] = today
                user["wins"] = max(0, int(user.get("wins", 0) or 0)) + 1
            else:
                user["streak"] = 0
            self._save()
            return dict(user)

    def stats(self, key: str) -> dict:
        with self._lock:
            user = self._data.get("users", {}).get(key)
            return dict(user) if isinstance(user, dict) else {}

    # ==================== 封面猜猜今日榜 ====================

    @staticmethod
    def _cover_better(a: dict, b: dict) -> bool:
        """答对多优先；同分用时短优先；再同分更早完成的优先。"""
        def _v(x, k, default):
            try:
                return float(x.get(k, default) or default)
            except (TypeError, ValueError):
                return float(default)
        return (_v(a, "correct", 0), -_v(a, "seconds", 10 ** 9), -_v(a, "updated", 0)) > (
            _v(b, "correct", 0), -_v(b, "seconds", 10 ** 9), -_v(b, "updated", 0))

    def cover_record(self, key: str, name: str, correct: int, total: int,
                     seconds: int, awarded: int = 0) -> dict:
        """记录一次封面猜猜成绩，只保留该用户当天最好成绩。"""
        with self._lock:
            cover = self._data.setdefault("cover", {})
            day = self.today()
            board = cover.setdefault(day, {})
            entry = {
                "name": name or key,
                "correct": max(0, int(correct or 0)),
                "total": max(1, int(total or 1)),
                "seconds": max(1, int(seconds or 1)),
                "awarded": max(0, int(awarded or 0)),
                "updated": time.time(),
            }
            old = board.get(key)
            if isinstance(old, dict):
                try:
                    entry["awarded"] = max(
                        entry["awarded"], int(old.get("awarded", 0) or 0))
                except (TypeError, ValueError):
                    pass
            if not isinstance(old, dict) or self._cover_better(entry, old):
                board[key] = entry
            # 只保留最近 14 天
            keep = {(self._now().date() - timedelta(days=i)).isoformat()
                    for i in range(14)}
            for d in list(cover):
                if d not in keep:
                    cover.pop(d, None)
            self._save()
            return dict(board.get(key) or entry)

    def _cover_rows(self, day: str = "") -> list:
        board = (self._data.get("cover") or {}).get(day or self.today(), {})
        rows = [(k, dict(v)) for k, v in board.items() if isinstance(v, dict)]
        rows.sort(key=lambda kv: (
            -int(kv[1].get("correct", 0) or 0),
            int(kv[1].get("seconds", 10 ** 9) or 10 ** 9),
            float(kv[1].get("updated", 0) or 0),
        ))
        return rows

    def cover_top(self, limit: int = 10, day: str = "") -> list:
        with self._lock:
            rows = self._cover_rows(day)
            return [(i + 1, k, dict(v))
                    for i, (k, v) in enumerate(rows[:max(1, int(limit))])]

    def cover_rank(self, key: str, day: str = "") -> int:
        with self._lock:
            for i, (k, _v) in enumerate(self._cover_rows(day), 1):
                if k == key:
                    return i
            return 0

    def cover_count(self, day: str = "") -> int:
        with self._lock:
            return len(self._cover_rows(day))

    # ==================== 谁是卧底战绩 ====================

    def uc_record(self, key: str, name: str, role: str, win: bool,
                  rounds: int = 0, desc_count: int = 0,
                  votes_received: int = 0) -> dict:
        """记一局卧底：身份、胜负、参与轮数、被投次数。"""
        with self._lock:
            uc = self._data.setdefault("uc", {})
            user = uc.get(key)
            if not isinstance(user, dict):
                user = {
                    "name": name or "", "plays": 0, "wins": 0,
                    "spy_plays": 0, "spy_wins": 0,
                    "rounds": 0, "descs": 0, "votes_received": 0,
                    "days": {},
                }
                uc[key] = user
            user["name"] = name or user.get("name") or ""
            user["plays"] = max(0, int(user.get("plays", 0) or 0)) + 1
            if win:
                user["wins"] = max(0, int(user.get("wins", 0) or 0)) + 1
            if role == "spy":
                user["spy_plays"] = max(0, int(user.get("spy_plays", 0) or 0)) + 1
                if win:
                    user["spy_wins"] = max(0, int(user.get("spy_wins", 0) or 0)) + 1
            user["rounds"] = max(0, int(user.get("rounds", 0) or 0)) + max(0, int(rounds))
            user["descs"] = max(0, int(user.get("descs", 0) or 0)) + max(0, int(desc_count))
            user["votes_received"] = (max(0, int(user.get("votes_received", 0) or 0))
                                      + max(0, int(votes_received)))
            days = user.setdefault("days", {})
            if not isinstance(days, dict):
                days = {}
                user["days"] = days
            today = self.today()
            cell = days.get(today)
            if not isinstance(cell, dict):
                cell = {"plays": 0, "wins": 0}
                days[today] = cell
            cell["plays"] = max(0, int(cell.get("plays", 0) or 0)) + 1
            if win:
                cell["wins"] = max(0, int(cell.get("wins", 0) or 0)) + 1
            keep = {(self._now().date() - timedelta(days=i)).isoformat()
                    for i in range(14)}
            for d in list(days):
                if d not in keep:
                    days.pop(d, None)
            self._save()
            return dict(user)

    def uc_stats(self, key: str) -> dict:
        with self._lock:
            user = (self._data.get("uc") or {}).get(key)
            return dict(user) if isinstance(user, dict) else {}

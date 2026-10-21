# -*- coding: utf-8 -*-
"""全局积分与每日签到（本地 JSON 持久化）。

设计要点：
- 用户积分按「平台:用户ID」全局共享，不区分群聊 / 私聊，换群不会丢；
- 数据文件放在 AstrBot data 目录（插件目录之外），覆盖安装 / 热重载不丢；
- 所有读改写都在同一把线程锁内完成，落盘使用「临时文件 + os.replace」原子替换；
- 文件损坏时自动备份为 points.json.bad.<时间戳>，再以空数据启动，避免静默覆盖用户数据。
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class PointsStore:
    """积分数据存储。

    tz_getter: 可选回调，返回 datetime.timezone / zoneinfo.ZoneInfo；
    用于让「签到日期」跟随插件使用的时区（默认 Asia/Shanghai），而不是服务器时区。
    """

    def __init__(self, path: str, tz_getter: Optional[Callable[[], object]] = None):
        self.path = path
        self._tz_getter = tz_getter
        self._lock = threading.RLock()
        self._data = {"version": 1, "users": {}}
        self.load()

    # ==================== 基础 I/O ====================

    def load(self) -> None:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("users"), dict):
                    self._data = data
            except FileNotFoundError:
                return
            except Exception:
                # 损坏文件先备份，避免下一次保存把原数据彻底覆盖
                try:
                    os.replace(self.path, f"{self.path}.bad.{int(time.time())}")
                except Exception:
                    pass

    def _save(self) -> None:
        """原子写盘，避免进程中断时写坏 JSON。"""
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ==================== 时间 / 用户 ====================

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

    @staticmethod
    def make_key(platform: str, user_id: str) -> str:
        platform = (platform or "unknown").strip() or "unknown"
        return f"{platform}:{user_id}"

    def _ensure(self, key: str, name: str = "", initial: int = 0) -> dict:
        users = self._data.setdefault("users", {})
        user = users.get(key)
        if not isinstance(user, dict):
            user = {
                "points": max(0, int(initial or 0)),
                "total_earned": max(0, int(initial or 0)),
                "total_spent": 0,
                "last_checkin": "",
                "streak": 0,
                "name": name or "",
                "created": _now_str(),
                "updated": _now_str(),
            }
            users[key] = user
        else:
            user.setdefault("points", 0)
            user.setdefault("total_earned", 0)
            user.setdefault("total_spent", 0)
            user.setdefault("last_checkin", "")
            user.setdefault("streak", 0)
            user.setdefault("name", "")
            user.setdefault("created", _now_str())
            user.setdefault("updated", _now_str())
        if name and user.get("name") != name:
            user["name"] = name
        return user

    # ==================== 查询 ====================

    def get(self, key: str, name: str = "", initial: int = 0) -> dict:
        with self._lock:
            user = self._ensure(key, name, initial)
            self._save()
            return dict(user)

    def balance(self, key: str) -> int:
        with self._lock:
            user = self._data.get("users", {}).get(key)
            if not isinstance(user, dict):
                return 0
            try:
                return max(0, int(user.get("points", 0) or 0))
            except (TypeError, ValueError):
                return 0

    def top(self, limit: int = 10) -> list[tuple[str, dict]]:
        with self._lock:
            rows = []
            for key, user in (self._data.get("users") or {}).items():
                if not isinstance(user, dict):
                    continue
                try:
                    points = max(0, int(user.get("points", 0) or 0))
                except (TypeError, ValueError):
                    points = 0
                rows.append((points, key, user))
            rows.sort(key=lambda x: x[0], reverse=True)
            return [(key, user) for _, key, user in rows[:max(1, int(limit))]]

    # ==================== 增减 ====================

    def add(self, key: str, amount: int, name: str = "", initial: int = 0) -> int:
        with self._lock:
            user = self._ensure(key, name, initial)
            before = max(0, int(user.get("points", 0) or 0))
            after = max(0, before + int(amount))
            delta = after - before
            user["points"] = after
            if delta > 0:
                user["total_earned"] = max(0, int(user.get("total_earned", 0) or 0)) + delta
            elif delta < 0:
                user["total_spent"] = max(0, int(user.get("total_spent", 0) or 0)) - delta
            user["updated"] = _now_str()
            self._save()
            return after

    def set_balance(self, key: str, value: int, name: str = "") -> int:
        with self._lock:
            user = self._ensure(key, name, 0)
            user["points"] = max(0, int(value))
            user["updated"] = _now_str()
            self._save()
            return user["points"]

    def spend(self, key: str, amount: int, name: str = "",
              initial: int = 0) -> tuple[bool, int]:
        """扣除积分。余额不足时不扣、不写盘，返回 (False, 当前余额)。"""
        amount = max(0, int(amount or 0))
        with self._lock:
            user = self._ensure(key, name, initial)
            balance = max(0, int(user.get("points", 0) or 0))
            if amount <= 0:
                return True, balance
            if balance < amount:
                return False, balance
            balance -= amount
            user["points"] = balance
            user["total_spent"] = max(0, int(user.get("total_spent", 0) or 0)) + amount
            user["updated"] = _now_str()
            self._save()
            return True, balance

    def refund(self, key: str, amount: int, name: str = "") -> int:
        with self._lock:
            user = self._ensure(key, name, 0)
            amount = max(0, int(amount or 0))
            user["points"] = max(0, int(user.get("points", 0) or 0)) + amount
            user["total_spent"] = max(0, int(user.get("total_spent", 0) or 0) - amount)
            user["updated"] = _now_str()
            self._save()
            return user["points"]

    # ==================== 签到 ====================

    def checkin(
        self,
        key: str,
        base_points: int,
        streak_bonus: int = 0,
        streak_max: int = 7,
        name: str = "",
        initial: int = 0,
    ) -> dict:
        """每日签到。

        连续签到：昨天也签到则 streak+1，否则从 1 重新开始；
        加成 = min(streak - 1, streak_max) * streak_bonus（首日无加成）。
        返回 dict：ok / duplicate / earned / bonus / streak / balance / today。
        """
        base_points = max(0, int(base_points or 0))
        streak_bonus = max(0, int(streak_bonus or 0))
        streak_max = max(1, int(streak_max or 1))
        today = self.today()
        with self._lock:
            user = self._ensure(key, name, initial)
            last = str(user.get("last_checkin") or "")
            balance = max(0, int(user.get("points", 0) or 0))
            streak = max(0, int(user.get("streak", 0) or 0))
            if last == today:
                return {
                    "ok": False, "duplicate": True, "earned": 0, "bonus": 0,
                    "streak": streak, "balance": balance, "today": today,
                }

            yesterday = (self._now().date() - timedelta(days=1)).isoformat()
            streak = streak + 1 if last == yesterday else 1
            bonus = min(max(0, streak - 1), streak_max) * streak_bonus
            earned = base_points + bonus
            balance += earned

            user["points"] = balance
            user["total_earned"] = max(0, int(user.get("total_earned", 0) or 0)) + earned
            user["last_checkin"] = today
            user["streak"] = streak
            user["updated"] = _now_str()
            self._save()
            return {
                "ok": True, "duplicate": False, "earned": earned, "bonus": bonus,
                "streak": streak, "balance": balance, "today": today,
            }

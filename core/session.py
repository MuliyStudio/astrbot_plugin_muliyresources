# -*- coding: utf-8 -*-
"""会话管理器"""
import time
from astrbot.api.event import AstrMessageEvent
from .constants import SESSION_TIMEOUT, logger


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def _key(self, e) -> str:
        p = e.get_platform_id(); u = e.get_sender_id(); g = e.get_group_id()
        return f"{p}:{u}:{g}" if g else f"{p}:{u}"

    def get(self, e):
        k = self._key(e); s = self._sessions.get(k)
        if not s: return None
        if time.time() - s.get("_updated", 0) > SESSION_TIMEOUT:
            del self._sessions[k]; return None
        return s

    def set(self, e, d: dict):
        d["_updated"] = time.time(); self._sessions[self._key(e)] = d

    def update(self, e, **kw):
        k = self._key(e)
        if k in self._sessions: self._sessions[k].update(kw); self._sessions[k]["_updated"] = time.time()

    def delete(self, e):
        self._sessions.pop(self._key(e), None)


class SearchSessionManager:
    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def _key(self, e) -> str:
        p = e.get_platform_id(); u = e.get_sender_id(); g = e.get_group_id()
        return f"{p}:{u}:{g}" if g else f"{p}:{u}"

    def get(self, e):
        k = self._key(e); s = self._sessions.get(k)
        if not s: return None
        if time.time() - s.get("_updated", 0) > SESSION_TIMEOUT:
            del self._sessions[k]; return None
        return s

    def set(self, e, d: dict):
        d["_updated"] = time.time(); self._sessions[self._key(e)] = d

    def update(self, e, **kw):
        k = self._key(e)
        if k in self._sessions: self._sessions[k].update(kw); self._sessions[k]["_updated"] = time.time()

    def delete(self, e):
        self._sessions.pop(self._key(e), None)

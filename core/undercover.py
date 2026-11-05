# -*- coding: utf-8 -*-
"""群聊小游戏：谁是卧底（纯逻辑，不依赖 AstrBot）。

设计约束与 `core/minigame.py` 一致：
- 只负责规则、发词、计票、胜负判定，不碰消息、不读配置；
- 群会话由 main.py 按「平台:群号」保存，本模块不持有全局状态；
- 可直接单测（`python -m pytest` / 手写脚本都行）。

关键规则：
- 暗卧底：玩家只知道自己拿到的词，**不告诉卧底身份**；
- 平民拿到同一个词，卧底拿到意思相近的另一个词；
- 描述不能直接说出自己的词；
- 投票只公布票数，不公布谁投了谁。
"""
from __future__ import annotations

import json
import os
import random
import re
from typing import Optional

from .constants import logger
from .undercover_words import PAIRS

ROLE_CIVIL = "civil"
ROLE_SPY = "spy"

LEVELS = {"easy": 1, "normal": 2, "hard": 3}

_MIN_LEN = 2
_MAX_LEN = 8
_MAX_LEN_GAP = 2

_BAD_WORD_RE = re.compile(
    r"情色|伦理|三级|成人|色情|裸露|裸体|性爱|做爱|强奸|乱伦|里番|无码|"
    r"涉政|台独|港独|法轮",
    re.I,
)


# ==================== 词库 ====================

def pair_key(pair: dict) -> str:
    """词对去重键：与 a/b 顺序无关。"""
    a = str((pair or {}).get("a") or "").strip()
    b = str((pair or {}).get("b") or "").strip()
    return "|".join(sorted((a, b)))


def validate_pair(pair) -> bool:
    """检查一组词对是否适合出题；不合格的词对直接丢弃。"""
    if not isinstance(pair, dict):
        return False
    a = str(pair.get("a") or "").strip()
    b = str(pair.get("b") or "").strip()
    if not a or not b or a == b:
        return False
    if not (_MIN_LEN <= len(a) <= _MAX_LEN) or not (_MIN_LEN <= len(b) <= _MAX_LEN):
        return False
    if abs(len(a) - len(b)) > _MAX_LEN_GAP:
        return False
    # 互相包含 = 上下位 / 别名词，一眼就能猜出来
    if a in b or b in a:
        return False
    if re.search(r"\s", a + b):
        return False
    if _BAD_WORD_RE.search(a) or _BAD_WORD_RE.search(b):
        return False
    return True


def _normalize(pair: dict) -> dict:
    a = str(pair.get("a") or "").strip()
    b = str(pair.get("b") or "").strip()
    try:
        level = int(pair.get("level", 2) or 2)
    except (TypeError, ValueError):
        level = 2
    return {
        "a": a,
        "b": b,
        "level": max(1, min(3, level)),
        "cat": str(pair.get("cat") or "").strip(),
    }


def load_pairs(extra_path: str = "") -> list:
    """内置词库 + data 目录自定义词库，去重并过滤不合法词对。

    extra_path 是 JSON 文件，内容为 `[{"a": "...", "b": "...", "level": 2}, ...]`。
    读取失败只记日志，不影响内置词库。
    """
    out: list = []
    seen: set = set()

    def _add(items) -> None:
        for raw in items or []:
            if not validate_pair(raw):
                continue
            pair = _normalize(raw)
            key = pair_key(pair)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(pair)

    _add(PAIRS)
    if extra_path and os.path.isfile(extra_path):
        try:
            with open(extra_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("pairs") or []
            if isinstance(data, list):
                before = len(out)
                _add(data)
                logger.info(f"[卧底] 自定义词库已加载 {len(out) - before} 组")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[卧底] 自定义词库读取失败: {e}")
    return out


def pick_pair(pairs: list, rng: random.Random | None = None,
              recent: Optional[list] = None, level: str = "mixed") -> dict | None:
    """抽一组词对；尽量避开最近用过的（recent 是 pair_key 列表）。"""
    rng = rng or random.Random()
    pool = list(pairs or [])
    if not pool:
        return None
    want = LEVELS.get(str(level or "mixed").strip().lower())
    if want:
        pool = [p for p in pool if int(p.get("level", 2) or 2) == want] or pool
    used = set(recent or [])
    fresh = [p for p in pool if pair_key(p) not in used]
    return rng.choice(fresh or pool)


# ==================== 一局的状态机 ====================

class UndercoverGame:
    """一局谁是卧底的全部状态。

    players: {key: {"name": str, "uid": str, "host": bool}}
    """

    def __init__(self, players: dict, spy_count: int = 1,
                 rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.spy_count = max(1, int(spy_count or 1))
        self.players: dict = {}
        self.order: list = []
        for key, raw in (players or {}).items():
            k = str(key)
            raw = raw or {}
            self.players[k] = {
                "name": str(raw.get("name") or "玩家"),
                "uid": str(raw.get("uid") or ""),
                "host": bool(raw.get("host")),
                "alive": True,
                "word": "",
                "role": "",
                "dm_ok": bool(raw.get("dm_ok", True)),
                "violations": 0,
                "miss_streak": 0,
                "miss_rounds": 0,
                "can_vote": True,
                "votes_received": 0,
                "removed": False,
                "descs": {},
            }
            self.order.append(k)

        self.words = {"civil": "", "spy": ""}
        self.pair = {}
        self.round_no = 0
        self.turn_order: list = []
        self.turn_index = 0
        self.turn_key = ""
        self.round_descs: list = []       # [(key, text)]
        self.missed_round: set = set()
        self.history: dict = {}           # {round_no: [{"key","name","text"}]}
        self.votes: dict = {}             # {voter_key: target_key}
        self.tie_keys: list = []
        self.tie_times = 0
        self.abstain_rounds = 0
        self.started_at = 0.0

    # ---------- 基础查询 ----------

    def alive_keys(self) -> list:
        return [k for k in self.order if self.players[k]["alive"]]

    def spies_alive(self) -> int:
        return sum(1 for k in self.alive_keys()
                   if self.players[k]["role"] == ROLE_SPY)

    def civilians_alive(self) -> int:
        return sum(1 for k in self.alive_keys()
                   if self.players[k]["role"] == ROLE_CIVIL)

    def player(self, key: str) -> dict:
        return self.players.get(str(key)) or {}

    def vote_candidates(self) -> list:
        if self.tie_keys:
            return [k for k in self.alive_keys() if k in self.tie_keys]
        return self.alive_keys()

    # ---------- 发词 ----------

    def deal(self, pair: dict, rng: random.Random | None = None) -> set:
        """分配平民词 / 卧底词，返回卧底 key 集合。"""
        rng = rng or self.rng
        if not pair or not self.order:
            return set()
        a, b = str(pair.get("a") or ""), str(pair.get("b") or "")
        if rng.random() < 0.5:
            a, b = b, a
        self.pair = {"a": pair.get("a"), "b": pair.get("b"),
                     "level": pair.get("level"), "cat": pair.get("cat")}
        self.words = {"civil": a, "spy": b}
        keys = list(self.order)
        rng.shuffle(keys)
        n = max(1, min(self.spy_count, max(1, len(keys) - 1)))
        spy_keys = set(keys[:n])
        for k in self.order:
            p = self.players[k]
            p["role"] = ROLE_SPY if k in spy_keys else ROLE_CIVIL
            p["word"] = self.words[p["role"]]
        return spy_keys

    def remove(self, key: str) -> None:
        """发词失败等情况下把玩家移出本局（保留在名单里，标记出局）。"""
        p = self.players.get(str(key))
        if p:
            p["alive"] = False
            p["can_vote"] = False
            p["removed"] = True

    # ---------- 轮次 ----------

    def start_round(self, only: Optional[list] = None) -> str:
        """开始新一轮描述；only 用于平票加时，只让平票者发言。"""
        if only is None:
            self.round_no = max(0, int(self.round_no)) + 1
            self.tie_keys = []
            self.tie_times = 0
        self.round_descs = []
        self.missed_round = set()
        self.votes = {}
        keys = self.alive_keys()
        if only is not None:
            keys = [k for k in keys if k in set(only)]
        self.turn_order = list(keys)
        self.rng.shuffle(self.turn_order)
        self.turn_index = 0
        self.turn_key = self.turn_order[0] if self.turn_order else ""
        return self.turn_key

    def start_tie(self, keys: list) -> str:
        self.tie_keys = [k for k in self.alive_keys() if k in set(keys or [])]
        self.round_descs = []
        self.missed_round = set()
        self.votes = {}
        self.turn_order = list(self.tie_keys)
        self.rng.shuffle(self.turn_order)
        self.turn_index = 0
        self.turn_key = self.turn_order[0] if self.turn_order else ""
        return self.turn_key

    def next_turn(self) -> str:
        self.turn_index = int(self.turn_index) + 1
        if self.turn_index < len(self.turn_order):
            self.turn_key = self.turn_order[self.turn_index]
            return self.turn_key
        self.turn_key = ""
        return ""

    def current_player(self) -> dict:
        return self.players.get(self.turn_key) or {}

    # ---------- 描述 ----------

    def note_desc(self, key: str, text: str) -> None:
        key = str(key)
        text = str(text or "").strip()
        self.round_descs.append((key, text))
        p = self.players.get(key)
        if p:
            p["descs"][str(self.round_no)] = text
            p["miss_streak"] = 0
        self.history.setdefault(str(self.round_no), []).append(
            {"key": key, "name": (p or {}).get("name") or "玩家", "text": text})

    def mark_miss(self, key: str) -> None:
        key = str(key)
        self.missed_round.add(key)
        p = self.players.get(key)
        if not p:
            return
        p["miss_rounds"] = int(p.get("miss_rounds", 0) or 0) + 1
        p["miss_streak"] = int(p.get("miss_streak", 0) or 0) + 1
        if p["miss_streak"] >= 2:
            p["can_vote"] = False

    def desc_of(self, key: str) -> str:
        for k, t in reversed(self.round_descs):
            if k == key:
                return t
        return ""

    def round_rows(self) -> list:
        rows = []
        for i, k in enumerate(self.turn_order, 1):
            p = self.players.get(k) or {}
            rows.append({
                "n": i,
                "key": k,
                "name": p.get("name") or "玩家",
                "desc": self.desc_of(k),
                "miss": k in self.missed_round,
                "now": k == self.turn_key,
            })
        return rows

    # ---------- 投票 ----------

    def record_vote(self, voter: str, target: str) -> tuple[bool, str]:
        voter, target = str(voter), str(target)
        p = self.players.get(voter)
        if not p or not p.get("alive"):
            return False, "你不在本局存活名单里。"
        if not p.get("can_vote", True):
            return False, "你本轮没有投票权（连续弃权）。"
        cands = self.vote_candidates()
        if target not in cands:
            return False, "这个编号不在可投名单里。"
        if target == voter:
            return False, "不能投自己。"
        self.votes[voter] = target
        return True, ""

    def tally(self) -> dict:
        alive = self.alive_keys()
        cands = self.vote_candidates()
        counts = {k: 0 for k in cands}
        for voter, target in self.votes.items():
            if voter in alive and target in counts:
                counts[target] += 1
        maxn = max(counts.values()) if counts else 0
        top = [k for k in cands if counts.get(k, 0) == maxn] if maxn > 0 else []
        abstain = [k for k in alive if self.votes.get(k) not in counts]
        return {"counts": counts, "max": maxn, "top": top, "abstain": abstain}

    def all_voted(self) -> bool:
        alive = [k for k in self.alive_keys()
                 if self.players[k].get("can_vote", True)]
        return bool(alive) and all(k in self.votes for k in alive)

    def eliminate(self, key: str, votes: int = 0) -> bool:
        p = self.players.get(str(key))
        if not p or not p.get("alive"):
            return False
        p["alive"] = False
        p["votes_received"] = int(p.get("votes_received", 0) or 0) + max(0, int(votes))
        return True

    # ---------- 胜负 ----------

    def winner(self) -> Optional[str]:
        alive = self.alive_keys()
        if not alive:
            return ROLE_CIVIL
        if self.spies_alive() == 0:
            return ROLE_CIVIL
        if len(alive) <= 2:
            return ROLE_SPY
        if self.spies_alive() >= self.civilians_alive():
            return ROLE_SPY
        return None

"""Per-conversation chat history cache.

Keeps the last ~20 turns per conversation_id in memory so multi-turn chats
see what was said before. Without this every /chat call starts fresh —
"show me cheaper options" right after an SSD recommendation forgets it
was talking about SSDs.

Single-process in-memory store is fine for the demo: nc-chatbot runs at
replicas=1 and conversations live minutes, not days. For a production
chatbot you'd back this with Redis or a Postgres conversations table.
"""
from __future__ import annotations

from collections import OrderedDict
from time import time
from typing import Any

# (timestamp, messages) per conversation_id, LRU by insertion order.
_HISTORY: "OrderedDict[str, tuple[float, list[dict[str, Any]]]]" = OrderedDict()
_TTL_SEC = 1800            # 30 minutes — long enough for any demo conv, short enough that stale stuff ages out
_MAX_CONVOS = 5000         # process-wide cap on tracked convos
_MAX_TURNS_PER_CONVO = 20  # keep recent turns; trim older ones


def _prune() -> None:
    """Drop expired entries. Called on every get/put — O(n) worst case, fine at demo scale."""
    cutoff = time() - _TTL_SEC
    expired = [k for k, (t, _) in _HISTORY.items() if t < cutoff]
    for k in expired:
        del _HISTORY[k]


def get(conversation_id: str) -> list[dict[str, Any]]:
    """Return the prior message list for this conversation. Empty list if unknown."""
    if not conversation_id:
        return []
    _prune()
    entry = _HISTORY.get(conversation_id)
    return list(entry[1]) if entry else []


def put(conversation_id: str, messages: list[dict[str, Any]]) -> None:
    """Store the updated message list. Caller passes the full conversation."""
    if not conversation_id:
        return
    _prune()
    trimmed = messages[-_MAX_TURNS_PER_CONVO:]
    _HISTORY[conversation_id] = (time(), trimmed)
    _HISTORY.move_to_end(conversation_id)
    while len(_HISTORY) > _MAX_CONVOS:
        _HISTORY.popitem(last=False)

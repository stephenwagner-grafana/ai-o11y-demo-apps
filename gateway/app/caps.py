"""Per-provider cap state.

Tracks daily spend (cloud providers) and GPU utilization (Ollama).
Exposes `is_open(provider)` for the routing layer and `/open` endpoint.

Spend is tracked in-process for now (lost on restart). For a real
multi-replica gateway, this would move to Postgres or Redis. The demo
runs with replicas=1, so in-process is fine.

Reset semantics: rolling 24h (each spend event is timestamped, anything
older than 24h is excluded from the sum). Calendar-day reset is an
alternative — TBD.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger(__name__)


class CapTracker:
    """Thread-safe per-provider cap tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # provider -> deque of (timestamp_seconds, cost_usd)
        self._spend: dict[str, deque[tuple[float, float]]] = {}
        # provider -> latest GPU utilization ratio (Ollama only)
        self._gpu_util: dict[str, float] = {}

    def record_spend(self, provider: str, cost_usd: float, caller_type: str = "synthetic") -> None:
        """Record a single LLM call's cost. caller_type tag preserved for split metrics later."""
        if cost_usd <= 0:
            return
        with self._lock:
            self._spend.setdefault(provider, deque()).append((time.time(), cost_usd))
            self._prune(provider)

    def spent_today(self, provider: str) -> float:
        """Sum of spend in rolling 24h."""
        with self._lock:
            self._prune(provider)
            return sum(c for _, c in self._spend.get(provider, ()))

    def cap_usd(self, provider: str) -> float:
        """Configured cap from env. e.g. ANTHROPIC_CAP_USD_PER_DAY=20."""
        env_key = f"{provider.upper()}_CAP_USD_PER_DAY"
        try:
            return float(os.getenv(env_key, "0") or "0")
        except ValueError:
            return 0.0

    def is_configured(self, provider: str) -> bool:
        """Provider is 'configured' iff its API key (or URL for Ollama) is set."""
        if provider == "ollama":
            return bool(os.getenv("OLLAMA_BASE_URL"))
        return bool(os.getenv(f"{provider.upper()}_API_KEY"))

    def set_gpu_util(self, provider: str, ratio: float) -> None:
        with self._lock:
            self._gpu_util[provider] = ratio

    def gpu_util(self, provider: str) -> float:
        with self._lock:
            return self._gpu_util.get(provider, 0.0)

    def is_open(self, provider: str) -> tuple[bool, str | None]:
        """Return (open, reason_if_closed)."""
        if not self.is_configured(provider):
            return False, "not configured"
        if provider == "ollama":
            threshold = float(os.getenv("OLLAMA_GPU_UTILIZATION_THRESHOLD", "0.85"))
            util = self.gpu_util(provider)
            if util > threshold:
                return False, f"gpu utilization {util:.2f} > threshold {threshold:.2f}"
            return True, None
        # Cloud providers: check daily $ cap
        cap = self.cap_usd(provider)
        if cap <= 0:
            # No cap configured = not enforced (open by default)
            return True, None
        spent = self.spent_today(provider)
        if spent >= cap:
            return False, f"spent ${spent:.2f} / cap ${cap:.2f}"
        return True, None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Per-provider state for the /open endpoint."""
        out: dict[str, dict[str, Any]] = {}
        for provider in ("anthropic", "openai", "gemini", "ollama"):
            open_, reason = self.is_open(provider)
            entry: dict[str, Any] = {
                "open": open_,
                "configured": self.is_configured(provider),
            }
            if reason:
                entry["reason"] = reason
            if provider != "ollama":
                entry["spent_usd_today"] = round(self.spent_today(provider), 4)
                entry["cap_usd"] = self.cap_usd(provider)
            else:
                entry["gpu_utilization_ratio"] = self.gpu_util(provider)
                entry["gpu_threshold"] = float(os.getenv("OLLAMA_GPU_UTILIZATION_THRESHOLD", "0.85"))
            out[provider] = entry
        return out

    def _prune(self, provider: str) -> None:
        """Drop entries older than 24h. Must be called under lock."""
        cutoff = time.time() - 86400
        dq = self._spend.get(provider)
        if not dq:
            return
        while dq and dq[0][0] < cutoff:
            dq.popleft()


# Module-level singleton
caps = CapTracker()

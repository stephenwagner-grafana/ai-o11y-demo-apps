"""Provider routing.

Strategy: weighted sticky-hash across configured AND open providers.
Caller can ask for a specific provider via `preferred_provider`; if
that provider is closed, default behavior is to fall through to the
weighted pick (override with `strict: true` to instead return 503).

Two-tier routing by caller_type:
- `interactive` (real human, no synthetic header) → always Anthropic, no /open check
- `synthetic` (loadgen) → weighted across configured+open, respects /open

If a `preferred_provider` is set and open, use it regardless of caller_type.

Weighting: PROVIDER_WEIGHTS env var, e.g. "anthropic:1,ollama:2" gives
ollama ~67% of synthetic traffic and anthropic ~33%. Empty/unset =
uniform across configured-and-open providers (the original behavior).
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
from typing import Any

from . import providers
from .caps import caps
from .providers import anthropic as anthropic_provider
from .providers import gemini as gemini_provider
from .providers import openai as openai_provider
from .providers import ollama as ollama_provider

log = logging.getLogger(__name__)

PROVIDER_MODULES = {
    "anthropic": anthropic_provider,
    "openai": openai_provider,
    "gemini": gemini_provider,
    "ollama": ollama_provider,
}


def _parse_provider_weights(env_value: str) -> dict[str, float]:
    """Parse 'anthropic:1,ollama:2' → {'anthropic': 0.333, 'ollama': 0.667}.

    Empty / blank / unparseable yields {} (callers fall back to uniform).
    """
    if not env_value or not env_value.strip():
        return {}
    raw: dict[str, float] = {}
    for entry in env_value.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        provider, w_str = entry.rsplit(":", 1)
        try:
            w = float(w_str)
        except ValueError:
            log.warning("PROVIDER_WEIGHTS bad weight %r in %r", w_str, entry)
            continue
        if w > 0:
            raw[provider.strip()] = w
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {p: w / total for p, w in raw.items()}


_PROVIDER_WEIGHTS = _parse_provider_weights(os.getenv("PROVIDER_WEIGHTS", ""))
if _PROVIDER_WEIGHTS:
    log.info(
        "router: weighted provider pool: %s",
        ", ".join(f"{p}={w:.0%}" for p, w in _PROVIDER_WEIGHTS.items()),
    )


class RoutingError(RuntimeError):
    """Raised when no provider can serve a request."""


def _hash_frac(sticky_key: str) -> float:
    """Map a sticky_key to a [0, 1) float deterministically; random if no key."""
    if not sticky_key.strip("|"):
        return random.random()
    return int(hashlib.md5(sticky_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _sticky_pick(candidates: list[str], sticky_key: str) -> str:
    """Deterministic provider pick: same sticky_key → same provider.

    With PROVIDER_WEIGHTS set, walks the weight CDF restricted to the
    currently-open candidates. Without weights, uniform modulo (original
    behavior). Either way, a single conversation stays on one provider
    across turns — so the inner _pick_model layer's sticky-model
    behavior isn't broken by provider re-rolls.
    """
    if not _PROVIDER_WEIGHTS:
        # Uniform fallback (original behavior).
        if not sticky_key.strip("|"):
            return random.choice(candidates)
        h = int(hashlib.md5(sticky_key.encode()).hexdigest()[:8], 16)
        return candidates[h % len(candidates)]

    # Weighted-CDF walk over open candidates only. Renormalize: if Anthropic
    # is closed and only Ollama is open, Ollama gets 100% regardless of the
    # configured ratio.
    open_weights = [(p, _PROVIDER_WEIGHTS.get(p, 0.0)) for p in candidates]
    total = sum(w for _, w in open_weights)
    if total <= 0:
        # No configured weight for any open provider — uniform fallback.
        return candidates[int(_hash_frac(sticky_key) * len(candidates))]

    frac = _hash_frac(sticky_key)
    cumulative = 0.0
    for provider, w in open_weights:
        cumulative += w / total
        if frac < cumulative:
            return provider
    return open_weights[-1][0]


def select_provider(
    caller_type: str,
    preferred_provider: str | None = None,
    strict: bool = False,
    sticky_key: str = "",
) -> str:
    """Return the name of the provider that should serve this request.

    Raises RoutingError if no provider is available.
    `sticky_key` (typically session_id|conversation_id) makes the choice
    deterministic per conversation so a single thread doesn't hop providers.
    """
    # Interactive traffic always goes to Anthropic, ungated
    if caller_type == "interactive" and not preferred_provider:
        if caps.is_configured("anthropic"):
            return "anthropic"
        raise RoutingError("interactive traffic but ANTHROPIC_API_KEY not configured")

    # Explicit preferred provider
    if preferred_provider:
        open_, reason = caps.is_open(preferred_provider)
        if open_:
            return preferred_provider
        if strict:
            raise RoutingError(f"preferred_provider {preferred_provider} closed: {reason}")
        log.info("preferred_provider %s closed (%s) — falling through to sticky pick", preferred_provider, reason)

    # Sticky-hashed across configured AND open
    candidates = [p for p in PROVIDER_MODULES if caps.is_open(p)[0]]
    if not candidates:
        raise RoutingError("no providers open")

    chosen = _sticky_pick(candidates, sticky_key)
    return chosen

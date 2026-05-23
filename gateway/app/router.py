"""Provider routing.

Strategy: random across configured AND open providers. Caller can ask
for a specific provider via `preferred_provider`; if that provider is
closed, default behavior is to fall through to random (override with
`strict: true` to instead return 503).

Two-tier routing by caller_type:
- `interactive` (real human, no synthetic header) → always Anthropic, no /open check
- `synthetic` (loadgen) → random across configured+open, respects /open

If a `preferred_provider` is set and open, use it regardless of caller_type.
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


class RoutingError(RuntimeError):
    """Raised when no provider can serve a request."""


def _sticky_pick(candidates: list[str], sticky_key: str) -> str:
    """Deterministic provider pick: same sticky_key → same provider.

    Used so a single conversation stays on one provider across turns. Without
    this, each call re-rolls and a 5-turn convo can hop ollama → anthropic →
    ollama, which both looks weird in the Conversation Thread and breaks
    sticky-model behavior at the inner _pick_model layer.
    """
    if not sticky_key.strip("|"):
        return random.choice(candidates)
    h = int(hashlib.md5(sticky_key.encode()).hexdigest()[:8], 16)
    return candidates[h % len(candidates)]


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

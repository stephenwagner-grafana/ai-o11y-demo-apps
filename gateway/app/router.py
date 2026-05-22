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


def select_provider(
    caller_type: str,
    preferred_provider: str | None = None,
    strict: bool = False,
) -> str:
    """Return the name of the provider that should serve this request.

    Raises RoutingError if no provider is available.
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
        log.info("preferred_provider %s closed (%s) — falling through to random", preferred_provider, reason)

    # Random across configured AND open
    candidates = [p for p in PROVIDER_MODULES if caps.is_open(p)[0]]
    if not candidates:
        raise RoutingError("no providers open")

    chosen = random.choice(candidates)
    return chosen

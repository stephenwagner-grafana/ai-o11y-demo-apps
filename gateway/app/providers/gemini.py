"""Gemini provider via the Sigil SDK wrapper. Stub for Phase 1."""
from __future__ import annotations

import logging
import os
from typing import Any

from .base import ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

PROVIDER_NAME = "gemini"
DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-1.5-flash")


async def generate(req: ProviderRequest, sigil_client: Any) -> ProviderResponse:
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY not set")
    log.warning("gemini.generate() is a stub")
    return ProviderResponse(
        content="[stub] gemini.generate() not yet wired",
        model=req.model or DEFAULT_MODEL,
        provider=PROVIDER_NAME,
        input_tokens=1,
        output_tokens=10,
        cost_usd=0.0,
    )

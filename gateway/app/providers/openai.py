"""OpenAI provider via the Sigil SDK wrapper. Stub for Phase 1."""
from __future__ import annotations

import logging
import os
from typing import Any

from .base import ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

PROVIDER_NAME = "openai"
DEFAULT_MODEL = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")


async def generate(req: ProviderRequest, sigil_client: Any) -> ProviderResponse:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set")
    log.warning("openai.generate() is a stub")
    return ProviderResponse(
        content="[stub] openai.generate() not yet wired",
        model=req.model or DEFAULT_MODEL,
        provider=PROVIDER_NAME,
        input_tokens=1,
        output_tokens=10,
        cost_usd=0.0,
    )

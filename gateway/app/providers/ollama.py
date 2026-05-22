"""Ollama provider (hand-rolled — no Sigil SDK wrapper exists for Ollama).

When implemented, this module will:
1. Call Ollama's HTTP API at OLLAMA_BASE_URL
2. Use sigil_client.start_generation() / set_result() / close() manually
3. Capture all the OTel attributes the Sigil generation ingest expects
4. Emit gen_ai.client.cost.usd via the static $/output-token rate (see pricing.py)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .base import ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

PROVIDER_NAME = "ollama"
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "qwen2.5:32b")


async def generate(req: ProviderRequest, sigil_client: Any) -> ProviderResponse:
    if not os.getenv("OLLAMA_BASE_URL"):
        raise RuntimeError("OLLAMA_BASE_URL not set")
    log.warning("ollama.generate() is a stub")
    return ProviderResponse(
        content="[stub] ollama.generate() not yet wired",
        model=req.model or DEFAULT_MODEL,
        provider=PROVIDER_NAME,
        input_tokens=0,
        output_tokens=10,
        cost_usd=0.0,
    )

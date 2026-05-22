"""Anthropic provider via the Sigil SDK wrapper.

The Sigil SDK's Anthropic helper (sigil-sdk-anthropic) instruments every
call automatically — generation ingest to Sigil, OTel spans/metrics,
proper field capture (cache tokens, reasoning tokens, finish reasons).

We don't hand-roll any of that here; we just wrap the call and translate
the Sigil/Anthropic shapes to our ProviderResponse.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ..pricing import calculate_cost
from .base import ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

PROVIDER_NAME = "anthropic"
DEFAULT_MODEL = os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-4-5-20251001")


def _get_sigil_anthropic() -> Any:
    """Lazy import — the package is optional at install time."""
    try:
        # The actual import path may differ; verify when package is installed.
        # The Sigil setup brief documents `python-providers/anthropic` as the wrapper module.
        from sigil_sdk_anthropic import wrap_anthropic
        return wrap_anthropic
    except ImportError:
        log.error("sigil-sdk-anthropic not installed")
        return None


async def generate(req: ProviderRequest, sigil_client: Any) -> ProviderResponse:
    """Call Anthropic via the Sigil wrapper. Returns normalised response."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    model = req.model or DEFAULT_MODEL

    # TODO: replace this placeholder with the real Sigil wrapper call.
    # The shape will be something like:
    #
    #   from anthropic import AsyncAnthropic
    #   from sigil_sdk_anthropic import wrap_anthropic
    #
    #   client = wrap_anthropic(AsyncAnthropic(), sigil_client)
    #   rec = sigil_client.start_generation(
    #       agent_name=req.agent_name,
    #       conversation_id=req.conversation_id,
    #       parent_generation_ids=req.parent_generation_ids,
    #       tags={
    #           "app": req.app,
    #           "caller_type": req.caller_type,
    #           "session_id": req.session_id,
    #           "user_id": req.user_id,
    #       },
    #   )
    #   resp = await client.messages.create(model=model, messages=req.messages, max_tokens=req.max_tokens, ...)
    #   rec.set_result(
    #       response_id=resp.id,
    #       response_model=resp.model,
    #       stop_reason=resp.stop_reason,
    #       usage={
    #           "input_tokens": resp.usage.input_tokens,
    #           "output_tokens": resp.usage.output_tokens,
    #           "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
    #           "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0),
    #       },
    #   )
    #   rec.close()
    #   if rec.err(): log.error(...)
    #
    # For Phase 1 skeleton we return a placeholder so the wider system
    # can run end-to-end without a real API call.

    log.warning("anthropic.generate() is a stub — returning placeholder")

    content = "[stub] anthropic.generate() not yet wired to the Sigil SDK wrapper"
    input_tokens = sum(len(str(m.get("content", ""))) // 4 for m in req.messages) or 1
    output_tokens = 20

    cost = calculate_cost(PROVIDER_NAME, model, input_tokens, output_tokens)

    return ProviderResponse(
        content=content,
        model=model,
        provider=PROVIDER_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        finish_reason="end_turn",
        response_id="resp_stub",
        generation_id="gen_stub",
    )

"""LLM Gateway — the routing + instrumentation gatekeeper.

Endpoints:
  POST /v1/llm     -> route + execute an LLM call (returns content + tokens + cost)
  GET  /open       -> per-provider open/closed state for loadgen
  GET  /health     -> liveness
  GET  /readyz     -> readiness
  GET  /metrics    -> Prometheus metrics

See docs/SIGIL_INTEGRATION.md and docs/METRICS.md for the full picture.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .caps import caps
from .otel import init_otel, shutdown_otel
from .pricing import load_pricing
from .providers import ProviderRequest
from .router import RoutingError, select_provider, PROVIDER_MODULES
from .sigil_client import init_sigil, shutdown_sigil, get_sigil

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Order matters: OTel first, then Sigil, then load pricing
    init_otel()
    init_sigil()
    load_pricing()
    log.info("Gateway ready")
    yield
    # Shutdown in reverse order: Sigil first (so it flushes via OTel), then OTel
    shutdown_sigil()
    shutdown_otel()


app = FastAPI(title="llm-gateway", version=os.getenv("APP_VERSION", "0.1.0"), lifespan=lifespan)


# ── Health / readiness / metrics ──────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    return {"status": "ready", "providers": caps.snapshot()}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    # TODO: integrate prometheus_client and emit llm_gateway_* metrics
    return "# HELP llm_gateway_up 1 if gateway is up\nllm_gateway_up 1\n"


# ── /open — the loadgen coordination contract ─────────────────────────────────

@app.get("/open")
def open_state() -> dict[str, Any]:
    """Per-provider open/closed state. Loadgen polls this every ~5s.

    Returns:
        {
          "any_open": true,
          "providers": {
            "anthropic": {"open": true, "configured": true, "spent_usd_today": 5.20, "cap_usd": 20.0},
            "openai":    {"open": false, "configured": false, "reason": "not configured"},
            ...
          }
        }
    """
    snap = caps.snapshot()
    return {
        "any_open": any(p["open"] for p in snap.values()),
        "providers": snap,
    }


# ── /v1/llm — the core inference endpoint ─────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str | list[dict[str, Any]]


class LLMRequest(BaseModel):
    messages: list[Message]
    model: str | None = None  # gateway picks if absent
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float | None = None
    tools: list[dict[str, Any]] | None = None
    preferred_provider: str | None = None
    strict: bool = False  # if true and preferred_provider closed, return 503

    # Routing + Sigil metadata
    conversation_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    app: str | None = None
    agent_name: str | None = None
    agent_version: str | None = None
    parent_generation_ids: list[str] = Field(default_factory=list)


@app.post("/v1/llm")
async def generate(
    req: LLMRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    caller_type = (x_caller_type or "interactive").lower()
    if caller_type not in ("synthetic", "interactive"):
        caller_type = "interactive"

    # Pick provider
    try:
        provider_name = select_provider(
            caller_type=caller_type,
            preferred_provider=req.preferred_provider,
            strict=req.strict,
        )
    except RoutingError as e:
        # All providers closed (or strict + preferred closed) → 503
        raise HTTPException(status_code=503, detail=str(e))

    # Translate to ProviderRequest
    provider_module = PROVIDER_MODULES[provider_name]
    p_req = ProviderRequest(
        messages=[m.model_dump() for m in req.messages],
        model=req.model or "",  # provider applies its default if empty
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
        tools=req.tools,
        conversation_id=req.conversation_id,
        session_id=req.session_id,
        user_id=req.user_id,
        app=req.app,
        agent_name=req.agent_name,
        agent_version=req.agent_version,
        caller_type=caller_type,
        parent_generation_ids=req.parent_generation_ids,
    )

    sigil_client = get_sigil()
    resp = await provider_module.generate(p_req, sigil_client)

    # Record spend against the cap
    caps.record_spend(provider_name, resp.cost_usd, caller_type=caller_type)

    return {
        "content": resp.content,
        "provider": resp.provider,
        "model": resp.model,
        "usage": {
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "cache_read_input_tokens": resp.cache_read_input_tokens,
            "cache_creation_input_tokens": resp.cache_creation_input_tokens,
            "reasoning_tokens": resp.reasoning_tokens,
            "cost_usd": round(resp.cost_usd, 6),
        },
        "finish_reason": resp.finish_reason,
        "response_id": resp.response_id,
        "generation_id": resp.generation_id,
        "caller_type": caller_type,
    }

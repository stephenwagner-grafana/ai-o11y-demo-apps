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
from pydantic import BaseModel, ConfigDict, Field

from .caps import caps
from .otel import init_otel, shutdown_otel
from .pricing import load_pricing
from .providers import ProviderRequest
from .router import RoutingError, select_provider, PROVIDER_MODULES
from .sigil_client import init_sigil, shutdown_sigil, get_sigil


# When the primary provider raises (upstream 5xx, timeout, etc.) we attempt
# one fallback to another open provider before giving up. This keeps the demo
# story coherent — a flaky Ollama backend doesn't blank out the chatbot UX.
# Set FALLBACK_ON_PROVIDER_ERROR=0 to disable.
_FALLBACK_ENABLED = os.getenv("FALLBACK_ON_PROVIDER_ERROR", "1") != "0"

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
    # extra="allow" preserves Anthropic tool-call linkage fields that specialists
    # send on multi-turn conversations: `tool_call_id` on role=tool messages and
    # `tool_calls` on role=assistant messages. Default Pydantic behavior strips
    # unknown fields silently → providers/anthropic.py falls through to the
    # literal "toolu_unknown" tool_use_id → Anthropic 400s the request.
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] = ""


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
            sticky_key=f"{req.session_id or ''}|{req.conversation_id or ''}",
        )
    except RoutingError as e:
        # All providers closed (or strict + preferred closed) → 503
        raise HTTPException(status_code=503, detail=str(e))

    # Translate to ProviderRequest
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

    # Try the primary provider. Behavior on failure depends on caller_type:
    #   * synthetic (loadgen)  → no fallback; error propagates as 502.
    #     Lets the demo show REAL infrastructure failures on the error-rate
    #     panel — that's the AI o11y story we want to tell.
    #   * interactive (browser) → fallback to any other open provider once
    #     so a flaky upstream doesn't blank out the chatbot UX for a human
    #     watching the demo. Emits the llm_gateway_fallback_total metric
    #     so dashboards can still SEE the infra-level failures even when
    #     users got a 200.
    # Disable entirely via FALLBACK_ON_PROVIDER_ERROR=0; force-enable for
    # synthetic via FALLBACK_FOR_SYNTHETIC=1.
    tried: list[str] = [provider_name]
    primary_provider = provider_name
    last_error: Exception | None = None
    resp = None

    try:
        provider_module = PROVIDER_MODULES[provider_name]
        resp = await provider_module.generate(p_req, sigil_client)
    except Exception as e:  # noqa: BLE001 — broad on purpose, see below
        last_error = e
        log.warning("provider %s failed: %s", provider_name, e)

    _fallback_for_synthetic = os.getenv("FALLBACK_FOR_SYNTHETIC", "0") == "1"
    _allow_fallback = (
        resp is None
        and _FALLBACK_ENABLED
        and not (req.strict and req.preferred_provider)
        and (caller_type == "interactive" or _fallback_for_synthetic)
    )
    if _allow_fallback:
        for alt in [p for p in PROVIDER_MODULES if p not in tried and caps.is_open(p)[0]]:
            tried.append(alt)
            try:
                resp = await PROVIDER_MODULES[alt].generate(p_req, sigil_client)
                provider_name = alt  # for cap recording + response
                log.info("fallback succeeded on %s after %s failed", alt, tried[0])
                from .metrics import record_fallback
                record_fallback(
                    from_provider=primary_provider,
                    to_provider=alt,
                    caller_type=caller_type,
                )
                break
            except Exception as e:  # noqa: BLE001
                last_error = e
                log.warning("fallback %s also failed: %s", alt, e)

    if resp is None:
        # Re-raise as 502 so callers know it's upstream, not us. Preserve the
        # original error message so traces still show the root cause.
        raise HTTPException(
            status_code=502,
            detail=f"all providers failed (tried={tried}): {last_error}",
        ) from last_error

    # Record spend against the cap (whichever provider actually served the call)
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
        "tool_calls": resp.tool_calls,
        "finish_reason": resp.finish_reason,
        "response_id": resp.response_id,
        "generation_id": resp.generation_id,
        "caller_type": caller_type,
    }

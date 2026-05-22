"""Ollama provider — real implementation.

POSTs to {OLLAMA_BASE_URL}/api/chat using Ollama's native chat API.
Token counts come back as `prompt_eval_count` (input) and `eval_count`
(output). Tool-calling is supported by recent Ollama builds via the
`tools` request field.

Cost is computed via the static $/M-output-token rate from pricing.yaml
(see docs/METRICS.md — the GPU-power-derived formula is a deferred
extension).

Emits a Sigil generation event around every call. Same defensive pattern
as the Anthropic provider — if Sigil isn't configured or its API drifts,
the gateway logs a warning and keeps serving.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..pricing import calculate_cost
from .base import ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

PROVIDER_NAME = "ollama"
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "qwen2.5:14b")
DEFAULT_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
DEFAULT_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))


def _to_ollama_messages(messages: list[dict]) -> list[dict]:
    """OpenAI-style messages -> Ollama's `messages` shape.

    Ollama accepts {role, content} pairs natively. We handle a few
    edge cases: `tool` role becomes a `tool` message; `assistant` with
    tool_calls is flattened (Ollama returns tool_calls in its own
    response shape; for input we just pass through what we have).
    """
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, list):
            # Flatten list-of-dicts content to plain text (Anthropic-style content blocks).
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
            )
        out.append({"role": role, "content": str(content or "")})
    return out


def _to_ollama_tools(tools: list[dict] | None) -> list[dict] | None:
    """Map our specialist tool schemas (Anthropic-shaped) -> Ollama's tools shape.

    Ollama's `tools` field follows OpenAI's function-calling convention:
        {"type": "function", "function": {"name", "description", "parameters"}}
    """
    if not tools:
        return None
    out: list[dict] = []
    for t in tools:
        if "function" in t:
            # Already OpenAI shape — pass through.
            out.append(t)
            continue
        # Convert from Anthropic shape (used by our specialists' tools.py)
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", "unknown"),
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _parse_ollama_tool_calls(message: dict) -> list[dict]:
    """Extract tool_calls from Ollama's response message."""
    tcs = message.get("tool_calls") or []
    out: list[dict] = []
    for tc in tcs:
        fn = tc.get("function") or {}
        out.append({
            "id": tc.get("id") or f"toolu_{len(out):03d}",
            "name": fn.get("name"),
            "input": fn.get("arguments") or {},
        })
    return out


async def generate(req: ProviderRequest, sigil_client: Any) -> ProviderResponse:
    """Call Ollama's /api/chat. Emit Sigil generation. Return normalised response."""
    base_url = os.getenv("OLLAMA_BASE_URL")
    if not base_url:
        raise RuntimeError("OLLAMA_BASE_URL not set")

    model = req.model or DEFAULT_MODEL
    payload: dict[str, Any] = {
        "model": model,
        "messages": _to_ollama_messages(req.messages),
        "stream": False,
        "keep_alive": DEFAULT_KEEP_ALIVE,
        "options": {
            "num_ctx": DEFAULT_NUM_CTX,
            "num_predict": min(req.max_tokens or 1024, 2048),
        },
    }
    if req.temperature is not None:
        payload["options"]["temperature"] = req.temperature
    if req.top_p is not None:
        payload["options"]["top_p"] = req.top_p
    tools = _to_ollama_tools(req.tools)
    if tools is not None:
        payload["tools"] = tools

    # Start Sigil generation record
    rec = None
    if sigil_client is not None:
        try:
            rec = sigil_client.start_generation(
                agent_name=req.agent_name or "unknown-agent",
                agent_version=req.agent_version or "",
                conversation_id=req.conversation_id or "",
                parent_generation_ids=req.parent_generation_ids or [],
                tags={
                    "app": req.app or "",
                    "caller_type": req.caller_type or "",
                    "session_id": req.session_id or "",
                    "user_id": req.user_id or "",
                    "gen_ai.system": PROVIDER_NAME,
                },
            )
        except Exception:
            log.exception("sigil start_generation failed (continuing without Sigil)")
            rec = None

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.post(f"{base_url.rstrip('/')}/api/chat", json=payload)
            # Ollama returns 400 on "model does not support tools" — try once without tools
            if r.status_code == 400 and tools is not None and "does not support tools" in r.text.lower():
                log.info("model %s doesn't support tools; retrying without", model)
                payload_no_tools = {k: v for k, v in payload.items() if k != "tools"}
                r = await client.post(f"{base_url.rstrip('/')}/api/chat", json=payload_no_tools)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        if rec is not None:
            try:
                rec.set_result(error=str(e))
                rec.close()
            except Exception:
                log.exception("sigil error-set_result failed")
        raise

    message = data.get("message", {}) or {}
    content_text = message.get("content", "") or ""
    tool_calls = _parse_ollama_tool_calls(message)
    input_tokens = int(data.get("prompt_eval_count") or 0)
    output_tokens = int(data.get("eval_count") or 0)
    response_model = data.get("model") or model

    cost_usd = calculate_cost(PROVIDER_NAME, response_model, input_tokens, output_tokens)

    if rec is not None:
        try:
            rec.set_result(
                response_id=None,  # Ollama doesn't return a response id
                response_model=response_model,
                stop_reason=data.get("done_reason") or ("stop" if data.get("done") else None),
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )
            rec.close()
            if hasattr(rec, "err") and rec.err():
                log.warning("sigil generation rec.err(): %s", rec.err())
        except Exception:
            log.exception("sigil set_result/close failed")

    return ProviderResponse(
        content=content_text,
        model=response_model,
        provider=PROVIDER_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        finish_reason=data.get("done_reason"),
        response_id=None,
        generation_id=(getattr(rec, "generation_id", None) or getattr(rec, "id", None)) if rec is not None else None,
        tool_calls=tool_calls,
    )

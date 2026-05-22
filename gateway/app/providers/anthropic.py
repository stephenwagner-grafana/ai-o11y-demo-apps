"""Anthropic (Claude) provider — real implementation.

Calls api.anthropic.com via the official `anthropic` Python SDK.
Emits a Sigil generation event per call (start_generation / set_result /
close) following the documented pattern from the Sigil agent-first
instrumentation brief.

Phase 1 scope: non-streaming `messages.create()` only. Supports tool use
in both directions (sees tool_use response blocks; accepts tool_result
input blocks). Streaming and prompt-caching land later.

Message translation pulled from observibelity's battle-tested helper —
Anthropic rejects OpenAI-style `role: "tool"` messages and expects
`role: "user"` with a `tool_result` content block instead.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
from typing import Any

from anthropic import AsyncAnthropic

from ..pricing import calculate_cost
from .base import ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

PROVIDER_NAME = "anthropic"
DEFAULT_MODEL = os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-4-5-20251001")
# Hard cap on max_tokens to keep $/day predictable. Specialists send 1024 by
# default; this clamps the per-call ceiling. Tunable via env.
_MAX_TOKENS_CAP = int(os.getenv("ANTHROPIC_MAX_TOKENS_CAP", "1024"))


def _parse_model_weights(env_value: str) -> list[tuple[str, float]]:
    """Parse "model_a:weight_a,model_b:weight_b" env value.

    Weights normalized to sum to 1.0. Returns [] when unset/blank.
    """
    if not env_value or not env_value.strip():
        return []
    pairs: list[tuple[str, float]] = []
    for entry in env_value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            log.warning("ANTHROPIC_MODEL_WEIGHTS entry missing ':': %r", entry)
            continue
        model, w_str = entry.rsplit(":", 1)
        try:
            w = float(w_str)
        except ValueError:
            log.warning("ANTHROPIC_MODEL_WEIGHTS bad weight %r in %r", w_str, entry)
            continue
        if w <= 0:
            continue
        pairs.append((model.strip(), w))
    total = sum(w for _, w in pairs)
    if total <= 0:
        return []
    return [(m, w / total) for m, w in pairs]


_MODEL_WEIGHTS = _parse_model_weights(os.getenv("ANTHROPIC_MODEL_WEIGHTS", ""))
if _MODEL_WEIGHTS:
    log.info(
        "anthropic provider: weighted model pool: %s",
        ", ".join(f"{m}={w:.0%}" for m, w in _MODEL_WEIGHTS),
    )


def _pick_model(req: ProviderRequest) -> str:
    """Pick a model. Priority: explicit req.model -> weighted-sticky -> default.

    Sticky by session_id so a conversation stays on the same model — better
    user experience and cleaner per-model dashboard slices.
    """
    if req.model:
        return req.model
    if not _MODEL_WEIGHTS:
        return DEFAULT_MODEL
    # Sticky-per-session: deterministic mapping (session_id, hour bucket) -> model
    sticky_key = (req.session_id or "") + "|" + req.conversation_id or ""
    if sticky_key.strip("|"):
        # Map the key to a [0,1) value and walk the weight CDF
        h = int(hashlib.md5(sticky_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        cumulative = 0.0
        for model, w in _MODEL_WEIGHTS:
            cumulative += w
            if h < cumulative:
                return model
        return _MODEL_WEIGHTS[-1][0]
    # No session info — plain weighted random
    r = random.random()
    cumulative = 0.0
    for model, w in _MODEL_WEIGHTS:
        cumulative += w
        if r < cumulative:
            return model
    return _MODEL_WEIGHTS[-1][0]


def _to_anthropic_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """OpenAI-style messages -> (system, anthropic messages).

    Handles:
      - role=system -> pulled out into a separate `system` parameter
      - role=tool   -> rewritten as role=user with a tool_result content block
      - assistant with tool_calls -> expanded into tool_use content blocks
    """
    system_parts: list[str] = []
    anth_messages: list[dict] = []

    for msg in messages:
        role = msg.get("role")

        if role == "system":
            content = msg.get("content")
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(p.get("text", "") for p in content if isinstance(p, dict))
            continue

        if role == "tool":
            anth_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id") or msg.get("id") or "toolu_unknown",
                    "content": str(msg.get("content", "")),
                }],
            })
            continue

        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": str(msg["content"])})
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or "toolu_unknown",
                    "name": tc.get("name") or fn.get("name") or "unknown",
                    "input": tc.get("input") or tc.get("args") or fn.get("arguments") or {},
                })
            anth_messages.append({"role": "assistant", "content": blocks})
            continue

        anth_messages.append({"role": role, "content": msg.get("content", "")})

    system = "\n\n".join(s for s in system_parts if s) or None
    return system, anth_messages


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict] | None:
    """Normalize tool schemas to Anthropic shape.

    Accepts both our specialist tool schemas (already Anthropic-style with
    name/description/input_schema) AND OpenAI-style {type: function, function: ...}.
    """
    if not tools:
        return None
    out: list[dict] = []
    for t in tools:
        if "function" in t:
            fn = t["function"]
            out.append({
                "name": fn.get("name", "unknown"),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        else:
            out.append({
                "name": t.get("name"),
                "description": t.get("description", ""),
                "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
            })
    return out


def _parse_response(content_blocks: list[Any]) -> tuple[str, list[dict]]:
    """Extract text + tool_use blocks from Anthropic response content."""
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in content_blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": getattr(block, "id", None),
                "name": getattr(block, "name", None),
                "input": getattr(block, "input", {}),
            })
    return "\n".join(text_parts), tool_calls


async def generate(req: ProviderRequest, sigil_client: Any) -> ProviderResponse:
    """Call Claude. Emit Sigil generation event. Return normalised response."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    model = _pick_model(req)
    system, messages = _to_anthropic_messages(req.messages)
    tools = _to_anthropic_tools(req.tools)
    max_tokens = min(req.max_tokens or 1024, _MAX_TOKENS_CAP)

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if tools is not None:
        kwargs["tools"] = tools
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.top_p is not None:
        kwargs["top_p"] = req.top_p

    client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from env

    # Start a Sigil generation record — fire-and-forget if Sigil is misconfigured
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
        response = await client.messages.create(**kwargs)
    except Exception as e:
        # Best-effort error reporting to Sigil before re-raising
        if rec is not None:
            try:
                rec.set_result(error=str(e))
                rec.close()
            except Exception:
                log.exception("sigil error-set_result failed")
        raise

    content_text, tool_calls = _parse_response(response.content)
    usage = response.usage
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0

    cost_usd = calculate_cost(PROVIDER_NAME, response.model, input_tokens, output_tokens)

    if rec is not None:
        try:
            rec.set_result(
                response_id=response.id,
                response_model=response.model,
                stop_reason=response.stop_reason,
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_create,
                },
            )
            rec.close()
            if hasattr(rec, "err") and rec.err():
                log.warning("sigil generation rec.err(): %s", rec.err())
        except Exception:
            log.exception("sigil set_result/close failed")

    return ProviderResponse(
        content=content_text,
        model=response.model,
        provider=PROVIDER_NAME,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        cost_usd=cost_usd,
        finish_reason=response.stop_reason,
        response_id=response.id,
        generation_id=(getattr(rec, "generation_id", None) or getattr(rec, "id", None)) if rec is not None else None,
        tool_calls=tool_calls,
    )

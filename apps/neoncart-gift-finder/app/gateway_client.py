"""Shared helper: specialist -> LLM gateway round-trip with tool-call loop.

Encapsulates the multi-turn protocol every specialist follows:
  1. Send messages (+ tool schemas) to GATEWAY_URL/v1/llm
  2. Read response. If LLM returned tool_use blocks, execute each tool
     locally, append the results as role=tool messages, re-call
  3. Repeat until LLM stops calling tools (or MAX_TOOL_TURNS hit)
  4. Return the final assistant content + accumulated tool-call log

The X-Caller-Type header propagates through so the gateway can route
synthetic (loadgen) traffic via random-across-configured providers and
interactive (real human) traffic exclusively to Anthropic.

This file is duplicated (not symlinked) into each specialist's app/ dir
so the Dockerfile COPY works cleanly. If you change it, copy to all 5
specialist dirs.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://llm-gateway.llm-gateway.svc.cluster.local:8000")
MAX_TOOL_TURNS = int(os.getenv("MAX_TOOL_TURNS", "5"))
DEFAULT_TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "60"))


async def call_gateway(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    execute_tool_fn: Callable[[str, dict], dict] | None = None,
    agent_name: str,
    agent_version: str = "0.1.0",
    app: str = "",
    session_id: str = "",
    conversation_id: str = "",
    user_id: str = "",
    caller_type: str = "interactive",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    preferred_provider: str | None = None,
    parent_generation_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Round-trip with the gateway, executing any tool calls until done.

    Returns:
        {
          "content": str,         # final assistant text
          "tool_calls": list,     # log of every tool executed (for debug)
          "model": str | None,    # last model used
          "provider": str | None, # last provider used
          "usage": {"input_tokens", "output_tokens", "cost_usd"},
          "generation_ids": list, # Sigil generation IDs from each turn
          "finish_reason": str | None,
        }

    Raises httpx.HTTPError on transport / 5xx failures.
    """
    convo: list[dict] = list(messages)
    tool_log: list[dict] = []
    gen_ids: list[str] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    last_resp: dict[str, Any] = {}

    headers = {"X-Caller-Type": caller_type}

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for turn in range(MAX_TOOL_TURNS):
            body: dict[str, Any] = {
                "messages": convo,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "agent_name": agent_name,
                "agent_version": agent_version,
                "app": app,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "parent_generation_ids": parent_generation_ids or [],
            }
            if tools:
                body["tools"] = tools
            if preferred_provider:
                body["preferred_provider"] = preferred_provider

            r = await client.post(f"{GATEWAY_URL}/v1/llm", json=body, headers=headers)
            r.raise_for_status()
            last_resp = r.json()

            usage = last_resp.get("usage", {}) or {}
            total_usage["input_tokens"] += int(usage.get("input_tokens") or 0)
            total_usage["output_tokens"] += int(usage.get("output_tokens") or 0)
            total_usage["cost_usd"] += float(usage.get("cost_usd") or 0)
            if last_resp.get("generation_id"):
                gen_ids.append(last_resp["generation_id"])

            tool_calls = last_resp.get("tool_calls") or []
            if not tool_calls or execute_tool_fn is None:
                # No more tools to execute — return whatever the model wrote.
                return {
                    "content": last_resp.get("content", "") or "",
                    "tool_calls": tool_log,
                    "model": last_resp.get("model"),
                    "provider": last_resp.get("provider"),
                    "usage": total_usage,
                    "generation_ids": gen_ids,
                    "finish_reason": last_resp.get("finish_reason"),
                }

            # Append assistant turn (text + tool_calls) so the model can see what
            # it just said in the next round.
            convo.append({
                "role": "assistant",
                "content": last_resp.get("content", "") or "",
                "tool_calls": [
                    {"id": tc.get("id"), "name": tc.get("name"), "input": tc.get("input") or {}}
                    for tc in tool_calls
                ],
            })

            # Execute each tool locally and append role=tool messages.
            for tc in tool_calls:
                tool_name = tc.get("name") or "unknown"
                tool_input = tc.get("input") or {}
                try:
                    tool_result = execute_tool_fn(tool_name, tool_input)
                except Exception as e:
                    log.exception("tool %s failed", tool_name)
                    tool_result = {"error": str(e), "tool": tool_name}
                tool_log.append({"tool": tool_name, "input": tool_input, "result": tool_result})
                convo.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": str(tool_result),
                })

    log.warning("max tool turns (%d) hit for agent=%s", MAX_TOOL_TURNS, agent_name)
    return {
        "content": last_resp.get("content", "") or "",
        "tool_calls": tool_log,
        "model": last_resp.get("model"),
        "provider": last_resp.get("provider"),
        "usage": total_usage,
        "generation_ids": gen_ids,
        "finish_reason": "max_tool_turns_exceeded",
    }

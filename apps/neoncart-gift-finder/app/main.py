"""nc-gift-finder specialist — real implementation.

Receives /recommend requests with a gift prompt + optional budget,
calls the LLM gateway to pick the right tools (search_by_criteria,
add_to_cart) and synthesise a recommendation, returns the result.

Endpoints:
  POST /recommend  -> 3 gift recommendations with reasons
  GET  /tools      -> available tool schemas
  GET  /health     /readyz /metrics
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .gateway_client import call_gateway
from .tools import SCHEMAS, execute_tool

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="nc-gift-finder", version=os.getenv("APP_VERSION", "0.1.0"))

SYSTEM_PROMPT = """You are NeonCart's AI gift-finder. Given a description of a \
gift recipient and an optional budget, recommend 3 products from the NeonCart \
catalog with a one-sentence reason for each.

Use the search_by_criteria tool to find candidates (filter by category and budget).
After finding products, respond with a JSON list of 3 recommendations, each:
  {"sku": "...", "name": "...", "price_usd": N, "reason": "..."}

Be concise and thoughtful — these recommendations should feel personal."""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP nc_gift_finder_up 1 if up\nnc_gift_finder_up 1\n"


@app.get("/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": SCHEMAS}


class RecommendRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    budget_usd: float | None = None


@app.post("/recommend")
async def recommend(
    req: RecommendRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    caller_type = (x_caller_type or "interactive").lower()
    if caller_type not in ("synthetic", "interactive"):
        caller_type = "interactive"

    user_text = req.prompt
    if req.budget_usd is not None:
        user_text += f"\n\nBudget: ${req.budget_usd:.2f} max."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    try:
        result = await call_gateway(
            messages=messages,
            tools=SCHEMAS,
            execute_tool_fn=execute_tool,
            agent_name="nc-gift-finder",
            agent_version=os.getenv("APP_VERSION", "0.1.0"),
            app="neoncart",
            session_id=req.session_id or "",
            conversation_id=req.conversation_id or "",
            user_id=req.user_id or "",
            caller_type=caller_type,
        )
    except httpx.HTTPError as e:
        log.warning("gateway call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"gateway unreachable: {e}") from e

    return {
        "ok": True,
        "specialist": "nc-gift-finder",
        "model": result.get("model"),
        "provider": result.get("provider"),
        "usage": result.get("usage"),
        "tool_calls": result.get("tool_calls"),
        "reply": result["content"],
        "conversation_id": req.conversation_id or "conv_stub",
    }

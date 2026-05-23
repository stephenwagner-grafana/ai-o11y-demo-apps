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

from . import history
from .gateway_client import call_gateway
from .tools import SCHEMAS, execute_tool

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="nc-gift-finder", version=os.getenv("APP_VERSION", "0.1.0"))

SYSTEM_PROMPT = """Always respond in American English. Never switch to another language even if the prompt suggests it. You are NeonCart's AI gift-finder. Your job: produce 3 concrete \
gift recommendations IMMEDIATELY based on whatever the user told you. Do NOT ask \
clarifying questions.

RULES (in order):
1. ALWAYS call search_by_criteria FIRST to fetch real products from the catalog. \
Never invent SKUs — only recommend products returned by the tool.
2. ALWAYS return 3 recommendations on the very first turn. No "tell me more about \
the recipient" follow-ups.
3. For typical inputs (a budget, an occasion, a recipient hint, an interest, or \
any combination), make reasonable assumptions and just recommend. Examples:
   - "anniversary gift under $100" -> assume romantic partner, search for premium \
audio / smart-home / accessories under $100, pick 3.
   - "gift for my nephew" -> assume a kid/teen, search gaming + accessories, pick 3.
   - "birthday present for mom" -> assume adult woman, search smart-home / audio / \
wearables, pick 3.
4. ONLY ask one short follow-up question if the request is completely context-free, \
e.g. literally "just give me a gift" or "I need a gift" with zero other signal.
5. If search_by_criteria returns fewer than 3 matches, broaden the filters (drop \
category, raise budget slightly, try different keywords) and search again until \
you have 3 — don't fall back to asking the user.

OUTPUT FORMAT: a numbered list of 3 items, each one line:
  1. <Product Name> — ~$<price> — <one-sentence reason it fits>
  2. ...
  3. ...

Keep the intro to one short sentence ("Here are three picks under $100:"). No \
JSON, no clarifying questions, no "let me know if you'd like more info" filler."""


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

    conv_id = req.conversation_id or ""
    prior = history.get(conv_id)
    user_turn = {"role": "user", "content": user_text}
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *prior, user_turn]

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
    # Persist this turn so subsequent calls in the same conv see it.
    history.put(conv_id, [*prior, user_turn, {"role": "assistant", "content": result.get("content", "")}])


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

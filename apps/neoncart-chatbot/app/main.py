"""nc-chatbot specialist — real implementation.

Handles general chatbot conversations on NeonCart. Receives /chat
requests from nc-web, sends them to the LLM gateway with the tool
schemas from app/tools.py, executes any tool calls the LLM picks
locally, returns the final reply.

The "show me mice" demo trap lives in the `search_products` tool:
when the LLM uses that tool with a mouse/mice query, the tool tries
a Postgres query against a column that doesn't exist (`species`)
and the resulting error bubbles through the trace.

Endpoints:
  POST /chat       -> respond to a chatbot message
  GET  /tools      -> list available tool schemas
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

app = FastAPI(title="nc-chatbot", version=os.getenv("APP_VERSION", "0.1.0"))

SYSTEM_PROMPT = """You are NeonCart's helpful AI chatbot. NeonCart is a neon-themed \
e-commerce store selling premium tech (peripherals, displays, audio gear, gaming, \
smart home). Be friendly and concise. You have tools available:

- navigate_to_search: take the user to the search results page for a query
- search_products: search the catalog by free-text query and summarize results inline
- get_product_detail: look up a specific product by SKU
- navigate_to_page: tell the frontend to navigate (main/search/product/cart/checkout)
- add_to_cart: add a product to the user's cart

Tool-choice guidance:
- When the user asks "show me X" or "find X" (they want to browse), call \
navigate_to_search with query=X and reply with a short confirmation like \
"Taking you to X!". Do NOT also call search_products in that case.
- Only use search_products when the user wants you to summarize results inline \
(e.g. "what's the cheapest mouse?", "compare wireless keyboards", "any speakers \
under $50?") — i.e. they want an answer, not a page.

ANSWER FIRST. If the request has enough signal to act on (a product name, \
category, attribute, budget, or clear intent like "show me X" / "add Y to cart"), \
call the appropriate tool and answer directly. Only ask a clarifying question if \
the request is truly ambiguous (e.g. "help me" with no other context). Never \
bounce a reasonable request back as "could you tell me more?".

Always respond in 1-3 short sentences."""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP nc_chatbot_up 1 if up\nnc_chatbot_up 1\n"


@app.get("/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": SCHEMAS}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None


@app.post("/chat")
async def chat(
    req: ChatRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    msg = req.message or ""
    caller_type = (x_caller_type or "interactive").lower()
    if caller_type not in ("synthetic", "interactive"):
        caller_type = "interactive"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": msg},
    ]

    try:
        result = await call_gateway(
            messages=messages,
            tools=SCHEMAS,
            execute_tool_fn=execute_tool,
            agent_name="nc-chatbot",
            agent_version=os.getenv("APP_VERSION", "0.1.0"),
            app="neoncart",
            session_id=req.session_id or "",
            conversation_id=req.conversation_id or "",
            user_id=req.user_id or "",
            caller_type=caller_type,
        )
    except HTTPException:
        # Mice trap fired inside execute_tool — propagate the 500 unchanged
        raise
    except httpx.HTTPError as e:
        log.warning("gateway call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"gateway unreachable: {e}") from e

    return {
        "ok": True,
        "reply": result["content"],
        "specialist": "nc-chatbot",
        "model": result.get("model"),
        "provider": result.get("provider"),
        "usage": result.get("usage"),
        "tool_calls": result.get("tool_calls"),
        "conversation_id": req.conversation_id or "conv_stub",
    }

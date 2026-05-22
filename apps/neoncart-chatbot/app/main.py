"""nc-chatbot specialist.

Handles general chatbot conversations on NeonCart. Receives /chat
requests from nc-web, calls tools as needed, calls the LLM gateway,
returns a reply.

Tools available (see app/tools.py):
- search_products: searches the catalog (contains the "show me mice" trap)
- navigate_to_page: tells the frontend to navigate to main/search/product/cart/checkout

For Phase 1: the /chat handler invokes tools directly based on simple
keyword heuristics so traces and the mice trap behave correctly without
a real LLM call yet. In Phase 2 the LLM picks which tools to invoke.

Endpoints:
  POST /chat       -> respond to a chatbot message
  GET  /tools      -> list available tool schemas (debug aid)
  GET  /health     -> liveness
  GET  /readyz     -> readiness
  GET  /metrics    -> Prometheus metrics
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .tools import SCHEMAS, execute_tool

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="nc-chatbot", version=os.getenv("APP_VERSION", "0.1.0"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP nc_chatbot_up 1 if the chatbot specialist is up\nnc_chatbot_up 1\n"


@app.get("/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": SCHEMAS}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    msg = req.message or ""
    msg_lower = msg.lower()

    # ── Phase 1 heuristic tool dispatch ──────────────────────────────────────
    # Phase 2: the LLM (via gateway) picks the tool. For now we mimic that
    # decision with simple keyword matching so the trace shape is realistic
    # (chatbot -> tool -> downstream) even before the LLM is wired.
    tool_results: list[dict[str, Any]] = []

    # search_products — fires for searches, "show me X", and the mice trap
    if any(k in msg_lower for k in ("search", "show me", "find", "looking for", "mice", "mouse")):
        result = execute_tool("search_products", {"query": msg, "max_results": 3})
        tool_results.append({"tool": "search_products", "result": result})

    # navigate_to_page — fires for explicit navigation requests
    if "cart" in msg_lower and "show" in msg_lower:
        result = execute_tool("navigate_to_page", {"page": "cart"})
        tool_results.append({"tool": "navigate_to_page", "result": result})

    # ── Normal path — proxy to LLM gateway (stub for Phase 1) ────────────────
    # TODO Phase 2: call POST {GATEWAY_URL}/v1/llm with messages + the tools
    # array from SCHEMAS, then execute whatever tools the LLM picks.
    return {
        "ok": True,
        "reply": f"[stub] nc-chatbot will reply to {msg[:60]!r} via the gateway",
        "specialist": "nc-chatbot",
        "model": None,
        "conversation_id": req.conversation_id or "conv_stub",
        "tool_calls": tool_results,
    }

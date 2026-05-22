"""sb-billing — Acme support bot billing specialist.

Handles billing questions routed in by sb-router (charges, refunds,
invoices, payment methods). Will call the LLM gateway in Phase 2 to
generate real answers grounded in Acme's billing knowledge base.

Endpoints:
  POST /chat    -> answer a billing question
  GET  /health  -> liveness
  GET  /readyz  -> readiness
  GET  /metrics -> Prometheus
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

AGENT_NAME = "sb-billing"
DOMAIN = "billing"

app = FastAPI(title=AGENT_NAME, version=os.getenv("APP_VERSION", "0.1.0"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return f"# HELP {AGENT_NAME.replace('-', '_')}_up 1 if up\n{AGENT_NAME.replace('-', '_')}_up 1\n"


class ChatRequest(BaseModel):
    question: str
    role: str | None = None
    employee_email: str | None = None
    employee_name: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None


@app.get("/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": SCHEMAS}


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    log.info("%s answering: %r", AGENT_NAME, req.question[:80])
    tool_result = execute_tool("lookup_employee_expense", {"employee_email": req.employee_email or "anonymous@acme.com"})
    tool_calls = [{"tool": "lookup_employee_expense", "result": tool_result}]

    # TODO Phase 2: build a system prompt with billing-domain context
    # (recent invoices, payment methods, refund policy) and POST to
    # GATEWAY_URL/v1/llm with agent_name=sb-billing.
    return {
        "ok": True,
        "specialist": AGENT_NAME,
        "domain": DOMAIN,
        "reply": f"[stub] {AGENT_NAME} would answer billing questions via the LLM gateway. "
                 f"You asked: {req.question[:80]!r}",
        "model": None,
        "conversation_id": req.conversation_id or "conv_stub",
        "tool_calls": tool_calls,
    }

"""sb-account-management — Acme support bot account/profile specialist.

Handles account, password, profile, email-change, permissions, and role
questions routed in by sb-router. Phase 2 will call the LLM gateway with
relevant HR/IAM policy context for grounded answers.

Endpoints:
  POST /chat    -> answer an account-management question
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

AGENT_NAME = "sb-account-management"
DOMAIN = "account-management"

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
    tool_result = execute_tool("lookup_employee_profile", {"employee_email": req.employee_email or "anonymous@acme.com"})
    tool_calls = [{"tool": "lookup_employee_profile", "result": tool_result}]

    # TODO Phase 2: pull relevant policy/IAM context and POST to
    # GATEWAY_URL/v1/llm with agent_name=sb-account-management.
    return {
        "ok": True,
        "specialist": AGENT_NAME,
        "domain": DOMAIN,
        "reply": f"[stub] {AGENT_NAME} would answer account questions via the LLM gateway. "
                 f"You asked: {req.question[:80]!r}",
        "model": None,
        "conversation_id": req.conversation_id or "conv_stub",
        "tool_calls": tool_calls,
    }

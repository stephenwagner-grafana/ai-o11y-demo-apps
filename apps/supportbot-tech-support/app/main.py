"""sb-tech-support — Acme support bot tech specialist.

Handles IT / hardware / software / network questions routed in by
sb-router. Will call the LLM gateway in Phase 2 to generate answers
grounded in Acme's IT runbooks + knowledge base (the RAG store).

Endpoints:
  POST /chat    -> answer a tech-support question
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

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

AGENT_NAME = "sb-tech-support"
DOMAIN = "tech-support"

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


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    log.info("%s answering: %r", AGENT_NAME, req.question[:80])
    # TODO Phase 2: pull relevant runbooks from the RAG store
    # (pgvector inside the shared Postgres), build a system prompt,
    # POST to GATEWAY_URL/v1/llm with agent_name=sb-tech-support.
    return {
        "ok": True,
        "specialist": AGENT_NAME,
        "domain": DOMAIN,
        "reply": f"[stub] {AGENT_NAME} would answer tech questions via the LLM gateway. "
                 f"You asked: {req.question[:80]!r}",
        "model": None,
        "conversation_id": req.conversation_id or "conv_stub",
    }

"""SupportBot (Ask Acme) web frontend.

Phase 1 skeleton: serves the static HTML/CSS/JS lifted from
ai-o11y-demo-pack/src/supportbot/frontend/html/ and stubs the /api/ask
endpoint.

The static page has a hardcoded role/employee picker — the demo operator
("Wags Wagner" by default, override via DEMO_OPERATOR_NAME /
DEMO_OPERATOR_EMAIL env vars), and 7 role buckets with example
employees. The JS posts to /api/ask with the selected role + question;
this endpoint will eventually proxy to sb-router → domain specialists
via the LLM gateway.

Endpoints:
  GET  /            -> static index.html
  GET  /style.css   -> static stylesheet (referenced at root by index.html)
  GET  /app.js      -> static JS (referenced at root by index.html)
  GET  /health      -> liveness
  GET  /readyz      -> readiness
  GET  /metrics     -> Prometheus metrics
  POST /api/ask     -> ask SupportBot (stub)
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR.parent / "static"

app = FastAPI(title="supportbot-web", version=os.getenv("APP_VERSION", "0.1.0"))

# ── Health / readiness ────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}

@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP supportbot_web_up 1 if the web app is up\nsupportbot_web_up 1\n"

# ── Static assets at root paths (matching original nginx layout) ──────────────

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

@app.get("/style.css")
def style() -> FileResponse:
    return FileResponse(STATIC_DIR / "style.css", media_type="text/css")

@app.get("/app.js")
def appjs() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")

# ── Ask Acme (stub — real impl proxies to sb-router → specialists) ────────────

class AskRequest(BaseModel):
    question: str
    role: str | None = None
    employee_email: str | None = None
    employee_name: str | None = None
    conversation_id: str | None = None

@app.post("/api/ask")
def ask(req: AskRequest) -> dict[str, object]:
    return {
        "ok": True,
        "reply": f"[stub] sb-router not yet wired to llm-gateway. "
                 f"You asked: {req.question[:80]}",
        "specialist": "sb-router",
        "conversation_id": req.conversation_id or "conv_stub",
        "trace_id": None,  # populated by OTel later; UI uses for "view in Sigil" link
    }

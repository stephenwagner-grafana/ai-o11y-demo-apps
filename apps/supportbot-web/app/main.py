"""SupportBot (Ask Acme) web frontend.

Serves the static HTML/CSS/JS and forwards /api/ask to sb-router.
sb-router does LLM-driven classification then forwards to one of the
3 domain specialists; this app just relays headers and JSON.

Endpoints:
  GET  /          -> static index.html
  GET  /style.css -> static stylesheet
  GET  /app.js    -> static JS
  GET  /health    -> liveness
  GET  /readyz    -> readiness
  GET  /metrics   -> Prometheus metrics
  POST /api/ask   -> forwards to sb-router
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR.parent / "static"

SB_ROUTER_URL = os.getenv("SB_ROUTER_URL", "http://sb-router.support-bot.svc.cluster.local:8000")
ROUTER_TIMEOUT = float(os.getenv("ROUTER_TIMEOUT_SECONDS", "60"))

app = FastAPI(title="supportbot-web", version=os.getenv("APP_VERSION", "0.1.0"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP supportbot_web_up 1 if the web app is up\nsupportbot_web_up 1\n"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/style.css")
def style() -> FileResponse:
    return FileResponse(STATIC_DIR / "style.css", media_type="text/css")


@app.get("/app.js")
def appjs() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")


class AskRequest(BaseModel):
    question: str
    role: str | None = None
    employee_email: str | None = None
    employee_name: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None


def _caller_type(header_value: str | None) -> str:
    ct = (header_value or "interactive").lower()
    return ct if ct in ("synthetic", "interactive") else "interactive"


@app.post("/api/ask")
async def ask(
    req: AskRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    headers = {"X-Caller-Type": _caller_type(x_caller_type)}
    try:
        async with httpx.AsyncClient(timeout=ROUTER_TIMEOUT) as client:
            r = await client.post(f"{SB_ROUTER_URL}/ask", json=req.model_dump(), headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        log.warning("router returned %d: %s", e.response.status_code, e.response.text[:200])
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text) from e
    except httpx.HTTPError as e:
        log.warning("router unreachable: %s", e)
        raise HTTPException(status_code=502, detail=f"router unreachable: {e}") from e

    return data

"""nc-chatbot specialist.

Handles general chatbot conversations on NeonCart. Receives /chat
requests from nc-web, calls the LLM gateway, returns a reply.

Built-in demo: when the user message contains "mice" (case-insensitive),
the chatbot executes a Postgres query that references a column that
doesn't exist (`species`) — producing a real database error visible in
the OTel trace from browser → chatbot → postgres. This is the
"show me mice" cascade demo. It's intentional and always-on.

Endpoints:
  POST /chat       -> respond to a chatbot message
  GET  /health     -> liveness
  GET  /readyz     -> readiness
  GET  /metrics    -> Prometheus metrics
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="nc-chatbot", version=os.getenv("APP_VERSION", "0.1.0"))


def _postgres_dsn() -> str | None:
    """Build the Postgres DSN from env vars. Returns None if not configured."""
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None
    return (
        f"postgresql://{os.getenv('POSTGRES_USER', 'neoncart')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '')}@{host}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'neoncart')}"
    )


# ── Health / readiness / metrics ──────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP nc_chatbot_up 1 if the chatbot specialist is up\nnc_chatbot_up 1\n"


# ── /chat — the main entrypoint ───────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    msg = req.message or ""

    # ── Built-in "show me mice" trap ─────────────────────────────────────────
    # When the user mentions mice, the chatbot tries to filter the catalog
    # by `species`. That column doesn't exist in our schema, so Postgres
    # raises "column \"species\" does not exist". This error is INTENTIONAL
    # and demonstrates the "show me mice" cascade in the AI o11y demo —
    # browser → chatbot → postgres, all stitched in one trace.
    if "mice" in msg.lower():
        dsn = _postgres_dsn()
        if not dsn:
            # Postgres not yet wired in this env. Raise a representative error
            # so the demo still has something to show in traces.
            raise HTTPException(
                status_code=500,
                detail='database error: column "species" does not exist '
                       '(synthetic — POSTGRES_HOST not set; will be a real PG error once deployed)',
            )
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT sku, name, price_usd FROM products "
                    "WHERE species = %s LIMIT 10",  # <-- `species` column does not exist
                    ("mouse",),
                )
                _ = cur.fetchall()  # unreachable
        except psycopg.errors.UndefinedColumn as e:
            log.warning("show-me-mice trap fired: %s", e)
            raise HTTPException(status_code=500, detail=f'database error: {e}') from e
        except psycopg.Error as e:
            log.warning("show-me-mice trap raised generic PG error: %s", e)
            raise HTTPException(status_code=500, detail=f'database error: {e}') from e

    # ── Normal path — proxy to LLM gateway (stub for Phase 1) ────────────────
    # TODO Phase 2: call POST {GATEWAY_URL}/v1/llm with proper metadata
    # (agent_name=nc-chatbot, session_id, user_id, conversation_id, app=neoncart,
    # X-Caller-Type from the inbound header).
    return {
        "ok": True,
        "reply": f"[stub] nc-chatbot will reply to {msg[:60]!r} via the gateway",
        "specialist": "nc-chatbot",
        "model": None,  # populated once gateway integration lands
        "conversation_id": req.conversation_id or "conv_stub",
    }

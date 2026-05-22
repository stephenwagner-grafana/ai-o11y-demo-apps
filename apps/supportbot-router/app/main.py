"""sb-router specialist.

Receives a free-text question from supportbot-web, decides which domain
specialist should handle it (billing / tech-support / account-management /
unable-to-route), and forwards the question to that specialist. The
decision is captured as a Sigil **workflow step** so the AI o11y plugin
can show the execution graph in the UI.

For Phase 1: keyword-based routing (case-insensitive substring match).
Phase 2 will use an LLM call via the gateway for classification, with
proper Sigil workflow-step ingest.

Endpoints:
  POST /ask     -> classify + forward to domain specialist
  GET  /health  -> liveness
  GET  /readyz  -> readiness
  GET  /metrics -> Prometheus
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="sb-router", version=os.getenv("APP_VERSION", "0.1.0"))

# Per-domain target URLs (in-cluster Kubernetes services)
DOMAIN_URLS = {
    "billing": os.getenv("SB_BILLING_URL", "http://sb-billing.support-bot.svc.cluster.local:8000"),
    "tech-support": os.getenv("SB_TECH_SUPPORT_URL", "http://sb-tech-support.support-bot.svc.cluster.local:8000"),
    "account-management": os.getenv("SB_ACCOUNT_URL", "http://sb-account-management.support-bot.svc.cluster.local:8000"),
}

# Phase 1 keyword routing — case-insensitive substring match
ROUTING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "billing": ("bill", "charge", "invoice", "refund", "payment", "pay ", "receipt"),
    "tech-support": ("error", "broken", "not working", "doesn't work", "bug", "crash", "issue",
                     "fix", "help with", "trouble", "vpn", "wifi", "laptop", "computer"),
    "account-management": ("password", "login", "email change", "update my", "account", "profile",
                           "settings", "permission", "access", "role"),
}


def classify(question: str) -> str:
    """Return the domain key, or 'unable-to-route' if nothing matches."""
    q = question.lower()
    # Score each domain by number of keyword matches
    scores = {d: sum(1 for kw in kws if kw in q) for d, kws in ROUTING_KEYWORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "unable-to-route"
    return best


# ── Health / readiness / metrics ──────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP sb_router_up 1 if the router is up\nsb_router_up 1\n"


# ── /ask — classify and forward ───────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    role: str | None = None
    employee_email: str | None = None
    employee_name: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None


@app.post("/ask")
async def ask(req: AskRequest) -> dict[str, Any]:
    domain = classify(req.question)
    log.info("router decision: question=%r -> domain=%s", req.question[:60], domain)

    # TODO Phase 2: emit Sigil workflow step capturing input_state (question, role)
    # and output_state (chosen domain) with linked_generation_ids from any LLM
    # classification call.

    if domain == "unable-to-route":
        return {
            "ok": True,
            "specialist": "sb-router",
            "domain": "unable-to-route",
            "reply": "I can help with billing, tech support, or account questions. "
                     "Could you rephrase your question into one of those areas?",
            "conversation_id": req.conversation_id or "conv_stub",
        }

    url = DOMAIN_URLS[domain]
    payload = req.model_dump()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{url}/chat", json=payload)
            resp.raise_for_status()
            downstream = resp.json()
    except httpx.HTTPError as e:
        log.warning("downstream %s failed: %s", domain, e)
        raise HTTPException(status_code=502, detail=f"domain specialist {domain} unreachable: {e}")

    return {
        "ok": True,
        "specialist": "sb-router",
        "domain": domain,
        "reply": downstream.get("reply"),
        "downstream_specialist": downstream.get("specialist"),
        "model": downstream.get("model"),
        "conversation_id": req.conversation_id or downstream.get("conversation_id") or "conv_stub",
    }

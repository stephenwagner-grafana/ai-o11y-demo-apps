"""NeonCart web frontend.

Serves the static cyberpunk HTML/CSS/JS storefront and forwards AI
requests to the in-cluster specialists:

  /api/copilot/chat       -> nc-chatbot's /chat
  /api/ai/gift-finder     -> nc-gift-finder's /recommend
  /api/ai/<specialist>    -> generic forward to nc-<specialist>:8000/chat

The X-Caller-Type header (set by the central loadgen on synthetic
traffic) propagates through every forward so the LLM gateway can route
correctly. Real-human browser sessions don't set the header → treated
as `interactive` → gateway routes to Claude ungated.

Postgres-backed catalog endpoints (/api/products, /api/cart/*, etc.)
return stubs in Phase 1 — wiring them to real Postgres queries is a
follow-up step. Frontend renders without errors because the stubs have
the right JSON shape.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR.parent / "static"

NC_CHATBOT_URL = os.getenv("NC_CHATBOT_URL", "http://nc-chatbot.neoncart.svc.cluster.local:8000")
NC_GIFT_FINDER_URL = os.getenv("NC_GIFT_FINDER_URL", "http://nc-gift-finder.neoncart.svc.cluster.local:8000")
SPECIALIST_TIMEOUT = float(os.getenv("SPECIALIST_TIMEOUT_SECONDS", "60"))

app = FastAPI(title="neoncart-web", version=os.getenv("APP_VERSION", "0.1.0"))


# ── Health / readiness / metrics ──────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP neoncart_web_up 1 if the web app is up\nneoncart_web_up 1\n"


# ── Static frontend ───────────────────────────────────────────────────────────

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


# ── Product / cart endpoints (stubs — Postgres wiring is a follow-up) ─────────

@app.get("/api/products")
def list_products() -> dict[str, Any]:
    return {"products": []}


@app.get("/api/products/{sku}")
def get_product(sku: str) -> dict[str, Any]:
    raise HTTPException(status_code=404, detail=f"product {sku} not found")


@app.get("/api/search")
def search(q: str = "") -> dict[str, Any]:
    return {"query": q, "results": []}


@app.get("/api/recommendations/popular")
def popular() -> dict[str, Any]:
    return {"products": []}


@app.get("/api/cart/guest")
def get_cart() -> dict[str, Any]:
    return {"items": [], "total_usd": 0}


class CartAddRequest(BaseModel):
    sku: str
    quantity: int = 1
    source: str = "manual"


@app.post("/api/cart/add")
def add_to_cart(req: CartAddRequest) -> dict[str, Any]:
    return {"ok": True, "sku": req.sku}


class CartTrackRequest(BaseModel):
    event: str
    sku: str | None = None


@app.post("/api/cart/track")
def track_cart(req: CartTrackRequest) -> dict[str, Any]:
    return {"ok": True}


@app.delete("/api/cart/guest/{sku}")
def remove_from_cart(sku: str) -> dict[str, Any]:
    return {"ok": True, "removed": sku}


@app.delete("/api/cart/guest")
def clear_cart() -> dict[str, Any]:
    return {"ok": True}


class OrderRequest(BaseModel):
    items: list[dict[str, Any]] = []


@app.post("/api/orders")
def create_order(req: OrderRequest) -> dict[str, Any]:
    return {"ok": True, "order_id": "ord_stub", "items": req.items}


# ── AI specialist forwarding ──────────────────────────────────────────────────

async def _forward(url: str, payload: dict, caller_type: str) -> dict[str, Any]:
    """POST `payload` to `url` and return the JSON. Propagates X-Caller-Type."""
    headers = {"X-Caller-Type": caller_type}
    try:
        async with httpx.AsyncClient(timeout=SPECIALIST_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        # If the specialist returned a 5xx (e.g. the mice trap firing), surface
        # the body so traces show the upstream error, not a generic 502.
        log.warning("specialist returned %d: %s", e.response.status_code, e.response.text[:200])
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text) from e
    except httpx.HTTPError as e:
        log.warning("specialist unreachable: %s", e)
        raise HTTPException(status_code=502, detail=f"specialist unreachable: {e}") from e


def _caller_type(header_value: str | None) -> str:
    ct = (header_value or "interactive").lower()
    return ct if ct in ("synthetic", "interactive") else "interactive"


class SpecialistRequest(BaseModel):
    prompt: str | None = None
    context: str | None = None
    query: str | None = None
    budget_usd: float | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None


@app.post("/api/ai/gift-finder")
async def gift_finder(
    req: SpecialistRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    payload = {
        "prompt": req.prompt or req.query or "",
        "budget_usd": req.budget_usd,
        "session_id": req.session_id,
        "conversation_id": req.conversation_id,
        "user_id": req.user_id,
    }
    return await _forward(f"{NC_GIFT_FINDER_URL}/recommend", payload, _caller_type(x_caller_type))


@app.post("/api/ai/{specialist}")
async def call_specialist(
    specialist: str,
    req: SpecialistRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    # Generic forwarding for specialists named like "inventory-whisperer",
    # "search-rewriter", etc. — they're expected to be services in the
    # neoncart namespace listening on /chat. If a specialist isn't deployed
    # we return a stub response so the frontend doesn't crash.
    target = f"http://nc-{specialist}.neoncart.svc.cluster.local:8000/chat"
    payload = {
        "message": req.prompt or req.context or req.query or "",
        "session_id": req.session_id,
        "conversation_id": req.conversation_id,
        "user_id": req.user_id,
    }
    try:
        return await _forward(target, payload, _caller_type(x_caller_type))
    except HTTPException as e:
        if e.status_code == 502:
            # Specialist not deployed — return a friendly stub
            return {
                "ok": False,
                "specialist": specialist,
                "output": f"[{specialist} not deployed in this build]",
            }
        raise


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None


@app.post("/api/copilot/chat")
async def copilot_chat(
    req: ChatRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> dict[str, Any]:
    payload = {
        "message": req.message,
        "session_id": req.session_id,
        "conversation_id": req.conversation_id,
        "user_id": req.user_id,
    }
    return await _forward(f"{NC_CHATBOT_URL}/chat", payload, _caller_type(x_caller_type))


class ReportRequest(BaseModel):
    conversation_id: str
    feedback: str


@app.post("/api/copilot/report")
def report(req: ReportRequest) -> dict[str, Any]:
    return {"ok": True}


# ── Static assets (must come last so it doesn't shadow explicit routes) ──────

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

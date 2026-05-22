"""NeonCart web frontend.

Phase 1 skeleton: serves the static HTML/CSS/JS lifted from ai-o11y-demo-pack
and stubs the API endpoints the frontend JS expects. Real implementations
(Postgres-backed product catalog, specialist proxying, cart persistence)
land in subsequent phases.

Endpoints:
  GET  /                          -> static index.html (the storefront UI)
  GET  /health                    -> liveness
  GET  /readyz                    -> readiness
  GET  /metrics                   -> Prometheus metrics
  GET  /api/products              -> product catalog (stub)
  GET  /api/products/{sku}        -> product detail (stub)
  GET  /api/search?q=...          -> text search (stub)
  GET  /api/recommendations/popular -> trending rail (stub)
  GET  /api/cart/guest            -> current guest cart (stub)
  POST /api/cart/add              -> add item to cart (stub)
  POST /api/cart/track            -> cart activity tracking (stub)
  DELETE /api/cart/guest/{sku}    -> remove item (stub)
  DELETE /api/cart/guest          -> clear cart (stub)
  POST /api/orders                -> checkout (stub)
  POST /api/ai/{specialist}       -> proxy to LLM-backed specialist (stub)
  POST /api/copilot/chat          -> chatbot proxy (stub)
  POST /api/copilot/report        -> chatbot feedback (stub)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR.parent / "static"

app = FastAPI(title="neoncart-web", version=os.getenv("APP_VERSION", "0.1.0"))

# ── Health / readiness ────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/readyz")
def readyz() -> dict[str, str]:
    # TODO: ping postgres
    return {"status": "ready"}

@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    # TODO: wire up prometheus_client
    return "# HELP neoncart_web_up 1 if the web app is up\nneoncart_web_up 1\n"

# ── Static frontend ───────────────────────────────────────────────────────────

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

# ── Product catalog (stubs — real impl reads from postgres) ───────────────────

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

# ── Cart (stubs — real impl persists to postgres or session) ──────────────────

@app.get("/api/cart/guest")
def get_cart() -> dict[str, Any]:
    return {"items": [], "total_usd": 0}

class CartAddRequest(BaseModel):
    sku: str
    quantity: int = 1
    source: str = "manual"  # manual / ai_gift_finder / ai_chatbot

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

# ── Checkout (stub) ───────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    items: list[dict[str, Any]] = []

@app.post("/api/orders")
def create_order(req: OrderRequest) -> dict[str, Any]:
    return {"ok": True, "order_id": "ord_stub", "items": req.items}

# ── AI specialist proxies (stubs — real impl proxies to specialists) ──────────

class SpecialistRequest(BaseModel):
    prompt: str | None = None
    context: str | None = None
    query: str | None = None

@app.post("/api/ai/{specialist}")
def call_specialist(specialist: str, req: SpecialistRequest) -> dict[str, Any]:
    return {
        "ok": True,
        "specialist": specialist,
        "output": f"[stub] {specialist} not yet wired to llm-gateway",
    }

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

@app.post("/api/copilot/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    return {
        "ok": True,
        "reply": "[stub] nc-chatbot not yet wired to llm-gateway",
        "conversation_id": req.conversation_id or "conv_stub",
    }

class ReportRequest(BaseModel):
    conversation_id: str
    feedback: str

@app.post("/api/copilot/report")
def report(req: ReportRequest) -> dict[str, Any]:
    return {"ok": True}

# ── Static assets (must come last so it doesn't shadow the explicit routes) ──

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

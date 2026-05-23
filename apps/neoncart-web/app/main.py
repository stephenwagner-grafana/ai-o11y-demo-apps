"""NeonCart web frontend — Phase 2 with real Postgres-backed catalog + cart + orders.

Serves the static cyberpunk HTML/CSS/JS storefront. The AI-specialist
forwarding (nc-chatbot, nc-gift-finder) propagates X-Caller-Type so the
LLM gateway can route correctly. Catalog/cart/orders endpoints query
Postgres and emit Prom metrics from docs/METRICS.md.
"""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import metrics as m

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR.parent / "static"

NC_CHATBOT_URL = os.getenv("NC_CHATBOT_URL", "http://nc-chatbot.neoncart.svc.cluster.local:8000")
NC_GIFT_FINDER_URL = os.getenv("NC_GIFT_FINDER_URL", "http://nc-gift-finder.neoncart.svc.cluster.local:8000")
SPECIALIST_TIMEOUT = float(os.getenv("SPECIALIST_TIMEOUT_SECONDS", "60"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        await db.init_pool()
    except Exception:
        log.exception("Postgres pool init failed — catalog endpoints will 503")
    yield
    await db.close_pool()


app = FastAPI(title="neoncart-web", version=os.getenv("APP_VERSION", "0.1.0"), lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_session(nc_session_id: str | None, response: Response, user_domain: str) -> str:
    """Return existing session id from cookie, or create one (and set cookie)."""
    if nc_session_id:
        return nc_session_id
    sid = secrets.token_urlsafe(16)
    response.set_cookie("nc_session_id", sid, max_age=86400, samesite="lax")
    m.session_starts_total.labels(user_domain=user_domain).inc()
    return sid


def _caller_type(header_value: str | None) -> str:
    ct = (header_value or "interactive").lower()
    return ct if ct in ("synthetic", "interactive") else "interactive"


# ── Health / readiness ────────────────────────────────────────────────────────
#
# No /metrics endpoint: custom metrics now ride the OTLP push pipeline that
# opentelemetry-instrument sets up (see app/metrics.py). There is no
# Prometheus scrape configured for these pods.

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres pool not ready")
    return {"status": "ready"}


# ── Static frontend ───────────────────────────────────────────────────────────

@app.get("/")
def index(
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> FileResponse:
    # Ensure the visitor has a session cookie on first page view
    _ensure_session(nc_session_id, response, user_domain="unknown")
    m.page_views_total.labels(page="main", user_domain="unknown").inc()
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


# ── Product catalog (real Postgres queries) ───────────────────────────────────

@app.get("/api/products")
async def list_products(
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
    limit: int = 50,
    category_id: int | None = None,
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain="unknown")
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres not ready")
    if category_id is not None:
        rows = await db.fetch(
            "SELECT sku, name, description, price_usd, category_id, brand_id, image_url, stock_qty "
            "FROM products WHERE category_id = %s LIMIT %s",
            (category_id, max(1, min(limit, 100))),
        )
    else:
        rows = await db.fetch(
            "SELECT sku, name, description, price_usd, category_id, brand_id, image_url, stock_qty "
            "FROM products LIMIT %s",
            (max(1, min(limit, 100)),),
        )
    return {"products": rows, "session_id": sid}


@app.get("/api/products/{sku}")
async def get_product(
    sku: str,
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain="unknown")
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres not ready")
    row = await db.fetchone(
        "SELECT sku, name, description, price_usd, category_id, brand_id, image_url, stock_qty "
        "FROM products WHERE sku = %s",
        (sku,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"product {sku} not found")
    m.product_views_total.labels(product_sku=sku, user_domain="unknown").inc()
    return {**row, "session_id": sid}


@app.get("/api/search")
async def search(
    response: Response,
    q: str = "",
    limit: int = 20,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain="unknown")
    m.search_queries_total.labels(user_domain="unknown").inc()
    if not q.strip():
        return {"query": q, "results": [], "session_id": sid}
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres not ready")
    rows = await db.fetch(
        "SELECT sku, name, description, price_usd, category_id, brand_id, image_url "
        "FROM products WHERE name ILIKE %s OR description ILIKE %s LIMIT %s",
        (f"%{q}%", f"%{q}%", max(1, min(limit, 50))),
    )
    return {"query": q, "results": rows, "session_id": sid}


@app.get("/api/recommendations/popular")
async def popular(
    response: Response,
    limit: int = 8,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    _ensure_session(nc_session_id, response, user_domain="unknown")
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres not ready")
    # No real popularity signal yet — surface the highest-priced products as "trending".
    rows = await db.fetch(
        "SELECT sku, name, description, price_usd, category_id, brand_id, image_url "
        "FROM products ORDER BY price_usd DESC LIMIT %s",
        (max(1, min(limit, 20)),),
    )
    return {"products": rows}


# ── Cart (real Postgres-backed, session via cookie) ───────────────────────────

@app.get("/api/cart/guest")
async def get_cart(
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain="unknown")
    if not db.pool_ready():
        return {"items": [], "total_usd": 0, "session_id": sid}
    rows = await db.fetch(
        "SELECT c.sku, c.quantity, c.source, p.name, p.price_usd, p.image_url "
        "FROM carts c JOIN products p ON p.sku = c.sku "
        "WHERE c.session_id = %s ORDER BY c.added_at",
        (sid,),
    )
    total = sum(float(r["price_usd"] or 0) * int(r["quantity"] or 0) for r in rows)
    return {"items": rows, "total_usd": round(total, 2), "session_id": sid}


class CartAddRequest(BaseModel):
    sku: str
    quantity: int = 1
    source: str = "manual"  # manual | ai_gift_finder | ai_chatbot
    user_email: str | None = None


@app.post("/api/cart/add")
async def add_to_cart(
    req: CartAddRequest,
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain=m.domain_from_email(req.user_email))
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres not ready")
    # Upsert by (session_id, sku)
    await db.execute(
        "INSERT INTO carts (session_id, sku, quantity, source, user_id) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (session_id, sku) DO UPDATE SET "
        "quantity = carts.quantity + EXCLUDED.quantity, "
        "source   = EXCLUDED.source",
        (sid, req.sku, max(1, req.quantity), req.source, req.user_email),
    )
    m.add_to_cart_total.labels(
        product_sku=req.sku,
        source=req.source,
        user_domain=m.domain_from_email(req.user_email),
    ).inc()
    if req.source.startswith("ai_"):
        m.session_used_ai_total.labels(user_domain=m.domain_from_email(req.user_email)).inc()
    return {"ok": True, "sku": req.sku}


class CartTrackRequest(BaseModel):
    event: str
    sku: str | None = None


@app.post("/api/cart/track")
def track_cart(req: CartTrackRequest) -> dict[str, Any]:
    # Tracking-only stub — frontend uses this for impression/click telemetry.
    # We don't store these (use OTel spans for the same info).
    return {"ok": True}


@app.delete("/api/cart/guest/{sku}")
async def remove_from_cart(
    sku: str,
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain="unknown")
    if db.pool_ready():
        await db.execute("DELETE FROM carts WHERE session_id = %s AND sku = %s", (sid, sku))
    return {"ok": True, "removed": sku}


@app.delete("/api/cart/guest")
async def clear_cart(
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain="unknown")
    if db.pool_ready():
        await db.execute("DELETE FROM carts WHERE session_id = %s", (sid,))
    return {"ok": True}


# ── Checkout — real order row + revenue counter ───────────────────────────────

class OrderRequest(BaseModel):
    user_email: str | None = None
    items: list[dict[str, Any]] = []


@app.post("/api/orders")
async def create_order(
    req: OrderRequest,
    response: Response,
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    sid = _ensure_session(nc_session_id, response, user_domain=m.domain_from_email(req.user_email))
    if not db.pool_ready():
        raise HTTPException(status_code=503, detail="postgres not ready")

    rows = await db.fetch(
        "SELECT c.sku, c.quantity, c.source, p.price_usd "
        "FROM carts c JOIN products p ON p.sku = c.sku WHERE c.session_id = %s",
        (sid,),
    )
    if not rows:
        raise HTTPException(status_code=400, detail="cart is empty")

    total = sum(float(r["price_usd"] or 0) * int(r["quantity"] or 0) for r in rows)
    item_count = sum(int(r["quantity"] or 0) for r in rows)
    used_ai = any(str(r.get("source", "")).startswith("ai_") for r in rows)
    order_id = f"ord_{secrets.token_hex(8)}"

    await db.execute(
        "INSERT INTO orders (order_id, session_id, user_id, total_usd, item_count, used_ai) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (order_id, sid, req.user_email, round(total, 2), item_count, used_ai),
    )
    await db.execute("DELETE FROM carts WHERE session_id = %s", (sid,))

    user_domain = m.domain_from_email(req.user_email)
    m.transactions_total.labels(user_domain=user_domain).inc()
    m.revenue_usd_total.labels(user_domain=user_domain).inc(round(total, 2))
    return {"ok": True, "order_id": order_id, "total_usd": round(total, 2), "item_count": item_count, "used_ai": used_ai}


# ── AI specialist forwarding (unchanged from Phase 1) ─────────────────────────

async def _forward(url: str, payload: dict, caller_type: str) -> dict[str, Any]:
    headers = {"X-Caller-Type": caller_type}
    try:
        async with httpx.AsyncClient(timeout=SPECIALIST_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        log.warning("specialist returned %d: %s", e.response.status_code, e.response.text[:200])
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text) from e
    except httpx.HTTPError as e:
        log.warning("specialist unreachable: %s", e)
        raise HTTPException(status_code=502, detail=f"specialist unreachable: {e}") from e


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
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    payload = {
        "prompt": req.prompt or req.query or "",
        "budget_usd": req.budget_usd,
        "session_id": req.session_id or nc_session_id,
        "conversation_id": req.conversation_id,
        "user_id": req.user_id,
    }
    m.session_used_ai_total.labels(user_domain=m.domain_from_email(req.user_id)).inc()
    return await _forward(f"{NC_GIFT_FINDER_URL}/recommend", payload, _caller_type(x_caller_type))


@app.post("/api/ai/{specialist}")
async def call_specialist(
    specialist: str,
    req: SpecialistRequest,
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    target = f"http://nc-{specialist}.neoncart.svc.cluster.local:8000/chat"
    payload = {
        "message": req.prompt or req.context or req.query or "",
        "session_id": req.session_id or nc_session_id,
        "conversation_id": req.conversation_id,
        "user_id": req.user_id,
    }
    try:
        return await _forward(target, payload, _caller_type(x_caller_type))
    except HTTPException as e:
        if e.status_code == 502:
            return {"ok": False, "specialist": specialist, "output": f"[{specialist} not deployed in this build]"}
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
    nc_session_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    payload = {
        "message": req.message,
        "session_id": req.session_id or nc_session_id,
        "conversation_id": req.conversation_id,
        "user_id": req.user_id,
    }
    m.session_used_ai_total.labels(user_domain=m.domain_from_email(req.user_id)).inc()
    return await _forward(f"{NC_CHATBOT_URL}/chat", payload, _caller_type(x_caller_type))


class ReportRequest(BaseModel):
    conversation_id: str
    feedback: str


@app.post("/api/copilot/report")
def report(req: ReportRequest) -> dict[str, Any]:
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

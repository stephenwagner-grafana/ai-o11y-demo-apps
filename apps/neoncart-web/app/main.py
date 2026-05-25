"""NeonCart web frontend — Phase 2 with real Postgres-backed catalog + cart + orders.

Serves the static cyberpunk HTML/CSS/JS storefront. The AI-specialist
forwarding (nc-chatbot, nc-gift-finder) propagates X-Caller-Type so the
LLM gateway can route correctly. Catalog/cart/orders endpoints query
Postgres and emit Prom metrics from docs/METRICS.md.
"""
from __future__ import annotations

import logging
import os
import random
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import yaml
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

# Map DB category names → frontend category slugs used by static/index.html's
# HOME_CATEGORIES table. Anything not listed falls back to the slugified name.
_CATEGORY_SLUG_OVERRIDES = {
    "Smart Home": "smart-home",
    "Electronics": "ai-gear",
    "Computers": "components",
    "Mobile": "accessories",
    "Gaming": "peripherals",
    "Cables": "accessories",
}
# Emoji per frontend slug, kept in sync with HOME_CATEGORIES in index.html so
# the storefront cards have a glyph even for the categories that lack an
# image_url that resolves publicly.
_CATEGORY_EMOJI = {
    "peripherals": "⌨️", "displays": "🖥️", "audio": "🎧", "storage": "💾",
    "accessories": "🔌", "networking": "📡", "components": "🧩",
    "wearables": "⌚", "lighting": "💡", "ergonomics": "🧍",
    "smart-home": "🏠", "ai-gear": "🤖",
}
_PRODUCTS_SELECT = (
    "SELECT p.sku, p.name, p.description, p.price_usd, p.category_id, "
    "p.brand_id, p.image_url, p.stock_qty, c.name AS category_name "
    "FROM products p LEFT JOIN categories c ON c.id = p.category_id"
)


def _slug(s: str) -> str:
    return s.lower().replace(" ", "-")


def _enrich(row: dict[str, Any]) -> dict[str, Any]:
    """Map DB row → frontend product shape (id/price/category/rating/stock/emoji).

    The storefront JS expects `id`, `price` (number), `category` (slug string),
    `rating`, `stock`, `image_emoji`. The Postgres schema only carries `sku`,
    `price_usd` (string), `category_id`, `stock_qty`. We synthesize the rest
    deterministically from sku so a product's rating is stable across reloads.
    """
    sku = row.get("sku") or ""
    cat_name = row.get("category_name") or ""
    slug = _CATEGORY_SLUG_OVERRIDES.get(cat_name, _slug(cat_name) if cat_name else "")
    # Stable rating in 3.5–5.0 derived from sku.
    h = sum(ord(c) for c in sku) % 16
    rating = round(3.5 + h * 0.1, 1)
    try:
        price = float(row.get("price_usd") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return {
        **row,
        "id": sku,
        "product_id": sku,
        "price": price,
        "category": slug,
        "rating": rating,
        "stock": int(row.get("stock_qty") or 0),
        "image_emoji": _CATEGORY_EMOJI.get(slug, "📦"),
    }


# ── Synthetic user pool (mirrors loadgen) ───────────────────────────────────
# Loaded once at module import. Same users.yaml the loadgen reads, so a
# manual NeonCart session in the browser shows up in Sigil with the same
# email/cohort identity a synthetic VU would have.
_USERS_PATH = os.getenv("USERS_CONFIG_PATH", "/etc/neoncart/users.yaml")
_USER_POOL: list[dict[str, Any]] = []
try:
    _p = Path(_USERS_PATH)
    if _p.is_file():
        _doc = yaml.safe_load(_p.read_text()) or {}
        _USER_POOL = list(_doc.get("nc_users") or [])
        log.info("loaded %d nc_users from %s", len(_USER_POOL), _USERS_PATH)
except Exception as e:  # noqa: BLE001
    log.warning("could not load users from %s: %s", _USERS_PATH, e)


@app.get("/api/whoami")
async def whoami(
    response: Response,
    nc_user_id: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Identify the browser session as a random shopper from the loadgen pool.

    Sticky via the `nc_user_id` cookie: first hit picks a random user and
    sets the cookie; subsequent hits return the same user. If the pool is
    empty (users.yaml not generated), we fall back to a guest identity.
    """
    if _USER_POOL:
        chosen = None
        if nc_user_id:
            chosen = next((u for u in _USER_POOL if u.get("id") == nc_user_id), None)
        if chosen is None:
            chosen = random.choice(_USER_POOL)
            response.set_cookie(
                "nc_user_id", str(chosen.get("id")),
                max_age=60 * 60 * 24 * 30, httponly=False, samesite="lax",
            )
        return {
            "id": chosen.get("id"),
            "name": chosen.get("name"),
            "email": chosen.get("email"),
            "cohort": chosen.get("cohort"),
        }
    return {"id": "guest", "name": "Guest", "email": "guest@neoncart.local", "cohort": "non_ai"}


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
            f"{_PRODUCTS_SELECT} WHERE p.category_id = %s LIMIT %s",
            (category_id, max(1, min(limit, 100))),
        )
    else:
        rows = await db.fetch(
            f"{_PRODUCTS_SELECT} LIMIT %s",
            (max(1, min(limit, 100)),),
        )
    return {"products": [_enrich(r) for r in rows], "session_id": sid}


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
        f"{_PRODUCTS_SELECT} WHERE p.sku = %s",
        (sku,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"product {sku} not found")
    m.product_views_total.labels(product_sku=sku, user_domain="unknown").inc()
    return {**_enrich(row), "session_id": sid}


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
    # Loose plural handling: also match the singular form so "keyboards" finds
    # products named "Keyboard". Catalog names are mostly singular ("NeonTech
    # Glow Keyboard"), so a strict substring search on "keyboards" returns 0.
    qs = q.strip()
    q_stem = qs[:-1] if len(qs) > 3 and qs.lower().endswith("s") else qs
    pat1, pat2 = f"%{qs}%", f"%{q_stem}%"
    rows = await db.fetch(
        f"{_PRODUCTS_SELECT} WHERE p.name ILIKE %s OR p.description ILIKE %s "
        "OR p.name ILIKE %s OR p.description ILIKE %s LIMIT %s",
        (pat1, pat1, pat2, pat2, max(1, min(limit, 50))),
    )
    return {"query": q, "results": [_enrich(r) for r in rows], "session_id": sid}


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
        f"{_PRODUCTS_SELECT} ORDER BY p.price_usd DESC LIMIT %s",
        (max(1, min(limit, 20)),),
    )
    return {"products": [_enrich(r) for r in rows]}


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
    # Optional model attribution — populated by the loadgen / frontend when an
    # AI agent drove the ATC, so dashboards can answer "ATC per model"
    # (e.g., does claude-sonnet-4-6 convert better than qwen2.5:3b?).
    model: str | None = None


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
    model_label = req.model or "unknown"
    m.add_to_cart_total.labels(
        product_sku=req.sku,
        source=req.source,
        user_domain=m.domain_from_email(req.user_email),
        gen_ai_request_model=model_label,
    ).inc()
    if req.source.startswith("ai_"):
        m.session_used_ai_total.labels(user_domain=m.domain_from_email(req.user_email)).inc()
        # Look up the product's current price and attribute that value to the
        # agent that drove the ATC. Powers the "AI ROI" panel: cart-value /
        # llm-cost per agent. Falls back to zero if the price is missing.
        price_row = await db.fetchone(
            "SELECT price_usd FROM products WHERE sku = %s",
            (req.sku,),
        )
        price = float(price_row.get("price_usd") or 0) if price_row else 0.0
        if price > 0:
            agent = m.agent_from_source(req.source) or "unknown"
            m.ai_attributed_revenue_usd_total.labels(
                source=req.source,
                gen_ai_agent_name=agent,
                gen_ai_request_model=model_label,
            ).inc(price * max(1, req.quantity))
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

"""nc-chatbot tools.

Defines the tools nc-chatbot can invoke. In Phase 2 these will be
passed to the LLM gateway in the `tools` field of the request, and the
LLM picks which to call. In Phase 1 the /chat handler invokes them
directly based on simple keyword heuristics so traces still light up.

Each tool exposes:
- a JSON schema (for the LLM in Phase 2)
- a Python callable that executes it

The `search_products` tool is where the "show me mice" trap lives —
when the LLM asks it to filter by species="mouse" (or the query string
contains "mice"), the tool runs a Postgres query against a column that
doesn't exist. This is intentional. See README.md.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote_plus

import httpx
import psycopg
from fastapi import HTTPException

# postgres-db is the thin proxy service that owns all SQL for the chatbot.
# Going via it (instead of psycopg direct) gives the demo trace an extra
# visible hop: nc-chatbot -> postgres-db -> postgres, with the failing
# SQL captured in postgres-db's logs (Loki under service.name=postgres-db).
POSTGRES_DB_URL = os.getenv(
    "POSTGRES_DB_URL",
    "http://postgres-db.neoncart.svc.cluster.local:8000",
)

log = logging.getLogger(__name__)


# ── Tool: search_products ─────────────────────────────────────────────────────

SEARCH_PRODUCTS_SCHEMA = {
    "name": "search_products",
    "description": (
        "Search NeonCart's product catalog. Use when the user asks for products by name, "
        "category, attribute, or anything matchable via text. Returns up to `max_results` "
        "products with sku, name, price."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text product search query."},
            "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    },
}


def _postgres_dsn() -> str | None:
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None
    return (
        f"postgresql://{os.getenv('POSTGRES_USER', 'neoncart')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '')}@{host}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'neoncart')}"
    )


def search_products(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the catalog by calling postgres-db.

    All SQL execution (including the mice trap) lives in the postgres-db
    service — this just forwards. The trace cascade then reads:
      browser → neoncart-web → nc-chatbot → postgres-db → postgres
    with the postgres SELECT span and its db.statement appearing under
    service.name=postgres-db (matches the original AI o11y demo layout).
    """
    log.info("tool=search_products query=%r max_results=%d", query[:80], max_results)
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"{POSTGRES_DB_URL}/search",
                json={"query": query, "max_results": max_results},
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        # Surface the downstream postgres-db error unchanged so the chat
        # handler / gateway client can see and present it.
        log.warning("postgres-db returned %d: %s", e.response.status_code, e.response.text[:200])
        detail = e.response.text
        try:
            parsed = e.response.json()
            if isinstance(parsed, dict) and "detail" in parsed:
                detail = parsed["detail"]
        except (ValueError, TypeError):
            pass
        raise HTTPException(status_code=e.response.status_code, detail=detail) from e
    except httpx.HTTPError as e:
        log.warning("postgres-db unreachable: %s", e)
        raise HTTPException(status_code=502, detail=f"postgres-db unreachable: {e}") from e


# ── Tool: navigate_to_page ────────────────────────────────────────────────────

NAVIGATE_TO_PAGE_SCHEMA = {
    "name": "navigate_to_page",
    "description": (
        "Tell the NeonCart frontend to navigate to a specific page. Use when the user "
        "says \"show me X\", \"take me to my cart\", \"go to product page for SKU\", etc. "
        "The response includes a `navigate_to` field the frontend will act on."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "enum": ["main", "search", "product", "cart", "checkout"],
                "description": "The page to navigate to.",
            },
            "sku": {"type": "string", "description": "Required when page=product."},
            "query": {"type": "string", "description": "Required when page=search."},
        },
        "required": ["page"],
    },
}


def navigate_to_page(page: str, sku: str | None = None, query: str | None = None) -> dict[str, Any]:
    log.info("tool=navigate_to_page page=%s sku=%s query=%r", page, sku, (query or "")[:60])
    out: dict[str, Any] = {"ok": True, "navigate_to": page}
    if sku:
        out["sku"] = sku
    if query:
        out["query"] = query
    return out


# ── Registry ──────────────────────────────────────────────────────────────────

# ── Tool: get_product_detail ──────────────────────────────────────────────────

GET_PRODUCT_DETAIL_SCHEMA = {
    "name": "get_product_detail",
    "description": "Fetch full detail for a single product by SKU.",
    "input_schema": {
        "type": "object",
        "properties": {"sku": {"type": "string"}},
        "required": ["sku"],
    },
}


def get_product_detail(sku: str) -> dict[str, Any]:
    log.info("tool=get_product_detail sku=%s", sku)
    dsn = _postgres_dsn()
    if not dsn:
        return {"ok": True, "sku": sku, "name": f"Product {sku}", "description": "Demo product detail stub.",
                "price_usd": 99.00, "stock_qty": 12}
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT sku, name, description, price_usd, stock_qty "
                "FROM products WHERE sku = %s",
                (sku,),
            )
            r = cur.fetchone()
        if not r:
            return {"ok": False, "sku": sku, "error": "not found"}
        return {"ok": True, "sku": r[0], "name": r[1], "description": r[2],
                "price_usd": float(r[3] or 0), "stock_qty": int(r[4] or 0)}
    except psycopg.Error as e:
        log.warning("get_product_detail PG error: %s", e)
        return {"ok": False, "sku": sku, "error": str(e)}


# ── Tool: navigate_to_search ──────────────────────────────────────────────────

NAVIGATE_TO_SEARCH_SCHEMA = {
    "name": "navigate_to_search",
    "description": (
        "Take the user to NeonCart's search results page for a query. Prefer this "
        "tool when the user says \"show me X\", \"find X\", \"take me to X\" — i.e. "
        "they want to browse the search page, not have results summarized inline. "
        "Returns a URL the frontend can navigate to."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The product search query, e.g. \"bluetooth speakers\".",
            },
        },
        "required": ["query"],
    },
}


def navigate_to_search(query: str) -> dict[str, Any]:
    log.info("tool=navigate_to_search query=%r", query[:80])

    # Mice trap — the system prompt routes "show me X" to this tool, so
    # for "show me mice" we go through postgres-db too (one hop, returns
    # 500 with `column "species" does not exist`). Same trace cascade as
    # search_products: nc-chatbot → postgres-db → postgres → error.
    if "mice" in query.lower() or "mouse" in query.lower():
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(
                    f"{POSTGRES_DB_URL}/search",
                    json={"query": query, "max_results": 5},
                )
                r.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.warning("postgres-db returned %d for mice query: %s",
                        e.response.status_code, e.response.text[:200])
            detail = e.response.text
            try:
                parsed = e.response.json()
                if isinstance(parsed, dict) and "detail" in parsed:
                    detail = parsed["detail"]
            except (ValueError, TypeError):
                pass
            raise HTTPException(status_code=e.response.status_code, detail=detail) from e
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"postgres-db unreachable: {e}") from e

    url = f"/search?q={quote_plus(query)}"
    return {
        "ok": True,
        "url": url,
        "message": f"Navigating to search results for {query}",
    }


# ── Tool: add_to_cart ─────────────────────────────────────────────────────────

ADD_TO_CART_SCHEMA = {
    "name": "add_to_cart",
    "description": "Add a product (by SKU) to the user's cart. Returns the updated cart summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "quantity": {"type": "integer", "default": 1, "minimum": 1, "maximum": 99},
        },
        "required": ["sku"],
    },
}


def add_to_cart(sku: str, quantity: int = 1) -> dict[str, Any]:
    log.info("tool=add_to_cart sku=%s qty=%d", sku, quantity)
    return {"ok": True, "sku": sku, "quantity": quantity, "cart_size": quantity}


SCHEMAS = [
    SEARCH_PRODUCTS_SCHEMA,
    NAVIGATE_TO_SEARCH_SCHEMA,
    NAVIGATE_TO_PAGE_SCHEMA,
    GET_PRODUCT_DETAIL_SCHEMA,
    ADD_TO_CART_SCHEMA,
]

_DISPATCH = {
    "search_products": search_products,
    "navigate_to_search": navigate_to_search,
    "navigate_to_page": navigate_to_page,
    "get_product_detail": get_product_detail,
    "add_to_cart": add_to_cart,
}


def execute_tool(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call. Raises KeyError if the tool isn't defined."""
    fn = _DISPATCH[name]
    return fn(**inputs)

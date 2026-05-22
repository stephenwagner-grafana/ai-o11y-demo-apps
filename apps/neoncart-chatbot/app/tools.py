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

import psycopg
from fastapi import HTTPException

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
    """Search the catalog. Contains the 'show me mice' trap."""
    log.info("tool=search_products query=%r max_results=%d", query[:80], max_results)

    # ── Mice trap ─────────────────────────────────────────────────────────────
    # If the query mentions mice/mouse, the chatbot (or LLM) tries to filter
    # by `species` — a column that doesn't exist in our schema. Postgres
    # returns "column \"species\" does not exist". This is the signature
    # AI o11y demo moment: browser -> nc-chatbot -> search_products tool ->
    # postgres -> error, all in one trace.
    if "mice" in query.lower() or "mouse" in query.lower():
        dsn = _postgres_dsn()
        if not dsn:
            raise HTTPException(
                status_code=500,
                detail='database error: column "species" does not exist '
                       '(synthetic — POSTGRES_HOST not set; will be a real PG error once deployed)',
            )
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT sku, name, price_usd FROM products "
                    "WHERE species = %s LIMIT %s",  # <-- `species` column does not exist
                    ("mouse", max_results),
                )
                _ = cur.fetchall()
        except psycopg.errors.UndefinedColumn as e:
            log.warning("show-me-mice trap fired: %s", e)
            raise HTTPException(status_code=500, detail=f"database error: {e}") from e
        except psycopg.Error as e:
            log.warning("show-me-mice trap raised generic PG error: %s", e)
            raise HTTPException(status_code=500, detail=f"database error: {e}") from e

    # Normal path: real PG search (Phase 2 — wires to products table)
    # For Phase 1 return a stub list.
    return {
        "ok": True,
        "query": query,
        "results": [
            {"sku": "GMG-002", "name": "Voltura Stormcaster Mouse", "price_usd": 89.00},
            {"sku": "ACC-003", "name": "LumenWorks Aurora Desk Light", "price_usd": 65.00},
        ][:max_results],
    }


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
    # Phase 2: real Postgres lookup. Phase 1 returns a representative stub.
    return {
        "ok": True,
        "sku": sku,
        "name": f"Product {sku}",
        "description": "Demo product detail stub.",
        "price_usd": 99.00,
        "stock_qty": 12,
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


SCHEMAS = [SEARCH_PRODUCTS_SCHEMA, NAVIGATE_TO_PAGE_SCHEMA, GET_PRODUCT_DETAIL_SCHEMA, ADD_TO_CART_SCHEMA]

_DISPATCH = {
    "search_products": search_products,
    "navigate_to_page": navigate_to_page,
    "get_product_detail": get_product_detail,
    "add_to_cart": add_to_cart,
}


def execute_tool(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call. Raises KeyError if the tool isn't defined."""
    fn = _DISPATCH[name]
    return fn(**inputs)

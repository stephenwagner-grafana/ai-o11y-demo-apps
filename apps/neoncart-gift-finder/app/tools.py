"""nc-gift-finder tools.

Two tools: `search_by_criteria` (structured catalog filter) and
`add_to_cart`. Wires to the shared Postgres catalog; falls back to a
small in-memory pool if POSTGRES_HOST isn't set yet (dev mode).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import psycopg

log = logging.getLogger(__name__)


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


SEARCH_BY_CRITERIA_SCHEMA = {
    "name": "search_by_criteria",
    "description": (
        "Search NeonCart's catalog with structured filters. Useful when the user "
        "describes a recipient or budget. Returns up to `max_results` products."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "Category slug (e.g. gaming, audio)."},
            "max_budget_usd": {"type": "number", "minimum": 0},
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Free-text keywords describing the recipient or use case.",
            },
            "max_results": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
        },
    },
}


_STUB_RESULTS = [
    {"sku": "AUD-001", "name": "AstroByte Quantum Earbuds", "price_usd": 199.00, "category": "audio"},
    {"sku": "GMG-002", "name": "Voltura Stormcaster Mouse", "price_usd": 89.00, "category": "gaming"},
    {"sku": "ACC-003", "name": "LumenWorks Aurora Desk Light", "price_usd": 65.00, "category": "accessories"},
    {"sku": "WRB-004", "name": "Quantix Halo Smartwatch", "price_usd": 249.00, "category": "wearables"},
    {"sku": "SMH-005", "name": "Synthlex HomeHub Pro", "price_usd": 149.00, "category": "smart-home"},
]


def search_by_criteria(
    category: str | None = None,
    max_budget_usd: float | None = None,
    keywords: list[str] | None = None,
    max_results: int = 3,
) -> dict[str, Any]:
    log.info("tool=search_by_criteria category=%s budget=%s keywords=%s",
             category, max_budget_usd, keywords)

    # Demo gag — "mother" keyword expansion to "motherboard". A classic
    # overzealous-LLM-tool failure mode: someone shopping for their MOM
    # ends up looking at PC motherboards because a token expander treated
    # "mother" as a product-noun. Surfaces beautifully in Sigil because
    # the LLM's clean input ("gift for my mother") gets transformed into
    # an obviously wrong tool call (keywords=["motherboard"]).
    if keywords:
        _expanded: list[str] = []
        for kw in keywords:
            if isinstance(kw, str) and "mother" in kw.lower():
                _expanded.append("motherboard")
            else:
                _expanded.append(kw)
        if _expanded != keywords:
            log.info("search_by_criteria: 'mother' keyword expanded to 'motherboard'")
            keywords = _expanded

    dsn = _postgres_dsn()
    if not dsn:
        # Fallback for dev mode
        items = _STUB_RESULTS
        if category:
            items = [p for p in items if p["category"] == category]
        if max_budget_usd is not None:
            items = [p for p in items if p["price_usd"] <= max_budget_usd]
        return {"ok": True, "results": items[:max_results]}

    limit = max(1, min(max_results, 20))
    base_select = (
        "SELECT p.sku, p.name, p.description, p.price_usd, c.slug AS category "
        "FROM products p LEFT JOIN categories c ON c.id = p.category_id"
    )

    def _run(where_clauses: list[str], local_params: list[Any]) -> list[dict[str, Any]]:
        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        local_params.append(limit)
        with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(
                f"{base_select}{where_sql} ORDER BY p.price_usd DESC LIMIT %s",
                tuple(local_params),
            )
            return [
                {"sku": r[0], "name": r[1], "description": r[2],
                 "price_usd": float(r[3] or 0), "category": r[4]}
                for r in cur.fetchall()
            ]

    try:
        # Try 1: full filters (category AND keywords AND budget).
        where: list[str] = []
        params: list[Any] = []
        if category:
            where.append("LOWER(c.slug) = LOWER(%s)")
            params.append(category)
        if max_budget_usd is not None:
            where.append("p.price_usd <= %s")
            params.append(max_budget_usd)
        if keywords:
            kw_clauses: list[str] = []
            for kw in keywords:
                kw_clauses.append("(p.name ILIKE %s OR p.description ILIKE %s)")
                params.extend([f"%{kw}%", f"%{kw}%"])
            where.append("(" + " OR ".join(kw_clauses) + ")")
        rows = _run(where, params)

        # Try 2: drop keywords (LLMs often pass relational/personal words
        # like "dad", "birthday", "gift" that don't appear in the catalog).
        # Demo-critical: we MUST return SOMETHING so the gift-finder can
        # surface ATC-able SKUs; an empty result rate of >50% across journeys
        # silently kills the "AI ROI" and "ATC per model" dashboards.
        if not rows and keywords and (category or max_budget_usd is not None):
            log.info("search_by_criteria: 0 results with keywords, retrying without")
            relaxed_where: list[str] = []
            relaxed_params: list[Any] = []
            if category:
                relaxed_where.append("LOWER(c.slug) = LOWER(%s)")
                relaxed_params.append(category)
            if max_budget_usd is not None:
                relaxed_where.append("p.price_usd <= %s")
                relaxed_params.append(max_budget_usd)
            rows = _run(relaxed_where, relaxed_params)

        # Try 3: drop category too — fall back to budget-only / unfiltered.
        if not rows and category and max_budget_usd is not None:
            log.info("search_by_criteria: 0 results with category, retrying budget-only")
            rows = _run(["p.price_usd <= %s"], [max_budget_usd])

        # Try 4: nothing matched at all — return top-rated products as a
        # last resort so the gift-finder never goes empty-handed.
        if not rows:
            log.info("search_by_criteria: relaxing all filters, returning top products")
            rows = _run([], [])

        return {"ok": True, "results": rows}
    except psycopg.Error as e:
        log.warning("search_by_criteria PG error: %s", e)
        return {"ok": False, "results": [], "error": str(e)}


ADD_TO_CART_SCHEMA = {
    "name": "add_to_cart",
    "description": "Add a recommended product to the user's cart directly from the gift-finder.",
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
    log.info("tool=add_to_cart sku=%s qty=%d source=gift-finder", sku, quantity)
    return {"ok": True, "sku": sku, "quantity": quantity, "source": "ai_gift_finder"}


SCHEMAS = [SEARCH_BY_CRITERIA_SCHEMA, ADD_TO_CART_SCHEMA]

_DISPATCH = {"search_by_criteria": search_by_criteria, "add_to_cart": add_to_cart}


def execute_tool(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return _DISPATCH[name](**inputs)

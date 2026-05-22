"""nc-gift-finder tools.

One tool: `search_by_criteria` — searches the catalog with structured
filters (category, max-budget, keywords). Phase 1 returns stubs;
Phase 2 reads from Postgres.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


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
    items = _STUB_RESULTS
    if category:
        items = [p for p in items if p["category"] == category]
    if max_budget_usd is not None:
        items = [p for p in items if p["price_usd"] <= max_budget_usd]
    return {"ok": True, "results": items[:max_results]}


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

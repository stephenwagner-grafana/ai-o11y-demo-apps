"""Prometheus counters defined in docs/METRICS.md."""
from __future__ import annotations

from prometheus_client import Counter, Gauge

active_sessions = Gauge(
    "neoncart_active_sessions",
    "Current active browser sessions (rough — counts session_ids seen in the last N minutes).",
)

session_starts_total = Counter(
    "neoncart_session_starts_total",
    "New sessions created.",
    ["user_domain"],
)

page_views_total = Counter(
    "neoncart_page_views_total",
    "Page views.",
    ["page", "user_domain"],
)

search_queries_total = Counter(
    "neoncart_search_queries_total",
    "Text searches executed.",
    ["user_domain"],
)

product_views_total = Counter(
    "neoncart_product_views_total",
    "Single-product page hits.",
    ["product_sku", "user_domain"],
)

add_to_cart_total = Counter(
    "neoncart_add_to_cart_total",
    "Items added to cart. source ∈ {manual, ai_gift_finder, ai_chatbot}.",
    ["product_sku", "source", "user_domain"],
)

transactions_total = Counter(
    "neoncart_transactions_total",
    "Completed checkouts.",
    ["user_domain"],
)

revenue_usd_total = Counter(
    "neoncart_revenue_usd_total",
    "Transaction revenue in USD.",
    ["user_domain"],
)

session_used_ai_total = Counter(
    "neoncart_session_used_ai_total",
    "Sessions where the AI gift-finder or chatbot was invoked ≥1 time.",
    ["user_domain"],
)


def domain_from_email(email: str | None) -> str:
    """Extract the email domain for cohort labels. Returns 'unknown' if absent."""
    if not email or "@" not in email:
        return "unknown"
    return email.rsplit("@", 1)[1].lower()

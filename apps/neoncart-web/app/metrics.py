"""NeonCart custom application metrics (see docs/METRICS.md).

Ported from prometheus_client to the OpenTelemetry meter SDK so the
metrics ride the OTLP push pipeline that `opentelemetry-instrument` sets
up (which exports to Grafana Cloud Prom). There is no in-cluster
Prometheus scraping these pods, so a /metrics endpoint would be invisible.

Metric names and label keys are kept identical to the previous
prometheus_client definitions so existing dashboards keep working. The
OTLP-to-Prometheus exporter on the Grafana Cloud side preserves the
`_total` suffix on counters; we keep the suffix in the OTel name for
clarity.
"""
from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("neoncart-web")


# NOTE: An earlier observable gauge for `neoncart_active_sessions` was removed
# because it tripped the OTLP exporter's EncodingException on a NumberDataPoint
# with a degenerate Exemplar (filtered_attributes=None). One bad metric in
# the batch poisoned the whole export and prevented EVERY metric from this
# pod from reaching Grafana Cloud. If we want active-session tracking later,
# track it as an UpDownCounter that we increment/decrement on session start
# / session end rather than an observable gauge with a no-op callback.


# ── Counters ─────────────────────────────────────────────────────────────────
#
# Each counter wraps the OTel meter counter with a tiny shim that exposes a
# `.labels(**kwargs).inc(value=1)` API matching the prometheus_client surface
# that call sites in main.py already use. This keeps the diff at the call
# sites minimal.

class _LabeledCounter:
    def __init__(self, name: str, description: str):
        self._counter = _meter.create_counter(name, description=description)
        self._name = name

    def labels(self, **kwargs: str) -> "_BoundCounter":
        return _BoundCounter(self._counter, kwargs)


class _BoundCounter:
    __slots__ = ("_counter", "_attrs")

    def __init__(self, counter, attrs: dict[str, str]):
        self._counter = counter
        self._attrs = attrs

    def inc(self, value: float = 1) -> None:
        self._counter.add(value, attributes=self._attrs)


session_starts_total = _LabeledCounter(
    "neoncart_session_starts_total",
    "New sessions created.",
)

page_views_total = _LabeledCounter(
    "neoncart_page_views_total",
    "Page views.",
)

search_queries_total = _LabeledCounter(
    "neoncart_search_queries_total",
    "Text searches executed.",
)

product_views_total = _LabeledCounter(
    "neoncart_product_views_total",
    "Single-product page hits.",
)

add_to_cart_total = _LabeledCounter(
    "neoncart_add_to_cart_total",
    "Items added to cart. source in {manual, ai_gift_finder, ai_chatbot}.",
)

transactions_total = _LabeledCounter(
    "neoncart_transactions_total",
    "Completed checkouts.",
)

revenue_usd_total = _LabeledCounter(
    "neoncart_revenue_usd_total",
    "Transaction revenue in USD.",
)

session_used_ai_total = _LabeledCounter(
    "neoncart_session_used_ai_total",
    "Sessions where the AI gift-finder or chatbot was invoked >= 1 time.",
)

# AI-attributed revenue: incremented by product price whenever an add-to-cart
# event fires with source != "manual". Labels: source (ai_chatbot|ai_gift_finder)
# and gen_ai_agent_name (nc-chatbot|nc-gift-finder) so this can be ratio'd
# against gen_ai_client_cost_usd_total{gen_ai_agent_name=X} for the
# "is the AI agent paying for itself?" KPI. Ratio > 1.0 means the agent
# generated more cart value than it cost in LLM tokens.
ai_attributed_revenue_usd_total = _LabeledCounter(
    "neoncart_ai_attributed_revenue_usd_total",
    "Cart-value (product price at time of ATC) attributed to AI-initiated adds. "
    "Ratio'd against gen_ai_client_cost_usd_total to compute per-agent ROI.",
)


# Map ATC source → Sigil agent name so the metric joins cleanly against
# gen_ai_*{gen_ai_agent_name=X}.
_SOURCE_TO_AGENT = {
    "ai_chatbot": "nc-chatbot",
    "ai_gift_finder": "nc-gift-finder",
}


def agent_from_source(source: str) -> str:
    """Map ATC source value → Sigil agent name. Empty string for manual ATCs."""
    return _SOURCE_TO_AGENT.get(source, "")


def domain_from_email(email: str | None) -> str:
    """Extract the email domain for cohort labels. Returns 'unknown' if absent."""
    if not email or "@" not in email:
        return "unknown"
    return email.rsplit("@", 1)[1].lower()

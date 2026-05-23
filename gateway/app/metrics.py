"""Gateway-owned OTel metrics — currently just per-call cost.

Sigil's sigil-sdk emits gen_ai_client_operation_duration_seconds,
gen_ai_client_token_usage, etc. automatically. But it does NOT emit a
cost counter (cost is computed server-side by Sigil and surfaced only in
its Analytics UI). For Prom-queryable cost dashboards on Grafana Cloud
we need to emit it ourselves.

Naming follows OTel GenAI semantic conventions; OTLP-to-Prom mapping
appends `_total` to the Sum, yielding `gen_ai_client_cost_usd_total`.
"""
from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter(__name__)

# Cumulative spend by provider / model / agent. Attribute keys mirror what
# sigil-sdk uses on its own metrics so cost can be joined with duration +
# token-usage in the same dashboard query.
cost_usd_counter = _meter.create_counter(
    name="gen_ai.client.cost.usd",
    # No `unit=...` here. Setting unit="USD" causes the OTLP→Prom mapping to
    # append the unit to the metric name, producing the awkward double-suffix
    # `gen_ai_client_cost_usd_USD_total` in Prom. Without unit, we get the
    # clean `gen_ai_client_cost_usd_total`.
    description="Cumulative LLM API spend in USD per provider/model/agent.",
)


def record_cost(*, provider: str, model: str, agent_name: str, cost_usd: float) -> None:
    """Record one LLM call's cost. No-ops on zero/negative values."""
    if cost_usd is None or cost_usd <= 0:
        return
    cost_usd_counter.add(
        cost_usd,
        attributes={
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.agent.name": agent_name,
        },
    )

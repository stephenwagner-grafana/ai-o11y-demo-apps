"""Pricing data + cost calculation.

Sigil owns canonical pricing data but does not (yet) emit it as a Prom
metric or expose a public pricing endpoint. So the gateway maintains a
small `pricing.yaml` mirror and computes `gen_ai.client.cost.usd` itself.

When Sigil ships a public cost metric or pricing endpoint, this module
can be replaced with a thin Sigil client and pricing.yaml deleted.

See docs/SIGIL_INTEGRATION.md for the long story.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

DEFAULT_PRICING_PATH = Path(__file__).resolve().parent.parent / "config" / "pricing.yaml"

_pricing: dict[str, dict[str, dict[str, float]]] = {}


def load_pricing(path: Path | None = None) -> dict[str, dict[str, dict[str, float]]]:
    """Load pricing.yaml. Env-var overrides applied on top.

    Returns a nested dict: {provider: {model: {input_usd_per_mtoken, output_usd_per_mtoken}}}.
    """
    global _pricing
    p = path or DEFAULT_PRICING_PATH
    if not p.exists():
        log.warning("pricing.yaml not found at %s — costs will be 0", p)
        _pricing = {}
        return _pricing

    with p.open() as f:
        _pricing = yaml.safe_load(f) or {}

    # Env-var overrides for negotiated discounts
    # e.g. ANTHROPIC_SONNET_OUTPUT_USD_PER_MTOKEN=15.00
    _apply_env_overrides()

    log.info("Loaded pricing for %d providers", len(_pricing))
    return _pricing


def _apply_env_overrides() -> None:
    """Look for env vars like <PROVIDER>_<MODEL>_{INPUT,OUTPUT}_USD_PER_MTOKEN and apply them."""
    for env_key, env_val in os.environ.items():
        if not env_key.endswith("_USD_PER_MTOKEN"):
            continue
        # Parse: ANTHROPIC_SONNET_OUTPUT_USD_PER_MTOKEN -> provider=anthropic, model_key=sonnet, kind=output
        # This is intentionally fuzzy — model_key matches against the YAML's model name slug
        try:
            tail = env_key[:-len("_USD_PER_MTOKEN")]
            parts = tail.lower().split("_")
            if len(parts) < 3:
                continue
            provider, *middle, kind = parts
            if kind not in ("input", "output"):
                continue
            model_key = "_".join(middle)
            rate = float(env_val)
            # Find the matching model in the loaded pricing
            for model_name, rates in _pricing.get(provider, {}).items():
                if model_key in model_name.lower().replace("-", "_"):
                    rates[f"{kind}_usd_per_mtoken"] = rate
                    log.info("Pricing override: %s/%s %s = $%.4f/Mtok", provider, model_name, kind, rate)
        except (ValueError, KeyError) as e:
            log.warning("Could not parse pricing override env %s=%s: %s", env_key, env_val, e)


def calculate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return cost in USD for a single LLM call.

    All providers (cloud + Ollama): input_tokens × input_rate + output_tokens × output_rate.
    Ollama rates model all-in compute cost (electricity + GPU amortization).
    Every call with non-zero tokens produces a non-zero cost so dashboards
    populate for every message.
    Returns 0 if pricing is unknown.
    """
    rates = _pricing.get(provider, {}).get(model)
    if rates is None:
        # Try longest-prefix match: Anthropic returns dated forms like
        # "claude-opus-4-1-20250805" but pricing.yaml may only list the
        # undated "claude-opus-4-1". Walk all keys, find the longest one
        # that is a prefix of the requested model. This also handles new
        # snapshot dates without needing to update pricing.yaml.
        provider_rates = _pricing.get(provider, {})
        best_match = ""
        for known in provider_rates:
            if model.startswith(known) and len(known) > len(best_match):
                best_match = known
        if best_match:
            rates = provider_rates[best_match]
    if rates is None:
        # Try a wildcard / default model entry
        rates = _pricing.get(provider, {}).get("default")
    if rates is None:
        log.warning("No pricing for %s/%s — cost = 0", provider, model)
        return 0.0

    input_rate = rates.get("input_usd_per_mtoken", 0.0)
    output_rate = rates.get("output_usd_per_mtoken", 0.0)
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

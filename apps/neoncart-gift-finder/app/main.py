"""nc-gift-finder specialist.

Takes a gift-search prompt ("birthday gift for my dad who likes gaming,
budget $200") and returns 3 product recommendations with explanations.

For Phase 1: returns 3 random products from a small in-memory pool as a
stub. Phase 2 will call the LLM gateway to generate real recommendations
based on the catalog in Postgres.
"""
from __future__ import annotations

import logging
import os
import random
from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="nc-gift-finder", version=os.getenv("APP_VERSION", "0.1.0"))


# Tiny in-memory stub pool — replace with Postgres + gateway in Phase 2
_STUB_RECS = [
    {"sku": "AUD-001", "name": "AstroByte Quantum Earbuds", "price_usd": 199.00,
     "reason": "Premium wireless audio — universal gift, looks great."},
    {"sku": "GMG-002", "name": "Voltura Stormcaster Mouse", "price_usd": 89.00,
     "reason": "Loved by gamers; under $100 puts it in birthday-gift range."},
    {"sku": "ACC-003", "name": "LumenWorks Aurora Desk Light", "price_usd": 65.00,
     "reason": "Mood lighting upgrade; works for almost any desk setup."},
    {"sku": "WRB-004", "name": "Quantix Halo Smartwatch", "price_usd": 249.00,
     "reason": "Fitness + notifications; flagship-feeling without flagship price."},
    {"sku": "SMH-005", "name": "Synthlex HomeHub Pro", "price_usd": 149.00,
     "reason": "Voice-controlled hub — gateway gift for smart-home curious."},
]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP nc_gift_finder_up 1 if the gift-finder specialist is up\nnc_gift_finder_up 1\n"


class RecommendRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    budget_usd: float | None = None


@app.post("/recommend")
def recommend(req: RecommendRequest) -> dict[str, Any]:
    """Return 3 gift recommendations for the given prompt.

    Phase 1: random pick from a static pool with canned reasons.
    Phase 2: call llm-gateway → Anthropic, ask for 3 SKUs from the
    Postgres catalog, with personalised explanations.
    """
    # TODO Phase 2: build a system prompt with the catalog snapshot +
    # send to GATEWAY_URL/v1/llm with agent_name=nc-gift-finder.
    log.info("recommend prompt=%r budget=%s user=%s", req.prompt[:80], req.budget_usd, req.user_id)

    picks = random.sample(_STUB_RECS, k=min(3, len(_STUB_RECS)))
    return {
        "ok": True,
        "specialist": "nc-gift-finder",
        "model": None,  # populated once gateway integration lands
        "recommendations": picks,
        "conversation_id": req.conversation_id or "conv_stub",
    }

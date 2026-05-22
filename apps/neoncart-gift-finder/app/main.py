"""nc-gift-finder specialist.

Takes a gift-search prompt + optional budget, returns 3 recommendations.
Uses the `search_by_criteria` tool (see app/tools.py).

Endpoints:
  POST /recommend  -> 3 gift recommendations
  GET  /tools      -> available tool schemas
  GET  /health     /readyz /metrics
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .tools import SCHEMAS, execute_tool

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="nc-gift-finder", version=os.getenv("APP_VERSION", "0.1.0"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "# HELP nc_gift_finder_up 1 if up\nnc_gift_finder_up 1\n"


@app.get("/tools")
def list_tools() -> dict[str, Any]:
    return {"tools": SCHEMAS}


class RecommendRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    budget_usd: float | None = None


@app.post("/recommend")
def recommend(req: RecommendRequest) -> dict[str, Any]:
    """Return 3 gift recommendations.

    Phase 1: call the search_by_criteria tool directly with the budget;
    Phase 2: the LLM picks tools and synthesises explanations.
    """
    log.info("recommend prompt=%r budget=%s", req.prompt[:80], req.budget_usd)
    tool_result = execute_tool(
        "search_by_criteria",
        {"max_budget_usd": req.budget_usd, "max_results": 3},
    )
    return {
        "ok": True,
        "specialist": "nc-gift-finder",
        "model": None,
        "recommendations": tool_result["results"],
        "conversation_id": req.conversation_id or "conv_stub",
        "tool_calls": [{"tool": "search_by_criteria", "result": tool_result}],
    }

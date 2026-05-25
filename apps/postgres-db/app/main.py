"""postgres-db — thin HTTP proxy over the shared NeonCart postgres.

Exists so the trace cascade has a visible hop between nc-chatbot and
postgres (matches the original AI o11y demo's `search-service` shape).
nc-chatbot calls this service over HTTP; this service runs the SQL.

The "show me mice" trap is staged here too: when query contains
"mice"/"mouse" the service runs a deliberately broken `SELECT ...
WHERE species = ...` (no such column). The OTel psycopg instrumentation
emits a child span with status=error + the SQL in db.statement, and we
log the same on stdout so the failure shows up in Loki under
service.name=postgres-db.

Endpoints:
  POST /search  -> run a product search; returns rows or 500 on PG error
  GET  /health  /readyz
"""
from __future__ import annotations

import logging
import os
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="postgres-db", version=os.getenv("APP_VERSION", "0.1.0"))


def _postgres_dsn() -> str | None:
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None
    return (
        f"host={host} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'aio11y')} "
        f"user={os.getenv('POSTGRES_USER', 'aio11y')} "
        f"password={os.getenv('POSTGRES_PASSWORD', '')}"
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready"}


class SearchRequest(BaseModel):
    query: str
    max_results: int = 5


@app.post("/search")
def search(req: SearchRequest) -> dict[str, Any]:
    query = (req.query or "").strip()
    limit = max(1, min(req.max_results, 50))
    log.info("postgres-db search query=%r limit=%d", query[:80], limit)

    dsn = _postgres_dsn()
    if not dsn:
        # Stub mode for dev — still simulate the mice trap so the demo works.
        if "mice" in query.lower() or "mouse" in query.lower():
            sql = 'SELECT sku, name FROM products WHERE species = %s LIMIT %s'
            log.error("postgres-db: query failed | sql=%r | error=%s",
                      sql, 'column "species" does not exist')
            raise HTTPException(
                status_code=500,
                detail='database error: column "species" does not exist '
                       '(synthetic — POSTGRES_HOST not set)',
            )
        return {"ok": True, "query": query, "results": []}

    # Mice trap — hardcoded broken SQL that references a nonexistent
    # `species` column. psycopg raises UndefinedColumn; the OTel
    # instrumentation captures the SQL in db.statement on the (errored)
    # span so the trace shows exactly what failed.
    if "mice" in query.lower() or "mouse" in query.lower():
        sql = "SELECT sku, name, price_usd FROM products WHERE species = %s LIMIT %s"
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute(sql, ("mouse", limit))
                _ = cur.fetchall()
        except psycopg.errors.UndefinedColumn as e:
            log.error(
                "postgres-db: query failed | sql=%r | params=%r | error=%s",
                sql, ("mouse", limit), str(e).strip(),
            )
            raise HTTPException(status_code=500, detail=f"database error: {e}") from e
        except psycopg.Error as e:
            log.error("postgres-db: pg error | sql=%r | error=%s", sql, str(e).strip())
            raise HTTPException(status_code=500, detail=f"database error: {e}") from e

    # Real path — ILIKE search on name + description.
    sql = (
        "SELECT sku, name, description, price_usd "
        "FROM products WHERE name ILIKE %s OR description ILIKE %s LIMIT %s"
    )
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute(sql, (f"%{query}%", f"%{query}%", limit))
            rows = [
                {"sku": r[0], "name": r[1], "description": r[2], "price_usd": float(r[3] or 0)}
                for r in cur.fetchall()
            ]
        return {"ok": True, "query": query, "results": rows}
    except psycopg.Error as e:
        log.error("postgres-db: query failed | sql=%r | query=%r | error=%s",
                  sql, query, str(e).strip())
        raise HTTPException(status_code=500, detail=f"database error: {e}") from e

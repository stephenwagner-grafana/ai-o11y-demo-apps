"""Postgres seed loader.

One-shot batch script: applies the schema and loads the three NeonCart
catalog CSVs (categories, brands, products) into Postgres. Runs once per
Helm install/upgrade as a Kubernetes Job.

Env vars (all optional except POSTGRES_HOST + POSTGRES_PASSWORD):
  POSTGRES_HOST                — Postgres hostname (required)
  POSTGRES_PORT (default 5432)
  POSTGRES_DB   (default neoncart)
  POSTGRES_USER (default neoncart)
  POSTGRES_PASSWORD             — required
  SEED_DIR      (default /seed)  — CSVs are ConfigMap-mounted here
  SCHEMA_PATH   (default /app/schema.sql)
  LOG_LEVEL     (default INFO)

The Job is idempotent: schema.sql DROPs+CREATEs the three tables before
each load, so rerunning always yields a clean catalog.
"""
from __future__ import annotations

import csv
import logging
import os
import sys
from pathlib import Path

import psycopg

log = logging.getLogger("seed-loader")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _dsn() -> str:
    host = os.getenv("POSTGRES_HOST")
    if not host:
        raise SystemExit("POSTGRES_HOST is required")
    password = os.getenv("POSTGRES_PASSWORD", "")
    return (
        f"postgresql://{os.getenv('POSTGRES_USER', 'neoncart')}:{password}"
        f"@{host}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'neoncart')}"
    )


def _none_if_empty(value: str | None) -> str | None:
    """Treat empty CSV cells as SQL NULL."""
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        # csv.DictReader handles RFC 4180 quoting correctly, so descriptions
        # like '"Compact, GaN charger"' would be parsed as one field. Our
        # current CSV doesn't quote anything because no field embeds commas,
        # but DictReader is the right tool either way.
        return list(csv.DictReader(f))


def load_categories(cur: psycopg.Cursor, seed_dir: Path) -> int:
    rows = _read_csv(seed_dir / "categories.csv")
    records = [
        (int(r["id"]), r["name"], r["slug"])
        for r in rows
    ]
    cur.executemany(
        "INSERT INTO categories (id, name, slug) VALUES (%s, %s, %s)",
        records,
    )
    return len(records)


def load_brands(cur: psycopg.Cursor, seed_dir: Path) -> int:
    rows = _read_csv(seed_dir / "brands.csv")
    records = [
        (int(r["id"]), r["name"], _none_if_empty(r.get("logo_url")))
        for r in rows
    ]
    cur.executemany(
        "INSERT INTO brands (id, name, logo_url) VALUES (%s, %s, %s)",
        records,
    )
    return len(records)


def load_products(cur: psycopg.Cursor, seed_dir: Path) -> int:
    rows = _read_csv(seed_dir / "products.csv")
    # `is_latest_SKU_for_product` is empty in the seed CSV, so we skip the
    # column entirely on insert and let the schema's DEFAULT TRUE apply.
    records = [
        (
            r["sku"],
            r["name"],
            _none_if_empty(r.get("description")),
            _none_if_empty(r.get("price_usd")),
            int(r["category_id"]) if _none_if_empty(r.get("category_id")) else None,
            int(r["brand_id"]) if _none_if_empty(r.get("brand_id")) else None,
            _none_if_empty(r.get("image_url")),
            int(r["stock_qty"]) if _none_if_empty(r.get("stock_qty")) else 0,
        )
        for r in rows
    ]
    cur.executemany(
        "INSERT INTO products "
        "(sku, name, description, price_usd, category_id, brand_id, image_url, stock_qty) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        records,
    )
    return len(records)


def main() -> int:
    seed_dir = Path(os.getenv("SEED_DIR", "/seed"))
    schema_path = Path(os.getenv("SCHEMA_PATH", "/app/schema.sql"))

    if not seed_dir.is_dir():
        log.error("SEED_DIR does not exist or is not a directory: %s", seed_dir)
        return 1
    if not schema_path.is_file():
        log.error("SCHEMA_PATH does not exist: %s", schema_path)
        return 1

    schema_sql = schema_path.read_text(encoding="utf-8")

    log.info("Connecting to Postgres at %s", os.getenv("POSTGRES_HOST"))
    with psycopg.connect(_dsn(), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            log.info("Applying schema from %s", schema_path)
            cur.execute(schema_sql)

            # FK-safe load order: categories + brands first, products last.
            n_cat = load_categories(cur, seed_dir)
            log.info("Loaded %d categories", n_cat)

            n_brand = load_brands(cur, seed_dir)
            log.info("Loaded %d brands", n_brand)

            n_prod = load_products(cur, seed_dir)
            log.info("Loaded %d products", n_prod)

        conn.commit()

    log.info("Seed load complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("Seed load failed")
        sys.exit(1)

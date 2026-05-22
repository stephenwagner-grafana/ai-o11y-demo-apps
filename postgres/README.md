# postgres

Postgres initialization for the AI o11y demo. Lives in the `ai-o11y-postgres` namespace and holds the NeonCart product catalog (50 products, 12 categories, 31 brands). The SupportBot pgvector knowledge base is initialized separately and isn't covered here.

## What's in this dir

| Path | Purpose |
|---|---|
| `seed-loader/schema.sql` | DDL for the catalog tables (`categories`, `brands`, `products`) **and** runtime tables (`carts`, `orders`). Drops + recreates on every run, so the seed Job is idempotent. |
| `seed-loader/main.py` | One-shot Python script that applies `schema.sql` and loads the seed CSVs. |
| `seed-loader/Dockerfile` | python:3.12-slim image with `psycopg[binary]==3.2.3`. |
| `seed-loader/requirements.txt` | Pinned deps. |

## Schema

See [seed-loader/schema.sql](./seed-loader/schema.sql). Five tables (3 catalog + 2 runtime):

- **`categories`** — `id` (PK), `name`, `slug` (unique). 12 rows.
- **`brands`** — `id` (PK), `name`, `logo_url`. 31 rows.
- **`products`** — `sku` (PK), `name`, `description`, `price_usd`, `category_id` (FK), `brand_id` (FK), `image_url`, `stock_qty`, `is_latest_sku_for_product`. 50 rows. Indexes on `category_id` and `brand_id`.
- **`carts`** — `session_id` + `sku` composite PK; `quantity`, `source`, `user_id`, `added_at`. Per-session shopping cart contents.
- **`orders`** — `order_id` (PK), `session_id`, `user_id`, `total_usd`, `item_count`, `used_ai`, `placed_at`. Completed checkouts.

The seed CSV's `is_latest_SKU_for_product` column is empty for every row — the loader skips it on insert and the schema's `DEFAULT TRUE` kicks in.

## How the seed Job runs

Once the Helm chart for `ai-o11y-postgres` is wired up:

1. Postgres StatefulSet comes up.
2. A Kubernetes `Job` (defined in `helm/templates/postgres-seed-job.yaml`) runs the image built from `seed-loader/`.
3. The seed CSVs in [`/seed`](../seed/) are mounted as a `ConfigMap` at `/seed` in the Job pod.
4. `main.py` connects to Postgres, applies `schema.sql`, then loads the three CSVs in FK-safe order (categories → brands → products) via `psycopg.executemany`.
5. Job exits 0; subsequent restarts repeat the drop+recreate (idempotent).

A `wait-for-postgres` initContainer or a `Helm hook` ordering keeps the Job from running before Postgres is ready.

## Customer override (env vars)

| Env var | Default | Notes |
|---|---|---|
| `POSTGRES_HOST` | — | Required. |
| `POSTGRES_PORT` | `5432` | |
| `POSTGRES_DB` | `neoncart` | |
| `POSTGRES_USER` | `neoncart` | |
| `POSTGRES_PASSWORD` | — | Required. Comes from the Helm-managed Secret. |
| `SEED_DIR` | `/seed` | Where the ConfigMap is mounted. |
| `SCHEMA_PATH` | `/app/schema.sql` | Baked into the image. |
| `LOG_LEVEL` | `INFO` | Standard Python logging level. |

A customer pointing the demo at their own Postgres instance only needs to set `POSTGRES_HOST` + `POSTGRES_PASSWORD` (and matching `POSTGRES_USER` / `POSTGRES_DB` if they differ).

## Phase 1 status

- Schema DDL
- Idempotent seed loader (Python + psycopg)
- Dockerfile
- Helm chart + Job template (lands with the chart PR)
- pgvector knowledge base init for SupportBot (separate dir)

## Local dev

```bash
# from repo root
docker build -t ai-o11y-seed-loader postgres/seed-loader

docker run --rm \
  -e POSTGRES_HOST=host.docker.internal \
  -e POSTGRES_PASSWORD=neoncart \
  -v "$PWD/seed:/seed:ro" \
  ai-o11y-seed-loader
```

# Seed data

These CSVs are loaded into Postgres on deploy by the seed Job (`helm/templates/postgres-seed-job.yaml`).

## Files

| File | Rows | Notes |
|---|---|---|
| `products.csv` | 50 | NeonCart product catalog. Hand-curated subset sampled from `observibelity` v1 (4 per category × 12 categories + 2 extras). |
| `categories.csv` | 12 | Product categories (Electronics, Gaming, Mobile, Smart Home, etc.) |
| `brands.csv` | 31 | Fictional brand names (NeonTech, BlueWave, AstroByte, etc.) |

## Schema

### `products.csv`

```
sku,name,description,price_usd,category_id,brand_id,image_url,stock_qty,is_latest_SKU_for_product
```

- `sku` — unique string ID (e.g., `PHN-001`)
- `name` — product display name
- `description` — short marketing copy (used for product detail page + gift-finder LLM context)
- `price_usd` — decimal USD
- `category_id` — FK to `categories.id`
- `brand_id` — FK to `brands.id`
- `image_url` — placeholder URLs; real images TBD
- `stock_qty` — initial stock count
- `is_latest_SKU_for_product` — legacy field from v1, unused here

### `categories.csv`

```
id,name,slug
```

### `brands.csv`

```
id,name,logo_url
```

## Expanding the catalog later

50 products is enough to populate dashboards. To grow the catalog (e.g., for "1000 products" demos), use `tools/regenerate-products.py` (TODO — placeholder for now). The script will use an LLM to generate batches of products keyed to the existing categories/brands, then append to or replace `products.csv`.

Hand-editing `products.csv` is fully supported and won't be overwritten unless `regenerate-products.py` is run with `--replace`.

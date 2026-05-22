-- NeonCart product catalog schema.
--
-- The seed-loader runs this DDL once on every Helm install (or upgrade) and
-- then loads the CSVs in seed/ into the resulting tables. The DROPs make the
-- Job idempotent: rerunning it always produces a clean catalog.
--
-- Drop order is reverse of FK dependencies so the DROPs themselves don't
-- choke on existing constraints.

-- Catalog tables are recreated by the seed Job (idempotent reseed).
-- Runtime tables (carts, orders) are also recreated — fine for the demo
-- since seed runs as a post-install hook (not every restart).
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS carts;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS brands;
DROP TABLE IF EXISTS categories;

CREATE TABLE categories (
    id   INT PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    slug VARCHAR(64) NOT NULL UNIQUE
);

CREATE TABLE brands (
    id       INT PRIMARY KEY,
    name     VARCHAR(64) NOT NULL,
    logo_url TEXT
);

CREATE TABLE products (
    sku                       VARCHAR(32)    PRIMARY KEY,
    name                      VARCHAR(128)   NOT NULL,
    description               TEXT,
    price_usd                 NUMERIC(10, 2),
    category_id               INT            REFERENCES categories(id),
    brand_id                  INT            REFERENCES brands(id),
    image_url                 TEXT,
    stock_qty                 INT            DEFAULT 0,
    is_latest_sku_for_product BOOLEAN        DEFAULT TRUE
);

CREATE INDEX idx_products_category_id ON products (category_id);
CREATE INDEX idx_products_brand_id    ON products (brand_id);

-- ── Runtime tables ───────────────────────────────────────────────────────────
-- Carts: per-session items. Composite PK so a single session can hold many SKUs.
CREATE TABLE carts (
    session_id VARCHAR(64)  NOT NULL,
    sku        VARCHAR(32)  NOT NULL REFERENCES products(sku),
    quantity   INT          NOT NULL DEFAULT 1,
    source     VARCHAR(32)  NOT NULL DEFAULT 'manual',  -- manual | ai_gift_finder | ai_chatbot
    user_id    VARCHAR(128),
    added_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, sku)
);

CREATE INDEX idx_carts_session_id ON carts (session_id);
CREATE INDEX idx_carts_user_id    ON carts (user_id);

-- Orders: completed checkouts. Item-level detail intentionally rolled up into
-- total_usd + item_count to keep the demo schema small; per-line breakdown can
-- be derived from the cart contents at checkout time via logs/events if needed.
CREATE TABLE orders (
    order_id   VARCHAR(32)  PRIMARY KEY,
    session_id VARCHAR(64)  NOT NULL,
    user_id    VARCHAR(128),
    total_usd  NUMERIC(10, 2) NOT NULL,
    item_count INT          NOT NULL,
    used_ai    BOOLEAN      NOT NULL DEFAULT FALSE,
    placed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orders_user_id   ON orders (user_id);
CREATE INDEX idx_orders_placed_at ON orders (placed_at);

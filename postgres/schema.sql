-- NeonCart product catalog schema.
--
-- The seed-loader runs this DDL once on every Helm install (or upgrade) and
-- then loads the CSVs in seed/ into the resulting tables. The DROPs make the
-- Job idempotent: rerunning it always produces a clean catalog.
--
-- Drop order is reverse of FK dependencies so the DROPs themselves don't
-- choke on existing constraints.

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

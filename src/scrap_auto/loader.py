from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_SQL = """\
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS autoparts_articles (
    article_id           BIGINT PRIMARY KEY,
    part_name            TEXT,
    part_number          TEXT,
    article_number       TEXT,
    article_manufacturer TEXT,
    group_name           TEXT,
    primary_group_name   TEXT,
    supplier_id          INTEGER,
    product_id           INTEGER,
    is_oem               BOOLEAN DEFAULT FALSE,
    thumbnail_url        TEXT,
    manufacturer_id      INTEGER,
    model_series_id      INTEGER,
    car_type_id          INTEGER,
    group_id             INTEGER,
    details_url          TEXT,
    search_vector        TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(part_name, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(part_number, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(article_number, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(article_manufacturer, '')), 'C')
    ) STORED
);

CREATE TABLE IF NOT EXISTS autoparts_article_details (
    article_id        BIGINT PRIMARY KEY
                      REFERENCES autoparts_articles(article_id) ON DELETE CASCADE,
    article_name      TEXT,
    ean_numbers       JSONB,
    oem_numbers       JSONB,
    technical_details JSONB,
    image_urls        JSONB
);

CREATE TABLE IF NOT EXISTS autoparts_compatible_cars (
    id                SERIAL PRIMARY KEY,
    article_id        BIGINT
                      REFERENCES autoparts_articles(article_id) ON DELETE CASCADE,
    car_type_id       INTEGER,
    model_series_id   INTEGER,
    manufacturer_name TEXT,
    model_name        TEXT,
    engine_or_variant TEXT,
    year_from         TEXT,
    year_to           TEXT,
    extra_qualifier   TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_fts
    ON autoparts_articles USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_articles_partnum
    ON autoparts_articles USING GIN (part_number gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_articles_mfr
    ON autoparts_articles (article_manufacturer);
CREATE INDEX IF NOT EXISTS idx_compat_lookup
    ON autoparts_compatible_cars (manufacturer_name, model_name);
CREATE INDEX IF NOT EXISTS idx_compat_article
    ON autoparts_compatible_cars (article_id);
"""

_GRANT_API_SQL = """\
GRANT SELECT ON ALL TABLES IN SCHEMA public TO autoparts_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO autoparts_api;
"""

_UPSERT_ARTICLE = """\
INSERT INTO autoparts_articles
    (article_id, part_name, part_number, article_number, article_manufacturer,
     group_name, primary_group_name, supplier_id, product_id, is_oem,
     thumbnail_url, manufacturer_id, model_series_id, car_type_id, group_id,
     details_url)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (article_id) DO UPDATE SET
    part_name            = EXCLUDED.part_name,
    part_number          = EXCLUDED.part_number,
    article_number       = EXCLUDED.article_number,
    article_manufacturer = EXCLUDED.article_manufacturer,
    group_name           = EXCLUDED.group_name,
    primary_group_name   = EXCLUDED.primary_group_name,
    supplier_id          = EXCLUDED.supplier_id,
    product_id           = EXCLUDED.product_id,
    is_oem               = EXCLUDED.is_oem,
    thumbnail_url        = EXCLUDED.thumbnail_url,
    manufacturer_id      = EXCLUDED.manufacturer_id,
    model_series_id      = EXCLUDED.model_series_id,
    car_type_id          = EXCLUDED.car_type_id,
    group_id             = EXCLUDED.group_id,
    details_url          = EXCLUDED.details_url
"""

_UPSERT_DETAIL = """\
INSERT INTO autoparts_article_details
    (article_id, article_name, ean_numbers, oem_numbers, technical_details, image_urls)
VALUES (%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb)
ON CONFLICT (article_id) DO UPDATE SET
    article_name      = EXCLUDED.article_name,
    ean_numbers       = EXCLUDED.ean_numbers,
    oem_numbers       = EXCLUDED.oem_numbers,
    technical_details = EXCLUDED.technical_details,
    image_urls        = EXCLUDED.image_urls
"""

_INSERT_COMPAT = """\
INSERT INTO autoparts_compatible_cars
    (article_id, car_type_id, model_series_id, manufacturer_name,
     model_name, engine_or_variant, year_from, year_to, extra_qualifier)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""


def load_all(
    database_url: str,
    data_dir: Path,
    batch_size: int,
    init: bool,
    grant_api: bool,
    console: Any,
) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn:
        if init:
            console.print("[cyan]Initializing schema...[/cyan]")
            conn.execute(_SCHEMA_SQL)
            conn.commit()
            console.print("[green]Schema ready[/green]")

        if grant_api:
            console.print("[cyan]Granting read-only access to autoparts_api...[/cyan]")
            conn.execute(_GRANT_API_SQL)
            conn.commit()

        articles_path = data_dir / "parquet" / "articles_deduped.parquet"
        details_path = data_dir / "parquet" / "article_details_deduped.parquet"

        if articles_path.exists():
            _load_articles(conn, articles_path, batch_size, console)
        else:
            console.print(f"[yellow]Not found: {articles_path} — run 'scrap-auto dedup' first[/yellow]")

        if details_path.exists():
            _load_article_details(conn, details_path, batch_size, console)
        else:
            console.print(f"[yellow]Not found: {details_path} — run 'scrap-auto dedup' first[/yellow]")

    console.print("[bold green]Load complete[/bold green]")


def _load_articles(conn: Any, path: Path, batch_size: int, console: Any) -> None:
    import polars as pl

    console.print(f"[cyan]Loading articles → autoparts_articles[/cyan]")
    df = pl.read_parquet(path)
    total = len(df)
    loaded = 0

    for start in range(0, total, batch_size):
        rows = []
        for r in df.slice(start, batch_size).to_dicts():
            rows.append((
                _int(r.get("article_id")),
                r.get("part_name") or "",
                r.get("part_number") or "",
                r.get("article_number") or "",
                r.get("article_manufacturer") or "",
                r.get("group_name") or "",
                r.get("primary_group_name") or "",
                _int(r.get("supplier_id")),
                _int(r.get("product_id")),
                bool(r.get("is_oem", False)),
                r.get("thumbnail_url") or "",
                _int(r.get("manufacturer_id")),
                _int(r.get("model_series_id")),
                _int(r.get("car_type_id")),
                _int(r.get("group_id")),
                r.get("details_url") or "",
            ))
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_ARTICLE, rows)
        conn.commit()
        loaded += len(rows)
        console.print(f"  articles {loaded}/{total}")

    console.print(f"[green]Articles loaded: {loaded}[/green]")


def _load_article_details(conn: Any, path: Path, batch_size: int, console: Any) -> None:
    import polars as pl

    console.print("[cyan]Loading article details → autoparts_article_details + compatible_cars[/cyan]")
    df = pl.read_parquet(path)
    total = len(df)
    loaded = 0

    for start in range(0, total, batch_size):
        detail_rows = []
        compat_rows: list[tuple] = []
        batch_article_ids: list[int] = []

        for r in df.slice(start, batch_size).to_dicts():
            article_id = _int(r.get("article_id"))
            if article_id is None:
                continue

            batch_article_ids.append(article_id)
            detail_rows.append((
                article_id,
                r.get("article_name") or "",
                json.dumps(_list(r.get("ean_numbers"))),
                json.dumps(_list(r.get("oem_numbers"))),
                json.dumps(_list(r.get("technical_details"))),
                json.dumps(_list(r.get("image_urls"))),
            ))

            for car in _list(r.get("compatible_cars")):
                if not isinstance(car, dict):
                    continue
                compat_rows.append((
                    article_id,
                    _int(car.get("car_type_id")),
                    _int(car.get("model_series_id")),
                    car.get("manufacturer_name") or "",
                    car.get("model_name") or "",
                    car.get("engine_or_variant") or "",
                    car.get("year_from") or "",
                    car.get("year_to") or "",
                    car.get("extra_qualifier") or "",
                ))

        with conn.cursor() as cur:
            cur.executemany(_UPSERT_DETAIL, detail_rows)
            if batch_article_ids:
                cur.execute(
                    "DELETE FROM autoparts_compatible_cars WHERE article_id = ANY(%s)",
                    (batch_article_ids,),
                )
            if compat_rows:
                cur.executemany(_INSERT_COMPAT, compat_rows)

        conn.commit()
        loaded += len(detail_rows)
        console.print(f"  details {loaded}/{total}")

    console.print(f"[green]Article details loaded: {loaded}[/green]")


def _int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return []

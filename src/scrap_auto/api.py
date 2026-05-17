from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config (from environment)
# ---------------------------------------------------------------------------
_DB_URL: str = os.environ.get("AUTOPARTS_DATABASE_URL", "")
_API_KEY: str = os.environ.get("AUTOPARTS_API_KEY", "")

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Register JSONB codec so asyncpg returns Python objects instead of strings."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _pool
    if not _DB_URL:
        raise RuntimeError("AUTOPARTS_DATABASE_URL is not set")
    _pool = await asyncpg.create_pool(
        _DB_URL,
        min_size=2,
        max_size=10,
        init=_init_conn,
    )
    yield
    if _pool:
        await _pool.close()


app = FastAPI(
    title="Auto Parts Search API",
    description="Search API for auto parts data served to i2doo / repair_auto module.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Auth — simple API key header (skip check when key not configured)
# ---------------------------------------------------------------------------
_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Depends(_key_header)) -> None:
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------
class ArticleSummary(BaseModel):
    article_id: int
    part_name: str | None
    part_number: str | None
    article_number: str | None
    article_manufacturer: str | None
    group_name: str | None
    is_oem: bool
    thumbnail_url: str | None
    manufacturer_id: int | None
    details_url: str | None


class SearchResult(BaseModel):
    total: int
    page: int
    limit: int
    results: list[ArticleSummary]


class ArticleDetail(BaseModel):
    article_id: int
    part_name: str | None
    article_name: str | None
    part_number: str | None
    article_number: str | None
    article_manufacturer: str | None
    is_oem: bool
    thumbnail_url: str | None
    image_urls: list[str]
    ean_numbers: list[str]
    oem_numbers: list[dict[str, str]]
    technical_details: list[dict[str, str]]
    compatible_cars_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pool_conn() -> asyncpg.Pool:
    if _pool is None:
        raise HTTPException(status_code=503, detail="Database pool not ready")
    return _pool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/search",
    response_model=SearchResult,
    dependencies=[Depends(require_api_key)],
    summary="Full-text + car-filter article search",
)
async def search(
    q: str = Query(default="", description="Search terms (part name, number, manufacturer)"),
    make: str | None = Query(default=None, description="Vehicle manufacturer e.g. FORD"),
    model: str | None = Query(default=None, description="Vehicle model e.g. FOCUS"),
    year: str | None = Query(default=None, description="Vehicle year e.g. 2015"),
    is_oem: bool | None = Query(default=None, description="True = OEM only, False = aftermarket only"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> SearchResult:
    offset = (page - 1) * limit
    q_clean = q.strip()

    args: list[Any] = []
    conditions: list[str] = []

    if q_clean:
        args.append(q_clean)
        conditions.append(f"a.search_vector @@ websearch_to_tsquery('simple', ${len(args)})")

    if is_oem is not None:
        args.append(is_oem)
        conditions.append(f"a.is_oem = ${len(args)}")

    if make or model or year:
        compat_conds: list[str] = []
        if make:
            args.append(f"%{make}%")
            compat_conds.append(f"manufacturer_name ILIKE ${len(args)}")
        if model:
            args.append(f"%{model}%")
            compat_conds.append(f"model_name ILIKE ${len(args)}")
        if year:
            args.append(year)
            compat_conds.append(f"(year_from = '' OR year_from <= ${len(args)})")
            args.append(year)
            compat_conds.append(f"(year_to = '' OR year_to >= ${len(args)})")
        compat_sql = " AND ".join(compat_conds)
        conditions.append(
            f"a.article_id IN (SELECT DISTINCT article_id FROM autoparts_compatible_cars WHERE {compat_sql})"
        )

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order_sql = (
        f"ORDER BY ts_rank(a.search_vector, websearch_to_tsquery('simple', $1)) DESC"
        if q_clean
        else "ORDER BY a.article_id"
    )

    n = len(args)
    count_sql = f"SELECT COUNT(*) FROM autoparts_articles a {where_sql}"
    rows_sql = f"""
        SELECT a.article_id, a.part_name, a.part_number, a.article_number,
               a.article_manufacturer, a.group_name, a.is_oem, a.thumbnail_url,
               a.manufacturer_id, a.details_url
        FROM autoparts_articles a
        {where_sql}
        {order_sql}
        LIMIT ${n + 1} OFFSET ${n + 2}
    """

    pool = _pool_conn()
    async with pool.acquire() as conn:
        total: int = await conn.fetchval(count_sql, *args) or 0
        rows = await conn.fetch(rows_sql, *args, limit, offset)

    return SearchResult(
        total=total,
        page=page,
        limit=limit,
        results=[ArticleSummary(**dict(r)) for r in rows],
    )


@app.get(
    "/article/{article_id}",
    response_model=ArticleDetail,
    dependencies=[Depends(require_api_key)],
    summary="Full article details including images, OEM numbers, and compatible cars",
)
async def get_article(article_id: int) -> ArticleDetail:
    pool = _pool_conn()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                a.article_id, a.part_name, a.part_number, a.article_number,
                a.article_manufacturer, a.is_oem, a.thumbnail_url, a.details_url,
                d.article_name, d.ean_numbers, d.oem_numbers,
                d.technical_details, d.image_urls,
                (SELECT COUNT(*)::int FROM autoparts_compatible_cars
                 WHERE article_id = a.article_id) AS compatible_cars_count
            FROM autoparts_articles a
            LEFT JOIN autoparts_article_details d USING (article_id)
            WHERE a.article_id = $1
            """,
            article_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")

    r = dict(row)
    return ArticleDetail(
        article_id=r["article_id"],
        part_name=r.get("part_name"),
        article_name=r.get("article_name"),
        part_number=r.get("part_number"),
        article_number=r.get("article_number"),
        article_manufacturer=r.get("article_manufacturer"),
        is_oem=bool(r.get("is_oem", False)),
        thumbnail_url=r.get("thumbnail_url"),
        image_urls=r.get("image_urls") or [],
        ean_numbers=r.get("ean_numbers") or [],
        oem_numbers=r.get("oem_numbers") or [],
        technical_details=r.get("technical_details") or [],
        compatible_cars_count=r.get("compatible_cars_count", 0),
    )


@app.get(
    "/compatible/{article_id}",
    dependencies=[Depends(require_api_key)],
    summary="List compatible cars for an article",
)
async def compatible_cars(
    article_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    pool = _pool_conn()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT car_type_id, model_series_id, manufacturer_name, model_name,
                   engine_or_variant, year_from, year_to, extra_qualifier
            FROM autoparts_compatible_cars
            WHERE article_id = $1
            ORDER BY manufacturer_name, model_name, year_from
            LIMIT $2 OFFSET $3
            """,
            article_id,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


@app.get(
    "/manufacturers",
    dependencies=[Depends(require_api_key)],
    summary="List all vehicle manufacturers present in compatible_cars data",
)
async def list_manufacturers() -> list[str]:
    pool = _pool_conn()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT manufacturer_name FROM autoparts_compatible_cars "
            "WHERE manufacturer_name != '' ORDER BY manufacturer_name"
        )
    return [r["manufacturer_name"] for r in rows]


@app.get(
    "/models/{manufacturer_name}",
    dependencies=[Depends(require_api_key)],
    summary="List vehicle models for a given manufacturer",
)
async def list_models(manufacturer_name: str) -> list[str]:
    pool = _pool_conn()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT model_name FROM autoparts_compatible_cars "
            "WHERE manufacturer_name ILIKE $1 AND model_name != '' "
            "ORDER BY model_name",
            f"%{manufacturer_name}%",
        )
    return [r["model_name"] for r in rows]

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import db_pool, require_api_key
from ..schemas.articles import (
    ArticleDetail,
    ArticleResult,
    ArticleSearchResponse,
    CompatibleCar,
)
from ..schemas.common import Page

router = APIRouter(tags=["articles"], dependencies=[Depends(require_api_key)])

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------
# $1 = car_type_id        (int  | None) — when set, restricts to compatible cars
# $2 = group_id           (int  | None)
# $3 = fts query          (str  | None) — websearch syntax
# $4 = part_number filter (str  | None) — ILIKE, uses idx_articles_partnum (GIN trgm)
# $5 = manufacturer filter(str  | None) — ILIKE, uses idx_articles_mfr (btree lower())
#
# car_type_id is optional: when NULL the EXISTS clause is skipped so the
# endpoint can be used for cross-car part-number / manufacturer lookups.
# At least one of the five parameters must be non-NULL (enforced in Python).
# ---------------------------------------------------------------------------
_WHERE = """\
    FROM autoparts_articles a
    WHERE ($1::integer IS NULL OR EXISTS (
        SELECT 1
        FROM   autoparts_compatible_cars
        WHERE  article_id = a.article_id
        AND    car_type_id = $1
    ))
    AND ($2::integer IS NULL OR a.group_id = $2)
    AND ($3::text    IS NULL OR a.search_vector @@ websearch_to_tsquery('simple', $3))
    AND ($4::text    IS NULL OR a.part_number ILIKE '%' || $4 || '%')
    AND ($5::text    IS NULL OR lower(a.article_manufacturer) = lower($5))
"""

_COUNT_SQL = f"SELECT COUNT(*) {_WHERE}"

_SEARCH_SQL = f"""
    SELECT
        a.article_id,
        a.part_name,
        a.part_number,
        a.article_manufacturer,
        a.group_id,
        a.is_oem,
        a.thumbnail_url
    {_WHERE}
    ORDER BY a.is_oem DESC, a.article_manufacturer, a.part_name
    LIMIT $6 OFFSET $7
"""

_DETAIL_SQL = """
    SELECT
        a.article_id,
        a.part_number,
        a.article_number,
        a.article_manufacturer,
        a.is_oem,
        a.thumbnail_url,
        d.article_name,
        d.ean_numbers,
        d.oem_numbers,
        d.technical_details,
        d.image_urls
    FROM autoparts_articles a
    LEFT JOIN autoparts_article_details d USING (article_id)
    WHERE a.article_id = $1
"""

# COUNT(*) OVER() gives the unfiltered total alongside the page rows so compatible_cars
# uses a single query and a single connection per request.
_COMPAT_SQL = """
    SELECT
        car_type_id,
        model_series_id,
        manufacturer_name,
        model_name,
        engine_or_variant,
        year_from,
        year_to,
        extra_qualifier,
        COUNT(*) OVER() AS total_count
    FROM autoparts_compatible_cars
    WHERE article_id = $1
    ORDER BY manufacturer_name, model_name, year_from
    LIMIT $2 OFFSET $3
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/articles/search",
    response_model=ArticleSearchResponse,
    summary="Search articles by car type, part number, manufacturer, category, and/or keyword",
)
async def search_articles(
    car_type_id: int | None = Query(None, description="Car type ID (from /sync/car-types) — restricts results to compatible articles"),
    group_id: int | None = Query(None, description="Filter by part category group_id"),
    q: str | None = Query(None, description="Free-text search across part name and number"),
    part_number: str | None = Query(None, description="Partial part number match (case-insensitive)"),
    article_manufacturer: str | None = Query(None, description="Exact manufacturer name match (case-insensitive)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> ArticleSearchResponse:
    q_clean = q.strip() or None if q else None
    pn_clean = part_number.strip() or None if part_number else None
    mfr_clean = article_manufacturer.strip() or None if article_manufacturer else None

    if not any([car_type_id, q_clean, pn_clean, mfr_clean]):
        raise HTTPException(
            status_code=400,
            detail="At least one search parameter is required: car_type_id, q, part_number, or article_manufacturer",
        )

    async with pool.acquire() as conn:
        total = (await conn.fetchval(_COUNT_SQL, car_type_id, group_id, q_clean, pn_clean, mfr_clean)) or 0
        rows = await conn.fetch(_SEARCH_SQL, car_type_id, group_id, q_clean, pn_clean, mfr_clean, limit, offset)

    return ArticleSearchResponse(
        total=total,
        offset=offset,
        limit=limit,
        results=[ArticleResult.model_validate(dict(r)) for r in rows],
    )


@router.get(
    "/articles/{article_id}",
    response_model=ArticleDetail,
    summary="Full article detail: images, OEM/EAN numbers, technical specs",
)
async def get_article(
    article_id: int,
    pool: asyncpg.Pool = Depends(db_pool),
) -> ArticleDetail:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_DETAIL_SQL, article_id)

    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")

    r = dict(row)
    return ArticleDetail(
        article_id=r["article_id"],
        article_name=r.get("article_name"),
        part_number=r.get("part_number"),
        article_number=r.get("article_number"),
        article_manufacturer=r.get("article_manufacturer"),
        is_oem=bool(r.get("is_oem", False)),
        thumbnail_url=r.get("thumbnail_url"),
        ean_numbers=r.get("ean_numbers") or [],
        oem_numbers=r.get("oem_numbers") or [],
        technical_details=r.get("technical_details") or [],
        image_urls=r.get("image_urls") or [],
    )


@router.get(
    "/compatible/{article_id}",
    response_model=Page[CompatibleCar],
    summary="Vehicle types compatible with an article (paginated)",
)
async def compatible_cars(
    article_id: int,
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(100, ge=1, le=1000, description="Rows per page"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> Page[CompatibleCar]:
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch(_COMPAT_SQL, article_id, size, offset)
    total = rows[0]["total_count"] if rows else 0
    return Page(
        data=[CompatibleCar.model_validate(dict(r)) for r in rows],
        total=total,
        page=page,
        pages=-(-total // size) if total else 0,
    )

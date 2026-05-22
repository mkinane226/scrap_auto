from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import db_pool, require_api_key
from ..schemas.common import Page
from ..schemas.sync import CarTypeOut, GroupOut, ManufacturerOut, ModelSeriesOut, StatsOut

router = APIRouter(
    prefix="/sync",
    tags=["sync"],
    dependencies=[Depends(require_api_key)],
)

# ---------------------------------------------------------------------------
# Manufacturers  (~1 000 rows — no pagination needed)
# ---------------------------------------------------------------------------

@router.get(
    "/manufacturers",
    response_model=list[ManufacturerOut],
    summary="All vehicle manufacturers",
)
async def sync_manufacturers(
    pool: asyncpg.Pool = Depends(db_pool),
) -> list[ManufacturerOut]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT manufacturer_id AS id, manufacturer_name AS name "
            "FROM autoparts_manufacturers ORDER BY manufacturer_name"
        )
    return [ManufacturerOut.model_validate(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Model series  (~16 000 rows total — filterable by manufacturer_id)
# ---------------------------------------------------------------------------

@router.get(
    "/model-series",
    response_model=Page[ModelSeriesOut],
    summary="Vehicle model series — filter by manufacturer_id for navigation",
)
async def sync_model_series(
    manufacturer_id: int | None = Query(None, description="Filter by manufacturer — returns only that manufacturer's models"),
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(500, ge=1, le=1000, description="Rows per page"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> Page[ModelSeriesOut]:
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            "SELECT COUNT(*) FROM autoparts_model_series "
            "WHERE ($1::integer IS NULL OR manufacturer_id = $1)",
            manufacturer_id,
        ) or 0
        rows = await conn.fetch(
            """
            SELECT
                model_series_id   AS id,
                manufacturer_id,
                display_name,
                model_native_name,
                year_from,
                year_to
            FROM autoparts_model_series
            WHERE ($3::integer IS NULL OR manufacturer_id = $3)
            ORDER BY display_name
            LIMIT $1 OFFSET $2
            """,
            size,
            offset,
            manufacturer_id,
        )
    return Page(
        data=[ModelSeriesOut.model_validate(dict(r)) for r in rows],
        total=total,
        page=page,
        pages=-(-total // size) if total else 0,
    )


# ---------------------------------------------------------------------------
# Car types  (~83 000 rows total — filterable by model_series_id)
# ---------------------------------------------------------------------------

_CAR_TYPES_SQL = """
    SELECT
        ct.car_type_id                                      AS id,
        ct.model_series_id,
        ct.manufacturer_id,
        ct.type_label,
        ct.engine_code,
        ct.cylinder,
        ct.capacity,
        ct.fuel_type,
        ct.power,
        ct.year_from,
        ct.year_to,
        COALESCE(ctd.car_type_title, ct.type_label)         AS car_type_title,
        ctd.details                                         AS technical_specs
    FROM autoparts_car_types ct
    LEFT JOIN autoparts_car_type_details ctd USING (car_type_id)
    WHERE ($3::integer IS NULL OR ct.model_series_id = $3)
    ORDER BY ct.year_from DESC, ct.car_type_id
    LIMIT $1 OFFSET $2
"""


@router.get(
    "/car-types",
    response_model=Page[CarTypeOut],
    summary="Vehicle engine variants / car types — filter by model_series_id for navigation",
)
async def sync_car_types(
    model_series_id: int | None = Query(None, description="Filter by model series — returns only that model's engine variants"),
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(500, ge=1, le=1000, description="Rows per page"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> Page[CarTypeOut]:
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            "SELECT COUNT(*) FROM autoparts_car_types "
            "WHERE ($1::integer IS NULL OR model_series_id = $1)",
            model_series_id,
        ) or 0
        rows = await conn.fetch(_CAR_TYPES_SQL, size, offset, model_series_id)
    return Page(
        data=[CarTypeOut.model_validate(dict(r)) for r in rows],
        total=total,
        page=page,
        pages=-(-total // size) if total else 0,
    )


# ---------------------------------------------------------------------------
# Groups / part categories  (~800 rows — no pagination needed)
# ---------------------------------------------------------------------------

@router.get(
    "/groups",
    response_model=list[GroupOut],
    summary="All part category groups",
)
async def sync_groups(
    pool: asyncpg.Pool = Depends(db_pool),
) -> list[GroupOut]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                group_id             AS id,
                group_name,
                primary_group_name,
                subcategory_name,
                sub_subcategory_name
            FROM autoparts_groups
            ORDER BY primary_group_name, subcategory_name, group_name
            """
        )
    return [GroupOut.model_validate(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

@router.get(
    "/statistics",
    response_model=StatsOut,
    summary="Row counts for all core tables — useful for sync wizard dashboards",
)
async def sync_statistics(
    pool: asyncpg.Pool = Depends(db_pool),
) -> StatsOut:
    async with pool.acquire() as conn:
        manufacturers  = await conn.fetchval("SELECT COUNT(*) FROM autoparts_manufacturers")  or 0
        model_series   = await conn.fetchval("SELECT COUNT(*) FROM autoparts_model_series")   or 0
        car_types      = await conn.fetchval("SELECT COUNT(*) FROM autoparts_car_types")      or 0
        articles       = await conn.fetchval("SELECT COUNT(*) FROM autoparts_articles")       or 0
        compatible_cars = await conn.fetchval("SELECT COUNT(*) FROM autoparts_compatible_cars") or 0
    return StatsOut(
        manufacturers=manufacturers,
        model_series=model_series,
        car_types=car_types,
        articles=articles,
        compatible_cars=compatible_cars,
    )


# ---------------------------------------------------------------------------
# Compatible-cars discovery  (manufacturer names & model names as they are
# stored in autoparts_compatible_cars — these may differ from the normalized
# names in autoparts_manufacturers / autoparts_model_series, so callers
# must use these endpoints to drive /articles/by-car lookups)
# ---------------------------------------------------------------------------

@router.get(
    "/compat-manufacturers",
    response_model=list[str],
    summary="Distinct manufacturer names in compatible_cars — use these for /articles/by-car",
)
async def compat_manufacturers(
    pool: asyncpg.Pool = Depends(db_pool),
) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT manufacturer_name FROM autoparts_compat_manufacturers ORDER BY manufacturer_name"
        )
    return [r["manufacturer_name"] for r in rows]


@router.get(
    "/compat-models",
    response_model=list[str],
    summary="Distinct model names for a manufacturer in compatible_cars — use these for /articles/by-car",
)
async def compat_models(
    manufacturer_name: str | None = Query(None, description="Manufacturer name from /sync/compat-manufacturers"),
    manufacturer_id: int | None = Query(None, description="Manufacturer ID from /sync/manufacturers — resolved to name automatically"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> list[str]:
    if not manufacturer_name and not manufacturer_id:
        raise HTTPException(status_code=400, detail="Provide manufacturer_name or manufacturer_id")

    async with pool.acquire() as conn:
        if manufacturer_id and not manufacturer_name:
            resolved = await conn.fetchval(
                "SELECT UPPER(manufacturer_name) FROM autoparts_manufacturers WHERE manufacturer_id = $1",
                manufacturer_id,
            )
            if resolved is None:
                raise HTTPException(status_code=404, detail=f"Manufacturer {manufacturer_id} not found")
            manufacturer_name = resolved

        rows = await conn.fetch(
            "SELECT model_name FROM autoparts_compat_models "
            "WHERE manufacturer_name = $1 ORDER BY model_name",
            manufacturer_name.strip().upper(),
        )
    return [r["model_name"] for r in rows]

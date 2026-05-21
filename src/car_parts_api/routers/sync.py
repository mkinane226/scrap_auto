from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from ..deps import db_pool, require_api_key
from ..schemas.common import Page
from ..schemas.sync import CarTypeOut, GroupOut, ManufacturerOut, ModelSeriesOut

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

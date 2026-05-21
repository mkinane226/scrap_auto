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
# Model series  (~16 000 rows — paginated)
# ---------------------------------------------------------------------------

@router.get(
    "/model-series",
    response_model=Page[ModelSeriesOut],
    summary="Vehicle model series (paginated)",
)
async def sync_model_series(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(500, ge=1, le=1000, description="Rows per page"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> Page[ModelSeriesOut]:
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        total: int = await conn.fetchval("SELECT COUNT(*) FROM autoparts_model_series") or 0
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
            ORDER BY model_series_id
            LIMIT $1 OFFSET $2
            """,
            size,
            offset,
        )
    return Page(
        data=[ModelSeriesOut.model_validate(dict(r)) for r in rows],
        total=total,
        page=page,
        pages=-(-total // size),
    )


# ---------------------------------------------------------------------------
# Car types  (~83 000 rows — paginated, LEFT JOIN car_type_details)
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
    ORDER BY ct.car_type_id
    LIMIT $1 OFFSET $2
"""


@router.get(
    "/car-types",
    response_model=Page[CarTypeOut],
    summary="Vehicle engine variants / car types (paginated)",
)
async def sync_car_types(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(500, ge=1, le=1000, description="Rows per page"),
    pool: asyncpg.Pool = Depends(db_pool),
) -> Page[CarTypeOut]:
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        total: int = await conn.fetchval("SELECT COUNT(*) FROM autoparts_car_types") or 0
        rows = await conn.fetch(_CAR_TYPES_SQL, size, offset)
    return Page(
        data=[CarTypeOut.model_validate(dict(r)) for r in rows],
        total=total,
        page=page,
        pages=-(-total // size),
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

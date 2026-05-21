from __future__ import annotations

import asyncpg
from fastapi import Depends, HTTPException
from fastapi.security.api_key import APIKeyHeader

from .config import settings
from .database import get_pool

_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def require_api_key(key: str | None = Depends(_key_header)) -> None:
    if settings.api_key and key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header")


def db_pool() -> asyncpg.Pool:
    try:
        return get_pool()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Database not available") from exc

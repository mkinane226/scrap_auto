from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from .config import settings
from .database import close_pool, create_pool
from .routers import articles, health, sync


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not settings.database_url:
        raise RuntimeError("AUTOPARTS_DATABASE_URL environment variable is not set")
    if not settings.api_key and not settings.debug:
        raise RuntimeError(
            "AUTOPARTS_API_KEY is not set. "
            "Provide a strong secret via the AUTOPARTS_API_KEY env var, "
            "or set AUTOPARTS_DEBUG=true to allow unauthenticated access in development."
        )
    await create_pool(settings.database_url, settings.pool_min_size, settings.pool_max_size)
    yield
    await close_pool()


app = FastAPI(
    title="Car Parts Catalog API",
    description=(
        "REST API serving auto parts data to the Odoo `garage_parts_catalog` module.\n\n"
        "All endpoints except `/health` require an `X-Api-Key` header."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Compress responses over 1 KB — useful for large sync payloads (car-types pages)
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(health.router)
app.include_router(sync.router)
app.include_router(articles.router)


def run() -> None:
    """Entry point for the `car-parts-api` console script."""
    import uvicorn

    uvicorn.run(
        "car_parts_api.main:app",
        host="127.0.0.1",
        port=8090,
        workers=2,
        access_log=not settings.debug,
    )

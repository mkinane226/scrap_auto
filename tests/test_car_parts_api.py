"""Integration tests for car_parts_api auth and startup behaviour.

Run with:  pytest tests/ -v
Requires:  pip install -e ".[car-parts-api,test]"

These tests mock the asyncpg pool so no real PostgreSQL instance is needed.
Add DB-backed tests (e.g. against a test schema) separately once a CI database
is available.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

API_KEY = "test-key-1234"
DB_URL  = "postgresql://user:pw@localhost/testdb"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_pool() -> MagicMock:
    """Minimal asyncpg.Pool mock — all queries return empty/zero results."""
    conn = AsyncMock(spec=asyncpg.Connection)
    conn.fetch    = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=0)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)

    pool = MagicMock(spec=asyncpg.Pool)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def api_client():
    """AsyncClient backed by a mocked pool with AUTOPARTS_API_KEY configured."""
    from car_parts_api import config, database
    from car_parts_api.main import app

    orig_url   = config.settings.database_url
    orig_key   = config.settings.api_key
    orig_debug = config.settings.debug

    config.settings.database_url = DB_URL
    config.settings.api_key      = API_KEY
    config.settings.debug        = False

    pool = _mock_pool()

    async def _create_pool(url: str, min_size: int, max_size: int) -> asyncpg.Pool:
        database._pool = pool
        return pool

    async def _close_pool() -> None:
        database._pool = None

    try:
        with (
            patch("car_parts_api.main.create_pool", _create_pool),
            patch("car_parts_api.main.close_pool", _close_pool),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                yield ac
    finally:
        config.settings.database_url = orig_url
        config.settings.api_key      = orig_key
        config.settings.debug        = orig_debug
        database._pool               = None


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

async def test_health_no_auth_required(api_client: AsyncClient) -> None:
    """/health must be reachable without an API key."""
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_protected_returns_401_without_key(api_client: AsyncClient) -> None:
    resp = await api_client.get("/sync/manufacturers")
    assert resp.status_code == 401


async def test_protected_returns_401_with_wrong_key(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        "/sync/manufacturers", headers={"X-Api-Key": "wrong-key"}
    )
    assert resp.status_code == 401


async def test_protected_returns_200_with_correct_key(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        "/sync/manufacturers", headers={"X-Api-Key": API_KEY}
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Startup / lifespan tests  (test the lifespan function directly)
# ---------------------------------------------------------------------------

async def test_startup_fails_when_database_url_missing() -> None:
    """Lifespan must raise RuntimeError when AUTOPARTS_DATABASE_URL is not set."""
    from car_parts_api import config
    from car_parts_api.main import app, lifespan

    orig = config.settings.database_url
    config.settings.database_url = ""
    try:
        with pytest.raises(RuntimeError, match="AUTOPARTS_DATABASE_URL"):
            async with lifespan(app):
                pass
    finally:
        config.settings.database_url = orig


async def test_startup_fails_when_api_key_missing() -> None:
    """Lifespan must raise RuntimeError when AUTOPARTS_API_KEY is empty and not in debug mode."""
    from car_parts_api import config
    from car_parts_api.main import app, lifespan

    orig_key   = config.settings.api_key
    orig_url   = config.settings.database_url
    orig_debug = config.settings.debug

    config.settings.database_url = DB_URL
    config.settings.api_key      = ""
    config.settings.debug        = False
    try:
        with pytest.raises(RuntimeError, match="AUTOPARTS_API_KEY"):
            async with lifespan(app):
                pass
    finally:
        config.settings.api_key      = orig_key
        config.settings.database_url = orig_url
        config.settings.debug        = orig_debug


async def test_startup_succeeds_without_api_key_in_debug_mode() -> None:
    """Debug mode must allow startup without AUTOPARTS_API_KEY."""
    from car_parts_api import config, database
    from car_parts_api.main import app, lifespan

    orig_key   = config.settings.api_key
    orig_url   = config.settings.database_url
    orig_debug = config.settings.debug

    config.settings.database_url = DB_URL
    config.settings.api_key      = ""
    config.settings.debug        = True

    pool = _mock_pool()

    async def _create_pool(url: str, min_size: int, max_size: int) -> asyncpg.Pool:
        database._pool = pool
        return pool

    async def _close_pool() -> None:
        database._pool = None

    try:
        with (
            patch("car_parts_api.main.create_pool", _create_pool),
            patch("car_parts_api.main.close_pool", _close_pool),
        ):
            async with lifespan(app):
                pass  # lifespan exited cleanly — no exception raised
    finally:
        config.settings.api_key      = orig_key
        config.settings.database_url = orig_url
        config.settings.debug        = orig_debug
        database._pool               = None

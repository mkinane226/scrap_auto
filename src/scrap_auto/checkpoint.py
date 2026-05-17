from __future__ import annotations

from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    status_code INTEGER,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    error_message TEXT
);
"""


class CheckpointManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def setup(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute(_SCHEMA)
            await db.commit()

    async def is_seen(self, url: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT 1 FROM seen_urls WHERE url = ? AND status_code = 200",
                (url,),
            )
            return await cur.fetchone() is not None

    async def mark_seen(self, url: str, status_code: int, error: str | None = None) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO seen_urls (url, status_code, error_message) VALUES (?, ?, ?)",
                (url, status_code, error),
            )
            await db.commit()

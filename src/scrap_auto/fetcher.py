from __future__ import annotations

import asyncio
import random

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .settings import CrawlConfig


class Fetcher:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.client = httpx.AsyncClient(
            timeout=config.timeout_seconds,
            headers={"User-Agent": config.user_agent},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, asyncio.TimeoutError)),
    )
    async def get_text(self, url: str) -> str:
        await asyncio.sleep(random.uniform(self.config.min_delay_seconds, self.config.max_delay_seconds))
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text

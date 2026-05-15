from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from rich.console import Console

from .fetcher import Fetcher
from .parser import (
    parse_article_details,
    parse_articles_list,
    parse_car_types_table,
    parse_category_groups,
    parse_manufacturers,
    parse_model_series,
)
from .settings import CrawlConfig, CrawlLimits
from .storage import JsonlStore
from .url_patterns import (
    is_in_scope,
    parse_article_details_url,
    parse_category_page_url,
    parse_list_articles_url,
    parse_manufacturer_url,
    parse_model_series_url,
)

console = Console()


class Crawler:
    def __init__(self, config: CrawlConfig, limits: CrawlLimits) -> None:
        self.config = config
        self.limits = limits
        self.store = JsonlStore(config.output_dir)
        self.fetcher = Fetcher(config)
        self.sem = asyncio.Semaphore(config.concurrency)

    async def close(self) -> None:
        await self.fetcher.close()

    async def crawl(self) -> dict[str, int]:
        counters: dict[str, int] = {
            "manufacturers": 0,
            "models": 0,
            "car_types": 0,
            "category_groups": 0,
            "articles": 0,
            "article_details": 0,
            "failed_requests": 0,
        }
        records_written = 0

        start_url = (
            f"{self.config.base_url}/manufacturers/"
            f"lang-id-{self.config.lang_id}/country-filter-id-{self.config.country_id}/type-id-{self.config.type_id}"
        )

        manufacturers_html = await self._try_fetch(start_url, counters)
        if not manufacturers_html:
            return counters

        manufacturers = parse_manufacturers(manufacturers_html, self.config.base_url)
        manufacturers = self._limit(manufacturers, self.limits.max_manufacturers)
        if self.config.verbose:
            console.print(f"[cyan]Manufacturers discovered:[/cyan] {len(manufacturers)}")

        for manufacturer in manufacturers:
            ids = parse_manufacturer_url(manufacturer["url"])
            if not ids:
                continue
            if self.config.verbose:
                console.print(
                    "[cyan]Manufacturer[/cyan]"
                    f" id={ids.values.get('manufacturer_id')}"
                    f" name={manufacturer.get('name', '')}"
                )
            record = {**manufacturer, **ids.values}
            self.store.append("manufacturers", record)
            counters["manufacturers"] += 1
            records_written += 1
            self._maybe_log_progress(counters, records_written)

            models_html = await self._try_fetch(manufacturer["url"], counters)
            if not models_html:
                continue

            model_series = parse_model_series(models_html, self.config.base_url)
            model_series = self._limit(model_series, self.limits.max_models_per_manufacturer)

            for model in model_series:
                ids_m = parse_model_series_url(model["url"])
                if not ids_m:
                    continue
                model_record = {**model, **ids_m.values}
                self.store.append("models", model_record)
                counters["models"] += 1
                records_written += 1
                self._maybe_log_progress(counters, records_written)

                car_types_html = await self._try_fetch(model["url"], counters)
                if not car_types_html:
                    continue

                car_types = parse_car_types_table(car_types_html, self.config.base_url)
                car_types = self._limit(car_types, self.limits.max_car_types_per_model)

                for car_type in car_types:
                    if not car_type.get("category_url"):
                        continue
                    self.store.append("car_types", car_type)
                    counters["car_types"] += 1
                    records_written += 1
                    self._maybe_log_progress(counters, records_written)

                    category_url = str(car_type["category_url"])
                    ids_c = parse_category_page_url(category_url)
                    if not ids_c:
                        continue

                    category_html = await self._try_fetch(category_url, counters)
                    if not category_html:
                        continue

                    groups = parse_category_groups(category_html, self.config.base_url)
                    groups = self._limit(groups, self.limits.max_groups_per_car_type)

                    for group in groups:
                        list_url = str(group["list_articles_url"])
                        ids_g = parse_list_articles_url(list_url)
                        if not ids_g:
                            continue

                        group_record = {**group, **ids_g.values}
                        self.store.append("category_groups", group_record)
                        counters["category_groups"] += 1
                        records_written += 1
                        self._maybe_log_progress(counters, records_written)

                        articles_html = await self._try_fetch(list_url, counters)
                        if not articles_html:
                            continue

                        articles = parse_articles_list(articles_html, self.config.base_url)
                        articles = self._limit(articles, self.limits.max_articles_per_group)

                        for article in articles:
                            ids_a = parse_article_details_url(article["details_url"])
                            if not ids_a:
                                continue

                            article_record = {**article, **ids_a.values}
                            self.store.append("articles", article_record)
                            counters["articles"] += 1
                            records_written += 1
                            self._maybe_log_progress(counters, records_written)

                            details_html = await self._try_fetch(article["details_url"], counters)
                            if not details_html:
                                continue

                            details = parse_article_details(details_html, self.config.base_url)
                            self.store.append(
                                "article_details",
                                {
                                    "article_id": ids_a.values["article_id"],
                                    "details_url": article["details_url"],
                                    **details,
                                },
                            )
                            counters["article_details"] += 1
                            records_written += 1
                            self._maybe_log_progress(counters, records_written)

        return counters

    async def _fetch(self, url: str) -> str:
        if not is_in_scope(url, self.config.lang_id, self.config.country_id, self.config.type_id):
            raise ValueError(f"Out-of-scope URL blocked: {url}")
        async with self.sem:
            return await self.fetcher.get_text(url)

    async def _try_fetch(self, url: str, counters: dict[str, int]) -> str | None:
        try:
            return await self._fetch(url)
        except Exception as exc:  # noqa: BLE001
            counters["failed_requests"] += 1
            console.print(f"[yellow]Fetch failed[/yellow] {url} :: {exc}")
            return None

    def _maybe_log_progress(self, counters: dict[str, int], records_written: int) -> None:
        if not self.config.verbose:
            return
        if records_written % self.config.progress_every != 0:
            return
        console.print(
            "[green]Progress[/green] "
            f"records={records_written} "
            f"manufacturers={counters['manufacturers']} "
            f"models={counters['models']} "
            f"car_types={counters['car_types']} "
            f"groups={counters['category_groups']} "
            f"articles={counters['articles']} "
            f"details={counters['article_details']} "
            f"failed_requests={counters['failed_requests']}"
        )

    @staticmethod
    def _limit(items: list[dict[str, Any]], cap: int | None) -> list[dict[str, Any]]:
        if cap is None:
            return items
        return items[:cap]


def config_to_dict(config: CrawlConfig, limits: CrawlLimits) -> dict[str, Any]:
    return {"config": asdict(config), "limits": asdict(limits)}

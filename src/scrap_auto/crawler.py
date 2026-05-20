from __future__ import annotations

import asyncio
import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from rich.console import Console

from .fetcher import Fetcher
from .parser import (
    parse_article_details,
    parse_articles_list,
    parse_car_type_details,
    parse_car_types_table,
    parse_category_groups,
    parse_manufacturers,
    parse_model_series,
)
from .checkpoint import CheckpointManager
from .settings import CrawlConfig, CrawlLimits
from .storage import JsonlStore
from .url_patterns import (
    is_in_scope,
    normalize_url,
    parse_article_details_url,
    parse_car_type_details_url,
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
        self._manufacturer_allowlist = self._load_manufacturer_allowlist(config.manufacturers_file)
        checkpoint_db = config.output_dir / "checkpoint.db"
        self.checkpoint = CheckpointManager(checkpoint_db)
        # In-memory dedup for navigation pages within one session.
        # Navigation pages bypass the cross-session checkpoint so that children
        # not yet processed in a previous session are always discovered.
        self._session_fetched: set[str] = set()

    async def close(self) -> None:
        await self.fetcher.close()
        self.store.close()

    async def crawl(self) -> dict[str, int]:
        await self.checkpoint.setup()

        counters: dict[str, int] = {
            "manufacturers": 0,
            "manufacturers_filtered": 0,
            "models": 0,
            "car_types": 0,
            "car_type_details": 0,
            "filtered_car_types": 0,
            "category_groups": 0,
            "articles": 0,
            "article_details": 0,
            "failed_requests": 0,
            "records_written": 0,
            "skipped_seen": 0,
        }

        start_url = (
            f"{self.config.base_url}/manufacturers/"
            f"lang-id-{self.config.lang_id}/country-filter-id-{self.config.country_id}/type-id-{self.config.type_id}"
        )

        manufacturers_html = await self._fetch_navigation(start_url, counters)
        if not manufacturers_html:
            return counters

        manufacturers = parse_manufacturers(manufacturers_html, self.config.base_url)
        if self._manufacturer_allowlist:
            allowed = []
            for manufacturer in manufacturers:
                if self._is_allowed_manufacturer(str(manufacturer.get("name", ""))):
                    allowed.append(manufacturer)
                else:
                    counters["manufacturers_filtered"] += 1
            manufacturers = allowed
        manufacturers = self._limit(manufacturers, self.limits.max_manufacturers)
        if self.config.verbose:
            console.print(f"[cyan]Manufacturers discovered:[/cyan] {len(manufacturers)}")

        async with asyncio.TaskGroup() as tg:
            for manufacturer in manufacturers:
                tg.create_task(self._crawl_manufacturer(manufacturer, counters))

        return counters

    async def _crawl_manufacturer(self, manufacturer: dict[str, Any], counters: dict[str, int]) -> None:
        ids = parse_manufacturer_url(manufacturer["url"])
        if not ids:
            return
        if self.config.verbose:
            console.print(
                "[cyan]Manufacturer[/cyan]"
                f" id={ids.values.get('manufacturer_id')}"
                f" name={manufacturer.get('name', '')}"
            )
        record = {**manufacturer, **ids.values}
        self.store.append("manufacturers", record)
        counters["manufacturers"] += 1
        counters["records_written"] += 1
        self._maybe_log_progress(counters)

        models_html = await self._fetch_navigation(manufacturer["url"], counters)
        if not models_html:
            return

        model_series = parse_model_series(models_html, self.config.base_url)
        model_series = self._limit(model_series, self.limits.max_models_per_manufacturer)

        for model in model_series:
            await self._crawl_model(model, counters)

    async def _crawl_model(self, model: dict[str, Any], counters: dict[str, int]) -> None:
        ids_m = parse_model_series_url(model["url"])
        if not ids_m:
            return
        model_record = {
            **model,
            **ids_m.values,
            "lang_id": self.config.lang_id,
            "country_id": self.config.country_id,
            "type_id": self.config.type_id,
        }
        self.store.append("models", model_record)
        counters["models"] += 1
        counters["records_written"] += 1
        self._maybe_log_progress(counters)

        car_types_html = await self._fetch_navigation(model["url"], counters)
        if not car_types_html:
            return

        car_types = parse_car_types_table(car_types_html, self.config.base_url)
        car_types = self._limit(car_types, self.limits.max_car_types_per_model)

        for car_type in car_types:
            details_url = str(car_type.get("details_url") or "")
            car_type_details: dict[str, Any] | None = None
            details_ids = parse_car_type_details_url(details_url) if details_url else None

            if details_url and details_ids:
                details_html = await self._try_fetch(details_url, counters)
                if details_html:
                    car_type_details = parse_car_type_details(details_html)

            year_to = car_type.get("year_to")
            if year_to is None and car_type_details is not None:
                year_to = car_type_details.get("year_to")

            if self._should_skip_year_to(year_to):
                counters["filtered_car_types"] += 1
                if counters["filtered_car_types"] <= 10:
                    console.print(
                        f"[yellow]DBG filtered[/yellow] year_to={year_to!r}"
                        f" year_range={car_type.get('year_range')!r}"
                        f" type_label={car_type.get('type_label')!r}"
                    )
                continue

            if not car_type.get("category_url"):
                continue

            url_car_type_id = details_ids.values["car_type_id"] if details_ids else None
            cell_car_type_id = car_type.get("car_type_id")
            if url_car_type_id is not None and cell_car_type_id is not None and url_car_type_id != cell_car_type_id:
                console.print(
                    f"[yellow]car_type_id mismatch[/yellow] cell={cell_car_type_id} url={url_car_type_id}"
                    f" — using URL value"
                )
            authoritative_car_type_id = url_car_type_id if url_car_type_id is not None else cell_car_type_id

            car_type_record = {
                **car_type,
                "car_type_id": authoritative_car_type_id,
                "model_series_id": ids_m.values["model_series_id"],
                "manufacturer_id": ids_m.values["manufacturer_id"],
                "lang_id": self.config.lang_id,
                "country_id": self.config.country_id,
                "type_id": self.config.type_id,
            }
            self.store.append("car_types", car_type_record)
            counters["car_types"] += 1
            counters["records_written"] += 1
            self._maybe_log_progress(counters)

            if car_type_details and details_ids:
                self.store.append(
                    "car_type_details",
                    {
                        "car_type_id": details_ids.values["car_type_id"],
                        "manufacturer_id": details_ids.values["manufacturer_id"],
                        "model_series_id": ids_m.values["model_series_id"],
                        "lang_id": self.config.lang_id,
                        "country_id": self.config.country_id,
                        "type_id": self.config.type_id,
                        "details_url": details_url,
                        **car_type_details,
                    },
                )
                counters["car_type_details"] += 1
                counters["records_written"] += 1
                self._maybe_log_progress(counters)

            if self.limits.max_groups_per_car_type == 0:
                continue

            category_url = str(car_type["category_url"])
            ids_c = parse_category_page_url(category_url)
            if not ids_c:
                continue

            category_html = await self._fetch_navigation(category_url, counters)
            if not category_html:
                continue

            groups = parse_category_groups(category_html, self.config.base_url)
            groups = self._limit(groups, self.limits.max_groups_per_car_type)

            for group in groups:
                list_url = str(group["list_articles_url"])
                ids_g = parse_list_articles_url(list_url)
                if not ids_g:
                    continue

                group_record = {
                    **group,
                    **ids_g.values,
                    "model_series_id": ids_m.values["model_series_id"],
                    "lang_id": self.config.lang_id,
                    "country_id": self.config.country_id,
                    "type_id": self.config.type_id,
                }
                self.store.append("category_groups", group_record)
                counters["category_groups"] += 1
                counters["records_written"] += 1
                self._maybe_log_progress(counters)

                oem_url = str(group.get("list_oem_articles_url", ""))
                article_list_urls: list[tuple[str, bool]] = [(list_url, False)]
                if oem_url:
                    article_list_urls.append((oem_url, True))

                for articles_fetch_url, is_oem in article_list_urls:
                    articles_html = await self._try_fetch(articles_fetch_url, counters)
                    if not articles_html:
                        continue

                    articles = parse_articles_list(articles_html, self.config.base_url)
                    articles = self._limit(articles, self.limits.max_articles_per_group)

                    for article in articles:
                        ids_a = parse_article_details_url(article["details_url"])
                        if not ids_a:
                            continue

                        article_record = {
                            **article,
                            **ids_a.values,
                            "group_id": ids_g.values["group_id"],
                            "car_type_id": ids_g.values["car_type_id"],
                            "lang_id": self.config.lang_id,
                            "country_id": self.config.country_id,
                            "type_id": self.config.type_id,
                            "is_oem": is_oem,
                        }
                        self.store.append("articles", article_record)
                        counters["articles"] += 1
                        counters["records_written"] += 1
                        self._maybe_log_progress(counters)

                        details_html = await self._try_fetch(article["details_url"], counters)
                        if not details_html:
                            continue

                        details = parse_article_details(details_html, self.config.base_url)
                        self.store.append(
                            "article_details",
                            {
                                "article_id": ids_a.values["article_id"],
                                "model_series_id": ids_a.values["model_series_id"],
                                "manufacturer_id": ids_a.values["manufacturer_id"],
                                "group_id": ids_g.values["group_id"],
                                "car_type_id": ids_g.values["car_type_id"],
                                "lang_id": self.config.lang_id,
                                "country_id": self.config.country_id,
                                "type_id": self.config.type_id,
                                "details_url": article["details_url"],
                                **details,
                            },
                        )
                        counters["article_details"] += 1
                        counters["records_written"] += 1
                        self._maybe_log_progress(counters)

    async def _fetch(self, url: str) -> str:
        normalized_url = normalize_url(url)
        if not is_in_scope(normalized_url, self.config.lang_id, self.config.country_id, self.config.type_id):
            raise ValueError(f"Out-of-scope URL blocked: {normalized_url}")
        async with self.sem:
            return await self.fetcher.get_text(normalized_url)

    async def _fetch_navigation(self, url: str, counters: dict[str, int]) -> str | None:
        """Fetch a navigation/index page, bypassing the cross-session checkpoint.

        Navigation pages must always be re-traversed so children not yet
        processed in a previous session are still discovered. Within a single
        session each URL is fetched at most once via _session_fetched.
        """
        normalized = normalize_url(url)
        if normalized in self._session_fetched:
            counters["skipped_seen"] += 1
            return None
        try:
            text = await self._fetch(url)
            self._session_fetched.add(normalized)
            await self.checkpoint.mark_seen(normalized, 200)
            return text
        except (httpx.HTTPError, httpx.RequestError, asyncio.TimeoutError, ValueError) as exc:
            counters["failed_requests"] += 1
            console.print(f"[yellow]Fetch failed[/yellow] {url} :: {exc}")
            await self.checkpoint.mark_seen(normalized, 0, str(exc))
            return None

    async def _try_fetch(self, url: str, counters: dict[str, int]) -> str | None:
        normalized = normalize_url(url)
        if await self.checkpoint.is_seen(normalized):
            counters["skipped_seen"] += 1
            return None
        try:
            text = await self._fetch(url)
            await self.checkpoint.mark_seen(normalized, 200)
            return text
        except (httpx.HTTPError, httpx.RequestError, asyncio.TimeoutError, ValueError) as exc:
            counters["failed_requests"] += 1
            console.print(f"[yellow]Fetch failed[/yellow] {url} :: {exc}")
            await self.checkpoint.mark_seen(normalized, 0, str(exc))
            return None

    def _maybe_log_progress(self, counters: dict[str, int]) -> None:
        if not self.config.verbose:
            return
        records_written = counters["records_written"]
        if records_written % self.config.progress_every != 0:
            return
        console.print(
            "[green]Progress[/green] "
            f"records={records_written} "
            f"manufacturers={counters['manufacturers']} "
            f"manufacturers_filtered={counters['manufacturers_filtered']} "
            f"models={counters['models']} "
            f"car_types={counters['car_types']} "
            f"car_type_details={counters['car_type_details']} "
            f"filtered_car_types={counters['filtered_car_types']} "
            f"groups={counters['category_groups']} "
            f"articles={counters['articles']} "
            f"details={counters['article_details']} "
            f"failed_requests={counters['failed_requests']}"
        )

    def _should_skip_year_to(self, year_to: Any) -> bool:
        if year_to in (None, ""):
            return False
        if isinstance(year_to, str):
            value = year_to.strip()
            if not value:
                return False
            if not value.isdigit():
                return False
            year_to_int = int(value)
        elif isinstance(year_to, int):
            year_to_int = year_to
        else:
            return False

        return year_to_int < self.config.min_year_to_include

    def _is_allowed_manufacturer(self, candidate: str) -> bool:
        if not self._manufacturer_allowlist:
            return True

        normalized_candidate = _normalize_manufacturer_name(candidate)
        if not normalized_candidate:
            return False
        compact_candidate = _compact_name(normalized_candidate)

        allowlist = self._manufacturer_allowlist
        if normalized_candidate in allowlist.exact:
            return True
        if compact_candidate in allowlist.compact:
            return True

        for key in _candidate_prefix_keys(compact_candidate):
            for allowed in allowlist.by_prefix.get(key, []):
                if _is_similar_name(normalized_candidate, compact_candidate, allowed):
                    return True

        return False

    @staticmethod
    def _load_manufacturer_allowlist(file_path: Path | None) -> _ManufacturerAllowlist | None:
        if file_path is None:
            return None
        if not file_path.exists():
            raise FileNotFoundError(f"Manufacturers allowlist file not found: {file_path}")

        raw = _read_text_lines(file_path)
        out: set[str] = set()
        for line in raw:
            if not line.strip() or line.strip().startswith("#"):
                continue
            normalized = _normalize_manufacturer_name(line)
            if normalized:
                out.add(normalized)
        if not out:
            return None

        entries = [_AllowedManufacturer(name=n, compact=_compact_name(n)) for n in sorted(out)]
        by_prefix: dict[str, list[_AllowedManufacturer]] = {}
        for entry in entries:
            for key in _candidate_prefix_keys(entry.compact):
                by_prefix.setdefault(key, []).append(entry)

        return _ManufacturerAllowlist(
            exact=out,
            compact={e.compact for e in entries},
            entries=entries,
            by_prefix=by_prefix,
        )

    @staticmethod
    def _limit(items: list[dict[str, Any]], cap: int | None) -> list[dict[str, Any]]:
        if cap is None:
            return items
        return items[:cap]


def config_to_dict(config: CrawlConfig, limits: CrawlLimits) -> dict[str, Any]:
    return {"config": asdict(config), "limits": asdict(limits)}


def _normalize_manufacturer_name(name: str) -> str:
    if not name:
        return ""
    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _compact_name(name: str) -> str:
    return name.replace(" ", "")


def _candidate_prefix_keys(name: str) -> list[str]:
    if not name:
        return []
    keys: list[str] = []
    for size in (3, 2, 1):
        if len(name) >= size:
            keys.append(name[:size])
    return keys


def _is_similar_name(candidate_name: str, candidate_compact: str, allowed: _AllowedManufacturer) -> bool:
    if candidate_name == allowed.name or candidate_compact == allowed.compact:
        return True

    if len(candidate_name) >= 5 and (candidate_name in allowed.name or allowed.name in candidate_name):
        return True

    if abs(len(candidate_compact) - len(allowed.compact)) > 2:
        return False

    return difflib.SequenceMatcher(None, candidate_compact, allowed.compact).ratio() >= 0.93


def _read_text_lines(path: Path) -> list[str]:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return path.read_text(encoding=encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1").splitlines()


@dataclass(slots=True)
class _AllowedManufacturer:
    name: str
    compact: str


@dataclass(slots=True)
class _ManufacturerAllowlist:
    exact: set[str]
    compact: set[str]
    entries: list[_AllowedManufacturer]
    by_prefix: dict[str, list[_AllowedManufacturer]]

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import orjson

import typer
from rich import print

from .crawler import Crawler, config_to_dict
from .settings import CrawlConfig, CrawlLimits
from .url_patterns import (
    parse_article_details_url,
    parse_category_page_url,
    parse_list_articles_url,
    parse_manufacturer_url,
    parse_model_series_url,
)

app = typer.Typer(help="scrap_auto command line")


@app.command()
def crawl(
    lang_id: int = 6,
    country_id: int = 145,
    type_id: int = 1,
    max_manufacturers: int | None = None,
    max_models_per_manufacturer: int | None = None,
    max_car_types_per_model: int | None = None,
    max_groups_per_car_type: int | None = None,
    max_articles_per_group: int | None = None,
    verbose: bool = typer.Option(False, help="Print live progress while crawling."),
    progress_every: int = typer.Option(25, min=1, help="Report progress every N records."),
) -> None:
    config = CrawlConfig(
        lang_id=lang_id,
        country_id=country_id,
        type_id=type_id,
        verbose=verbose,
        progress_every=progress_every,
    )
    limits = CrawlLimits(
        max_manufacturers=max_manufacturers,
        max_models_per_manufacturer=max_models_per_manufacturer,
        max_car_types_per_model=max_car_types_per_model,
        max_groups_per_car_type=max_groups_per_car_type,
        max_articles_per_group=max_articles_per_group,
    )

    print("[bold]Running crawl with:[/bold]", config_to_dict(config, limits))

    async def _run() -> None:
        crawler = Crawler(config, limits)
        try:
            counters = await crawler.crawl()
            print("[bold green]Done[/bold green]", counters)
        finally:
            await crawler.close()

    asyncio.run(_run())


@app.command()
def validate() -> None:
    samples = {
        "manufacturer": "https://auto-parts-catalog.makingdatameaningful.com/models/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
        "model_series": "https://auto-parts-catalog.makingdatameaningful.com/passenger-car-types/53/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
        "category": "https://auto-parts-catalog.makingdatameaningful.com/list-category-products-groups/1146/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
        "list_articles": "https://auto-parts-catalog.makingdatameaningful.com/list-articles/1146/100253/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
        "article_details": "https://auto-parts-catalog.makingdatameaningful.com/article-details/8373643/model-series-id-53/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
    }

    checks = {
        "manufacturer": parse_manufacturer_url(samples["manufacturer"]),
        "model_series": parse_model_series_url(samples["model_series"]),
        "category": parse_category_page_url(samples["category"]),
        "list_articles": parse_list_articles_url(samples["list_articles"]),
        "article_details": parse_article_details_url(samples["article_details"]),
    }

    bad = [k for k, v in checks.items() if v is None]
    if bad:
        raise typer.Exit(code=1)

    print("[green]Validation passed[/green]")
    for name, parsed in checks.items():
        print(name, parsed.values if parsed else None)


@app.command("export-images")
def export_images(
    details_file: str = "data/article_details.jsonl",
    output_dir: str = "data/images",
    manifest_file: str = "data/images_manifest.jsonl",
    concurrency: int = 8,
) -> None:
    details_path = Path(details_file)
    if not details_path.exists():
        raise typer.BadParameter(f"Details file not found: {details_file}")

    images = _collect_images(details_path)
    print(f"Found {len(images)} image references")

    async def _run() -> None:
        await _download_images(images, Path(output_dir), Path(manifest_file), concurrency)

    asyncio.run(_run())


def _collect_images(details_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    with details_path.open("rb") as f:
        for line in f:
            if not line.strip():
                continue
            record = orjson.loads(line)
            article_id = int(record.get("article_id", 0) or 0)
            for idx, url in enumerate(record.get("image_urls", []), start=1):
                if not url:
                    continue
                key = (article_id, str(url))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"article_id": article_id, "image_index": idx, "url": str(url)})

    return out


async def _download_images(
    images: list[dict[str, Any]],
    output_dir: Path,
    manifest_path: Path,
    concurrency: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(30.0)
    headers = {"User-Agent": "scrap-auto-image-export/0.1"}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        async def _one(item: dict[str, Any]) -> dict[str, Any]:
            url = item["url"]
            article_id = int(item["article_id"])
            image_index = int(item["image_index"])
            ext = _guess_ext(url)

            file_name = f"article_{article_id}_img_{image_index}{ext}"
            shard = str(article_id % 1000).zfill(3)
            folder = output_dir / shard
            folder.mkdir(parents=True, exist_ok=True)
            file_path = folder / file_name

            if file_path.exists() and file_path.stat().st_size > 0:
                return {
                    "article_id": article_id,
                    "image_index": image_index,
                    "url": url,
                    "status": "cached",
                    "path": str(file_path).replace("\\", "/"),
                    "bytes": file_path.stat().st_size,
                }

            async with sem:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    file_path.write_bytes(resp.content)
                    return {
                        "article_id": article_id,
                        "image_index": image_index,
                        "url": url,
                        "status": "downloaded",
                        "path": str(file_path).replace("\\", "/"),
                        "bytes": len(resp.content),
                    }
                except Exception as exc:  # noqa: BLE001
                    return {
                        "article_id": article_id,
                        "image_index": image_index,
                        "url": url,
                        "status": "error",
                        "error": str(exc),
                    }

        results = await asyncio.gather(*[_one(i) for i in images])

    downloaded = 0
    cached = 0
    errors = 0
    with manifest_path.open("ab") as f:
        for row in results:
            f.write(orjson.dumps(row))
            f.write(b"\n")
            status = row.get("status")
            if status == "downloaded":
                downloaded += 1
            elif status == "cached":
                cached += 1
            else:
                errors += 1

    print(
        "Image export complete:",
        {
            "downloaded": downloaded,
            "cached": cached,
            "errors": errors,
            "manifest": str(manifest_path).replace("\\", "/"),
        },
    )


def _guess_ext(url: str) -> str:
    lowered = url.lower()
    for ext in [".webp", ".jpg", ".jpeg", ".png", ".gif", ".avif"]:
        if lowered.endswith(ext):
            return ext
    return ".bin"


if __name__ == "__main__":
    app()

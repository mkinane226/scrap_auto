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
    parse_car_type_details_url,
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
    min_year_to_include: int = typer.Option(
        2006,
        min=1900,
        help="Skip extraction for car types where manufacturing end year is lower than this value.",
    ),
    manufacturers_file: Path | None = typer.Option(
        None,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=False,
        help="Only crawl manufacturers equal or similar to names listed in this file. If omitted, all manufacturers are crawled.",
    ),
    verbose: bool = typer.Option(False, help="Print live progress while crawling."),
    progress_every: int = typer.Option(25, min=1, help="Report progress every N records."),
) -> None:
    config = CrawlConfig(
        lang_id=lang_id,
        country_id=country_id,
        type_id=type_id,
        min_year_to_include=min_year_to_include,
        manufacturers_file=manufacturers_file,
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
        "car_type_details": "https://auto-parts-catalog.makingdatameaningful.com/passenger-car-type-details/12424/manufacturer-id-609/lang-id-6/country-filter-id-145",
        "category": "https://auto-parts-catalog.makingdatameaningful.com/list-category-products-groups/1146/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
        "list_articles": "https://auto-parts-catalog.makingdatameaningful.com/list-articles/1146/100253/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
        "article_details": "https://auto-parts-catalog.makingdatameaningful.com/article-details/8373643/model-series-id-53/manufacturer-id-5/lang-id-6/country-filter-id-145/type-id-1",
    }

    checks = {
        "manufacturer": parse_manufacturer_url(samples["manufacturer"]),
        "model_series": parse_model_series_url(samples["model_series"]),
        "car_type_details": parse_car_type_details_url(samples["car_type_details"]),
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


def _convert_jsonl_streaming(src: Path, dest: Path, batch_size: int = 500) -> None:
    """Read JSONL in fixed-size batches and write Parquet incrementally via PyArrow.

    Used as a fallback when DuckDB OOMs on large files (e.g. article_details).
    Peak RAM per call is proportional to batch_size rows, not file size.
    """
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    writer: pq.ParquetWriter | None = None
    batch: list[dict] = []

    try:
        with src.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                batch.append(json.loads(line))
                if len(batch) >= batch_size:
                    table = pa.Table.from_pylist(batch)
                    if writer is None:
                        writer = pq.ParquetWriter(dest, table.schema, compression="zstd")
                    writer.write_table(table)
                    batch.clear()

        if batch:
            table = pa.Table.from_pylist(batch)
            if writer is None:
                writer = pq.ParquetWriter(dest, table.schema, compression="zstd")
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()


@app.command()
def convert(
    data_dir: str = typer.Option("data", help="Directory containing JSONL output files."),
    output_dir: str = typer.Option("data/parquet", help="Directory for Parquet output."),
    crawl_date: str = typer.Option("", help="Crawl date label for partition (e.g. 2026-05-16). Defaults to today."),
    memory_limit: str = typer.Option("3GB", help="DuckDB memory limit. Excess spills to temp dir."),
    temp_dir: str = typer.Option("/tmp/duckdb_convert", help="Temp dir for DuckDB spill-to-disk."),
) -> None:
    """Convert JSONL output files to partitioned Parquet using DuckDB (spills to disk, handles any size)."""
    import datetime
    import duckdb

    from rich.console import Console as RichConsole

    console = RichConsole()

    if not crawl_date:
        crawl_date = datetime.date.today().isoformat()

    data_path = Path(data_dir)
    out_path = Path(output_dir)
    Path(temp_dir).mkdir(parents=True, exist_ok=True)

    entity_types = [
        "manufacturers",
        "models",
        "car_types",
        "car_type_details",
        "category_groups",
        "articles",
        "article_details",
    ]

    for entity in entity_types:
        src = data_path / f"{entity}.jsonl"
        if not src.exists():
            console.print(f"[yellow]Skipping {entity} — {src} not found[/yellow]")
            continue

        partition_dir = out_path / f"entity_type={entity}" / f"crawl_date={crawl_date}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        dest = partition_dir / "part-0.parquet"

        console.print(f"[cyan]Converting[/cyan] {src} → {dest}")
        try:
            con = duckdb.connect()
            con.execute(f"SET memory_limit='{memory_limit}'")
            con.execute(f"SET temp_directory='{temp_dir}'")
            con.execute("SET preserve_insertion_order=false")
            con.execute("SET threads=2")
            con.execute(f"""
                COPY (
                    SELECT * FROM read_ndjson(
                        '{src}',
                        auto_detect=True,
                        maximum_object_size=33554432
                    )
                )
                TO '{dest}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
            con.close()
            console.print(f"[green]Done[/green] {entity}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]DuckDB failed ({exc.__class__.__name__}), retrying with PyArrow streaming...[/yellow]")
            try:
                _convert_jsonl_streaming(src, dest)
                console.print(f"[green]Done[/green] {entity} [dim](streaming fallback)[/dim]")
            except Exception as exc2:  # noqa: BLE001
                console.print(f"[red]Failed {entity}[/red] :: {exc2}")

    console.print("[bold green]Conversion complete[/bold green]")


@app.command()
def load(
    database_url: str = typer.Option(
        ...,
        envvar="AUTOPARTS_DATABASE_URL",
        help="PostgreSQL connection string. E.g. postgresql://user:pass@localhost/autoparts",
    ),
    data_dir: Path = typer.Option(Path("data"), help="Directory containing Parquet output files."),
    init: bool = typer.Option(False, "--init", help="Create database schema before loading."),
    grant_api: bool = typer.Option(
        False, "--grant-api", help="Grant SELECT to autoparts_api role after loading."
    ),
    batch_size: int = typer.Option(1000, help="Rows per batch for UPSERT."),
) -> None:
    """Load deduped Parquet files into PostgreSQL (run after 'scrap-auto dedup')."""
    from rich.console import Console as RichConsole

    from .loader import load_all

    console = RichConsole()
    db_display = database_url.split("@")[-1] if "@" in database_url else database_url
    console.print(f"[bold]Loading data:[/bold] {data_dir} → {db_display}")
    load_all(database_url, data_dir, batch_size, init, grant_api, console)


def _dedup_streaming(glob_pattern: str, pk: str, out_path: str, console: Any) -> None:
    """PyArrow streaming dedup — reads one parquet file at a time, O(n_unique_ids) memory.

    Files are sorted newest-first so the most recent crawl round wins when
    the same pk appears in multiple rounds.
    """
    import glob as _glob
    import pyarrow as pa
    import pyarrow.parquet as pq

    files = sorted(_glob.glob(glob_pattern, recursive=True), reverse=True)
    if not files:
        console.print(f"[yellow]  No parquet files found: {glob_pattern}[/yellow]")
        return

    seen: set[Any] = set()
    writer: pq.ParquetWriter | None = None
    skipped = 0
    total = 0

    for fpath in files:
        try:
            pf = pq.ParquetFile(fpath)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]  SKIP (bad file): {fpath} — {exc}[/yellow]")
            skipped += 1
            continue

        # Read in batches so large files (multi-GB parquet) never load fully into RAM.
        for batch in pf.iter_batches(batch_size=500):
            table = pa.Table.from_batches([batch])
            if table.num_rows == 0:
                continue
            pk_vals = table.column(pk).to_pylist()
            mask = []
            for v in pk_vals:
                if v not in seen:
                    seen.add(v)
                    mask.append(True)
                else:
                    mask.append(False)
            filtered = table.filter(pa.array(mask))
            if filtered.num_rows > 0:
                if writer is None:
                    writer = pq.ParquetWriter(out_path, filtered.schema, compression="zstd")
                writer.write_table(filtered)
                total += filtered.num_rows

    if writer:
        writer.close()

    suffix = f", {skipped} bad files skipped" if skipped else ""
    console.print(
        f"[green]Done[/green] → {out_path} ({total} rows, {len(seen)} unique {pk}{suffix})"
    )


@app.command("dedup")
def dedup(
    data_dir: str = typer.Option("data/parquet", help="Parquet data directory."),
    memory_limit: str = typer.Option("4GB", help="DuckDB memory limit."),
    temp_dir: str = typer.Option("/tmp/duckdb_dedup", help="Temp dir for DuckDB spill-to-disk."),
) -> None:
    """Deduplicate articles and article_details by article_id using DuckDB."""
    import duckdb

    from rich.console import Console as RichConsole

    console = RichConsole()
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET temp_directory='{temp_dir}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=2")

    entity_pk = [
        ("manufacturers",    "manufacturer_id"),
        ("models",           "model_series_id"),
        ("car_types",        "car_type_id"),
        ("car_type_details", "car_type_id"),
        ("category_groups",  "group_id"),
        ("articles",         "article_id"),
        ("article_details",  "article_id"),
    ]
    for entity, pk in entity_pk:
        glob_pat = f"{data_dir}/entity_type={entity}/**/*.parquet"
        out = f"{data_dir}/{entity}_deduped.parquet"
        console.print(f"[cyan]Deduplicating[/cyan] {entity}")
        try:
            con.execute(
                f"COPY (SELECT DISTINCT ON ({pk}) * FROM read_parquet('{glob_pat}', hive_partitioning=false)"
                f" ORDER BY {pk})"
                f" TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            console.print(f"[green]Done[/green] → {out}")
        except Exception as exc:  # noqa: BLE001
            if "Out of Memory" in str(exc):
                console.print(f"[yellow]  OOM — retrying {entity} with streaming dedup...[/yellow]")
                try:
                    _dedup_streaming(glob_pat, pk, out, console)
                except Exception as exc2:  # noqa: BLE001
                    console.print(f"[red]Failed {entity} (streaming)[/red] :: {exc2}")
            else:
                console.print(f"[red]Failed {entity}[/red] :: {exc}")

    con.close()
    console.print("[bold green]Dedup complete[/bold green]")


if __name__ == "__main__":
    app()

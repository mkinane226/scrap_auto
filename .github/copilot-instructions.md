# Copilot instructions for scrap_auto

## Mission
Build a resilient crawler for auto-parts-catalog.makingdatameaningful.com with strict URL filtering by lang_id, country_id, and type_id.

## Hard constraints

- Never crawl outside the target domain.
- Follow only URLs that preserve configured lang_id/country_id/type_id.
- Scope guard uses regex matching (not substring) to avoid false positives on sequential IDs.
- Keep crawl polite: 300ms–1000ms random delay per request, max 5 concurrent requests.
- Retry with exponential backoff on all HTTP errors and timeouts (tenacity, 4 attempts).
- Prefer URL ID parsing over blob/text scraping. article_id comes from the URL path, not regex on blob text.
- Keep data normalized by stable IDs.
- Include passenger-car-types and passenger-car-type-details coverage.
- Apply year_to filter: do not extract type/category/article branches when year_to < 2006. Handle formats: "2005", "01/2005", "2005-01".
- Treat empty/null year_to as still in production.
- Persist explicit foreign-key IDs between related entities (manufacturer/model_series/car_type/group/article) plus scope IDs.
- car_type_id is authoritative from the URL; cross-validate against table cell value and log a warning on mismatch.
- Include only manufacturers equal or similar to names in manufaturers.txt (normalized matching). --manufacturers-file is optional.
- Collect only S3 article images (filter src to s3.us-east-1.amazonaws.com / auto-car-parts).
- compatible_cars table has 8 columns — always extract extra_qualifier (column 8).

## Architecture

- crawler.py: Crawler — asyncio.TaskGroup at manufacturer level, _crawl_manufacturer() and _crawl_model() methods. Semaphore caps HTTP concurrency across all tasks.
- checkpoint.py: CheckpointManager — aiosqlite SQLite WAL DB. is_seen() / mark_seen() called in _try_fetch for every URL.
- storage.py: JsonlStore — file handles kept open for crawl lifetime; call store.close() to flush.
- parser.py: pure selectolax parse_* functions. No side effects. article_id from URL regex _ARTICLE_ID_FROM_URL_RE.
- url_patterns.py: regex ParsedIds + is_in_scope() with regex guards.
- cli.py: Typer app — crawl, validate, export-images, convert, dedup.

## Code style

- Python 3.11+
- Typed functions and dataclasses
- Small pure parsing functions for testability
- No silent exception swallowing — catch only specific exception types
- No bare `except Exception` in new code

## Data quality gates

- No duplicate article_id in output (enforced post-crawl by `scrap-auto dedup`)
- No malformed ID fields from URL parsing
- article_id must never be None — always parseable from details_url
- Track extraction coverage counters per entity (manufacturers, models, car_types, car_type_details, filtered_car_types, category_groups, articles, article_details, failed_requests, skipped_seen, records_written)
- Ensure article_name is extracted from article-details h1 in div.container (skip "AUTO PARTS CATALOG" banner and section headings).
- Ensure relationship integrity via explicit IDs.
- Track and report manufacturers_filtered count.

## Recovery requirements

- Checkpoint DB at data/checkpoint.db records every fetched URL (status 200) and every failure.
- Re-running the same crawl command resumes automatically — seen 200 URLs are skipped.
- JsonlStore appends are idempotent per crawl session (no dedup within session — use `scrap-auto dedup` post-crawl).
- Make crawl resilient to intermittent 429/5xx — retry handles these.

## Storage pipeline

During crawl: JSONL files in data/
Post-crawl:
1. `scrap-auto convert` → partitioned Parquet in data/parquet/ (polars streaming, handles 25 GB)
2. `scrap-auto dedup` → DuckDB DISTINCT ON article_id → deduped Parquet
3. For reading large files: use DuckDB read_ndjson() or read_parquet() — never open in editor

## Before merge checklist

- Run `scrap-auto validate` — all 6 URL parsers must pass
- Run smoke crawl with --max-manufacturers 2 and --verbose and verify all JSONL files are non-empty
- Interrupt mid-run, rerun same command, confirm skipped_seen > 0 in final counters
- Confirm article_details image_urls contain only S3 URLs
- Confirm compatible_cars rows have extra_qualifier field

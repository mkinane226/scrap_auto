# AI harness for scrap_auto

This folder contains AI execution prompts and coding guidance to accelerate iterative scraping development.

## Current implementation status

All phases are implemented and production-ready:

- Concurrent async traversal using asyncio.TaskGroup at manufacturer level
- Resume/checkpoint via SQLite WAL DB (data/checkpoint.db) — re-running skips seen URLs
- Buffered JSONL writes (file handles kept open for crawl lifetime)
- Manufacturer allowlist filtering against manufaturers.txt (optional, normalized fuzzy matching)
- year_to branch filtering (skip < 2006; keep null/empty; handles MM/YYYY formats)
- article_name extracted from first relevant h1 in div.container
- article_id always extracted from URL path (not blob text)
- car_type_id cross-validated between table cell and URL; URL wins on mismatch
- S3-only image filtering in article-details pages
- compatible_cars table: 8 columns including extra_qualifier
- Explicit relational IDs across all entities
- Post-crawl pipeline: scrap-auto convert (JSONL → Parquet via polars) + scrap-auto dedup (DuckDB)

## Key constraints verified against live site

- No pagination on any page — all content loads in a single HTML response
- All 6 URL patterns confirmed correct
- compatible_cars has 8 columns (not 6)
- Images hosted exclusively on auto-car-parts.s3.us-east-1.amazonaws.com
- 1,004 total manufacturers available; no login or JS rendering required

## Files

- copilot-instructions.md: project-specific rules and constraints for AI coding sessions
- prompts/01_discovery.prompt.md: prompt for discovery crawl implementation (completed)
- prompts/02_extraction_quality.prompt.md: prompt for parser hardening and field quality (completed)
- prompts/03_scale_run.prompt.md: prompt for large batch execution and recovery (completed)

## How to use prompts

1. Open one prompt file.
2. Paste the prompt into your AI coding session.
3. Run the requested commands and collect metrics.
4. Move to next prompt only after acceptance checks pass.

## Quick command reference

```bash
# Smoke test with logs
scrap-auto crawl --max-manufacturers 2 --max-models-per-manufacturer 2 --max-car-types-per-model 2 --max-groups-per-car-type 2 --max-articles-per-group 5 --verbose

# Production run from allowlist (saves log)
scrap-auto crawl --manufacturers-file manufaturers.txt --verbose --progress-every 100 | Tee-Object -FilePath crawl.log

# Resume interrupted crawl — same command, checkpoint skips seen URLs
scrap-auto crawl --manufacturers-file manufaturers.txt --verbose --progress-every 100

# Validate URL parsers
scrap-auto validate

# Convert JSONL to Parquet (streaming, handles 25 GB)
scrap-auto convert

# Deduplicate by article_id using DuckDB
scrap-auto dedup

# Query large files without opening them
python -c "import duckdb; duckdb.connect().sql(\"SELECT article_id, article_name FROM read_ndjson('data/article_details.jsonl') LIMIT 20\").show()"
```

## Checkpoint DB inspection

```powershell
sqlite3 data\checkpoint.db "SELECT COUNT(*), status_code FROM seen_urls GROUP BY status_code"
```

Use the **SQLite Viewer** VS Code extension to browse checkpoint.db visually.

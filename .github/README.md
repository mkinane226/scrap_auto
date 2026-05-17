# AI harness for scrap_auto

This folder contains AI execution prompts and coding guidance to accelerate iterative scraping development.

## Current implementation status

All phases are implemented and deployed to production (Hetzner CPX31, Ubuntu 24.04):

**Crawler**
- Concurrent async traversal using asyncio.TaskGroup at manufacturer level
- Resume/checkpoint via SQLite WAL DB (data/checkpoint.db) — re-running skips seen URLs
- Buffered JSONL writes (file handles kept open for crawl lifetime)
- Manufacturer allowlist filtering against manufaturers.txt (optional, normalized fuzzy matching)
- year_to branch filtering (skip < 2006; keep null/empty; handles MM/YYYY formats)
- OEM articles: both `list-articles` and `list-oem-articles` URLs crawled; `is_oem` flag set on each article
- article_name extracted from first relevant h1 in div.container
- article_id always extracted from URL path (not blob text)
- car_type_id cross-validated between table cell and URL; URL wins on mismatch
- S3-only image filtering in article-details pages
- compatible_cars table: 8 columns including extra_qualifier
- Explicit relational IDs across all entities
- Bootstrap accordion parsing for category groups (primary → sub → sub-sub hierarchy)

**Pipeline**
- `scrap-auto convert` → partitioned Parquet in data/parquet/ (polars streaming, handles 25 GB)
- `scrap-auto dedup` → DuckDB DISTINCT ON article_id → deduped Parquet
- `scrap-auto load` → Parquet → PostgreSQL UPSERT (idempotent, batch 1000)

**Production API**
- FastAPI on 127.0.0.1:8090, proxied via Nginx at /api/autoparts/
- Endpoints: /health, /search (FTS + car filter), /article/{id}, /compatible/{id}, /manufacturers, /models/{name}
- X-API-Key header auth; asyncpg connection pool
- Systemd service (scrap-auto-api) + weekly crawl timer (scrap-auto-crawl.timer)

## Key constraints verified against live site

- No pagination on any page — all content loads in a single HTML response
- All 7 URL patterns confirmed correct (including list-oem-articles)
- compatible_cars has 8 columns (not 6)
- Images hosted exclusively on auto-car-parts.s3.us-east-1.amazonaws.com
- 1,004 total manufacturers available; no login or JS rendering required
- OEM and aftermarket articles share the same article_id space — `is_oem` flag distinguishes them

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
# Smoke test (local dev)
scrap-auto crawl --max-manufacturers 2 --max-models-per-manufacturer 2 --max-car-types-per-model 2 --max-groups-per-car-type 2 --max-articles-per-group 5 --verbose

# Validate URL parsers (7 patterns)
scrap-auto validate

# Production crawl — run on server inside tmux
scrap-auto crawl --manufacturers-file data/manufaturers.txt --verbose --progress-every 100 2>&1 | tee logs/crawl_initial.log

# Resume interrupted crawl — same command, checkpoint skips seen URLs
scrap-auto crawl --manufacturers-file data/manufaturers.txt --verbose --progress-every 100 2>&1 | tee -a logs/crawl_initial.log

# Post-crawl pipeline
scrap-auto convert                          # JSONL → Parquet (polars streaming)
scrap-auto dedup                            # DuckDB dedup by article_id
AUTOPARTS_DATABASE_URL="postgresql://autoparts_loader:PASS@localhost/autoparts" \
    scrap-auto load --data-dir data         # Parquet → PostgreSQL (UPSERT)

# Initialize PostgreSQL schema (first run only)
AUTOPARTS_DATABASE_URL="..." scrap-auto load --init --grant-api --data-dir data

# Query large files without opening them
python -c "import duckdb; duckdb.connect().sql(\"SELECT article_id, article_name FROM read_ndjson('data/article_details.jsonl') LIMIT 20\").show()"
```

## Checkpoint DB inspection

```bash
sqlite3 data/checkpoint.db "SELECT COUNT(*), status_code FROM seen_urls GROUP BY status_code"
```

## Production server paths

```
/opt/scrap_auto/
├── repo/        ← git clone (pull to update)
├── venv/        ← Python venv (pip install -e repo[api])
├── data/        ← JSONL, Parquet, checkpoint.db
└── logs/        ← crawl.log, api.log
```

Use the **SQLite Viewer** VS Code extension to browse checkpoint.db visually.

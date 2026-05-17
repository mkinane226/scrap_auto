# Full scraping plan for auto-parts-catalog.makingdatameaningful.com

## 1) Website analysis summary

The site is highly crawlable using deterministic URLs and embedded numeric IDs.
All pages load without JavaScript rendering, login walls, or pagination — all content is in the initial HTML response.

Live-verified counts:
- 1,004 manufacturers on the main listing page
- Up to 120 models per manufacturer (Audi observed)
- 11+ car type variants per model page
- 150+ category items per car type
- 60+ articles per category group
- Compatible cars table has 8 columns (car_type_id, model_series_id, manufacturer_name, model_name, engine_or_variant, year_from, year_to, extra_qualifier)

Observed URL layers:

1. Manufacturers list
- /manufacturers/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

2. Manufacturer models
- /models/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

3. Model passenger car types
- /passenger-car-types/{model_series_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

3b. Passenger car type details
- /passenger-car-type-details/{car_type_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}
- Note: type_id is NOT embedded in this URL — is_in_scope() allows it by path pattern

4. Car type categories page
- /list-category-products-groups/{car_type_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

5. Group product list
- /list-articles/{car_type_id}/{group_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

6. Article detail
- /article-details/{article_id}/model-series-id-{model_series_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

Image host:
- https://auto-car-parts.s3.us-east-1.amazonaws.com/media_unziped/IMAGES/...
- Only images from this S3 host are collected (logos and nav images are filtered out)

## 2) Scope and filtering

Inputs required by user:
- lang_id (default: 6)
- country_id (default: 145)
- type_id (default: 1)

The crawler uses regex-based scope matching (not substring) to avoid false positives on sequential IDs (e.g. lang-id-1 vs lang-id-16).

Manufacturer allowlist policy:
- Crawl only manufacturers that are equal or similar to names from manufaturers.txt (63 brands).
- --manufacturers-file is optional; if omitted, all manufacturers are crawled.
- Matching is case-insensitive and tolerant to accents/punctuation differences.
- Pre-indexed with O(1) exact + compact hash lookups, then prefix-indexed fuzzy fallback (difflib SequenceMatcher >= 0.93 ratio).
- Read allowlist with encoding fallback (utf-8-sig -> utf-8 -> latin-1).

Year filtering policy:
- Skip extraction for car types whose manufacturing end year is lower than 2006.
- If year_to is null/empty, treat the car type as still manufactured and keep extracting.
- Year interval parsing handles formats: "2005", "01/2005", "2005-01".
- The year_to gate is applied before category/group/article traversal.

car_type_id integrity:
- car_type_id is extracted from both the table cell and the details URL.
- If they diverge, the URL-derived value is used and a warning is logged.

## 3) Data model (entities)

All entities carry explicit stable IDs to support deterministic joins without re-parsing URLs.

1. manufacturer
- manufacturer_id, name, url, lang_id, country_id, type_id

2. model_series
- model_series_id, manufacturer_id, display_name, url, lang_id, country_id, type_id

3. car_type
- car_type_id (authoritative from URL), model_series_id, manufacturer_id, type_label, engine_code, cylinder, capacity, fuel_type, year_from, year_to, power, category_url, details_url, lang_id, country_id, type_id

3b. car_type_detail
- car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, details_url, car_type_title, construction_interval, year_from, year_to, details (key-value list)

4. category_group
- car_type_id, group_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, group_name, list_articles_url

5. article_summary
- article_id (from URL), group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, part_name, part_number, article_manufacturer, supplier_id, product_id, details_url

6. article_detail
- article_id, group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, article_name, image_urls (S3 only), technical_details (key-value list), oem_numbers (list), compatible_cars (8-column rows including extra_qualifier)

Entity relationship edges:
- manufacturer.manufacturer_id -> model_series.manufacturer_id
- model_series.model_series_id -> car_type.model_series_id
- car_type.car_type_id -> car_type_detail.car_type_id
- car_type.car_type_id -> category_group.car_type_id
- category_group.group_id -> article_summary.group_id
- article_summary.article_id -> article_detail.article_id

## 4) Crawl strategy

The crawl runs as a single integrated pass (no separate phases) using asyncio.TaskGroup for concurrent manufacturer traversal, gated by a configurable semaphore (default: 5 concurrent requests).

Traversal order per manufacturer (sequential within each manufacturer task):
- manufacturer -> models -> car_types -> car_type_details -> category_groups -> articles -> article_details

Resume support: every successfully fetched URL is recorded in data/checkpoint.db (SQLite WAL). Re-running the same command skips already-seen URLs automatically. The skipped_seen counter in the final output confirms this is working.

Phase D: Media pass (optional, separate command)
- scrap-auto export-images: downloads product images from S3 to data/images/ with shard subfolders and a manifest JSONL

## 5) Reliability and safety controls

- Global concurrency cap: 5 concurrent requests (configurable via CrawlConfig.concurrency)
- Retry policy: exponential backoff for all HTTP errors and timeouts (4 attempts, max 10s wait) via tenacity
- 429 responses are caught by raise_for_status() and retried automatically
- Respectful delay per request: 300ms to 1000ms random jitter
- User-agent string configurable in CrawlConfig
- Scope guard: is_in_scope() uses regex to enforce lang_id/country_id/type_id on every URL
- Exception handling: only specific exception types caught in _try_fetch (httpx.HTTPError, httpx.RequestError, asyncio.TimeoutError, ValueError); no silent swallowing of programming errors

## 6) Storage architecture

During crawl:
- JSONL append-only files for each entity (data/*.jsonl)
- File handles kept open for the crawl lifetime (not opened per-record)
- Checkpoint SQLite DB at data/checkpoint.db (WAL mode, aiosqlite)

Post-crawl conversion:
- scrap-auto convert: streams JSONL → partitioned Parquet via polars.scan_ndjson + sink_parquet
  Output: data/parquet/entity_type={name}/crawl_date={date}/part-0.parquet
  Nested fields (image_urls, technical_details, oem_numbers, compatible_cars) preserved as Parquet List/Struct types
- scrap-auto dedup: DuckDB DISTINCT ON article_id across Parquet → articles_deduped.parquet / article_details_deduped.parquet

Reading large files:
- Do NOT open article_details.jsonl in a text editor — it can reach 10-25 GB
- Use DuckDB to query directly: duckdb.connect().sql("SELECT ... FROM read_ndjson('data/article_details.jsonl') LIMIT 20").show()
- Or convert to Parquet first then query Parquet partitions

Dependencies:
- aiosqlite >= 0.21.0 (async SQLite checkpoint)
- polars >= 1.0.0 (streaming JSONL → Parquet)
- duckdb >= 1.1.0 (post-crawl analytics and dedup)

## 7) QA and validation checks

- scrap-auto validate: verifies all 6 URL pattern parsers against known sample URLs
- ID extraction coverage from every URL type
- article_id extracted from URL path (not blob text) — always reliable
- car_type_id cross-validated between table cell and URL; mismatch logged as warning
- Image URLs filtered to S3 host only
- Year filter checks:
  - no category/group/article rows from car types with year_to < 2006
  - car types with empty/null year_to remain eligible
- Uniqueness checks:
  - article_id globally unique (enforced post-crawl by dedup command)
- Referential checks (run via DuckDB post-crawl):
  - car_type.manufacturer_id exists in manufacturer
  - car_type.model_series_id exists in model_series
  - category_group.car_type_id exists in car_type
  - article.group_id exists in category_group
  - article_detail.article_id exists in article

## 8) Command runbook

Smoke test (with logs):
```
scrap-auto crawl --max-manufacturers 2 --max-models-per-manufacturer 2 --max-car-types-per-model 2 --max-groups-per-car-type 2 --max-articles-per-group 5 --verbose --progress-every 5
```

Production run from allowlist:
```
scrap-auto crawl --manufacturers-file manufaturers.txt --verbose --progress-every 100 | Tee-Object -FilePath crawl.log
```

Resume interrupted crawl (same command — checkpoint skips seen URLs automatically):
```
scrap-auto crawl --manufacturers-file manufaturers.txt --verbose --progress-every 100
```

Validate URL parsers:
```
scrap-auto validate
```

Convert JSONL to Parquet after crawl:
```
scrap-auto convert
```

Deduplicate articles by article_id:
```
scrap-auto dedup
```

Download article images:
```
scrap-auto export-images
```

Query large files without converting:
```python
import duckdb
duckdb.connect().sql("SELECT article_id, article_name FROM read_ndjson('data/article_details.jsonl') LIMIT 20").show()
```

Monitor output file sizes while crawling (PowerShell):
```powershell
Get-ChildItem data\*.jsonl | Select-Object Name, @{N='Lines';E={(Get-Content $_.FullName | Measure-Object -Line).Lines}}
```

Inspect checkpoint DB:
```powershell
sqlite3 data\checkpoint.db "SELECT COUNT(*), status_code FROM seen_urls GROUP BY status_code"
```

## 9) Legal and operational checklist

- Confirm permission/terms for scraping and media usage
- Keep request rates conservative (default delay 300ms–1000ms is polite)
- Crawl only the target domain — enforced by is_in_scope()
- Keep full logs: crawl.log captures all output with Tee-Object
- data/checkpoint.db records URL, status code, timestamp, and error message for every request

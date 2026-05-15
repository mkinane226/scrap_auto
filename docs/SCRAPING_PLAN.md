# Full scraping plan for auto-parts-catalog.makingdatameaningful.com

## 1) Website analysis summary

The site is highly crawlable using deterministic URLs and embedded numeric IDs.

Observed URL layers:

1. Manufacturers list
- /manufacturers/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

2. Manufacturer models
- /models/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

3. Model passenger car types
- /passenger-car-types/{model_series_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

4. Car type categories page
- /list-category-products-groups/{car_type_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

5. Group product list
- /list-articles/{car_type_id}/{group_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

6. Article detail
- /article-details/{article_id}/model-series-id-{model_series_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}

Image host observed:
- https://auto-car-parts.s3.us-east-1.amazonaws.com/media_unziped/IMAGES/...

## 2) Scope and filtering

Inputs required by user:
- lang_id (example: 6)
- country_id (example: 145)
- type_id (example: 1)

The crawler should only follow links preserving these IDs.

## 3) Data model (entities)

1. manufacturer
- manufacturer_id, name, url, lang_id, country_id, type_id

2. model_series
- model_series_id, manufacturer_id, display_name, from_year, to_year, url

3. car_type
- car_type_id, model_series_id, manufacturer_id, type_label, engine_code, cylinder, capacity, fuel_type, year_from, year_to, power, category_url, details_url

4. category_group
- car_type_id, group_id, group_name, list_articles_url, list_oem_url

5. article_summary
- article_id, car_type_id, group_id, part_name, part_number, article_manufacturer, supplier_id, product_id, details_url

6. article_detail
- article_id, image_urls, technical_details (key-value list), oem_numbers (list), compatible_cars (rows)

## 4) Crawl strategy

Phase A: Discovery pass
- Crawl all manufacturers
- Crawl all model series for each manufacturer
- Crawl all car types for each model series
- Crawl category groups and list-articles links
- Save frontier tables first

Phase B: Article pass
- Crawl list-articles pages
- Extract article summary rows and detail links
- De-duplicate by article_id

Phase C: Detail pass
- Crawl article-details pages
- Extract technical blocks, OEM lines, image URLs, compatible cars table

Phase D: Media pass (optional)
- Download image URLs with checksum file
- Keep metadata linking image to article_id

## 5) Reliability and safety controls

- Global concurrency cap: 5 to 10 workers max to start
- Retry policy: exponential backoff for 429/5xx/timeouts
- Respectful delay per host: 300ms to 1500ms jitter
- User-agent with contact email
- Resume support from checkpoints and seen sets

## 6) Storage architecture

Short-term:
- JSONL append-only files for each entity

Mid-term:
- SQLite/DuckDB for joins and dedupe checks

Long-term:
- Partitioned parquet by entity and crawl_date

## 7) QA and validation checks

- ID extraction coverage from every URL type
- Null-rate checks by critical field
- Uniqueness checks:
  - manufacturer_id unique per lang/country/type
  - article_id globally unique
- Referential checks:
  - car_type.manufacturer_id exists in manufacturer
  - article.car_type_id exists in car_type

## 8) Estimated execution plan

1. Day 1
- Implement URL parsing + extraction unit tests
- Smoke crawl with small limits

2. Day 2
- Full discovery pass and checkpointing
- Fix parsing gaps

3. Day 3+
- Full article and detail crawl
- Optional image download + parquet conversion

## 9) Legal and operational checklist

- Confirm permission/terms for scraping and media usage
- Keep request rates conservative
- Add kill switch and domain allowlist
- Keep full logs of URL, status, and retry count

## 10) Command runbook

Small test:
- scrap-auto crawl --max-manufacturers 2 --max-models-per-manufacturer 2 --max-car-types-per-model 2 --max-groups-per-car-type 2 --max-articles-per-group 5

Larger batch:
- scrap-auto crawl --max-manufacturers 100 --max-models-per-manufacturer 40 --max-car-types-per-model 100 --max-groups-per-car-type 300 --max-articles-per-group 1000

Validation:
- scrap-auto validate

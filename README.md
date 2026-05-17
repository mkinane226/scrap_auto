# scrap_auto

Python project to crawl the auto-parts catalog website in a controlled and structured way.

## What this project contains

- A crawler skeleton that follows the site hierarchy:
  - manufacturers -> models -> car types -> car type details -> category groups -> articles -> article details
- Strong URL pattern parsing based on IDs embedded in paths
- JSONL output for fast append-only exports
- A complete execution plan in docs and an AI harness in .github
- Manufacturing end-year filtering:
  - if car type year_to < 2006, skip type/category/article extraction for that branch
  - if year_to is null/empty, treat as still in production and keep it
- Manufacturer allowlist filtering:
  - only manufacturers equal or similar to names in manufaturers.txt are crawled
  - file parsing is robust to utf-8/utf-8-sig/latin-1 encodings and ignores empty/comment lines
  - matching is normalized (case/accent/punctuation-insensitive)
  - fast path uses exact and compact-name hash lookups
  - fallback fuzzy matching is prefix-indexed and length-bounded to reduce false positives and CPU cost

## Quick start

1. Create and activate a virtual environment.
2. Install the package in editable mode:

```bash
pip install -e .
```

3. Run a small validation crawl:

```bash
scrap-auto crawl --max-manufacturers 2 --max-models-per-manufacturer 2 --max-car-types-per-model 2 --max-groups-per-car-type 2 --max-articles-per-group 5 --min-year-to-include 2006
```

Use a custom manufacturer allowlist file:

```bash
scrap-auto crawl --manufacturers-file manufaturers.txt
```

4. Run URL/HTML extraction checks:

```bash
scrap-auto validate
```

## Important notes

- Respect website terms and robots policy before large-scale crawling.
- Use conservative rate limits and retries.
- Persist progress often; this dataset can become very large.

## Output

By default, JSONL artifacts are written to:

- data/manufacturers.jsonl
- data/models.jsonl
- data/car_types.jsonl
- data/car_type_details.jsonl
- data/category_groups.jsonl
- data/articles.jsonl
- data/article_details.jsonl

Notes:
- data/article_details.jsonl now includes article_name extracted from the first relevant h1 inside div.container (excluding site banner and section headings).

Relationship keys (explicit IDs for joins):
- manufacturers.jsonl: manufacturer_id, lang_id, country_id, type_id
- models.jsonl: model_series_id, manufacturer_id, lang_id, country_id, type_id
- car_types.jsonl: car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id
- car_type_details.jsonl: car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id
- category_groups.jsonl: group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id
- articles.jsonl: article_id, group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id
- article_details.jsonl: article_id, group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id

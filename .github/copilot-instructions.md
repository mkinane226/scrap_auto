# Copilot instructions for scrap_auto

## Mission
Build a resilient crawler for auto-parts-catalog.makingdatameaningful.com with strict URL filtering by lang_id, country_id, and type_id.

## Hard constraints

- Never crawl outside the target domain.
- Follow only URLs that preserve configured lang_id/country_id/type_id.
- Keep crawl polite and retry with backoff.
- Prefer deterministic URL ID parsing over brittle text scraping.
- Keep data normalized by stable IDs.

## Code style

- Python 3.11+
- Typed functions and dataclasses/pydantic models
- Small pure parsing functions for testability
- No silent exception swallowing

## Data quality gates

- No duplicate article_id in output
- No malformed ID fields from URL parsing
- Track extraction coverage counters per entity

## Recovery requirements

- Persist outputs incrementally
- Keep a seen-url cache to resume
- Make crawl idempotent when rerun

## Before merge checklist

- Run validation command
- Verify a small smoke crawl completes
- Confirm image URLs parse in article-details pages

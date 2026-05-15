You are implementing discovery phase for this project.

Goal:
- Crawl manufacturers -> models -> car types -> category groups.
- Save clean JSONL outputs with IDs.

Constraints:
- Keep lang_id/country_id/type_id filter strict.
- Add retries, timeout, and jitter.
- Keep code modular and typed.

Tasks:
1. Run smoke crawl with tiny limits.
2. Print counts per entity.
3. Report any parse failures with sample URLs.

Acceptance:
- manufacturers.jsonl, models.jsonl, car_types.jsonl, category_groups.jsonl all non-empty in smoke run.
- No URL parse errors for core patterns.

You are hardening extraction quality.

Goal:
- Improve article and article-detail extraction accuracy.

Tasks:
1. Extract article summary rows from list-articles pages.
2. Extract article detail blocks:
   - technical key/value fields
   - OEM numbers
   - image URLs
   - compatible cars table rows
3. Add validation counters for null/empty critical fields.

Acceptance:
- article_details.jsonl contains image_urls for at least some records.
- compatible_cars parsed into structured rows.
- validation command prints summary with no fatal schema errors.

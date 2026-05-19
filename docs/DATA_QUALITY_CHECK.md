# Data Quality & Consistency Check — autoparts Database

Run all checks as the `autoparts_api` read-only user after each load cycle.

```bash
psql 'postgresql://autoparts_api:ScrapAuto2026!Kinane@localhost/autoparts'
```

---

## 1. Summary Counts

```sql
SELECT
    (SELECT COUNT(*)                          FROM autoparts_articles)          AS total_articles,
    (SELECT COUNT(*)                          FROM autoparts_article_details)   AS total_details,
    (SELECT COUNT(*)                          FROM autoparts_compatible_cars)   AS total_compat_cars,
    (SELECT COUNT(DISTINCT article_id)        FROM autoparts_compatible_cars)   AS articles_with_cars,
    (SELECT COUNT(DISTINCT manufacturer_name) FROM autoparts_compatible_cars)   AS distinct_manufacturers,
    (SELECT COUNT(DISTINCT model_name)        FROM autoparts_compatible_cars)   AS distinct_models;
```

**Expected:** All counts > 0. `articles_with_cars` close to `total_articles`.

---

## 2. Duplication Checks

### 2a. Duplicate article_id in articles (must be 0)

```sql
SELECT article_id, COUNT(*) AS n
FROM autoparts_articles
GROUP BY article_id
HAVING COUNT(*) > 1
ORDER BY n DESC
LIMIT 20;
```

### 2b. Duplicate article_id in article_details (must be 0)

```sql
SELECT article_id, COUNT(*) AS n
FROM autoparts_article_details
GROUP BY article_id
HAVING COUNT(*) > 1
ORDER BY n DESC
LIMIT 20;
```

### 2c. Duplicate compatible_cars rows (same article + car_type + variant)

```sql
SELECT article_id, car_type_id, engine_or_variant, year_from, year_to, COUNT(*) AS n
FROM autoparts_compatible_cars
GROUP BY article_id, car_type_id, engine_or_variant, year_from, year_to
HAVING COUNT(*) > 1
ORDER BY n DESC
LIMIT 20;
```

**Expected:** All three queries return 0 rows.

---

## 3. Referential Integrity Checks

### 3a. Article_details with no parent article (FK orphans)

```sql
SELECT COUNT(*) AS orphan_details
FROM autoparts_article_details d
LEFT JOIN autoparts_articles a USING (article_id)
WHERE a.article_id IS NULL;
```

### 3b. Compatible_cars with no parent article

```sql
SELECT COUNT(*) AS orphan_compat
FROM autoparts_compatible_cars c
LEFT JOIN autoparts_articles a USING (article_id)
WHERE a.article_id IS NULL;
```

**Expected:** Both return 0. Any non-zero value means a round's `articles.jsonl`
was not converted — recover from Storage Box (see CRAWL_ROUNDS_PROCESS.md).

---

## 4. Coverage Gaps

### 4a. Articles without any details

```sql
SELECT COUNT(*) AS articles_missing_details
FROM autoparts_articles a
LEFT JOIN autoparts_article_details d USING (article_id)
WHERE d.article_id IS NULL;
```

### 4b. Articles without any compatible cars

```sql
SELECT COUNT(*) AS articles_missing_cars
FROM autoparts_articles a
LEFT JOIN autoparts_compatible_cars c USING (article_id)
WHERE c.id IS NULL;
```

### 4c. Articles without thumbnail image

```sql
SELECT COUNT(*) AS no_thumbnail
FROM autoparts_articles
WHERE thumbnail_url IS NULL OR thumbnail_url = '';
```

### 4d. Article details without images

```sql
SELECT COUNT(*) AS no_images
FROM autoparts_article_details
WHERE image_urls IS NULL OR image_urls = '[]'::jsonb;
```

### 4e. Coverage percentages summary

```sql
SELECT
    total.n                                                        AS total_articles,
    has_details.n                                                  AS with_details,
    ROUND(has_details.n * 100.0 / total.n, 1)                     AS pct_with_details,
    has_cars.n                                                     AS with_compat_cars,
    ROUND(has_cars.n * 100.0 / total.n, 1)                        AS pct_with_cars,
    has_thumb.n                                                    AS with_thumbnail,
    ROUND(has_thumb.n * 100.0 / total.n, 1)                       AS pct_with_thumbnail,
    has_img.n                                                      AS with_images,
    ROUND(has_img.n * 100.0 / total.n, 1)                         AS pct_with_images
FROM
    (SELECT COUNT(*) AS n FROM autoparts_articles)                                                             total,
    (SELECT COUNT(DISTINCT a.article_id) AS n FROM autoparts_articles a JOIN autoparts_article_details d USING (article_id)) has_details,
    (SELECT COUNT(DISTINCT article_id) AS n FROM autoparts_compatible_cars)                                    has_cars,
    (SELECT COUNT(*) AS n FROM autoparts_articles WHERE thumbnail_url IS NOT NULL AND thumbnail_url <> '')      has_thumb,
    (SELECT COUNT(*) AS n FROM autoparts_article_details WHERE image_urls IS NOT NULL AND image_urls <> '[]'::jsonb) has_img;
```

---

## 5. Data Quality Checks

### 5a. Articles with null or empty critical fields

```sql
SELECT
    COUNT(*) FILTER (WHERE article_id IS NULL)                     AS null_article_id,
    COUNT(*) FILTER (WHERE part_name IS NULL OR part_name = '')    AS empty_part_name,
    COUNT(*) FILTER (WHERE part_number IS NULL OR part_number = '') AS empty_part_number,
    COUNT(*) FILTER (WHERE details_url IS NULL OR details_url = '') AS empty_details_url,
    COUNT(*) FILTER (WHERE manufacturer_id IS NULL)                AS null_manufacturer_id,
    COUNT(*) FILTER (WHERE group_id IS NULL)                       AS null_group_id,
    COUNT(*) FILTER (WHERE car_type_id IS NULL)                    AS null_car_type_id
FROM autoparts_articles;
```

### 5b. Image URLs must be S3 (no external domains)

```sql
SELECT COUNT(*) AS non_s3_images
FROM autoparts_article_details,
     jsonb_array_elements_text(image_urls) AS url
WHERE url NOT LIKE '%s3.us-east-1.amazonaws.com%'
  AND url NOT LIKE '%auto-car-parts%'
  AND url <> '';
```

**Expected:** 0. All images must come from the S3 bucket.

### 5c. OEM numbers format check (should be list of objects with brand+number)

```sql
SELECT COUNT(*) AS malformed_oem
FROM autoparts_article_details
WHERE oem_numbers IS NOT NULL
  AND oem_numbers <> '[]'::jsonb
  AND NOT (oem_numbers -> 0 ? 'brand' AND oem_numbers -> 0 ? 'number');
```

### 5d. Compatible cars with missing manufacturer or model name

```sql
SELECT COUNT(*) AS missing_make_model
FROM autoparts_compatible_cars
WHERE manufacturer_name IS NULL OR manufacturer_name = ''
   OR model_name IS NULL OR model_name = '';
```

### 5e. Compatible cars year range validity

```sql
SELECT COUNT(*) AS invalid_year_range
FROM autoparts_compatible_cars
WHERE year_from <> ''
  AND year_to   <> ''
  AND year_from > year_to;
```

### 5f. OEM vs regular article split

```sql
SELECT
    is_oem,
    COUNT(*)                          AS count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
FROM autoparts_articles
GROUP BY is_oem
ORDER BY is_oem;
```

---

## 6. Search Functionality Checks

### 6a. Full-text search index is populated

```sql
SELECT COUNT(*) AS articles_with_search_vector
FROM autoparts_articles
WHERE search_vector IS NOT NULL;
```

**Expected:** Equal to total articles count.

### 6b. Sample FTS search (French — uses 'simple' dictionary)

```sql
SELECT article_id, part_name, part_number, article_manufacturer
FROM autoparts_articles
WHERE search_vector @@ websearch_to_tsquery('simple', 'filtre huile')
LIMIT 10;
```

### 6c. Search by manufacturer name

```sql
SELECT article_id, part_name, article_manufacturer
FROM autoparts_articles
WHERE article_manufacturer ILIKE '%bosch%'
LIMIT 10;
```

### 6d. Compatible car lookup (articles for a specific car)

```sql
SELECT a.article_id, a.part_name, a.part_number, c.engine_or_variant, c.year_from, c.year_to
FROM autoparts_compatible_cars c
JOIN autoparts_articles a USING (article_id)
WHERE c.manufacturer_name ILIKE 'ford'
  AND c.model_name ILIKE '%focus%'
LIMIT 20;
```

### 6e. Article detail lookup by ID

```sql
SELECT
    a.article_id,
    a.part_name,
    a.part_number,
    a.article_manufacturer,
    a.thumbnail_url,
    d.article_name,
    d.ean_numbers,
    d.oem_numbers,
    jsonb_array_length(COALESCE(d.image_urls, '[]'::jsonb))    AS image_count,
    jsonb_array_length(COALESCE(d.technical_details, '[]'::jsonb)) AS tech_detail_count,
    (SELECT COUNT(*) FROM autoparts_compatible_cars WHERE article_id = a.article_id) AS compat_car_count
FROM autoparts_articles a
LEFT JOIN autoparts_article_details d USING (article_id)
WHERE a.article_id = (SELECT article_id FROM autoparts_articles LIMIT 1);
```

---

## 7. Manufacturer Coverage Report

```sql
SELECT
    c.manufacturer_name,
    COUNT(DISTINCT c.model_name)    AS models,
    COUNT(DISTINCT c.article_id)    AS articles,
    COUNT(*)                        AS compat_entries
FROM autoparts_compatible_cars c
GROUP BY c.manufacturer_name
ORDER BY articles DESC
LIMIT 30;
```

---

## 8. Full Health Report (run this after every load)

```sql
\echo '=== COUNTS ==='
SELECT 'articles'        AS entity, COUNT(*) FROM autoparts_articles
UNION ALL
SELECT 'article_details',            COUNT(*) FROM autoparts_article_details
UNION ALL
SELECT 'compatible_cars',            COUNT(*) FROM autoparts_compatible_cars;

\echo '=== DUPLICATES (expect all 0) ==='
SELECT 'dup_articles'        AS check, COUNT(*) FROM (SELECT article_id FROM autoparts_articles GROUP BY article_id HAVING COUNT(*) > 1) x
UNION ALL
SELECT 'dup_details',                  COUNT(*) FROM (SELECT article_id FROM autoparts_article_details GROUP BY article_id HAVING COUNT(*) > 1) x
UNION ALL
SELECT 'orphan_details',               COUNT(*) FROM autoparts_article_details d LEFT JOIN autoparts_articles a USING (article_id) WHERE a.article_id IS NULL
UNION ALL
SELECT 'orphan_compat',                COUNT(*) FROM autoparts_compatible_cars c LEFT JOIN autoparts_articles a USING (article_id) WHERE a.article_id IS NULL
UNION ALL
SELECT 'non_s3_images',               COUNT(*) FROM autoparts_article_details, jsonb_array_elements_text(image_urls) url WHERE url NOT LIKE '%amazonaws.com%' AND url <> ''
UNION ALL
SELECT 'missing_make_model',           COUNT(*) FROM autoparts_compatible_cars WHERE manufacturer_name = '' OR model_name = '';

\echo '=== COVERAGE ==='
SELECT
    ROUND(COUNT(DISTINCT d.article_id) * 100.0 / COUNT(DISTINCT a.article_id), 1) AS pct_with_details,
    ROUND(COUNT(DISTINCT c.article_id) * 100.0 / COUNT(DISTINCT a.article_id), 1) AS pct_with_cars
FROM autoparts_articles a
LEFT JOIN autoparts_article_details d USING (article_id)
LEFT JOIN autoparts_compatible_cars c USING (article_id);
```

---

## Acceptance Criteria

| Check | Target |
|---|---|
| Duplicate article_ids | 0 |
| Orphan article_details | 0 |
| Orphan compatible_cars | 0 |
| Non-S3 image URLs | 0 |
| Articles with details | ≥ 95% |
| Articles with compatible cars | ≥ 90% |
| Articles with thumbnail | ≥ 80% |
| FTS search returns results | Yes |
| Compatible car lookup returns results | Yes |

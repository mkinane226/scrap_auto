# Article Search Queries — autoparts Database

Two search paths are available:

- **Hierarchical navigation** (Steps 1–5 below): browse by car → category → article
- **Full-text search** (Step 6): keyword search across part names, numbers, and manufacturers

Both paths end at Step 5 (article detail).

---

## Step 1 — Select a manufacturer → see all its models

```sql
-- Fast: single lookup in tiny dimension table (~121 rows)
SELECT manufacturer_id, manufacturer_name
FROM autoparts_manufacturers
ORDER BY manufacturer_name;
```

**Input:** none (show full list) or filter with `WHERE manufacturer_name ILIKE '%ford%'`
**Output:** manufacturer_id + name — pass manufacturer_id to Step 2

---

## Step 2 — Select a model → see all car type variants

```sql
-- Fast: indexed lookup by manufacturer_id (~1,100 total rows)
SELECT model_series_id, display_name, model_native_name, year_from, year_to
FROM autoparts_model_series
WHERE manufacturer_id = 5
ORDER BY display_name;
```

**Input:** manufacturer_id (from Step 1)
**Output:** model_series_id + names — pass model_series_id to Step 3

---

## Step 3 — Select a car type → see engine variants

```sql
-- Fast: indexed lookup by model_series_id
SELECT car_type_id, type_label, engine_code, fuel_type, capacity, power, year_from, year_to
FROM autoparts_car_types
WHERE model_series_id = 53
ORDER BY year_from, type_label;
```

**Input:** model_series_id (from Step 2)
**Output:** car_type_id + specs — pass car_type_id to Step 4

---

## Step 4 — Select a car type → see part categories

```sql
-- Fast: idx_compat_car_type + idx_articles_group
SELECT DISTINCT
    g.primary_group_name  AS category,
    g.subcategory_name,
    g.group_name          AS sub_category,
    g.group_id,
    COUNT(*)              AS articles
FROM autoparts_compatible_cars c
JOIN autoparts_articles a USING (article_id)
JOIN autoparts_groups g ON g.group_id = a.group_id
WHERE c.car_type_id = 140451
GROUP BY g.primary_group_name, g.subcategory_name, g.group_name, g.group_id
ORDER BY g.primary_group_name, g.subcategory_name, g.group_name;
```

**Input:** car_type_id (from Step 3)
**Output:** 3-level category tree with group_id — pass group_id to Step 5

---

## Step 5 — Select a category → see all articles

```sql
-- Fast: idx_compat_car_type + idx_articles_group (two indexed lookups)
SELECT
    a.article_id,
    a.part_name,
    a.part_number,
    a.article_number,
    a.article_manufacturer,
    a.is_oem,
    a.thumbnail_url
FROM autoparts_articles a
JOIN autoparts_compatible_cars c USING (article_id)
WHERE c.car_type_id = 140451
  AND a.group_id    = 1234
ORDER BY a.is_oem DESC, a.article_manufacturer, a.part_name;
```

**Input:** car_type_id + group_id (from Step 4)
**Output:** article list with thumbnails — pass article_id to Step 6

---

## Step 6 — Select an article → see full details

```sql
SELECT
    a.article_id,
    a.part_name,
    a.part_number,
    a.article_number,
    a.article_manufacturer,
    a.group_name,
    a.primary_group_name,
    a.is_oem,
    a.thumbnail_url,
    a.details_url,
    d.article_name,
    d.ean_numbers,
    d.oem_numbers,
    d.technical_details,
    d.image_urls,
    jsonb_array_length(COALESCE(d.image_urls,        '[]'::jsonb)) AS image_count,
    jsonb_array_length(COALESCE(d.oem_numbers,       '[]'::jsonb)) AS oem_count,
    jsonb_array_length(COALESCE(d.technical_details, '[]'::jsonb)) AS tech_detail_count,
    (SELECT COUNT(*) FROM autoparts_compatible_cars WHERE article_id = a.article_id) AS compat_car_count
FROM autoparts_articles a
LEFT JOIN autoparts_article_details d USING (article_id)
WHERE a.article_id = 3449023;
```

**Input:** article_id (from Step 4)
**Output:** everything — names, part numbers, OEM cross-references, EAN barcodes, technical specs, image URLs, compatible car count

---

## Step 7 (alternative) — Full-text keyword search

Skips Steps 1–3. Useful when the user types a part name or number directly.

```sql
SELECT
    a.article_id,
    a.part_name,
    a.part_number,
    a.article_manufacturer,
    a.group_name,
    a.thumbnail_url,
    ts_rank(a.search_vector, query) AS relevance
FROM autoparts_articles a,
     websearch_to_tsquery('simple', 'filtre huile') AS query
WHERE a.search_vector @@ query
ORDER BY relevance DESC
LIMIT 20;
```

**Then filter by car** (optional, add after the WHERE):

```sql
  AND a.article_id IN (
      SELECT DISTINCT article_id
      FROM autoparts_compatible_cars
      WHERE manufacturer_name ILIKE 'Ford'
        AND model_name        ILIKE 'Kuga'
        AND car_type_id       = 140451
  )
```

---

## All steps in one view

```
Step 1  Manufacturer list    ← autoparts_manufacturers          (121 rows, instant)
           │
Step 2  Model list           ← autoparts_model_series           (~1,100 rows, indexed)
           │
Step 3  Car type / variant   ← autoparts_car_types              (~50k rows, indexed)
           │
Step 4  Category tree        ← autoparts_compatible_cars        (car_type_id index)
         (primary →            JOIN autoparts_articles
          sub-cat →             JOIN autoparts_groups
          group)
           │
Step 5  Article list         ← autoparts_compatible_cars        (car_type_id + group_id index)
                               JOIN autoparts_articles
           │
Step 6  Article detail       ← autoparts_articles
                               JOIN autoparts_article_details
```

**Keyword search** (Step 7) enters at the article list level and can be combined with any car filter.

## Car type technical details (optional)

Full specs for a selected car type (engine, displacement, power, construction interval):

```sql
SELECT
    ct.type_label, ct.engine_code, ct.fuel_type, ct.capacity,
    ct.power, ct.year_from, ct.year_to,
    ctd.car_type_title, ctd.construction_interval,
    ctd.details AS technical_specs
FROM autoparts_car_types ct
LEFT JOIN autoparts_car_type_details ctd USING (car_type_id)
WHERE ct.car_type_id = 140451;
```

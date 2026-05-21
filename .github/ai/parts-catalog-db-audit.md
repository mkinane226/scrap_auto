# Audit Base de Données Catalogue Pièces

**Statut** : Référence — à exécuter sur le serveur Hetzner pour obtenir les chiffres réels  
**Mis à jour** : 2026-05-21  
**Base de données** : `autoparts` (PostgreSQL 16, même VM que Odoo)

Ce document contient les requêtes SQL à exécuter pour renseigner les volumétries réelles,
les taux de nullité et les exemples de données dont l'équipe Odoo a besoin avant de coder.

---

## 1. Volumétries — Requêtes à exécuter

```bash
# Sur le serveur Hetzner, en tant que odoo :
psql autoparts
```

### 1.1 Comptage de toutes les tables

```sql
SELECT
    relname                                       AS table_name,
    n_live_tup                                    AS estimated_rows
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY n_live_tup DESC;
```

> Résultat rapide (stats internes PG). Pour les chiffres exacts, utiliser `SELECT COUNT(*)`.

### 1.2 Comptage exact par table

```sql
-- Tables de référence (petites — résultat immédiat)
SELECT 'manufacturers'   AS t, COUNT(*) FROM autoparts_manufacturers
UNION ALL
SELECT 'model_series',          COUNT(*) FROM autoparts_model_series
UNION ALL
SELECT 'groups',                COUNT(*) FROM autoparts_groups
UNION ALL
SELECT 'car_types',             COUNT(*) FROM autoparts_car_types
UNION ALL
SELECT 'car_type_details',      COUNT(*) FROM autoparts_car_type_details;

-- Tables volumineuses (peut prendre quelques secondes)
SELECT 'articles',              COUNT(*) FROM autoparts_articles
UNION ALL
SELECT 'article_details',       COUNT(*) FROM autoparts_article_details
UNION ALL
SELECT 'compatible_cars',       COUNT(*) FROM autoparts_compatible_cars;
```

### 1.3 Couverture article_details vs articles

```sql
-- Taux de remplissage des fiches détaillées
SELECT
    (SELECT COUNT(*) FROM autoparts_articles)       AS total_articles,
    (SELECT COUNT(*) FROM autoparts_article_details) AS articles_with_details,
    ROUND(
        100.0 * (SELECT COUNT(*) FROM autoparts_article_details)
               / NULLIF((SELECT COUNT(*) FROM autoparts_articles), 0),
        1
    )                                               AS coverage_pct;
```

---

## 2. Qualité des données — Requêtes à exécuter

### 2.1 Champs critiques dans `autoparts_articles`

```sql
SELECT
    COUNT(*)                                           AS total,
    COUNT(*) FILTER (WHERE thumbnail_url IS NULL
                       OR thumbnail_url = '')          AS missing_thumbnail,
    COUNT(*) FILTER (WHERE part_number IS NULL
                       OR part_number = '')            AS missing_part_number,
    COUNT(*) FILTER (WHERE article_manufacturer IS NULL
                       OR article_manufacturer = '')   AS missing_manufacturer,
    COUNT(*) FILTER (WHERE group_id IS NULL)           AS missing_group_id,
    COUNT(*) FILTER (WHERE is_oem = TRUE)              AS is_oem_count,
    COUNT(*) FILTER (WHERE is_oem = FALSE)             AS aftermarket_count
FROM autoparts_articles;
```

### 2.2 Champs critiques dans `autoparts_article_details`

```sql
SELECT
    COUNT(*)                                                          AS total,
    COUNT(*) FILTER (WHERE ean_numbers  = '[]'::jsonb
                        OR ean_numbers  IS NULL)                      AS no_ean,
    COUNT(*) FILTER (WHERE oem_numbers  = '[]'::jsonb
                        OR oem_numbers  IS NULL)                      AS no_oem,
    COUNT(*) FILTER (WHERE image_urls   = '[]'::jsonb
                        OR image_urls   IS NULL)                      AS no_images,
    COUNT(*) FILTER (WHERE technical_details = '[]'::jsonb
                        OR technical_details IS NULL)                 AS no_tech_details,
    ROUND(AVG(jsonb_array_length(COALESCE(image_urls, '[]'::jsonb))), 1) AS avg_images_per_article,
    ROUND(AVG(jsonb_array_length(COALESCE(oem_numbers,'[]'::jsonb))), 1) AS avg_oem_per_article
FROM autoparts_article_details;
```

### 2.3 Couverture manufacturer_id dans les tables de navigation

```sql
-- Séries sans fabricant (problème connu — voir §5)
SELECT
    COUNT(*)                                  AS total_model_series,
    COUNT(*) FILTER (WHERE manufacturer_id IS NULL) AS missing_manufacturer_id
FROM autoparts_model_series;

-- Car types sans model_series (orphelins)
SELECT
    COUNT(*)                                        AS total_car_types,
    COUNT(*) FILTER (WHERE model_series_id IS NULL) AS missing_model_series_id
FROM autoparts_car_types;
```

### 2.4 Distribution fuel_type (normalisation)

```sql
SELECT fuel_type, COUNT(*) AS n
FROM autoparts_car_types
GROUP BY fuel_type
ORDER BY n DESC;
```

> L'équipe Odoo doit savoir si `fuel_type` est déjà normalisé ("Diesel", "Petrol", "Hybrid")
> ou brut ("Diesel/CNG", "Electric/Petrol (Hybrid)", etc.) pour décider si une normalisation
> côté Odoo est nécessaire.

### 2.5 Distribution des fabricants dans `compatible_cars`

```sql
-- Top 20 fabricants par nombre d'articles compatibles
SELECT manufacturer_name, COUNT(DISTINCT article_id) AS articles
FROM autoparts_compatible_cars
WHERE manufacturer_name != ''
GROUP BY manufacturer_name
ORDER BY articles DESC
LIMIT 20;
```

---

## 3. Exemples de données — Requêtes à exécuter

### 3.1 Exemple d'article complet (pour valider le format JSON)

```sql
-- Choisir un article qui a des données complètes
SELECT
    a.article_id, a.part_name, a.part_number, a.article_number,
    a.article_manufacturer, a.group_name, a.primary_group_name,
    a.is_oem, a.thumbnail_url,
    d.article_name,
    d.ean_numbers,
    d.oem_numbers,
    d.technical_details,
    d.image_urls,
    jsonb_array_length(COALESCE(d.image_urls,        '[]'::jsonb)) AS image_count,
    jsonb_array_length(COALESCE(d.oem_numbers,       '[]'::jsonb)) AS oem_count,
    jsonb_array_length(COALESCE(d.technical_details, '[]'::jsonb)) AS tech_detail_count
FROM autoparts_articles a
JOIN autoparts_article_details d USING (article_id)
WHERE d.oem_numbers  != '[]'::jsonb
  AND d.image_urls   != '[]'::jsonb
  AND d.ean_numbers  != '[]'::jsonb
LIMIT 3;
```

### 3.2 Exemple de compatible_cars pour un article

```sql
SELECT car_type_id, manufacturer_name, model_name, engine_or_variant, year_from, year_to
FROM autoparts_compatible_cars
WHERE article_id = (
    SELECT article_id FROM autoparts_article_details
    WHERE jsonb_array_length(COALESCE(oem_numbers, '[]'::jsonb)) > 2
    LIMIT 1
)
LIMIT 10;
```

### 3.3 Exemples de groupes (catégories)

```sql
SELECT group_id, primary_group_name, subcategory_name, sub_subcategory_name, group_name
FROM autoparts_groups
ORDER BY primary_group_name, subcategory_name
LIMIT 20;
```

### 3.4 Exemples de car_types (pour valider le format envoyé à Odoo)

```sql
SELECT
    ct.car_type_id, ct.model_series_id, ct.type_label, ct.engine_code,
    ct.fuel_type, ct.capacity, ct.power, ct.year_from, ct.year_to,
    ctd.car_type_title, ctd.construction_interval
FROM autoparts_car_types ct
LEFT JOIN autoparts_car_type_details ctd USING (car_type_id)
WHERE ctd.car_type_title IS NOT NULL
LIMIT 5;
```

### 3.5 Exemple de recherche full-text (valider que FTS fonctionne)

```sql
-- Recherche "brake disc" — doit retourner des résultats
SELECT article_id, part_name, article_manufacturer, is_oem
FROM autoparts_articles
WHERE search_vector @@ websearch_to_tsquery('simple', 'brake disc')
ORDER BY ts_rank(search_vector, websearch_to_tsquery('simple', 'brake disc')) DESC
LIMIT 5;

-- Recherche par numéro de pièce partiel (trigram)
SELECT article_id, part_name, part_number, article_manufacturer
FROM autoparts_articles
WHERE part_number ILIKE '%09864795%'
LIMIT 5;
```

---

## 4. Schéma complet des tables

### Tables de référence (synchronisées dans Odoo)

```sql
-- Fabricants
TABLE autoparts_manufacturers:
  manufacturer_id   INTEGER PK
  manufacturer_name TEXT

-- Séries de modèles
TABLE autoparts_model_series:
  model_series_id     INTEGER PK
  manufacturer_id     INTEGER FK → autoparts_manufacturers
  display_name        TEXT          -- "FIAT 500 (111_, 101_, 110_)"
  model_native_name   TEXT          -- "500 (111_, 101_, 110_)"
  year_from           TEXT
  year_to             TEXT
  url                 TEXT          -- artefact scraping — ignoré par l'API

-- Motorisations
TABLE autoparts_car_types:
  car_type_id       INTEGER PK
  model_series_id   INTEGER FK → autoparts_model_series
  type_label        TEXT          -- "2.0 TDI 150 CV"
  engine_code       TEXT
  cylinder          INTEGER
  capacity          TEXT          -- "1968 cm³"
  fuel_type         TEXT          -- "Diesel", "Petrol", etc.
  year_range        TEXT          -- brut TecDoc
  year_from         INTEGER
  year_to           INTEGER       -- NULL = encore en production
  power             TEXT          -- "110 kW (150 CV)"
  category_url      TEXT          -- artefact scraping — ignoré par l'API
  details_url       TEXT          -- artefact scraping — ignoré par l'API

-- Détails motorisation (specs techniques)
TABLE autoparts_car_type_details:
  car_type_id             INTEGER PK FK → autoparts_car_types
  car_type_title          TEXT    -- "AUDI - A4 (B9) - 2.0 TDI 150 CV"
  construction_interval   TEXT    -- "From: 10/2015 To: 10/2020"
  year_from               INTEGER
  year_to                 INTEGER
  details                 JSONB   -- [{key, value}, ...]

-- Groupes / catégories de pièces
TABLE autoparts_groups:
  group_id              INTEGER PK
  primary_group_name    TEXT    -- "Braking"
  subcategory_name      TEXT    -- "Disc Brakes"
  sub_subcategory_name  TEXT    -- "Brake Disc"
  group_name            TEXT    -- "Braking > Disc Brakes > Brake Disc"
  list_articles_url     TEXT    -- artefact scraping — ignoré
  list_oem_articles_url TEXT    -- artefact scraping — ignoré
```

### Tables live (jamais synchronisées dans Odoo)

```sql
-- Articles (résultats de recherche)
TABLE autoparts_articles:
  article_id            BIGINT PK
  part_name             TEXT
  part_number           TEXT
  article_number        TEXT
  article_manufacturer  TEXT
  group_name            TEXT          -- dénormalisé depuis autoparts_groups
  primary_group_name    TEXT          -- dénormalisé
  group_id              INTEGER FK → autoparts_groups
  supplier_id           INTEGER
  product_id            INTEGER
  is_oem                BOOLEAN
  thumbnail_url         TEXT          -- URL S3 directe
  manufacturer_id       INTEGER
  model_series_id       INTEGER
  car_type_id           INTEGER
  details_url           TEXT          -- artefact scraping — IGNORÉ par l'API
  search_vector         TSVECTOR      -- FTS interne — NON exposé par l'API

-- Fiches détaillées (récupérées par article_id)
TABLE autoparts_article_details:
  article_id          BIGINT PK FK → autoparts_articles
  article_name        TEXT
  ean_numbers         JSONB    -- ["3165143396929"]
  oem_numbers         JSONB    -- [{"brand": "AUDI", "number": "4F0615301D"}]
  technical_details   JSONB    -- [{"key": "Diamètre [mm]", "value": "320"}]
  image_urls          JSONB    -- ["https://auto-car-parts.s3...webp"]

-- Compatibilités véhicules (51M+ lignes)
TABLE autoparts_compatible_cars:
  id                SERIAL PK
  article_id        BIGINT FK → autoparts_articles
  car_type_id       INTEGER       -- clé de liaison principale avec le wizard Odoo
  model_series_id   INTEGER
  manufacturer_name TEXT
  model_name        TEXT
  engine_or_variant TEXT
  year_from         TEXT
  year_to           TEXT
  extra_qualifier   TEXT
```

---

## 5. Notes connues sur la qualité des données

### manufacturer_id NULL dans model_series / car_types

Avant le rechargement complet (crawl en cours), certaines séries et motorisations
avaient `manufacturer_id IS NULL`. Après la fin du crawl métadonnées complet
(tous fabricants, min_year=1900), ces valeurs doivent être backfillées via :

```sql
-- Vérifier si le problème est résolu après chargement
SELECT COUNT(*) FROM autoparts_model_series WHERE manufacturer_id IS NULL;
SELECT COUNT(*) FROM autoparts_car_types WHERE model_series_id IS NULL;
```

### year_to NULL = encore en production

`year_to IS NULL` dans `autoparts_car_types` signifie que le véhicule est
toujours en production. Côté Odoo, afficher "" ou "aujourd'hui" pour `year_to = None`.

### thumbnail_url — format S3

Toutes les URLs de miniatures suivent le format :
`https://auto-car-parts.s3.us-east-1.amazonaws.com/<path>.webp`

Ces URLs sont accessibles publiquement sans authentification.
Le client Odoo peut les afficher directement avec `<img src="..."/>` sans proxification.

### Langue des données

- `part_name`, `article_name` : anglais (source TecDoc)
- `group_name` : anglais (ex. "Braking > Disc Brakes > Brake Disc")
- `fuel_type` : anglais, valeurs connues : "Petrol", "Diesel", "Electric",
  "Hybrid (Petrol/Electric)", "CNG (Compressed Natural Gas)", "LPG"
  — mais vérifier avec la requête §2.4 pour la liste complète réelle
- `manufacturer_name` dans `compatible_cars` : MAJUSCULES (ex. "FORD", "VOLKSWAGEN")
- `model_name` dans `compatible_cars` : mixte (ex. "FOCUS", "Golf", "3 Series")

### Champs à ignorer côté Odoo

Ces colonnes sont des artefacts de scraping qui ne doivent pas être stockés ni exposés :

| Colonne | Table | Raison |
|---|---|---|
| `details_url` | `autoparts_articles` | URL page web scrapée — sans valeur métier |
| `url` | `autoparts_model_series` | Idem |
| `category_url` / `details_url` | `autoparts_car_types` | Idem |
| `list_articles_url` / `list_oem_articles_url` | `autoparts_groups` | Idem |
| `search_vector` | `autoparts_articles` | Colonne interne PostgreSQL tsvector |

---

## 6. Checklist de validation avant démarrage du développement

Exécuter les requêtes des §1–3 et cocher chaque point :

- [ ] `autoparts_articles` : nombre total de lignes renseigné
- [ ] `autoparts_article_details` : couverture % (articles avec fiche détaillée)
- [ ] `autoparts_compatible_cars` : nombre total de lignes renseigné
- [ ] `autoparts_manufacturers` : toutes les grandes marques présentes (VW, Ford, BMW, etc.)
- [ ] `autoparts_car_types` : nombre total proche de ~100 000
- [ ] `autoparts_groups` : exemples de `primary_group_name` plausibles
- [ ] `thumbnail_url` : les URLs S3 s'affichent dans le navigateur (tester 1 URL manuellement)
- [ ] FTS fonctionne : requête §3.5 retourne des résultats pour "brake disc"
- [ ] `manufacturer_id IS NULL` dans `model_series` : 0 après rechargement
- [ ] Accès en lecture avec l'utilisateur `autoparts_api` : `psql -U autoparts_api autoparts -c "SELECT COUNT(*) FROM autoparts_articles;"`
- [ ] `fuel_type` : liste complète des valeurs documentée (requête §2.4)

---

## 7. Accès base de données pour l'équipe Odoo

L'équipe Odoo n'a pas d'accès direct à la base `autoparts`. Toutes les données passent
par l'API REST. Pour les tests d'intégration, utiliser l'API en dev local avec
`AUTOPARTS_API_KEY` désactivé (env var vide) ou une clé de test.

Si un accès direct à la DB de développement est nécessaire pour debug :

```bash
# Depuis le serveur Hetzner uniquement (pas d'accès externe)
psql -U autoparts_api -d autoparts
# Droits : SELECT uniquement sur toutes les tables (read-only)
```

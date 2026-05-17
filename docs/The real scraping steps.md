# Auto-Parts Catalog — Real Scraping Steps (AI Harness Reference)

> **Purpose:** This document is the authoritative field-by-field extraction specification for every page type in the scraping pipeline. It is written for an AI coding agent implementing or updating the parsers. Follow this exactly — do not rely on earlier assumptions. All HTML structures and selectors have been live-verified against the target site.
>
> **Target site:** https://auto-parts-catalog.makingdatameaningful.com  
> **Scope params (defaults):** lang_id=6, country_id=145, type_id=1

---

## Overview: Traversal Graph

```
Step 1: Manufacturers list
    └── Step 2: Model cards  (one page per manufacturer)
          └── Step 3: Car types table  (one page per model)
                ├── Step 4: Car type details  (one page per car type row)
                └── Step 5: Category groups  (one page per car type row)
                      └── Step 6: Articles list  (one page per group/subgroup/sub-subgroup)
                            └── Step 7: Article details  (one page per article)
```

Every link between steps is embedded as a URL in the parent page. All URLs contain the full scope parameters (lang_id, country_id, type_id) except car-type-details URLs which omit type_id — this is by design.

---

## Step 1 — Manufacturers List

**URL pattern:** `/manufacturers/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}`

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/manufacturers/lang-id-6/country-filter-id-145/type-id-1

**Selector:** `a[href*='/models/manufacturer-id-']`

**Fields per manufacturer:**
| Field | Source | Notes |
|---|---|---|
| `name` | `a.text()` (strip) | Manufacturer name, uppercase |
| `url` | `a[href]` → absolute URL | Links to Step 2 |

**Parsing notes:**
- All 1,004 manufacturers appear on a single page — no pagination.
- Deduplicate by `url`.

**Output file:** `data/manufacturers.jsonl`

---

## Step 2 — Model Cards

**URL pattern:** `/models/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}`

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/models/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1

**Verified HTML structure:**
```html
<div class="colman col-12 col-md-4 col-lg-4 mb-3">
    <div class="card">
        <div class="card-body">
            <h5 class="card-title">
                <a href="/passenger-car-types/5855/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1">
                    <strong> FORD ACTIVA 3/5 portes</strong>
                </a>
            </h5>
            <p class="card-text">
                ID: 5855
                <br>
                <strong>ACTIVA 3/5 portes</strong>
                <br>
                From: 2000-10-01
                <br>
                To: 
            </p>
        </div>
        <div class="card-footer">
            <a class="btn btn-success" href="/passenger-car-types/5855/...">More details</a>
        </div>
    </div>
</div>
```

**Card selector:** `div.colman.col-12.col-md-4.col-lg-4.mb-3 div.card`  
(or more simply: `h5.card-title a[href*='/passenger-car-types/']` to locate cards)

**Fields per model card:**
| Field | Selector / Pattern | Notes |
|---|---|---|
| `url` | `h5.card-title a[href]` → absolute URL | Links to Step 3. Also the primary key. |
| `display_name` | `h5.card-title a strong` text (strip) | Full name e.g. "FORD ACTIVA 3/5 portes" |
| `model_series_id` | From URL path: `/passenger-car-types/(\d+)/` | Extracted via regex from `url` |
| `model_id` | `p.card-text` text → regex `r"ID:\s*(\d+)"` | e.g. 5855 — same as model_series_id from URL |
| `model_native_name` | `p.card-text > strong` text (strip) | Short name e.g. "ACTIVA 3/5 portes" |
| `from_date` | `p.card-text` text → regex `r"From:\s*([\d\-]+)"` | Full date e.g. "2000-10-01". Extract year as int separately. |
| `to_date` | `p.card-text` text → regex `r"To:\s*([\d\-]+)"` | Full date or empty string. Empty = still manufactured. |

**Parsing notes:**
- `p.card-text` contains `ID:`, `From:`, `To:` on separate lines separated by `<br>`. Parse the raw text with regex.
- `to_date` being empty string means the model is still in production — do NOT treat as null, keep as `""`.
- Deduplicate by `url`.

**Output file:** `data/models.jsonl`

---

## Step 3 — Car Types Table

**URL pattern:** `/passenger-car-types/{model_series_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}`

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/passenger-car-types/9155/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1

**Page-level fields:**
| Field | Selector | Notes |
|---|---|---|
| `model_title` | `div.container h1` (first, skip "AUTO PARTS CATALOG") | e.g. "FORD FOCUS III \| Passenger Cars Types" |
| `car_type_count` | `div.container h2` text → regex `r"Car Types count:\s*(\d+)"` | e.g. 41 |

**Table selector:** `table.table.table-vcenter.card-table.table-striped tbody tr`  
Fallback: `table tbody tr`

**Columns (0-indexed cells):**
| Index | Field | Notes |
|---|---|---|
| 0 | `car_type_id` | Numeric ID — also extract from details URL to cross-validate |
| 1 | `type_label` | Engine displacement or type name (e.g. "2.0 TDCi ST") |
| 2 | `engine_code` | Engine code (e.g. "T8DA") |
| 3 | `cylinder` | Number of cylinders (int) |
| 4 | `capacity` | Capacity string (e.g. "1997 ccm") |
| 5 | `fuel_type` | Fuel type (e.g. "Diesel") |
| 6 | `year_range` | Full text. Year is inside `div.text-secondary`. If only ONE date present, it is start-only with no end (still manufactured). |
| 7 | `power` | Power string (e.g. "136 kW / 185 PS") |
| 8 | `details_url` | `a[href*='/passenger-car-type-details/']` → absolute URL → Step 4 |
| 9 | `category_url` | `a[href*='/list-category-products-groups/']` → absolute URL → Step 5 |

**Parsing notes:**
- Extract `year_from` and `year_to` from `year_range` using `re.findall(r"(\d{4})", text)`.
- If only one 4-digit year found → `year_from = that year`, `year_to = None`.
- `car_type_id` from cells[0] must be cross-validated against the ID in `details_url`. If they differ, log a warning and use the URL value.
- Skip rows where `len(cells) < 10`.
- Skip the entire car-type branch if `year_to < 2006` (see year filter policy).

**Output file:** `data/car_types.jsonl`

---

## Step 4 — Car Type Details

**URL pattern:** `/passenger-car-type-details/{car_type_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}`

> ⚠ Note: `type_id` is NOT in this URL. `is_in_scope()` allows it via path pattern match.

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/passenger-car-type-details/108575/manufacturer-id-36/lang-id-6/country-filter-id-145

**Page-level fields:**
| Field | Selector | Notes |
|---|---|---|
| `car_type_title` | `div.container h1` (strip, skip "AUTO PARTS CATALOG") | e.g. "FORD - FOCUS III - 2.0 TDCi ST" |

**Vehicle details block:**
```html
<div class="card-header bg-primary text-white">Vehicle Details</div>
<div class="card-body">
    <dl class="row">
        <dt class="col-sm-4">Construction Interval</dt>
        <dd class="col-sm-8">From: 2014-11-01<br>To: 2017-12-01</dd>
        ...
    </dl>
</div>
```

**Selector:** `div.container dl dt` and `div.container dl dd` (paired by zip)

**Fields extracted as `details` list of `{key, value}` dicts:**
The exact set of keys varies per vehicle. Observed keys include but are not limited to:
- Type
- Construction Interval
- Power (kW) / Power (PS)
- Capacity (multi-line: "Tax:\nLiters: 2.0000\nTech: 1997.0000")
- ABS / ASR
- Number of Cylinders / Number of Valves
- Body Type
- Engine Type / Fuel Type
- Gear Type / Drive Type
- Brake System / Brake Type
- Catalysator Type / Fuel Mixture
- Engine Codes

**Construction interval parsing:**
- `construction_interval` = raw `dd` text for key "Construction Interval" (e.g. "From: 2014-11-01\nTo: 2017-12-01")
- `year_from` = regex `r"From[:\s]+([\d\-]+)"` → extract 4-digit year: `r"(\d{4})"` from the matched group
- `year_to` = regex `r"To[:\s]+([\d\-]+)"` → extract 4-digit year, or None if empty

**Parsing notes:**
- Empty `dd` values are valid — keep as empty string in `details` list.
- `year_to` from this page takes priority over `year_to` from the car types table when the table value is None.

**Output file:** `data/car_type_details.jsonl`

---

## Step 5 — Category Group Products

**URL pattern:** `/list-category-products-groups/{car_type_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}`

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/list-category-products-groups/108575/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1

**Page-level fields:**
| Field | Selector | Notes |
|---|---|---|
| `page_title` | `div.container h1` (skip banner) | e.g. "Category Group Products for: FORD FOCUS III" |

**Structure:** Bootstrap accordion with 3 levels of hierarchy.

**Verified HTML (accordion item with all levels):**
```html
<div class="accordion-item">
    <!-- Level 1: Primary category group -->
    <h1 class="accordion-header" id="accordion100733">
        <button class="accordion-button ...">Accessoires</button>
    </h1>
    <div id="collapse100733" class="accordion-collapse collapse">
        <div class="accordion-body row">

            <!-- Level 2: Subcategory (no sub-items) -->
            <div class="col-sm-12 col-md-3">
                <h3>Accoudoir</h3>
                <a class="badge bg-green text-green-fg"
                   href="/list-articles/108575/100860/manufacturer-id-36/...">List products</a>
                <br>
                <a class="badge bg-green text-green-fg"
                   href="/list-oem-articles/108575/100860/manufacturer-id-36/...">List OEM products</a>
            </div>

            <!-- Level 2: Subcategory WITH sub-subcategories -->
            <div class="col-sm-12 col-md-3">
                <h3>Pompe / accessoires</h3>
                <ul>
                    <!-- Level 3: Sub-subcategory -->
                    <li>
                        <strong>Pompe d'alimentation</strong>
                        <a href="/list-articles/108575/100717/...">List products</a>
                        <a href="/list-oem-articles/108575/100717/...">List OEM products</a>
                    </li>
                    <li>
                        <strong>Réparation</strong>
                        <a href="/list-articles/108575/100719/...">List products</a>
                        <a href="/list-oem-articles/108575/100719/...">List OEM products</a>
                    </li>
                </ul>
            </div>

        </div>
    </div>
</div>
```

**Fields per group entry** (one entry per unique `list-articles` or `list-oem-articles` link):
| Field | Source | Notes |
|---|---|---|
| `group_id` | From URL: `/list-articles/{car_type_id}/(\d+)/` | Second numeric segment |
| `car_type_id` | From URL: `/list-articles/(\d+)/` | First numeric segment |
| `primary_group_name` | `accordion-button` text (strip) | Level 1 category name |
| `subcategory_name` | `h3` text (strip) in `col-md-3` | Level 2 name |
| `sub_subcategory_name` | `li > strong` text (strip) | Level 3 name — empty string if no sub-subcategory |
| `group_name` | Concatenation: `primary > subcategory [ > sub_subcategory]` | Full hierarchy label |
| `list_articles_url` | `a[href*='/list-articles/']` → absolute URL | Links to Step 6 |
| `list_oem_articles_url` | `a[href*='/list-oem-articles/']` → absolute URL | OEM variant — crawl separately |

**Parsing algorithm:**
```
For each div.accordion-item:
    primary_name = button.text() in h1.accordion-header

    For each div.col-sm-12.col-md-3 in accordion-body:
        sub_name = h3.text() if present else ""

        if div has no ul>li children:
            # Level 2 only — links are direct children of col-md-3
            list_url = a[href*='/list-articles/'].href
            oem_url  = a[href*='/list-oem-articles/'].href
            emit entry(primary_name, sub_name, "", list_url, oem_url)
        else:
            # Level 3 — links inside li elements
            for li in ul > li:
                sub_sub_name = li > strong.text()
                list_url = li a[href*='/list-articles/'].href
                oem_url  = li a[href*='/list-oem-articles/'].href
                emit entry(primary_name, sub_name, sub_sub_name, list_url, oem_url)
```

**Parsing notes:**
- Both `list_articles_url` AND `list_oem_articles_url` must be recorded per entry.
- The OEM articles URL follows the same group_id structure — crawl it the same way as `list-articles`.
- Deduplicate by `list_articles_url`.
- The `group_id` embedded in the URL is the stable join key — not the group_name text.

**Output file:** `data/category_groups.jsonl`

---

## Step 6 — Articles List

**URL patterns:**
- `/list-articles/{car_type_id}/{group_id}/manufacturer-id-{manufacturer_id}/...`
- `/list-oem-articles/{car_type_id}/{group_id}/manufacturer-id-{manufacturer_id}/...`

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/list-articles/108575/101779/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1

**Page-level fields:**
| Field | Selector | Notes |
|---|---|---|
| `article_count` | `div.container h1` text → regex `r"List \(\s*(\d+)\s*\)"` | e.g. 28 |

**Verified article card HTML:**
```html
<div class="colman col-12 col-md-4 col-lg-4 mb-3">
    <div class="card">
        <div class="card-body">
            <h5 class="card-title"><strong>Doublure d'aile</strong></h5>
            <p class="card-text">Article ID: 2361730</p>
            <p class="card-text">
                Article Part No:
                <strong>2726,138,1</strong>
            </p>
            <p class="card-text">Manufacturer: <strong>BINDER</strong></p>
            <p class="card-text">Supplier ID: 4202</p>
            <p class="card-text">Products ID: 421</p>
            <hr>
            <div class="img-responsive img-responsive-21x9 card-img-bottom"
                 style="background-image: url(https://auto-car-parts.s3.amazonaws.com/.../img.webp)">
            </div>
        </div>
        <div class="card-footer">
            <a class="btn btn-success"
               href="/article-details/2361730/model-series-id-9155/manufacturer-id-36/...">
                Article Details
            </a>
        </div>
    </div>
</div>
```

**Card selector:** `div.colman.col-12.col-md-4.col-lg-4.mb-3 div.card`

**Fields per article card:**
| Field | Selector / Pattern | Notes |
|---|---|---|
| `part_name` | `h5.card-title strong` text (strip) | e.g. "Doublure d'aile" |
| `article_id` | `div.card-footer a[href*='/article-details/']` href → regex `r"/article-details/(\d+)/"` | Always from URL — most reliable source |
| `part_number` | `p.card-text:contains("Article Part No") strong` text (strip) | e.g. "2726,138,1" |
| `article_manufacturer` | `p.card-text:contains("Manufacturer") strong` text (strip) | e.g. "BINDER" |
| `supplier_id` | `p.card-text:contains("Supplier ID")` text → regex `r"Supplier ID:\s*(\d+)"` | e.g. 4202 (int) |
| `product_id` | `p.card-text:contains("Products ID")` text → regex `r"Products ID:\s*(\d+)"` | e.g. 421 (int) |
| `thumbnail_url` | `div.img-responsive.card-img-bottom[style]` → regex `r"url\(([^)]+)\)"` from style attr | S3 URL — preview image on list page |
| `details_url` | `div.card-footer a.btn-success[href*='/article-details/']` → absolute URL | Links to Step 7 |

**Parsing notes:**
- `article_id` MUST come from the URL, not from a regex on blob text. The URL is always present and reliable.
- `thumbnail_url` is a background-image CSS value — extract with `re.search(r"url\(([^)]+)\)", style)`.
- `p.card-text` elements do not have unique IDs — iterate all `p.card-text` and match by text prefix ("Article ID:", "Article Part No:", etc.).
- Deduplicate by `details_url`.

**Output file:** `data/articles.jsonl`

---

## Step 7 — Article Details ⚠ CRITICAL

**URL pattern:** `/article-details/{article_id}/model-series-id-{model_series_id}/manufacturer-id-{manufacturer_id}/lang-id-{lang_id}/country-filter-id-{country_id}/type-id-{type_id}`

**Test URL:** https://auto-parts-catalog.makingdatameaningful.com/article-details/2361727/model-series-id-9155/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1

> This is the most important page. It contains the complete part specification as a variable key/value dictionary. Every article has a different set of fields.

**Page title:**
| Field | Selector | Notes |
|---|---|---|
| `article_name` | `div.container h1` (first, skip "AUTO PARTS CATALOG", skip section headings: "Tehnic Details", "Image Details", "Compatible Cars") | e.g. "Aile BINDER 2726,135,11 for FORD FOCUS III" |

**Page layout:** Two-column row, then image carousel row, then compatible cars row.

---

### 7a — Technical Details (Left Column)

**Selector:** First `div.col-md-6` in the technical details row

**Verified structure:**
```html
<div class="col-md-6">
    <h1>Tehnic Details</h1>
    <ul class="list-group">
        <li class="list-group-item">
            <strong>Côté d'assemblage</strong>
            <span class="float-end">avant gauche</span>
        </li>
        <li class="list-group-item">
            <strong>Surface</strong>
            <span class="float-end">zingué</span>
        </li>
    </ul>
</div>
```

**Selector per item:** `li.list-group-item` → `strong` (key) + `span.float-end` (value)

**Fields:**
| Field | Source | Notes |
|---|---|---|
| `technical_details` | List of `{key: str, value: str}` | Variable per article. Keys are physical/technical attributes. |

**Parsing:** `key = li.css_first("strong").text(strip=True)` / `value = li.css_first("span.float-end").text(strip=True)`

---

### 7b — Article Identification Details (Right Column)

**Selector:** Second `div.col-md-6` in the technical details row

**Verified structure:**
```html
<div class="col-md-6">
    <h1>Tehnic Details</h1>
    <ul class="list-group">
        <li class="list-group-item">
            <strong> Article ID: </strong>
            <span class="float-end">2361727</span>
        </li>
        <li class="list-group-item">
            <strong> Article Number: </strong>
            <span class="float-end">2726,135,11</span>
        </li>
        <li class="list-group-item">
            <strong> Manufacturer: </strong>
            <span class="float-end">BINDER</span>
        </li>
        <li class="list-group-item">
            <strong> EAN Numbers: </strong>
            <span class="float-end">0900872147770</span>
        </li>
        <li class="list-group-item">
            <strong> OEM Numbers FORD: </strong>
            <span class="float-end">1718100</span>
        </li>
        <li class="list-group-item">
            <strong> OEM Numbers FORD: </strong>
            <span class="float-end">1722659</span>
        </li>
    </ul>
</div>
```

**Fields extracted from right column:**
| Field | Key pattern | Output field | Notes |
|---|---|---|---|
| `ean_numbers` | key starts with "EAN Numbers" | `list[str]` | One or more values |
| `oem_numbers` | key starts with "OEM Numbers" | `list[{brand, number}]` | brand = part after "OEM Numbers " (e.g. "FORD"), number = value. Multiple entries per brand. |
| `article_number` | key == "Article Number" | `str` | Manufacturer's part number |
| `article_manufacturer_detail` | key == "Manufacturer" | `str` | From right column — may differ from list-page manufacturer |

**Parsing algorithm for right column:**
```
for li in right_col.css("li.list-group-item"):
    key = li.css_first("strong").text(strip=True)
    value = li.css_first("span.float-end").text(strip=True)
    if key.startswith("OEM Numbers"):
        brand = key.replace("OEM Numbers", "").strip(": ")
        oem_numbers.append({"brand": brand, "number": value})
    elif key.startswith("EAN Numbers"):
        ean_numbers.append(value)
    else:
        identification_details[key.strip(": ")] = value
```

---

### 7c — Image Details (Carousel)

**Verified structure:**
```html
<div id="carousel-sample" class="carousel slide">
    <div class="carousel-inner">
        <div class="carousel-item">
            <img class="d-block w-100" alt="Photo"
                 src="https://auto-car-parts.s3.us-east-1.amazonaws.com/media_unziped/IMAGES/4202/2b2d...webp">
        </div>
        <div class="carousel-item active">
            <img class="d-block w-100" alt="Photo"
                 src="https://auto-car-parts.s3.us-east-1.amazonaws.com/media_unziped/IMAGES/4202/9bd4...webp">
        </div>
    </div>
</div>
```

**Selector:** `div#carousel-sample div.carousel-item img[src]`

**Fields:**
| Field | Source | Notes |
|---|---|---|
| `image_urls` | `img[src]` → deduplicated list | All images are S3 URLs. Carousel may have 1–10+ images. |

**Parsing notes:**
- Use the specific carousel selector, NOT `tree.css("img")` — the latter picks up logos, icons, and UI elements.
- All valid article images have `src` starting with `https://auto-car-parts.s3.us-east-1.amazonaws.com`.
- Deduplicate the list (some carousels repeat the active image).

---

### 7d — Compatible Cars Table

**Verified structure:**
```html
<div class="card-header"><h1>Compatible Cars</h1></div>
<div class="table-responsive">
    <table class="table card-table table-vcenter text-nowrap">
        <thead>
            <tr>
                <th>vehicleId</th>
                <th>modelId</th>
                <th>manufacturerName</th>
                <th>modelName</th>
                <th>typeEngineName</th>
                <th>constructionIntervalStart</th>
                <th>constructionIntervalEnd</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>7965</td>
                <td>9156</td>
                <td>FORD</td>
                <td>FOCUS III A trois volumes</td>
                <td>1.6 Ti</td>
                <td>2010-07-01</td>
                <td></td>
            </tr>
        </tbody>
    </table>
</div>
```

**Selector:** `div.table-responsive table tr`

**Columns (0-indexed):**
| Index | Field name | Type | Notes |
|---|---|---|---|
| 0 | `car_type_id` | int | vehicleId |
| 1 | `model_series_id` | int | modelId |
| 2 | `manufacturer_name` | str | e.g. "FORD" |
| 3 | `model_name` | str | e.g. "FOCUS III A trois volumes" |
| 4 | `engine_or_variant` | str | typeEngineName e.g. "1.6 Ti" |
| 5 | `year_from` | str | constructionIntervalStart (YYYY-MM-DD) |
| 6 | `year_to` | str | constructionIntervalEnd (YYYY-MM-DD or empty) |
| 7 | `extra_qualifier` | str | Present in some tables, empty string if absent |

**Parsing notes:**
- Skip header row (tr with th elements).
- `constructionIntervalEnd` empty = the vehicle is still in production.
- A compatible_cars list can have 600+ rows — always capture all of them.
- `extra_qualifier` (column 7) appears in some tables and not others — always use `row[7] if len(row) > 7 else ""`.

**Output file:** `data/article_details.jsonl`

---

## Complete Output Schema

```
data/
  manufacturers.jsonl       — {manufacturer_id, name, url, lang_id, country_id, type_id}
  models.jsonl              — {model_series_id, manufacturer_id, display_name, model_native_name, from_date, to_date, url, lang_id, country_id, type_id}
  car_types.jsonl           — {car_type_id, model_series_id, manufacturer_id, type_label, engine_code, cylinder, capacity, fuel_type, year_range, year_from, year_to, power, category_url, details_url, lang_id, country_id, type_id}
  car_type_details.jsonl    — {car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, details_url, car_type_title, construction_interval, year_from, year_to, details[]}
  category_groups.jsonl     — {group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, primary_group_name, subcategory_name, sub_subcategory_name, group_name, list_articles_url, list_oem_articles_url}
  articles.jsonl            — {article_id, group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, part_name, part_number, article_manufacturer, supplier_id, product_id, thumbnail_url, details_url}
  article_details.jsonl     — {article_id, group_id, car_type_id, model_series_id, manufacturer_id, lang_id, country_id, type_id, article_name, article_number, ean_numbers[], oem_numbers[{brand,number}], technical_details[{key,value}], image_urls[], compatible_cars[{car_type_id, model_series_id, manufacturer_name, model_name, engine_or_variant, year_from, year_to, extra_qualifier}], details_url}
  checkpoint.db             — SQLite WAL. seen_urls table: {url, status_code, timestamp, error_message}
```

---

## Parser Implementation Gaps (vs current code)

The following gaps exist in the current `parser.py` and `crawler.py` relative to this specification:

| # | File | Current | Required |
|---|---|---|---|
| 1 | `parser.py:parse_model_series` | Only extracts `display_name` + `url` | Must also extract `model_native_name`, `from_date`, `to_date` from `p.card-text` |
| 2 | `parser.py:parse_category_groups` | `a[href*='/list-articles/']` flat selector | Must traverse accordion 3-level hierarchy, extract `primary_group_name`, `subcategory_name`, `sub_subcategory_name`, and `list_oem_articles_url` |
| 3 | `crawler.py` | Only crawls `list_articles_url` per group | Must also queue `list_oem_articles_url` for each group |
| 4 | `parser.py:parse_articles_list` | Blob text regex for all fields | Must use card structure: `h5.card-title strong`, `p.card-text` per field, background-image for `thumbnail_url` |
| 5 | `parser.py:parse_article_details` | `li strong` key + string-strip for value | Must use `span.float-end` for values; split right column to extract `ean_numbers`, `oem_numbers`, `article_number` separately |
| 6 | `parser.py:parse_article_details` | `tree.css("img")` (all images) | Must use `div#carousel-sample div.carousel-item img[src]` (carousel only) |

---

## Test URLs Reference

| Step | URL |
|---|---|
| 1 — Manufacturers | https://auto-parts-catalog.makingdatameaningful.com/manufacturers/lang-id-6/country-filter-id-145/type-id-1 |
| 2 — Models (Ford) | https://auto-parts-catalog.makingdatameaningful.com/models/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1 |
| 3 — Car Types (Focus III) | https://auto-parts-catalog.makingdatameaningful.com/passenger-car-types/9155/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1 |
| 4 — Car Type Details | https://auto-parts-catalog.makingdatameaningful.com/passenger-car-type-details/108575/manufacturer-id-36/lang-id-6/country-filter-id-145 |
| 5 — Category Groups | https://auto-parts-catalog.makingdatameaningful.com/list-category-products-groups/108575/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1 |
| 6 — Articles List | https://auto-parts-catalog.makingdatameaningful.com/list-articles/108575/101779/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1 |
| 7 — Article Details | https://auto-parts-catalog.makingdatameaningful.com/article-details/2361727/model-series-id-9155/manufacturer-id-36/lang-id-6/country-filter-id-145/type-id-1 |

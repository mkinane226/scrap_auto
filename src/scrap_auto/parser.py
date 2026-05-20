from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

_ARTICLE_ID_FROM_URL_RE = re.compile(r"/article-details/(\d+)/")


def _abs(base_url: str, href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return f"{base_url.rstrip('/')}/{href.lstrip('/')}"


def parse_manufacturers(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for node in tree.css("a[href*='/models/manufacturer-id-']"):
        name = (node.text() or "").strip()
        href = node.attributes.get("href", "")
        if not name or not href:
            continue
        out.append({"name": name, "url": _abs(base_url, href)})
    return dedupe_by_key(out, "url")


def parse_model_series(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for card in tree.css("div.colman.col-12.col-md-4.col-lg-4.mb-3 div.card"):
        link = card.css_first("h5.card-title a[href*='/passenger-car-types/']")
        if link is None:
            continue
        href = link.attributes.get("href", "")
        if not href:
            continue
        strong = link.css_first("strong")
        display_name = (strong.text(strip=True) if strong else link.text(strip=True)).strip()
        card_text = card.css_first("p.card-text")
        card_text_raw = card_text.text(separator="\n", strip=True) if card_text else ""
        native_name_node = card_text.css_first("strong") if card_text else None
        model_native_name = native_name_node.text(strip=True) if native_name_node else ""
        from_m = re.search(r"From:\s*([\d\-]+)", card_text_raw)
        to_m = re.search(r"To:\s*([\d\-]+)", card_text_raw)
        out.append({
            "display_name": display_name,
            "model_native_name": model_native_name,
            "from_date": from_m.group(1) if from_m else "",
            "to_date": to_m.group(1) if to_m else "",
            "url": _abs(base_url, href),
        })
    return dedupe_by_key(out, "url")


def parse_car_types_table(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    rows = tree.css("table.table.table-vcenter.card-table.table-striped tbody tr")
    if not rows:
        rows = tree.css("table tbody tr")
    for row in rows:
        td_nodes = row.css("td")
        cells = [c.text(strip=True) for c in td_nodes]
        if len(cells) < 10:
            continue
        year_from, year_to = parse_year_range(cells[6])
        car_details_link = td_nodes[8].css_first("a[href*='/passenger-car-type-details/']")
        category_link = td_nodes[9].css_first("a[href*='/list-category-products-groups/']")
        out.append(
            {
                "car_type_id": safe_int(cells[0]),
                "type_label": cells[1],
                "engine_code": cells[2],
                "cylinder": safe_int(cells[3]),
                "capacity": cells[4],
                "fuel_type": cells[5],
                "year_range": cells[6],
                "year_from": year_from,
                "year_to": year_to,
                "power": cells[7],
                "category_url": _abs(base_url, category_link.attributes.get("href", "")) if category_link else None,
                "details_url": _abs(base_url, car_details_link.attributes.get("href", "")) if car_details_link else None,
            }
        )
    return [r for r in out if r.get("car_type_id") is not None]


def parse_category_groups(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for accordion_item in tree.css("div.accordion-item"):
        btn = accordion_item.css_first("button.accordion-button")
        primary_name = btn.text(strip=True) if btn else ""
        accordion_body = accordion_item.css_first("div.accordion-body")
        if accordion_body is None:
            continue
        for col in accordion_body.css("div.col-sm-12.col-md-3"):
            h3 = col.css_first("h3")
            sub_name = h3.text(strip=True) if h3 else ""
            lis = col.css("ul li")
            if lis:
                for li in lis:
                    strong = li.css_first("strong")
                    sub_sub_name = strong.text(strip=True) if strong else ""
                    list_link = li.css_first("a[href*='/list-articles/']")
                    oem_link = li.css_first("a[href*='/list-oem-articles/']")
                    if not list_link:
                        continue
                    href = list_link.attributes.get("href", "")
                    oem_href = oem_link.attributes.get("href", "") if oem_link else ""
                    group_name = " > ".join(x for x in [primary_name, sub_name, sub_sub_name] if x)
                    out.append({
                        "primary_group_name": primary_name,
                        "subcategory_name": sub_name,
                        "sub_subcategory_name": sub_sub_name,
                        "group_name": group_name,
                        "list_articles_url": _abs(base_url, href),
                        "list_oem_articles_url": _abs(base_url, oem_href) if oem_href else "",
                    })
            else:
                list_link = col.css_first("a[href*='/list-articles/']")
                oem_link = col.css_first("a[href*='/list-oem-articles/']")
                if not list_link:
                    continue
                href = list_link.attributes.get("href", "")
                oem_href = oem_link.attributes.get("href", "") if oem_link else ""
                group_name = " > ".join(x for x in [primary_name, sub_name] if x)
                out.append({
                    "primary_group_name": primary_name,
                    "subcategory_name": sub_name,
                    "sub_subcategory_name": "",
                    "group_name": group_name,
                    "list_articles_url": _abs(base_url, href),
                    "list_oem_articles_url": _abs(base_url, oem_href) if oem_href else "",
                })
    return dedupe_by_key(out, "list_articles_url")


def parse_articles_list(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for card in tree.css("div.colman.col-12.col-md-4.col-lg-4.mb-3 div.card"):
        footer_link = card.css_first("div.card-footer a[href*='/article-details/']")
        if footer_link is None:
            continue
        href = footer_link.attributes.get("href", "")
        if not href:
            continue
        details_url = _abs(base_url, href)
        url_id_match = _ARTICLE_ID_FROM_URL_RE.search(href)
        article_id = int(url_id_match.group(1)) if url_id_match else None

        title_strong = card.css_first("h5.card-title strong")
        part_name = title_strong.text(strip=True) if title_strong else ""

        part_number = ""
        article_manufacturer = ""
        supplier_id: int | None = None
        product_id: int | None = None
        for p in card.css("p.card-text"):
            text = p.text(strip=True)
            if text.startswith("Article Part No"):
                strong = p.css_first("strong")
                part_number = strong.text(strip=True) if strong else re.sub(r"^Article Part No[:\s]*", "", text).strip()
            elif text.startswith("Manufacturer"):
                strong = p.css_first("strong")
                article_manufacturer = strong.text(strip=True) if strong else re.sub(r"^Manufacturer[:\s]*", "", text).strip()
            elif text.startswith("Supplier ID"):
                m = re.search(r"Supplier ID[:\s]*(\d+)", text, re.IGNORECASE)
                supplier_id = int(m.group(1)) if m else None
            elif text.startswith("Products ID"):
                m = re.search(r"Products ID[:\s]*(\d+)", text, re.IGNORECASE)
                product_id = int(m.group(1)) if m else None

        thumbnail_url = ""
        img_div = card.css_first("div.img-responsive.card-img-bottom")
        if img_div:
            style = img_div.attributes.get("style", "")
            m = re.search(r"url\(([^)]+)\)", style)
            if m:
                thumbnail_url = m.group(1).strip("'\" ")

        out.append({
            "part_name": part_name,
            "article_id": article_id,
            "part_number": part_number,
            "article_manufacturer": article_manufacturer,
            "supplier_id": supplier_id,
            "product_id": product_id,
            "thumbnail_url": thumbnail_url,
            "details_url": details_url,
        })
    return dedupe_by_key(out, "details_url")


def parse_article_details(html: str, base_url: str) -> dict[str, Any]:
    tree = HTMLParser(html)
    article_name = _extract_article_name(tree)

    image_urls = []
    for img in tree.css("div#carousel-sample div.carousel-item img[src]"):
        src = img.attributes.get("src", "")
        if src:
            image_urls.append(_abs(base_url, src))

    technical_pairs: list[dict[str, str]] = []
    oem_numbers: list[dict[str, str]] = []
    ean_numbers: list[str] = []
    article_number = ""

    for col in tree.css("div.col-md-6"):
        items = col.css("li.list-group-item")
        if not items:
            continue
        col_entries: list[tuple[str, str]] = []
        has_identification = False
        for li in items:
            strong = li.css_first("strong")
            span = li.css_first("span.float-end")
            if strong is None:
                continue
            key = strong.text(strip=True)
            value = span.text(strip=True) if span else ""
            col_entries.append((key, value))
            if key.startswith("OEM Numbers") or key.startswith("EAN Numbers") or key == "Article Number":
                has_identification = True

        if has_identification:
            for key, value in col_entries:
                if key.startswith("OEM Numbers"):
                    brand = key.replace("OEM Numbers", "").strip(": ")
                    oem_numbers.append({"brand": brand, "number": value})
                elif key.startswith("EAN Numbers"):
                    if value:
                        ean_numbers.append(value)
                elif key == "Article Number":
                    article_number = value
        else:
            for key, value in col_entries:
                if key:
                    technical_pairs.append({"key": key, "value": value})

    compatible_rows = []
    for tr in tree.css("div.table-responsive table tr"):
        if tr.css("th"):
            continue
        row = [td.text(strip=True) for td in tr.css("td")]
        if len(row) >= 6:
            compatible_rows.append(
                {
                    "car_type_id": safe_int(row[0]) if len(row) > 0 else None,
                    "model_series_id": safe_int(row[1]) if len(row) > 1 else None,
                    "manufacturer_name": row[2] if len(row) > 2 else "",
                    "model_name": row[3] if len(row) > 3 else "",
                    "engine_or_variant": row[4] if len(row) > 4 else "",
                    "year_from": row[5] if len(row) > 5 else "",
                    "year_to": row[6] if len(row) > 6 else "",
                    "extra_qualifier": row[7] if len(row) > 7 else "",
                }
            )

    return {
        "article_name": article_name,
        "article_number": article_number,
        "ean_numbers": dedupe_list(ean_numbers),
        "oem_numbers": oem_numbers,
        "image_urls": dedupe_list(image_urls),
        "technical_details": technical_pairs,
        "compatible_cars": compatible_rows,
    }


def parse_car_type_details(html: str) -> dict[str, Any]:
    tree = HTMLParser(html)

    title = ""
    for h1 in tree.css("div.container h1"):
        text = h1.text(strip=True)
        if not text:
            continue
        if text.upper().startswith("AUTO PARTS CATALOG"):
            continue
        title = text
        break

    details: list[dict[str, str]] = []
    dt_nodes = tree.css("div.container dl dt")
    dd_nodes = tree.css("div.container dl dd")
    for dt_node, dd_node in zip(dt_nodes, dd_nodes):
        key = dt_node.text(strip=True)
        value = dd_node.text(separator=" ", strip=True)
        if not key:
            continue
        details.append({"key": key, "value": value})

    construction_interval = next((i["value"] for i in details if i["key"].lower() == "construction interval"), "")
    year_from, year_to = _parse_interval_years(construction_interval)

    return {
        "car_type_title": title,
        "construction_interval": construction_interval,
        "year_from": year_from,
        "year_to": year_to,
        "details": details,
    }



def _extract_article_name(tree: HTMLParser) -> str:
    skip_titles = {"tehnic details", "image details", "compatible cars"}
    for h1 in tree.css("div.container h1"):
        text = h1.text(separator=" ", strip=True)
        if not text:
            continue
        text_l = text.lower()
        if text.upper().startswith("AUTO PARTS CATALOG"):
            continue
        if text_l in skip_titles:
            continue
        return text
    return ""


def _parse_interval_years(text: str) -> tuple[int | None, int | None]:
    year_from = _extract_int(r"From[:\s]+(?:\d{1,2}[/\-])?(\d{4})", text)
    year_to = _extract_int(r"To[:\s]+(?:\d{1,2}[/\-])?(\d{4})", text)
    return year_from, year_to


def parse_year_range(text: str) -> tuple[int | None, int | None]:
    # TecDoc concatenates ISO dates without separator: "YYYY-MM-DDYYYY-MM-DD"
    # Insert a space at the join so both years are extracted correctly.
    text = re.sub(r"(\d{4}-\d{2}-\d{2})(\d{4})", r"\1 \2", text)
    years = [int(y) for y in re.findall(r"(\d{4})", text) if 1800 <= int(y) <= 2100]
    if not years:
        return None, None
    return years[0], (years[1] if len(years) > 1 else None)


def _extract_text(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return safe_int(match.group(1))


def dedupe_by_key(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in items:
        value = str(item.get(key, ""))
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(item)
    return out


def dedupe_list(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def safe_int(value: str) -> int | None:
    value = (value or "").strip().replace(",", "")
    if not value.isdigit():
        return None
    return int(value)

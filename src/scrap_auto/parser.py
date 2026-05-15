from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser


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
    for node in tree.css("a[href*='/passenger-car-types/']"):
        href = node.attributes.get("href", "")
        text = (node.text() or "").strip()
        if not href:
            continue
        out.append({"display_name": text, "url": _abs(base_url, href)})
    return dedupe_by_key(out, "url")


def parse_car_types_table(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    rows = tree.css("table tr")
    for row in rows:
        cells = [c.text(strip=True) for c in row.css("td")]
        if len(cells) < 8:
            continue
        category_link = row.css_first("a[href*='/list-category-products-groups/']")
        car_details_link = row.css_first("a[href*='/passenger-car-type-details/']")
        out.append(
            {
                "car_type_id": safe_int(cells[0]),
                "type_label": cells[1],
                "engine_code": cells[2],
                "cylinder": safe_int(cells[3]),
                "capacity": cells[4],
                "fuel_type": cells[5],
                "year_range": cells[6],
                "power": cells[7],
                "category_url": _abs(base_url, category_link.attributes.get("href", "")) if category_link else None,
                "details_url": _abs(base_url, car_details_link.attributes.get("href", "")) if car_details_link else None,
            }
        )
    return [r for r in out if r.get("car_type_id") is not None]


def parse_category_groups(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for node in tree.css("a[href*='/list-articles/']"):
        href = node.attributes.get("href", "")
        if not href:
            continue
        block_text = ""
        parent = node.parent
        if parent is not None:
            block_text = parent.text(separator=" ", strip=True)
        out.append(
            {
                "group_name": block_text[:180],
                "list_articles_url": _abs(base_url, href),
            }
        )
    return dedupe_by_key(out, "list_articles_url")


def parse_articles_list(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    cards = tree.css("a[href*='/article-details/']")
    for link in cards:
        href = link.attributes.get("href", "")
        parent = link.parent
        blob = parent.text(separator=" ", strip=True) if parent is not None else ""
        part_name = ""
        if parent is not None:
            heading = parent.css_first("h5,strong")
            if heading is not None:
                part_name = heading.text(strip=True)

        parsed = _parse_article_blob(blob)
        out.append(
            {
                "part_name": part_name or parsed.get("part_name", ""),
                "article_id": parsed.get("article_id"),
                "part_number": parsed.get("part_number"),
                "article_manufacturer": parsed.get("article_manufacturer"),
                "supplier_id": parsed.get("supplier_id"),
                "product_id": parsed.get("product_id"),
                "raw_text": blob[:3000],
                "details_url": _abs(base_url, href),
            }
        )
    return dedupe_by_key(out, "details_url")


def parse_article_details(html: str, base_url: str) -> dict[str, Any]:
    tree = HTMLParser(html)

    image_urls = []
    for img in tree.css("img"):
        src = img.attributes.get("src", "")
        if not src:
            continue
        image_urls.append(_abs(base_url, src))

    technical_pairs = []
    oem_numbers = []
    for li in tree.css("li"):
        strong = li.css_first("strong")
        if strong is None:
            continue
        key = strong.text(strip=True)
        value = li.text(strip=True).replace(key, "", 1).strip(": ")
        if key:
            if key.startswith("OEM Numbers"):
                brand = key.replace("OEM Numbers", "").strip(" :")
                oem_numbers.append({"brand": brand, "number": value})
            else:
                technical_pairs.append({"key": key, "value": value})

    compatible_rows = []
    for tr in tree.css("table tr"):
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
                }
            )

    return {
        "image_urls": dedupe_list(image_urls),
        "technical_details": technical_pairs,
        "oem_numbers": oem_numbers,
        "compatible_cars": compatible_rows,
    }


def _parse_article_blob(blob: str) -> dict[str, Any]:
    article_id = _extract_int(r"Article\s+ID:\s*(\d+)", blob)
    supplier_id = _extract_int(r"Supplier\s+ID:\s*(\d+)", blob)
    product_id = _extract_int(r"Products\s+ID:\s*(\d+)", blob)
    part_number = _extract_text(r"Article\s+Part\s+No:\s*(.*?)\s+Manufacturer:", blob)
    article_manufacturer = _extract_text(r"Manufacturer:\s*(.*?)\s+Supplier\s+ID:", blob)

    return {
        "article_id": article_id,
        "part_number": part_number,
        "article_manufacturer": article_manufacturer,
        "supplier_id": supplier_id,
        "product_id": product_id,
    }


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

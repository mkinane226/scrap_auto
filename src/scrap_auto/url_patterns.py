from __future__ import annotations

import re
from dataclasses import dataclass


_MANUFACTURER_RE = re.compile(r"/models/manufacturer-id-(?P<manufacturer_id>\d+)/")
_MODEL_SERIES_RE = re.compile(r"/passenger-car-types/(?P<model_series_id>\d+)/manufacturer-id-(?P<manufacturer_id>\d+)/")
_CATEGORY_PAGE_RE = re.compile(r"/list-category-products-groups/(?P<car_type_id>\d+)/manufacturer-id-(?P<manufacturer_id>\d+)/")
_LIST_ARTICLES_RE = re.compile(r"/list-articles/(?P<car_type_id>\d+)/(?P<group_id>\d+)/manufacturer-id-(?P<manufacturer_id>\d+)/")
_ARTICLE_DETAILS_RE = re.compile(r"/article-details/(?P<article_id>\d+)/model-series-id-(?P<model_series_id>\d+)/manufacturer-id-(?P<manufacturer_id>\d+)/")


@dataclass(slots=True)
class ParsedIds:
    values: dict[str, int]


def _parse(pattern: re.Pattern[str], url: str) -> ParsedIds | None:
    match = pattern.search(url)
    if not match:
        return None
    return ParsedIds(values={k: int(v) for k, v in match.groupdict().items()})


def parse_manufacturer_url(url: str) -> ParsedIds | None:
    return _parse(_MANUFACTURER_RE, url)


def parse_model_series_url(url: str) -> ParsedIds | None:
    return _parse(_MODEL_SERIES_RE, url)


def parse_category_page_url(url: str) -> ParsedIds | None:
    return _parse(_CATEGORY_PAGE_RE, url)


def parse_list_articles_url(url: str) -> ParsedIds | None:
    return _parse(_LIST_ARTICLES_RE, url)


def parse_article_details_url(url: str) -> ParsedIds | None:
    return _parse(_ARTICLE_DETAILS_RE, url)


def is_in_scope(url: str, lang_id: int, country_id: int, type_id: int) -> bool:
    return (
        f"/lang-id-{lang_id}/" in url
        and f"/country-filter-id-{country_id}/" in url
        and f"/type-id-{type_id}" in url
    )

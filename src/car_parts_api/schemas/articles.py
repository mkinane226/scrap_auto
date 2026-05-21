from __future__ import annotations

from pydantic import BaseModel


class OemNumber(BaseModel):
    brand: str
    number: str


class TechnicalDetail(BaseModel):
    key: str
    value: str


class ArticleResult(BaseModel):
    article_id: int
    part_name: str | None
    part_number: str | None
    article_manufacturer: str | None
    group_id: int | None
    is_oem: bool
    thumbnail_url: str | None


class ArticleSearchResponse(BaseModel):
    total: int
    offset: int
    limit: int
    results: list[ArticleResult]


class ArticleDetail(BaseModel):
    article_id: int
    article_name: str | None
    part_number: str | None
    article_number: str | None
    article_manufacturer: str | None
    is_oem: bool
    thumbnail_url: str | None
    ean_numbers: list[str]
    oem_numbers: list[OemNumber]
    technical_details: list[TechnicalDetail]
    image_urls: list[str]


class CompatibleCar(BaseModel):
    car_type_id: int | None
    model_series_id: int | None
    manufacturer_name: str
    model_name: str
    engine_or_variant: str
    year_from: str
    year_to: str
    extra_qualifier: str

from __future__ import annotations

from pydantic import BaseModel


class ManufacturerOut(BaseModel):
    id: int
    name: str


class ModelSeriesOut(BaseModel):
    id: int
    manufacturer_id: int | None
    display_name: str
    model_native_name: str
    year_from: str | None
    year_to: str | None


class CarTypeOut(BaseModel):
    id: int
    model_series_id: int | None
    manufacturer_id: int | None
    type_label: str | None
    engine_code: str | None
    cylinder: int | None
    capacity: str | None
    fuel_type: str | None
    power: str | None
    year_from: int | None
    year_to: int | None
    car_type_title: str | None
    technical_specs: list[dict] | None


class GroupOut(BaseModel):
    id: int
    group_name: str
    primary_group_name: str
    subcategory_name: str
    sub_subcategory_name: str


class StatsOut(BaseModel):
    manufacturers: int
    model_series: int
    car_types: int
    articles: int
    compatible_cars: int

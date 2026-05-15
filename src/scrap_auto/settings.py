from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CrawlConfig:
    base_url: str = "https://auto-parts-catalog.makingdatameaningful.com"
    lang_id: int = 6
    country_id: int = 145
    type_id: int = 1
    timeout_seconds: float = 30.0
    concurrency: int = 5
    min_delay_seconds: float = 0.3
    max_delay_seconds: float = 1.0
    user_agent: str = "scrap-auto-bot/0.1 (+contact: your-email@example.com)"
    output_dir: Path = Path("data")
    verbose: bool = False
    progress_every: int = 25


@dataclass(slots=True)
class CrawlLimits:
    max_manufacturers: int | None = None
    max_models_per_manufacturer: int | None = None
    max_car_types_per_model: int | None = None
    max_groups_per_car_type: int | None = None
    max_articles_per_group: int | None = None

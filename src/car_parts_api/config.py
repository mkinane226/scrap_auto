from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTOPARTS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""
    api_key: str = ""
    pool_min_size: int = 2
    pool_max_size: int = 10
    debug: bool = False


settings = Settings()

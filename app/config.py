from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env_mode: str = Field(default="test", pattern="^(prod|test)$")

    database_url: str
    clickhouse_url: str
    clickhouse_db: str

    lag_proxy_url: str
    lag_proxy_timeout: float = 30.0

    oauth2_introspect_url: str
    oauth2_introspect_timeout: float = 5.0
    oauth2_token_cache_max: int = 1000
    oauth2_token_cache_default_ttl: int = 300
    default_client_id: str = "maas2ss"

    enable_docs: bool = True

    internal_api_key: str
    cost_cache_managed_ttl: int = 300
    cost_cache_rate_ttl: int = 600
    billing_service_url: str

    model_config = SettingsConfigDict(
        env_file=(".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def team_id_prefix(self) -> str:
        return "AI_PRD" if self.env_mode == "prod" else "AI_TEST"


@lru_cache
def get_settings() -> Settings:
    return Settings()

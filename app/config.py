from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env_mode: str = Field(default="test", pattern="^(prod|test)$")

    database_url: str
    ch_dbt_scheme: str = "https"
    ch_dbt_host: str
    ch_dbt_port: int = 8123
    ch_dbt_user: str
    ch_dbt_password: str
    ch_dbt_database: str
    ch_dbt_billing_table: str = "dws_para_statements_changelog"

    lag_proxy_url: str
    lag_proxy_timeout: float = 30.0

    oauth2_introspect_url: str
    oauth2_introspect_timeout: float = 5.0
    oauth2_token_cache_max: int = 1000
    oauth2_token_cache_default_ttl: int = 300
    default_client_id: str = "maas2ss"

    enable_docs: bool = True
    enable_debug_routes: bool | None = None

    internal_api_key: str
    cost_cache_managed_ttl: int = 300
    cost_cache_rate_ttl: int = 600
    billing_service_url: str = ""
    billing_service_cost_path: str = "/api/v1/cost/calculate"
    billing_service_timeout: float = 5.0

    model_config = SettingsConfigDict(
        env_file=(".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def team_id_prefix(self) -> str:
        return "AI_PRD" if self.env_mode == "prod" else "AI_TEST"

    @property
    def debug_routes_enabled(self) -> bool:
        if self.enable_debug_routes is not None:
            return self.enable_debug_routes
        return self.env_mode != "prod"

    @property
    def clickhouse_url(self) -> str:
        return f"{self.ch_dbt_scheme}://{self.ch_dbt_host}:{self.ch_dbt_port}"

    @property
    def clickhouse_db(self) -> str:
        return self.ch_dbt_database

    @property
    def clickhouse_user(self) -> str:
        return self.ch_dbt_user

    @property
    def clickhouse_password(self) -> str:
        return self.ch_dbt_password

    @property
    def clickhouse_billing_table(self) -> str:
        return self.ch_dbt_billing_table


@lru_cache
def get_settings() -> Settings:
    return Settings()

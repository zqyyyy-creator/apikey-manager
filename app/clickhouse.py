import json
from typing import Any

import httpx

from app.config import get_settings


class ClickHouseError(Exception):
    pass


class ClickHouseClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.url = settings.clickhouse_url.rstrip("/")
        self.database = settings.clickhouse_db
        self.billing_table = settings.clickhouse_billing_table
        self.auth = (
            (settings.clickhouse_user, settings.clickhouse_password or "")
            if settings.clickhouse_user
            else None
        )

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.url}/ping", auth=self.auth)
                response.raise_for_status()
                return response.text.strip() == "Ok."
        except httpx.HTTPError:
            return False

    async def query_json_each_row(
        self,
        sql: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        request_params = {"database": self.database}
        if params:
            request_params.update({f"param_{key}": value for key, value in params.items()})

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.url,
                    params=request_params,
                    content=sql,
                    auth=self.auth,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClickHouseError("ClickHouse query failed") from exc

        rows = []
        for line in response.text.splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


def get_clickhouse_client() -> ClickHouseClient:
    return ClickHouseClient()


async def check_clickhouse_health() -> bool:
    return await get_clickhouse_client().ping()

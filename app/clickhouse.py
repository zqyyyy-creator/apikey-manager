import httpx

from app.config import get_settings


class ClickHouseClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.url = settings.clickhouse_url.rstrip("/")
        self.database = settings.clickhouse_db

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.url}/ping")
                response.raise_for_status()
                return response.text.strip() == "Ok."
        except httpx.HTTPError:
            return False


def get_clickhouse_client() -> ClickHouseClient:
    return ClickHouseClient()


async def check_clickhouse_health() -> bool:
    return await get_clickhouse_client().ping()

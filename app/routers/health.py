from fastapi import APIRouter

from app.config import get_settings
from app.clickhouse import check_clickhouse_health
from app.database import check_mysql_health

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    summary="服务健康检查",
    description="检查 MaaS API、MySQL 和 ClickHouse 连接状态。",
)
async def health_check() -> dict[str, object]:
    settings = get_settings()
    mysql_up = await check_mysql_health()
    clickhouse_up = await check_clickhouse_health()
    healthy = mysql_up and clickhouse_up

    return {
        "status": "healthy" if healthy else "degraded",
        "environment": settings.env_mode,
        "services": {
            "mysql": "up" if mysql_up else "down",
            "clickhouse": "up" if clickhouse_up else "down",
        },
    }

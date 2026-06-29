from app.main import app
from app.routers import health
from tests.asgi_client import asgi_get


def test_health_returns_service_status(monkeypatch) -> None:  # noqa: ANN001
    async def fake_mysql_health() -> bool:
        return True

    async def fake_clickhouse_health() -> bool:
        return True

    monkeypatch.setattr(health, "check_mysql_health", fake_mysql_health)
    monkeypatch.setattr(health, "check_clickhouse_health", fake_clickhouse_health)

    response = asgi_get(app, "/health")

    assert response.status_code == 200
    assert response.headers["x-trace-id"]
    body = response.json()
    assert body["environment"] == "test"
    assert body["services"].keys() == {"mysql", "clickhouse"}
    assert body["status"] == "healthy"

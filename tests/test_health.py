from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_service_status() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-trace-id"]
    body = response.json()
    assert body["environment"] == "test"
    assert body["services"].keys() == {"mysql", "clickhouse"}
    assert body["status"] in {"healthy", "degraded"}

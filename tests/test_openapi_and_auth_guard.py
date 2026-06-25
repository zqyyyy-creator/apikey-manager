from fastapi.testclient import TestClient

from app.main import app


def test_openapi_includes_key_management_routes() -> None:
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/keys" in paths
    assert set(paths["/api/v1/keys"]) == {"get", "post"}
    assert "/api/v1/keys/{key_id}" in paths
    assert "/api/v1/keys/{key_id}/revoke" in paths
    assert "/api/v1/keys/{key_id}/unblock" in paths
    assert "/api/v1/keys/{key_id}/limits" in paths
    assert "/api/v1/keys/{key_id}/limits/{limit_id}" in paths


def test_key_routes_require_authentication() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/keys", headers={"x-user-id": "12345"})

    assert response.status_code == 401
    assert response.json() == {
        "code": 40100,
        "data": None,
        "message": "Missing bearer token",
    }

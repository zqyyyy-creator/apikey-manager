from app.dependencies import get_auth_service
from app.main import app
from app.services.auth_service import AuthService
from tests.asgi_client import asgi_get


async def fake_auth_service() -> AuthService:
    return AuthService()


def test_openapi_includes_key_management_routes() -> None:
    response = asgi_get(app, "/openapi.json")

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
    app.dependency_overrides[get_auth_service] = fake_auth_service
    try:
        response = asgi_get(app, "/api/v1/keys", headers={"x-user-id": "12345"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {
        "code": 40100,
        "data": None,
        "message": "Missing bearer token",
    }

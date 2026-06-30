import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.dependencies import get_auth_service, get_current_auth_context
from app.main import app
from app.schemas.auth import AuthContext
from app.services.auth_service import AuthPermissionError, AuthService


async def fake_auth_service() -> AuthService:
    return AuthService()


def test_debug_auth_requires_bearer_token() -> None:
    from tests.asgi_client import asgi_get

    app.dependency_overrides[get_auth_service] = fake_auth_service
    try:
        response = asgi_get(
            app,
            "/api/v1/debug/auth",
            headers={"x-user-id": "12345"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {
        "code": 40100,
        "data": None,
        "message": "Missing bearer token",
    }
    assert response.headers["x-trace-id"]


def test_debug_auth_missing_x_user_id_uses_unified_error_response() -> None:
    from tests.asgi_client import asgi_get

    app.dependency_overrides[get_auth_service] = fake_auth_service
    try:
        response = asgi_get(
            app,
            "/api/v1/debug/auth",
            headers={"Authorization": "Bearer fake-token"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 40000
    assert body["message"] == "Request parameter error"
    assert body["data"]["errors"][0]["loc"] == ["header", "x-user-id"]
    assert response.headers["x-trace-id"]


def test_debug_auth_can_use_dependency_override() -> None:
    async def fake_auth_context() -> AuthContext:
        return AuthContext(
            client_id="maas2ss",
            user_id="12345",
            team_id="AI_TEST_12345",
            access_token="token_123",
        )

    app.dependency_overrides[get_current_auth_context] = fake_auth_context

    try:
        from tests.asgi_client import asgi_get

        response = asgi_get(app, "/api/v1/debug/auth")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "data": {
            "client_id": "maas2ss",
            "user_id": "12345",
            "team_id": "AI_TEST_12345",
            "access_token": "token_123",
        },
        "message": "success",
    }


def test_debug_routes_are_disabled_by_default_in_prod() -> None:
    settings = Settings(
        env_mode="prod",
        database_url="sqlite+aiosqlite:///:memory:",
        ch_dbt_host="clickhouse.example.com",
        ch_dbt_user="user",
        ch_dbt_password="password",
        ch_dbt_database="dev_dbt_data",
        lag_proxy_url="http://lag-proxy",
        oauth2_introspect_url="http://auth/introspect",
        internal_api_key="internal-key",
        billing_service_url="http://billing",
    )

    assert settings.debug_routes_enabled is False


def test_auth_service_authenticate_builds_auth_context() -> None:
    service = AuthService()
    service.get_client_id = AsyncMock(return_value="maas2ss")
    service.get_user_id_by_client_id = AsyncMock(return_value="12345")

    auth = asyncio.run(
        service.authenticate(
            db=None,
            token="fake-token",
            x_user_id="12345",
        )
    )

    assert auth == AuthContext(
        client_id="maas2ss",
        user_id="12345",
        team_id="AI_TEST_12345",
        access_token="fake-token",
    )


def test_auth_service_rejects_mismatched_user_id() -> None:
    service = AuthService()
    service.get_client_id = AsyncMock(return_value="maas2ss")
    service.get_user_id_by_client_id = AsyncMock(return_value="12345")

    with pytest.raises(AuthPermissionError):
        asyncio.run(
            service.authenticate(
                db=None,
                token="fake-token",
                x_user_id="67890",
            )
        )


def test_auth_service_introspection_sends_configured_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_data = {}

    async def fake_post(self, url, data):  # noqa: ANN001
        captured_data.update(data)
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"active": True, "client_id": "maas2ss"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = AuthService()
    data = asyncio.run(service.introspect_token("fake-token"))

    assert data == {"active": True, "client_id": "maas2ss"}
    assert captured_data == {
        "token": "fake-token",
        "client_id": "maas2ss",
    }

import asyncio
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from app.dependencies import get_current_auth_context
from app.main import app
from app.schemas.auth import AuthContext
from app.services.auth_service import AuthPermissionError, AuthService


def test_debug_auth_requires_bearer_token() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/debug/auth", headers={"x-user-id": "12345"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing bearer token"}
    assert response.headers["x-trace-id"]


def test_debug_auth_can_use_dependency_override() -> None:
    async def fake_auth_context() -> AuthContext:
        return AuthContext(
            client_id="maas2ss",
            user_id="12345",
            team_id="AI_TEST_12345",
        )

    app.dependency_overrides[get_current_auth_context] = fake_auth_context
    client = TestClient(app)

    try:
        response = client.get("/api/v1/debug/auth")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "client_id": "maas2ss",
        "user_id": "12345",
        "team_id": "AI_TEST_12345",
    }


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

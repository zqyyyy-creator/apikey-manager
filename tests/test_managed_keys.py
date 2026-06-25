from datetime import datetime

from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.litellm_integration.client import GeneratedKey
from app.main import app
from app.models.managed_key import ManagedKey
from app.routers.managed_keys import get_managed_key_service
from app.schemas.auth import AuthContext
from app.schemas.common import PageData
from app.schemas.managed_key import (
    CreateKeyData,
    CreateKeyRequest,
    ManagedKeyDetail,
    ManagedKeyListItem,
    RevokeKeyData,
    RevokeKeyRequest,
    UnblockKeyData,
    UnblockKeyRequest,
)
from app.services.managed_key_service import ManagedKeyService


def auth_context() -> AuthContext:
    return AuthContext(
        client_id="maas2ss",
        user_id="12345",
        team_id="AI_TEST_12345",
        access_token="token_123",
    )


async def fake_auth_context() -> AuthContext:
    return auth_context()


async def fake_db():
    yield None


def clear_overrides() -> None:
    app.dependency_overrides.clear()


class FakeManagedKeyService:
    async def create_key(self, db, auth, request):  # noqa: ANN001
        assert auth.team_id == "AI_TEST_12345"
        assert request == CreateKeyRequest(
            name="production-api-key",
            description="生产环境 API 调用专用 key",
        )
        return CreateKeyData(
            id="hash_001",
            name=request.name,
            description=request.description,
            key="sk-maas-secret",
            key_alias="sk...cret",
            status="active",
            created_at=datetime(2025, 6, 17, 10, 0, 0),
        )

    async def list_keys(self, db, auth, **kwargs):  # noqa: ANN001
        assert auth.team_id == "AI_TEST_12345"
        assert kwargs["page"] == 1
        assert kwargs["page_size"] == 20
        return PageData[ManagedKeyListItem](
            items=[
                ManagedKeyListItem(
                    id="hash_001",
                    name="production-api-key",
                    description="生产环境 API 调用专用 key",
                    team_id="AI_TEST_12345",
                    key_alias="sk...cret",
                    status="active",
                    created_at=datetime(2025, 6, 17, 10, 0, 0),
                    blocked_reason=None,
                    blocked_at=None,
                    revoked_at=None,
                )
            ],
            total=1,
            page=1,
            page_size=20,
        )

    async def get_key(self, db, auth, key_id):  # noqa: ANN001
        assert key_id == "hash_001"
        return ManagedKeyDetail(
            id="hash_001",
            name="production-api-key",
            description="生产环境 API 调用专用 key",
            team_id=auth.team_id,
            key_alias="sk...cret",
            status="active",
            created_at=datetime(2025, 6, 17, 10, 0, 0),
            blocked_reason=None,
            blocked_at=None,
            revoked_at=None,
            spending_limits=[],
            usage_summary=None,
        )

    async def revoke_key(self, db, auth, key_id, request):  # noqa: ANN001
        assert key_id == "hash_001"
        assert request == RevokeKeyRequest(reason="rotate")
        return RevokeKeyData(
            id="hash_001",
            status="revoked",
            revoked_at=datetime(2025, 6, 17, 15, 30, 0),
        )

    async def unblock_key(self, db, auth, key_id, request):  # noqa: ANN001
        assert key_id == "hash_001"
        assert request == UnblockKeyRequest(reason="approved")
        return UnblockKeyData(id="hash_001", status="active")


def install_router_overrides() -> None:
    app.dependency_overrides[get_current_auth_context] = fake_auth_context
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_managed_key_service] = lambda: FakeManagedKeyService()


def test_create_key_route_returns_created_response() -> None:
    install_router_overrides()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/keys",
            json={
                "name": "production-api-key",
                "description": "生产环境 API 调用专用 key",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "success"
    assert body["data"]["id"] == "hash_001"
    assert body["data"]["key"] == "sk-maas-secret"
    assert body["data"]["key_alias"] == "sk...cret"


def test_list_and_detail_routes_do_not_return_raw_key() -> None:
    install_router_overrides()
    client = TestClient(app)

    try:
        list_response = client.get("/api/v1/keys")
        detail_response = client.get("/api/v1/keys/hash_001")
    finally:
        clear_overrides()

    assert list_response.status_code == 200
    list_item = list_response.json()["data"]["items"][0]
    assert "key" not in list_item
    assert list_item["key_alias"] == "sk...cret"

    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert "key" not in detail
    assert detail["id"] == "hash_001"


def test_revoke_and_unblock_routes_return_status_updates() -> None:
    install_router_overrides()
    client = TestClient(app)

    try:
        revoke_response = client.patch(
            "/api/v1/keys/hash_001/revoke",
            json={"reason": "rotate"},
        )
        unblock_response = client.patch(
            "/api/v1/keys/hash_001/unblock",
            json={"reason": "approved"},
        )
    finally:
        clear_overrides()

    assert revoke_response.status_code == 200
    assert revoke_response.json()["data"]["status"] == "revoked"

    assert unblock_response.status_code == 200
    assert unblock_response.json()["data"] == {
        "id": "hash_001",
        "status": "active",
        "blocked_reason": None,
        "blocked_at": None,
    }


class FakeLiteLLMClient:
    async def generate_key(self, **kwargs):  # noqa: ANN003
        return GeneratedKey(
            key="sk-maas-secret",
            key_hash_id="hash_001",
            key_alias="sk...cret",
        )


class FakeSession:
    def __init__(self) -> None:
        self.added: ManagedKey | None = None

    def add(self, model: ManagedKey) -> None:
        self.added = model

    async def commit(self) -> None:
        pass

    async def refresh(self, model: ManagedKey) -> None:
        model.created_at = datetime(2025, 6, 17, 10, 0, 0)


def test_service_create_key_does_not_store_raw_key() -> None:
    import asyncio

    session = FakeSession()
    service = ManagedKeyService(litellm_client=FakeLiteLLMClient())

    result = asyncio.run(
        service.create_key(
            session,
            auth_context(),
            CreateKeyRequest(
                name="production-api-key",
                description="生产环境 API 调用专用 key",
            ),
        )
    )

    assert result.key == "sk-maas-secret"
    assert session.added is not None
    assert session.added.key_hash_id == "hash_001"
    assert session.added.key_alias == "sk...cret"
    assert not hasattr(session.added, "key")

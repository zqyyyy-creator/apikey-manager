from datetime import datetime
from decimal import Decimal

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.litellm_integration.client import GeneratedKey
from app.main import app
from app.models.managed_key import ManagedKey, ManagedKeyStatus
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
    UsageSummary,
)
from app.services.managed_key_service import ManagedKeyService
from tests.asgi_client import asgi_get, asgi_patch, asgi_post


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


async def fake_managed_key_service() -> "FakeManagedKeyService":
    return FakeManagedKeyService()


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
    app.dependency_overrides[get_managed_key_service] = fake_managed_key_service


def test_create_key_route_returns_created_response() -> None:
    install_router_overrides()

    try:
        response = asgi_post(
            app,
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

    try:
        list_response = asgi_get(app, "/api/v1/keys")
        detail_response = asgi_get(app, "/api/v1/keys/hash_001")
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

    try:
        revoke_response = asgi_patch(
            app,
            "/api/v1/keys/hash_001/revoke",
            json={"reason": "rotate"},
        )
        unblock_response = asgi_patch(
            app,
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


class FakeUsageBillingService:
    pass


class FakeResult:
    def __init__(self, model) -> None:  # noqa: ANN001
        self.model = model

    def scalar_one_or_none(self):  # noqa: ANN201
        return self.model


class FakeSession:
    def __init__(self) -> None:
        self.added: ManagedKey | None = None

    def add(self, model: ManagedKey) -> None:
        self.added = model

    async def commit(self) -> None:
        pass

    async def refresh(self, model: ManagedKey) -> None:
        model.created_at = datetime(2025, 6, 17, 10, 0, 0)


class FakeUnblockSession:
    def __init__(self, managed_key: ManagedKey) -> None:
        self.managed_key = managed_key
        self.commits = 0
        self.refreshes = 0

    async def execute(self, statement):  # noqa: ANN001
        return FakeResult(self.managed_key)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, model: ManagedKey) -> None:
        self.refreshes += 1


class FakeResetSpendClient:
    def __init__(self) -> None:
        self.reset_calls = []
        self.unblock_calls = []

    async def reset_key_spend(self, **kwargs):  # noqa: ANN003
        self.reset_calls.append(kwargs)
        return {"ok": True}

    async def unblock_key(self, **kwargs):  # noqa: ANN003
        self.unblock_calls.append(kwargs)
        return {"ok": True}


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


def test_service_detail_includes_usage_summary() -> None:
    service = ManagedKeyService(
        litellm_client=FakeLiteLLMClient(),
        billing_service=FakeUsageBillingService(),
    )
    managed_key = ManagedKey(
        key_hash_id="hash_001",
        team_id="AI_TEST_12345",
        name="production-api-key",
        description="生产环境 API 调用专用 key",
        key_alias="sk...cret",
        status=ManagedKeyStatus.ACTIVE,
    )
    managed_key.created_at = datetime(2025, 6, 17, 10, 0, 0)
    managed_key.spending_limits = []

    detail = service._to_detail(
        managed_key,
        usage_summary=UsageSummary(
            today_cost=Decimal("0.14"),
            total_cost_7d=Decimal("0.42"),
        ),
    )

    assert detail.usage_summary is not None
    assert detail.usage_summary.today_cost == Decimal("0.14")
    assert detail.usage_summary.total_cost_7d == Decimal("0.42")


def test_service_unblock_resets_spend_before_marking_key_active() -> None:
    import asyncio

    managed_key = ManagedKey(
        key_hash_id="hash_001",
        team_id="AI_TEST_12345",
        key_alias="sk...cret",
        status=ManagedKeyStatus.BLOCKED,
        blocked_reason="Daily spending limit exceeded",
        blocked_at=datetime(2026, 6, 29, 10, 0, 0),
    )
    session = FakeUnblockSession(managed_key)
    client = FakeResetSpendClient()
    service = ManagedKeyService(
        litellm_client=client,
        billing_service=FakeUsageBillingService(),
    )

    result = asyncio.run(
        service.unblock_key(
            session,
            auth_context(),
            "hash_001",
            UnblockKeyRequest(reason="approved"),
        )
    )

    assert client.reset_calls == [
        {
            "key": "hash_001",
            "user_id": "12345",
            "access_token": "token_123",
        }
    ]
    assert client.unblock_calls == []
    assert managed_key.status == ManagedKeyStatus.ACTIVE
    assert managed_key.blocked_reason is None
    assert managed_key.blocked_at is None
    assert session.commits == 1
    assert session.refreshes == 1
    assert result.status == "active"

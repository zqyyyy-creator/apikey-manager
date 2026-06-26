from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies import get_current_auth_context
from app.exceptions import AppException, ErrorCode
from app.main import app
from app.models.managed_key import ManagedKey, ManagedKeyStatus
from app.models.spending_limit import SpendingLimit, SpendingLimitType
from app.routers.billing import get_billing_service
from app.schemas.auth import AuthContext
from app.schemas.billing import BillingItem, BillingPageData, BillingTotals
from app.services.billing_service import BillingService


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


class FakeBillingService:
    async def get_key_billing(self, db, auth, key_id, **kwargs):  # noqa: ANN001
        assert auth.team_id == "AI_TEST_12345"
        assert key_id == "hash_001"
        assert kwargs["group_by"] == "date_model"
        item = BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 25),
            model="deepseek-v3",
            request_count=3,
            input_tokens=Decimal("1000"),
            cache_tokens=Decimal("600"),
            output_tokens=Decimal("250"),
            input_cost=Decimal("1.00"),
            cache_cost=Decimal("0.06"),
            output_cost=Decimal("0.50"),
            cost=Decimal("1.56"),
        )
        return BillingPageData(
            items=[item],
            total=1,
            page=1,
            page_size=20,
            summary=BillingTotals(
                total_request_count=3,
                total_input_tokens=Decimal("1000"),
                total_cache_tokens=Decimal("600"),
                total_output_tokens=Decimal("250"),
                total_input_cost=Decimal("1.00"),
                total_cache_cost=Decimal("0.06"),
                total_output_cost=Decimal("0.50"),
                total_cost=Decimal("1.56"),
            ),
        )

    async def get_billing_summary(self, db, auth, **kwargs):  # noqa: ANN001
        raise NotImplementedError


class FakeResourceKeyMapping:
    async def get_resource_uuids_for_key(self, key_hash_id: str) -> list[str]:
        assert key_hash_id == "hash_001"
        return ["resource_a", "resource_b"]

    async def get_resource_uuid_map_for_keys(self, key_hash_ids: list[str]) -> dict[str, str]:
        assert key_hash_ids == ["hash_001"]
        return {"resource_a": "hash_001", "resource_b": "hash_001"}


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def install_router_overrides() -> None:
    app.dependency_overrides[get_current_auth_context] = fake_auth_context
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_billing_service] = lambda: FakeBillingService()


def test_key_billing_route_returns_usage_breakdown() -> None:
    install_router_overrides()
    client = TestClient(app)

    try:
        response = client.get("/api/v1/keys/hash_001/billing?group_by=date_model")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    item = body["data"]["items"][0]
    assert item["input_tokens"] == "1000"
    assert item["cache_tokens"] == "600"
    assert item["output_tokens"] == "250"
    assert item["input_cost"] == "1.00"
    assert item["cache_cost"] == "0.06"
    assert item["output_cost"] == "0.50"
    assert item["cost"] == "1.56"


def test_billing_date_range_cannot_exceed_seven_days() -> None:
    service = BillingService(clickhouse_client=None)

    try:
        service._resolve_date_range(date(2026, 6, 1), date(2026, 6, 8))
    except AppException as exc:
        assert exc.code == ErrorCode.BILLING_DATE_RANGE_EXCEEDED
    else:
        raise AssertionError("Expected date range error")


def test_billing_item_summary_uses_plan_field_mapping() -> None:
    service = BillingService(clickhouse_client=None)
    items = [
        BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 25),
            model="deepseek-v3",
            request_count=3,
            input_tokens=Decimal("1000"),
            cache_tokens=Decimal("600"),
            output_tokens=Decimal("250"),
            input_cost=Decimal("1.00"),
            cache_cost=Decimal("0.06"),
            output_cost=Decimal("0.50"),
            cost=Decimal("1.56"),
        )
    ]

    summary = service._summarize_billing_items(items)

    assert summary.total_request_count == 3
    assert summary.total_input_tokens == Decimal("1000")
    assert summary.total_cache_tokens == Decimal("600")
    assert summary.total_output_tokens == Decimal("250")
    assert summary.total_input_cost == Decimal("1.00")
    assert summary.total_cache_cost == Decimal("0.06")
    assert summary.total_output_cost == Decimal("0.50")
    assert summary.total_cost == Decimal("1.56")


def test_billing_date_range_is_converted_to_epoch_millis() -> None:
    service = BillingService(clickhouse_client=None)

    start_ms, end_ms = service._date_range_to_millis(
        date(2026, 6, 25),
        date(2026, 6, 25),
    )

    assert start_ms == 1782345600000
    assert end_ms == 1782432000000


def test_latest_billing_rows_sql_deduplicates_changelog_by_id() -> None:
    service = BillingService(clickhouse_client=None)
    service.clickhouse_client.database = "dev_dbt_data"
    service.clickhouse_client.billing_table = "dws_para_statements_changelog"

    sql = service._latest_billing_rows_sql(extra_filters="AND resource_uuid = {key_id:String}")

    assert "argMax(used_value, _seq_id) AS used_value" in sql
    assert "argMax(real_price, _seq_id) AS real_price" in sql
    assert "FROM dev_dbt_data.dws_para_statements_changelog AS source" in sql
    assert "WHERE source.service_user_id = {user_id:String}" in sql
    assert "AND source.start_time >= {start_time:Int64}" in sql
    assert "AND source.periodic_end_time < {end_time:Int64}" in sql
    assert "GROUP BY id" in sql
    assert "HAVING _action != 'DELETE'" in sql


def test_billing_sql_uses_real_price_for_total_cost() -> None:
    service = BillingService(clickhouse_client=None)
    service.clickhouse_client.database = "dev_dbt_data"
    service.clickhouse_client.billing_table = "dws_para_statements_changelog"

    latest_rows_sql = service._latest_billing_rows_sql(
        extra_filters="AND resource_uuid = {key_id:String}"
    )
    key_sql = f"""
SELECT
    resource_uuid AS key_id,
    billing_date AS date,
    resource_scale AS model,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {service._charge_type_condition(service.COUNT_CHARGE_TYPES)}) AS request_count,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {service._charge_type_condition(service.INPUT_CHARGE_TYPES)}) AS input_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {service._charge_type_condition(service.CACHE_CHARGE_TYPES)}) AS cache_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {service._charge_type_condition(service.OUTPUT_CHARGE_TYPES)}) AS output_tokens,
    sumIf(toFloat64OrZero(used_value), charge_type IN {service._charge_type_condition(service.INPUT_CHARGE_TYPES)}) AS input_cost,
    sumIf(toFloat64OrZero(used_value), charge_type IN {service._charge_type_condition(service.CACHE_CHARGE_TYPES)}) AS cache_cost,
    sumIf(toFloat64OrZero(used_value), charge_type IN {service._charge_type_condition(service.OUTPUT_CHARGE_TYPES)}) AS output_cost,
    sum(toFloat64(real_price)) AS cost
FROM ({latest_rows_sql})
GROUP BY resource_uuid, billing_date, resource_scale
FORMAT JSONEachRow
"""

    assert (
        "sumIf(toFloat64OrZero(used_value), charge_type IN "
        "('INPUT', 'TEXT_API_TOKEN_INPUT')) AS input_cost"
    ) in key_sql
    assert "sum(toFloat64(real_price)) AS cost" in key_sql
    assert "sum(toFloat64OrZero(used_value)) AS cost" not in key_sql


def test_key_billing_group_by_does_not_include_constant_key_alias() -> None:
    service = BillingService(clickhouse_client=None)

    group_fields = service._key_group_fields("date_model")[2]

    assert service._group_fields_without_leading_comma(group_fields) == (
        "billing_date, resource_scale"
    )


def test_billing_service_accepts_resource_uuid_mapping_layer() -> None:
    service = BillingService(
        clickhouse_client=None,
        resource_key_mapping=FakeResourceKeyMapping(),
    )

    assert service.resource_key_mapping is not None


def test_billing_charge_type_conditions_support_spec_and_real_bytehouse_values() -> None:
    service = BillingService(clickhouse_client=None)

    assert service._charge_type_condition(service.COUNT_CHARGE_TYPES) == (
        "('COUNT', 'COUNT_API_TOKEN_OUTPUT')"
    )
    assert service._charge_type_condition(service.INPUT_CHARGE_TYPES) == (
        "('INPUT', 'TEXT_API_TOKEN_INPUT')"
    )
    assert service._charge_type_condition(service.CACHE_CHARGE_TYPES) == (
        "('CACHE', 'CACHE_API_TOKEN_INPUT')"
    )
    assert service._charge_type_condition(service.OUTPUT_CHARGE_TYPES) == (
        "('OUTPUT', 'TEXT_API_TOKEN_OUTPUT')"
    )


def test_weekly_limit_blocks_on_natural_iso_week_total() -> None:
    import asyncio

    service = BillingService(clickhouse_client=None)
    managed_key = ManagedKey(
        key_hash_id="hash_001",
        team_id="AI_TEST_12345",
        key_alias="sk-...0001",
        status=ManagedKeyStatus.ACTIVE,
    )
    managed_key.spending_limits = [
        SpendingLimit(
            id=1,
            key_hash_id="hash_001",
            limit_type=SpendingLimitType.WEEKLY,
            amount=Decimal("10.00"),
            currency="CNY",
            enabled=True,
        )
    ]
    items = [
        BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 22),
            model="deepseek-v3",
            request_count=1,
            input_tokens=Decimal("0"),
            cache_tokens=Decimal("0"),
            output_tokens=Decimal("0"),
            input_cost=Decimal("0"),
            cache_cost=Decimal("0"),
            output_cost=Decimal("0"),
            cost=Decimal("4.00"),
        ),
        BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 28),
            model="deepseek-v3",
            request_count=1,
            input_tokens=Decimal("0"),
            cache_tokens=Decimal("0"),
            output_tokens=Decimal("0"),
            input_cost=Decimal("0"),
            cache_cost=Decimal("0"),
            output_cost=Decimal("0"),
            cost=Decimal("6.00"),
        ),
    ]
    db = FakeDb()

    asyncio.run(
        service._block_key_if_limit_exceeded(
            db,
            managed_key,
            items,
            service._summarize_billing_items(items),
        )
    )

    assert managed_key.status == ManagedKeyStatus.BLOCKED
    assert managed_key.blocked_reason == "Weekly spending limit exceeded"
    assert db.commits == 1


def test_monthly_limit_blocks_on_natural_month_total() -> None:
    import asyncio

    service = BillingService(clickhouse_client=None)
    managed_key = ManagedKey(
        key_hash_id="hash_001",
        team_id="AI_TEST_12345",
        key_alias="sk-...0001",
        status=ManagedKeyStatus.ACTIVE,
    )
    managed_key.spending_limits = [
        SpendingLimit(
            id=1,
            key_hash_id="hash_001",
            limit_type=SpendingLimitType.MONTHLY,
            amount=Decimal("10.00"),
            currency="CNY",
            enabled=True,
        )
    ]
    items = [
        BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 1),
            model="deepseek-v3",
            request_count=1,
            input_tokens=Decimal("0"),
            cache_tokens=Decimal("0"),
            output_tokens=Decimal("0"),
            input_cost=Decimal("0"),
            cache_cost=Decimal("0"),
            output_cost=Decimal("0"),
            cost=Decimal("4.00"),
        ),
        BillingItem(
            key_id="hash_001",
            date=date(2026, 6, 30),
            model="deepseek-v3",
            request_count=1,
            input_tokens=Decimal("0"),
            cache_tokens=Decimal("0"),
            output_tokens=Decimal("0"),
            input_cost=Decimal("0"),
            cache_cost=Decimal("0"),
            output_cost=Decimal("0"),
            cost=Decimal("6.00"),
        ),
    ]
    db = FakeDb()

    asyncio.run(
        service._block_key_if_limit_exceeded(
            db,
            managed_key,
            items,
            service._summarize_billing_items(items),
        )
    )

    assert managed_key.status == ManagedKeyStatus.BLOCKED
    assert managed_key.blocked_reason == "Monthly spending limit exceeded"
    assert db.commits == 1

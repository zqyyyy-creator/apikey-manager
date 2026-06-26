from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clickhouse import ClickHouseClient, ClickHouseError, get_clickhouse_client
from app.exceptions import AppException, ErrorCode
from app.models.managed_key import ManagedKey, ManagedKeyStatus
from app.models.spending_limit import SpendingLimitType
from app.schemas.auth import AuthContext
from app.schemas.billing import (
    BillingGroupBy,
    BillingItem,
    BillingPageData,
    BillingSummaryGroupBy,
    BillingSummaryItem,
    BillingSummaryPageData,
    BillingTotals,
)
from app.services.resource_key_mapping_service import ResourceKeyMappingService


logger = structlog.get_logger()


class BillingService:
    COUNT_CHARGE_TYPES = ("COUNT", "COUNT_API_TOKEN_OUTPUT")
    INPUT_CHARGE_TYPES = ("INPUT", "TEXT_API_TOKEN_INPUT")
    CACHE_CHARGE_TYPES = ("CACHE", "CACHE_API_TOKEN_INPUT")
    OUTPUT_CHARGE_TYPES = ("OUTPUT", "TEXT_API_TOKEN_OUTPUT")

    def __init__(
        self,
        clickhouse_client: ClickHouseClient | None = None,
        resource_key_mapping: ResourceKeyMappingService | None = None,
    ) -> None:
        self.clickhouse_client = clickhouse_client or get_clickhouse_client()
        self.resource_key_mapping = resource_key_mapping or ResourceKeyMappingService()

    async def get_key_billing(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        *,
        start_date: date | None,
        end_date: date | None,
        group_by: BillingGroupBy,
        page: int,
        page_size: int,
    ) -> BillingPageData:
        start_date, end_date = self._resolve_date_range(start_date, end_date)
        managed_key = await self._get_owned_key(db, auth, key_id, with_limits=True)
        resource_uuids = await self.resource_key_mapping.get_resource_uuids_for_key(
            managed_key.key_hash_id
        )

        rows = await self._query_key_billing_rows(
            auth=auth,
            key_id=managed_key.key_hash_id,
            resource_uuids=resource_uuids,
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
        )
        items = [self._to_billing_item(row) for row in rows]
        summary = self._summarize_billing_items(items)

        await self._block_key_if_limit_exceeded(db, managed_key, items, summary)

        return BillingPageData(
            items=self._paginate(items, page, page_size),
            total=len(items),
            page=max(page, 1),
            page_size=min(max(page_size, 1), 100),
            summary=summary,
        )

    async def get_billing_summary(
        self,
        db: AsyncSession,
        auth: AuthContext,
        *,
        start_date: date | None,
        end_date: date | None,
        group_by: BillingSummaryGroupBy,
        key_id: str | None,
        page: int,
        page_size: int,
    ) -> BillingSummaryPageData:
        start_date, end_date = self._resolve_date_range(start_date, end_date)
        managed_keys = await self._list_owned_keys(db, auth, key_id=key_id)
        if key_id is not None and not managed_keys:
            raise AppException(
                code=ErrorCode.KEY_NOT_FOUND,
                message="Key not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if not managed_keys:
            return BillingSummaryPageData(
                items=[],
                total=0,
                page=max(page, 1),
                page_size=min(max(page_size, 1), 100),
                summary=BillingTotals(),
            )

        key_by_id = {key.key_hash_id: key for key in managed_keys}
        resource_uuid_to_key_id = (
            await self.resource_key_mapping.get_resource_uuid_map_for_keys(list(key_by_id))
        )
        rows = await self._query_summary_rows(
            auth=auth,
            resource_uuids=list(resource_uuid_to_key_id),
            start_date=start_date,
            end_date=end_date,
            group_by=group_by,
        )
        rows = [
            {**row, "key_id": resource_uuid_to_key_id[str(row["key_id"])]}
            for row in rows
            if str(row["key_id"]) in resource_uuid_to_key_id
        ]
        items = [self._to_summary_item(row, key_by_id) for row in rows]

        return BillingSummaryPageData(
            items=self._paginate(items, page, page_size),
            total=len(items),
            page=max(page, 1),
            page_size=min(max(page_size, 1), 100),
            summary=self._summarize_summary_items(items),
        )

    async def _query_key_billing_rows(
        self,
        *,
        auth: AuthContext,
        key_id: str,
        resource_uuids: list[str],
        start_date: date,
        end_date: date,
        group_by: BillingGroupBy,
    ) -> list[dict[str, Any]]:
        if not resource_uuids:
            return []
        date_select, model_select, group_fields = self._key_group_fields(group_by)
        group_by_fields = self._group_fields_without_leading_comma(group_fields)
        resource_uuid_list = ", ".join(
            self._quote_clickhouse_string(resource_uuid)
            for resource_uuid in resource_uuids
        )
        start_time_ms, end_time_ms = self._date_range_to_millis(
            start_date,
            end_date,
        )
        latest_rows_sql = self._latest_billing_rows_sql(
            extra_filters=f"AND source.resource_uuid IN ({resource_uuid_list})",
        )
        count_charge_types = self._charge_type_condition(self.COUNT_CHARGE_TYPES)
        input_charge_types = self._charge_type_condition(self.INPUT_CHARGE_TYPES)
        cache_charge_types = self._charge_type_condition(self.CACHE_CHARGE_TYPES)
        output_charge_types = self._charge_type_condition(self.OUTPUT_CHARGE_TYPES)
        sql = f"""
SELECT
    {self._quote_clickhouse_string(key_id)} AS key_id,
    {date_select} AS date,
    {model_select} AS model,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {count_charge_types}) AS request_count,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {input_charge_types}) AS input_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {cache_charge_types}) AS cache_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {output_charge_types}) AS output_tokens,
    sumIf(toFloat64OrZero(used_value), charge_type IN {input_charge_types}) AS input_cost,
    sumIf(toFloat64OrZero(used_value), charge_type IN {cache_charge_types}) AS cache_cost,
    sumIf(toFloat64OrZero(used_value), charge_type IN {output_charge_types}) AS output_cost,
    sum(toFloat64(real_price)) AS cost
FROM ({latest_rows_sql})
GROUP BY {group_by_fields}
ORDER BY date DESC, cost DESC
FORMAT JSONEachRow
"""
        return await self._run_query(
            sql,
            {
                "user_id": auth.user_id,
                "start_time": start_time_ms,
                "end_time": end_time_ms,
            },
        )

    async def _query_summary_rows(
        self,
        *,
        auth: AuthContext,
        resource_uuids: list[str],
        start_date: date,
        end_date: date,
        group_by: BillingSummaryGroupBy,
    ) -> list[dict[str, Any]]:
        if not resource_uuids:
            return []
        date_select, model_select, group_fields = self._summary_group_fields(group_by)
        resource_uuid_list = ", ".join(
            self._quote_clickhouse_string(resource_uuid)
            for resource_uuid in resource_uuids
        )
        start_time_ms, end_time_ms = self._date_range_to_millis(
            start_date,
            end_date,
        )
        latest_rows_sql = self._latest_billing_rows_sql(
            extra_filters=f"AND source.resource_uuid IN ({resource_uuid_list})",
        )
        count_charge_types = self._charge_type_condition(self.COUNT_CHARGE_TYPES)
        input_charge_types = self._charge_type_condition(self.INPUT_CHARGE_TYPES)
        cache_charge_types = self._charge_type_condition(self.CACHE_CHARGE_TYPES)
        output_charge_types = self._charge_type_condition(self.OUTPUT_CHARGE_TYPES)
        sql = f"""
SELECT
    resource_uuid AS key_id,
    {date_select} AS date,
    {model_select} AS model,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {count_charge_types}) AS total_request_count,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {input_charge_types}) AS total_input_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {cache_charge_types}) AS total_cache_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type IN {output_charge_types}) AS total_output_tokens,
    sumIf(toFloat64OrZero(used_value), charge_type IN {input_charge_types}) AS total_input_cost,
    sumIf(toFloat64OrZero(used_value), charge_type IN {cache_charge_types}) AS total_cache_cost,
    sumIf(toFloat64OrZero(used_value), charge_type IN {output_charge_types}) AS total_output_cost,
    sum(toFloat64(real_price)) AS total_cost
FROM ({latest_rows_sql})
GROUP BY resource_uuid{group_fields}
ORDER BY total_cost DESC
FORMAT JSONEachRow
"""
        return await self._run_query(
            sql,
            {
                "user_id": auth.user_id,
                "start_time": start_time_ms,
                "end_time": end_time_ms,
            },
        )

    def _latest_billing_rows_sql(self, *, extra_filters: str) -> str:
        return f"""
SELECT
    id,
    argMax(_action, _seq_id) AS _action,
    argMax(start_time, _seq_id) AS start_time,
    argMax(periodic_end_time, _seq_id) AS periodic_end_time,
    argMax(resource_uuid, _seq_id) AS resource_uuid,
    argMax(resource_scale, _seq_id) AS resource_scale,
    argMax(charge_type, _seq_id) AS charge_type,
    argMax(service_user_id, _seq_id) AS service_user_id,
    argMax(statement_resource, _seq_id) AS statement_resource,
    argMax(resource_used_count, _seq_id) AS resource_used_count,
    argMax(used_value, _seq_id) AS used_value,
    argMax(real_price, _seq_id) AS real_price,
    argMax(is_backfill, _seq_id) AS is_backfill,
    argMax(billing_date, _seq_id) AS billing_date
FROM {self.clickhouse_client.database}.{self.clickhouse_client.billing_table} AS source
WHERE source.service_user_id = {{user_id:String}}
  AND source.start_time >= {{start_time:Int64}}
  AND source.periodic_end_time < {{end_time:Int64}}
  {extra_filters}
GROUP BY id
HAVING _action != 'DELETE'
   AND statement_resource = 'LLM_USAGE'
   AND is_backfill = 0
"""

    async def _run_query(
        self,
        sql: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            return await self.clickhouse_client.query_json_each_row(sql, params=params)
        except ClickHouseError as exc:
            logger.warning(
                "billing_clickhouse_query_failed",
                error=str(exc),
                sql=sql,
                params=params,
            )
            raise AppException(
                code=ErrorCode.BILLING_SOURCE_UNAVAILABLE,
                message="Billing data source unavailable",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

    async def _get_owned_key(
        self,
        db: AsyncSession,
        auth: AuthContext,
        key_id: str,
        *,
        with_limits: bool = False,
    ) -> ManagedKey:
        statement = select(ManagedKey).where(
            ManagedKey.key_hash_id == key_id,
            ManagedKey.team_id == auth.team_id,
        )
        if with_limits:
            statement = statement.options(selectinload(ManagedKey.spending_limits))
        result = await db.execute(statement)
        managed_key = result.scalar_one_or_none()
        if managed_key is None:
            raise AppException(
                code=ErrorCode.KEY_NOT_FOUND,
                message="Key not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return managed_key

    async def _list_owned_keys(
        self,
        db: AsyncSession,
        auth: AuthContext,
        *,
        key_id: str | None,
    ) -> list[ManagedKey]:
        statement = select(ManagedKey).where(ManagedKey.team_id == auth.team_id)
        if key_id is not None:
            statement = statement.where(ManagedKey.key_hash_id == key_id)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def _block_key_if_limit_exceeded(
        self,
        db: AsyncSession,
        managed_key: ManagedKey,
        items: list[BillingItem],
        summary: BillingTotals,
    ) -> None:
        if managed_key.status != ManagedKeyStatus.ACTIVE:
            return

        daily_costs: dict[date, Decimal] = {}
        weekly_costs: dict[tuple[int, int], Decimal] = {}
        monthly_costs: dict[tuple[int, int], Decimal] = {}
        for item in items:
            if item.date is not None:
                daily_costs[item.date] = daily_costs.get(item.date, Decimal("0")) + item.cost
                iso_year, iso_week, _ = item.date.isocalendar()
                week_key = (iso_year, iso_week)
                weekly_costs[week_key] = weekly_costs.get(week_key, Decimal("0")) + item.cost
                month_key = (item.date.year, item.date.month)
                monthly_costs[month_key] = monthly_costs.get(month_key, Decimal("0")) + item.cost

        for limit in managed_key.spending_limits:
            if not limit.enabled:
                continue
            if limit.limit_type == SpendingLimitType.DAILY and any(
                cost >= limit.amount for cost in daily_costs.values()
            ):
                managed_key.status = ManagedKeyStatus.BLOCKED
                managed_key.blocked_reason = "Daily spending limit exceeded"
                managed_key.blocked_at = datetime.utcnow()
                await db.commit()
                return
            if limit.limit_type == SpendingLimitType.WEEKLY and any(
                cost >= limit.amount for cost in weekly_costs.values()
            ):
                managed_key.status = ManagedKeyStatus.BLOCKED
                managed_key.blocked_reason = "Weekly spending limit exceeded"
                managed_key.blocked_at = datetime.utcnow()
                await db.commit()
                return
            if limit.limit_type == SpendingLimitType.MONTHLY and any(
                cost >= limit.amount for cost in monthly_costs.values()
            ):
                managed_key.status = ManagedKeyStatus.BLOCKED
                managed_key.blocked_reason = "Monthly spending limit exceeded"
                managed_key.blocked_at = datetime.utcnow()
                await db.commit()
                return
            if limit.limit_type == SpendingLimitType.TOTAL and summary.total_cost >= limit.amount:
                managed_key.status = ManagedKeyStatus.BLOCKED
                managed_key.blocked_reason = "Total spending limit exceeded"
                managed_key.blocked_at = datetime.utcnow()
                await db.commit()
                return

    def _resolve_date_range(
        self,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[date, date]:
        resolved_end = end_date or date.today()
        resolved_start = start_date or (resolved_end - timedelta(days=6))
        if resolved_start > resolved_end:
            raise AppException(
                code=ErrorCode.BILLING_DATE_FORMAT_ERROR,
                message="start_date must be earlier than or equal to end_date",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if (resolved_end - resolved_start).days > 6:
            raise AppException(
                code=ErrorCode.BILLING_DATE_RANGE_EXCEEDED,
                message="Billing query date range cannot exceed 7 days",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return resolved_start, resolved_end

    def _date_range_to_millis(self, start_date: date, end_date: date) -> tuple[int, int]:
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        exclusive_end_dt = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        return int(start_dt.timestamp() * 1000), int(
            exclusive_end_dt.timestamp() * 1000
        )

    def _key_group_fields(self, group_by: BillingGroupBy) -> tuple[str, str, str]:
        if group_by == "date":
            return "billing_date", "CAST(NULL, 'Nullable(String)')", ", billing_date"
        if group_by == "model":
            return "CAST(NULL, 'Nullable(Date)')", "resource_scale", ", resource_scale"
        return "billing_date", "resource_scale", ", billing_date, resource_scale"

    def _summary_group_fields(
        self,
        group_by: BillingSummaryGroupBy,
    ) -> tuple[str, str, str]:
        if group_by == "key":
            return "CAST(NULL, 'Nullable(Date)')", "CAST(NULL, 'Nullable(String)')", ""
        if group_by == "key_date":
            return "billing_date", "CAST(NULL, 'Nullable(String)')", ", billing_date"
        return "CAST(NULL, 'Nullable(Date)')", "resource_scale", ", resource_scale"

    def _to_billing_item(self, row: dict[str, Any]) -> BillingItem:
        return BillingItem(
            key_id=str(row["key_id"]),
            date=self._parse_date(row.get("date")),
            model=row.get("model"),
            request_count=int(row["request_count"]),
            input_tokens=self._decimal(row["input_tokens"]),
            cache_tokens=self._decimal(row["cache_tokens"]),
            output_tokens=self._decimal(row["output_tokens"]),
            input_cost=self._decimal(row["input_cost"]),
            cache_cost=self._decimal(row["cache_cost"]),
            output_cost=self._decimal(row["output_cost"]),
            cost=self._decimal(row["cost"]),
        )

    def _to_summary_item(
        self,
        row: dict[str, Any],
        key_by_id: dict[str, ManagedKey],
    ) -> BillingSummaryItem:
        key_id = str(row["key_id"])
        managed_key = key_by_id[key_id]
        return BillingSummaryItem(
            key_id=key_id,
            key_name=managed_key.name,
            key_alias=managed_key.key_alias,
            date=self._parse_date(row.get("date")),
            model=row.get("model"),
            total_request_count=int(row["total_request_count"]),
            total_input_tokens=self._decimal(row["total_input_tokens"]),
            total_cache_tokens=self._decimal(row["total_cache_tokens"]),
            total_output_tokens=self._decimal(row["total_output_tokens"]),
            total_input_cost=self._decimal(row["total_input_cost"]),
            total_cache_cost=self._decimal(row["total_cache_cost"]),
            total_output_cost=self._decimal(row["total_output_cost"]),
            total_cost=self._decimal(row["total_cost"]),
        )

    def _summarize_billing_items(self, items: list[BillingItem]) -> BillingTotals:
        return BillingTotals(
            total_request_count=sum(item.request_count for item in items),
            total_input_tokens=sum((item.input_tokens for item in items), Decimal("0")),
            total_cache_tokens=sum((item.cache_tokens for item in items), Decimal("0")),
            total_output_tokens=sum((item.output_tokens for item in items), Decimal("0")),
            total_input_cost=sum((item.input_cost for item in items), Decimal("0")),
            total_cache_cost=sum((item.cache_cost for item in items), Decimal("0")),
            total_output_cost=sum((item.output_cost for item in items), Decimal("0")),
            total_cost=sum((item.cost for item in items), Decimal("0")),
        )

    def _summarize_summary_items(self, items: list[BillingSummaryItem]) -> BillingTotals:
        return BillingTotals(
            total_request_count=sum(item.total_request_count for item in items),
            total_input_tokens=sum((item.total_input_tokens for item in items), Decimal("0")),
            total_cache_tokens=sum((item.total_cache_tokens for item in items), Decimal("0")),
            total_output_tokens=sum((item.total_output_tokens for item in items), Decimal("0")),
            total_input_cost=sum((item.total_input_cost for item in items), Decimal("0")),
            total_cache_cost=sum((item.total_cache_cost for item in items), Decimal("0")),
            total_output_cost=sum((item.total_output_cost for item in items), Decimal("0")),
            total_cost=sum((item.total_cost for item in items), Decimal("0")),
        )

    def _paginate(self, items: list[Any], page: int, page_size: int) -> list[Any]:
        normalized_page = max(page, 1)
        normalized_page_size = min(max(page_size, 1), 100)
        offset = (normalized_page - 1) * normalized_page_size
        return items[offset : offset + normalized_page_size]

    def _decimal(self, value: Any) -> Decimal:
        return Decimal(str(value))

    def _parse_date(self, value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    def _quote_clickhouse_string(self, value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def _charge_type_condition(self, values: tuple[str, ...]) -> str:
        quoted_values = ", ".join(self._quote_clickhouse_string(value) for value in values)
        return f"({quoted_values})"

    def _group_fields_without_leading_comma(self, group_fields: str) -> str:
        return group_fields[2:] if group_fields.startswith(", ") else group_fields

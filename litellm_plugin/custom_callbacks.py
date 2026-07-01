import asyncio
import json
import logging
import os
from typing import Any

import httpx
from litellm.integrations.custom_logger import CustomLogger


logger = logging.getLogger("maas_custom_logger")


class MaasCustomLogger(CustomLogger):
    """LiteLLM callback that replaces managed-key spend with MaaS cost."""

    def __init__(
        self,
        *,
        maas_api_url: str | None = None,
        internal_api_key: str | None = None,
        timeout: float | None = None,
        budget_sync_enabled: bool | None = None,
        budget_sync_interval_seconds: float | None = None,
        realtime_cost_enabled: bool | None = None,
    ) -> None:
        super().__init__()
        self.maas_api_url = (
            maas_api_url or os.environ.get("MAAS_V2_API_URL") or ""
        ).rstrip("/")
        self.internal_api_key = internal_api_key or os.environ.get(
            "MAAS_V2_INTERNAL_API_KEY",
            os.environ.get("INTERNAL_API_KEY", ""),
        )
        self.timeout = timeout or float(os.environ.get("MAAS_V2_API_TIMEOUT", "3.0"))
        self.budget_sync_enabled = (
            budget_sync_enabled
            if budget_sync_enabled is not None
            else os.environ.get("MAAS_V2_BUDGET_SYNC_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"}
        )
        self.budget_sync_interval_seconds = budget_sync_interval_seconds or float(
            os.environ.get("MAAS_V2_BUDGET_SYNC_INTERVAL_SECONDS", "3600")
        )
        self.realtime_cost_enabled = (
            realtime_cost_enabled
            if realtime_cost_enabled is not None
            else os.environ.get("MAAS_V2_REALTIME_COST_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"}
        )
        self._budget_sync_task: asyncio.Task | None = None
        self._ensure_budget_sync_task()

    async def async_log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        self._ensure_budget_sync_task()

        if not self.maas_api_url or not self.internal_api_key:
            logger.warning("maas_custom_logger_not_configured")
            return

        key_hash_id = self._extract_key_hash_id(kwargs)
        if not key_hash_id:
            logger.warning("maas_custom_logger_skip_missing_key")
            return

        model = self._extract_model(kwargs, response_obj)
        if not self.realtime_cost_enabled:
            await self._skip_realtime_cost_for_managed_key(
                key_hash_id=key_hash_id,
                model=model,
                kwargs=kwargs,
                response_obj=response_obj,
                start_time=start_time,
                end_time=end_time,
            )
            return

        usage = self._extract_usage(response_obj)

        try:
            cost_data = await self._fetch_cost(
                key_hash_id=key_hash_id,
                model=model,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_tokens=usage["cache_tokens"],
            )
        except Exception:
            logger.exception(
                "maas_custom_logger_cost_lookup_failed",
                extra={"key_hash_id": key_hash_id, "model": model},
            )
            return

        if not cost_data.get("managed"):
            logger.warning(
                "maas_custom_logger_non_managed_key",
                extra={"key_hash_id": key_hash_id, "model": model},
            )
            return

        spend_adjustment = self._calculate_spend_adjustment(kwargs, cost_data)
        if spend_adjustment is None:
            return

        try:
            await self._apply_spend_adjustment(
                kwargs=kwargs,
                response_obj=response_obj,
                start_time=start_time,
                end_time=end_time,
                response_cost=spend_adjustment["delta_cost"],
            )
        except Exception:
            logger.exception(
                "maas_custom_logger_spend_sync_failed",
                extra={
                    "key_hash_id": key_hash_id,
                    "model": model,
                    "maas_cost": spend_adjustment["maas_cost"],
                    "default_cost": spend_adjustment["default_cost"],
                    "delta_cost": spend_adjustment["delta_cost"],
                },
            )
            return

        logger.warning(
            "maas_custom_logger_managed_cost_synced",
            extra={
                "key_hash_id": key_hash_id,
                "model": model,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cache_tokens": usage["cache_tokens"],
                "maas_cost": spend_adjustment["maas_cost"],
                "default_cost": spend_adjustment["default_cost"],
                "delta_cost": spend_adjustment["delta_cost"],
                "currency": cost_data.get("currency"),
                "charge_detail": cost_data.get("charge_detail"),
            },
        )

    async def _skip_realtime_cost_for_managed_key(
        self,
        *,
        key_hash_id: str,
        model: str,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        try:
            managed_data = await self._fetch_managed_status(key_hash_id=key_hash_id)
        except Exception:
            logger.exception(
                "maas_custom_logger_managed_lookup_failed",
                extra={"key_hash_id": key_hash_id, "model": model},
            )
            return

        if not managed_data.get("managed"):
            logger.warning(
                "maas_custom_logger_non_managed_key",
                extra={"key_hash_id": key_hash_id, "model": model},
            )
            return

        spend_adjustment = self._calculate_spend_adjustment(kwargs, {"cost": 0})
        if spend_adjustment is None:
            return

        try:
            await self._apply_spend_adjustment(
                kwargs=kwargs,
                response_obj=response_obj,
                start_time=start_time,
                end_time=end_time,
                response_cost=spend_adjustment["delta_cost"],
            )
        except Exception:
            logger.exception(
                "maas_custom_logger_realtime_cost_neutralize_failed",
                extra={
                    "key_hash_id": key_hash_id,
                    "model": model,
                    "default_cost": spend_adjustment["default_cost"],
                    "delta_cost": spend_adjustment["delta_cost"],
                },
            )
            return

        logger.warning(
            "maas_custom_logger_realtime_cost_skipped_for_managed_key",
            extra={
                "key_hash_id": key_hash_id,
                "model": model,
                "default_cost": spend_adjustment["default_cost"],
                "delta_cost": spend_adjustment["delta_cost"],
            },
        )

    async def async_log_failure_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        key_hash_id = self._extract_key_hash_id(kwargs)
        logger.warning(
            "maas_custom_logger_failure_observed",
            extra={"key_hash_id": key_hash_id, "model": kwargs.get("model")},
        )

    def _ensure_budget_sync_task(self) -> None:
        if not self.budget_sync_enabled:
            return
        if not self.maas_api_url or not self.internal_api_key:
            return
        if self._budget_sync_task is not None and not self._budget_sync_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._budget_sync_task = loop.create_task(self._budget_sync_loop())

    async def _budget_sync_loop(self) -> None:
        while True:
            try:
                await self._run_budget_sync_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("maas_budget_sync_failed")
            await asyncio.sleep(self.budget_sync_interval_seconds)

    async def _run_budget_sync_once(self) -> None:
        sync_data = await self._fetch_budget_sync_keys()
        items = sync_data.get("items", [])
        if not isinstance(items, list):
            raise ValueError("MaaS budget sync API returned invalid items")

        synced = 0
        for item in items:
            if isinstance(item, dict) and item.get("key_hash_id"):
                await self._apply_key_budget_sync(item)
                synced += 1

        logger.warning("maas_budget_sync_completed", extra={"synced_keys": synced})

    async def _fetch_budget_sync_keys(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.maas_api_url}/api/v1/internal/budget-sync/keys",
                headers={"x-internal-api-key": self.internal_api_key},
            )
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("MaaS budget sync API returned unexpected response")
        return data

    async def _apply_key_budget_sync(self, item: dict[str, Any]) -> None:
        key_hash_id = str(item["key_hash_id"])
        spend = float(item.get("spend") or 0)
        budget_limits = item.get("budget_limits")
        normalized_budget_limits = self._budget_limits_for_litellm(budget_limits)

        from litellm.proxy.proxy_server import (
            prisma_client,
            spend_counter_cache,
            user_api_key_cache,
        )

        db_data = {
            "spend": spend,
            "max_budget": self._optional_float(item.get("max_budget")),
            "budget_duration": item.get("budget_duration"),
            "budget_limits": (
                json.dumps(normalized_budget_limits)
                if normalized_budget_limits is not None
                else None
            ),
            "blocked": bool(item.get("blocked", False)),
        }
        updated_key = None
        if prisma_client is not None:
            updated_key = await prisma_client.db.litellm_verificationtoken.update(
                where={"token": key_hash_id},
                data=db_data,
            )

        cache_value = updated_key or await user_api_key_cache.async_get_cache(
            key=key_hash_id
        )
        if cache_value is not None:
            self._set_value(cache_value, "spend", spend)
            self._set_value(cache_value, "max_budget", db_data["max_budget"])
            self._set_value(cache_value, "budget_duration", db_data["budget_duration"])
            self._set_value(cache_value, "budget_limits", normalized_budget_limits)
            self._set_value(cache_value, "blocked", db_data["blocked"])
            await user_api_key_cache.async_set_cache(key=key_hash_id, value=cache_value)

        await self._set_spend_counter(
            spend_counter_cache,
            f"spend:key:{key_hash_id}",
            spend,
        )
        if isinstance(budget_limits, list):
            for window in budget_limits:
                if not isinstance(window, dict):
                    continue
                duration = window.get("budget_duration")
                if not duration:
                    continue
                await self._set_spend_counter(
                    spend_counter_cache,
                    f"spend:key:{key_hash_id}:window:{duration}",
                    float(window.get("spend") or 0),
                )

    async def _set_spend_counter(
        self,
        spend_counter_cache: Any,
        counter_key: str,
        spend: float,
    ) -> None:
        spend_counter_cache.in_memory_cache.set_cache(key=counter_key, value=spend)
        if spend_counter_cache.redis_cache is not None:
            await spend_counter_cache.redis_cache.async_set_cache(
                key=counter_key,
                value=spend,
            )

    def _budget_limits_for_litellm(
        self,
        budget_limits: Any,
    ) -> list[dict[str, Any]] | None:
        if not isinstance(budget_limits, list):
            return None

        normalized = []
        for window in budget_limits:
            if not isinstance(window, dict):
                continue
            duration = window.get("budget_duration")
            max_budget = self._optional_float(window.get("max_budget"))
            if not duration or max_budget is None:
                continue
            normalized.append(
                {
                    "budget_duration": str(duration),
                    "max_budget": max_budget,
                }
            )
        return normalized or None

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _fetch_cost(
        self,
        *,
        key_hash_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.maas_api_url}/api/v1/internal/keys/{key_hash_id}/cost",
                params={
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_tokens": cache_tokens,
                },
                headers={"x-internal-api-key": self.internal_api_key},
            )
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("MaaS cost API returned unexpected response")
        return data

    async def _fetch_managed_status(
        self,
        *,
        key_hash_id: str,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.maas_api_url}/api/v1/internal/keys/{key_hash_id}/managed",
                headers={"x-internal-api-key": self.internal_api_key},
            )
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("MaaS managed API returned unexpected response")
        return data

    def _calculate_spend_adjustment(
        self, kwargs: dict[str, Any], cost_data: dict[str, Any]
    ) -> dict[str, float] | None:
        if kwargs.get("_maas_spend_adjusted") is True:
            logger.warning("maas_custom_logger_spend_already_adjusted")
            return None

        maas_cost = self._get_float(cost_data, "cost")
        default_cost = self._extract_default_response_cost(kwargs)
        if maas_cost is None or default_cost is None:
            logger.warning(
                "maas_custom_logger_skip_missing_cost",
                extra={"maas_cost": maas_cost, "default_cost": default_cost},
            )
            return None

        delta_cost = maas_cost - default_cost
        kwargs["_maas_spend_adjusted"] = True
        self._set_value(kwargs, "response_cost", maas_cost)
        standard_logging_object = kwargs.get("standard_logging_object")
        if standard_logging_object is not None:
            self._set_value(standard_logging_object, "response_cost", maas_cost)
        return {
            "maas_cost": maas_cost,
            "default_cost": default_cost,
            "delta_cost": delta_cost,
        }

    def _extract_default_response_cost(self, kwargs: dict[str, Any]) -> float | None:
        standard_logging_object = kwargs.get("standard_logging_object")
        default_cost = self._get_float(standard_logging_object, "response_cost")
        if default_cost is not None:
            return default_cost
        return self._get_float(kwargs, "response_cost")

    async def _apply_spend_adjustment(
        self,
        *,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: Any,
        end_time: Any,
        response_cost: float,
    ) -> None:
        if response_cost == 0:
            return

        from litellm.litellm_core_utils.core_helpers import (
            _get_parent_otel_span_from_kwargs,
            get_litellm_metadata_from_kwargs,
        )
        from litellm.proxy.hooks.proxy_track_cost_callback import (
            _get_request_tags_for_cost_tracking,
        )
        from litellm.proxy.proxy_server import (
            increment_spend_counters,
            proxy_logging_obj,
            update_cache,
        )
        from litellm.utils import get_end_user_id_for_cost_tracking

        litellm_params = kwargs.get("litellm_params", {}) or {}
        metadata = get_litellm_metadata_from_kwargs(kwargs=kwargs)
        user_api_key = metadata.get("user_api_key")
        if not user_api_key:
            logger.warning("maas_custom_logger_skip_missing_litellm_token")
            return

        user_id = metadata.get("user_api_key_user_id")
        team_id = metadata.get("user_api_key_team_id")
        org_id = metadata.get("user_api_key_org_id")
        end_user_id = get_end_user_id_for_cost_tracking(litellm_params)
        standard_logging_object = kwargs.get("standard_logging_object")
        request_tags = _get_request_tags_for_cost_tracking(
            sl_object=standard_logging_object,
            metadata=metadata,
        )

        await proxy_logging_obj.db_spend_update_writer.update_database(
            token=user_api_key,
            response_cost=response_cost,
            user_id=user_id,
            end_user_id=end_user_id,
            team_id=team_id,
            kwargs=kwargs,
            completion_response=response_obj,
            start_time=start_time,
            end_time=end_time,
            org_id=org_id,
        )
        await increment_spend_counters(
            token=user_api_key,
            team_id=team_id,
            user_id=user_id,
            response_cost=response_cost,
            org_id=org_id,
            budget_reservation=None,
            end_user_id=end_user_id,
            tags=request_tags,
        )
        asyncio.create_task(
            update_cache(
                token=user_api_key,
                user_id=user_id,
                end_user_id=end_user_id,
                response_cost=response_cost,
                team_id=team_id,
                parent_otel_span=_get_parent_otel_span_from_kwargs(kwargs=kwargs),
                tags=request_tags,
            )
        )

    def _extract_key_hash_id(self, kwargs: dict[str, Any]) -> str | None:
        explicit_key_hash_id = self._extract_explicit_key_hash_id(kwargs)
        if explicit_key_hash_id:
            return explicit_key_hash_id

        user_api_key_dict = kwargs.get("user_api_key_dict")
        for field in ("token", "key", "api_key", "key_hash_id"):
            value = self._get_value(user_api_key_dict, field)
            if value:
                return str(value)

        metadata = kwargs.get("metadata")
        for field in ("user_api_key_hash", "key_hash_id", "token"):
            value = self._get_value(metadata, field)
            if value:
                return str(value)

        litellm_params = kwargs.get("litellm_params")
        litellm_metadata = self._get_value(litellm_params, "metadata")
        for field in ("user_api_key_hash", "key_hash_id", "token"):
            value = self._get_value(litellm_metadata, field)
            if value:
                return str(value)

        standard_logging_object = kwargs.get("standard_logging_object")
        standard_metadata = self._get_value(standard_logging_object, "metadata")
        for field in ("user_api_key_hash", "key_hash_id", "token"):
            value = self._get_value(standard_metadata, field)
            if value:
                return str(value)

        return None

    def _extract_explicit_key_hash_id(self, kwargs: dict[str, Any]) -> str | None:
        metadata_sources = [
            kwargs.get("metadata"),
            self._get_value(kwargs.get("litellm_params"), "metadata"),
            self._get_value(kwargs.get("standard_logging_object"), "metadata"),
        ]
        for metadata in metadata_sources:
            value = self._get_value(metadata, "key_hash_id")
            if value:
                return str(value)
        return None

    def _extract_model(self, kwargs: dict[str, Any], response_obj: Any) -> str:
        model = kwargs.get("model") or self._get_value(response_obj, "model")
        return str(model or "unknown")

    def _extract_usage(self, response_obj: Any) -> dict[str, int]:
        usage = self._get_value(response_obj, "usage")
        input_tokens = self._get_int(usage, "prompt_tokens")
        output_tokens = self._get_int(usage, "completion_tokens")
        cache_tokens = self._extract_cache_tokens(usage)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_tokens": cache_tokens,
        }

    def _extract_cache_tokens(self, usage: Any) -> int:
        prompt_tokens_details = self._get_value(usage, "prompt_tokens_details")
        cache_tokens = self._get_int(prompt_tokens_details, "cached_tokens")
        if cache_tokens:
            return cache_tokens
        return self._get_int(usage, "cache_read_input_tokens")

    def _get_int(self, value: Any, field: str) -> int:
        raw_value = self._get_value(value, field)
        if raw_value is None:
            return 0
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return 0

    def _get_float(self, value: Any, field: str) -> float | None:
        raw_value = self._get_value(value, field)
        if raw_value is None:
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    def _get_value(self, value: Any, field: str) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(field)
        return getattr(value, field, None)

    def _set_value(self, value: Any, field: str, new_value: Any) -> None:
        if isinstance(value, dict):
            value[field] = new_value
            return
        setattr(value, field, new_value)


maas_custom_logger = MaasCustomLogger()
proxy_handler_instance = maas_custom_logger

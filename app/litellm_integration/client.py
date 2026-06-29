from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings


class LagProxyError(Exception):
    pass


class GeneratedKey(BaseModel):
    key: str = Field(description="Raw key returned once by LiteLLM.")
    key_hash_id: str
    key_alias: str


class LiteLLMClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.lag_proxy_url).rstrip("/")
        self.timeout = timeout or settings.lag_proxy_timeout
        self._http_client = http_client

    async def generate_key(
        self,
        *,
        team_id: str,
        user_id: str,
        access_token: str,
        name: str | None = None,
        description: str | None = None,
        max_budget: Decimal | None = None,
        budget_duration: str | None = None,
    ) -> GeneratedKey:
        payload: dict[str, Any] = {
            "team_id": team_id,
        }
        if name is not None:
            payload["key_alias"] = name
        if description is not None:
            payload["metadata"] = {"description": description}
        if max_budget is not None:
            payload["max_budget"] = str(max_budget)
        if budget_duration is not None:
            payload["budget_duration"] = budget_duration

        data = await self._post(
            "/key/generate",
            payload,
            user_id=user_id,
            access_token=access_token,
        )
        return self._parse_generated_key(data)

    async def update_key(
        self,
        *,
        key: str,
        user_id: str,
        access_token: str,
        max_budget: Decimal | None = None,
        clear_max_budget: bool = False,
        spend: Decimal | None = None,
        budget_duration: str | None = None,
        clear_budget_duration: bool = False,
        budget_limits: list[dict[str, Any]] | None = None,
        blocked: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": key,
        }
        if clear_max_budget:
            payload["max_budget"] = None
        elif max_budget is not None:
            payload["max_budget"] = str(max_budget)
        if spend is not None:
            payload["spend"] = str(spend)
        if clear_budget_duration:
            payload["budget_duration"] = None
        elif budget_duration is not None:
            payload["budget_duration"] = budget_duration
        if budget_limits is not None:
            payload["budget_limits"] = budget_limits
        if blocked is not None:
            payload["blocked"] = blocked
        if metadata is not None:
            payload["metadata"] = metadata

        return await self._post(
            "/key/update",
            payload,
            user_id=user_id,
            access_token=access_token,
        )

    async def block_key(
        self,
        *,
        key: str,
        user_id: str,
        access_token: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": key}
        if reason is not None:
            payload["reason"] = reason
        return await self._post(
            "/key/block",
            payload,
            user_id=user_id,
            access_token=access_token,
        )

    async def unblock_key(
        self,
        *,
        key: str,
        user_id: str,
        access_token: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": key}
        if reason is not None:
            payload["reason"] = reason
        return await self._post(
            "/key/unblock",
            payload,
            user_id=user_id,
            access_token=access_token,
        )

    async def reset_key_spend(
        self,
        *,
        key: str,
        user_id: str,
        access_token: str,
        reset_to: Decimal = Decimal("0"),
    ) -> dict[str, Any]:
        return await self._post(
            f"/key/{quote(key, safe='')}/reset_spend",
            {"reset_to": str(reset_to)},
            user_id=user_id,
            access_token=access_token,
        )

    async def get_key_info(
        self,
        *,
        key: str,
        user_id: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._get(
            "/key/info",
            params={"key": key},
            user_id=user_id,
            access_token=access_token,
        )

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        user_id: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            path,
            user_id=user_id,
            access_token=access_token,
            json=payload,
        )

    async def _get(
        self,
        path: str,
        *,
        user_id: str,
        access_token: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            path,
            user_id=user_id,
            access_token=access_token,
            params=params,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_id: str,
        access_token: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = {
            "x-user-id": user_id,
            "Authorization": f"Bearer {access_token}",
        }
        try:
            response = await self._send_request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LagProxyError("lag-proxy request failed") from exc
        except ValueError as exc:
            raise LagProxyError("lag-proxy returned invalid JSON") from exc

        if isinstance(data, dict):
            return data
        raise LagProxyError("lag-proxy returned unexpected response")

    async def _send_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(method, url, **kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.request(method, url, **kwargs)

    def _parse_generated_key(self, data: dict[str, Any]) -> GeneratedKey:
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        key = payload.get("key")
        key_hash_id = payload.get("key_hash_id") or payload.get("token_id")
        key_alias = payload.get("key_alias")

        if not key or not key_hash_id or not key_alias:
            raise LagProxyError("lag-proxy key generation response is incomplete")

        return GeneratedKey(
            key=key,
            key_hash_id=key_hash_id,
            key_alias=key_alias,
        )

from decimal import Decimal
from typing import Any

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

        data = await self._post("/key/generate", payload, user_id=user_id)
        return self._parse_generated_key(data)

    async def update_key(
        self,
        *,
        key: str,
        user_id: str,
        max_budget: Decimal | None = None,
        spend: Decimal | None = None,
        budget_duration: str | None = None,
        blocked: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": key,
        }
        if max_budget is not None:
            payload["max_budget"] = str(max_budget)
        if spend is not None:
            payload["spend"] = str(spend)
        if budget_duration is not None:
            payload["budget_duration"] = budget_duration
        if blocked is not None:
            payload["blocked"] = blocked
        if metadata is not None:
            payload["metadata"] = metadata

        return await self._post("/key/update", payload, user_id=user_id)

    async def block_key(
        self,
        *,
        key: str,
        user_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": key}
        if reason is not None:
            payload["reason"] = reason
        return await self._post("/key/block", payload, user_id=user_id)

    async def unblock_key(
        self,
        *,
        key: str,
        user_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"key": key}
        if reason is not None:
            payload["reason"] = reason
        return await self._post("/key/unblock", payload, user_id=user_id)

    async def get_key_info(
        self,
        *,
        key: str,
        user_id: str,
    ) -> dict[str, Any]:
        return await self._get(
            "/key/info",
            params={"key": key},
            user_id=user_id,
        )

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            path,
            user_id=user_id,
            json=payload,
        )

    async def _get(
        self,
        path: str,
        *,
        user_id: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            path,
            user_id=user_id,
            params=params,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = await self._send_request(
                method,
                f"{self.base_url}{path}",
                headers={"x-user-id": user_id},
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

import time
from collections import OrderedDict
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.client_user_mapping import ClientUserMapping
from app.schemas.auth import AuthContext


class AuthTokenError(Exception):
    pass


class AuthPermissionError(Exception):
    pass


class AuthServiceUnavailableError(Exception):
    pass


class AuthService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._token_cache: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()

    def _get_cached_introspection(self, token: str) -> dict[str, Any] | None:
        cached = self._token_cache.get(token)
        if cached is None:
            return None

        data, expire_at = cached
        if expire_at <= time.time():
            self._token_cache.pop(token, None)
            return None

        self._token_cache.move_to_end(token)
        return data

    def _cache_introspection(self, token: str, data: dict[str, Any]) -> None:
        now = time.time()
        exp = data.get("exp")
        ttl = self.settings.oauth2_token_cache_default_ttl

        if isinstance(exp, int | float):
            ttl = min(ttl, max(0, int(exp - now - 10)))

        if ttl <= 0:
            return

        self._token_cache[token] = (data, now + ttl)
        self._token_cache.move_to_end(token)

        while len(self._token_cache) > self.settings.oauth2_token_cache_max:
            self._token_cache.popitem(last=False)

    async def introspect_token(self, token: str) -> dict[str, Any]:
        cached = self._get_cached_introspection(token)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.oauth2_introspect_timeout
            ) as client:
                response = await client.post(
                    self.settings.oauth2_introspect_url,
                    data={
                        "token": token,
                        "client_id": self.settings.default_client_id,
                    },
                )
                response.raise_for_status()
                data = response.json()
                self._cache_introspection(token, data)
                return data
        except httpx.HTTPError as exc:
            raise AuthServiceUnavailableError("Auth center is unavailable") from exc

    async def get_client_id(self, token: str) -> str:
        data = await self.introspect_token(token)

        if not data.get("active"):
            raise AuthTokenError("Token is not active")

        client_id = data.get("client_id")
        if not client_id:
            raise AuthTokenError("Missing client id")

        return client_id

    async def get_user_id_by_client_id(
        self,
        db: AsyncSession,
        client_id: str,
    ) -> str | None:
        result = await db.execute(
            select(ClientUserMapping.user_id).where(
                ClientUserMapping.client_id == client_id
            )
        )
        return result.scalar_one_or_none()

    def build_team_id(self, user_id: str) -> str:
        return f"{self.settings.team_id_prefix}_{user_id}"

    async def authenticate(
        self,
        db: AsyncSession,
        token: str,
        x_user_id: str,
    ) -> AuthContext:
        client_id = await self.get_client_id(token)
        mapped_user_id = await self.get_user_id_by_client_id(db, client_id)

        if mapped_user_id is None:
            raise AuthPermissionError("Client is not mapped to a user")

        if mapped_user_id != x_user_id:
            raise AuthPermissionError("x-user-id does not match token client mapping")

        return AuthContext(
            client_id=client_id,
            user_id=mapped_user_id,
            team_id=self.build_team_id(mapped_user_id),
            access_token=token,
        )

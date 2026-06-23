from typing import Annotated

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.auth import AuthContext
from app.services.auth_service import (
    AuthPermissionError,
    AuthService,
    AuthServiceUnavailableError,
    AuthTokenError,
)


bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="OAuth2 access token using the Bearer scheme.",
    auto_error=False,
)


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()


async def get_bearer_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> str | None:
    if credentials is None:
        return None
    return credentials.credentials


async def get_x_user_id(
    x_user_id: Annotated[
        str,
        Header(
            alias="x-user-id",
            description="Business user ID mapped from the OAuth2 client_id.",
        ),
    ],
) -> str:
    return x_user_id


async def get_current_auth_context(
    token: Annotated[str | None, Depends(get_bearer_token)],
    x_user_id: Annotated[str, Depends(get_x_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthContext:
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return await auth_service.authenticate(db, token, x_user_id)
    except AuthTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except AuthServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

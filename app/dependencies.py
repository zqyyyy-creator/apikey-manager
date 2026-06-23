from typing import Annotated

from fastapi import Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="OAuth2 access token using the Bearer scheme.",
    auto_error=False,
)


async def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, bearer_scheme],
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

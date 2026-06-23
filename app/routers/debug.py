from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_current_auth_context
from app.schemas.auth import AuthContext

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get("/auth")
async def debug_auth(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> AuthContext:
    return auth

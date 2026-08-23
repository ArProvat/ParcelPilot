"""Authentication endpoints."""
from fastapi import APIRouter, Depends

from app.schemas.api import MockLoginRequest, TokenResponse
from app.schemas.auth import UserContext
from app.security.auth import get_current_user


router = APIRouter()


@router.post("/mock-login", response_model=TokenResponse)
async def mock_login(request: MockLoginRequest):
    token_map = {
        "northstar": "mock-northstar",
        "lumenworks": "mock-lumenworks",
        "admin": "mock-admin",
    }
    return TokenResponse(access_token=token_map[request.user])


@router.get("/me")
async def me(user: UserContext = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "role": user.role,
        "account_id": user.account_id,
        "permissions": sorted(user.permissions),
    }

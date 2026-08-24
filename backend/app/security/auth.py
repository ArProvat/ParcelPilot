"""FastAPI authentication dependency for mocked or signed JWT identity."""
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.schemas.auth import UserContext


bearer_scheme = HTTPBearer(auto_error=False)

MOCK_USERS: dict[str, UserContext] = {
    "mock-northstar": UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read", "documents:read", "escalations:create"}),
    ),
    "mock-northstar-revoked": UserContext(
        user_id="USR-NORTHSTAR-1",
        role="customer",
        account_id="ACCT-001",
        permissions=frozenset({"orders:read", "tickets:read", "documents:read"}),  # escalations:create REVOKED
    ),
    "mock-lumenworks": UserContext(
        user_id="USR-LUMENWORKS-1",
        role="customer",
        account_id="ACCT-002",
        permissions=frozenset({"orders:read", "tickets:read", "documents:read", "escalations:create"}),
    ),
    "mock-admin": UserContext(
        user_id="USR-ADMIN-1",
        role="operations_admin",
        account_id=None,
        permissions=frozenset({"*"}),
    ),
}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = credentials.credentials
    if token in MOCK_USERS:
        return MOCK_USERS[token]

    claims = _decode_jwt(token)
    return _context_from_claims(claims)


def _decode_jwt(token: str) -> dict[str, Any]:
    try:
        from jose import jwt

        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token") from exc


def _context_from_claims(claims: dict[str, Any]) -> UserContext:
    try:
        user_id = claims["sub"]
        role = claims["role"]
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing identity claims") from exc

    return UserContext(
        user_id=user_id,
        role=role,
        account_id=claims.get("account_id"),
        permissions=frozenset(claims.get("permissions", [])),
        authorized_account_ids=frozenset(claims.get("authorized_account_ids", [])),
    )

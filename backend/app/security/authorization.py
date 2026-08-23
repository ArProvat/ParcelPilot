"""Authorization checks shared by repositories, tools, and retrieval."""
from app.schemas.auth import UserContext


class AuthorizationError(PermissionError):
    """Raised when an authenticated user lacks required access."""


def require_permission(user: UserContext, permission: str) -> None:
    if not user.has_permission(permission):
        raise AuthorizationError(f"Missing required permission: {permission}")


def accessible_account_ids(user: UserContext) -> frozenset[str] | None:
    """Return allowed account ids, or None for all-account access."""
    if user.role == "operations_admin" or "accounts:*" in user.permissions:
        return None

    if user.role == "support_agent":
        return user.authorized_account_ids

    if user.account_id is None:
        return frozenset()

    return frozenset({user.account_id})


def can_access_account(user: UserContext, account_id: str) -> bool:
    allowed = accessible_account_ids(user)
    return allowed is None or account_id in allowed

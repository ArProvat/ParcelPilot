"""Authenticated caller context used by data and retrieval layers."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserContext:
    user_id: str
    role: str
    account_id: str | None
    permissions: frozenset[str] = field(default_factory=frozenset)
    authorized_account_ids: frozenset[str] = field(default_factory=frozenset)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions or "*" in self.permissions

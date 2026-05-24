"""In-memory password-reset token store. No real crypto."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .login import User, UserStore


# token -> user_id
_TOKENS: dict[str, int] = {}


def issue_reset_token(user: "User") -> str:
    token = secrets.token_urlsafe(16)
    _TOKENS[token] = user.id
    return token


def verify_reset_token(store: "UserStore", token: str) -> "User | None":
    user_id = _TOKENS.get(token)
    if user_id is None:
        return None
    for user in store._users.values():
        if user.id == user_id:
            return user
    return None


def clear_all_tokens() -> None:
    """Test helper. Real apps would expire tokens by timestamp."""
    _TOKENS.clear()

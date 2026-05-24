"""Pretend login + reset-password endpoints. In-memory, no real services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .password_reset import issue_reset_token, verify_reset_token


@dataclass
class User:
    id: int
    email: str
    password: str  # toy in-memory store

    def check_password(self, candidate: str) -> bool:
        # Toy comparison. Real apps must use a constant-time hash check.
        return candidate == self.password


@dataclass
class UserStore:
    """In-memory user store. Pure stdlib, no DB."""

    _users: dict[str, User] = field(default_factory=dict)
    _next_id: int = 1

    def create(self, email: str, password: str) -> User:
        u = User(id=self._next_id, email=email, password=password)
        self._users[email] = u
        self._next_id += 1
        return u

    def get_by_email(self, email: str) -> User | None:
        return self._users.get(email)


def login(store: UserStore, email: str, password: str) -> dict[str, Any]:
    """Return a fake session dict, or an error dict."""
    user = store.get_by_email(email)
    if not user or not user.check_password(password):
        return {"status": 401, "error": "invalid_credentials"}
    return {"status": 200, "session": f"session-for-{user.id}"}


def request_reset(store: UserStore, email: str) -> dict[str, Any]:
    """Issue a reset token if the user exists. Always returns 200 to avoid
    leaking which addresses are registered."""
    user = store.get_by_email(email)
    if user is None:
        return {"status": 200, "ok": True}
    token = issue_reset_token(user)
    # In a real app this would be emailed. For the demo we return it.
    return {"status": 200, "ok": True, "token": token}


def reset_password(store: UserStore, token: str, new_password: str) -> dict[str, Any]:
    """Accept a new password. Currently performs *no* strength check —
    that's exactly the gap the demo task asks AgentForge to close."""
    user = verify_reset_token(store, token)
    if user is None:
        return {"status": 400, "error": "invalid_token"}
    # TODO: this is the line the demo task is about. Add validation here.
    user.password = new_password
    return {"status": 200, "ok": True}

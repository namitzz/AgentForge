"""Reusable input validators.

Note: there is no password-strength validator here yet. That is exactly
the gap the AgentForge demo task ("Add password reset validation to the
login flow") asks the agents to close.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    if not value:
        return False
    return bool(_EMAIL_RE.match(value))

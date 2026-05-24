"""Stdlib-only tests for the demo app.

Run from inside demo-projects/tiny-python-app:
  python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Make `import src.*` work when running unittest from the demo dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.auth.login import UserStore, login, request_reset, reset_password
from src.auth.password_reset import clear_all_tokens
from src.utils.validators import is_valid_email


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_all_tokens()
        self.store = UserStore()
        self.store.create(email="jo@example.com", password="correct-horse-9")

    # --- login ----------------------------------------------------------
    def test_login_succeeds_with_correct_credentials(self) -> None:
        result = login(self.store, "jo@example.com", "correct-horse-9")
        self.assertEqual(result["status"], 200)
        self.assertIn("session", result)

    def test_login_fails_with_wrong_password(self) -> None:
        result = login(self.store, "jo@example.com", "nope")
        self.assertEqual(result["status"], 401)

    def test_login_fails_for_unknown_user(self) -> None:
        result = login(self.store, "ghost@example.com", "anything")
        self.assertEqual(result["status"], 401)

    # --- reset flow -----------------------------------------------------
    def test_request_reset_for_known_user_returns_token(self) -> None:
        result = request_reset(self.store, "jo@example.com")
        self.assertEqual(result["status"], 200)
        self.assertIn("token", result)

    def test_request_reset_for_unknown_user_does_not_leak(self) -> None:
        result = request_reset(self.store, "ghost@example.com")
        self.assertEqual(result["status"], 200)
        self.assertNotIn("token", result)

    def test_reset_password_with_valid_token_changes_password(self) -> None:
        token = request_reset(self.store, "jo@example.com")["token"]
        result = reset_password(self.store, token, "hunter2-new-1234")
        self.assertEqual(result["status"], 200)
        # The new password works for login.
        self.assertEqual(
            login(self.store, "jo@example.com", "hunter2-new-1234")["status"],
            200,
        )

    def test_reset_password_with_bad_token_rejected(self) -> None:
        result = reset_password(self.store, "not-a-token", "anything-123")
        self.assertEqual(result["status"], 400)


class ValidatorTests(unittest.TestCase):
    def test_valid_email(self) -> None:
        self.assertTrue(is_valid_email("a@b.co"))

    def test_invalid_email(self) -> None:
        self.assertFalse(is_valid_email("not-an-email"))
        self.assertFalse(is_valid_email(""))


if __name__ == "__main__":
    unittest.main()

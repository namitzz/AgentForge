## Task understanding
Harden the password-reset endpoint inside the login flow so that any new password chosen by the user passes the same strength rules already enforced at signup. Today the reset endpoint accepts any non-empty string, which lets a returning user replace a strong password with something trivial.

## Relevant files
- `src/auth/login.py` — handles the `/reset-password` endpoint; currently writes the new password straight to the user record.
- `src/auth/password_reset.py` — verifies reset tokens; no validation of the new password.
- `src/utils/validators.py` — contains the password rules used at signup. We will reuse this rather than duplicate.
- `tests/test_auth.py` — extend with three new reset cases.

## Risks
- **medium** — a regression here could lock users out of resetting their password. Mitigate with explicit test cases for valid + invalid passwords.
- **low** — rate limiting on reset attempts is out of scope; flag as a follow-up issue.

## Implementation steps
1. Extract the signup strength check into a reusable `validate_password_strength(password) -> (bool, str)` in `validators.py`.
2. Call it from the reset endpoint in `login.py`. On failure, return 400 with the validator's reason.
3. Log rejected attempts with the user id and reason category (no password content in logs).
4. Add three test cases to `tests/test_auth.py`: valid password accepted, too-short password rejected, missing-digit password rejected.

## Test strategy
Extend `tests/test_auth.py` using the existing test client fixture. Run with `pytest tests/test_auth.py -v`. CI test command (`pytest`) covers the whole suite.

## Reviewer needed?
Yes — the change is on the authentication boundary. Diff-only review is sufficient.

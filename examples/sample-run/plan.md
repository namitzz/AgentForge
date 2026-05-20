## Task understanding
Add HMAC signature verification to the Stripe webhook handler so that requests with a missing or invalid `Stripe-Signature` header are rejected before any state is changed.

## Relevant files
- `billing/webhooks.py` — current handler, accepts the request body without verification.
- `billing/config.py` — already reads other Stripe secrets; add `STRIPE_WEBHOOK_SECRET` here.
- `tests/test_webhooks.py` — needs new cases for valid, invalid, and missing signatures.

## Risks
- **medium** — A bug in verification could reject all legitimate webhooks. Mitigate with explicit tests against Stripe's documented tolerance window.
- **low** — Replay protection isn't in scope here; flag for a follow-up issue.

## Implementation steps
1. Add `STRIPE_WEBHOOK_SECRET` to `billing/config.py` with a clear error if missing.
2. In `billing/webhooks.py`, read the raw request body before parsing JSON.
3. Compute `hmac.new(secret, body, sha256)` and compare against the `Stripe-Signature` header's `v1=` value using `hmac.compare_digest`.
4. Reject with 400 on missing header, 401 on mismatch.
5. Log rejected requests with request ID but no body content.

## Test strategy
- Extend `tests/test_webhooks.py` with three cases: valid signature, invalid signature, missing header.
- Reuse the existing fake Stripe payload fixture; sign it with a known test secret.
- Run `pytest tests/test_webhooks.py -v`.

## Reviewer needed?
Yes — touches authentication boundary and request rejection logic. Diff-only review is sufficient.

# tiny-python-app

A minimal pretend web-app used as a target for AgentForge demos. **No real secrets, no real services, no external dependencies.** Pure Python stdlib.

## Layout

```
src/
  auth/
    login.py            # login + reset-password handlers (in-memory)
    password_reset.py   # token issuance + verification (in-memory)
  utils/
    validators.py       # email validator (no password rules yet — that's the demo task)
tests/
  test_auth.py          # a handful of trivial tests
```

## Demo task

The default demo asks AgentForge to harden the reset endpoint:

> *Add password reset validation to the login flow*

This task intentionally lands as **HIGH** risk in the local risk engine (it mentions `password` + `login`), and the selected files include paths under `src/auth/` (which the policy engine treats as sensitive). Use it to see the full pipeline — classifier, policy, risk, security, prompts, budget — without spending any tokens.

## Try it

From the repo root:

```bash
cd demo-projects/tiny-python-app
python -m agentforge init
python -m agentforge solve "Add password reset validation to the login flow" --dry-run
```

Or use the helper script:

```bash
python scripts/demo_dry_run.py
```

## Run the tests

The included tests use only the stdlib `unittest` runner so you don't need pytest:

```bash
cd demo-projects/tiny-python-app
python -m unittest discover -s tests
```

## Safety

- No `.env`, no API keys, no production hostnames, no real tokens.
- The "passwords" stored in tests are obvious placeholders (`hunter2`, `correct-horse-9`).
- Nothing talks to the network.
- The auth code is deliberately incomplete — that's the point of the demo task.

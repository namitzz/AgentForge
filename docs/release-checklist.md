# Release checklist

Run through this before tagging a new version. AgentForge is **local-first / MVP / experimental** — keep claims honest, no marketing creep.

## Pre-release

- [ ] All tests pass locally: `python -m pytest tests/`
- [ ] Demo dry-run works end-to-end: `python scripts/demo_dry_run.py`
- [ ] CI green on `main`
- [ ] No `your-org` placeholder links left in `README.md` or `pyproject.toml`
- [ ] Secret scan on the working tree:
      `git grep -nIE "(AKIA|ghp_|sk-ant|sk-[A-Za-z0-9]{32})" -- ":(exclude)tests" ":(exclude)agentforge/security.py"`
      should return nothing
- [ ] No `.env`, credentials, private keys, or `.agentforge/runs/` committed
- [ ] `CHANGELOG.md` updated with a new dated section
- [ ] Version bumped in `pyproject.toml` and `agentforge/__init__.py`
- [ ] `pip install -e .` produces a working `agentforge --help` and `agentforge doctor`
- [ ] `agentforge doctor` reports OK / WARN only (no FAIL) against a fresh clone

## Tag + release

- [ ] Commit the version bump + changelog:
      `git commit -am "Release v0.1.0"`
- [ ] Tag:
      `git tag v0.1.0 -m "AgentForge 0.1.0"`
- [ ] Push:
      `git push origin main && git push --tags`
- [ ] Create the GitHub release from the tag:
  - Title: `v0.1.0`
  - Body: paste the matching `## 0.1.0` section from `CHANGELOG.md`
  - Attach the demo GIF if recorded

## Repo metadata

- [ ] **Description:** `Cost-aware control plane for Claude, Codex, and AI coding agents.`
- [ ] **Topics:** `ai-agents` `coding-agent` `claude-code` `codex` `multi-agent` `developer-tools` `ai-code-review` `git` `cli-tool` `agent-orchestration` `ai-governance`
- [ ] About card: enable Releases + Topics + Description in repo settings
- [ ] README badges resolve (CI / Python / License)

## Demo media

- [ ] Record a 60-second demo GIF (see [`docs/demo-placeholder.md`](demo-placeholder.md))
- [ ] Save under `docs/images/` and reference from `README.md` *Quick demo* section
- [ ] Compress the GIF to under 2 MB

## Announce

- [ ] LinkedIn / X / Mastodon post: 2 sentences + GIF + repo link
- [ ] If you have a personal site: short blog note explaining what AgentForge does and what it doesn't
- [ ] Notify any beta users individually

## Post-release

- [ ] File the eight roadmap issues from [`docs/roadmap-issues.md`](roadmap-issues.md)
- [ ] Start a new `## Unreleased` section at the top of `CHANGELOG.md`
- [ ] If anything in the release surprised you (a flaky test, an awkward CLI message), open an issue while it's fresh

## Honesty check

Before publishing, scan `README.md` for any of these phrases and remove / soften them:

- "production-ready" / "production-grade"
- "enterprise-grade" / "battle-tested"
- "always" / "guaranteed" (unless backed by a test)
- "no false positives" / "100%"

Honest replacements: *MVP*, *local-first*, *experimental*, *developer-controlled*, *typically*, *defended by tests*.

# AgentForge as a Claude Code plugin

AgentForge ships as a **Claude Code plugin**, and this repo doubles as its **plugin marketplace**. Installing it adds AgentForge slash commands and an auto-invoked guardrail skill to Claude Code, so you can route AI coding changes through risk scoring, policy + security checks, and budget caps from inside your normal Claude Code session.

## What the plugin adds

**Slash commands** (namespaced under the plugin):

| Command | What it does |
|---|---|
| `/agentforge:solve` | Run a task through the full pipeline (risk → policy → security → budget → plan → implement → review). Pass `--dry-run` to preview with zero AI calls. |
| `/agentforge:plan` | Produce an implementation plan only. No edits. |
| `/agentforge:review` | PR-style, diff-only review of the current branch. |
| `/agentforge:readiness` | Score the latest run 0–100 for merge readiness. |
| `/agentforge:doctor` | Environment + config health check. |

**A skill — `agentforge-guardrails`** — that Claude invokes *automatically* when you ask for a risky or sensitive change (auth, login, tokens, payments, migrations, secrets, deploy config) or when you ask for a risk check, a diff-only review, a merge-readiness score, or a cost "dry run".

## Install from GitHub (for others)

Once this repo is pushed to GitHub, anyone can add it in an interactive Claude Code session:

```
/plugin marketplace add namitzz/AgentForge
/plugin install agentforge@agentforge-marketplace
```

Then, so the CLI the commands call is available, install the Python package once:

```bash
git clone https://github.com/namitzz/AgentForge.git
cd AgentForge
pip install -e .
```

Restart Claude Code and the `/agentforge:*` commands appear in `/help`.

## Install from a local checkout (for development)

If you already have the repo cloned locally:

```
/plugin marketplace add /absolute/path/to/AgentForge
/plugin install agentforge@agentforge-marketplace
```

(The non-interactive equivalents are `claude plugin marketplace add <path>` and `claude plugin install agentforge@agentforge-marketplace`.)

## How it fits together

```
this repo (namitzz/AgentForge)
├── .claude-plugin/
│   ├── plugin.json        ← plugin manifest (name, version, metadata)
│   └── marketplace.json   ← marketplace catalog listing this plugin at source "./"
├── commands/              ← slash commands, auto-discovered
│   ├── solve.md  plan.md  review.md  readiness.md  doctor.md
├── skills/
│   └── agentforge-guardrails/SKILL.md   ← auto-invoked guardrail skill
└── agentforge/            ← the Python CLI the commands drive
```

The plugin components (commands + skill) are thin wrappers that call the `agentforge` CLI via Bash and interpret the JSON artifacts it writes. The plugin does **not** bundle or auto-install the Python package — that's a one-time `pip install -e .` so the `agentforge` command is on PATH.

## Requirements

- Claude Code (for the plugin) with the AgentForge Python package installed (`pip install -e .`).
- Python 3.11+ and git.
- For **real** runs: the `claude` CLI logged in (or `ANTHROPIC_API_KEY` set). Every command works in `--dry-run` mode with no auth and no AI calls.

## Managing the plugin

```
/plugin                                  # open the plugin manager UI
/plugin uninstall agentforge@agentforge-marketplace
/plugin marketplace update agentforge-marketplace   # after pushing repo changes
```

## Version updates

`plugin.json` pins `version: "0.1.0"`. Bump it whenever you want installed users to pick up changes — pushing commits without bumping the version keeps the cached copy. See [Claude Code version management](https://code.claude.com/docs/en/plugins-reference#version-management).

# Security

AgentForge sends source code to external AI agents. That is the whole point of the tool, but it also means a few things deserve explicit attention.

## What AgentForge does to keep things safe

Three layers of defence run on every command, before any agent is called:

**Layer 1 — Name-based filtering.**

- **Secret files dropped by name.** Anything listed under `secret_files:` in `config.yaml` (default: `.env`, `.env.local`, `credentials.json`) is excluded at scan time.
- **Policy `block:` patterns drop more.** Default policies block `*.pem`, `**/secrets*`, etc. Add your own for project-specific sensitive paths.
- **Binaries are skipped.** Files with NUL bytes in the first 1KB are not read or sent.

**Layer 2 — Content scanning (`agentforge/security.py`).**

- **Secret content scan.** Even if a file's *name* looks innocent, its *contents* are scanned for high-precision credential patterns: AWS access/session keys, GitHub tokens, OpenAI / Anthropic API keys, JWT tokens, PEM private keys, SSH private keys, Slack tokens, Google API keys. Any file that matches is dropped from the context. The matched secret value is **never** written to logs or artifacts — only the pattern name (e.g. `aws_access_key`) and the file path are recorded.
- **Prompt-injection scan.** Selected file contents are scanned for known injection phrases (e.g. `ignore previous instructions`, `exfiltrate`, `disable safety`, `reveal your system prompt`). Warnings are surfaced in the terminal and saved to `security_report.json`. The file is **not** auto-dropped — false positives in docs and tests are common, and the agent prompts already include explicit guidance to ignore embedded instructions.
- **Env-marker scan.** Lower-confidence patterns like `API_KEY=...`, `PASSWORD=...`, `TOKEN=...`, `OPENAI_API_KEY=...`, `ANTHROPIC_API_KEY=...`. Obvious placeholders (`YOUR_KEY_HERE`, `changeme`, `replace_me*`, etc.) are ignored. Real-looking values do **not** drop the file but do add it to `suspicious_files`. Operators inspect.
- **Test-command safety check.** `default_test_command` is pattern-checked before exec. Refused patterns include `rm -rf /`, `mkfs`, raw-device writes (`dd of=/dev/...`), fork bombs, `curl | sh`, Windows `format C:` / `del /s` / `rmdir /s`, `shutdown`, and dangerous git commands: `git push --force` (or `-f`), `git reset --hard`, `git clean -fd`. A refused command is recorded as a failed test (exit 126) so the run aborts cleanly.

**Layer 3 — Pipeline guarantees.**

- **The reviewer only sees the diff.** Full source files are never sent to the reviewer agent.
- **No API keys live in this repo.** Agent CLIs handle their own authentication.
- **No destructive git.** Only `git checkout -b` into fresh branches. AgentForge never resets, force-pushes, deletes branches, or auto-merges.
- **Budget enforced before each call.** Cannot silently overrun.

## What you should still do

1. **Run `--dry-run` first.** Every command supports it. The CLI prints which agent would be called, which files would be sent, the budget estimate, and the exact prompts. It never calls an LLM. Use it before any real run on a new repo.

2. **Review `selected_files.json`.** After any run (real or dry), open `.agentforge/runs/<latest>/selected_files.json` and confirm the file list is what you'd expect. The context builder picks files by token overlap with your task — if something sensitive snuck in, you'll see it here.

3. **Review `policy_report.json`.** Confirm your policies fired the way you expect, especially the `block:` rules. Files that were dropped are listed under `blocked_files`.

4. **Add your own policies.** The defaults catch the obvious stuff, but every project has its own sensitive paths. Edit `config.yaml > policies:` to add `match:` and `block:` patterns specific to your repo.

5. **Be deliberate about the test command.** `default_test_command` is invoked as a subprocess. Don't point it at a script you haven't read.

6. **Inspect `prompts.json`.** It contains the exact text that would have been sent to each agent. If you suspect something sensitive leaked, this is where you'd see it. Redact before sharing run artifacts in issues.

7. **Inspect `security_report.json`.** It tells you, for every run: how many files had detected secrets and were dropped, which prompt-injection phrases were spotted (and in which files), and whether the test command passed the safety check. The actual secret values are never recorded — only the pattern name.

8. **Keep your agent CLIs up to date.** Auth tokens and rate-limit behavior are handled by `claude` and `codex`, not by AgentForge.

## Reporting a vulnerability

If you find a security issue, please do **not** open a public GitHub issue.

Instead:

- Open a private security advisory on the GitHub repository (Security tab → Report a vulnerability), or
- Email the maintainers directly if a contact is listed in the repository README.

Include:

- What you found
- A minimal reproduction, ideally with `.agentforge/runs/<id>/` artifacts (redacted)
- The version of AgentForge

We aim to acknowledge reports within a few business days. Coordinated disclosure is appreciated.

## Threat model (rough)

AgentForge is a local developer tool that orchestrates other CLIs. It is **not** designed for:

- Running untrusted task descriptions submitted by third parties
- Operating on repositories you do not control
- Use in CI/CD pipelines without explicit `--dry-run` or `--yes` gating

Treat it like any other tool that can edit files on your machine: review what it produces before merging.

# Security

AgentForge sends source code to external AI agents. That is the whole point of the tool, but it also means a few things deserve explicit attention.

## What AgentForge does to keep things safe

- **Secret files are filtered at scan time.** Anything listed under `secret_files:` in `config.yaml` (default: `.env`, `.env.local`, `credentials.json`) is dropped before any prompt is built. The agent never sees those files.
- **Policy `block:` patterns add to that list.** The default policies block `*.pem`, `**/secrets*`, and similar. Add your own for project-specific sensitive paths.
- **Binaries are skipped.** Files with NUL bytes in the first 1KB are not read or sent.
- **The reviewer only sees the diff.** Full source files are never sent to the reviewer agent.
- **No API keys live in this repo.** Agent CLIs handle their own authentication. AgentForge shells out and reads stdout.
- **No destructive git.** Only `git checkout -b` into fresh branches. AgentForge never resets, force-pushes, deletes branches, or auto-merges.

## What you should still do

1. **Run `--dry-run` first.** Every command supports it. The CLI prints which agent would be called, which files would be sent, the budget estimate, and the exact prompts. It never calls an LLM. Use it before any real run on a new repo.

2. **Review `selected_files.json`.** After any run (real or dry), open `.agentforge/runs/<latest>/selected_files.json` and confirm the file list is what you'd expect. The context builder picks files by token overlap with your task — if something sensitive snuck in, you'll see it here.

3. **Review `policy_report.json`.** Confirm your policies fired the way you expect, especially the `block:` rules. Files that were dropped are listed under `blocked_files`.

4. **Add your own policies.** The defaults catch the obvious stuff, but every project has its own sensitive paths. Edit `config.yaml > policies:` to add `match:` and `block:` patterns specific to your repo.

5. **Be deliberate about the test command.** `default_test_command` is invoked as a subprocess. Don't point it at a script you haven't read.

6. **Inspect `prompts.json`.** It contains the exact text that would have been sent to each agent. If you suspect something sensitive leaked, this is where you'd see it. Redact before sharing run artifacts in issues.

7. **Keep your agent CLIs up to date.** Auth tokens and rate-limit behavior are handled by `claude` and `codex`, not by AgentForge.

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

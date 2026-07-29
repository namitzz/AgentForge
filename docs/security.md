# Security defaults

> **Honest framing.** AgentForge's local security checks are pattern-based and best-effort. They reduce common ways code, secrets, and prompt-injection text leak into AI prompts, but they are not a guarantee. Treat them as a defence-in-depth layer alongside (not instead of) human review.

Without any config changes, every run already does this:

| Layer | What it does | Default |
|---|---|---|
| Name filter | Drop files whose name matches `secret_files:` | `.env`, `.env.local`, `.env.production`, `credentials.json`, `service-account.json`, `secrets.yaml`, `secrets.yml`, `id_rsa`, `id_ed25519` |
| Policy `block:` | Drop files matching glob patterns | `.env`, `.env.*`, `*.pem`, `credentials.json`, `**/secrets*` |
| Secret value scan | Drop files whose **content** matches a vendor credential pattern | AWS keys, GitHub tokens, OpenAI / Anthropic keys, JWTs, PEM private keys, SSH keys, Slack / Google API keys |
| Env-marker scan | Warn on `API_KEY=`, `PASSWORD=`, `TOKEN=`, `SECRET=` with a non-placeholder value | files kept, flagged in `suspicious_files` |
| Prompt-injection scan | Warn on phrases like *ignore previous instructions*, *exfiltrate*, *disable safety*, *upload this code*, *print environment variables* | files kept, listed in `prompt_injection_warnings` |
| Command safety | Refuse to run `default_test_command` if it matches a destructive pattern | `rm -rf /`, `mkfs`, `dd of=/dev/...`, fork bomb, `curl \| sh`, `format C:`, `del /s`, `rmdir /s`, `git push --force`, `git reset --hard`, `git clean -fd`, `shutdown` |
| Git operations | Only `git checkout -b` into fresh branches | no `push`, `reset`, `force-push`, or branch deletion |
| Reviewer scope | Diff only | full source never sent to the reviewer |

Every check runs locally. No network, no LLM, no third-party services. Findings land in `.agentforge/runs/<timestamp>/security_report.json`:

```json
{
  "blocked_files": ["src/utils/keys.py"],
  "suspicious_files": ["docs/notes.md"],
  "prompt_injection_warnings": [
    {"file": "docs/notes.md", "phrase": "ignore previous instructions"}
  ],
  "command_risk": "low",
  "command_blocked": false,
  "reasons": ["Dropped 1 file(s) containing secret patterns: aws_access_key"],
  "safe_to_continue": true
}
```

The matched secret value is **never** written to that file — only the pattern name and the file path.

Terminal output:

```
Security checks:
- Blocked secret files: src/utils/keys.py
- Prompt-injection warnings: 1
    - docs/notes.md: "ignore previous instructions"
- Command risk: low
- Safe to continue: yes
```

## Limitations to be aware of

- Pattern-based credential detection catches common vendor formats; bespoke or obfuscated secrets can slip through. Inspect `selected_files.json` after a run to confirm the file list.
- The prompt-injection list is finite. New attack phrasings will not be caught until added.
- The command safety check is a deny-list and assumes default shell semantics. A maliciously-crafted equivalent could evade it.
- Reviewer-scope guarantee (diff-only) holds because the orchestrator builds the prompt that way — verify in `prompts.json` if your config swaps the reviewer adapter.

If you want a stricter posture, see the [Minimum secure-default config](policies.md#minimum-secure-default-config) and the [No-Code-Leak Mode](privacy.md) which refuses to send code at all.

If you find a vulnerability, please report privately — see [SECURITY.md](../SECURITY.md).

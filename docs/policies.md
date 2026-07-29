# Policy rules

Declarative governance lives in `config.yaml`:

```yaml
policies:
  - name: "Never send secrets to AI"
    block:
      - ".env"
      - "*.pem"
      - "credentials.json"
      - "**/secrets*"

  - name: "Auth changes require review"
    match:
      - "auth/**"
      - "**/login*"
      - "**/security*"
    require_review: true
    require_tests: true

  - name: "Database changes require human approval"
    match:
      - "migrations/**"
      - "**/schema.sql"
      - "**/models.py"
    require_human_approval: true
```

The `PolicyEngine` (in `agentforge/policy_engine.py`) evaluates these rules against the set of files the run is about to send to an agent. `block:` patterns are dropped from the context before any prompt is built. `match:` patterns escalate the run: force review, force tests, prompt for human approval. Decisions are saved to `policy_report.json`.

Sample terminal output:

```
Policy checks:
- Blocked files: .env
- Review required: yes
- Tests required: yes
- Human approval required: yes
- Reasons:
  - Auth changes require review
  - Never send secrets to AI
```

Pattern matching supports glob syntax (`**/x` for any depth, `dir/**` for everything under a dir, plain `fnmatch` otherwise). Empty pattern lists are skipped without error.

## Minimum secure-default config

If you want the most conservative posture, start from this. Tighten the budget caps, expand the secret file and policy lists, force review + tests + human approval for anything touching auth, secrets, or the database. Drop into `config.yaml`:

```yaml
# Tight budget. Fail closed when in doubt.
max_ai_calls_per_run: 3
max_review_loops: 0
max_files_sent: 5
max_chars_per_file: 8000
max_total_chars: 40000

# Files always filtered by name before any prompt is built.
secret_files:
  - .env
  - .env.local
  - .env.production
  - credentials.json
  - id_rsa
  - id_ed25519

policies:
  - name: "Never send secrets to AI"
    block:
      - ".env"
      - ".env.*"
      - "*.pem"
      - "*.key"
      - "credentials*"
      - "**/secrets*"
      - "**/private*"
      - "**/id_rsa*"
      - "**/id_ed25519*"

  - name: "Sensitive paths require human approval"
    match:
      - "**/auth*"
      - "**/login*"
      - "**/security*"
      - "migrations/**"
      - "**/schema*"
      - "**/models.py"
    require_review: true
    require_tests: true
    require_human_approval: true
```

> Heuristic only: these patterns reflect common project conventions. They are not a substitute for a security review.

On top of those rules, the content scanner in `agentforge/security.py` drops any file whose body matches a known credential pattern (AWS, GitHub, OpenAI, Anthropic, JWT, PEM private key, SSH key) regardless of its name. See [`docs/security.md`](security.md). The pattern name lands in `security_report.json`; the actual secret value is never logged.

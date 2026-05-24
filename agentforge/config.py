"""Configuration loading and validation for AgentForge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class AgentRoutes:
    planner: str = "claude"
    implementer: str = "codex"
    reviewer: str = "claude"


@dataclass
class Config:
    project_name: str = "AgentForge"
    default_test_command: str = "pytest"

    max_ai_calls_per_run: int = 5
    max_review_loops: int = 1
    max_files_sent: int = 8
    max_chars_per_file: int = 12_000
    max_total_chars: int = 80_000

    claude_command: str = "claude --print"
    codex_command: str = "codex exec"

    # Per-command (agent or test) timeout. If the subprocess does not finish
    # in this many seconds AgentForge stops it and writes a failure report.
    command_timeout_seconds: int = 600

    agents: AgentRoutes = field(default_factory=AgentRoutes)

    ignore_dirs: list[str] = field(default_factory=lambda: [
        ".git", "node_modules", "venv", ".venv", "__pycache__",
        "dist", "build", ".agentforge",
    ])
    text_extensions: list[str] = field(default_factory=lambda: [
        ".py", ".js", ".ts", ".md", ".yaml", ".yml", ".json", ".toml",
    ])
    risky_files: list[str] = field(default_factory=lambda: [
        "auth", "security", "payment", "database", "migrations", "config",
    ])
    secret_files: list[str] = field(default_factory=lambda: [
        ".env", ".env.local", "credentials.json",
    ])

    branch_prefix: str = "agentforge/"

    # Declarative governance rules. Raw dicts; PolicyEngine parses them.
    policies: list[dict[str, Any]] = field(default_factory=list)

    # Filled by the loader.
    source_path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: Path | None = None) -> "Config":
        agents_raw = data.get("agents") or {}
        agents = AgentRoutes(
            planner=agents_raw.get("planner", "claude"),
            implementer=agents_raw.get("implementer", "codex"),
            reviewer=agents_raw.get("reviewer", "claude"),
        )
        cfg = cls(
            project_name=data.get("project_name", "AgentForge"),
            default_test_command=data.get("default_test_command", "pytest"),
            max_ai_calls_per_run=int(data.get("max_ai_calls_per_run", 5)),
            max_review_loops=int(data.get("max_review_loops", 1)),
            max_files_sent=int(data.get("max_files_sent", 8)),
            max_chars_per_file=int(data.get("max_chars_per_file", 12_000)),
            max_total_chars=int(data.get("max_total_chars", 80_000)),
            claude_command=data.get("claude_command", "claude --print"),
            codex_command=data.get("codex_command", "codex exec"),
            command_timeout_seconds=int(data.get("command_timeout_seconds", 600)),
            agents=agents,
            ignore_dirs=list(data.get("ignore_dirs", cls.__dataclass_fields__["ignore_dirs"].default_factory())),
            text_extensions=list(data.get("text_extensions", cls.__dataclass_fields__["text_extensions"].default_factory())),
            risky_files=list(data.get("risky_files", cls.__dataclass_fields__["risky_files"].default_factory())),
            secret_files=list(data.get("secret_files", cls.__dataclass_fields__["secret_files"].default_factory())),
            branch_prefix=data.get("branch_prefix", "agentforge/"),
            policies=list(data.get("policies") or []),
            source_path=source,
        )
        return cfg


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Load a YAML config file. Falls back to defaults if missing."""
    p = Path(path)
    if not p.exists():
        return Config(source_path=None)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {p} must contain a YAML mapping.")
    return Config.from_dict(data, source=p)


DEFAULT_CONFIG_YAML = """\
project_name: MyProject
default_test_command: "pytest"

max_ai_calls_per_run: 5
max_review_loops: 1
max_files_sent: 8
max_chars_per_file: 12000
max_total_chars: 80000

claude_command: "claude --print"
codex_command: "codex exec"

# Per-command (agent or test) timeout in seconds. Lower it for tight CI
# environments; raise it for big refactors or slow test suites.
command_timeout_seconds: 600

agents:
  planner: claude
  implementer: codex
  reviewer: claude

ignore_dirs:
  - .git
  - node_modules
  - venv
  - .venv
  - __pycache__
  - dist
  - build
  - .agentforge

text_extensions:
  - .py
  - .js
  - .ts
  - .tsx
  - .jsx
  - .go
  - .rs
  - .java
  - .md
  - .yaml
  - .yml
  - .json
  - .toml

risky_files:
  - auth
  - security
  - payment
  - database
  - migrations
  - config
  - secret

secret_files:
  - .env
  - .env.local
  - .env.production
  - credentials.json
  - service-account.json
  - secrets.yaml
  - secrets.yml
  - id_rsa
  - id_ed25519

branch_prefix: "agentforge/"

# Anonymous telemetry. Off by default. Run `agentforge telemetry status`
# to inspect, or `agentforge telemetry enable` to opt in. Source code,
# prompts, diffs, file paths, repo names, and secrets are NEVER sent.
telemetry:
  enabled: false
  anonymous_id: null
  endpoint: null

# Declarative governance rules. Optional but recommended.
policies:
  - name: "Auth changes require review"
    match:
      - "auth/**"
      - "**/login*"
      - "**/security*"
    require_review: true
    require_tests: true

  - name: "Never send secrets to AI"
    block:
      - ".env"
      - ".env.*"
      - "*.pem"
      - "credentials.json"
      - "**/secrets*"

  - name: "Database changes require human approval"
    match:
      - "migrations/**"
      - "**/schema.sql"
      - "**/models.py"
    require_human_approval: true
"""


def write_default_config(path: Path | str = DEFAULT_CONFIG_PATH, overwrite: bool = False) -> Path:
    """Write a starter config.yaml. Returns the path written."""
    p = Path(path)
    if p.exists() and not overwrite:
        return p
    p.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
    return p

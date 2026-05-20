"""Shared test fixtures.

Builds tiny temporary 'repos' via pytest's tmp_path so unit tests can exercise
the scanner, context builder, and orchestrator end-to-end without ever calling
a real agent CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.config import Config


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A small repo with text files, an ignored dir, secrets, and a binary."""
    _write(tmp_path / "README.md", "# sample\n")
    _write(tmp_path / "src" / "auth.py", "def login():\n    return True\n")
    _write(tmp_path / "src" / "pagination.py", "def paginate(items, page):\n    return items[page:page+10]\n")
    _write(tmp_path / "tests" / "test_pagination.py", "def test_paginate():\n    assert True\n")
    _write(tmp_path / "migrations" / "001_init.sql", "CREATE TABLE users (id INT);")
    _write(tmp_path / ".env", "SECRET=xyz\n")
    _write(tmp_path / "credentials.json", '{"key": "real-secret"}')
    _write(tmp_path / "node_modules" / "lib" / "index.js", "// should be ignored")
    # Binary-ish file with NUL bytes.
    (tmp_path / "image.png").write_bytes(b"PNG\x00\x00\x00data")
    return tmp_path


@pytest.fixture
def base_config() -> Config:
    return Config(
        project_name="Test",
        default_test_command="",
        max_ai_calls_per_run=3,
        max_review_loops=1,
        max_files_sent=5,
        max_chars_per_file=2000,
        max_total_chars=10_000,
        claude_command="claude --print",
        codex_command="codex exec",
        ignore_dirs=[".git", "node_modules", ".agentforge"],
        text_extensions=[".py", ".md", ".sql", ".json"],
        risky_files=["auth", "migrations"],
        secret_files=[".env", "credentials.json"],
        branch_prefix="agentforge/",
        policies=[
            {
                "name": "Never send secrets",
                "block": [".env", "credentials.json", "**/secrets*"],
            },
            {
                "name": "Auth changes require review",
                "match": ["**/auth*", "**/login*"],
                "require_review": True,
                "require_tests": True,
            },
            {
                "name": "Migrations require approval",
                "match": ["migrations/**"],
                "require_human_approval": True,
            },
        ],
    )

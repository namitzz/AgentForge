"""Adapter for the OpenAI Codex CLI."""

from __future__ import annotations

from pathlib import Path

from .base import CLIAgent


class CodexAgent(CLIAgent):
    def __init__(self, command: str = "codex exec", cwd: Path | str | None = None, timeout: int = 600) -> None:
        super().__init__(name="codex", command=command, cwd=cwd, timeout=timeout)

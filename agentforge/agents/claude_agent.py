"""Adapter for the Claude Code CLI."""

from __future__ import annotations

from pathlib import Path

from .base import CLIAgent


class ClaudeAgent(CLIAgent):
    def __init__(self, command: str = "claude --print", cwd: Path | str | None = None, timeout: int = 600) -> None:
        super().__init__(name="claude", command=command, cwd=cwd, timeout=timeout)

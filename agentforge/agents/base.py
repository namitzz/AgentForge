"""Base contracts for agents."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AgentUnavailable(RuntimeError):
    """Raised when an agent's underlying CLI is not installed or misconfigured."""


@dataclass
class AgentResponse:
    agent: str
    role: str
    prompt_chars: int
    output: str
    exit_code: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.error


class Agent:
    """Base class. Each adapter implements ``run(prompt) -> AgentResponse``."""

    name: str = "agent"

    def run(self, prompt: str, role: str = "generic") -> AgentResponse:
        raise NotImplementedError


def _resolve_command(command: str) -> list[str]:
    """Split a command string and verify the executable is on PATH."""
    if not command or not command.strip():
        raise AgentUnavailable("agent command is empty; set it in config.yaml")
    parts = shlex.split(command, posix=False)
    if not parts:
        raise AgentUnavailable(f"could not parse command: {command!r}")
    exe = parts[0]
    if shutil.which(exe) is None:
        raise AgentUnavailable(
            f"'{exe}' not found on PATH. Install it, or update the command in config.yaml."
        )
    return parts


class CLIAgent(Agent):
    """Generic agent that shells out to a CLI taking the prompt as one argument."""

    def __init__(self, name: str, command: str, cwd: Path | str | None = None, timeout: int = 600) -> None:
        self.name = name
        self.command = command
        self.cwd = str(cwd) if cwd else None
        self.timeout = timeout

    def run(self, prompt: str, role: str = "generic") -> AgentResponse:
        try:
            argv = _resolve_command(self.command)
        except AgentUnavailable as exc:
            return AgentResponse(
                agent=self.name, role=role, prompt_chars=len(prompt),
                output="", exit_code=127, error=str(exc),
            )
        argv = argv + [prompt]
        try:
            proc = subprocess.run(
                argv,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return AgentResponse(
                agent=self.name, role=role, prompt_chars=len(prompt),
                output=exc.stdout or "", exit_code=124,
                error=f"agent '{self.name}' timed out after {self.timeout}s",
            )
        except OSError as exc:
            return AgentResponse(
                agent=self.name, role=role, prompt_chars=len(prompt),
                output="", exit_code=126, error=str(exc),
            )
        return AgentResponse(
            agent=self.name,
            role=role,
            prompt_chars=len(prompt),
            output=(proc.stdout or "").strip(),
            exit_code=proc.returncode,
            error=(proc.stderr or "").strip() or None if proc.returncode != 0 else None,
        )

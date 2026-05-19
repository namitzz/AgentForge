"""Run the project's configured test command."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_text(self) -> str:
        return (
            f"$ {self.command}\n"
            f"exit_code: {self.exit_code}\n"
            f"--- stdout ---\n{self.stdout}\n"
            f"--- stderr ---\n{self.stderr}\n"
        )


def run_tests(command: str, cwd: Path | str = ".", timeout: int = 600) -> TestResult:
    """Run the test command. Captures output; never raises on non-zero exit."""
    if not command or not command.strip():
        return TestResult(command="", exit_code=0, stdout="(no test command configured)", stderr="")
    args = shlex.split(command, posix=False)
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return TestResult(command=command, exit_code=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return TestResult(
            command=command,
            exit_code=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[timed out after {timeout}s]",
        )
    return TestResult(
        command=command,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )

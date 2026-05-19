"""Local (non-LLM) agent.

Provides cheap operations that should never burn AI budget:
repo scanning, file reading, git diff, and test running.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..tools import file_scanner, git_tools
from ..tools.test_runner import TestResult, run_tests
from .base import Agent, AgentResponse


@dataclass
class LocalAgent(Agent):
    config: Config
    cwd: Path = Path(".")
    name: str = "local"

    def run(self, prompt: str, role: str = "generic") -> AgentResponse:
        # The local agent never accepts free-form prompts; surface a clear error.
        return AgentResponse(
            agent=self.name,
            role=role,
            prompt_chars=len(prompt or ""),
            output="",
            exit_code=2,
            error="LocalAgent does not accept prompts; call its methods directly.",
        )

    # --- explicit operations -----------------------------------------
    def scan_repo(self) -> file_scanner.RepoSummary:
        return file_scanner.scan_repo(self.cwd, self.config)

    def read_file(self, rel_path: str) -> str:
        return file_scanner.read_file_capped(
            self.cwd / rel_path,
            max_chars=self.config.max_chars_per_file,
        )

    def git_diff(self) -> str:
        if not git_tools.is_git_repo(self.cwd):
            return ""
        return git_tools.diff(staged=False, path=self.cwd)

    def run_tests(self) -> TestResult:
        return run_tests(self.config.default_test_command, cwd=self.cwd)

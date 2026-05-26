"""Budget tracking for AgentForge runs.

Cost is approximated as (number of AI calls) + (characters sent). No
token-accurate counting yet — character count is the proxy.

The manager exposes two views of every run:

  - **Estimate** (printed up-front, before the first agent call).
    Built from the routing + the prompts the orchestrator has prepared.

  - **Summary** (printed at the end).
    The actuals: calls used, files sent, chars sent, review loops, whether
    the run stopped early and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config


class BudgetExceeded(RuntimeError):
    """Raised when a run would exceed its configured budget."""


@dataclass
class BudgetSnapshot:
    # Actuals
    ai_calls: int
    review_loops: int
    chars_sent: int
    files_sent: int
    # Caps
    max_ai_calls: int
    max_review_loops: int
    max_total_chars: int
    max_files_sent: int
    max_chars_per_file: int
    # Plan (set before the first agent call)
    planned_ai_calls: int = 0
    planned_chars_sent: int = 0
    # Result
    dry_run: bool = False
    stopped_early: bool = False
    stop_reason: str | None = None
    # Per-call breakdown so downstream tools (scorecards, telemetry) can
    # attribute chars + roles to specific agents. List of
    # {"agent", "role", "prompt_chars"}.
    call_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ai_calls": self.ai_calls,
            "review_loops": self.review_loops,
            "chars_sent": self.chars_sent,
            "files_sent": self.files_sent,
            "max_ai_calls": self.max_ai_calls,
            "max_review_loops": self.max_review_loops,
            "max_total_chars": self.max_total_chars,
            "max_files_sent": self.max_files_sent,
            "max_chars_per_file": self.max_chars_per_file,
            "planned_ai_calls": self.planned_ai_calls,
            "planned_chars_sent": self.planned_chars_sent,
            "dry_run": self.dry_run,
            "stopped_early": self.stopped_early,
            "stop_reason": self.stop_reason,
            "call_log": list(self.call_log),
        }

    def estimate_summary(self) -> list[str]:
        """Lines printed before the first agent call."""
        return [
            "Budget estimate:",
            f"- Planned AI calls: {self.planned_ai_calls}/{self.max_ai_calls}",
            f"- Files selected: {self.files_sent}/{self.max_files_sent}",
            f"- Estimated chars sent: {self.planned_chars_sent:,}",
            f"- Review loops allowed: {self.max_review_loops}",
            f"- Dry run: {'yes' if self.dry_run else 'no'}",
        ]

    def human_summary(self) -> list[str]:
        """Lines printed at the end of the run."""
        lines = [
            "Budget summary:",
            f"- AI calls used: {self.ai_calls}/{self.max_ai_calls}",
            f"- Review loops used: {self.review_loops}/{self.max_review_loops}",
            f"- Files sent: {self.files_sent}/{self.max_files_sent}",
            f"- Estimated chars sent: {self.chars_sent:,}",
            f"- Stopped early: {'yes' if self.stopped_early else 'no'}",
        ]
        if self.stop_reason:
            lines.append(f"- Stop reason: {self.stop_reason}")
        return lines


@dataclass
class BudgetManager:
    config: Config
    ai_calls: int = 0
    review_loops: int = 0
    chars_sent: int = 0
    files_sent: int = 0
    planned_ai_calls: int = 0
    planned_chars_sent: int = 0
    dry_run: bool = False
    stopped_early: bool = False
    stop_reason: str | None = None
    call_log: list[dict] = field(default_factory=list)

    # --- Limits --------------------------------------------------------
    @property
    def max_ai_calls(self) -> int:
        return self.config.max_ai_calls_per_run

    @property
    def max_review_loops(self) -> int:
        return self.config.max_review_loops

    @property
    def max_files_sent(self) -> int:
        return self.config.max_files_sent

    @property
    def max_chars_per_file(self) -> int:
        return self.config.max_chars_per_file

    @property
    def max_total_chars(self) -> int:
        return self.config.max_total_chars

    # --- Checks --------------------------------------------------------
    def can_call_ai(self) -> bool:
        return self.ai_calls < self.max_ai_calls

    def can_start_review_loop(self) -> bool:
        return self.review_loops < self.max_review_loops

    def remaining_chars(self) -> int:
        return max(0, self.max_total_chars - self.chars_sent)

    # --- Estimation (called before the first agent call) ---------------
    def record_planned(self, ai_calls: int, chars: int) -> None:
        """Store the up-front estimate. Does not raise — call
        :meth:`enforce_planned_within_caps` after emitting the estimate
        so the user always sees the numbers before any abort message."""
        self.planned_ai_calls = ai_calls
        self.planned_chars_sent = chars

    def enforce_planned_within_caps(self) -> None:
        """Raise if the stored estimate would exceed the configured caps."""
        if self.planned_ai_calls > self.max_ai_calls:
            raise BudgetExceeded(
                f"Planned AI calls ({self.planned_ai_calls}) exceed cap "
                f"({self.max_ai_calls}). Raise max_ai_calls_per_run "
                f"in config.yaml or narrow the task."
            )
        if self.planned_chars_sent > self.max_total_chars:
            raise BudgetExceeded(
                f"Estimated prompt size ({self.planned_chars_sent:,} chars) "
                f"exceeds total cap ({self.max_total_chars:,}). Raise "
                f"max_total_chars or reduce max_files_sent / max_chars_per_file."
            )

    def set_dry_run(self, value: bool) -> None:
        self.dry_run = value

    # --- Recording -----------------------------------------------------
    def record_call(self, agent: str, role: str, prompt_chars: int) -> None:
        if not self.can_call_ai():
            raise BudgetExceeded(
                f"AI call budget exhausted ({self.ai_calls}/{self.max_ai_calls}). "
                "Raise max_ai_calls_per_run in config.yaml to continue."
            )
        if prompt_chars > self.remaining_chars():
            raise BudgetExceeded(
                f"Character budget would be exceeded: prompt is {prompt_chars:,} "
                f"chars but only {self.remaining_chars():,} remain."
            )
        self.ai_calls += 1
        self.chars_sent += prompt_chars
        self.call_log.append({
            "agent": agent,
            "role": role,
            "prompt_chars": prompt_chars,
        })

    def record_review_loop(self) -> None:
        if not self.can_start_review_loop():
            raise BudgetExceeded(
                f"Review loop budget exhausted ({self.review_loops}/{self.max_review_loops})."
            )
        self.review_loops += 1

    def record_files_sent(self, n: int) -> None:
        # Tracks the largest selected-file set seen across the run.
        self.files_sent = max(self.files_sent, n)

    def mark_stopped_early(self, value: bool = True, reason: str | None = None) -> None:
        self.stopped_early = value
        if reason and value:
            self.stop_reason = reason

    # --- Reporting -----------------------------------------------------
    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            ai_calls=self.ai_calls,
            review_loops=self.review_loops,
            chars_sent=self.chars_sent,
            files_sent=self.files_sent,
            max_ai_calls=self.max_ai_calls,
            max_review_loops=self.max_review_loops,
            max_total_chars=self.max_total_chars,
            max_files_sent=self.max_files_sent,
            max_chars_per_file=self.max_chars_per_file,
            planned_ai_calls=self.planned_ai_calls,
            planned_chars_sent=self.planned_chars_sent,
            dry_run=self.dry_run,
            stopped_early=self.stopped_early,
            stop_reason=self.stop_reason,
            call_log=list(self.call_log),
        )

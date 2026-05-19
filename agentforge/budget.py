"""Budget tracking for AgentForge runs.

The MVP approximates cost as (number of AI calls) + (characters sent).
No token-accurate counting yet — character count is the proxy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config


class BudgetExceeded(RuntimeError):
    """Raised when a run would exceed its configured budget."""


@dataclass
class BudgetSnapshot:
    ai_calls: int
    review_loops: int
    chars_sent: int
    max_ai_calls: int
    max_review_loops: int
    max_total_chars: int

    def to_dict(self) -> dict:
        return {
            "ai_calls": self.ai_calls,
            "review_loops": self.review_loops,
            "chars_sent": self.chars_sent,
            "max_ai_calls": self.max_ai_calls,
            "max_review_loops": self.max_review_loops,
            "max_total_chars": self.max_total_chars,
        }


@dataclass
class BudgetManager:
    config: Config
    ai_calls: int = 0
    review_loops: int = 0
    chars_sent: int = 0
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

    # --- Recording -----------------------------------------------------
    def record_call(self, agent: str, role: str, prompt_chars: int) -> None:
        if not self.can_call_ai():
            raise BudgetExceeded(
                f"AI call budget exhausted ({self.ai_calls}/{self.max_ai_calls}). "
                "Raise max_ai_calls_per_run in config.yaml to continue."
            )
        if prompt_chars > self.remaining_chars():
            raise BudgetExceeded(
                f"Character budget would be exceeded: prompt is {prompt_chars} chars "
                f"but only {self.remaining_chars()} remain."
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

    # --- Reporting -----------------------------------------------------
    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            ai_calls=self.ai_calls,
            review_loops=self.review_loops,
            chars_sent=self.chars_sent,
            max_ai_calls=self.max_ai_calls,
            max_review_loops=self.max_review_loops,
            max_total_chars=self.max_total_chars,
        )

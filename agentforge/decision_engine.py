"""Agent decision engine.

Aggregates the local signals (task classification, risk, policy, security,
context size, budget caps) into one explicit "how many agents do we actually
need" decision **before** any agent is invoked.

The engine is purely deterministic and never calls an external agent. The
result is written to ``.agentforge/runs/<id>/decision_report.json`` and
surfaced in the CLI so the routing is auditable.

Decisions
---------
``NO_AI``               No agent call needed. Used when:
                          - security says safe_to_continue=false, or
                          - the planned prompt would exceed the budget cap, or
                          - the task is a trivial docs/typo with no files.

``SINGLE_AGENT``        One agent call. Typically the implementer for a
                        small LOW-risk change with no review required.

``IMPLEMENT_AND_REVIEW`` Two agent calls (implementer + reviewer). Used for
                        MEDIUM risk, or LOW risk where a policy forces
                        review.

``FULL_PIPELINE``       Planner + implementer + reviewer. Used for HIGH
                        risk, UNKNOWN risk, or anything where the
                        classifier and policy stack agree review + planning
                        are warranted.

Notes
-----
- The engine recommends; the orchestrator already enforces its own routing
  based on the same signals. The decision report exists so an operator can
  audit *why* a particular set of agent calls was planned.
- Adding a new field requires editing both the dataclass and the
  ``to_dict`` method. Keep the keys stable — downstream tooling and the
  README schema reference these names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Decision(str, Enum):
    NO_AI                = "NO_AI"
    SINGLE_AGENT         = "SINGLE_AGENT"
    IMPLEMENT_AND_REVIEW = "IMPLEMENT_AND_REVIEW"
    FULL_PIPELINE        = "FULL_PIPELINE"


# Task-type families that intrinsically skip planning.
_NO_PLANNER_TASKS: frozenset[str] = frozenset({"docs", "tests", "bug_fix"})

# Risk levels that genuinely warrant a planner.
_PLANNER_RISKS: frozenset[str] = frozenset({"HIGH", "UNKNOWN"})

# Risk levels that warrant a reviewer regardless of policy.
_REVIEWER_RISKS: frozenset[str] = frozenset({"MEDIUM", "HIGH", "UNKNOWN"})


# ---------------------------------------------------------------------------
# Inputs / Result
# ---------------------------------------------------------------------------

@dataclass
class DecisionInputs:
    """All signals the engine needs. Pre-computed by the orchestrator."""

    task_text: str                 # original task description (for display only)
    task_type: str                 # classifier verdict, e.g. "bug_fix"
    risk_level: str                # LOW / MEDIUM / HIGH / UNKNOWN

    # Policy escalations.
    require_review: bool           # policy.require_review OR risk.review_required
    require_tests: bool            # policy.require_tests OR risk.tests_required
    require_human_approval: bool   # policy.require_human_approval OR risk.human_approval_required

    # Security verdict.
    safe_to_continue: bool         # security_report.safe_to_continue

    # Context shape.
    selected_files_count: int
    estimated_prompt_chars: int

    # Budget caps.
    max_total_chars: int
    max_ai_calls: int

    # Configured agents (the engine may recommend a subset).
    planner_agent: str
    implementer_agent: str
    reviewer_agent: str

    # Mode flags.
    dry_run: bool = False


@dataclass
class DecisionResult:
    decision: str
    recommended_agents: dict[str, str | None]
    planned_ai_calls: int
    reasons: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    safe_to_continue: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "recommended_agents": dict(self.recommended_agents),
            "planned_ai_calls": self.planned_ai_calls,
            "reasons": list(self.reasons),
            "skipped_steps": list(self.skipped_steps),
            "safe_to_continue": self.safe_to_continue,
        }

    def human_summary(self) -> list[str]:
        lines: list[str] = ["Agent decision:"]
        lines.append(f"- Decision: {self.decision}")
        lines.append(f"- Planned AI calls: {self.planned_ai_calls}")

        agents = self.recommended_agents
        if any(agents.values()):
            lines.append("- Agents:")
            for role in ("planner", "implementer", "reviewer"):
                value = agents.get(role)
                if value:
                    lines.append(f"  - {role.capitalize()}: {value}")
                else:
                    lines.append(f"  - {role.capitalize()}: (none)")

        if self.reasons:
            lines.append("- Reasons:")
            for r in self.reasons:
                lines.append(f"  - {r}")

        if self.skipped_steps:
            lines.append("- Skipped:")
            for s in self.skipped_steps:
                lines.append(f"  - {s}")

        if not self.safe_to_continue:
            lines.append("- Safe to continue: no")
        return lines


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DecisionEngine:
    """Pure, deterministic routing decision."""

    def decide(self, inputs: DecisionInputs) -> DecisionResult:
        risk      = (inputs.risk_level or "UNKNOWN").upper()
        task_type = (inputs.task_type or "unknown").lower()

        # -------- Safety short-circuits --------
        if not inputs.safe_to_continue:
            return DecisionResult(
                decision=Decision.NO_AI.value,
                recommended_agents={"planner": None, "implementer": None, "reviewer": None},
                planned_ai_calls=0,
                reasons=["Security check refused to continue (safe_to_continue=false)"],
                skipped_steps=["All AI calls skipped because the security report blocked the run"],
                safe_to_continue=False,
            )

        if inputs.estimated_prompt_chars > inputs.max_total_chars > 0:
            return DecisionResult(
                decision=Decision.NO_AI.value,
                recommended_agents={"planner": None, "implementer": None, "reviewer": None},
                planned_ai_calls=0,
                reasons=[
                    f"Estimated prompt size ({inputs.estimated_prompt_chars:,} chars) "
                    f"would exceed total cap ({inputs.max_total_chars:,} chars)"
                ],
                skipped_steps=["All AI calls skipped because the run would exceed the budget"],
                safe_to_continue=False,
            )

        # -------- Trivial / no-context paths --------
        # Empty context + LOW docs/tests + no policy escalation = nothing useful
        # to send. Recommend NO_AI so the user knows they can hand-fix it.
        if (
            inputs.selected_files_count == 0
            and task_type in ("docs", "tests")
            and risk == "LOW"
            and not inputs.require_review
            and not inputs.require_human_approval
        ):
            return DecisionResult(
                decision=Decision.NO_AI.value,
                recommended_agents={"planner": None, "implementer": None, "reviewer": None},
                planned_ai_calls=0,
                reasons=[
                    "Task is LOW risk",
                    "No relevant files were selected (empty context)",
                    f"'{task_type}' task with empty context does not need AI",
                ],
                skipped_steps=["All AI calls skipped — nothing to send"],
                safe_to_continue=True,
            )

        # -------- Role-by-role routing --------
        planner:     str | None = None
        implementer: str | None = inputs.implementer_agent or None
        reviewer:    str | None = None
        reasons:      list[str] = []
        skipped:      list[str] = []

        # Planner: HIGH/UNKNOWN risk, OR task is a planning-worthy kind
        # (refactor / feature / security). Always skipped for docs / tests /
        # bug_fix regardless of risk — the planner adds no value there.
        if task_type in _NO_PLANNER_TASKS:
            skipped.append(f"Planner skipped because task is a {task_type}")
        elif risk in _PLANNER_RISKS:
            planner = inputs.planner_agent or None
            if planner is not None:
                reasons.append(f"Planner included because risk is {risk}")
        else:
            skipped.append(f"Planner skipped because risk is {risk}")

        # Reviewer: MEDIUM/HIGH/UNKNOWN risk OR policy says so.
        if inputs.require_review or risk in _REVIEWER_RISKS:
            reviewer = inputs.reviewer_agent or None
            if inputs.require_review and risk not in _REVIEWER_RISKS:
                reasons.append("Reviewer required by policy")
            elif risk == "HIGH":
                reasons.append("Reviewer required for HIGH risk task")
            elif risk == "MEDIUM":
                reasons.append("Reviewer required for MEDIUM risk task")
            elif risk == "UNKNOWN":
                reasons.append("Reviewer included because risk is UNKNOWN (safe default)")
        else:
            skipped.append(
                f"Reviewer skipped because task is {risk} risk and no policy requires review"
            )

        # Risk-level reason (always include for clarity)
        if risk in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
            reasons.append(f"Task classified as {risk} risk")

        # Approval / tests requirements (context for the operator)
        if inputs.require_human_approval:
            reasons.append("Human approval required before merge")
        if inputs.require_tests:
            reasons.append("Tests required by policy or risk")

        # Note when we're inside budget
        if inputs.max_total_chars > 0:
            reasons.append(
                f"Context is within budget "
                f"({inputs.estimated_prompt_chars:,}/{inputs.max_total_chars:,} chars)"
            )

        # Mode note
        if inputs.dry_run:
            reasons.append(
                "Dry-run mode: prompts will be built but no agent will be called"
            )

        # -------- Tally + label --------
        planned_calls = sum(1 for a in (planner, implementer, reviewer) if a)

        # Cap planned_calls at the configured max so a too-small budget shows.
        if planned_calls > inputs.max_ai_calls > 0:
            skipped.append(
                f"Planned {planned_calls} calls exceeds max_ai_calls "
                f"({inputs.max_ai_calls}); the run may stop early"
            )

        if planned_calls == 0:
            decision = Decision.NO_AI
        elif planned_calls == 1:
            decision = Decision.SINGLE_AGENT
        elif planned_calls == 2:
            decision = Decision.IMPLEMENT_AND_REVIEW
        else:
            decision = Decision.FULL_PIPELINE

        return DecisionResult(
            decision=decision.value,
            recommended_agents={
                "planner":     planner,
                "implementer": implementer,
                "reviewer":    reviewer,
            },
            planned_ai_calls=planned_calls,
            reasons=reasons,
            skipped_steps=skipped,
            safe_to_continue=True,
        )


# ---------------------------------------------------------------------------
# Convenience: build inputs from the orchestrator's existing reports
# ---------------------------------------------------------------------------

def build_inputs_from_reports(
    *,
    task_text: str,
    task_type: str,
    risk_report: dict | None,
    policy_report: dict | None,
    security_report: dict | None,
    selected_files_count: int,
    estimated_prompt_chars: int,
    max_total_chars: int,
    max_ai_calls: int,
    planner_agent: str,
    implementer_agent: str,
    reviewer_agent: str,
    dry_run: bool,
) -> DecisionInputs:
    risk = (risk_report or {}).get("risk_level") or "UNKNOWN"

    require_review = bool(
        (policy_report or {}).get("require_review")
        or (risk_report or {}).get("review_required")
    )
    require_tests = bool(
        (policy_report or {}).get("require_tests")
        or (risk_report or {}).get("tests_required")
    )
    require_human_approval = bool(
        (policy_report or {}).get("require_human_approval")
        or (risk_report or {}).get("human_approval_required")
    )
    safe_to_continue = bool(
        # security_report may be None (e.g. before scan) — assume safe in
        # that case so we don't refuse to recommend anything.
        (security_report or {}).get("safe_to_continue", True)
    )

    return DecisionInputs(
        task_text=task_text,
        task_type=task_type,
        risk_level=risk,
        require_review=require_review,
        require_tests=require_tests,
        require_human_approval=require_human_approval,
        safe_to_continue=safe_to_continue,
        selected_files_count=selected_files_count,
        estimated_prompt_chars=estimated_prompt_chars,
        max_total_chars=max_total_chars,
        max_ai_calls=max_ai_calls,
        planner_agent=planner_agent,
        implementer_agent=implementer_agent,
        reviewer_agent=reviewer_agent,
        dry_run=dry_run,
    )


def decide(inputs: DecisionInputs) -> DecisionResult:
    """Module-level convenience wrapper."""
    return DecisionEngine().decide(inputs)


DECISION_ARTIFACT_NAME: str = "decision_report.json"

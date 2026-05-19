"""The orchestrator wires every step of the AgentForge workflow together.

Workflow (solve):
  1. scan repo (local)
  2. classify task (local)
  3. build minimal relevant context (local)
  4. planner agent -> plan
  5. create git branch
  6. implementation agent -> code edits
  7. run tests (local)
  8. reviewer agent -> JSON review (sees only the diff)
  9. optional single revision loop
 10. write final summary
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .agents import Agent, AgentResponse, ClaudeAgent, CodexAgent, LocalAgent
from .agents.base import AgentUnavailable
from .budget import BudgetExceeded, BudgetManager
from .config import Config
from .context_builder import BuiltContext, build_context, summarize_repo
from .logger import RunLogger
from .prompts.implementation_prompt import build_implementation_prompt
from .prompts.planning_prompt import build_planning_prompt
from .prompts.review_prompt import build_review_prompt
from .task_classifier import Classification, classify
from .tools import diff_tools, git_tools
from .tools.file_scanner import RepoSummary
from .tools.test_runner import TestResult


ApprovalFn = Callable[[str], bool]


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    task: str
    classification: dict
    plan: str
    branch: str | None
    diff_stats: dict
    test_passed: bool | None
    review: dict | None
    budget: dict
    final_summary: str
    aborted_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "task": self.task,
            "classification": self.classification,
            "plan_chars": len(self.plan),
            "branch": self.branch,
            "diff_stats": self.diff_stats,
            "test_passed": self.test_passed,
            "review": self.review,
            "budget": self.budget,
            "aborted_reason": self.aborted_reason,
        }


@dataclass
class Orchestrator:
    config: Config
    cwd: Path = field(default_factory=lambda: Path("."))
    approval_fn: ApprovalFn | None = None      # called for risky decisions
    on_event: Callable[[str], None] | None = None

    # --- agent factory -------------------------------------------------
    def _agent(self, kind: str) -> Agent:
        if kind == "claude":
            return ClaudeAgent(command=self.config.claude_command, cwd=self.cwd)
        if kind == "codex":
            return CodexAgent(command=self.config.codex_command, cwd=self.cwd)
        if kind == "local":
            return LocalAgent(config=self.config, cwd=self.cwd)
        raise ValueError(f"unknown agent kind: {kind}")

    def _emit(self, msg: str) -> None:
        if self.on_event:
            self.on_event(msg)

    # --- shared steps --------------------------------------------------
    def _scan(self, local: LocalAgent) -> RepoSummary:
        self._emit("Scanning repo...")
        return local.scan_repo()

    def _classify(self, task: str) -> Classification:
        defaults = (
            self.config.agents.planner,
            self.config.agents.implementer,
            self.config.agents.reviewer,
        )
        return classify(task, defaults)

    def _call_agent(
        self,
        budget: BudgetManager,
        agent: Agent,
        prompt: str,
        role: str,
    ) -> AgentResponse:
        budget.record_call(agent=agent.name, role=role, prompt_chars=len(prompt))
        self._emit(f"[{agent.name}] role={role} prompt={len(prompt)} chars")
        resp = agent.run(prompt, role=role)
        if not resp.ok:
            self._emit(f"[{agent.name}] returned error (exit={resp.exit_code}): {resp.error}")
        return resp

    # --- plan-only flow -----------------------------------------------
    def plan_only(self, task: str) -> RunResult:
        logger = RunLogger()
        budget = BudgetManager(self.config)
        local = LocalAgent(config=self.config, cwd=self.cwd)

        summary = self._scan(local)
        classification = self._classify(task)

        logger.save_task({"task": task, "mode": "plan"})
        logger.save_repo_summary(summary.to_dict())

        context = build_context(local, summary, task, self.config)
        planner_kind = classification.routing.planner or self.config.agents.planner
        planner = self._agent(planner_kind)

        prompt = build_planning_prompt(
            task=task,
            task_type=classification.task_type.value,
            repo_summary=context.repo_summary_text,
            relevant_files=context.selected_paths,
        )

        plan = ""
        aborted = None
        try:
            resp = self._call_agent(budget, planner, prompt, role="planner")
            if resp.ok:
                plan = resp.output
            else:
                aborted = resp.error or f"planner exit {resp.exit_code}"
        except (BudgetExceeded, AgentUnavailable) as exc:
            aborted = str(exc)

        logger.save_plan(plan or f"(planning failed: {aborted})")
        logger.save_budget(budget.snapshot().to_dict())

        final = self._write_summary(
            logger=logger, task=task, classification=classification, branch=None,
            diff_text="", diff_stats={"files_changed": 0, "additions": 0, "deletions": 0, "file_list": []},
            test_result=None, review=None, budget=budget, plan=plan, mode="plan",
            aborted=aborted,
        )

        return RunResult(
            run_id=logger.run_id, run_dir=logger.dir, task=task,
            classification=classification.to_dict(), plan=plan, branch=None,
            diff_stats={"files_changed": 0, "additions": 0, "deletions": 0, "file_list": []},
            test_passed=None, review=None, budget=budget.snapshot().to_dict(),
            final_summary=final, aborted_reason=aborted,
        )

    # --- full solve flow -----------------------------------------------
    def solve(self, task: str) -> RunResult:
        logger = RunLogger()
        budget = BudgetManager(self.config)
        local = LocalAgent(config=self.config, cwd=self.cwd)

        summary = self._scan(local)
        classification = self._classify(task)
        logger.save_task({"task": task, "mode": "solve", "classification": classification.to_dict()})
        logger.save_repo_summary(summary.to_dict())

        context = build_context(local, summary, task, self.config)
        self._emit(
            f"Context: {len(context.selected_files)} files, "
            f"{context.total_chars} chars (truncated={context.truncated})"
        )

        # Step 1 — Plan (if routing calls for one).
        plan = ""
        aborted: str | None = None
        if classification.routing.planner:
            try:
                planner = self._agent(classification.routing.planner)
                planning_prompt = build_planning_prompt(
                    task=task,
                    task_type=classification.task_type.value,
                    repo_summary=context.repo_summary_text,
                    relevant_files=context.selected_paths,
                )
                resp = self._call_agent(budget, planner, planning_prompt, role="planner")
                if resp.ok:
                    plan = resp.output
                else:
                    aborted = resp.error or f"planner exit {resp.exit_code}"
            except (BudgetExceeded, AgentUnavailable) as exc:
                aborted = str(exc)
        else:
            plan = "(no planning step — task type routed straight to implementation)"

        logger.save_plan(plan)

        if aborted:
            return self._finalize_aborted(
                logger, budget, task, classification, plan, branch=None,
                aborted=aborted, diff_text="", test_result=None, review=None,
            )

        # Step 2 — git branch.
        branch = self._maybe_create_branch(task)

        # Step 3 — Implementation.
        try:
            implementer = self._agent(classification.routing.implementer or self.config.agents.implementer)
            impl_prompt = build_implementation_prompt(
                task=task,
                plan=plan,
                files=context.selected_files,
                max_chars_per_file=self.config.max_chars_per_file,
                secret_files=self.config.secret_files,
            )
            impl_resp = self._call_agent(budget, implementer, impl_prompt, role="implementer")
            if not impl_resp.ok:
                aborted = impl_resp.error or f"implementer exit {impl_resp.exit_code}"
        except (BudgetExceeded, AgentUnavailable) as exc:
            aborted = str(exc)

        if aborted:
            return self._finalize_aborted(
                logger, budget, task, classification, plan, branch=branch,
                aborted=aborted, diff_text="", test_result=None, review=None,
            )

        # Step 4 — tests + diff.
        test_result = local.run_tests()
        logger.save_test_result(test_result.to_text())

        diff_text = local.git_diff()
        logger.save_diff(diff_text)
        stats = diff_tools.parse_diff_stats(diff_text).to_dict()

        # Step 5 — review (one optional revision loop).
        review_json: dict | None = None
        if self._needs_review(classification, test_result, stats):
            review_json = self._review(budget, classification, task, plan, diff_text, test_result, logger)

            if (
                review_json
                and review_json.get("status") == "needs_changes"
                and budget.can_start_review_loop()
            ):
                budget.record_review_loop()
                self._emit("Review requested changes — running one revision loop.")
                try:
                    implementer = self._agent(classification.routing.implementer or self.config.agents.implementer)
                    revision_prompt = self._build_revision_prompt(task, plan, diff_text, review_json)
                    rev_resp = self._call_agent(budget, implementer, revision_prompt, role="implementer-revision")
                    if rev_resp.ok:
                        test_result = local.run_tests()
                        logger.save_test_result(test_result.to_text())
                        diff_text = local.git_diff()
                        logger.save_diff(diff_text)
                        stats = diff_tools.parse_diff_stats(diff_text).to_dict()
                        review_json = self._review(budget, classification, task, plan, diff_text, test_result, logger)
                except (BudgetExceeded, AgentUnavailable) as exc:
                    self._emit(f"Revision loop skipped: {exc}")

        logger.save_budget(budget.snapshot().to_dict())

        final = self._write_summary(
            logger=logger, task=task, classification=classification, branch=branch,
            diff_text=diff_text, diff_stats=stats, test_result=test_result,
            review=review_json, budget=budget, plan=plan, mode="solve", aborted=None,
        )

        return RunResult(
            run_id=logger.run_id,
            run_dir=logger.dir,
            task=task,
            classification=classification.to_dict(),
            plan=plan,
            branch=branch,
            diff_stats=stats,
            test_passed=test_result.passed if test_result else None,
            review=review_json,
            budget=budget.snapshot().to_dict(),
            final_summary=final,
        )

    # --- review-only flow ---------------------------------------------
    def review_diff_only(self, task: str | None = None) -> RunResult:
        logger = RunLogger()
        budget = BudgetManager(self.config)
        local = LocalAgent(config=self.config, cwd=self.cwd)

        if not git_tools.is_git_repo(self.cwd):
            raise RuntimeError("not a git repo; cannot review diff")
        diff_text = local.git_diff()
        if not diff_text.strip():
            self._emit("No diff to review.")
        logger.save_diff(diff_text)

        reviewer = self._agent(self.config.agents.reviewer)
        prompt = build_review_prompt(
            task=task or "(no task description supplied)",
            plan="(plan not provided to review-only mode)",
            diff=diff_text,
            test_result="(tests not run in review-only mode)",
        )

        review_json: dict | None = None
        aborted = None
        try:
            resp = self._call_agent(budget, reviewer, prompt, role="reviewer")
            if resp.ok:
                review_json = self._parse_review_json(resp.output)
            else:
                aborted = resp.error or f"reviewer exit {resp.exit_code}"
        except (BudgetExceeded, AgentUnavailable) as exc:
            aborted = str(exc)

        if review_json:
            logger.save_review(review_json)
        logger.save_budget(budget.snapshot().to_dict())

        stats = diff_tools.parse_diff_stats(diff_text).to_dict()
        final = self._write_summary(
            logger=logger, task=task or "", classification=None, branch=None,
            diff_text=diff_text, diff_stats=stats, test_result=None,
            review=review_json, budget=budget, plan="", mode="review", aborted=aborted,
        )
        return RunResult(
            run_id=logger.run_id, run_dir=logger.dir, task=task or "",
            classification={}, plan="", branch=None, diff_stats=stats,
            test_passed=None, review=review_json,
            budget=budget.snapshot().to_dict(), final_summary=final,
            aborted_reason=aborted,
        )

    # --- helpers ------------------------------------------------------
    def _maybe_create_branch(self, task: str) -> str | None:
        if not git_tools.is_git_repo(self.cwd):
            self._emit("Not a git repo — skipping branch creation.")
            return None
        if git_tools.has_uncommitted_changes(self.cwd):
            self._emit(
                "Uncommitted changes detected. AgentForge will work on the current "
                "branch without creating a new one. Commit or stash to enable branching."
            )
            return git_tools.current_branch(self.cwd)
        slug = git_tools.slugify(task)
        branch = f"{self.config.branch_prefix}{slug}"
        try:
            git_tools.create_branch(branch, self.cwd)
            self._emit(f"Created branch {branch}")
            return branch
        except git_tools.GitError as exc:
            self._emit(f"Could not create branch {branch}: {exc}")
            return git_tools.current_branch(self.cwd)

    def _needs_review(self, classification: Classification, test_result: TestResult, stats: dict) -> bool:
        if classification.routing.require_review:
            return True
        if not test_result.passed:
            return True
        risky = any(
            any(s in f.lower() for s in self.config.risky_files)
            for f in stats.get("file_list", [])
        )
        return risky

    def _review(
        self,
        budget: BudgetManager,
        classification: Classification,
        task: str,
        plan: str,
        diff_text: str,
        test_result: TestResult,
        logger: RunLogger,
    ) -> dict | None:
        reviewer_kind = classification.routing.reviewer or self.config.agents.reviewer
        reviewer = self._agent(reviewer_kind)
        # Cap diff size for reviewer to avoid runaway prompts.
        max_diff_chars = max(2000, self.config.max_total_chars // 2)
        capped_diff = diff_tools.truncate_diff(diff_text, max_diff_chars)
        prompt = build_review_prompt(
            task=task, plan=plan, diff=capped_diff,
            test_result=test_result.to_text(),
        )
        try:
            resp = self._call_agent(budget, reviewer, prompt, role="reviewer")
        except (BudgetExceeded, AgentUnavailable) as exc:
            self._emit(f"Review skipped: {exc}")
            return None
        if not resp.ok:
            return None
        parsed = self._parse_review_json(resp.output)
        if parsed:
            logger.save_review(parsed)
        return parsed

    @staticmethod
    def _parse_review_json(text: str) -> dict | None:
        if not text:
            return None
        # Reviewers occasionally wrap JSON in code fences; strip them.
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract the first JSON object from the text.
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return {"status": "needs_changes", "risk_level": "medium",
                        "issues": [], "summary": "reviewer returned non-JSON output",
                        "raw": text[:2000]}
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {"status": "needs_changes", "risk_level": "medium",
                        "issues": [], "summary": "reviewer returned malformed JSON",
                        "raw": text[:2000]}

    @staticmethod
    def _build_revision_prompt(task: str, plan: str, diff: str, review: dict) -> str:
        issues = review.get("issues") or []
        rendered_issues = "\n".join(
            f"- {i.get('file', '?')}: {i.get('problem', '')} -> {i.get('suggested_fix', '')}"
            for i in issues
        ) or "(no specific issues — see summary)"
        return (
            f"Reviewer asked for changes. Apply minimal edits to address each issue.\n\n"
            f"# Task\n{task}\n\n"
            f"# Plan\n{plan}\n\n"
            f"# Reviewer summary\n{review.get('summary', '')}\n\n"
            f"# Issues to fix\n{rendered_issues}\n\n"
            f"# Current diff (for context)\n```diff\n{diff[:4000]}\n```\n"
            f"Make the smallest possible changes to resolve the issues. Do not refactor."
        )

    def _write_summary(
        self,
        *,
        logger: RunLogger,
        task: str,
        classification: Classification | None,
        branch: str | None,
        diff_text: str,
        diff_stats: dict,
        test_result: TestResult | None,
        review: dict | None,
        budget: BudgetManager,
        plan: str,
        mode: str,
        aborted: str | None,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# AgentForge run {logger.run_id}")
        lines.append("")
        lines.append(f"- mode: {mode}")
        lines.append(f"- task: {task}")
        if classification:
            lines.append(f"- task_type: {classification.task_type.value} "
                         f"(confidence={classification.confidence:.2f})")
        if branch:
            lines.append(f"- branch: {branch}")
        if aborted:
            lines.append(f"- aborted: {aborted}")
        lines.append("")
        if plan:
            lines.append("## Plan")
            lines.append(plan)
            lines.append("")
        lines.append("## Diff stats")
        lines.append(f"- files changed: {diff_stats.get('files_changed', 0)}")
        lines.append(f"- +{diff_stats.get('additions', 0)} / -{diff_stats.get('deletions', 0)} lines")
        if diff_stats.get("file_list"):
            for f in diff_stats["file_list"]:
                lines.append(f"  - {f}")
        lines.append("")
        if test_result is not None:
            lines.append("## Tests")
            lines.append(f"- command: `{test_result.command}`")
            lines.append(f"- passed: {test_result.passed}")
            lines.append("")
        if review:
            lines.append("## Review")
            lines.append(f"- status: {review.get('status', 'unknown')}")
            lines.append(f"- risk: {review.get('risk_level', 'unknown')}")
            lines.append(f"- summary: {review.get('summary', '')}")
            if review.get("issues"):
                lines.append("- issues:")
                for issue in review["issues"]:
                    lines.append(f"  - **{issue.get('file', '?')}**: {issue.get('problem', '')}")
            lines.append("")
        snap = budget.snapshot()
        lines.append("## Budget")
        lines.append(f"- ai_calls: {snap.ai_calls}/{snap.max_ai_calls}")
        lines.append(f"- review_loops: {snap.review_loops}/{snap.max_review_loops}")
        lines.append(f"- chars_sent: {snap.chars_sent}/{snap.max_total_chars}")

        text = "\n".join(lines)
        logger.save_final_summary(text)
        return text

    def _finalize_aborted(
        self,
        logger: RunLogger,
        budget: BudgetManager,
        task: str,
        classification: Classification,
        plan: str,
        branch: str | None,
        aborted: str,
        diff_text: str,
        test_result: TestResult | None,
        review: dict | None,
    ) -> RunResult:
        logger.save_budget(budget.snapshot().to_dict())
        stats = diff_tools.parse_diff_stats(diff_text).to_dict() if diff_text else {
            "files_changed": 0, "additions": 0, "deletions": 0, "file_list": [],
        }
        final = self._write_summary(
            logger=logger, task=task, classification=classification, branch=branch,
            diff_text=diff_text, diff_stats=stats, test_result=test_result,
            review=review, budget=budget, plan=plan, mode="solve", aborted=aborted,
        )
        return RunResult(
            run_id=logger.run_id, run_dir=logger.dir, task=task,
            classification=classification.to_dict(), plan=plan, branch=branch,
            diff_stats=stats, test_passed=test_result.passed if test_result else None,
            review=review, budget=budget.snapshot().to_dict(),
            final_summary=final, aborted_reason=aborted,
        )

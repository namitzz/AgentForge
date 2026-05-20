"""The orchestrator wires every step of the AgentForge workflow together.

Workflow (solve):
  1. scan repo (local)
  2. classify task (local)
  3. build minimal relevant context (local)
  4. policy check on selected files (local)
  5. planner agent -> plan
  6. create git branch
  7. implementation agent -> code edits
  8. run tests (local)
  9. reviewer agent -> JSON review (sees only the diff)
 10. optional single revision loop
 11. write final summary

Every step that would call an external agent first records cost in the
BudgetManager and writes a corresponding artifact under .agentforge/runs/.

When ``dry_run=True``, no agent CLI is invoked, no branch is created, and no
files are modified. The run still produces all artifacts (with placeholders
explaining what was skipped) so it's a faithful preview of what a real run
would do.
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
from .policy_engine import PolicyEngine, PolicyReport
from .risk_engine import RiskEngine, RiskLevel, RiskReport
from .run_artifacts import RunManifest
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
    policy_report: dict | None = None
    risk_report: dict | None = None
    dry_run: bool = False
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
            "policy_report": self.policy_report,
            "risk_report": self.risk_report,
            "dry_run": self.dry_run,
            "budget": self.budget,
            "aborted_reason": self.aborted_reason,
        }


@dataclass
class Orchestrator:
    config: Config
    cwd: Path = field(default_factory=lambda: Path("."))
    approval_fn: ApprovalFn | None = None
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

    def _policy_engine(self) -> PolicyEngine:
        return PolicyEngine.from_config_list(self.config.policies)

    def _build_manifest(
        self,
        *,
        logger: RunLogger,
        mode: str,
        task: str,
        dry_run: bool,
        classification: Classification | None,
    ) -> RunManifest:
        if classification is not None:
            workflow = {
                "planner": classification.routing.planner,
                "implementer": (
                    classification.routing.implementer or self.config.agents.implementer
                ),
                "reviewer": (
                    classification.routing.reviewer or self.config.agents.reviewer
                ),
            }
            classification_dict: dict | None = classification.to_dict()
        else:
            workflow = {
                "planner": None,
                "implementer": None,
                "reviewer": self.config.agents.reviewer,
            }
            classification_dict = None

        manifest = RunManifest(
            run_id=logger.run_id,
            mode=mode,
            task=task,
            dry_run=dry_run,
            agent_workflow=workflow,
            classification=classification_dict,
        )
        logger.save_task(manifest.to_dict())
        return manifest

    def _finalize_manifest(
        self,
        logger: RunLogger,
        manifest: RunManifest,
        budget: BudgetManager,
    ) -> None:
        snap = budget.snapshot()
        manifest.finalize(
            stopped_early=snap.stopped_early,
            stop_reason=snap.stop_reason,
        )
        logger.save_task(manifest.to_dict())

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

    @staticmethod
    def _estimate_reviewer_chars(diff_chars: int) -> int:
        # Reviewer prompt has the diff + plan + task + system text. Diff is
        # the dominant variable. Add a fixed overhead.
        return diff_chars + 2_000

    def _estimate_budget(
        self,
        *,
        classification: Classification | None,
        planning_prompt_chars: int,
        impl_prompt_chars: int,
        mode: str,
        force_review: bool,
        review_loops_possible: int,
        avg_diff_chars: int = 5_000,
    ) -> tuple[int, int]:
        """Return (planned_ai_calls, planned_chars_sent) for this run."""
        planned_calls = 0
        planned_chars = 0

        # Plan-only flow: one call to the planner if routing wants one.
        if mode == "plan":
            if classification and classification.routing.planner:
                planned_calls += 1
                planned_chars += planning_prompt_chars
            return planned_calls, planned_chars

        # Review-only flow.
        if mode == "review":
            planned_calls += 1
            planned_chars += self._estimate_reviewer_chars(avg_diff_chars)
            return planned_calls, planned_chars

        # Solve flow.
        if classification and classification.routing.planner:
            planned_calls += 1
            planned_chars += planning_prompt_chars

        # Implementation always runs.
        planned_calls += 1
        planned_chars += impl_prompt_chars

        # Reviewer if classification or policy/risk force it.
        reviewer_planned = force_review or bool(
            classification and classification.routing.reviewer
        )
        if reviewer_planned:
            planned_calls += 1
            planned_chars += self._estimate_reviewer_chars(avg_diff_chars)

        # Each allowed review loop = up to 2 extra calls (revision + re-review).
        if reviewer_planned and review_loops_possible > 0:
            planned_calls += review_loops_possible * 2
            planned_chars += review_loops_possible * (
                impl_prompt_chars + self._estimate_reviewer_chars(avg_diff_chars)
            )

        return planned_calls, planned_chars

    def _emit_planned_workflow(
        self,
        mode: str,
        classification: Classification | None,
    ) -> None:
        """For dry-run: announce the steps the run *would* take, in order."""
        steps: list[str] = ["Local scan"]
        if mode != "review":
            steps.append("Task classification")
            steps.append("Context selection")
        steps.append("Policy check")
        steps.append("Risk assessment")

        if mode == "plan":
            planner = classification.routing.planner if classification else None
            if planner:
                steps.append(f"{planner.capitalize()} planning prompt would be generated")
        elif mode == "solve":
            planner = classification.routing.planner if classification else None
            implementer = (
                classification.routing.implementer if classification else None
            ) or self.config.agents.implementer
            reviewer = (
                classification.routing.reviewer if classification else None
            ) or self.config.agents.reviewer
            if planner:
                steps.append(f"{planner.capitalize()} planning prompt would be generated")
            steps.append(f"{implementer.capitalize()} implementation prompt would be generated")
            steps.append("Tests would run")
            if reviewer:
                steps.append(f"{reviewer.capitalize()} diff review prompt would be generated")
        elif mode == "review":
            steps = ["Read current git diff", "Risk assessment", "Policy check"]
            steps.append(
                f"{self.config.agents.reviewer.capitalize()} diff review prompt would be generated"
            )

        self._emit("Dry run: enabled")
        self._emit("No external agents will be called.")
        self._emit("No files will be modified.")
        self._emit("")
        self._emit("Planned workflow:")
        for i, step in enumerate(steps, 1):
            self._emit(f"  {i}. {step}")
        self._emit("")

    def _assess_risk(
        self,
        task: str,
        selected_paths: list[str],
        logger: RunLogger,
    ) -> RiskReport:
        report = RiskEngine().assess(task, selected_paths)
        logger.save_risk_report(report.to_dict())
        for line in report.human_summary():
            self._emit(line)
        return report

    def _apply_policies(
        self,
        selected_paths: list[str],
    ) -> tuple[list[str], PolicyReport]:
        engine = self._policy_engine()
        kept, blocked = engine.filter_blocked(selected_paths)
        report = engine.evaluate(selected_paths)
        # Make sure blocked hits from filter_blocked are reflected in report too.
        seen = {(h.path, h.policy) for h in report.blocked_files}
        for hit in blocked:
            if (hit.path, hit.policy) not in seen:
                report.blocked_files.append(hit)
        for line in report.human_summary():
            self._emit(line)
        return kept, report

    # --- plan-only flow -----------------------------------------------
    def plan_only(self, task: str, dry_run: bool = False) -> RunResult:
        logger = RunLogger()
        budget = BudgetManager(self.config)
        local = LocalAgent(config=self.config, cwd=self.cwd)

        summary = self._scan(local)
        classification = self._classify(task)

        if dry_run:
            self._emit_planned_workflow(mode="plan", classification=classification)

        manifest = self._build_manifest(
            logger=logger, mode="plan", task=task, dry_run=dry_run,
            classification=classification,
        )
        logger.save_repo_summary(summary.to_dict())

        context = build_context(local, summary, task, self.config)
        kept_paths, policy_report = self._apply_policies(context.selected_paths)
        context = self._drop_blocked_from_context(context, kept_paths)
        budget.record_files_sent(len(context.selected_files))
        logger.save_selected_files([{"path": p, "chars": len(c)} for p, c in context.selected_files])
        logger.save_policy_report(policy_report.to_dict())

        risk_report = self._assess_risk(task, context.selected_paths, logger)

        planner_kind = classification.routing.planner or self.config.agents.planner
        planning_prompt = build_planning_prompt(
            task=task,
            task_type=classification.task_type.value,
            repo_summary=context.repo_summary_text,
            relevant_files=context.selected_paths,
        )
        logger.save_prompts({"planner": planning_prompt})

        # Budget estimate (plan-only: just the planner call if routing wants one).
        budget.set_dry_run(dry_run)
        planned_calls, planned_chars = self._estimate_budget(
            classification=classification,
            planning_prompt_chars=len(planning_prompt),
            impl_prompt_chars=0,
            mode="plan",
            force_review=False,
            review_loops_possible=0,
        )
        budget.record_planned(planned_calls, planned_chars)
        for line in budget.snapshot().estimate_summary():
            self._emit(line)
        if not dry_run:
            try:
                budget.enforce_planned_within_caps()
            except BudgetExceeded as exc:
                budget.mark_stopped_early(True, reason=str(exc))
                self._emit(f"Aborting plan: {exc}")

        plan = ""
        aborted: str | None = None
        if dry_run:
            self._emit(
                f"DRY-RUN — would call {planner_kind} as planner with "
                f"{len(planning_prompt)} chars. No call made."
            )
            plan = self._dry_run_plan_placeholder(planner_kind, planning_prompt)
        else:
            try:
                planner = self._agent(planner_kind)
                resp = self._call_agent(budget, planner, planning_prompt, role="planner")
                if resp.ok:
                    plan = resp.output
                else:
                    aborted = resp.error or f"planner exit {resp.exit_code}"
            except (BudgetExceeded, AgentUnavailable) as exc:
                aborted = str(exc)
                self._emit(f"Aborting plan: {exc}. Try `--dry-run` to preview without calling an agent.")

        logger.save_plan(plan or f"(planning failed: {aborted})")
        if aborted:
            budget.mark_stopped_early(True, reason=aborted)
        elif dry_run:
            budget.mark_stopped_early(True, reason="dry-run - no agent calls made")
        logger.save_budget(budget.snapshot().to_dict())
        self._finalize_manifest(logger, manifest, budget)

        final = self._write_summary(
            logger=logger, task=task, classification=classification, branch=None,
            diff_text="", diff_stats={"files_changed": 0, "additions": 0, "deletions": 0, "file_list": []},
            test_result=None, review=None, policy_report=policy_report,
            risk_report=risk_report, budget=budget,
            plan=plan, mode=("plan-dry-run" if dry_run else "plan"), aborted=aborted,
        )

        logger.fill_missing_placeholders(
            reason=("dry-run preview" if dry_run else (aborted or "plan-only mode"))
        )

        return RunResult(
            run_id=logger.run_id, run_dir=logger.dir, task=task,
            classification=classification.to_dict(), plan=plan, branch=None,
            diff_stats={"files_changed": 0, "additions": 0, "deletions": 0, "file_list": []},
            test_passed=None, review=None,
            policy_report=policy_report.to_dict(),
            risk_report=risk_report.to_dict(),
            dry_run=dry_run,
            budget=budget.snapshot().to_dict(),
            final_summary=final, aborted_reason=aborted,
        )

    # --- full solve flow -----------------------------------------------
    def solve(self, task: str, dry_run: bool = False) -> RunResult:
        logger = RunLogger()
        budget = BudgetManager(self.config)
        local = LocalAgent(config=self.config, cwd=self.cwd)

        summary = self._scan(local)
        classification = self._classify(task)

        if dry_run:
            self._emit_planned_workflow(mode="solve", classification=classification)

        manifest = self._build_manifest(
            logger=logger, mode="solve", task=task, dry_run=dry_run,
            classification=classification,
        )
        logger.save_repo_summary(summary.to_dict())

        context = build_context(local, summary, task, self.config)
        kept_paths, policy_report = self._apply_policies(context.selected_paths)
        context = self._drop_blocked_from_context(context, kept_paths)
        budget.record_files_sent(len(context.selected_files))

        self._emit(
            f"Context: {len(context.selected_files)} files, "
            f"{context.total_chars} chars (truncated={context.truncated})"
        )

        logger.save_selected_files([{"path": p, "chars": len(c)} for p, c in context.selected_files])
        logger.save_policy_report(policy_report.to_dict())

        risk_report = self._assess_risk(task, context.selected_paths, logger)

        # Honour policy + risk escalation: force review on even if the classifier wouldn't.
        force_review = policy_report.require_review or risk_report.review_required

        # Surface a clear warning if tests are required by policy or risk but
        # the user has no test command configured.
        tests_required = (
            policy_report.require_tests or risk_report.tests_required
        )
        if tests_required and not (self.config.default_test_command or "").strip():
            self._emit(
                "WARNING: tests are required for this run (policy/risk) but "
                "default_test_command is empty in config.yaml."
            )

        # Combine both sources for the human-approval gate.
        approval_required = (
            policy_report.require_human_approval or risk_report.human_approval_required
        )

        # Honour human approval gate (skipped in dry-run by definition).
        if not dry_run and approval_required:
            if self.approval_fn is None:
                self._emit("Approval gate triggered but no approval_fn is wired.")
            else:
                gate_reason = (
                    "Risk and policy"
                    if (policy_report.require_human_approval and risk_report.human_approval_required)
                    else ("Risk" if risk_report.human_approval_required else "Policy")
                )
                ok = self.approval_fn(
                    f"{gate_reason} requires human approval before continuing. Proceed?"
                )
                if not ok:
                    aborted = "human approval declined"
                    return self._finalize_aborted(
                        logger, budget, task, classification, plan="",
                        branch=None, aborted=aborted, diff_text="",
                        test_result=None, review=None, policy_report=policy_report,
                        risk_report=risk_report, dry_run=dry_run,
                        manifest=manifest,
                    )

        # Build prompts up front so they're recorded even in dry-run.
        planning_prompt = build_planning_prompt(
            task=task,
            task_type=classification.task_type.value,
            repo_summary=context.repo_summary_text,
            relevant_files=context.selected_paths,
        )
        impl_prompt = build_implementation_prompt(
            task=task,
            plan="(filled in after planning)",
            files=context.selected_files,
            max_chars_per_file=self.config.max_chars_per_file,
            secret_files=self.config.secret_files,
        )
        prompts_blob: dict[str, str] = {
            "planner": planning_prompt,
            "implementer_template": impl_prompt,
        }

        # Budget estimate (before any agent call). Always emit, then enforce.
        budget.set_dry_run(dry_run)
        planned_calls, planned_chars = self._estimate_budget(
            classification=classification,
            planning_prompt_chars=len(planning_prompt),
            impl_prompt_chars=len(impl_prompt),
            mode="solve",
            force_review=force_review,
            review_loops_possible=self.config.max_review_loops,
        )
        budget.record_planned(planned_calls, planned_chars)
        for line in budget.snapshot().estimate_summary():
            self._emit(line)
        try:
            if not dry_run:
                budget.enforce_planned_within_caps()
        except BudgetExceeded as exc:
            return self._finalize_aborted(
                logger, budget, task, classification, plan="",
                branch=None, aborted=str(exc), diff_text="",
                test_result=None, review=None, policy_report=policy_report,
                risk_report=risk_report, dry_run=dry_run,
                manifest=manifest,
            )

        # Step 1 — Plan (if routing calls for one).
        plan = ""
        aborted: str | None = None
        planner_kind = classification.routing.planner
        if planner_kind:
            if dry_run:
                self._emit(
                    f"DRY-RUN — would call {planner_kind} as planner with "
                    f"{len(planning_prompt)} chars. No call made."
                )
                plan = self._dry_run_plan_placeholder(planner_kind, planning_prompt)
            else:
                try:
                    planner = self._agent(planner_kind)
                    resp = self._call_agent(budget, planner, planning_prompt, role="planner")
                    if resp.ok:
                        plan = resp.output
                    else:
                        aborted = resp.error or f"planner exit {resp.exit_code}"
                except (BudgetExceeded, AgentUnavailable) as exc:
                    aborted = str(exc)
                    self._emit(f"Planner unavailable: {exc}. Try `--dry-run` to preview the pipeline without calling an agent.")
        else:
            plan = "(no planning step — task type routed straight to implementation)"

        logger.save_plan(plan)
        prompts_blob["implementer"] = build_implementation_prompt(
            task=task,
            plan=plan,
            files=context.selected_files,
            max_chars_per_file=self.config.max_chars_per_file,
            secret_files=self.config.secret_files,
        )
        logger.save_prompts(prompts_blob)

        if aborted:
            budget.mark_stopped_early(True, reason=aborted)
            return self._finalize_aborted(
                logger, budget, task, classification, plan, branch=None,
                aborted=aborted, diff_text="", test_result=None, review=None,
                policy_report=policy_report, risk_report=risk_report, dry_run=dry_run,
                manifest=manifest,
            )

        # Step 2 — git branch (skipped in dry-run).
        branch: str | None = None
        if dry_run:
            self._emit("DRY-RUN — skipping git branch creation.")
        else:
            branch = self._maybe_create_branch(task)

        # Step 3 — Implementation.
        implementer_kind = classification.routing.implementer or self.config.agents.implementer
        if dry_run:
            self._emit(
                f"DRY-RUN — would call {implementer_kind} as implementer with "
                f"{len(prompts_blob['implementer'])} chars. No call made."
            )
            test_result = None
            diff_text = ""
            stats = {"files_changed": 0, "additions": 0, "deletions": 0, "file_list": []}
            review_json: dict | None = None
            budget.mark_stopped_early(True, reason="dry-run - no agent calls made")
        else:
            try:
                implementer = self._agent(implementer_kind)
                impl_resp = self._call_agent(
                    budget, implementer, prompts_blob["implementer"], role="implementer"
                )
                if not impl_resp.ok:
                    aborted = impl_resp.error or f"implementer exit {impl_resp.exit_code}"
            except (BudgetExceeded, AgentUnavailable) as exc:
                aborted = str(exc)
                self._emit(f"Implementer unavailable: {exc}. Try `--dry-run` to preview without calling an agent.")

            if aborted:
                budget.mark_stopped_early(True, reason=aborted)
                return self._finalize_aborted(
                    logger, budget, task, classification, plan, branch=branch,
                    aborted=aborted, diff_text="", test_result=None, review=None,
                    policy_report=policy_report, risk_report=risk_report, dry_run=dry_run,
                    manifest=manifest,
                )

            # Step 4 — tests + diff.
            test_result = local.run_tests()
            logger.save_test_result(test_result.to_text())

            diff_text = local.git_diff()
            logger.save_diff(diff_text)
            stats = diff_tools.parse_diff_stats(diff_text).to_dict()

            # Step 5 — review (one optional revision loop).
            review_json = None
            if self._needs_review(classification, test_result, stats, force_review):
                review_json = self._review(budget, classification, task, plan, diff_text, test_result, logger)

                if (
                    review_json
                    and review_json.get("status") == "needs_changes"
                    and budget.can_start_review_loop()
                ):
                    budget.record_review_loop()
                    self._emit("Review requested changes — running one revision loop.")
                    try:
                        implementer = self._agent(implementer_kind)
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

            # If we made it here without forcing review and tests passed, the run
            # ended on the early-stop path. That's a feature, not stoppage.
            if review_json is None and test_result and test_result.passed:
                self._emit("Tests passed and review wasn't required — early stop (saved an AI call).")
                budget.mark_stopped_early(
                    True, reason="tests passed and review not required"
                )

        logger.save_budget(budget.snapshot().to_dict())
        self._finalize_manifest(logger, manifest, budget)

        final = self._write_summary(
            logger=logger, task=task, classification=classification, branch=branch,
            diff_text=diff_text, diff_stats=stats, test_result=test_result,
            review=review_json, policy_report=policy_report,
            risk_report=risk_report,
            budget=budget, plan=plan,
            mode=("solve-dry-run" if dry_run else "solve"), aborted=None,
        )

        logger.fill_missing_placeholders(
            reason=("dry-run preview - no agent calls made" if dry_run else "step skipped - see final_summary.md")
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
            policy_report=policy_report.to_dict(),
            risk_report=risk_report.to_dict(),
            dry_run=dry_run,
            budget=budget.snapshot().to_dict(),
            final_summary=final,
        )

    # --- review-only flow ---------------------------------------------
    def review_diff_only(self, task: str | None = None, dry_run: bool = False) -> RunResult:
        logger = RunLogger()
        budget = BudgetManager(self.config)
        local = LocalAgent(config=self.config, cwd=self.cwd)

        if not git_tools.is_git_repo(self.cwd):
            raise RuntimeError("not a git repo; cannot review diff")

        if dry_run:
            self._emit_planned_workflow(mode="review", classification=None)

        diff_text = local.git_diff()
        if not diff_text.strip():
            self._emit("No diff to review.")
        logger.save_diff(diff_text)
        manifest = self._build_manifest(
            logger=logger, mode="review", task=(task or ""),
            dry_run=dry_run, classification=None,
        )

        # No file context in review-only mode, so policy evaluation is over an
        # empty set. We still emit a (mostly empty) report for consistency.
        policy_report = self._policy_engine().evaluate([])
        logger.save_policy_report(policy_report.to_dict())

        # Risk scoring runs on the task description (paths are unknown here).
        risk_report = self._assess_risk(task or "", [], logger)

        prompt = build_review_prompt(
            task=task or "(no task description supplied)",
            plan="(plan not provided to review-only mode)",
            diff=diff_text,
            test_result="(tests not run in review-only mode)",
        )
        logger.save_prompts({"reviewer": prompt})

        budget.set_dry_run(dry_run)
        budget.record_planned(ai_calls=1, chars=len(prompt))
        for line in budget.snapshot().estimate_summary():
            self._emit(line)
        if not dry_run:
            try:
                budget.enforce_planned_within_caps()
            except BudgetExceeded as exc:
                budget.mark_stopped_early(True, reason=str(exc))
                self._emit(f"Aborting review: {exc}")

        review_json: dict | None = None
        aborted = None
        if dry_run:
            self._emit(
                f"DRY-RUN — would call {self.config.agents.reviewer} as reviewer with "
                f"{len(prompt)} chars on a {len(diff_text)}-char diff. No call made."
            )
            budget.mark_stopped_early(True)
        else:
            try:
                reviewer = self._agent(self.config.agents.reviewer)
                resp = self._call_agent(budget, reviewer, prompt, role="reviewer")
                if resp.ok:
                    review_json = self._parse_review_json(resp.output)
                else:
                    aborted = resp.error or f"reviewer exit {resp.exit_code}"
            except (BudgetExceeded, AgentUnavailable) as exc:
                aborted = str(exc)
                self._emit(f"Reviewer unavailable: {exc}. Try `--dry-run` to preview.")

        if review_json:
            logger.save_review(review_json)
        if aborted:
            budget.mark_stopped_early(True, reason=aborted)
        elif dry_run:
            budget.mark_stopped_early(True, reason="dry-run - no agent calls made")
        logger.save_budget(budget.snapshot().to_dict())
        self._finalize_manifest(logger, manifest, budget)

        stats = diff_tools.parse_diff_stats(diff_text).to_dict()
        final = self._write_summary(
            logger=logger, task=task or "", classification=None, branch=None,
            diff_text=diff_text, diff_stats=stats, test_result=None,
            review=review_json, policy_report=policy_report,
            risk_report=risk_report,
            budget=budget, plan="",
            mode=("review-dry-run" if dry_run else "review"), aborted=aborted,
        )

        logger.fill_missing_placeholders(
            reason=("dry-run preview — no agent calls made" if dry_run else "review-only mode")
        )

        return RunResult(
            run_id=logger.run_id, run_dir=logger.dir, task=task or "",
            classification={}, plan="", branch=None, diff_stats=stats,
            test_passed=None, review=review_json,
            policy_report=policy_report.to_dict(),
            risk_report=risk_report.to_dict(),
            dry_run=dry_run,
            budget=budget.snapshot().to_dict(), final_summary=final,
            aborted_reason=aborted,
        )

    # --- helpers ------------------------------------------------------
    @staticmethod
    def _drop_blocked_from_context(context: BuiltContext, kept_paths: list[str]) -> BuiltContext:
        if len(kept_paths) == len(context.selected_paths):
            return context
        kept_set = set(kept_paths)
        kept_files = [(p, c) for p, c in context.selected_files if p in kept_set]
        total = sum(len(c) for _, c in kept_files)
        return BuiltContext(
            repo_summary_text=context.repo_summary_text,
            selected_files=kept_files,
            selected_paths=[p for p, _ in kept_files],
            total_chars=total,
            truncated=context.truncated,
        )

    @staticmethod
    def _dry_run_plan_placeholder(planner_kind: str, prompt: str) -> str:
        return (
            f"(dry-run preview — no plan generated)\n\n"
            f"Would call planner: **{planner_kind}**\n"
            f"Prompt size: {len(prompt)} chars\n"
        )

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

    def _needs_review(
        self,
        classification: Classification,
        test_result: TestResult,
        stats: dict,
        force_review: bool = False,
    ) -> bool:
        if force_review:
            return True
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
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
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
        policy_report: PolicyReport | None,
        risk_report: RiskReport | None,
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
        if risk_report:
            lines.append("## Risk")
            for ln in risk_report.human_summary():
                lines.append(ln)
            lines.append("")
        if policy_report:
            lines.append("## Policy")
            for ln in policy_report.human_summary():
                lines.append(ln)
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
        for ln in snap.human_summary():
            lines.append(ln)

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
        policy_report: PolicyReport | None = None,
        risk_report: RiskReport | None = None,
        dry_run: bool = False,
        manifest: RunManifest | None = None,
    ) -> RunResult:
        budget.mark_stopped_early(True, reason=aborted)
        logger.save_budget(budget.snapshot().to_dict())
        if manifest is not None:
            self._finalize_manifest(logger, manifest, budget)
        stats = diff_tools.parse_diff_stats(diff_text).to_dict() if diff_text else {
            "files_changed": 0, "additions": 0, "deletions": 0, "file_list": [],
        }
        final = self._write_summary(
            logger=logger, task=task, classification=classification, branch=branch,
            diff_text=diff_text, diff_stats=stats, test_result=test_result,
            review=review, policy_report=policy_report,
            risk_report=risk_report,
            budget=budget, plan=plan, mode="solve", aborted=aborted,
        )
        logger.fill_missing_placeholders(reason=aborted)
        return RunResult(
            run_id=logger.run_id, run_dir=logger.dir, task=task,
            classification=classification.to_dict() if classification else {},
            plan=plan, branch=branch,
            diff_stats=stats, test_passed=test_result.passed if test_result else None,
            review=review,
            policy_report=policy_report.to_dict() if policy_report else None,
            risk_report=risk_report.to_dict() if risk_report else None,
            dry_run=dry_run,
            budget=budget.snapshot().to_dict(),
            final_summary=final, aborted_reason=aborted,
        )

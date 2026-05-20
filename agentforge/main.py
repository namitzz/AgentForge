"""AgentForge CLI entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import DEFAULT_CONFIG_PATH, load_config, write_default_config
from .logger import RUNS_ROOT, latest_run_dir
from .orchestrator import Orchestrator, RunResult
from .tools.test_runner import run_tests


app = typer.Typer(
    add_completion=False,
    help="AgentForge — cost-aware control plane for Claude, Codex, and AI coding agents.",
    no_args_is_help=True,
)

console = Console()


def _dry_run_banner() -> None:
    """Spec-format banner shown at the top of any --dry-run command."""
    console.print(Panel.fit(
        "[yellow]Dry run: enabled[/yellow]\n"
        "No external agents will be called.\n"
        "No files will be modified.",
        title="AgentForge",
        border_style="yellow",
    ))


def _load(config_path: Path) -> Orchestrator:
    cfg = load_config(config_path)
    return Orchestrator(
        config=cfg,
        cwd=Path("."),
        on_event=lambda msg: console.print(f"[dim]- {msg}[/dim]"),
        approval_fn=lambda msg: typer.confirm(msg, default=False),
    )


@app.command()
def init(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Where to write config.yaml"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config.yaml"),
) -> None:
    """Create config.yaml and the .agentforge/ directory."""
    cfg_path = write_default_config(config_path, overwrite=force)
    forge_dir = Path(".agentforge")
    (forge_dir / "runs").mkdir(parents=True, exist_ok=True)
    console.print(f"[green]OK[/green] config at {cfg_path}")
    console.print(f"[green]OK[/green] runs directory at {forge_dir / 'runs'}")
    console.print("Edit config.yaml to point at your Claude / Codex CLIs.")


@app.command()
def plan(
    task: str = typer.Argument(..., help="Task description in quotes."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the run without calling any agent."),
) -> None:
    """Produce an implementation plan without changing any files."""
    orch = _load(config_path)
    if dry_run:
        _dry_run_banner()
    result = orch.plan_only(task, dry_run=dry_run)
    _print_result(result, show_plan=True)


@app.command()
def solve(
    task: str = typer.Argument(..., help="Task description in quotes."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the run without calling any agent or creating a branch."),
) -> None:
    """Run the full plan -> implement -> test -> review workflow."""
    orch = _load(config_path)
    cfg = orch.config
    if dry_run:
        _dry_run_banner()
    console.print(Panel.fit(
        f"[bold]Task:[/bold] {task}\n"
        f"[bold]Planner:[/bold] {cfg.agents.planner}    "
        f"[bold]Implementer:[/bold] {cfg.agents.implementer}    "
        f"[bold]Reviewer:[/bold] {cfg.agents.reviewer}\n"
        f"[bold]Budget:[/bold] {cfg.max_ai_calls_per_run} calls, "
        f"{cfg.max_total_chars} chars, {cfg.max_review_loops} review loop(s)",
        title="AgentForge solve",
    ))
    if not yes and not dry_run:
        if not typer.confirm("Proceed?", default=True):
            raise typer.Exit(code=1)
    result = orch.solve(task, dry_run=dry_run)
    _print_result(result, show_plan=True)


@app.command()
def review(
    task: str = typer.Option("", "--task", help="Optional task description for context."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the review without calling the reviewer."),
) -> None:
    """Review the current git diff only (no full-repo context sent)."""
    orch = _load(config_path)
    if dry_run:
        _dry_run_banner()
    result = orch.review_diff_only(task or None, dry_run=dry_run)
    _print_result(result, show_plan=False)


@app.command()
def test(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
) -> None:
    """Run the configured test command."""
    cfg = load_config(config_path)
    console.print(f"[dim]$ {cfg.default_test_command}[/dim]")
    result = run_tests(cfg.default_test_command, cwd=Path("."))
    if result.stdout:
        console.print(result.stdout)
    if result.stderr:
        console.print(f"[red]{result.stderr}[/red]")
    console.print(f"[{'green' if result.passed else 'red'}]"
                  f"exit_code={result.exit_code}[/]")
    raise typer.Exit(code=0 if result.passed else result.exit_code)


@app.command()
def status(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
) -> None:
    """Show the most recent run, budget used, changed files, and review status."""
    cfg = load_config(config_path)
    run_dir = latest_run_dir()
    if not run_dir:
        console.print("[yellow]No runs yet.[/yellow] Try: agentforge solve \"...\"")
        return

    console.print(Panel.fit(f"latest run: [bold]{run_dir.name}[/bold]"))

    summary_md = (run_dir / "final_summary.md")
    if summary_md.exists():
        console.print(summary_md.read_text(encoding="utf-8"))

    budget_path = run_dir / "budget.json"
    if budget_path.exists():
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        if not budget.get("placeholder"):
            table = Table(title="Budget", show_header=True)
            for k in budget.keys():
                table.add_column(k)
            table.add_row(*[str(v) for v in budget.values()])
            console.print(table)

    risk_path = run_dir / "risk_report.json"
    if risk_path.exists():
        risk = json.loads(risk_path.read_text(encoding="utf-8"))
        if not risk.get("placeholder"):
            color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}.get(
                risk.get("risk_level"), "white"
            )
            console.print(Panel.fit(
                f"[{color}]level: {risk.get('risk_level')}[/{color}]\n"
                f"score: {risk.get('score')}/100\n"
                f"review required: {risk.get('review_required')}\n"
                f"human approval: {risk.get('human_approval_required')}",
                title="Risk",
            ))

    policy_path = run_dir / "policy_report.json"
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if not policy.get("placeholder"):
            console.print(Panel.fit(
                f"review required: {policy.get('require_review')}\n"
                f"tests required: {policy.get('require_tests')}\n"
                f"human approval: {policy.get('require_human_approval')}\n"
                f"blocked: {len(policy.get('blocked_files') or [])}\n"
                f"triggering policies: {', '.join(policy.get('triggering_policies') or []) or 'none'}",
                title="Policy",
            ))

    diff_path = run_dir / "diff.patch"
    if diff_path.exists():
        size = diff_path.stat().st_size
        console.print(f"[dim]diff.patch: {size} bytes[/dim]")

    review_path = run_dir / "review.json"
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if not review.get("placeholder"):
            console.print(Panel.fit(
                f"status: {review.get('status')}\n"
                f"risk:   {review.get('risk_level')}\n"
                f"summary: {review.get('summary')}",
                title="Review",
            ))


def _print_result(result: RunResult, show_plan: bool) -> None:
    console.print(Panel.fit(
        f"run_id: [bold]{result.run_id}[/bold]\n"
        f"dir:    {result.run_dir}\n"
        f"branch: {result.branch or '(none)'}\n"
        f"dry_run: {result.dry_run}\n"
        f"aborted: {result.aborted_reason or 'no'}",
        title="AgentForge",
    ))
    if show_plan and result.plan:
        console.print(Panel(result.plan, title="Plan", border_style="cyan"))
    console.print(result.final_summary)
    if result.aborted_reason and (
        "not found on PATH" in result.aborted_reason
        or "agent command is empty" in result.aborted_reason
    ):
        console.print(
            "[yellow]Tip:[/yellow] the agent CLI doesn't seem to be installed. "
            "Re-run with [bold]--dry-run[/bold] to preview the full pipeline "
            "(scan, classify, risk score, prompts) without calling any external agent."
        )


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted.[/red]")
        sys.exit(130)


if __name__ == "__main__":
    main()

"""AgentForge CLI entrypoint."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import DEFAULT_CONFIG_PATH, load_config, write_default_config
from .logger import RUNS_ROOT, latest_run_dir
from .merge_readiness import MergeReadinessEngine, MERGE_READINESS_ARTIFACT_NAME
from .orchestrator import Orchestrator, RunResult
from .project_rules import PROJECT_RULES_REL_PATH, write_default_project_rules
from . import telemetry
from .scorecards import SCORECARDS_PATH, ScorecardStore, update_from_run_dir
from .tools.test_runner import run_tests


app = typer.Typer(
    add_completion=False,
    help="AgentForge - cost-aware control plane for Claude, Codex, and AI coding agents.",
    no_args_is_help=True,
)

console = Console()


def _emit_telemetry_for_run(
    command_type: str,
    result: RunResult,
    duration_ms: int,
) -> None:
    """Build + send an event for a completed run. Never raises.

    Lives at the CLI layer (not the orchestrator) so the orchestrator
    can't accidentally leak ``RunResult`` fields into telemetry. We
    extract only the allowed scalars here and hand them to
    ``telemetry.build_event``.
    """
    try:
        settings = telemetry.load_settings()
        if not settings.enabled:
            return
        risk = result.risk_report or {}
        policy = result.policy_report or {}
        budget = result.budget or {}
        failure = result.failure or {}
        # Security warning count comes from the on-disk report if present.
        security_warnings = 0
        try:
            sec_path = Path(result.run_dir) / "security_report.json"
            if sec_path.exists():
                import json as _json
                sec = _json.loads(sec_path.read_text(encoding="utf-8"))
                security_warnings = (
                    len(sec.get("blocked_files") or [])
                    + len(sec.get("prompt_injection_warnings") or [])
                )
        except (OSError, ValueError):
            pass

        event = telemetry.build_event(
            command_type=command_type,
            dry_run=bool(result.dry_run),
            risk_level=risk.get("risk_level"),
            policy_trigger_count=len(policy.get("triggering_policies") or []),
            security_warning_count=security_warnings,
            ai_calls_used=int(budget.get("ai_calls") or 0),
            planned_ai_calls=int(budget.get("planned_ai_calls") or 0),
            review_loops_used=int(budget.get("review_loops") or 0),
            run_duration_ms=int(duration_ms),
            stopped_early=bool(budget.get("stopped_early")),
            error_category=(failure.get("error_category") if failure else None),
            anonymous_id=settings.anonymous_id,
        )
        telemetry.emit(event)
    except Exception:
        # Telemetry must never break the main command. Swallow everything.
        pass


def _update_scorecards_for_run(result: RunResult) -> None:
    """Update local scorecards from a completed run. Never raises — a
    scorecard write failure must not break the user's command."""
    try:
        store = ScorecardStore(SCORECARDS_PATH)
        if store.was_corrupted:
            console.print(
                "[yellow]Warning:[/yellow] .agentforge/scorecards.json was "
                "missing or unreadable; recreating it."
            )
        if update_from_run_dir(store, Path(result.run_dir)):
            store.save()
    except Exception:
        # Scorecards are observability, never authority. Stay silent.
        pass


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
    force: bool = typer.Option(False, "--force", help="Overwrite existing config.yaml and project_rules.md"),
) -> None:
    """Set up AgentForge in the current directory.

    Creates config.yaml, .agentforge/project_rules.md, and .agentforge/runs/
    if they don't already exist. Safe to re-run — existing files are kept
    unless --force is passed.
    """
    created: list[str] = []
    skipped: list[str] = []

    cfg_existed = Path(config_path).exists()
    cfg_path = write_default_config(config_path, overwrite=force)
    if cfg_existed and not force:
        skipped.append(str(cfg_path))
    else:
        created.append(str(cfg_path))

    forge_dir = Path(".agentforge")
    runs_dir = forge_dir / "runs"
    runs_existed = runs_dir.exists()
    runs_dir.mkdir(parents=True, exist_ok=True)
    if runs_existed:
        skipped.append(str(runs_dir))
    else:
        created.append(str(runs_dir))

    rules_target = Path(PROJECT_RULES_REL_PATH)
    rules_existed = rules_target.exists()
    rules_path = write_default_project_rules(overwrite=force)
    if rules_existed and not force:
        skipped.append(str(rules_path))
    else:
        created.append(str(rules_path))

    console.print(Panel.fit(
        "[bold green]AgentForge initialized.[/bold green]",
        border_style="green",
    ))

    if created:
        console.print("[green]Created:[/green]")
        for item in created:
            console.print(f"  - {item}")
    if skipped:
        console.print("[yellow]Already present (kept as-is):[/yellow]")
        for item in skipped:
            console.print(f"  - {item}")

    console.print()
    console.print("[bold]Next:[/bold]")
    console.print("  1. Verify the environment:")
    console.print("     [cyan]python -m agentforge doctor[/cyan]")
    console.print("  2. Try a dry run (no Claude/Codex needed):")
    console.print("     [cyan]python -m agentforge solve \"Fix typo in README\" --dry-run[/cyan]")
    console.print("  3. Review configuration:")
    console.print("     [cyan]config.yaml[/cyan]")
    console.print("  4. Add project-specific rules:")
    console.print(f"     [cyan]{PROJECT_RULES_REL_PATH}[/cyan]")


@app.command()
def plan(
    task: str = typer.Argument(..., help="The task in quotes. Be specific — keywords drive file selection and risk scoring."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the plan prompt without calling any agent. No files modified."),
    no_code_leak: bool = typer.Option(False, "--no-code-leak", help="Override config: do not send source code, diffs, or file contents to agents."),
) -> None:
    """Produce an implementation plan. Reads the repo, picks relevant files,
    runs the local risk + policy engines, asks the planner agent for a plan,
    and writes the artifacts to .agentforge/runs/<timestamp>/.

    Does not edit files. Does not create a branch. Use 'solve' for that.
    """
    orch = _load(config_path)
    if dry_run:
        _dry_run_banner()
    started = time.monotonic()
    result = orch.plan_only(
        task,
        dry_run=dry_run,
        no_code_leak=(True if no_code_leak else None),
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    _print_result(result, show_plan=True)
    _emit_telemetry_for_run("plan", result, duration_ms)
    _update_scorecards_for_run(result)


@app.command()
def solve(
    task: str = typer.Argument(..., help="The task in quotes. Be specific."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the 'Proceed?' confirmation. Required in CI / scripts."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the full pipeline (no AI calls, no edits, no branch)."),
    no_code_leak: bool = typer.Option(False, "--no-code-leak", help="Refuse to send code; solve will stop cleanly. Use --dry-run to preview."),
) -> None:
    """Full pipeline: scan -> classify -> policy + risk + security checks
    -> plan -> create branch -> implement -> tests -> diff-only review
    -> optional revision -> summary.

    Creates a fresh git branch (agentforge/<slug>) and applies edits there.
    You inspect with `git diff` and merge yourself - AgentForge never pushes
    or auto-merges.
    """
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
    started = time.monotonic()
    result = orch.solve(
        task,
        dry_run=dry_run,
        no_code_leak=(True if no_code_leak else None),
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    _print_result(result, show_plan=True)
    _emit_telemetry_for_run("solve", result, duration_ms)
    _update_scorecards_for_run(result)


@app.command()
def review(
    task: str = typer.Option("", "--task", help="Optional task description for reviewer context."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the reviewer prompt without calling the agent."),
    no_code_leak: bool = typer.Option(False, "--no-code-leak", help="Send diff stats only — never the diff body."),
) -> None:
    """Review your current working-tree git diff. The reviewer sees only
    the diff - full source files are never sent.

    For PR-style review against main/master, use `review-pr` instead.
    """
    orch = _load(config_path)
    if dry_run:
        _dry_run_banner()
    started = time.monotonic()
    result = orch.review_diff_only(
        task or None,
        dry_run=dry_run,
        no_code_leak=(True if no_code_leak else None),
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    _print_result(result, show_plan=False)
    _emit_telemetry_for_run("review", result, duration_ms)
    _update_scorecards_for_run(result)


@app.command("review-pr")
def review_pr(
    task: str = typer.Option("", "--task", help="Optional task description for reviewer context."),
    base: str = typer.Option("", "--base", help="Base branch to compare against. Auto-detects main, then master."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the reviewer prompt without calling the agent."),
    no_code_leak: bool = typer.Option(False, "--no-code-leak", help="Send diff stats only — never the diff body."),
) -> None:
    """PR-style review: compare the current branch against main (or master)
    and ask the reviewer to judge the merge-base diff.

    Never pushes a branch. Never opens a GitHub PR. Never needs GitHub auth.
    """
    orch = _load(config_path)
    if dry_run:
        _dry_run_banner()
    started = time.monotonic()
    result = orch.review_pr(
        task=task or None,
        dry_run=dry_run,
        base=base or None,
        no_code_leak=(True if no_code_leak else None),
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    _print_result(result, show_plan=False)
    _emit_telemetry_for_run("review-pr", result, duration_ms)
    _update_scorecards_for_run(result)


@app.command()
def doctor(
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
) -> None:
    """Run health checks. Reports environment + configuration readiness.

    Optional dependencies (claude, codex) are flagged as warnings, not
    errors — dry-run mode still works without them.
    """
    import shlex
    import shutil as _shutil
    import sys as _sys

    rows: list[tuple[str, str, str]] = []   # (check, status, detail)

    # Python version
    py = _sys.version_info
    if (py.major, py.minor) >= (3, 11):
        rows.append(("Python version", "ok", f"{py.major}.{py.minor}.{py.micro}"))
    else:
        rows.append((
            "Python version", "fail",
            f"{py.major}.{py.minor}.{py.micro} (requires 3.11+)",
        ))

    # git installed
    git_path = _shutil.which("git")
    if git_path:
        rows.append(("git installed", "ok", git_path))
    else:
        rows.append(("git installed", "fail", "git not on PATH"))

    # current dir is a git repo
    from .tools import git_tools
    if git_tools.is_git_repo(Path(".")):
        rows.append(("git repository", "ok", "current directory is a git repo"))
    else:
        rows.append((
            "git repository", "warn",
            "not a git repo — run `git init` before `agentforge solve`",
        ))

    # config.yaml
    cfg_present = Path(config_path).exists()
    if cfg_present:
        rows.append(("config.yaml", "ok", str(config_path)))
        try:
            cfg = load_config(config_path)
        except Exception as exc:  # noqa: BLE001
            cfg = None
            rows.append(("config.yaml parses", "fail", str(exc)))
    else:
        cfg = None
        rows.append((
            "config.yaml", "warn",
            "missing — run `python -m agentforge init`",
        ))

    # project_rules.md
    if Path(PROJECT_RULES_REL_PATH).exists():
        rows.append(("project rules", "ok", str(PROJECT_RULES_REL_PATH)))
    else:
        rows.append((
            "project rules", "warn",
            f"missing — created by `agentforge init` at {PROJECT_RULES_REL_PATH}",
        ))

    # Agent CLIs + test command + telemetry / security — all need cfg.
    if cfg is not None:
        # Only check the agent CLIs actually referenced by the configured
        # roles. Claude-only config -> just the Claude row. Swap a role to
        # another adapter and its CLI shows up here too.
        _command_for = {
            "claude": cfg.claude_command,
            "codex": cfg.codex_command,
        }
        used_agents: list[str] = []
        for role_agent in (cfg.agents.planner, cfg.agents.implementer, cfg.agents.reviewer):
            if role_agent and role_agent not in used_agents:
                used_agents.append(role_agent)
        for agent_name in used_agents:
            command = _command_for.get(agent_name, agent_name)
            bin_first = shlex.split(command or "")[:1]
            label = f"{agent_name.capitalize()} CLI"
            if bin_first and _shutil.which(bin_first[0]):
                rows.append((label, "ok", f"`{command}` -> {_shutil.which(bin_first[0])}"))
            else:
                rows.append((
                    label, "warn",
                    f"'{bin_first[0] if bin_first else '?'}' not on PATH. "
                    f"Real runs need it; --dry-run works without it.",
                ))

        # Test command configured
        test_cmd = (cfg.default_test_command or "").strip()
        if test_cmd:
            rows.append(("Test command", "ok", test_cmd))
        else:
            rows.append((
                "Test command", "warn",
                "default_test_command is empty — tests will be skipped",
            ))

        # Security defaults present
        sec_ok = bool(cfg.secret_files) and any(
            "block" in (p or {}) for p in (cfg.policies or [])
        )
        if sec_ok:
            rows.append((
                "Security defaults",
                "ok",
                f"{len(cfg.secret_files)} secret_files + {sum(1 for p in cfg.policies if 'block' in (p or {}))} block-rule(s) configured",
            ))
        else:
            rows.append((
                "Security defaults", "warn",
                "consider adding secret_files + a 'Never send secrets' policy in config.yaml",
            ))
    else:
        rows.append(("Agent CLIs",        "warn", "(skipped — no config)"))
        rows.append(("Test command",      "warn", "(skipped — no config)"))
        rows.append(("Security defaults", "warn", "(skipped — no config)"))

    # Telemetry status
    try:
        tsettings = telemetry.load_settings()
        if tsettings.enabled:
            rows.append((
                "Telemetry", "ok",
                f"enabled (anonymous_id={tsettings.anonymous_id[:8]}...)" if tsettings.anonymous_id else "enabled",
            ))
        else:
            rows.append((
                "Telemetry", "ok",
                "disabled (default). Run `agentforge telemetry enable` to opt in.",
            ))
    except Exception:  # noqa: BLE001
        rows.append(("Telemetry", "warn", "could not read telemetry settings"))

    # Render
    table = Table(title="agentforge doctor", show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status", justify="center")
    table.add_column("Detail")
    color = {"ok": "green", "warn": "yellow", "fail": "red"}
    for check, status, detail in rows:
        table.add_row(check, f"[{color[status]}]{status.upper()}[/{color[status]}]", detail)
    console.print(table)

    n_ok   = sum(1 for _, s, _ in rows if s == "ok")
    n_warn = sum(1 for _, s, _ in rows if s == "warn")
    n_fail = sum(1 for _, s, _ in rows if s == "fail")
    summary_color = "red" if n_fail else ("yellow" if n_warn else "green")
    console.print(
        f"[{summary_color}]Summary:[/{summary_color}] "
        f"{n_ok} ok, {n_warn} warning(s), {n_fail} failure(s)"
    )
    if n_warn and not n_fail:
        console.print(
            "[dim]Warnings are informational. AgentForge can still run in --dry-run mode.[/dim]"
        )


@app.command()
def redteam(
    task: str = typer.Option("", "--task", help="Optional task description for reviewer context."),
    base: str = typer.Option("", "--base", help="Compare current branch against this base (PR-style)."),
    run: Path = typer.Option(None, "--run", help="Replay an existing run directory instead of using the current diff."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the red-team prompt without calling the reviewer."),
    no_code_leak: bool = typer.Option(False, "--no-code-leak", help="Send diff stats only — never the diff body."),
) -> None:
    """Strict, adversarial review for high-risk changes.

    Three diff sources, picked in order:
      - --run <path>: reuse a saved run's diff + reports
      - --base <branch>: PR-style comparison
      - default: current working-tree diff

    Never pushes, never opens a PR, never needs GitHub auth.
    """
    orch = _load(config_path)
    if dry_run:
        _dry_run_banner()
    started = time.monotonic()
    result = orch.redteam(
        task=task or None,
        dry_run=dry_run,
        base=base or None,
        run=run,
        no_code_leak=(True if no_code_leak else None),
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    _print_result(result, show_plan=False)
    if result.review:
        verdict = result.review
        color = {
            "approved":             "green",
            "needs_changes":        "yellow",
            "needs_manual_review":  "red",
        }.get(str(verdict.get("status")), "white")
        console.print(Panel.fit(
            f"status: [{color}]{verdict.get('status')}[/{color}]\n"
            f"risk_level: {verdict.get('risk_level')}\n"
            f"merge_recommendation: {verdict.get('merge_recommendation')}\n"
            f"summary: {verdict.get('summary')}",
            title="Red team verdict",
            border_style=color,
        ))
        findings = verdict.get("findings") or []
        if findings:
            console.print("[bold]Findings:[/bold]")
            for f in findings:
                sev = f.get("severity", "?")
                sev_color = {"critical": "red", "high": "red", "medium": "yellow", "low": "white"}.get(sev, "white")
                console.print(
                    f"  - [{sev_color}][{sev}][/{sev_color}] "
                    f"{f.get('file', '?')}: {f.get('issue', '')}"
                )
                if f.get("why_it_matters"):
                    console.print(f"      why: {f.get('why_it_matters')}")
                if f.get("suggested_fix"):
                    console.print(f"      fix: {f.get('suggested_fix')}")
        missing = verdict.get("missing_tests") or []
        if missing:
            console.print("[bold]Missing tests:[/bold]")
            for t in missing:
                console.print(f"  - {t}")
    _emit_telemetry_for_run("review", result, duration_ms)
    _update_scorecards_for_run(result)


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


telemetry_app = typer.Typer(
    add_completion=False,
    help="Manage anonymous telemetry. Off by default. No code or paths collected.",
    no_args_is_help=True,
)
app.add_typer(telemetry_app, name="telemetry")


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Show current telemetry settings + local event count."""
    settings = telemetry.load_settings()
    events_path = Path(".agentforge") / "telemetry" / "events.jsonl"
    event_count = 0
    if events_path.exists():
        try:
            event_count = sum(1 for _ in events_path.read_text(encoding="utf-8").splitlines() if _.strip())
        except OSError:
            event_count = 0
    color = "green" if settings.enabled else "yellow"
    console.print(Panel.fit(
        f"[{color}]enabled: {settings.enabled}[/{color}]\n"
        f"anonymous_id: {settings.anonymous_id or '(none)'}\n"
        f"endpoint: {settings.endpoint or '(local file: .agentforge/telemetry/events.jsonl)'}\n"
        f"local events on disk: {event_count}",
        title="Telemetry",
    ))


@telemetry_app.command("enable")
def telemetry_enable(
    endpoint: str = typer.Option("", "--endpoint", help="Optional HTTPS endpoint. If empty, events are written locally only."),
) -> None:
    """Turn anonymous telemetry on. Generates a fresh anonymous UUID."""
    console.print(Panel.fit(
        "[bold]Anonymous telemetry will be enabled.[/bold]\n\n"
        "[green]What WILL be collected:[/green]",
        title="Telemetry — what's collected",
    ))
    for name, desc in telemetry.collected_field_descriptions():
        console.print(f"  - {name}: {desc}")
    console.print(Panel.fit(
        "[red]What is NEVER collected:[/red]\n"
        + "\n".join(f"  - {item}" for item in telemetry.never_collected()),
        title="Telemetry — what's never collected",
    ))
    if not typer.confirm("Enable telemetry?", default=False):
        console.print("[yellow]No changes made.[/yellow]")
        raise typer.Exit(code=1)
    settings = telemetry.enable(endpoint=(endpoint or None))
    console.print(
        f"[green]OK[/green] telemetry enabled. anonymous_id={settings.anonymous_id}\n"
        f"endpoint: {settings.endpoint or '(local file)'}"
    )
    console.print("To turn it off:  python -m agentforge telemetry disable")


@telemetry_app.command("disable")
def telemetry_disable() -> None:
    """Turn anonymous telemetry off and clear the anonymous ID."""
    telemetry.disable()
    console.print(
        "[green]OK[/green] telemetry disabled. anonymous_id cleared.\n"
        "Local event log (if any) was NOT deleted — see "
        "`python -m agentforge telemetry clear` to remove it."
    )


@telemetry_app.command("preview")
def telemetry_preview() -> None:
    """Show the most recently logged telemetry event (no network call)."""
    event = telemetry.latest_event()
    if event is None:
        console.print(
            "[yellow]No local telemetry events yet.[/yellow]\n"
            "Run any AgentForge command after `telemetry enable` to generate one."
        )
        return
    console.print(Panel.fit(
        json.dumps(event, indent=2),
        title="Latest telemetry event (not sent during preview)",
        border_style="cyan",
    ))


@telemetry_app.command("clear")
def telemetry_clear() -> None:
    """Delete all local telemetry data (settings + event log)."""
    if not typer.confirm(
        "Delete .agentforge/telemetry/settings.json and events.jsonl?",
        default=False,
    ):
        console.print("[yellow]No changes made.[/yellow]")
        raise typer.Exit(code=1)
    telemetry.clear_local_data()
    console.print("[green]OK[/green] local telemetry data cleared.")


scorecards_app = typer.Typer(
    add_completion=False,
    help="Local per-agent scorecards (no network, no telemetry).",
    invoke_without_command=True,
)
app.add_typer(scorecards_app, name="scorecards")


@scorecards_app.callback(invoke_without_command=True)
def scorecards_main(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False, "--json",
        help="Emit machine-readable JSON instead of the text view.",
    ),
) -> None:
    """Show local agent scorecards. Use 'scorecards reset' to wipe them."""
    if ctx.invoked_subcommand is not None:
        return
    store = ScorecardStore(SCORECARDS_PATH)
    if store.was_corrupted:
        console.print(
            "[yellow]Warning:[/yellow] .agentforge/scorecards.json was "
            "unreadable; starting fresh."
        )
    if json_output:
        console.print(json.dumps(store.to_dict(), indent=2))
    else:
        console.print(store.render_text())


@scorecards_app.command("reset")
def scorecards_reset() -> None:
    """Delete .agentforge/scorecards.json and reset all per-agent stats."""
    if not typer.confirm("Delete .agentforge/scorecards.json?", default=False):
        console.print("[yellow]No changes made.[/yellow]")
        raise typer.Exit(code=1)
    store = ScorecardStore(SCORECARDS_PATH)
    store.reset()
    console.print("[green]OK[/green] scorecards cleared.")


@app.command()
def readiness(
    run: Path = typer.Option(None, "--run", help="Run directory to score. Defaults to the latest run."),
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
) -> None:
    """Compute a 0-100 merge readiness score for an AgentForge run.

    Reads the existing run artifacts (risk, policy, security, budget, review,
    test_result, failure_report) and turns them into a single verdict so you
    can decide whether to merge. No agents are called.

    Writes merge_readiness.json into the run directory.
    """
    target = run if run is not None else latest_run_dir()
    if target is None:
        console.print(
            "[yellow]No runs yet.[/yellow] Try: "
            "agentforge solve \"...\" --dry-run"
        )
        raise typer.Exit(code=1)
    target = Path(target)
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/red] {target}")
        raise typer.Exit(code=2)

    try:
        result = MergeReadinessEngine(target).calculate()
    except Exception as exc:  # noqa: BLE001 — surface as a CLI error, not a crash
        console.print(f"[red]Could not score run:[/red] {exc}")
        raise typer.Exit(code=2)

    # Persist the artifact.
    try:
        (target / MERGE_READINESS_ARTIFACT_NAME).write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8",
        )
    except OSError as exc:
        console.print(f"[yellow]Warning:[/yellow] could not write {MERGE_READINESS_ARTIFACT_NAME}: {exc}")

    # Color the level.
    color = {
        "READY":              "green",
        "READY_WITH_CAUTION": "yellow",
        "NEEDS_WORK":         "yellow",
        "DO_NOT_MERGE":       "red",
    }.get(result.level, "white")
    console.print(Panel.fit(
        f"score: [bold]{result.score}/100[/bold]\n"
        f"level: [{color}]{result.level}[/{color}]\n"
        f"recommendation: {result.recommendation}\n"
        f"summary: {result.summary}",
        title="Merge readiness",
        border_style=color,
    ))
    if result.passed:
        console.print("[green]Passed:[/green]")
        for item in result.passed:
            console.print(f"  - {item}")
    if result.warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for item in result.warnings:
            console.print(f"  - {item}")
    if result.blockers:
        console.print("[red]Blockers:[/red]")
        for item in result.blockers:
            console.print(f"  - {item}")
    console.print(
        f"\n[dim]Artifact: {target / MERGE_READINESS_ARTIFACT_NAME}[/dim]"
    )


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

    failure_path = run_dir / "failure_report.json"
    if failure_path.exists():
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        fix_lines = "\n".join(f"  - {f}" for f in failure.get("suggested_fix") or [])
        console.print(Panel.fit(
            f"[bold red]status:[/bold red] {failure.get('status')}\n"
            f"category: {failure.get('error_category')}\n"
            f"step: {failure.get('step_failed', '?')}\n"
            f"safe to retry: {'yes' if failure.get('safe_to_retry') else 'no'}\n"
            f"reason: {failure.get('message')}\n\n"
            f"Suggested fix:\n{fix_lines}",
            title="Failure",
            border_style="red",
        ))

    summary_md = (run_dir / "final_summary.md")
    if summary_md.exists():
        console.print(summary_md.read_text(encoding="utf-8"))

    budget_path = run_dir / "budget.json"
    if budget_path.exists():
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        if not budget.get("placeholder"):
            # call_log is a list of per-call dicts; skip it in the summary
            # table — too wide to render usefully alongside scalars.
            scalar = {k: v for k, v in budget.items() if k != "call_log"}
            table = Table(title="Budget", show_header=True)
            for k in scalar.keys():
                table.add_column(k)
            table.add_row(*[str(v) for v in scalar.values()])
            console.print(table)

    security_path = run_dir / "security_report.json"
    if security_path.exists():
        sec = json.loads(security_path.read_text(encoding="utf-8"))
        if not sec.get("placeholder"):
            blocked = sec.get("blocked_files") or []
            suspicious = sec.get("suspicious_files") or []
            warnings = sec.get("prompt_injection_warnings") or []
            risk = sec.get("command_risk", "low")
            safe = sec.get("safe_to_continue", True)
            color = "red" if (blocked or not safe) else (
                "yellow" if (suspicious or warnings) else "green"
            )
            console.print(Panel.fit(
                f"[{color}]blocked secret files: {len(blocked)}[/{color}]\n"
                f"[{color}]prompt-injection warnings: {len(warnings)}[/{color}]\n"
                f"command risk: {risk}\n"
                f"safe to continue: {'yes' if safe else 'no'}",
                title="Security",
            ))

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
    status_color = {
        "completed":          "green",
        "dry_run_completed":  "green",
        "stopped_early":      "yellow",
        "failed":             "red",
    }.get(result.status, "white")
    console.print(Panel.fit(
        f"run_id: [bold]{result.run_id}[/bold]\n"
        f"dir:    {result.run_dir}\n"
        f"branch: {result.branch or '(none)'}\n"
        f"dry_run: {result.dry_run}\n"
        f"status:  [{status_color}]{result.status}[/{status_color}]\n"
        f"aborted: {result.aborted_reason or 'no'}",
        title="AgentForge",
    ))
    if show_plan and result.plan:
        console.print(Panel(result.plan, title="Plan", border_style="cyan"))
    if result.final_summary:
        console.print(result.final_summary)
    console.print(
        f"\n[green]Run artifacts saved to:[/green]\n  {result.run_dir}{'/' if not str(result.run_dir).endswith('/') else ''}"
    )
    if result.failure:
        fix_lines = "\n".join(f"  - {f}" for f in result.failure.get("suggested_fix") or [])
        retry_note = ""
        if result.failure.get("safe_to_retry") is False:
            retry_note = "\n(Retrying without changes will hit the same error.)"
        console.print(Panel.fit(
            f"[bold]AgentForge stopped safely.[/bold]\n"
            f"Reason: {result.failure.get('message', '')}\n"
            f"Category: {result.failure.get('error_category', '')}\n"
            f"Step: {result.failure.get('step_failed', '?')}\n"
            f"Safe to retry: {'yes' if result.failure.get('safe_to_retry') else 'no'}\n\n"
            f"Suggested fix:\n{fix_lines}{retry_note}",
            title="Failure",
            border_style="red",
        ))


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted.[/red]")
        sys.exit(130)


if __name__ == "__main__":
    main()

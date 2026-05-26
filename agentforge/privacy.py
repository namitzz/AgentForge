"""Privacy controls.

Adds a **No-Code-Leak Mode** that prevents source code, file contents, and
diff bodies from being sent to external agents. Local checks (risk
scoring, policy, security, budget, merge readiness, classifier) still run
because they never leave the machine.

Toggle via ``config.yaml``:

    privacy:
      no_code_leak_mode: true

Or per-run via the CLI flag ``--no-code-leak`` which overrides the config
for that command.

When enabled:

  - ``solve`` refuses to call the implementer (real run) — implementation
    inherently requires sending code. Dry-run still works.
  - ``plan`` runs normally — the planner only ever sees paths, not contents.
  - ``review`` / ``review-pr`` / ``redteam`` produce reviewer prompts where
    the diff body is replaced with stats only (files changed counts,
    +/- line totals, grouped file paths).
  - Every run writes ``.agentforge/runs/<id>/privacy_report.json`` and
    surfaces a *Privacy mode:* block in the CLI.

All file paths in this module are POSIX-normalised so behaviour matches
on Windows and Unix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .tools.diff_tools import parse_diff_stats


# Sentinel that downstream code can ``raise`` to abort a run cleanly with
# a "stopped_early" status when no-code-leak is on and we'd need to send
# code. The orchestrator catches this and never lets it propagate.
class CodeLeakRefused(RuntimeError):
    """Raised when a step would have sent code under No-Code-Leak Mode."""


REFUSAL_MESSAGE: str = (
    "No-Code-Leak Mode is enabled, so AgentForge will not send source code "
    "to external agents. Use --dry-run, disable this mode, or run local "
    "checks only."
)


@dataclass
class PrivacyMode:
    """The privacy-mode flags that govern a single run."""

    no_code_leak: bool = False

    @property
    def source_code_sent(self) -> bool:
        return not self.no_code_leak

    @property
    def file_contents_sent(self) -> bool:
        return not self.no_code_leak

    @property
    def diff_content_sent(self) -> bool:
        return not self.no_code_leak

    @property
    def external_implementation_allowed(self) -> bool:
        return not self.no_code_leak

    def to_dict(self) -> dict:
        return {
            "no_code_leak_mode": self.no_code_leak,
            "source_code_sent": self.source_code_sent,
            "file_contents_sent": self.file_contents_sent,
            "diff_content_sent": self.diff_content_sent,
            "external_implementation_allowed": self.external_implementation_allowed,
            "redaction_applied": self.no_code_leak,
        }


# ---------------------------------------------------------------------------
# Public reporting helpers
# ---------------------------------------------------------------------------

def build_privacy_report(privacy: PrivacyMode, notes: list[str] | None = None) -> dict:
    """The on-disk ``privacy_report.json`` shape."""
    out = privacy.to_dict()
    out["notes"] = list(notes or [])
    return out


def privacy_human_summary(privacy: PrivacyMode) -> list[str]:
    """Lines for the CLI ``Privacy mode:`` block."""
    yes_no = lambda b: "yes" if b else "no"  # noqa: E731 — tiny helper
    return [
        "Privacy mode:",
        f"- No-Code-Leak Mode: {'enabled' if privacy.no_code_leak else 'disabled'}",
        f"- Source code sent to agents: {yes_no(privacy.source_code_sent)}",
        f"- File contents sent to agents: {yes_no(privacy.file_contents_sent)}",
        f"- Diff content sent to agents: {yes_no(privacy.diff_content_sent)}",
        f"- External implementation calls allowed: "
        f"{yes_no(privacy.external_implementation_allowed)}",
    ]


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------

def redact_diff_to_stats(diff_text: str) -> str:
    """Replace a real diff with a stats-only summary that is safe to send.

    Output contains only:
      - a clear redaction header
      - files-changed / additions / deletions counts
      - changed file *categories* (grouped paths), not the raw file list
    No diff content, no file content, no specific filenames except as
    grouped patterns like ``src/auth/*.py``.
    """
    if not diff_text or not diff_text.strip():
        return "[Diff redacted by No-Code-Leak Mode — empty diff]"
    stats = parse_diff_stats(diff_text)
    lines: list[str] = [
        "[Diff content redacted by No-Code-Leak Mode]",
        f"Files changed: {stats.files_changed}",
        f"Additions: +{stats.additions}",
        f"Deletions: -{stats.deletions}",
    ]
    if stats.file_list:
        lines.append("Changed file categories:")
        for group, count in group_paths(stats.file_list):
            suffix = "s" if count != 1 else ""
            lines.append(f"  - {group} ({count} file{suffix})")
    return "\n".join(lines)


def group_paths(paths: list[str]) -> list[tuple[str, int]]:
    """Collapse a list of paths into ``(group_label, count)`` pairs.

    Grouping key is ``(parent_dir, extension)``. Examples::

        src/auth/login.py, src/auth/password_reset.py  -> src/auth/*.py (2)
        tests/test_auth.py                              -> tests/*.py (1)
        README.md                                       -> *.md (1)
    """
    groups: dict[str, int] = {}
    for raw in paths:
        if not raw:
            continue
        pp = PurePosixPath(str(raw).replace("\\", "/"))
        parent = str(pp.parent)
        ext = pp.suffix
        if parent in ("", "."):
            label = f"*{ext}" if ext else "*"
        else:
            label = f"{parent}/*{ext}" if ext else f"{parent}/*"
        groups[label] = groups.get(label, 0) + 1
    return sorted(groups.items(), key=lambda kv: kv[0])


def grouped_file_list(paths: list[str]) -> list[str]:
    """Human-readable list, e.g. ``['src/auth/*.py (2)', 'tests/*.py (1)']``."""
    return [f"{label} ({count})" for label, count in group_paths(paths)]


# ---------------------------------------------------------------------------
# Effective-mode helper
# ---------------------------------------------------------------------------

def effective_mode(*, override: bool | None, config_default: bool) -> PrivacyMode:
    """Per-run flag wins; otherwise fall back to the project default."""
    if override is None:
        return PrivacyMode(no_code_leak=bool(config_default))
    return PrivacyMode(no_code_leak=bool(override))

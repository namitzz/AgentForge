"""Lightweight per-project memory.

A free-form Markdown file at ``.agentforge/project_rules.md`` lets developers
state rules that should be included in every agent prompt without retyping
them on the command line.

The contents are pasted verbatim into the planner, implementer, and reviewer
prompts. If the file doesn't exist the system continues safely and the
orchestrator notes that no rules were found.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_RULES_REL_PATH = Path(".agentforge") / "project_rules.md"


DEFAULT_PROJECT_RULES = """\
# Project Rules

- Keep changes small and focused.
- Prefer existing project style.
- Do not modify authentication, security, database, or deployment files without review.
- Do not send secrets or environment files to AI agents.
- Explain risky changes clearly.
- Do not auto-merge or force-push changes.
"""


def load_project_rules(root: Path | str = ".") -> str | None:
    """Return the project_rules.md contents, or None if the file is missing.

    Empty / whitespace-only files are treated as missing.
    """
    p = Path(root) / PROJECT_RULES_REL_PATH
    if not p.exists() or not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    cleaned = text.strip()
    return cleaned or None


def write_default_project_rules(
    root: Path | str = ".",
    overwrite: bool = False,
) -> Path:
    """Create the default rules file if it doesn't already exist.

    Returns the path that was (or would have been) written to. Never raises
    when the file is already there unless ``overwrite=True`` is requested.
    """
    p = Path(root) / PROJECT_RULES_REL_PATH
    if p.exists() and not overwrite:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_PROJECT_RULES, encoding="utf-8")
    return p


def project_rules_status(root: Path | str = ".") -> tuple[bool, int]:
    """Return ``(present, char_count)`` for the orchestrator to print on each run."""
    rules = load_project_rules(root)
    if rules is None:
        return False, 0
    return True, len(rules)

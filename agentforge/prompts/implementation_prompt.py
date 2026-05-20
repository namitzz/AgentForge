"""Builds the implementation prompt for the coding agent."""

from __future__ import annotations


IMPLEMENTATION_SYSTEM = """\
You are the IMPLEMENTATION agent for AgentForge.
Make the minimum changes required to satisfy the plan. Do not refactor
unrelated code. Do not add speculative features. Keep diffs small and focused.

Working rules:
- You are operating on an isolated git branch already created for this task.
- Apply edits directly to files on disk.
- If a step in the plan is ambiguous, choose the simpler interpretation and note it in the summary.
- Run tests yourself if your tooling permits; otherwise the orchestrator will.

When you finish, output a short Markdown summary with:
  - Files changed (path + 1-line reason)
  - Notable decisions / trade-offs
  - Anything skipped and why
"""

IMPLEMENTATION_TEMPLATE = """\
{system}

# Project rules
{project_rules}

# Task
{task}

# Plan (from planner)
{plan}

# Relevant files (with capped contents)
{files_block}

# Constraints
- Keep changes minimal.
- Do not modify files outside the relevant set unless strictly required.
- Do not commit. The orchestrator owns git operations.
- Do not touch secret files: {secret_files}
"""


def _files_block(files: list[tuple[str, str]], max_chars_per_file: int) -> str:
    if not files:
        return "(no files attached — agent should request or scan as needed)"
    chunks: list[str] = []
    for path, content in files:
        snippet = content if len(content) <= max_chars_per_file else (
            content[:max_chars_per_file] + f"\n... [truncated]"
        )
        chunks.append(f"## {path}\n```\n{snippet}\n```")
    return "\n\n".join(chunks)


def build_implementation_prompt(
    task: str,
    plan: str,
    files: list[tuple[str, str]],
    max_chars_per_file: int,
    secret_files: list[str],
    project_rules: str | None = None,
) -> str:
    return IMPLEMENTATION_TEMPLATE.format(
        system=IMPLEMENTATION_SYSTEM.strip(),
        project_rules=(project_rules or "").strip() or "(no project rules file found)",
        task=task.strip(),
        plan=plan.strip() or "(no plan provided)",
        files_block=_files_block(files, max_chars_per_file),
        secret_files=", ".join(secret_files) or "(none configured)",
    )

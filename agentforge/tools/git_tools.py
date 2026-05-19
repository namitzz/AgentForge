"""Safe git wrappers using subprocess.

Only non-destructive commands are exposed.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path | str | None = None, check: bool = True) -> str:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError(f"git is not installed or not on PATH: {exc}") from exc
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args[1:])} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def is_git_repo(path: Path | str = ".") -> bool:
    try:
        out = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
        return out.strip() == "true"
    except GitError:
        return False


def current_branch(path: Path | str = ".") -> str:
    out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return out.strip()


def has_uncommitted_changes(path: Path | str = ".") -> bool:
    out = _run(["git", "status", "--porcelain"], cwd=path)
    return bool(out.strip())


_SLUG_RE = re.compile(r"[^a-zA-Z0-9-]+")


def slugify(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return s[:max_len] or "task"


def create_branch(name: str, path: Path | str = ".") -> str:
    """Create a new branch from HEAD and switch to it. Safe: refuses to overwrite."""
    existing = _run(["git", "branch", "--list", name], cwd=path).strip()
    if existing:
        raise GitError(f"branch '{name}' already exists; pick a different name")
    _run(["git", "checkout", "-b", name], cwd=path)
    return name


def checkout(branch: str, path: Path | str = ".") -> None:
    _run(["git", "checkout", branch], cwd=path)


def diff(staged: bool = False, path: Path | str = ".") -> str:
    """Return the working diff. Includes untracked files via intent-to-add if not staged."""
    args = ["git", "diff"]
    if staged:
        args.append("--staged")
    return _run(args, cwd=path)


def diff_against(ref: str, path: Path | str = ".") -> str:
    """Return diff vs ``ref`` (e.g. main). Includes uncommitted changes."""
    return _run(["git", "diff", ref], cwd=path)


def changed_files(path: Path | str = ".") -> list[str]:
    """List files with uncommitted changes (working tree + staged)."""
    out = _run(["git", "status", "--porcelain"], cwd=path)
    files: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # Format: "XY path" where XY are status codes.
        parts = line[3:].strip()
        # Handle renames: "old -> new"
        if " -> " in parts:
            parts = parts.split(" -> ", 1)[1]
        files.append(parts)
    return files


@dataclass
class GitContext:
    is_repo: bool
    branch: str | None
    dirty: bool

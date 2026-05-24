"""End-to-end AgentForge demo against the tiny demo project.

Runs ``agentforge init`` and ``agentforge solve "..." --dry-run`` inside
``demo-projects/tiny-python-app``. No Claude / Codex / network required —
dry-run mode covers the entire pipeline locally.

Usage:
    python scripts/demo_dry_run.py
    python scripts/demo_dry_run.py --print-only      # just show the commands
    python scripts/demo_dry_run.py --task "..."      # override the demo task
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "demo-projects" / "tiny-python-app"
DEFAULT_TASK = "Add password reset validation to the login flow"


def _print_commands(task: str) -> None:
    rel = DEMO_DIR.relative_to(REPO_ROOT)
    print("Run these from the repo root:")
    print()
    print(f"  cd {rel}")
    print(f"  python -m agentforge init")
    print(f"  python -m agentforge solve {task!r} --dry-run")
    print()
    print("Or one-shot via this script:  python scripts/demo_dry_run.py")


def _run(args: list[str], cwd: Path) -> int:
    # Inject the repo root onto PYTHONPATH so `python -m agentforge`
    # finds the package even when AgentForge isn't `pip install`-ed.
    env = os.environ.copy()
    extra = str(REPO_ROOT)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (extra + os.pathsep + existing) if existing else extra
    print(f"\n$ {' '.join(args)}    (cwd={cwd.relative_to(REPO_ROOT)})")
    proc = subprocess.run(args, cwd=str(cwd), env=env)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task", default=DEFAULT_TASK,
        help=f"Task to send to agentforge solve. Default: {DEFAULT_TASK!r}",
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help="Print the commands you would run instead of executing them.",
    )
    parser.add_argument(
        "--no-doctor", action="store_true",
        help="Skip the `agentforge doctor` health check.",
    )
    args = parser.parse_args()

    if not DEMO_DIR.is_dir():
        print(f"ERROR: demo directory not found at {DEMO_DIR}", file=sys.stderr)
        return 2

    if args.print_only:
        _print_commands(args.task)
        return 0

    # Sanity: make sure `python -m agentforge` is importable from the repo.
    if shutil.which(sys.executable) is None:
        print("ERROR: could not locate the current Python interpreter", file=sys.stderr)
        return 2

    py = [sys.executable, "-m", "agentforge"]

    if not args.no_doctor:
        _run(py + ["doctor"], cwd=DEMO_DIR)

    rc = _run(py + ["init"], cwd=DEMO_DIR)
    if rc != 0:
        print(f"\n`agentforge init` exited with {rc}", file=sys.stderr)
        return rc

    rc = _run(py + ["solve", args.task, "--dry-run"], cwd=DEMO_DIR)
    if rc != 0:
        print(f"\n`agentforge solve --dry-run` exited with {rc}", file=sys.stderr)
        return rc

    runs_dir = DEMO_DIR / ".agentforge" / "runs"
    print("\nDemo done. Inspect the artifacts:")
    print(f"  {runs_dir.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

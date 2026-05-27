from __future__ import annotations

import subprocess
from pathlib import Path


def summarize_git_changes(cwd: Path) -> dict:
    if not _is_git_repo(cwd):
        return {"available": False, "reason": "execution directory is not inside a git repository"}

    status = _run_git(cwd, ["status", "--short"])
    diff_stat = _run_git(cwd, ["diff", "--stat"])
    changed_files = []
    for line in status.splitlines():
        if not line.strip():
            continue
        changed_files.append({"status": line[:2].strip(), "path": line[3:].strip()})
    return {
        "available": True,
        "status_short": status,
        "changed_files": changed_files,
        "diff_stat": diff_stat,
    }


def _is_git_repo(cwd: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _run_git(cwd: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=20,
        )
        return (proc.stdout or "")[-8000:]
    except (OSError, subprocess.SubprocessError) as exc:
        return f"git {' '.join(args)} failed: {exc}"

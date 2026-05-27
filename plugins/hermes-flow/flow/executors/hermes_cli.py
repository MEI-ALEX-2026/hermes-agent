from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import BaseExecutor, ExecutionResult


class HermesCLIExecutor(BaseExecutor):
    executor_type = "hermes_cli"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def run(self, *, prompt: str, cwd: Path, env: dict[str, str], log_path: Path) -> ExecutionResult:
        hermes_bin = self.config.get("command") or shutil.which("hermes") or "hermes"
        profile = self.config.get("profile")
        timeout = int(self.config.get("timeout_seconds") or 3600)

        argv = [str(hermes_bin)]
        if profile:
            argv.extend(["--profile", str(profile)])
        argv.extend(["-z", prompt])

        merged_env = os.environ.copy()
        merged_env.update(env)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            log.write(("$ " + " ".join(argv[:4]) + " ...\n").encode("utf-8", errors="replace"))
            try:
                proc = subprocess.run(
                    argv,
                    cwd=str(cwd),
                    env=merged_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    text=True,
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                log.write(output.encode("utf-8", errors="replace"))
                return ExecutionResult(
                    status="failed",
                    exit_code=124,
                    summary=f"Hermes CLI executor timed out after {timeout}s.",
                    output_excerpt=output[-4000:],
                    metadata={"timeout_seconds": timeout},
                )
            log.write((proc.stdout or "").encode("utf-8", errors="replace"))

        output = proc.stdout or ""
        return ExecutionResult(
            status="passed" if proc.returncode == 0 else "failed",
            exit_code=int(proc.returncode),
            summary="Hermes CLI task completed." if proc.returncode == 0 else "Hermes CLI task failed.",
            output_excerpt=output[-4000:],
            metadata={"argv": argv[:-1] + ["<prompt>"]},
        )

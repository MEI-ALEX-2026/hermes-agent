from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .base import BaseExecutor, ExecutionResult


class ACPExecutor(BaseExecutor):
    executor_type = "acp"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def run(self, *, prompt: str, cwd: Path, env: dict[str, str], log_path: Path) -> ExecutionResult:
        command = str(self.config.get("command") or "").strip()
        if not command:
            return _interface_only(log_path, cwd)

        timeout = int(self.config.get("timeout_seconds") or 3600)
        prompt_mode = str(self.config.get("prompt_mode") or "stdin")
        session_id = str(self.config.get("session_id") or env.get("HERMES_FLOW_RUN_ID") or "")
        argv = shlex.split(command)
        extra_args = self.config.get("args") or []
        if isinstance(extra_args, list):
            argv.extend(str(arg) for arg in extra_args)
        if prompt_mode == "arg":
            argv.append(prompt)

        merged_env = os.environ.copy()
        merged_env.update(env)
        merged_env["HERMES_FLOW_ACP_SESSION_ID"] = session_id
        if prompt_mode == "env":
            merged_env["HERMES_FLOW_ACP_PROMPT"] = prompt

        stdin_text = prompt if prompt_mode == "stdin" else None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            log.write(("$ " + " ".join(argv) + "\n").encode("utf-8", errors="replace"))
            try:
                proc = subprocess.run(
                    argv,
                    cwd=str(cwd),
                    env=merged_env,
                    input=stdin_text,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    text=True,
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.stdout if isinstance(exc.stdout, str) else ""
                log.write(output.encode("utf-8", errors="replace"))
                return ExecutionResult(
                    "failed",
                    124,
                    f"ACP executor timed out after {timeout}s.",
                    output[-4000:],
                    {
                        "session_id": session_id,
                        "timeout_seconds": timeout,
                        "command": command,
                    },
                )
            output = proc.stdout or ""
            log.write(output.encode("utf-8", errors="replace"))

        return ExecutionResult(
            "passed" if proc.returncode == 0 else "failed",
            int(proc.returncode),
            "ACP executor task completed." if proc.returncode == 0 else "ACP executor task failed.",
            output[-4000:],
            {
                "session_id": session_id,
                "command": command,
                "prompt_mode": prompt_mode,
            },
        )


def _interface_only(log_path: Path, cwd: Path) -> ExecutionResult:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "ACP executor interface is configured, but no ACP command was provided.\n",
        encoding="utf-8",
    )
    return ExecutionResult(
        "failed",
        2,
        "ACP executor requires a configured command for runtime execution.",
        "",
        {"cwd": str(cwd), "requires_command": True},
    )

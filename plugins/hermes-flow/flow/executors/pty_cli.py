from __future__ import annotations

import os
import pty
import select
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BaseExecutor, ExecutionResult
from ..pty_sessions import register_pty_session


class PtyCLIExecutor(BaseExecutor):
    executor_type = "pty_cli"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def run(self, *, prompt: str, cwd: Path, env: dict[str, str], log_path: Path) -> ExecutionResult:
        command = str(self.config.get("command") or "").strip()
        if not command:
            return ExecutionResult("failed", 2, "PTY CLI template has no command configured.")
        timeout = int(self.config.get("timeout_seconds") or 3600)
        idle_timeout = int(self.config.get("idle_timeout_seconds") or 0)
        append_prompt = bool(self.config.get("append_prompt", True))
        argv = shlex.split(command)
        if append_prompt:
            argv.append(prompt)

        merged_env = os.environ.copy()
        merged_env.update(env)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        master_fd, slave_fd = pty.openpty()
        output_chunks: list[str] = []
        start = time.monotonic()
        last_output = start
        keep_session_open = False
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=merged_env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            with log_path.open("ab") as log:
                log.write(("$ " + " ".join(argv[:-1] if append_prompt else argv) + "\n").encode("utf-8", errors="replace"))
                while True:
                    if proc.poll() is not None:
                        break
                    if time.monotonic() - start > timeout:
                        _stop_process(proc)
                        return ExecutionResult(
                            "failed",
                            124,
                            f"PTY CLI executor timed out after {timeout}s.",
                            "".join(output_chunks)[-4000:],
                            {"timeout_seconds": timeout},
                        )
                    if idle_timeout and time.monotonic() - last_output > idle_timeout:
                        session_id = register_pty_session(
                            run_id=str(env.get("HERMES_FLOW_RUN_ID") or ""),
                            task_id=str(env.get("HERMES_FLOW_TASK_ID") or ""),
                            task_run_id=str(env.get("HERMES_FLOW_TASK_RUN_ID") or ""),
                            command=command,
                            cwd=cwd,
                            master_fd=master_fd,
                            process=proc,
                            log_path=log_path,
                            initial_output="".join(output_chunks),
                        )
                        keep_session_open = True
                        return ExecutionResult(
                            "waiting_input",
                            130,
                            "PTY CLI appears idle and may be waiting for user input.",
                            "".join(output_chunks)[-4000:],
                            {
                                "idle_timeout_seconds": idle_timeout,
                                "command": command,
                                "pty_session_id": session_id,
                            },
                        )
                    readable, _, _ = select.select([master_fd], [], [], 0.2)
                    if not readable:
                        continue
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    last_output = time.monotonic()
                    log.write(data)
                    text = data.decode("utf-8", errors="replace")
                    output_chunks.append(text)
                while True:
                    readable, _, _ = select.select([master_fd], [], [], 0)
                    if not readable:
                        break
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    log.write(data)
                    output_chunks.append(data.decode("utf-8", errors="replace"))
            try:
                code = int(proc.wait(timeout=1))
            except subprocess.TimeoutExpired:
                _stop_process(proc)
                try:
                    code = int(proc.wait(timeout=1))
                except subprocess.TimeoutExpired:
                    code = 124
        finally:
            if not keep_session_open:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
            try:
                os.close(slave_fd)
            except OSError:
                pass

        output = "".join(output_chunks)
        return ExecutionResult(
            "passed" if code == 0 else "failed",
            code,
            "PTY CLI task completed." if code == 0 else "PTY CLI task failed.",
            output[-4000:],
            {"command": command},
        )


def _stop_process(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

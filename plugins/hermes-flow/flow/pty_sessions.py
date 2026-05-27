from __future__ import annotations

import os
import select
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .db import FlowDB, new_id


@dataclass
class PtySession:
    id: str
    run_id: str
    task_id: str
    task_run_id: str
    command: str
    cwd: str
    master_fd: int
    process: subprocess.Popen
    log_path: Path
    created_at: float = field(default_factory=time.time)
    closed: bool = False
    user_closed: bool = False
    output: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


_SESSIONS: dict[str, PtySession] = {}
_LOCK = threading.Lock()


def register_pty_session(
    *,
    run_id: str,
    task_id: str,
    task_run_id: str,
    command: str,
    cwd: Path,
    master_fd: int,
    process: subprocess.Popen,
    log_path: Path,
    initial_output: str = "",
) -> str:
    session_id = new_id("pty")
    session = PtySession(
        id=session_id,
        run_id=run_id,
        task_id=task_id,
        task_run_id=task_run_id,
        command=command,
        cwd=str(cwd),
        master_fd=master_fd,
        process=process,
        log_path=log_path,
        output=[initial_output] if initial_output else [],
    )
    with _LOCK:
        _SESSIONS[session_id] = session
    FlowDB().record_event(
        run_id,
        "pty_waiting_input",
        "PTY session is waiting for user input.",
        task_run_id=task_run_id,
        task_id=task_id,
        payload={"pty_session_id": session_id, "command": command, "cwd": str(cwd)},
    )
    thread = threading.Thread(target=_drain_session, args=(session_id,), daemon=True)
    thread.start()
    return session_id


def list_pty_sessions(run_id: Optional[str] = None) -> list[dict]:
    with _LOCK:
        sessions = list(_SESSIONS.values())
    rows = []
    for session in sessions:
        if run_id and session.run_id != run_id:
            continue
        rows.append(_session_row(session))
    return rows


def get_pty_output(session_id: str, *, max_chars: int = 8000) -> dict:
    session = _get_session(session_id)
    with session.lock:
        text = "".join(session.output)[-max_chars:]
    return {**_session_row(session), "output": text}


def send_pty_input(session_id: str, text: str) -> dict:
    session = _get_session(session_id)
    if session.closed or session.process.poll() is not None:
        raise ValueError("PTY session is closed.")
    with session.lock:
        master_fd = session.master_fd
    if master_fd < 0:
        raise ValueError("PTY session is closed.")
    data = text.encode("utf-8", errors="replace")
    os.write(master_fd, data)
    FlowDB().record_event(
        session.run_id,
        "pty_user_input",
        "User sent input to PTY session.",
        task_run_id=session.task_run_id,
        task_id=session.task_id,
        payload={"pty_session_id": session_id, "byte_count": len(data)},
    )
    return _session_row(session)


def close_pty_session(session_id: str) -> dict:
    session = _get_session(session_id)
    session.closed = True
    session.user_closed = True
    _stop_process(session.process)
    _close_master_fd(session)
    FlowDB().record_event(
        session.run_id,
        "pty_closed",
        "PTY takeover session closed.",
        task_run_id=session.task_run_id,
        task_id=session.task_id,
        payload={"pty_session_id": session_id},
    )
    return _session_row(session)


def _drain_session(session_id: str) -> None:
    try:
        session = _get_session(session_id)
    except KeyError:
        return
    finalized = False
    while not session.closed:
        if session.process.poll() is not None:
            _read_available(session)
            session.closed = True
            _finalize_completed_session(session)
            finalized = True
            break
        _read_available(session)
        time.sleep(0.1)
    _close_master_fd(session)
    if session.process.poll() is not None and not finalized and not session.user_closed:
        _finalize_completed_session(session)


def _read_available(session: PtySession) -> None:
    while True:
        with session.lock:
            master_fd = session.master_fd
        if master_fd < 0:
            session.closed = True
            return
        try:
            readable, _, _ = select.select([master_fd], [], [], 0)
        except (OSError, ValueError):
            session.closed = True
            return
        if not readable:
            return
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            session.closed = True
            return
        if not data:
            return
        text = data.decode("utf-8", errors="replace")
        with session.lock:
            session.output.append(text)
            if sum(len(chunk) for chunk in session.output) > 120000:
                session.output = ["".join(session.output)[-60000:]]
        try:
            with session.log_path.open("ab") as log:
                log.write(data)
        except OSError:
            pass


def _close_master_fd(session: PtySession) -> None:
    with session.lock:
        master_fd = session.master_fd
        session.master_fd = -1
    if master_fd < 0:
        return
    try:
        os.close(master_fd)
    except OSError:
        pass


def _finalize_completed_session(session: PtySession) -> None:
    db = FlowDB()
    run = db.get_run(session.run_id)
    if not run or run.get("status") in {"cancelled", "interrupted", "stopped"}:
        return
    workflow = db.get_workflow(run["workflow_id"])
    if not workflow:
        return
    task = next((item for item in workflow.get("tasks", []) if item["id"] == session.task_id), None)
    if not task:
        return
    exit_code = int(session.process.poll() or 0)
    output = get_pty_output(session.id, max_chars=4000).get("output", "")
    try:
        from .scheduler import Scheduler

        scheduler = Scheduler(db)
        validation_results = scheduler._run_validation(  # noqa: SLF001 - resume path shares scheduler validation semantics.
            session.run_id,
            session.task_run_id,
            task,
            workflow,
            Path(session.cwd),
        )
    except Exception as exc:
        validation_results = [{"command": "validation", "exit_code": 1, "output_summary": str(exc), "duration_ms": 0}]
    validation_passed = all(item.get("exit_code") == 0 for item in validation_results)
    status = "passed" if exit_code == 0 and validation_passed else "failed"
    summary = "PTY takeover task completed." if status == "passed" else "PTY takeover task failed."
    from .db import now_iso

    db.update_task_run(
        session.task_run_id,
        status=status,
        exit_code=exit_code,
        summary=summary,
        finished_at=now_iso(),
    )
    db.update_task(session.task_id, status=status)
    db.save_summary(
        session.run_id,
        "task",
        summary,
        task_id=session.task_id,
        payload={
            "executor": {"command": session.command, "pty_session_id": session.id},
            "output_excerpt": output[-4000:],
            "validation": validation_results,
        },
    )
    db.record_event(
        session.run_id,
        "pty_completed",
        summary,
        task_run_id=session.task_run_id,
        task_id=session.task_id,
        payload={"pty_session_id": session.id, "exit_code": exit_code, "status": status},
    )
    if run.get("status") == "waiting_input":
        db.update_run(session.run_id, status="ready")
        try:
            from .scheduler import Scheduler

            Scheduler(db).run_existing(session.run_id)
        except Exception as exc:
            db.update_run(session.run_id, status="failed", finished_at=now_iso())
            db.record_event(
                session.run_id,
                "run_error",
                f"Workflow resume after PTY takeover failed: {exc}",
                task_run_id=session.task_run_id,
                task_id=session.task_id,
                payload={"error": str(exc)},
            )


def _session_row(session: PtySession) -> dict:
    code = session.process.poll()
    return {
        "id": session.id,
        "run_id": session.run_id,
        "task_id": session.task_id,
        "task_run_id": session.task_run_id,
        "command": session.command,
        "cwd": session.cwd,
        "closed": bool(session.closed or code is not None),
        "exit_code": code,
        "created_at": session.created_at,
    }


def _get_session(session_id: str) -> PtySession:
    with _LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        raise KeyError(session_id)
    return session


def _stop_process(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except Exception:
        return

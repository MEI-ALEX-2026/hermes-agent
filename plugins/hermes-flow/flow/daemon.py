from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import FlowDB
from .paths import heartbeat_path, stop_flag_path
from .scheduler import Scheduler


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_heartbeat(status: str = "running", *, active_workers: int = 0) -> dict:
    db = FlowDB()
    db.initialize()
    payload = {
        "status": status,
        "updated_at": utc_now(),
        "running_workflow_count": db.count_running_runs(),
        "active_workers": active_workers,
        "stop_requested": stop_flag_path().exists(),
    }
    heartbeat_path().parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def daemon_status() -> dict:
    db = FlowDB()
    db.initialize()
    heartbeat = {}
    if heartbeat_path().exists():
        try:
            heartbeat = json.loads(heartbeat_path().read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            heartbeat = {"status": "unknown", "error": "heartbeat JSON is invalid"}
    return {
        "heartbeat": heartbeat,
        "running_workflow_count": db.count_running_runs(),
        "stop_requested": stop_flag_path().exists(),
        "db_path": str(db.path),
    }


def request_stop() -> Path:
    stop_flag_path().parent.mkdir(parents=True, exist_ok=True)
    stop_flag_path().write_text(utc_now(), encoding="utf-8")
    write_heartbeat("stopping")
    return stop_flag_path()


def run_daemon(*, interval_seconds: float = 5.0, once: bool = False, max_workers: int = 4) -> int:
    db = FlowDB()
    db.initialize()
    interrupted = db.recover_interrupted()
    db.seed_builtin_templates()
    if stop_flag_path().exists():
        stop_flag_path().unlink()
    write_heartbeat("running", active_workers=0)
    if once:
        process_pending_once(max_workers=max_workers)
        return interrupted
    with ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="hermes-flow") as pool:
        futures: dict[Future, str] = {}
        while not stop_flag_path().exists():
            _drain_finished(futures)
            capacity = max(0, max_workers - len(futures))
            if capacity:
                for run in db.claim_pending_runs(limit=capacity):
                    run_id = run["id"]
                    futures[pool.submit(_run_claimed, run_id)] = run_id
            write_heartbeat("running", active_workers=len(futures))
            time.sleep(interval_seconds)
        for future in futures:
            future.cancel()
    write_heartbeat("stopped", active_workers=0)
    return interrupted


def process_pending_once(*, max_workers: int = 4) -> list[str]:
    db = FlowDB()
    db.initialize()
    claimed = db.claim_pending_runs(limit=max_workers)
    completed: list[str] = []
    for run in claimed:
        _run_claimed(run["id"])
        completed.append(run["id"])
    write_heartbeat("running", active_workers=0)
    return completed


def _run_claimed(run_id: str) -> str:
    db = FlowDB()
    try:
        Scheduler(db).run_existing(run_id)
    except Exception as exc:
        db.update_run(run_id, status="failed", guardrail_reason="", finished_at=utc_now())
        db.record_event(
            run_id,
            "run_error",
            f"Workflow run failed: {exc}",
            payload={"error": str(exc)},
        )
    return run_id


def _drain_finished(futures: dict[Future, str]) -> None:
    for future in list(futures):
        if future.done() or future.cancelled():
            futures.pop(future, None)


def doctor() -> dict:
    db = FlowDB()
    db.initialize()
    db.seed_builtin_templates()
    templates = [wf for wf in db.list_workflows(include_templates=True) if wf.get("template_key")]
    return {
        "ok": True,
        "db_path": str(db.path),
        "db_exists": db.path.exists(),
        "data_dir_writable": _writable(db.path.parent),
        "log_dir_writable": _writable(db.path.parent.parent / "logs"),
        "hermes_cli_found": bool(shutil.which("hermes")),
        "builtin_template_count": len(templates),
        "daemon": daemon_status(),
    }


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False

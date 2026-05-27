from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .db import FlowDB
from .paths import logs_dir


def cleanup_runs(
    db: Optional[FlowDB] = None,
    *,
    project_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    statuses: Optional[list[str]] = None,
    retain_recent: int = 100,
    raw_log_days: int = 30,
    dry_run: bool = True,
) -> dict:
    """Clean old raw logs while preserving active, failed, and pinned runs."""

    db = db or FlowDB()
    db.initialize()
    cutoff = datetime.now(timezone.utc) - timedelta(days=raw_log_days)
    with db.connect() as conn:
        where: list[str] = []
        params: list[object] = []
        if workflow_id:
            where.append("workflow_runs.workflow_id = ?")
            params.append(workflow_id)
        if project_id:
            where.append("workflows.project_id = ?")
            params.append(project_id)
        if statuses:
            where.append("workflow_runs.status IN ({})".format(",".join("?" for _ in statuses)))
            params.extend(statuses)
        sql = """
            SELECT workflow_runs.id, workflow_runs.status, workflow_runs.pinned,
                   workflow_runs.finished_at, workflow_runs.updated_at
            FROM workflow_runs
            JOIN workflows ON workflows.id = workflow_runs.workflow_id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(workflow_runs.finished_at, workflow_runs.updated_at) DESC"
        rows = conn.execute(sql, params).fetchall()
    removable = []
    for idx, row in enumerate(rows):
        status = row["status"]
        if status in {"pending", "ready", "running", "validating", "reviewing", "failed", "guardrail_stopped"}:
            continue
        if int(row["pinned"] or 0):
            continue
        timestamp = row["finished_at"] or row["updated_at"]
        too_many = idx >= retain_recent
        too_old = _older_than(timestamp, cutoff)
        if too_many or too_old:
            removable.append({"run_id": row["id"], "reason": "count" if too_many else "age"})

    deleted_logs = []
    for item in removable:
        path = logs_dir() / item["run_id"]
        if path.exists():
            deleted_logs.append(str(path))
            if not dry_run:
                shutil.rmtree(path)
    return {
        "dry_run": dry_run,
        "candidate_runs": removable,
        "deleted_log_dirs": deleted_logs,
        "retained_recent": retain_recent,
        "raw_log_days": raw_log_days,
        "project_id": project_id,
        "workflow_id": workflow_id,
        "statuses": statuses or [],
    }


def _older_than(value: str, cutoff: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < cutoff

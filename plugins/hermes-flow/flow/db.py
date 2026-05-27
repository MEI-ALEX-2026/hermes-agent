from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

from .constants import (
    DEFAULT_MAX_DURATION_MINUTES,
    DEFAULT_MAX_LOOP_ITERATIONS,
    DEFAULT_MAX_TASK_STEPS,
)
from .paths import db_path, ensure_flow_dirs


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True, sort_keys=True)


def loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class FlowDB:
    def __init__(self, path: Optional[Path] = None) -> None:
        ensure_flow_dirs()
        self.path = Path(path) if path else db_path()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._ensure_columns(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, now_iso()),
            )

    def create_project(self, name: str, root_dir: str, **kwargs: Any) -> str:
        project_id = kwargs.get("project_id") or new_id("proj")
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects(id, name, root_dir, default_agent_template_id,
                                     default_validation_commands_json, settings_json,
                                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name,
                    root_dir,
                    kwargs.get("default_agent_template_id"),
                    dumps(kwargs.get("default_validation_commands", [])),
                    dumps(kwargs.get("settings", {})),
                    ts,
                    ts,
                ),
            )
        return project_id

    def update_project(self, project_id: str, **fields: Any) -> None:
        mapped: dict[str, Any] = {}
        for key in ("name", "root_dir", "default_agent_template_id"):
            if key in fields:
                mapped[key] = fields[key]
        if "default_validation_commands" in fields:
            mapped["default_validation_commands_json"] = dumps(fields["default_validation_commands"] or [])
        if "settings" in fields:
            mapped["settings_json"] = dumps(fields["settings"] or {})
        self._update_table("projects", project_id, mapped)

    def list_projects(self) -> list[dict]:
        with self.connect() as conn:
            return [self._project_row(r) for r in conn.execute("SELECT * FROM projects ORDER BY updated_at DESC")]

    def get_project(self, project_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return self._project_row(row) if row else None

    def upsert_agent_template(
        self,
        name: str,
        template_type: str,
        config: Optional[dict] = None,
        *,
        template_id: Optional[str] = None,
    ) -> str:
        tid = template_id or new_id("agent")
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_templates(id, name, type, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    type = excluded.type,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (tid, name, template_type, dumps(config or {}), ts, ts),
            )
        return tid

    def list_agent_templates(self) -> list[dict]:
        with self.connect() as conn:
            return [self._agent_template_row(r) for r in conn.execute("SELECT * FROM agent_templates ORDER BY name")]

    def get_agent_template(self, template_id: Optional[str]) -> Optional[dict]:
        if not template_id:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agent_templates WHERE id = ?", (template_id,)).fetchone()
            return self._agent_template_row(row) if row else None

    def delete_agent_template(self, template_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM agent_templates WHERE id = ?", (template_id,))

    def create_project_agent_binding(
        self,
        project_id: str,
        agent_template_id: str,
        *,
        role: str = "",
        config: Optional[dict] = None,
        binding_id: Optional[str] = None,
    ) -> str:
        bid = binding_id or new_id("bind")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_agent_bindings(id, project_id, agent_template_id, role, config_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (bid, project_id, agent_template_id, role, dumps(config or {}), now_iso()),
            )
        return bid

    def list_project_agent_bindings(self, project_id: str) -> list[dict]:
        with self.connect() as conn:
            return [
                self._binding_row(r)
                for r in conn.execute(
                    """
                    SELECT project_agent_bindings.*, agent_templates.name AS agent_template_name,
                           agent_templates.type AS agent_template_type
                    FROM project_agent_bindings
                    JOIN agent_templates ON agent_templates.id = project_agent_bindings.agent_template_id
                    WHERE project_agent_bindings.project_id = ?
                    ORDER BY project_agent_bindings.role, agent_templates.name
                    """,
                    (project_id,),
                )
            ]

    def delete_project_agent_binding(self, binding_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM project_agent_bindings WHERE id = ?", (binding_id,))

    def create_workflow(
        self,
        name: str,
        goal: str,
        *,
        project_id: Optional[str] = None,
        root_dir: str = "",
        default_agent_template_id: Optional[str] = None,
        default_validation_commands: Optional[list[str]] = None,
        max_loop_iterations: int = DEFAULT_MAX_LOOP_ITERATIONS,
        max_task_steps: int = DEFAULT_MAX_TASK_STEPS,
        max_duration_minutes: int = DEFAULT_MAX_DURATION_MINUTES,
        template_key: Optional[str] = None,
        status: str = "confirmed",
        workflow_id: Optional[str] = None,
    ) -> str:
        wid = workflow_id or new_id("wf")
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows(id, project_id, name, goal, root_dir,
                                      default_agent_template_id,
                                      default_validation_commands_json,
                                      max_loop_iterations, max_task_steps,
                                      max_duration_minutes, template_key, status,
                                      created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wid,
                    project_id,
                    name,
                    goal,
                    root_dir,
                    default_agent_template_id,
                    dumps(default_validation_commands or []),
                    max_loop_iterations,
                    max_task_steps,
                    max_duration_minutes,
                    template_key,
                    status,
                    ts,
                    ts,
                ),
            )
        return wid

    def update_workflow(self, workflow_id: str, **fields: Any) -> None:
        mapped: dict[str, Any] = {}
        for key in (
            "project_id",
            "name",
            "goal",
            "root_dir",
            "default_agent_template_id",
            "max_loop_iterations",
            "max_task_steps",
            "max_duration_minutes",
            "template_key",
            "status",
        ):
            if key in fields:
                mapped[key] = fields[key]
        if "default_validation_commands" in fields:
            mapped["default_validation_commands_json"] = dumps(fields["default_validation_commands"] or [])
        self._update_table("workflows", workflow_id, mapped)

    def delete_workflow(self, workflow_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))

    def add_task(
        self,
        workflow_id: str,
        title: str,
        goal: str,
        *,
        acceptance_criteria: str = "",
        execution_dir: str = "",
        agent_template_id: Optional[str] = None,
        validation_commands: Optional[list[str]] = None,
        status: str = "draft",
        position_x: float = 0,
        position_y: float = 0,
        metadata: Optional[dict] = None,
        task_id: Optional[str] = None,
    ) -> str:
        tid = task_id or new_id("task")
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(id, workflow_id, title, goal, acceptance_criteria,
                                  execution_dir, agent_template_id,
                                  validation_commands_json, status, position_x,
                                  position_y, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    workflow_id,
                    title,
                    goal,
                    acceptance_criteria,
                    execution_dir,
                    agent_template_id,
                    dumps(validation_commands or []),
                    status,
                    position_x,
                    position_y,
                    dumps(metadata or {}),
                    ts,
                    ts,
                ),
            )
        return tid

    def update_task(self, task_id: str, **fields: Any) -> None:
        mapped: dict[str, Any] = {}
        for key in (
            "title",
            "goal",
            "acceptance_criteria",
            "execution_dir",
            "agent_template_id",
            "status",
            "position_x",
            "position_y",
        ):
            if key in fields:
                mapped[key] = fields[key]
        if "validation_commands" in fields:
            mapped["validation_commands_json"] = dumps(fields["validation_commands"] or [])
        if "metadata" in fields:
            mapped["metadata_json"] = dumps(fields["metadata"] or {})
        self._update_table("tasks", task_id, mapped)

    def delete_task(self, task_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def add_edge(
        self,
        workflow_id: str,
        source_task_id: str,
        target_task_id: str,
        edge_type: str,
        *,
        edge_id: Optional[str] = None,
    ) -> str:
        eid = edge_id or new_id("edge")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_edges(id, workflow_id, source_task_id, target_task_id, edge_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (eid, workflow_id, source_task_id, target_task_id, edge_type),
            )
        return eid

    def update_edge(self, edge_id: str, **fields: Any) -> None:
        allowed = {key: fields[key] for key in ("source_task_id", "target_task_id", "edge_type") if key in fields}
        if not allowed:
            return
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        values = list(allowed.values()) + [edge_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE task_edges SET {assignments} WHERE id = ?", values)

    def delete_edge(self, edge_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM task_edges WHERE id = ?", (edge_id,))

    def list_workflows(self, project_id: Optional[str] = None, include_templates: bool = True) -> list[dict]:
        sql = "SELECT * FROM workflows"
        params: list[Any] = []
        filters: list[str] = []
        if project_id and include_templates:
            filters.append("(project_id = ? OR template_key IS NOT NULL)")
            params.append(project_id)
        elif project_id:
            filters.append("project_id = ?")
            params.append(project_id)
        if not include_templates:
            filters.append("template_key IS NULL")
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY updated_at DESC"
        with self.connect() as conn:
            return [self._workflow_row(r) for r in conn.execute(sql, params)]

    def get_workflow(self, workflow_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            if not row:
                return None
            workflow = self._workflow_row(row)
            workflow["tasks"] = [
                self._task_row(r)
                for r in conn.execute(
                    "SELECT * FROM tasks WHERE workflow_id = ? ORDER BY position_x, position_y, id",
                    (workflow_id,),
                )
            ]
            workflow["edges"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM task_edges WHERE workflow_id = ? ORDER BY id",
                    (workflow_id,),
                )
            ]
            return workflow

    def create_run(self, workflow_id: str, *, status: str = "pending") -> str:
        rid = new_id("run")
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs(id, workflow_id, status, loop_iterations,
                                          executed_steps, started_at, updated_at)
                VALUES (?, ?, ?, 0, 0, ?, ?)
                """,
                (rid, workflow_id, status, ts, ts),
            )
        return rid

    def list_runs(self, workflow_id: Optional[str] = None, *, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM workflow_runs"
        params: list[Any] = []
        if workflow_id:
            sql += " WHERE workflow_id = ?"
            params.append(workflow_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    def claim_pending_runs(self, *, limit: int = 4) -> list[dict]:
        claimed: list[dict] = []
        ts = now_iso()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_runs
                WHERE status = 'pending'
                ORDER BY started_at, id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE workflow_runs SET status = 'ready', updated_at = ? WHERE id = ? AND status = 'pending'",
                    (ts, row["id"]),
                )
                updated = dict(row)
                updated["status"] = "ready"
                updated["updated_at"] = ts
                claimed.append(updated)
        return claimed

    def update_run(self, run_id: str, **fields: Any) -> None:
        self._update_table("workflow_runs", run_id, fields)

    def get_run(self, run_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def create_task_run(self, run_id: str, task_id: str, *, attempt: int, log_path: str, executor_type: str) -> str:
        trid = new_id("trun")
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_runs(id, run_id, task_id, status, attempt,
                                      started_at, updated_at, log_path, executor_type)
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (trid, run_id, task_id, attempt, ts, ts, log_path, executor_type),
            )
        return trid

    def update_task_run(self, task_run_id: str, **fields: Any) -> None:
        self._update_table("task_runs", task_run_id, fields)

    def record_event(
        self,
        run_id: str,
        event_type: str,
        message: str,
        *,
        task_run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> str:
        eid = new_id("evt")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(id, run_id, task_run_id, task_id, type, message,
                                   payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (eid, run_id, task_run_id, task_id, event_type, message, dumps(payload or {}), now_iso()),
            )
        return eid

    def list_approvals(self, run_id: Optional[str] = None, *, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM approvals"
        params: list[Any] = []
        if run_id:
            sql += " WHERE run_id = ?"
            params.append(run_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    def create_approval(
        self,
        *,
        run_id: str,
        task_id: Optional[str] = None,
        task_run_id: Optional[str] = None,
        source_task: str = "",
        executor_type: str = "",
        command: str = "",
        target_path: str = "",
        trigger_reason: str = "",
        execution_dir: str = "",
        outside_execution_dir: bool = False,
        risk_level: str = "",
    ) -> str:
        approval_id = new_id("appr")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals(id, run_id, task_run_id, task_id, source_task,
                                      executor_type, command, target_path,
                                      trigger_reason, execution_dir,
                                      outside_execution_dir, risk_level, decision,
                                      created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                """,
                (
                    approval_id,
                    run_id,
                    task_run_id,
                    task_id,
                    source_task,
                    executor_type,
                    command,
                    target_path,
                    trigger_reason,
                    execution_dir,
                    1 if outside_execution_dir else 0,
                    risk_level,
                    now_iso(),
                ),
            )
        return approval_id

    def decide_approval(self, approval_id: str, decision: str) -> None:
        if decision not in {"allow_once", "allow_run", "deny"}:
            raise ValueError("approval decision must be allow_once, allow_run, or deny")
        with self.connect() as conn:
            conn.execute(
                "UPDATE approvals SET decision = ?, decided_at = ? WHERE id = ?",
                (decision, now_iso(), approval_id),
            )

    def save_validation_result(
        self,
        run_id: str,
        task_run_id: str,
        task_id: str,
        command: str,
        exit_code: int,
        output_summary: str,
        duration_ms: int,
    ) -> str:
        vid = new_id("val")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO validation_results(id, run_id, task_run_id, task_id, command,
                                               exit_code, output_summary,
                                               duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (vid, run_id, task_run_id, task_id, command, exit_code, output_summary, duration_ms, now_iso()),
            )
        return vid

    def save_summary(self, run_id: str, kind: str, content: str, *, task_id: Optional[str] = None, payload: Optional[dict] = None) -> str:
        sid = new_id("sum")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO summaries(id, run_id, task_id, kind, content, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, run_id, task_id, kind, content, dumps(payload or {}), now_iso()),
            )
        return sid

    def save_workflow_version(self, workflow_id: str, source: str, workflow_payload: dict) -> str:
        version_id = new_id("wver")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM workflow_versions WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            version = int(row["next_version"] if row else 1)
            conn.execute(
                """
                INSERT INTO workflow_versions(id, workflow_id, version, source, workflow_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (version_id, workflow_id, version, source, dumps(workflow_payload), now_iso()),
            )
        return version_id

    def get_run_status(self, run_id: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["task_runs"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM task_runs WHERE run_id = ? ORDER BY started_at, id",
                    (run_id,),
                )
            ]
            return data

    def get_run_summary(self, run_id: str) -> Optional[dict]:
        status = self.get_run_status(run_id)
        if not status:
            return None
        with self.connect() as conn:
            status["events"] = [
                self._event_row(r)
                for r in conn.execute(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY created_at, id LIMIT 200",
                    (run_id,),
                )
            ]
            status["validation_results"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM validation_results WHERE run_id = ? ORDER BY created_at, id",
                    (run_id,),
                )
            ]
            status["summaries"] = [
                {**dict(r), "payload": loads(r["payload_json"], {})}
                for r in conn.execute(
                    "SELECT * FROM summaries WHERE run_id = ? ORDER BY created_at, id",
                    (run_id,),
                )
            ]
        return status

    def list_recent_events(self, run_id: Optional[str] = None, *, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM events"
        params: list[Any] = []
        if run_id:
            sql += " WHERE run_id = ?"
            params.append(run_id)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = [self._event_row(r) for r in conn.execute(sql, params)]
        rows.reverse()
        return rows

    def get_task_log_path(self, run_id: str, task_id: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT log_path FROM task_runs
                WHERE run_id = ? AND task_id = ?
                ORDER BY started_at DESC, id DESC LIMIT 1
                """,
                (run_id, task_id),
            ).fetchone()
            return row["log_path"] if row else None

    def recover_interrupted(self) -> int:
        ts = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = 'pending', updated_at = ?
                WHERE status = 'ready'
                """,
                (ts,),
            )
            runs = conn.execute(
                "SELECT id FROM workflow_runs WHERE status IN ('running','validating','reviewing','waiting_input','waiting_approval')"
            ).fetchall()
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = 'interrupted', finished_at = ?, updated_at = ?
                WHERE status IN ('running','validating','reviewing','waiting_input','waiting_approval')
                """,
                (ts, ts),
            )
            conn.execute(
                """
                UPDATE task_runs
                SET status = 'interrupted', finished_at = ?, updated_at = ?
                WHERE status IN ('running','validating','reviewing','waiting_input','waiting_approval')
                """,
                (ts, ts),
            )
        return len(runs)

    def count_running_runs(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM workflow_runs WHERE status IN ('pending','ready','running','validating','reviewing')"
            ).fetchone()
            return int(row["n"] if row else 0)

    def seed_builtin_templates(self) -> None:
        templates = builtin_workflow_templates()
        with self.connect() as conn:
            existing = {
                r["template_key"]
                for r in conn.execute("SELECT template_key FROM workflows WHERE template_key IS NOT NULL")
            }
        for spec in templates:
            if spec["template_key"] in existing:
                continue
            workflow_id = self.create_workflow(
                spec["name"],
                spec["goal"],
                template_key=spec["template_key"],
                status="template",
                max_loop_iterations=spec.get("max_loop_iterations", DEFAULT_MAX_LOOP_ITERATIONS),
                max_task_steps=spec.get("max_task_steps", DEFAULT_MAX_TASK_STEPS),
                max_duration_minutes=spec.get("max_duration_minutes", DEFAULT_MAX_DURATION_MINUTES),
            )
            task_ids: dict[str, str] = {}
            for idx, task in enumerate(spec["tasks"]):
                task_ids[task["key"]] = self.add_task(
                    workflow_id,
                    task["title"],
                    task["goal"],
                    acceptance_criteria=task.get("acceptance_criteria", ""),
                    validation_commands=task.get("validation_commands", []),
                    status="draft",
                    position_x=idx * 260,
                    position_y=0,
                    metadata={"template_task_key": task["key"]},
                )
            for edge in spec["edges"]:
                self.add_edge(workflow_id, task_ids[edge["source"]], task_ids[edge["target"]], edge["type"])
            self.save_summary(
                workflow_id,
                "template",
                f"Built-in template: {spec['name']}",
                payload={"template_key": spec["template_key"]},
            )

    def _update_table(self, table: str, row_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        fields = dict(fields)
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [row_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", values)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        workflow_cols = {row["name"] for row in conn.execute("PRAGMA table_info(workflows)")}
        if "status" not in workflow_cols:
            conn.execute("ALTER TABLE workflows ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
            conn.execute("UPDATE workflows SET status = 'template' WHERE template_key IS NOT NULL")

    @staticmethod
    def _project_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["default_validation_commands"] = loads(data.pop("default_validation_commands_json"), [])
        data["settings"] = loads(data.pop("settings_json"), {})
        return data

    @staticmethod
    def _agent_template_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["config"] = loads(data.pop("config_json"), {})
        return data

    @staticmethod
    def _binding_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["config"] = loads(data.pop("config_json"), {})
        return data

    @staticmethod
    def _workflow_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["default_validation_commands"] = loads(data.pop("default_validation_commands_json"), [])
        return data

    @staticmethod
    def _task_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["validation_commands"] = loads(data.pop("validation_commands_json"), [])
        data["metadata"] = loads(data.pop("metadata_json"), {})
        return data

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["payload"] = loads(data.pop("payload_json"), {})
        return data


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_dir TEXT NOT NULL,
    default_agent_template_id TEXT,
    default_validation_commands_json TEXT NOT NULL DEFAULT '[]',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('hermes_cli','acp','pty_cli')),
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_agent_bindings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_template_id TEXT NOT NULL REFERENCES agent_templates(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    goal TEXT NOT NULL DEFAULT '',
    root_dir TEXT NOT NULL DEFAULT '',
    default_agent_template_id TEXT REFERENCES agent_templates(id),
    default_validation_commands_json TEXT NOT NULL DEFAULT '[]',
    max_loop_iterations INTEGER NOT NULL DEFAULT 5,
    max_task_steps INTEGER NOT NULL DEFAULT 30,
    max_duration_minutes INTEGER NOT NULL DEFAULT 180,
    template_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_versions (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    workflow_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(workflow_id, version)
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    goal TEXT NOT NULL DEFAULT '',
    acceptance_criteria TEXT NOT NULL DEFAULT '',
    execution_dir TEXT NOT NULL DEFAULT '',
    agent_template_id TEXT REFERENCES agent_templates(id),
    validation_commands_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    position_x REAL NOT NULL DEFAULT 0,
    position_y REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_edges (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    source_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    target_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL CHECK(edge_type IN ('dependency','success','failure','always','manual'))
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    current_task_id TEXT,
    loop_iterations INTEGER NOT NULL DEFAULT 0,
    executed_steps INTEGER NOT NULL DEFAULT 0,
    guardrail_reason TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL,
    log_path TEXT NOT NULL DEFAULT '',
    executor_type TEXT NOT NULL DEFAULT '',
    exit_code INTEGER,
    summary TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_run_id TEXT,
    task_id TEXT,
    type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_run_id TEXT,
    task_id TEXT,
    source_task TEXT NOT NULL DEFAULT '',
    executor_type TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL DEFAULT '',
    target_path TEXT NOT NULL DEFAULT '',
    trigger_reason TEXT NOT NULL DEFAULT '',
    execution_dir TEXT NOT NULL DEFAULT '',
    outside_execution_dir INTEGER NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    command TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    output_summary TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def builtin_workflow_templates() -> list[dict]:
    return [
        {
            "template_key": "feature_until_green",
            "name": "Feature Until Green",
            "goal": "Implement a requested feature, test it, repair failures, and complete only after validation passes.",
            "tasks": [
                {"key": "implement", "title": "Implement", "goal": "Implement the requested feature."},
                {"key": "test", "title": "Test", "goal": "Run the validation commands and summarize failures.", "validation_commands": ["pytest"]},
                {"key": "fix", "title": "Fix", "goal": "Fix validation failures using recent failure summaries."},
                {"key": "complete", "title": "Complete", "goal": "Summarize what changed and why it satisfies the acceptance criteria."},
            ],
            "edges": [
                {"source": "implement", "target": "test", "type": "success"},
                {"source": "test", "target": "complete", "type": "success"},
                {"source": "test", "target": "fix", "type": "failure"},
                {"source": "fix", "target": "test", "type": "success"},
            ],
        },
        {
            "template_key": "bugfix_loop",
            "name": "Bugfix Loop",
            "goal": "Reproduce a bug, fix it, run regression validation, and repeat repairs until green.",
            "tasks": [
                {"key": "reproduce", "title": "Reproduce", "goal": "Create or run a reproduction for the bug."},
                {"key": "fix", "title": "Fix", "goal": "Apply the smallest fix that addresses the reproduced bug."},
                {"key": "regression", "title": "Regression Test", "goal": "Run focused regression validation.", "validation_commands": ["pytest"]},
                {"key": "fix_again", "title": "Fix Again", "goal": "Repair any regression failures."},
                {"key": "complete", "title": "Complete", "goal": "Summarize the bugfix and regression evidence."},
            ],
            "edges": [
                {"source": "reproduce", "target": "fix", "type": "success"},
                {"source": "fix", "target": "regression", "type": "success"},
                {"source": "regression", "target": "complete", "type": "success"},
                {"source": "regression", "target": "fix_again", "type": "failure"},
                {"source": "fix_again", "target": "regression", "type": "success"},
            ],
        },
        {
            "template_key": "refactor_with_guardrails",
            "name": "Refactor With Guardrails",
            "goal": "Analyze impact, refactor, validate, optionally review, and repair failures.",
            "tasks": [
                {"key": "analyze", "title": "Analyze Impact", "goal": "Map affected files and risky behavior before editing."},
                {"key": "refactor", "title": "Refactor", "goal": "Apply the refactor while preserving behavior."},
                {"key": "build_test", "title": "Build/Test", "goal": "Run build and tests.", "validation_commands": ["pytest"]},
                {"key": "review", "title": "Optional Review", "goal": "Review the file-change and validation summary."},
                {"key": "fix", "title": "Fix", "goal": "Fix refactor regressions."},
                {"key": "complete", "title": "Complete", "goal": "Summarize refactor evidence."},
            ],
            "edges": [
                {"source": "analyze", "target": "refactor", "type": "success"},
                {"source": "refactor", "target": "build_test", "type": "success"},
                {"source": "build_test", "target": "review", "type": "success"},
                {"source": "review", "target": "complete", "type": "success"},
                {"source": "build_test", "target": "fix", "type": "failure"},
                {"source": "fix", "target": "build_test", "type": "success"},
            ],
        },
        {
            "template_key": "docs_validation",
            "name": "Docs + Validation",
            "goal": "Update documentation, validate commands or links, optionally review, and complete.",
            "tasks": [
                {"key": "update_docs", "title": "Update Docs", "goal": "Make the requested documentation changes."},
                {"key": "validate", "title": "Validate Links/Commands", "goal": "Validate documented links or commands."},
                {"key": "review", "title": "Optional Review", "goal": "Review docs clarity and validation output."},
                {"key": "complete", "title": "Complete", "goal": "Summarize documentation changes and validation."},
            ],
            "edges": [
                {"source": "update_docs", "target": "validate", "type": "success"},
                {"source": "validate", "target": "review", "type": "success"},
                {"source": "review", "target": "complete", "type": "success"},
                {"source": "validate", "target": "update_docs", "type": "failure"},
            ],
        },
    ]

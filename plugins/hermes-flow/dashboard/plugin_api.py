"""Hermes Flow dashboard plugin backend.

Mounted at /api/plugins/hermes-flow/ by the dashboard plugin loader.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

try:
    from hermes_cli.web_server import _SESSION_TOKEN
except Exception:  # tests may load without the dashboard runtime
    _SESSION_TOKEN = None

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from flow.daemon import daemon_status, doctor
from flow.db import FlowDB, now_iso
from flow.drafts import create_ai_development_draft, create_development_draft
from flow.pty_sessions import close_pty_session, get_pty_output, list_pty_sessions, send_pty_input
from flow.retention import cleanup_runs
from flow.scheduler import Scheduler
from flow.yaml_io import export_workflow, import_workflow


router = APIRouter()


class RunBody(BaseModel):
    workflow_id: str


class ImportBody(BaseModel):
    file: str
    project_id: Optional[str] = None
    root_dir: Optional[str] = None
    allow_absolute_paths: bool = False
    template_conflict: str = "reuse"


class DraftBody(BaseModel):
    goal: str
    project_id: Optional[str] = None
    root_dir: str = ""
    default_agent_template_id: Optional[str] = None
    use_ai: bool = True


class CleanupBody(BaseModel):
    project_id: Optional[str] = None
    workflow_id: Optional[str] = None
    statuses: list[str] = []
    retain_recent: int = 100
    raw_log_days: int = 30
    dry_run: bool = True


class ProjectBody(BaseModel):
    name: str
    root_dir: str
    default_agent_template_id: Optional[str] = None
    default_validation_commands: list[str] = []
    settings: dict[str, Any] = {}


class AgentTemplateBody(BaseModel):
    name: str
    type: str
    config: dict[str, Any] = {}


class AgentBindingBody(BaseModel):
    agent_template_id: str
    role: str = ""
    config: dict[str, Any] = {}


class WorkflowBody(BaseModel):
    name: str
    goal: str = ""
    project_id: Optional[str] = None
    root_dir: str = ""
    default_agent_template_id: Optional[str] = None
    default_validation_commands: list[str] = []
    max_loop_iterations: int = 5
    max_task_steps: int = 30
    max_duration_minutes: int = 180
    status: str = "confirmed"


class CloneWorkflowBody(BaseModel):
    project_id: Optional[str] = None
    root_dir: str = ""
    name: Optional[str] = None


class TaskBody(BaseModel):
    title: str
    goal: str = ""
    acceptance_criteria: str = ""
    execution_dir: str = ""
    agent_template_id: Optional[str] = None
    validation_commands: list[str] = []
    status: str = "draft"
    position_x: float = 0
    position_y: float = 0
    metadata: dict[str, Any] = {}


class EdgeBody(BaseModel):
    source_task_id: str
    target_task_id: str
    edge_type: str


class ApprovalDecisionBody(BaseModel):
    decision: str


class PtyInputBody(BaseModel):
    text: str


@router.get("/status")
async def status():
    db = FlowDB()
    db.initialize()
    db.seed_builtin_templates()
    return {
        "daemon": daemon_status(),
        "doctor": doctor(),
        "projects": len(db.list_projects()),
        "workflows": len(db.list_workflows()),
    }


@router.get("/projects")
async def projects():
    db = FlowDB()
    db.initialize()
    return {"projects": db.list_projects()}


@router.post("/projects")
async def create_project(body: ProjectBody):
    db = FlowDB()
    db.initialize()
    project_id = db.create_project(
        body.name,
        body.root_dir,
        default_agent_template_id=body.default_agent_template_id,
        default_validation_commands=body.default_validation_commands,
        settings=body.settings,
    )
    return db.get_project(project_id)


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectBody):
    db = FlowDB()
    db.initialize()
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    db.update_project(
        project_id,
        name=body.name,
        root_dir=body.root_dir,
        default_agent_template_id=body.default_agent_template_id,
        default_validation_commands=body.default_validation_commands,
        settings=body.settings,
    )
    return db.get_project(project_id)


@router.get("/agent-templates")
async def agent_templates():
    db = FlowDB()
    db.initialize()
    return {"agent_templates": db.list_agent_templates()}


@router.post("/agent-templates")
async def create_agent_template(body: AgentTemplateBody):
    if body.type not in {"hermes_cli", "acp", "pty_cli"}:
        raise HTTPException(status_code=400, detail="Unsupported agent template type")
    db = FlowDB()
    db.initialize()
    template_id = db.upsert_agent_template(body.name, body.type, body.config)
    return db.get_agent_template(template_id)


@router.patch("/agent-templates/{template_id}")
async def update_agent_template(template_id: str, body: AgentTemplateBody):
    db = FlowDB()
    db.initialize()
    if not db.get_agent_template(template_id):
        raise HTTPException(status_code=404, detail="Agent template not found")
    db.upsert_agent_template(body.name, body.type, body.config, template_id=template_id)
    return db.get_agent_template(template_id)


@router.get("/projects/{project_id}/agent-bindings")
async def project_agent_bindings(project_id: str):
    db = FlowDB()
    db.initialize()
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"bindings": db.list_project_agent_bindings(project_id)}


@router.post("/projects/{project_id}/agent-bindings")
async def create_project_agent_binding(project_id: str, body: AgentBindingBody):
    db = FlowDB()
    db.initialize()
    if not db.get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if not db.get_agent_template(body.agent_template_id):
        raise HTTPException(status_code=404, detail="Agent template not found")
    binding_id = db.create_project_agent_binding(
        project_id,
        body.agent_template_id,
        role=body.role,
        config=body.config,
    )
    return {"binding_id": binding_id, "bindings": db.list_project_agent_bindings(project_id)}


@router.delete("/agent-bindings/{binding_id}")
async def delete_project_agent_binding(binding_id: str):
    db = FlowDB()
    db.initialize()
    db.delete_project_agent_binding(binding_id)
    return {"ok": True}


@router.get("/projects/{project_id}/workflows")
async def project_workflows(project_id: str):
    db = FlowDB()
    db.initialize()
    return {"workflows": db.list_workflows(project_id=project_id, include_templates=False)}


@router.get("/workflows")
async def workflows(project_id: str = "", include_templates: bool = True):
    db = FlowDB()
    db.initialize()
    db.seed_builtin_templates()
    return {"workflows": db.list_workflows(project_id=project_id or None, include_templates=include_templates)}


@router.post("/workflows")
async def create_workflow(body: WorkflowBody):
    db = FlowDB()
    db.initialize()
    workflow_id = db.create_workflow(
        body.name,
        body.goal,
        project_id=body.project_id,
        root_dir=body.root_dir,
        default_agent_template_id=body.default_agent_template_id,
        default_validation_commands=body.default_validation_commands,
        max_loop_iterations=body.max_loop_iterations,
        max_task_steps=body.max_task_steps,
        max_duration_minutes=body.max_duration_minutes,
        status=body.status,
    )
    workflow = db.get_workflow(workflow_id)
    db.save_workflow_version(workflow_id, "dashboard_create", workflow or {})
    return workflow


@router.get("/workflows/{workflow_id}")
async def workflow(workflow_id: str):
    db = FlowDB()
    db.initialize()
    data = db.get_workflow(workflow_id)
    if not data:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return data


@router.patch("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowBody):
    db = FlowDB()
    db.initialize()
    if not db.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.update_workflow(
        workflow_id,
        name=body.name,
        goal=body.goal,
        project_id=body.project_id,
        root_dir=body.root_dir,
        default_agent_template_id=body.default_agent_template_id,
        default_validation_commands=body.default_validation_commands,
        max_loop_iterations=body.max_loop_iterations,
        max_task_steps=body.max_task_steps,
        max_duration_minutes=body.max_duration_minutes,
        status=body.status,
    )
    workflow = db.get_workflow(workflow_id)
    db.save_workflow_version(workflow_id, "dashboard_update", workflow or {})
    return workflow


@router.post("/workflows/{workflow_id}/confirm")
async def confirm_workflow(workflow_id: str):
    db = FlowDB()
    db.initialize()
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.get("template_key"):
        raise HTTPException(status_code=400, detail="Templates must be copied before running")
    db.update_workflow(workflow_id, status="confirmed")
    confirmed = db.get_workflow(workflow_id)
    db.save_workflow_version(workflow_id, "dashboard_confirm", confirmed or {})
    return confirmed


@router.post("/workflows/{workflow_id}/clone")
async def clone_workflow(workflow_id: str, body: CloneWorkflowBody):
    db = FlowDB()
    db.initialize()
    source = db.get_workflow(workflow_id)
    if not source:
        raise HTTPException(status_code=404, detail="Workflow not found")
    clone_id = db.create_workflow(
        body.name or source["name"],
        source.get("goal") or "",
        project_id=body.project_id,
        root_dir=body.root_dir or source.get("root_dir") or "",
        default_agent_template_id=source.get("default_agent_template_id"),
        default_validation_commands=source.get("default_validation_commands") or [],
        max_loop_iterations=source.get("max_loop_iterations") or 5,
        max_task_steps=source.get("max_task_steps") or 30,
        max_duration_minutes=source.get("max_duration_minutes") or 180,
        status="draft",
    )
    task_map: dict[str, str] = {}
    for task in source.get("tasks") or []:
        task_map[task["id"]] = db.add_task(
            clone_id,
            task.get("title") or "Task",
            task.get("goal") or "",
            acceptance_criteria=task.get("acceptance_criteria") or "",
            execution_dir=task.get("execution_dir") or "",
            agent_template_id=task.get("agent_template_id"),
            validation_commands=task.get("validation_commands") or [],
            status="draft",
            position_x=task.get("position_x") or 0,
            position_y=task.get("position_y") or 0,
            metadata={**(task.get("metadata") or {}), "source_template_task_id": task["id"]},
        )
    for edge in source.get("edges") or []:
        source_id = task_map.get(edge["source_task_id"])
        target_id = task_map.get(edge["target_task_id"])
        if source_id and target_id:
            db.add_edge(clone_id, source_id, target_id, edge.get("edge_type") or "dependency")
    cloned = db.get_workflow(clone_id)
    db.save_workflow_version(clone_id, "dashboard_template_copy", {"source_workflow_id": workflow_id, "workflow": cloned})
    return cloned


@router.post("/workflows/{workflow_id}/tasks")
async def create_task(workflow_id: str, body: TaskBody):
    db = FlowDB()
    db.initialize()
    if not db.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.add_task(
        workflow_id,
        body.title,
        body.goal,
        acceptance_criteria=body.acceptance_criteria,
        execution_dir=body.execution_dir,
        agent_template_id=body.agent_template_id,
        validation_commands=body.validation_commands,
        status=body.status,
        position_x=body.position_x,
        position_y=body.position_y,
        metadata=body.metadata,
    )
    workflow = db.get_workflow(workflow_id)
    db.save_workflow_version(workflow_id, "dashboard_task_create", workflow or {})
    return workflow


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskBody):
    db = FlowDB()
    db.initialize()
    db.update_task(
        task_id,
        title=body.title,
        goal=body.goal,
        acceptance_criteria=body.acceptance_criteria,
        execution_dir=body.execution_dir,
        agent_template_id=body.agent_template_id,
        validation_commands=body.validation_commands,
        status=body.status,
        position_x=body.position_x,
        position_y=body.position_y,
        metadata=body.metadata,
    )
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    db = FlowDB()
    db.initialize()
    db.delete_task(task_id)
    return {"ok": True}


@router.post("/workflows/{workflow_id}/edges")
async def create_edge(workflow_id: str, body: EdgeBody):
    db = FlowDB()
    db.initialize()
    if not db.get_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    edge_id = db.add_edge(workflow_id, body.source_task_id, body.target_task_id, body.edge_type)
    workflow = db.get_workflow(workflow_id)
    db.save_workflow_version(workflow_id, "dashboard_edge_create", workflow or {})
    return {"edge_id": edge_id, "workflow": workflow}


@router.patch("/edges/{edge_id}")
async def update_edge(edge_id: str, body: EdgeBody):
    db = FlowDB()
    db.initialize()
    db.update_edge(edge_id, source_task_id=body.source_task_id, target_task_id=body.target_task_id, edge_type=body.edge_type)
    return {"ok": True}


@router.delete("/edges/{edge_id}")
async def delete_edge(edge_id: str):
    db = FlowDB()
    db.initialize()
    db.delete_edge(edge_id)
    return {"ok": True}


@router.post("/runs")
async def run_workflow(body: RunBody):
    try:
        run_id = Scheduler().enqueue_workflow(body.workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FlowDB().get_run_status(run_id)


@router.get("/runs")
async def runs(workflow_id: str = "", limit: int = 50):
    db = FlowDB()
    db.initialize()
    return {"runs": db.list_runs(workflow_id=workflow_id or None, limit=min(max(limit, 1), 200))}


@router.post("/drafts")
async def draft_workflow(body: DraftBody):
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required")
    db = FlowDB()
    db.initialize()
    draft_fn = create_ai_development_draft if body.use_ai else create_development_draft
    return draft_fn(
        db,
        goal=body.goal,
        project_id=body.project_id,
        root_dir=body.root_dir,
        default_agent_template_id=body.default_agent_template_id,
    )


@router.get("/runs/{run_id}")
async def run_status(run_id: str):
    db = FlowDB()
    db.initialize()
    data = db.get_run_summary(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found")
    return data


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    db = FlowDB()
    db.initialize()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") in {"passed", "failed", "guardrail_stopped", "cancelled", "interrupted", "stopped"}:
        return db.get_run_status(run_id)
    db.update_run(run_id, status="cancelled", finished_at=now_iso())
    db.record_event(run_id, "run_cancel_requested", "Workflow run cancellation requested.")
    return db.get_run_status(run_id)


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str):
    db = FlowDB()
    db.initialize()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") in {"passed", "failed", "guardrail_stopped", "cancelled", "interrupted", "stopped"}:
        return db.get_run_status(run_id)
    db.update_run(run_id, status="paused")
    db.record_event(run_id, "run_pause_requested", "Workflow run pause requested.")
    return db.get_run_status(run_id)


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str):
    db = FlowDB()
    db.initialize()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") != "paused":
        return db.get_run_status(run_id)
    db.update_run(run_id, status="pending")
    db.record_event(run_id, "run_resume_requested", "Workflow run resume requested.")
    return db.get_run_status(run_id)


@router.get("/events")
async def recent_events(run_id: str = "", limit: int = 100):
    db = FlowDB()
    db.initialize()
    return {"events": db.list_recent_events(run_id=run_id or None, limit=min(max(limit, 1), 500))}


@router.get("/runs/{run_id}/logs")
async def run_logs(run_id: str, task_id: str = "", tail: int = 8000):
    db = FlowDB()
    db.initialize()
    run = db.get_run_status(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    entries = []
    task_runs = run.get("task_runs", [])
    for task_run in task_runs:
        if task_id and task_run.get("task_id") != task_id:
            continue
        path = Path(task_run.get("log_path") or "")
        text = path.read_text(encoding="utf-8", errors="replace")[-tail:] if path.exists() else ""
        entries.append({"task_id": task_run.get("task_id"), "task_run_id": task_run.get("id"), "log": text})
    return {"logs": entries}


@router.get("/workflows/{workflow_id}/export")
async def export(workflow_id: str, mode: str = "workflow", local_private: bool = False):
    return export_workflow(FlowDB(), workflow_id, mode=mode, local_private=local_private)


@router.post("/imports")
async def import_(body: ImportBody):
    workflow_id = import_workflow(
        FlowDB(),
        Path(body.file),
        project_id=body.project_id,
        root_dir=body.root_dir,
        allow_absolute_paths=body.allow_absolute_paths,
        template_conflict=body.template_conflict,
    )
    return {"workflow_id": workflow_id}


@router.post("/cleanup")
async def cleanup(body: CleanupBody):
    return cleanup_runs(
        FlowDB(),
        project_id=body.project_id,
        workflow_id=body.workflow_id,
        statuses=body.statuses,
        retain_recent=max(1, body.retain_recent),
        raw_log_days=max(1, body.raw_log_days),
        dry_run=body.dry_run,
    )


@router.get("/approvals")
async def approvals(run_id: str = ""):
    db = FlowDB()
    db.initialize()
    return {"approvals": _approval_rows(db, run_id=run_id or None)}


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, body: ApprovalDecisionBody):
    db = FlowDB()
    db.initialize()
    try:
        db.decide_approval(approval_id, body.decision)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "approval_id": approval_id, "decision": body.decision}


@router.get("/pty-sessions")
async def pty_sessions(run_id: str = ""):
    return {"sessions": list_pty_sessions(run_id=run_id or None)}


@router.get("/pty-sessions/{session_id}")
async def pty_session_output(session_id: str, max_chars: int = 8000):
    try:
        return get_pty_output(session_id, max_chars=min(max(max_chars, 1), 60000))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="PTY session not found") from exc


@router.post("/pty-sessions/{session_id}/input")
async def pty_session_input(session_id: str, body: PtyInputBody):
    try:
        return send_pty_input(session_id, body.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="PTY session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/pty-sessions/{session_id}/close")
async def pty_session_close(session_id: str):
    try:
        return close_pty_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="PTY session not found") from exc


@router.websocket("/events")
async def events(websocket: WebSocket):
    if _SESSION_TOKEN:
        token = websocket.query_params.get("token", "")
        if token != _SESSION_TOKEN:
            await websocket.close(code=1008)
            return
    await websocket.accept()
    try:
        while True:
            db = FlowDB()
            db.initialize()
            runs = db.list_runs(limit=20)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "flow.snapshot",
                        "data": {
                            "daemon": daemon_status(),
                            "runs": runs,
                            "events": db.list_recent_events(limit=100),
                            "log_tails": _log_tails(db, runs),
                        },
                    },
                    sort_keys=True,
                )
            )
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


def _log_tails(db: FlowDB, runs: list[dict], *, tail: int = 8000) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for run in runs[:8]:
        run_id = run.get("id")
        if not run_id:
            continue
        status = db.get_run_status(run_id)
        entries = []
        for task_run in (status or {}).get("task_runs", [])[-6:]:
            path = Path(task_run.get("log_path") or "")
            text = path.read_text(encoding="utf-8", errors="replace")[-tail:] if path.exists() else ""
            entries.append({"task_id": task_run.get("task_id"), "task_run_id": task_run.get("id"), "log": text})
        if entries:
            out[run_id] = entries
    return out


def _approval_rows(db: FlowDB, run_id: Optional[str] = None) -> list[dict]:
    rows = db.list_approvals(run_id=run_id)
    for row in rows:
        path = db.get_task_log_path(row.get("run_id") or "", row.get("task_id") or "")
        if path and Path(path).exists():
            row["log_excerpt"] = Path(path).read_text(encoding="utf-8", errors="replace")[-4000:]
        else:
            row["log_excerpt"] = ""
    return rows

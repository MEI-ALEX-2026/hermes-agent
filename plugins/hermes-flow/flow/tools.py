from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import FlowDB


def register_flow_tools(ctx: Any) -> None:
    for spec in _TOOL_SPECS:
        ctx.register_tool(
            name=spec["name"],
            toolset="hermes_flow",
            schema=spec["schema"],
            handler=spec["handler"],
            description=spec["description"],
            emoji="flow",
        )


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=True, sort_keys=True)


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=True, sort_keys=True)


def _list_projects(args: dict, **_: Any) -> str:
    db = FlowDB()
    db.initialize()
    return _ok(db.list_projects())


def _list_workflows(args: dict, **_: Any) -> str:
    db = FlowDB()
    db.initialize()
    return _ok(db.list_workflows(project_id=args.get("project_id") or None, include_templates=bool(args.get("include_templates", True))))


def _get_workflow(args: dict, **_: Any) -> str:
    workflow_id = str(args.get("workflow_id") or "")
    if not workflow_id:
        return _error("workflow_id is required")
    db = FlowDB()
    db.initialize()
    workflow = db.get_workflow(workflow_id)
    return _ok(workflow) if workflow else _error("workflow not found")


def _get_run_status(args: dict, **_: Any) -> str:
    run_id = str(args.get("run_id") or "")
    if not run_id:
        return _error("run_id is required")
    db = FlowDB()
    db.initialize()
    status = db.get_run_status(run_id)
    return _ok(status) if status else _error("run not found")


def _get_run_summary(args: dict, **_: Any) -> str:
    run_id = str(args.get("run_id") or "")
    if not run_id:
        return _error("run_id is required")
    db = FlowDB()
    db.initialize()
    summary = db.get_run_summary(run_id)
    return _ok(summary) if summary else _error("run not found")


def _get_task_log_excerpt(args: dict, **_: Any) -> str:
    run_id = str(args.get("run_id") or "")
    task_id = str(args.get("task_id") or "")
    max_chars = int(args.get("max_chars") or 4000)
    if not run_id or not task_id:
        return _error("run_id and task_id are required")
    db = FlowDB()
    db.initialize()
    log_path = db.get_task_log_path(run_id, task_id)
    if not log_path:
        return _error("task log not found")
    path = Path(log_path)
    if not path.exists():
        return _error("task log file is missing")
    text = path.read_text(encoding="utf-8", errors="replace")
    return _ok({"run_id": run_id, "task_id": task_id, "excerpt": text[-max_chars:]})


_TOOL_SPECS = [
    {
        "name": "flow_list_projects",
        "description": "List Hermes Flow projects.",
        "handler": _list_projects,
        "schema": {
            "name": "flow_list_projects",
            "description": "Read-only: list Hermes Flow projects.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "name": "flow_list_workflows",
        "description": "List Hermes Flow workflows.",
        "handler": _list_workflows,
        "schema": {
            "name": "flow_list_workflows",
            "description": "Read-only: list Hermes Flow workflows for a project or all projects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "include_templates": {"type": "boolean", "default": True},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "name": "flow_get_workflow",
        "description": "Get a Hermes Flow workflow.",
        "handler": _get_workflow,
        "schema": {
            "name": "flow_get_workflow",
            "description": "Read-only: get workflow graph, tasks, and edges.",
            "parameters": {
                "type": "object",
                "properties": {"workflow_id": {"type": "string"}},
                "required": ["workflow_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "name": "flow_get_run_status",
        "description": "Get a Hermes Flow run status.",
        "handler": _get_run_status,
        "schema": {
            "name": "flow_get_run_status",
            "description": "Read-only: get workflow run status and task runs.",
            "parameters": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "name": "flow_get_run_summary",
        "description": "Get a Hermes Flow run summary.",
        "handler": _get_run_summary,
        "schema": {
            "name": "flow_get_run_summary",
            "description": "Read-only: get workflow run events, validation output, and summaries.",
            "parameters": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "name": "flow_get_task_log_excerpt",
        "description": "Get a Hermes Flow task log excerpt.",
        "handler": _get_task_log_excerpt,
        "schema": {
            "name": "flow_get_task_log_excerpt",
            "description": "Read-only: get the tail of a task run log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 4000},
                },
                "required": ["run_id", "task_id"],
                "additionalProperties": False,
            },
        },
    },
]

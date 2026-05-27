from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from .db import FlowDB


def export_workflow(
    db: FlowDB,
    workflow_id: str,
    output: Optional[Path] = None,
    *,
    mode: str = "workflow",
    local_private: bool = False,
) -> dict:
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        raise ValueError(f"Unknown workflow: {workflow_id}")
    if mode not in {"workflow", "template_references", "template_snapshots", "full_local_bundle"}:
        raise ValueError("Unsupported export mode.")
    exported_workflow = _exportable_workflow(workflow, local_private=local_private)
    tasks = [_exportable_task(task, workflow, local_private=local_private) for task in workflow["tasks"]]
    payload = {
        "format": "hermes-flow.workflow.v1",
        "export_mode": mode,
        "local_private": local_private,
        "workflow": exported_workflow,
        "tasks": tasks,
        "edges": workflow["edges"],
    }
    template_ids = {
        workflow.get("default_agent_template_id"),
        *(task.get("agent_template_id") for task in workflow["tasks"]),
    }
    template_ids.discard(None)
    template_ids.discard("")
    if mode in {"template_references", "template_snapshots", "full_local_bundle"}:
        payload["agent_template_references"] = sorted(template_ids)
    if mode in {"template_snapshots", "full_local_bundle"}:
        payload["agent_template_snapshots"] = [
            db.get_agent_template(template_id)
            for template_id in sorted(template_ids)
            if db.get_agent_template(template_id)
        ]
    if mode == "full_local_bundle":
        payload["project"] = db.get_project(workflow["project_id"]) if workflow.get("project_id") else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_dump(payload), encoding="utf-8")
    return payload


def import_workflow(
    db: FlowDB,
    file_path: Path,
    *,
    project_id: Optional[str] = None,
    root_dir: Optional[str] = None,
    allow_absolute_paths: bool = False,
    template_conflict: str = "reuse",
) -> str:
    if template_conflict not in {"reuse", "copy", "overwrite"}:
        raise ValueError("template_conflict must be reuse, copy, or overwrite")
    payload = _load(file_path.read_text(encoding="utf-8"))
    if payload.get("format") != "hermes-flow.workflow.v1":
        raise ValueError("Unsupported Hermes Flow import format.")
    wf = dict(payload.get("workflow") or {})
    tasks = list(payload.get("tasks") or [])
    edges = list(payload.get("edges") or [])
    candidate_root = root_dir if root_dir is not None else str(wf.get("root_dir") or "")
    if candidate_root and Path(candidate_root).is_absolute() and not allow_absolute_paths:
        raise ValueError("Import contains an absolute root_dir; pass allow_absolute_paths after confirmation or remap root_dir.")
    for task in tasks:
        execution_dir = str(task.get("execution_dir") or "")
        if execution_dir and Path(execution_dir).is_absolute() and not allow_absolute_paths:
            raise ValueError("Import contains absolute task execution_dir; remap before execution.")
    template_id_map = _import_template_snapshots(
        db,
        list(payload.get("agent_template_snapshots") or []),
        conflict=template_conflict,
    )
    default_template = wf.get("default_agent_template_id")

    workflow_id = db.create_workflow(
        wf.get("name") or "Imported Workflow",
        wf.get("goal") or "",
        project_id=project_id,
        root_dir=candidate_root,
        default_agent_template_id=template_id_map.get(default_template, default_template),
        default_validation_commands=wf.get("default_validation_commands") or [],
        max_loop_iterations=int(wf.get("max_loop_iterations") or 5),
        max_task_steps=int(wf.get("max_task_steps") or 30),
        max_duration_minutes=int(wf.get("max_duration_minutes") or 180),
    )
    id_map: dict[str, str] = {}
    for task in tasks:
        old_id = task.get("id")
        new_id = db.add_task(
            workflow_id,
            task.get("title") or "Task",
            task.get("goal") or "",
            acceptance_criteria=task.get("acceptance_criteria") or "",
            execution_dir=task.get("execution_dir") or "",
            agent_template_id=template_id_map.get(task.get("agent_template_id"), task.get("agent_template_id")),
            validation_commands=task.get("validation_commands") or [],
            status=task.get("status") or "draft",
            position_x=float(task.get("position_x") or 0),
            position_y=float(task.get("position_y") or 0),
            metadata=task.get("metadata") or {},
        )
        if old_id:
            id_map[str(old_id)] = new_id
    for edge in edges:
        source = id_map.get(str(edge.get("source_task_id")))
        target = id_map.get(str(edge.get("target_task_id")))
        if source and target:
            db.add_edge(workflow_id, source, target, edge.get("edge_type") or "dependency")
    imported = db.get_workflow(workflow_id) or {}
    db.save_workflow_version(workflow_id, "import", imported)
    return workflow_id


def _exportable_workflow(workflow: dict, *, local_private: bool) -> dict:
    fields = {
        key: workflow[key]
        for key in (
            "id",
            "name",
            "goal",
            "root_dir",
            "default_agent_template_id",
            "default_validation_commands",
            "max_loop_iterations",
            "max_task_steps",
            "max_duration_minutes",
            "template_key",
        )
    }
    if not local_private and fields.get("root_dir") and Path(str(fields["root_dir"])).is_absolute():
        fields["root_dir"] = "."
    return fields


def _exportable_task(task: dict, workflow: dict, *, local_private: bool) -> dict:
    exported = dict(task)
    if local_private:
        return exported
    execution_dir = str(exported.get("execution_dir") or "")
    root_dir = str(workflow.get("root_dir") or "")
    if execution_dir and root_dir:
        path = Path(execution_dir)
        root = Path(root_dir)
        if path.is_absolute() and root.is_absolute():
            try:
                exported["execution_dir"] = str(path.relative_to(root))
            except ValueError:
                exported["execution_dir"] = ""
    return exported


def _import_template_snapshots(db: FlowDB, snapshots: list[dict], *, conflict: str) -> dict[str, str]:
    id_map: dict[str, str] = {}
    existing_by_name = {template["name"]: template for template in db.list_agent_templates()}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        old_id = snapshot.get("id")
        name = snapshot.get("name") or "Imported Agent"
        template_type = snapshot.get("type") or "pty_cli"
        config = snapshot.get("config") or {}
        existing = existing_by_name.get(name)
        if existing and conflict == "reuse":
            id_map[old_id] = existing["id"]
        elif existing and conflict == "overwrite":
            db.upsert_agent_template(name, template_type, config, template_id=existing["id"])
            id_map[old_id] = existing["id"]
        else:
            new_name = name
            if existing and conflict == "copy":
                new_name = f"{name} Copy"
            id_map[old_id] = db.upsert_agent_template(new_name, template_type, config)
    return id_map


def _dump(payload: dict) -> str:
    if yaml is not None:
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    return json.dumps(payload, indent=2, sort_keys=False)


def _load(text: str) -> dict:
    if yaml is not None:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Workflow import must contain a mapping.")
    return data

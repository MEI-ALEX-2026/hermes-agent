from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional

from .db import FlowDB


def create_ai_development_draft(
    db: FlowDB,
    *,
    goal: str,
    project_id: Optional[str] = None,
    root_dir: str = "",
    default_agent_template_id: Optional[str] = None,
    command: Optional[str] = None,
    timeout_seconds: int = 120,
) -> dict:
    """Ask an LLM for an editable workflow draft, then fall back locally."""

    draft_command = command or os.getenv("HERMES_FLOW_DRAFT_COMMAND") or "hermes -z"
    try:
        payload = _request_llm_draft(draft_command, goal=goal, root_dir=root_dir, timeout_seconds=timeout_seconds)
        workflow = _create_workflow_from_payload(
            db,
            payload,
            goal=goal,
            project_id=project_id,
            root_dir=root_dir,
            default_agent_template_id=default_agent_template_id,
        )
        db.save_workflow_version(workflow["id"], "ai_draft_generator", workflow)
        return workflow
    except Exception as exc:
        workflow = create_development_draft(
            db,
            goal=goal,
            project_id=project_id,
            root_dir=root_dir,
            default_agent_template_id=default_agent_template_id,
        )
        workflow.setdefault("metadata", {})["draft_fallback_reason"] = str(exc)
        db.save_workflow_version(
            workflow["id"],
            "ai_draft_fallback",
            {"reason": str(exc), "workflow": workflow},
        )
        return workflow


def create_development_draft(
    db: FlowDB,
    *,
    goal: str,
    project_id: Optional[str] = None,
    root_dir: str = "",
    default_agent_template_id: Optional[str] = None,
) -> dict:
    """Create an editable workflow draft for a software development goal.

    This is the v1 entry point used by Dashboard. It deliberately creates a
    draft only; running still requires an explicit user action.
    """

    validation = _suggest_validation(root_dir)
    workflow_id = db.create_workflow(
        _title_from_goal(goal),
        goal,
        project_id=project_id,
        root_dir=root_dir,
        default_agent_template_id=default_agent_template_id,
        default_validation_commands=validation,
        status="draft",
    )
    implement = db.add_task(
        workflow_id,
        "Implement",
        f"Implement the requested change: {goal}",
        acceptance_criteria="Code changes address the requested development goal.",
        validation_commands=[],
        status="draft",
        position_x=0,
        position_y=0,
    )
    test = db.add_task(
        workflow_id,
        "Validate",
        "Run project validation and summarize failures.",
        acceptance_criteria="Validation commands complete successfully.",
        validation_commands=validation,
        status="draft",
        position_x=260,
        position_y=0,
    )
    fix = db.add_task(
        workflow_id,
        "Fix Failures",
        "Repair validation failures using the most recent failure summary.",
        acceptance_criteria="The same validation commands pass after the fix.",
        validation_commands=[],
        status="draft",
        position_x=520,
        position_y=120,
    )
    review = db.add_task(
        workflow_id,
        "Review",
        "Review the implementation, validation output, and file-change summary.",
        acceptance_criteria="Review finds no blocking issue or routes back to fixes.",
        validation_commands=[],
        status="draft",
        position_x=780,
        position_y=0,
    )
    complete = db.add_task(
        workflow_id,
        "Complete",
        "Summarize the final change and verification evidence.",
        acceptance_criteria="A concise completion summary exists.",
        validation_commands=[],
        status="draft",
        position_x=1040,
        position_y=0,
    )
    for source, target, edge_type in [
        (implement, test, "success"),
        (test, review, "success"),
        (test, fix, "failure"),
        (fix, test, "success"),
        (review, complete, "success"),
        (review, fix, "failure"),
    ]:
        db.add_edge(workflow_id, source, target, edge_type)
    workflow = db.get_workflow(workflow_id) or {}
    db.save_workflow_version(workflow_id, "draft_generator", workflow)
    return workflow


def _suggest_validation(root_dir: str) -> list[str]:
    root = Path(root_dir).expanduser() if root_dir else Path.cwd()
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        return ["pytest"]
    if (root / "package.json").exists():
        return ["pnpm test"]
    if (root / "Cargo.toml").exists():
        return ["cargo test"]
    if (root / "go.mod").exists():
        return ["go test ./..."]
    return []


def _title_from_goal(goal: str) -> str:
    clean = " ".join(goal.strip().split())
    if not clean:
        return "Development Workflow Draft"
    return clean[:60]


def _request_llm_draft(command: str, *, goal: str, root_dir: str, timeout_seconds: int) -> dict:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("draft command is empty")
    prompt = _draft_prompt(goal=goal, root_dir=root_dir)
    proc = subprocess.run(
        [*argv, prompt],
        cwd=str(Path(root_dir).expanduser()) if root_dir else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(1, int(timeout_seconds)),
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "draft command failed")[-1000:])
    return _parse_json_payload(proc.stdout)


def _draft_prompt(*, goal: str, root_dir: str) -> str:
    validation = _suggest_validation(root_dir)
    return (
        "Generate a Hermes Flow workflow draft for this software development goal.\n"
        f"Goal: {goal}\n"
        f"Repository root: {root_dir or '.'}\n"
        f"Suggested validation commands: {json.dumps(validation)}\n\n"
        "Return only strict JSON with this shape:\n"
        "{\n"
        '  "name": "short workflow name",\n'
        '  "goal": "workflow goal",\n'
        '  "default_validation_commands": ["command"],\n'
        '  "max_loop_iterations": 5,\n'
        '  "max_task_steps": 30,\n'
        '  "max_duration_minutes": 180,\n'
        '  "tasks": [\n'
        '    {"key":"implement","title":"Implement","goal":"...",'
        '"acceptance_criteria":"...","validation_commands":[],"position_x":0,"position_y":0}\n'
        "  ],\n"
        '  "edges": [{"source":"implement","target":"validate","type":"success"}]\n'
        "}\n"
        "Use only edge type dependency, success, failure, always, or manual. Include failure repair routing when useful."
    )


def _parse_json_payload(text: str) -> dict:
    clean = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, flags=re.DOTALL)
    if fenced:
        clean = fenced.group(1)
    else:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            clean = clean[start : end + 1]
    data = json.loads(clean)
    if not isinstance(data, dict):
        raise ValueError("draft response must be a JSON object")
    return data


def _create_workflow_from_payload(
    db: FlowDB,
    payload: dict[str, Any],
    *,
    goal: str,
    project_id: Optional[str],
    root_dir: str,
    default_agent_template_id: Optional[str],
) -> dict:
    tasks = payload.get("tasks")
    edges = payload.get("edges") or []
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("draft response must include at least one task")
    validation = _string_list(payload.get("default_validation_commands")) or _suggest_validation(root_dir)
    workflow_id = db.create_workflow(
        str(payload.get("name") or _title_from_goal(goal))[:120],
        str(payload.get("goal") or goal),
        project_id=project_id,
        root_dir=root_dir,
        default_agent_template_id=default_agent_template_id,
        default_validation_commands=validation,
        max_loop_iterations=_positive_int(payload.get("max_loop_iterations"), 5),
        max_task_steps=_positive_int(payload.get("max_task_steps"), 30),
        max_duration_minutes=_positive_int(payload.get("max_duration_minutes"), 180),
        status="draft",
    )
    key_to_id: dict[str, str] = {}
    for index, item in enumerate(tasks):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("id") or f"task_{index}")
        task_id = db.add_task(
            workflow_id,
            str(item.get("title") or key or "Task")[:160],
            str(item.get("goal") or ""),
            acceptance_criteria=str(item.get("acceptance_criteria") or ""),
            execution_dir=str(item.get("execution_dir") or ""),
            agent_template_id=str(item.get("agent_template_id") or "") or None,
            validation_commands=_string_list(item.get("validation_commands")),
            status=str(item.get("status") or "draft"),
            position_x=float(item.get("position_x") or index * 260),
            position_y=float(item.get("position_y") or 0),
            metadata={"draft_key": key},
        )
        key_to_id[key] = task_id
    valid_edge_types = {"dependency", "success", "failure", "always", "manual"}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = key_to_id.get(str(edge.get("source") or edge.get("source_task_id") or ""))
        target = key_to_id.get(str(edge.get("target") or edge.get("target_task_id") or ""))
        edge_type = str(edge.get("type") or edge.get("edge_type") or "dependency")
        if source and target and edge_type in valid_edge_types:
            db.add_edge(workflow_id, source, target, edge_type)
    workflow = db.get_workflow(workflow_id)
    if not workflow:
        raise RuntimeError("created draft workflow could not be loaded")
    return workflow


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

"""Hermes Flow plugin registration.

The plugin stays on the public plugin surfaces: CLI command registration,
read-only tool registration, Dashboard routes, and lifecycle hooks.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Dict, Optional

from .flow import cli as flow_cli
from .flow.db import FlowDB
from .flow.paths import ensure_flow_dirs
from .flow.tools import register_flow_tools


_PATH_KEYS = {
    "path",
    "file_path",
    "filepath",
    "target_path",
    "output_path",
    "directory",
    "cwd",
}


def _active_execution_dir() -> Optional[Path]:
    raw = os.getenv("HERMES_FLOW_EXECUTION_DIR", "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except OSError:
        return None


def _is_inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base)
        return True
    except (OSError, ValueError):
        return False


def _extract_candidate_paths(args: Dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for key, value in args.items():
        if key not in _PATH_KEYS or not isinstance(value, str) or not value.strip():
            continue
        try:
            candidates.append(Path(value).expanduser())
        except OSError:
            continue
    return candidates


def _record_flow_event(event_type: str, message: str, payload: Dict[str, Any]) -> None:
    run_id = os.getenv("HERMES_FLOW_RUN_ID", "").strip()
    task_id = os.getenv("HERMES_FLOW_TASK_ID", "").strip()
    if not run_id:
        return
    try:
        db = FlowDB()
        db.initialize()
        db.record_event(
            run_id=run_id,
            task_id=task_id or None,
            event_type=event_type,
            message=message,
            payload=payload,
        )
    except Exception:
        return


def _pre_tool_call(tool_name: str = "", args: Optional[Dict[str, Any]] = None, **_: Any):
    """Best-effort task directory policy for Hermes subprocess executors.

    External PTY executors remain observable-only in v1. This hook only runs
    inside Hermes subprocesses that receive HERMES_FLOW_* environment vars.
    """

    base = _active_execution_dir()
    if base is None or not isinstance(args, dict):
        return None

    for candidate in _extract_candidate_paths(args):
        resolved = candidate if candidate.is_absolute() else base / candidate
        if not _is_inside(resolved, base):
            message = (
                f"Hermes Flow blocked {tool_name}: path is outside task "
                f"execution directory ({base})."
            )
            _record_flow_event(
                "permission_blocked",
                message,
                {
                    "tool_name": tool_name,
                    "path": str(resolved),
                    "execution_dir": str(base),
                    "risk_level": "high",
                },
            )
            return {"action": "block", "message": message}

    if tool_name == "terminal":
        command = args.get("command") or args.get("cmd") or ""
        if isinstance(command, str):
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = []
            if tokens and tokens[0] in {"rm", "sudo", "chmod", "chown", "mkfs"}:
                _record_flow_event(
                    "permission_sensitive_command",
                    "Sensitive terminal command observed.",
                    {
                        "tool_name": tool_name,
                        "command": command,
                        "execution_dir": str(base),
                        "risk_level": "medium",
                    },
                )
    return None


def _pre_approval_request(**kwargs: Any) -> None:
    run_id = os.getenv("HERMES_FLOW_RUN_ID", "").strip()
    task_id = os.getenv("HERMES_FLOW_TASK_ID", "").strip()
    if run_id:
        try:
            db = FlowDB()
            db.initialize()
            command = str(kwargs.get("command") or "")
            db.create_approval(
                run_id=run_id,
                task_id=task_id or None,
                source_task=task_id,
                executor_type="hermes_cli",
                command=command,
                target_path=str(kwargs.get("target_path") or ""),
                trigger_reason=str(kwargs.get("description") or kwargs.get("pattern_key") or "approval requested"),
                execution_dir=os.getenv("HERMES_FLOW_EXECUTION_DIR", ""),
                outside_execution_dir=False,
                risk_level="medium",
            )
        except Exception:
            pass
    _record_flow_event(
        "approval_requested",
        "Permission approval requested.",
        {k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))},
    )


def _post_approval_response(**kwargs: Any) -> None:
    choice = str(kwargs.get("choice") or "")
    mapped = {"once": "allow_once", "session": "allow_run", "deny": "deny"}.get(choice)
    _record_flow_event(
        "approval_decided",
        "Permission approval decided.",
        {
            **{k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))},
            "flow_decision": mapped or choice,
        },
    )


def register(ctx) -> None:
    ensure_flow_dirs()
    db = FlowDB()
    db.initialize()
    db.seed_builtin_templates()

    ctx.register_cli_command(
        name="flow",
        help="Operate Hermes Flow workflow orchestration",
        setup_fn=flow_cli.register_cli,
        handler_fn=flow_cli.flow_command,
        description=(
            "Daemon, diagnostics, run control, logs, and YAML import/export "
            "for Hermes Flow."
        ),
    )
    register_flow_tools(ctx)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("pre_approval_request", _pre_approval_request)
    ctx.register_hook("post_approval_response", _post_approval_response)

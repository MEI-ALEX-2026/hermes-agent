from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .daemon import daemon_status, doctor, process_pending_once, request_stop, run_daemon
from .db import FlowDB
from .scheduler import Scheduler
from .yaml_io import export_workflow, import_workflow


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="flow_command")

    daemon_p = subs.add_parser("daemon", help="Run the Hermes Flow worker daemon")
    daemon_p.add_argument("--interval", type=float, default=5.0, help=argparse.SUPPRESS)
    daemon_p.add_argument("--once", action="store_true", help=argparse.SUPPRESS)

    subs.add_parser("status", help="Show daemon and run status")
    subs.add_parser("stop", help="Request daemon stop")
    subs.add_parser("doctor", help="Check Hermes Flow configuration")

    run_p = subs.add_parser("run", help="Run a workflow")
    run_p.add_argument("workflow_id")
    run_p.add_argument("--wait", action="store_true", help="Run synchronously instead of queueing for the daemon")

    subs.add_parser("tick", help="Claim and run pending workflow runs once")

    logs_p = subs.add_parser("logs", help="Show run logs")
    logs_p.add_argument("run_id")
    logs_p.add_argument("--task-id", default="")
    logs_p.add_argument("--tail", type=int, default=8000)

    export_p = subs.add_parser("export", help="Export workflow YAML")
    export_p.add_argument("workflow_id")
    export_p.add_argument("--output", "-o", default="")
    export_p.add_argument(
        "--mode",
        choices=("workflow", "template_references", "template_snapshots", "full_local_bundle"),
        default="workflow",
    )
    export_p.add_argument("--local-private", action="store_true")

    import_p = subs.add_parser("import", help="Import workflow YAML")
    import_p.add_argument("file")
    import_p.add_argument("--project-id", default="")
    import_p.add_argument("--root-dir", default="")
    import_p.add_argument("--allow-absolute-paths", action="store_true")
    import_p.add_argument("--template-conflict", choices=("reuse", "copy", "overwrite"), default="reuse")

    subparser.set_defaults(func=flow_command)


def flow_command(args: argparse.Namespace) -> int:
    cmd = getattr(args, "flow_command", None)
    if not cmd:
        print("usage: hermes flow {daemon,status,stop,doctor,run,tick,logs,export,import}")
        return 2
    try:
        if cmd == "daemon":
            interrupted = run_daemon(interval_seconds=float(args.interval), once=bool(args.once))
            print(json.dumps({"ok": True, "interrupted_recovered": interrupted}, indent=2, sort_keys=True))
            return 0
        if cmd == "status":
            print(json.dumps(daemon_status(), indent=2, sort_keys=True))
            return 0
        if cmd == "stop":
            path = request_stop()
            print(f"Hermes Flow stop requested: {path}")
            return 0
        if cmd == "doctor":
            report = doctor()
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("ok") else 1
        if cmd == "run":
            scheduler = Scheduler()
            run_id = scheduler.run_workflow(args.workflow_id) if args.wait else scheduler.enqueue_workflow(args.workflow_id)
            print(json.dumps(FlowDB().get_run_status(run_id), indent=2, sort_keys=True))
            return 0
        if cmd == "tick":
            completed = process_pending_once()
            print(json.dumps({"ok": True, "completed_run_ids": completed}, indent=2, sort_keys=True))
            return 0
        if cmd == "logs":
            return _cmd_logs(args)
        if cmd == "export":
            payload = export_workflow(
                FlowDB(),
                args.workflow_id,
                Path(args.output) if args.output else None,
                mode=args.mode,
                local_private=bool(args.local_private),
            )
            if not args.output:
                try:
                    import yaml
                    print(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False))
                except ImportError:
                    print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"Exported workflow {args.workflow_id} to {args.output}")
            return 0
        if cmd == "import":
            workflow_id = import_workflow(
                FlowDB(),
                Path(args.file),
                project_id=args.project_id or None,
                root_dir=args.root_dir or None,
                allow_absolute_paths=bool(args.allow_absolute_paths),
                template_conflict=args.template_conflict,
            )
            print(workflow_id)
            return 0
    except Exception as exc:
        print(f"hermes flow {cmd}: {exc}", file=sys.stderr)
        return 1
    print(f"unknown flow command: {cmd}", file=sys.stderr)
    return 2


def _cmd_logs(args: argparse.Namespace) -> int:
    db = FlowDB()
    run = db.get_run_status(args.run_id)
    if not run:
        print(f"unknown run: {args.run_id}", file=sys.stderr)
        return 1
    paths = []
    if args.task_id:
        log_path = db.get_task_log_path(args.run_id, args.task_id)
        if log_path:
            paths.append(Path(log_path))
    else:
        paths.extend(Path(t["log_path"]) for t in run.get("task_runs", []) if t.get("log_path"))
    for path in paths:
        print(f"==> {path}")
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            print(text[-int(args.tail):])
        else:
            print("(missing log file)")
    return 0

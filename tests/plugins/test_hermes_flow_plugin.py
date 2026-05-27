from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugins" / "hermes-flow"


def _load_plugin_module():
    name = "hermes_flow_plugin_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _import_flow_module(module_name: str):
    root = str(PLUGIN_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    sys.modules.pop(module_name, None)
    return __import__(module_name, fromlist=["*"])


class FakeCtx:
    def __init__(self):
        self.cli = []
        self.tools = []
        self.hooks = []

    def register_cli_command(self, **kwargs):
        self.cli.append(kwargs)

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_hook(self, name, fn):
        self.hooks.append((name, fn))


def test_register_wires_cli_read_only_tools_hooks_and_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path))
    plugin = _load_plugin_module()
    ctx = FakeCtx()

    plugin.register(ctx)

    assert [entry["name"] for entry in ctx.cli] == ["flow"]
    assert {tool["name"] for tool in ctx.tools} == {
        "flow_list_projects",
        "flow_list_workflows",
        "flow_get_workflow",
        "flow_get_run_status",
        "flow_get_run_summary",
        "flow_get_task_log_excerpt",
    }
    assert {name for name, _fn in ctx.hooks} == {
        "pre_tool_call",
        "pre_approval_request",
        "post_approval_response",
    }
    assert (tmp_path / "data" / "flow.db").exists()


def test_bundled_flow_plugin_autoloads_without_enabled_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    pmod = _import_flow_module("hermes_cli.plugins")
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "hermes-flow").symlink_to(PLUGIN_DIR, target_is_directory=True)
    monkeypatch.setattr(pmod, "get_bundled_plugins_dir", lambda: bundled)
    monkeypatch.setattr(pmod, "get_hermes_home", lambda: tmp_path / "home")
    monkeypatch.setattr(pmod, "_get_enabled_plugins", lambda: set())
    monkeypatch.setattr(pmod, "_get_disabled_plugins", lambda: set())

    manager = pmod.PluginManager()
    manager.discover_and_load(force=True)

    loaded = {entry["key"]: entry for entry in manager.list_plugins()}
    assert loaded["hermes-flow"]["enabled"] is True
    assert "flow" in manager._cli_commands


def test_db_seeds_required_builtin_templates(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path))
    db_mod = _import_flow_module("flow.db")

    db = db_mod.FlowDB()
    db.initialize()
    db.seed_builtin_templates()

    workflows = db.list_workflows(include_templates=True)
    by_key = {wf["template_key"]: wf for wf in workflows if wf["template_key"]}
    assert set(by_key) == {
        "feature_until_green",
        "bugfix_loop",
        "refactor_with_guardrails",
        "docs_validation",
    }
    feature = db.get_workflow(by_key["feature_until_green"]["id"])
    edge_types = {(edge["edge_type"], edge["source_task_id"], edge["target_task_id"]) for edge in feature["edges"]}
    assert any(edge[0] == "failure" for edge in edge_types)
    assert len(feature["tasks"]) == 4


def test_read_only_tools_return_workflow_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path))
    tools_mod = _import_flow_module("flow.tools")
    db_mod = _import_flow_module("flow.db")

    db = db_mod.FlowDB()
    db.initialize()
    project_id = db.create_project("Repo", str(tmp_path))
    workflow_id = db.create_workflow("Flow", "Goal", project_id=project_id, root_dir=str(tmp_path))
    db.add_task(workflow_id, "Task", "Do work")

    projects = json.loads(tools_mod._list_projects({}))
    workflows = json.loads(tools_mod._list_workflows({"project_id": project_id}))
    workflow = json.loads(tools_mod._get_workflow({"workflow_id": workflow_id}))

    assert projects["ok"] is True
    assert projects["data"][0]["id"] == project_id
    assert workflows["data"][0]["id"] == workflow_id
    assert workflow["data"]["tasks"][0]["title"] == "Task"


def test_scheduler_runs_serial_success_route_with_pty_executor(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    agent_id = db.upsert_agent_template(
        "Echo",
        "pty_cli",
        {"command": f"{sys.executable} -c \"print('ran')\""},
    )
    workflow_id = db.create_workflow(
        "Serial",
        "Run two tasks",
        root_dir=str(tmp_path),
        default_agent_template_id=agent_id,
    )
    first = db.add_task(workflow_id, "First", "Run first")
    second = db.add_task(workflow_id, "Second", "Run second")
    db.add_edge(workflow_id, first, second, "success")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    run = db.get_run_status(run_id)

    assert run["status"] == "passed"
    assert run["executed_steps"] == 2
    assert [task_run["status"] for task_run in run["task_runs"]] == ["passed", "passed"]


def test_scheduler_routes_plain_dependency_edges_and_updates_task_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    agent_id = db.upsert_agent_template(
        "Echo",
        "pty_cli",
        {"command": f"{sys.executable} -c \"print('dependency')\""},
    )
    workflow_id = db.create_workflow(
        "Dependency",
        "Run dependency edge",
        root_dir=str(tmp_path),
        default_agent_template_id=agent_id,
    )
    first = db.add_task(workflow_id, "Prepare", "Run first")
    second = db.add_task(workflow_id, "Dependent", "Run after dependency")
    db.add_edge(workflow_id, first, second, "dependency")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    run = db.get_run_status(run_id)
    workflow = db.get_workflow(workflow_id)

    assert run["status"] == "passed"
    assert [task_run["status"] for task_run in run["task_runs"]] == ["passed", "passed"]
    assert [task["status"] for task in workflow["tasks"]] == ["passed", "passed"]


def test_pty_executor_preserves_nonzero_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    fail_id = db.upsert_agent_template(
        "Fail",
        "pty_cli",
        {"command": f"{sys.executable} -c \"import sys; print('failed'); sys.exit(7)\""},
    )
    repair_id = db.upsert_agent_template(
        "Repair",
        "pty_cli",
        {"command": f"{sys.executable} -c \"print('repair')\""},
    )
    workflow_id = db.create_workflow("Failure Route", "Route failure", root_dir=str(tmp_path), default_agent_template_id=fail_id)
    first = db.add_task(workflow_id, "Fail", "Fail", agent_template_id=fail_id)
    second = db.add_task(workflow_id, "Repair", "Repair", agent_template_id=repair_id)
    db.add_edge(workflow_id, first, second, "failure")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    run = db.get_run_status(run_id)
    by_task = {task_run["task_id"]: task_run for task_run in run["task_runs"]}

    assert run["status"] == "failed"
    assert by_task[first]["status"] == "failed"
    assert by_task[first]["exit_code"] == 7
    assert by_task[second]["status"] == "passed"


def test_scheduler_runs_optional_ai_review_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    code = "import os; print('review' if os.environ.get('HERMES_FLOW_REVIEW') else 'run')"
    agent_id = db.upsert_agent_template(
        "Reviewer",
        "pty_cli",
        {"command": f"{sys.executable} -c \"{code}\""},
    )
    workflow_id = db.create_workflow("Review", "Review task", root_dir=str(tmp_path), default_agent_template_id=agent_id)
    db.add_task(workflow_id, "Task", "Do work", metadata={"ai_review_enabled": True})

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    summary = db.get_run_summary(run_id)

    assert summary["status"] == "passed"
    assert any(item["kind"] == "review" for item in summary["summaries"])
    assert any(event["type"] == "ai_review_finished" for event in summary["events"])


def test_scheduler_guardrail_stops_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    agent_id = db.upsert_agent_template(
        "Echo",
        "pty_cli",
        {"command": f"{sys.executable} -c \"print('loop')\""},
    )
    workflow_id = db.create_workflow(
        "Cycle",
        "Stop loop",
        root_dir=str(tmp_path),
        default_agent_template_id=agent_id,
        max_loop_iterations=1,
        max_task_steps=30,
    )
    task = db.add_task(workflow_id, "Loop", "Loop once")
    db.add_edge(workflow_id, task, task, "success")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    summary = db.get_run_summary(run_id)

    assert summary["status"] == "guardrail_stopped"
    assert summary["guardrail_reason"] == "max_loop_iterations"
    guardrail_event = next(event for event in summary["events"] if event["type"] == "guardrail_stopped")
    assert guardrail_event["payload"]["loop_path"]
    assert "elapsed_seconds" in guardrail_event["payload"]
    assert "executed_steps" in guardrail_event["payload"]


def test_yaml_export_import_rejects_absolute_paths_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    yaml_mod = _import_flow_module("flow.yaml_io")

    db = db_mod.FlowDB()
    db.initialize()
    workflow_id = db.create_workflow("Export", "Goal", root_dir=".")
    db.add_task(workflow_id, "Task", "Do work", execution_dir="src")
    out = tmp_path / "workflow.yaml"

    payload = yaml_mod.export_workflow(db, workflow_id, out)
    imported_id = yaml_mod.import_workflow(db, out)
    assert payload["format"] == "hermes-flow.workflow.v1"
    assert db.get_workflow(imported_id)["name"] == "Export"

    bad = tmp_path / "bad.yaml"
    text = out.read_text(encoding="utf-8").replace("root_dir: .", f"root_dir: {tmp_path}")
    bad.write_text(text, encoding="utf-8")
    try:
        yaml_mod.import_workflow(db, bad)
    except ValueError as exc:
        assert "absolute root_dir" in str(exc)
    else:
        raise AssertionError("absolute import should require confirmation")


def test_draft_generator_creates_editable_loop_and_version(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    drafts_mod = _import_flow_module("flow.drafts")

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    db = db_mod.FlowDB()
    db.initialize()

    workflow = drafts_mod.create_development_draft(
        db,
        goal="Add a retry helper",
        root_dir=str(tmp_path),
    )

    assert workflow["name"] == "Add a retry helper"
    assert [task["title"] for task in workflow["tasks"]] == [
        "Implement",
        "Validate",
        "Fix Failures",
        "Review",
        "Complete",
    ]
    assert any(edge["edge_type"] == "failure" for edge in workflow["edges"])
    assert workflow["default_validation_commands"] == ["pytest"]
    assert workflow["status"] == "draft"
    with db.connect() as conn:
        versions = conn.execute(
            "SELECT source FROM workflow_versions WHERE workflow_id = ?",
            (workflow["id"],),
        ).fetchall()
    assert [row["source"] for row in versions] == ["draft_generator"]


def test_ai_draft_generator_uses_llm_json_and_records_version(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    drafts_mod = _import_flow_module("flow.drafts")

    script = tmp_path / "draft_agent.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({"
        "'name':'LLM Draft',"
        "'goal':'Generated goal',"
        "'default_validation_commands':['pytest tests/unit'],"
        "'max_loop_iterations':3,"
        "'tasks':["
        "{'key':'build','title':'Build','goal':'Do work','position_x':5,'position_y':7},"
        "{'key':'validate','title':'Validate','goal':'Run tests','validation_commands':['pytest tests/unit'],'position_x':260,'position_y':7}"
        "],"
        "'edges':[{'source':'build','target':'validate','type':'success'},{'source':'validate','target':'build','type':'failure'}]"
        "}))\n",
        encoding="utf-8",
    )
    db = db_mod.FlowDB()
    db.initialize()

    workflow = drafts_mod.create_ai_development_draft(
        db,
        goal="Add generated workflow",
        root_dir=str(tmp_path),
        command=f"{sys.executable} {script}",
    )

    assert workflow["name"] == "LLM Draft"
    assert workflow["status"] == "draft"
    assert workflow["default_validation_commands"] == ["pytest tests/unit"]
    assert [task["title"] for task in workflow["tasks"]] == ["Build", "Validate"]
    assert {edge["edge_type"] for edge in workflow["edges"]} == {"success", "failure"}
    with db.connect() as conn:
        versions = conn.execute(
            "SELECT source FROM workflow_versions WHERE workflow_id = ? ORDER BY version",
            (workflow["id"],),
        ).fetchall()
    assert [row["source"] for row in versions] == ["ai_draft_generator"]


def test_scheduler_requires_confirmed_workflow_before_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    workflow_id = db.create_workflow("Draft", "Goal", root_dir=str(tmp_path), status="draft")
    db.add_task(workflow_id, "Task", "Do work")

    try:
        scheduler_mod.Scheduler(db).enqueue_workflow(workflow_id)
    except ValueError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("draft workflows must not be runnable")

    db.update_workflow(workflow_id, status="confirmed")
    run_id = scheduler_mod.Scheduler(db).enqueue_workflow(workflow_id)
    assert db.get_run_status(run_id)["status"] == "pending"


def test_daemon_tick_claims_pending_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")
    daemon_mod = _import_flow_module("flow.daemon")

    db = db_mod.FlowDB()
    db.initialize()
    agent_id = db.upsert_agent_template(
        "Echo",
        "pty_cli",
        {"command": f"{sys.executable} -c \"print('queued')\""},
    )
    workflow_id = db.create_workflow("Queued", "Run from daemon", root_dir=str(tmp_path), default_agent_template_id=agent_id)
    db.add_task(workflow_id, "Task", "Run")
    run_id = scheduler_mod.Scheduler(db).enqueue_workflow(workflow_id)

    completed = daemon_mod.process_pending_once(max_workers=1)
    run = db.get_run_status(run_id)

    assert completed == [run_id]
    assert run["status"] == "passed"
    assert run["task_runs"][0]["status"] == "passed"


def test_daemon_start_preserves_pending_and_requeues_ready_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")

    db = db_mod.FlowDB()
    db.initialize()
    workflow_id = db.create_workflow("Queued", "Keep queued", root_dir=str(tmp_path))
    pending_id = db.create_run(workflow_id, status="pending")
    ready_id = db.create_run(workflow_id, status="ready")
    running_id = db.create_run(workflow_id, status="running")

    interrupted = db.recover_interrupted()

    assert interrupted == 1
    assert db.get_run(pending_id)["status"] == "pending"
    assert db.get_run(ready_id)["status"] == "pending"
    assert db.get_run(running_id)["status"] == "interrupted"


def test_export_import_template_snapshots_with_copy_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    yaml_mod = _import_flow_module("flow.yaml_io")

    db = db_mod.FlowDB()
    db.initialize()
    template_id = db.upsert_agent_template("Local Claude", "pty_cli", {"command": "claude"})
    workflow_id = db.create_workflow(
        "Snapshot",
        "Export with template",
        root_dir=str(tmp_path),
        default_agent_template_id=template_id,
    )
    db.add_task(workflow_id, "Task", "Do work", execution_dir=str(tmp_path / "src"), agent_template_id=template_id)
    out = tmp_path / "snapshot.yaml"

    payload = yaml_mod.export_workflow(db, workflow_id, out, mode="template_snapshots")
    imported_id = yaml_mod.import_workflow(db, out, template_conflict="copy")
    imported = db.get_workflow(imported_id)
    templates = db.list_agent_templates()

    assert payload["agent_template_snapshots"][0]["name"] == "Local Claude"
    assert len([t for t in templates if t["name"].startswith("Local Claude")]) == 2
    assert imported["root_dir"] == "."
    assert imported["tasks"][0]["execution_dir"] == "src"


def test_db_approval_decision_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")

    db = db_mod.FlowDB()
    db.initialize()
    workflow_id = db.create_workflow("Approvals", "Goal")
    run_id = db.create_run(workflow_id)
    approval_id = db.create_approval(
        run_id=run_id,
        source_task="Task",
        executor_type="hermes_cli",
        command="rm file",
        target_path="/tmp/file",
        trigger_reason="dangerous command",
        execution_dir=str(tmp_path),
        outside_execution_dir=True,
        risk_level="high",
    )
    db.decide_approval(approval_id, "allow_run")

    approval = db.list_approvals(run_id=run_id)[0]
    assert approval["decision"] == "allow_run"
    assert approval["risk_level"] == "high"


def test_dashboard_crud_api_for_project_workflow_task_edge(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    spec = importlib.util.spec_from_file_location(
        "hermes_flow_dashboard_api_test",
        PLUGIN_DIR / "dashboard" / "plugin_api.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["hermes_flow_dashboard_api_test"] = module
    spec.loader.exec_module(module)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)

    project = client.post("/projects", json={"name": "Repo", "root_dir": str(tmp_path)}).json()
    template = client.post(
        "/agent-templates",
        json={"name": "Hermes Dev", "type": "pty_cli", "config": {"command": "true"}},
    ).json()
    binding = client.post(
        f"/projects/{project['id']}/agent-bindings",
        json={"agent_template_id": template["id"], "role": "implementer"},
    ).json()
    workflow = client.post(
        "/workflows",
        json={"name": "Flow", "goal": "Goal", "project_id": project["id"], "root_dir": str(tmp_path)},
    ).json()
    workflow = client.post(
        f"/workflows/{workflow['id']}/tasks",
        json={"title": "Implement", "goal": "Do it", "position_x": 10, "position_y": 20},
    ).json()
    first_task = workflow["tasks"][0]
    workflow = client.post(
        f"/workflows/{workflow['id']}/tasks",
        json={"title": "Validate", "goal": "Test it", "position_x": 100, "position_y": 20},
    ).json()
    second_task = workflow["tasks"][1]
    edge = client.post(
        f"/workflows/{workflow['id']}/edges",
        json={"source_task_id": first_task["id"], "target_task_id": second_task["id"], "edge_type": "success"},
    ).json()

    assert project["name"] == "Repo"
    assert binding["bindings"][0]["role"] == "implementer"
    assert client.get(f"/projects/{project['id']}/agent-bindings").json()["bindings"][0]["agent_template_name"] == "Hermes Dev"
    assert edge["workflow"]["edges"][0]["edge_type"] == "success"
    assert client.get(f"/workflows/{workflow['id']}").json()["tasks"][0]["title"] == "Implement"
    moved = dict(first_task)
    moved["position_x"] = 222
    moved["position_y"] = 333
    assert client.patch(f"/tasks/{first_task['id']}", json=moved).json()["ok"] is True
    reloaded = client.get(f"/workflows/{workflow['id']}").json()
    reloaded_task = next(task for task in reloaded["tasks"] if task["id"] == first_task["id"])
    assert reloaded_task["position_x"] == 222
    assert reloaded_task["position_y"] == 333
    client.patch(f"/workflows/{workflow['id']}", json={**workflow, "status": "draft"})
    assert client.post("/runs", json={"workflow_id": workflow["id"]}).status_code == 409
    confirmed = client.post(f"/workflows/{workflow['id']}/confirm").json()
    assert confirmed["status"] == "confirmed"
    run = client.post("/runs", json={"workflow_id": workflow["id"]}).json()
    assert run["status"] == "pending"
    paused = client.post(f"/runs/{run['id']}/pause").json()
    assert paused["status"] == "paused"
    resumed = client.post(f"/runs/{run['id']}/resume").json()
    assert resumed["status"] == "pending"
    cancelled = client.post(f"/runs/{run['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert client.patch(
        f"/edges/{edge['edge_id']}",
        json={"source_task_id": first_task["id"], "target_task_id": second_task["id"], "edge_type": "always"},
    ).json()["ok"] is True
    assert client.delete(f"/agent-bindings/{binding['binding_id']}").json()["ok"] is True
    templates = [wf for wf in client.get("/workflows?include_templates=true").json()["workflows"] if wf.get("template_key")]
    cloned = client.post(
        f"/workflows/{templates[0]['id']}/clone",
        json={"project_id": project["id"], "root_dir": str(tmp_path)},
    ).json()
    assert cloned["status"] == "draft"
    assert cloned["project_id"] == project["id"]
    assert cloned["template_key"] is None
    assert cloned["tasks"]
    client.close()


def test_pty_idle_sets_waiting_input_without_routing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    agent_id = db.upsert_agent_template(
        "Idle",
        "pty_cli",
        {"command": f"{sys.executable} -c \"import time; time.sleep(5)\"", "idle_timeout_seconds": 1},
    )
    workflow_id = db.create_workflow("Idle Flow", "Wait for input", root_dir=str(tmp_path), default_agent_template_id=agent_id)
    first = db.add_task(workflow_id, "Prompt", "Wait")
    second = db.add_task(workflow_id, "After", "Should not run")
    db.add_edge(workflow_id, first, second, "success")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    run = db.get_run_status(run_id)

    assert run["status"] == "waiting_input"
    assert len(run["task_runs"]) == 1
    assert run["task_runs"][0]["status"] == "waiting_input"


def test_pty_takeover_accepts_user_input_and_records_event(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")
    pty_mod = sys.modules["flow.pty_sessions"]

    db = db_mod.FlowDB()
    db.initialize()
    code = "import sys; print('ready', flush=True); line=sys.stdin.readline(); print('got:' + line.strip(), flush=True)"
    agent_id = db.upsert_agent_template(
        "Interactive",
        "pty_cli",
        {"command": f"{sys.executable} -c \"{code}\"", "idle_timeout_seconds": 1},
    )
    workflow_id = db.create_workflow("Interactive Flow", "Wait for user", root_dir=str(tmp_path), default_agent_template_id=agent_id)
    db.add_task(workflow_id, "Prompt", "Wait")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    sessions = pty_mod.list_pty_sessions(run_id=run_id)

    assert len(sessions) == 1
    session_id = sessions[0]["id"]
    pty_mod.send_pty_input(session_id, "hello\n")

    output = ""
    for _ in range(20):
        output = pty_mod.get_pty_output(session_id)["output"]
        if "got:hello" in output:
            break
        import time
        time.sleep(0.1)
    pty_mod.close_pty_session(session_id)

    assert "ready" in output
    assert "got:hello" in output
    events = db.list_recent_events(run_id=run_id)
    assert any(event["type"] == "pty_user_input" for event in events)


def test_pty_takeover_completion_resumes_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")
    pty_mod = sys.modules["flow.pty_sessions"]

    db = db_mod.FlowDB()
    db.initialize()
    code = "import sys; print('ready', flush=True); line=sys.stdin.readline(); print('done:' + line.strip(), flush=True)"
    interactive_id = db.upsert_agent_template(
        "Interactive",
        "pty_cli",
        {"command": f"{sys.executable} -c \"{code}\"", "idle_timeout_seconds": 1},
    )
    echo_id = db.upsert_agent_template(
        "Echo",
        "pty_cli",
        {"command": f"{sys.executable} -c \"print('after')\""},
    )
    workflow_id = db.create_workflow("Interactive Resume", "Resume", root_dir=str(tmp_path), default_agent_template_id=interactive_id)
    first = db.add_task(workflow_id, "Prompt", "Wait")
    second = db.add_task(workflow_id, "After", "Run after input", agent_template_id=echo_id)
    db.add_edge(workflow_id, first, second, "success")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    session_id = pty_mod.list_pty_sessions(run_id=run_id)[0]["id"]
    pty_mod.send_pty_input(session_id, "go\n")

    run = {}
    for _ in range(40):
        run = db.get_run_status(run_id) or {}
        if run.get("status") == "passed":
            break
        import time
        time.sleep(0.1)

    assert run["status"] == "passed"
    assert [task_run["status"] for task_run in run["task_runs"]] == ["passed", "passed"]
    events = db.list_recent_events(run_id=run_id)
    assert any(event["type"] == "pty_completed" for event in events)


def test_acp_executor_runs_configured_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FLOW_HOME", str(tmp_path / "flow-home"))
    db_mod = _import_flow_module("flow.db")
    scheduler_mod = _import_flow_module("flow.scheduler")

    db = db_mod.FlowDB()
    db.initialize()
    code = "import os,sys; prompt=sys.stdin.read(); print('session=' + os.environ.get('HERMES_FLOW_ACP_SESSION_ID','')); print('prompt=' + prompt[:8])"
    agent_id = db.upsert_agent_template(
        "ACP Echo",
        "acp",
        {"command": f"{sys.executable} -c \"{code}\"", "prompt_mode": "stdin"},
    )
    workflow_id = db.create_workflow(
        "ACP Flow",
        "Run ACP executor",
        root_dir=str(tmp_path),
        default_agent_template_id=agent_id,
    )
    db.add_task(workflow_id, "ACP Task", "Execute through ACP runtime")

    run_id = scheduler_mod.Scheduler(db).run_workflow(workflow_id)
    run = db.get_run_status(run_id)
    summary = db.get_run_summary(run_id)

    assert run["status"] == "passed"
    assert run["task_runs"][0]["executor_type"] == "acp"
    task_summary = next(item for item in summary["summaries"] if item["kind"] == "task")
    assert task_summary["payload"]["executor"]["session_id"] == run_id
    assert "session=" in task_summary["payload"]["output_excerpt"]

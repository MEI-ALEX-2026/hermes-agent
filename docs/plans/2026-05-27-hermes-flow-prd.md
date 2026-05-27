# Hermes Flow v1 PRD and Architecture Draft

**Goal:** Build a local Hermes plugin for visual AI workflow orchestration focused on software development loops. Hermes Flow lets users design, run, observe, and improve workflows such as feature implementation, test failure repair, retesting, and review.

**Plugin boundary:** Hermes Flow must live outside Hermes core, installed under `~/.hermes/plugins/hermes-flow/`. It must use stable plugin surfaces only: plugin registration, CLI subcommands, Dashboard plugin APIs, hooks, registered tools, and subprocess-based execution. It must not patch `run_agent.py`, `cli.py`, `gateway/run.py`, or other core files.

**Primary UX:** Hermes Dashboard. CLI exists for daemon operation, diagnostics, rescue, and automation.

---

## 1. Product Scope

Hermes Flow v1 is a software-development workflow orchestrator, not a general-purpose business process platform. The primary use case is a controlled development loop:

```text
Implement feature -> Run tests -> Fix failures -> Run tests again -> Complete
```

Workflows are visual task graphs. Nodes represent tasks. Edges represent dependencies and routing. A workflow may contain cycles, such as routing from a failed test task back to a bug-fix task, but every run is protected by hard stop limits.

v1 explicitly does not include:

- general low-code business workflow automation;
- multiplayer collaborative canvas editing;
- system-level sandboxing for external CLI agents;
- complex condition-expression editing;
- parallel task execution inside one workflow;
- automatic terminal replies for external CLI agents.

The data model should leave room for broader orchestration later, but v1 UI, templates, agent categories, and validation behavior are optimized for code projects.

---

## 2. Core Concepts

### Project

A project binds Hermes Flow to a codebase root directory. The Dashboard first asks the user to select or create a project.

Project bindings may define:

- root directory;
- default agent templates by role;
- default validation commands;
- default workflow settings.

### Agent Template

Agent templates define execution capability, not a fixed directory. A task chooses an agent template and an execution directory. The same template can run in many directories.

Template types:

- `hermes_cli`: run a Hermes profile through the `hermes` CLI in a subprocess;
- `acp`: run an ACP-compatible agent session;
- `pty_cli`: run an external CLI agent, such as Claude Code, OpenCode, or a custom command, through a PTY.

Templates are global, but workflows can export template snapshots for portability.

### Workflow

A workflow is a task graph with defaults and guardrails.

Workflow defaults may include:

- `root_dir`;
- default agent template;
- default validation commands;
- max loop iterations;
- max task steps;
- max duration.

### Task

Each task supports:

- title;
- task goal;
- acceptance criteria;
- execution directory;
- selected agent template;
- execution status;
- dependency relationships;
- success routing;
- failure routing;
- always-run routing.

### Run

A run is one execution of a workflow. Runs have task runs, structured events, raw logs, validation outputs, summaries, approval decisions, and analysis results.

---

## 3. Workflow Model

Nodes are tasks. Edges are typed relationships.

Edge types:

- `dependency`: target waits for source to satisfy readiness requirements;
- `success`: source passed, route to target;
- `failure`: source failed or validation did not pass, route to target;
- `always`: source finished, route to target regardless of pass/fail;
- `manual`: stored and displayed in v1, reserved for later manual branch selection.

The UI may expose these as "parent task", "success task", "failure task", and "always run task" fields, while the data model stores explicit edge types.

One workflow run executes serially: only one task in that workflow runs at a time. Multiple workflow runs may run concurrently.

---

## 4. Task States

v1 task status values:

```text
draft
pending
ready
running
waiting_input
waiting_approval
validating
reviewing
passed
failed
skipped
stopped
guardrail_stopped
cancelled
interrupted
```

Status meanings:

- `draft`: not ready to run;
- `pending`: waiting for dependency or route decision;
- `ready`: eligible to execute;
- `running`: executor is active;
- `waiting_input`: PTY CLI task needs user input;
- `waiting_approval`: permission approval is pending;
- `validating`: validation commands are running;
- `reviewing`: optional AI review is running;
- `passed`: task passed execution and validation;
- `failed`: task failed execution or validation;
- `skipped`: skipped by routing;
- `stopped`: stopped by user or normal system stop;
- `guardrail_stopped`: stopped by loop, step, or duration guardrail;
- `cancelled`: cancelled by user;
- `interrupted`: daemon, process, or host interruption.

---

## 5. Guardrails

All workflow runs must have stop protection.

Default values:

- `max_loop_iterations`: 5;
- `max_task_steps`: 30;
- `max_duration_minutes`: 180.

If any guardrail triggers:

1. stop automatic progression;
2. mark the current task and workflow run as `guardrail_stopped`;
3. write a structured event with the trigger reason, current task, loop path, elapsed time, and executed step count;
4. show a clear Dashboard explanation;
5. allow the user to modify limits, edit the graph, rerun from a node, or end the run.

---

## 6. Validation

Default validation is command-based. AI review is off by default.

Each task can define validation commands. Commands run in the task execution directory. Exit codes and summarized output determine validation status.

Optional AI review can be configured at the task or workflow level. If enabled, an explicit review agent evaluates:

- task goal;
- acceptance criteria;
- execution log summary;
- validation command output;
- file-change summary.

Review outcomes:

- `passed`: route through success edges;
- `failed`: route through failure edges;
- `inconclusive`: default to failure routing or stop for user handling, depending on task configuration.

---

## 7. Execution Model

Hermes Flow has a background worker/daemon. The Dashboard is a control plane and must not be required to stay open for a workflow to keep running.

v1 daemon responsibilities:

- claim and schedule workflow runs;
- keep single-workflow execution serial;
- allow multiple workflow runs concurrently;
- launch executors;
- collect logs;
- write SQLite state;
- broadcast WebSocket events;
- handle pause, cancel, interruption, and recovery;
- mark stale running tasks as `interrupted` on restart when they cannot be recovered.

### Hermes CLI Executor

v1 runs Hermes Profile tasks through the `hermes` CLI as a subprocess. This avoids direct dependency on `AIAgent` internals.

The daemon injects context through environment variables, such as:

```text
HERMES_FLOW_WORKFLOW_ID
HERMES_FLOW_RUN_ID
HERMES_FLOW_TASK_ID
HERMES_FLOW_EXECUTION_DIR
```

Hermes Flow hooks can use these variables inside the subprocess to link tool calls, approvals, and logs to the active task.

### ACP Executor

ACP is the preferred standard path for compatible agents. Hermes currently exposes an ACP server surface for editor clients and structured interaction. Hermes Flow should define an ACP executor interface for:

- session creation or reuse;
- prompt submission;
- event streaming;
- cancellation;
- approval bridging;
- session recovery where supported.

ACP support may be phased in after the subprocess and PTY executors are stable.

### PTY CLI Executor

External CLI agents, such as Claude Code and OpenCode, run through a PTY.

v1 behavior:

- start the command in the task execution directory;
- stream terminal output to logs and Dashboard;
- detect idle or prompt-like waiting states best-effort;
- set status to `waiting_input`;
- let the user take over the terminal from the Dashboard;
- record all user input as structured events;
- never auto-answer prompts in v1.

Future versions may add template-level automatic interaction strategies based on recorded patterns.

---

## 8. Permission Model

v1 permission strength differs by executor.

Hermes executors are controlled execution. They can use plugin hooks and tool-call checks to enforce directory policy:

- task execution directory: automatic read/write;
- outside execution directory: approval or block;
- dangerous command: approval.

External CLI executors are observable execution in v1. Hermes Flow sets `cwd`, injects rules into prompts, records logs, and summarizes file changes. It does not claim system-level filesystem sandboxing for external CLI processes.

Dashboard approval requests must show:

- source task;
- executor type;
- command or file path;
- trigger reason;
- execution directory;
- target path;
- whether the operation is outside the execution directory;
- risk level;
- relevant log excerpt.

v1 approval actions:

- allow once;
- allow for this run;
- deny.

v1 does not support permanent trust rules. Permanent project/template allowlists are a later feature and must include audit and revoke UX.

---

## 9. Task Context Inheritance

Tasks default to isolated execution. Hermes Flow passes summaries, not full previous logs.

Before a task starts, the scheduler builds a prompt from:

- workflow goal;
- current task title and goal;
- acceptance criteria;
- execution directory;
- directory permission rules;
- parent task summaries;
- recent failure summaries;
- validation output excerpts;
- current loop count and guardrail state.

After a task finishes, Hermes Flow writes a structured task summary for downstream tasks. Full logs remain available in the Dashboard but are not injected by default.

---

## 10. File Change Summary

v1 uses git-based change summaries.

If the task execution directory is inside a git repository, the worker records:

- pre-task `git status --short`;
- post-task `git status --short`;
- changed files;
- added, modified, deleted classifications;
- diff stat;
- optional diff patch path or excerpt.

If the directory is not a git repository, v1 marks file-change summary as unavailable and still keeps execution logs and validation results.

Directory snapshot/hash comparison is a later feature.

---

## 11. Storage

Hermes Flow owns its storage under the plugin directory.

Suggested paths:

```text
~/.hermes/plugins/hermes-flow/data/flow.db
~/.hermes/plugins/hermes-flow/logs/<run_id>/<task_id>.log
```

SQLite stores structured state and event metadata. Large raw logs stay as files.

Recommended tables:

- `projects`;
- `agent_templates`;
- `project_agent_bindings`;
- `workflows`;
- `workflow_versions`;
- `tasks`;
- `task_edges`;
- `workflow_runs`;
- `task_runs`;
- `events`;
- `approvals`;
- `validation_results`;
- `summaries`;
- `analysis_reports`.

The plugin may reference Hermes session IDs, ACP session IDs, or process IDs, but those are external references, not primary storage.

---

## 12. Import and Export

Workflows support YAML import/export.

Path rules:

- workflow has `root_dir`;
- task `execution_dir` defaults to a path relative to `root_dir`;
- default export uses relative paths;
- absolute paths are only kept in "local private export" mode;
- import with absolute paths requires confirmation or root remapping before execution.

Export modes:

- workflow only;
- workflow plus agent template references;
- workflow plus agent template snapshots;
- full local bundle, including project binding metadata.

Import conflict handling must support:

- reuse existing template;
- create template copy;
- overwrite only after explicit confirmation.

---

## 13. Dashboard UX

Dashboard is the main product surface.

First screen:

- worker status;
- running workflow count;
- latest failures;
- daemon startup instructions if worker is not running;
- project selector/list.

Project page:

- workflows for the project;
- recent runs;
- agent bindings;
- built-in template entry points;
- AI workflow draft generator.

Workflow page:

- visual canvas;
- node creation and editing;
- edge creation and editing;
- task detail panel;
- run controls;
- live log panel;
- validation results;
- file-change summary;
- run analysis.

Realtime updates use WebSocket as the primary channel. Low-frequency polling, around every 10 to 30 seconds, is only a fallback for reconnect, initial load, or page resume.

---

## 14. AI Workflow Drafting

v1 includes AI-generated workflow drafts but does not auto-run them.

Flow:

1. user enters a development goal;
2. user selects project and default agent template;
3. Hermes Flow asks an LLM to generate a workflow draft;
4. Dashboard renders the draft canvas;
5. user edits or confirms;
6. only confirmed workflows can run.

Generated drafts should include:

- task nodes;
- success/failure edges;
- validation command suggestions;
- loop guardrail suggestions;
- optional review node suggestions.

Draft generation history should be stored in workflow versions for later analysis.

---

## 15. Built-In Templates

v1 should ship initial templates:

1. **Feature Until Green**
   `Implement -> Test -> Fix -> Test -> Complete`

2. **Bugfix Loop**
   `Reproduce -> Fix -> Regression Test -> Fix Again -> Complete`

3. **Refactor With Guardrails**
   `Analyze Impact -> Refactor -> Build/Test -> Optional Review -> Fix -> Complete`

4. **Docs + Validation**
   `Update Docs -> Validate Links/Commands -> Optional Review -> Complete`

These are starting points, not locked workflows.

---

## 16. CLI

Hermes Flow registers `hermes flow` commands.

v1 commands:

```bash
hermes flow daemon
hermes flow status
hermes flow stop
hermes flow doctor
hermes flow run <workflow-id>
hermes flow logs <run-id>
hermes flow export <workflow-id>
hermes flow import <file>
```

CLI does not replace the Dashboard editor. It is for daemon operation, diagnostics, rescue, automation, logs, and import/export.

Daemon startup strategy:

- v1: user starts daemon manually;
- Dashboard detects missing worker and shows startup command;
- future: Dashboard may auto-start worker or install launchd/systemd service.

---

## 17. Agent Tools

v1 registers read-only agent tools:

- `flow_list_projects`;
- `flow_list_workflows`;
- `flow_get_workflow`;
- `flow_get_run_status`;
- `flow_get_run_summary`;
- `flow_get_task_log_excerpt`.

These let Hermes conversations inspect workflow state and help analyze failures.

v1 must not allow agent tools to create, modify, or run workflows. Write tools are a later feature and require explicit approval design.

---

## 18. Logging and Analysis

Hermes Flow records a structured event fact layer and derived analysis.

Fact layer examples:

- workflow and task status changes;
- executor type, profile, command, cwd;
- prompt inputs and context summaries;
- ACP events;
- PTY output;
- user takeover input;
- approvals and decisions;
- git change summaries;
- validation commands, exit codes, output summaries;
- AI review result and rationale;
- routing decisions;
- error stacks, timeouts, cancellations.

Derived analysis examples:

- workflow run summary;
- failure reason classification;
- loop count and stuck-node detection;
- agent/template success rate;
- task duration;
- frequent validation failures;
- suggestions to improve task goals, validation commands, failure routing, or guardrail settings.

---

## 19. Data Retention

v1 includes default retention plus manual cleanup.

Suggested defaults:

- retain recent 100 workflow runs;
- or retain recent 30 days of raw logs;
- never automatically delete running runs, unresolved failed runs, or user-pinned runs.

Cleanup should support:

- project filter;
- workflow filter;
- time filter;
- status filter;
- dry-run preview.

When raw logs are removed, preserve structured summaries where possible.

---

## 20. Suggested Plugin Layout

```text
~/.hermes/plugins/hermes-flow/
├── plugin.yaml
├── __init__.py
├── flow/
│   ├── db.py
│   ├── daemon.py
│   ├── scheduler.py
│   ├── events.py
│   ├── approvals.py
│   ├── yaml_io.py
│   ├── git_changes.py
│   ├── analysis.py
│   └── executors/
│       ├── base.py
│       ├── hermes_cli.py
│       ├── acp.py
│       └── pty_cli.py
├── dashboard/
│   ├── manifest.json
│   ├── plugin_api.py
│   └── dist/
├── data/
└── logs/
```

---

## 21. MVP Milestones

### Milestone 1: Plugin Skeleton

- Create local plugin structure.
- Add `plugin.yaml`.
- Register `hermes flow` CLI command.
- Register Dashboard manifest and placeholder tab.
- Initialize plugin data directory.

### Milestone 2: Data Model

- Implement SQLite schema and migrations.
- Add CRUD for projects, agent templates, workflows, tasks, edges, runs, task runs, and events.
- Add fixture workflows for built-in templates.

### Milestone 3: Daemon

- Implement `daemon`, `status`, `stop`, and `doctor`.
- Add heartbeat.
- Add stale-run recovery and `interrupted` marking.

### Milestone 4: Scheduler

- Implement serial execution inside one workflow run.
- Support multiple concurrent workflow runs.
- Implement `dependency`, `success`, `failure`, and `always` routing.
- Enforce loop, step, and duration guardrails.

### Milestone 5: Executors

- Implement Hermes CLI executor.
- Implement PTY CLI executor.
- Define ACP executor interface.
- Persist stdout/stderr or PTY streams into raw logs and structured events.

### Milestone 6: Validation

- Run validation commands in task execution directory.
- Store exit code and output summary.
- Route success/failure.
- Add AI review configuration surface, but keep it off by default.

### Milestone 7: Dashboard MVP

- Project page.
- Workflow list.
- Visual canvas.
- Node and edge editor.
- Run controls.
- Worker status.
- Live logs through WebSocket.
- Low-frequency polling fallback.

### Milestone 8: Logs and Analysis

- Implement structured event writing.
- Add git diff summary.
- Add run summary.
- Add failure reason summary.

### Milestone 9: Import and Export

- Export workflow YAML.
- Import workflow YAML.
- Support template snapshots.
- Detect absolute paths and template conflicts.

### Milestone 10: Built-In Templates

- Add Feature Until Green.
- Add Bugfix Loop.
- Add Refactor With Guardrails.
- Add Docs + Validation.
- Add AI draft-generation entry point.

---

## 22. Open Implementation Questions

- Exact `hermes` CLI invocation format for non-interactive profile execution should be verified against current CLI behavior.
- Dashboard canvas library should be selected during implementation. It should support node dragging, typed edges, status colors, and stable serialization.
- ACP executor should be designed against the installed ACP SDK and current Hermes ACP server shape before implementation.
- Directory enforcement for Hermes tool calls needs a precise hook design and tests.
- PTY takeover transport should reuse existing Dashboard PTY patterns where practical, but must remain scoped to individual task runs.

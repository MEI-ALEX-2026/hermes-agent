from __future__ import annotations

import os
import subprocess
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Optional

from .analysis import build_run_summary, classify_failure
from .constants import DEFAULT_MAX_DURATION_MINUTES
from .db import FlowDB, now_iso
from .executors.acp import ACPExecutor
from .executors.base import BaseExecutor, ExecutionResult
from .executors.hermes_cli import HermesCLIExecutor
from .executors.pty_cli import PtyCLIExecutor
from .git_changes import summarize_git_changes
from .paths import logs_dir, stop_flag_path


class Scheduler:
    def __init__(self, db: Optional[FlowDB] = None) -> None:
        self.db = db or FlowDB()
        self.db.initialize()

    def run_workflow(self, workflow_id: str) -> str:
        workflow = self.db.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        self._ensure_runnable(workflow)
        run_id = self.db.create_run(workflow_id)
        self.run_existing(run_id)
        return run_id

    def enqueue_workflow(self, workflow_id: str) -> str:
        workflow = self.db.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        self._ensure_runnable(workflow)
        run_id = self.db.create_run(workflow_id, status="pending")
        self.db.record_event(run_id, "run_queued", "Workflow run queued.", payload={"workflow_id": workflow_id})
        return run_id

    def run_existing(self, run_id: str) -> str:
        run = self.db.get_run(run_id)
        if not run:
            raise ValueError(f"Unknown run: {run_id}")
        workflow = self.db.get_workflow(run["workflow_id"])
        if not workflow:
            raise ValueError(f"Unknown workflow: {run['workflow_id']}")
        self._ensure_runnable(workflow)
        if run.get("status") == "cancelled":
            return run_id
        self.db.update_run(run_id, status="running")
        self.db.record_event(run_id, "run_started", "Workflow run started.", payload={"workflow_id": workflow["id"]})

        start_monotonic = time.monotonic()
        task_by_id = {task["id"]: task for task in workflow["tasks"]}
        task_outcomes, attempts = self._existing_task_state(run_id)
        executed_steps = max(int(run.get("executed_steps") or 0), sum(attempts.values()))
        incoming_dependency = Counter(
            edge["target_task_id"] for edge in workflow["edges"] if edge["edge_type"] == "dependency"
        )
        ready: deque[str] = deque()
        if task_outcomes:
            self._seed_ready_from_outcomes(ready, workflow, task_outcomes)
        else:
            ready.extend(
                task["id"]
                for task in workflow["tasks"]
                if incoming_dependency[task["id"]] == 0
                and not any(edge["target_task_id"] == task["id"] and edge["edge_type"] in {"success", "failure", "always"} for edge in workflow["edges"])
            )
        if not ready and workflow["tasks"] and not task_outcomes:
            ready.append(workflow["tasks"][0]["id"])

        executed_path: list[str] = []

        while ready:
            task_id = ready.popleft()
            task = task_by_id[task_id]
            current_run = self.db.get_run(run_id) or {}
            if current_run.get("status") == "paused":
                self.db.record_event(run_id, "run_paused", "Workflow run paused at task boundary.", task_id=task_id)
                return run_id
            if current_run.get("status") == "cancelled":
                self.db.update_run(run_id, status="cancelled", current_task_id=task_id, finished_at=now_iso())
                self.db.record_event(run_id, "run_cancelled", "Workflow run cancelled.", task_id=task_id)
                return run_id
            if stop_flag_path().exists():
                self.db.update_run(run_id, status="stopped", current_task_id=task_id, finished_at=now_iso())
                self.db.record_event(run_id, "run_stopped", "Workflow run stopped by daemon stop request.", task_id=task_id)
                return run_id
            attempts[task_id] += 1
            if attempts[task_id] > int(workflow["max_loop_iterations"]):
                self._guardrail_stop(
                    run_id,
                    task_id,
                    "max_loop_iterations",
                    self._guardrail_payload(
                        task_id=task_id,
                        attempts=attempts[task_id],
                        executed_steps=executed_steps,
                        executed_path=executed_path + [task_id],
                        start_monotonic=start_monotonic,
                    ),
                )
                return run_id
            if executed_steps >= int(workflow["max_task_steps"]):
                self._guardrail_stop(
                    run_id,
                    task_id,
                    "max_task_steps",
                    self._guardrail_payload(
                        task_id=task_id,
                        attempts=attempts[task_id],
                        executed_steps=executed_steps,
                        executed_path=executed_path + [task_id],
                        start_monotonic=start_monotonic,
                    ),
                )
                return run_id
            max_seconds = int(workflow.get("max_duration_minutes") or DEFAULT_MAX_DURATION_MINUTES) * 60
            if time.monotonic() - start_monotonic > max_seconds:
                self._guardrail_stop(
                    run_id,
                    task_id,
                    "max_duration_minutes",
                    self._guardrail_payload(
                        task_id=task_id,
                        attempts=attempts[task_id],
                        executed_steps=executed_steps,
                        executed_path=executed_path + [task_id],
                        start_monotonic=start_monotonic,
                    ),
                )
                return run_id

            executed_steps += 1
            executed_path.append(task_id)
            self.db.update_run(run_id, current_task_id=task_id, executed_steps=executed_steps, loop_iterations=max(attempts.values()))
            status = self._run_task(run_id, workflow, task, attempts[task_id])
            if status in {"waiting_input", "waiting_approval", "stopped", "cancelled", "interrupted"}:
                self.db.update_run(run_id, status=status, current_task_id=task_id)
                self.db.update_task(task_id, status=status)
                return run_id
            task_outcomes[task_id] = status

            next_edges = [
                edge for edge in workflow["edges"]
                if edge["source_task_id"] == task_id
                and edge["edge_type"] in ({status_to_route(status), "always"})
            ]
            for edge in next_edges:
                target_id = edge["target_task_id"]
                if edge["edge_type"] == "manual":
                    continue
                if self._dependencies_satisfied(target_id, workflow["edges"], task_outcomes):
                    self._queue_ready(ready, target_id, task_outcomes, allow_revisit=True)
                    self.db.record_event(
                        run_id,
                        "routing_decision",
                        f"Routed {task_id} -> {target_id} via {edge['edge_type']}.",
                        task_id=task_id,
                        payload={"source_task_id": task_id, "target_task_id": target_id, "edge_type": edge["edge_type"]},
                    )
            dependency_edges = [
                edge for edge in workflow["edges"]
                if edge["source_task_id"] == task_id
                and edge["edge_type"] == "dependency"
                and not self._has_incoming_route(edge["target_task_id"], workflow["edges"])
            ]
            for edge in dependency_edges:
                target_id = edge["target_task_id"]
                if self._dependencies_satisfied(target_id, workflow["edges"], task_outcomes):
                    self._queue_ready(ready, target_id, task_outcomes)
                    self.db.record_event(
                        run_id,
                        "routing_decision",
                        f"Dependency satisfied {task_id} -> {target_id}.",
                        task_id=task_id,
                        payload={"source_task_id": task_id, "target_task_id": target_id, "edge_type": "dependency"},
                    )

        final_status = "passed" if task_outcomes and all(v == "passed" for v in task_outcomes.values()) else "failed"
        finished = now_iso()
        self.db.update_run(run_id, status=final_status, current_task_id=None, finished_at=finished)
        summary = build_run_summary(self.db.get_run_status(run_id) or {"id": run_id, "status": final_status, "executed_steps": executed_steps})
        self.db.save_summary(run_id, "run", summary)
        self.db.record_event(run_id, "run_finished", summary, payload={"status": final_status})
        return run_id

    def _run_task(self, run_id: str, workflow: dict, task: dict, attempt: int) -> str:
        executor = self._executor_for_task(workflow, task)
        execution_dir = self._execution_dir(workflow, task)
        execution_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir() / run_id / f"{task['id']}.log"
        task_run_id = self.db.create_task_run(
            run_id,
            task["id"],
            attempt=attempt,
            log_path=str(log_path),
            executor_type=executor.executor_type,
        )
        self.db.update_task(task["id"], status="running")
        self.db.record_event(
            run_id,
            "task_started",
            f"Task started: {task['title']}",
            task_run_id=task_run_id,
            task_id=task["id"],
            payload={"executor_type": executor.executor_type, "execution_dir": str(execution_dir), "attempt": attempt},
        )
        prompt = self._build_prompt(workflow, task, attempt)
        env = {
            "HERMES_FLOW_WORKFLOW_ID": workflow["id"],
            "HERMES_FLOW_RUN_ID": run_id,
            "HERMES_FLOW_TASK_ID": task["id"],
            "HERMES_FLOW_TASK_RUN_ID": task_run_id,
            "HERMES_FLOW_EXECUTION_DIR": str(execution_dir),
        }
        pre_changes = summarize_git_changes(execution_dir)
        self.db.record_event(
            run_id,
            "git_pre_task",
            "Captured pre-task git change summary.",
            task_run_id=task_run_id,
            task_id=task["id"],
            payload=pre_changes,
        )
        result = executor.run(prompt=prompt, cwd=execution_dir, env=env, log_path=log_path)

        review_result: ExecutionResult | None = None
        if result.status in {"waiting_input", "waiting_approval", "stopped", "cancelled", "interrupted"}:
            validation_results = []
        else:
            validation_results = self._run_validation(run_id, task_run_id, task, workflow, execution_dir)
        validation_passed = all(v["exit_code"] == 0 for v in validation_results)
        review_passed = True
        if result.exit_code == 0 and validation_passed and _ai_review_enabled(task):
            review_result = self._run_ai_review(run_id, task_run_id, task, workflow, execution_dir)
            review_passed = review_result.exit_code == 0
        status = result.status if result.status in {"waiting_input", "waiting_approval", "stopped", "cancelled", "interrupted"} else ("passed" if result.exit_code == 0 and validation_passed and review_passed else "failed")
        post_changes = summarize_git_changes(execution_dir)
        self.db.record_event(
            run_id,
            "git_post_task",
            "Captured post-task git change summary.",
            task_run_id=task_run_id,
            task_id=task["id"],
            payload=post_changes,
        )
        failure_kind = classify_failure(result.summary, validation_results) if status == "failed" else ""
        summary = result.summary
        if failure_kind:
            summary += f" Failure classified as {failure_kind}."

        self.db.update_task_run(
            task_run_id,
            status=status,
            exit_code=result.exit_code,
            summary=summary,
            finished_at=now_iso(),
        )
        self.db.update_task(task["id"], status=status)
        self.db.save_summary(
            run_id,
            "task",
            summary,
            task_id=task["id"],
            payload={
                "executor": result.metadata,
                "output_excerpt": result.output_excerpt,
                "git_pre": pre_changes,
                "git_post": post_changes,
                "validation": validation_results,
                "review": {
                    "enabled": _ai_review_enabled(task),
                    "exit_code": review_result.exit_code if review_result else None,
                    "summary": review_result.summary if review_result else "",
                    "output_excerpt": review_result.output_excerpt if review_result else "",
                },
                "failure_kind": failure_kind,
            },
        )
        self.db.record_event(
            run_id,
            "task_finished",
            f"Task {status}: {task['title']}",
            task_run_id=task_run_id,
            task_id=task["id"],
            payload={"status": status, "exit_code": result.exit_code, "failure_kind": failure_kind},
        )
        return status

    def _run_validation(self, run_id: str, task_run_id: str, task: dict, workflow: dict, cwd: Path) -> list[dict]:
        commands = task.get("validation_commands") or workflow.get("default_validation_commands") or []
        results: list[dict] = []
        if not commands:
            return results
        self.db.update_task_run(task_run_id, status="validating")
        self.db.update_task(task["id"], status="validating")
        for command in commands:
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    timeout=1800,
                )
                output = (proc.stdout or "")[-4000:]
                exit_code = int(proc.returncode)
            except subprocess.TimeoutExpired as exc:
                output = str(exc.stdout or "")[-4000:]
                exit_code = 124
            duration_ms = int((time.monotonic() - start) * 1000)
            row = {
                "command": command,
                "exit_code": exit_code,
                "output_summary": output,
                "duration_ms": duration_ms,
            }
            self.db.save_validation_result(run_id, task_run_id, task["id"], command, exit_code, output, duration_ms)
            self.db.record_event(
                run_id,
                "validation_finished",
                f"Validation exited {exit_code}: {command}",
                task_run_id=task_run_id,
                task_id=task["id"],
                payload=row,
            )
            results.append(row)
        return results

    def _run_ai_review(self, run_id: str, task_run_id: str, task: dict, workflow: dict, cwd: Path) -> ExecutionResult:
        metadata = task.get("metadata") or {}
        review_template = self.db.get_agent_template(metadata.get("review_agent_template_id") or workflow.get("default_agent_template_id"))
        executor = self._executor_for(review_template)
        log_path = logs_dir() / run_id / f"{task['id']}.review.log"
        self.db.update_task_run(task_run_id, status="reviewing")
        self.db.update_task(task["id"], status="reviewing")
        self.db.record_event(
            run_id,
            "ai_review_started",
            f"AI review started: {task['title']}",
            task_run_id=task_run_id,
            task_id=task["id"],
            payload={"executor_type": executor.executor_type, "execution_dir": str(cwd)},
        )
        prompt = "\n".join(
            [
                "Review the completed task. Do not modify files.",
                f"Workflow goal: {workflow.get('goal', '')}",
                f"Task: {task.get('title', '')}",
                f"Task goal: {task.get('goal', '')}",
                f"Acceptance criteria: {task.get('acceptance_criteria', '')}",
                "Exit with code 0 only if the implementation satisfies the task and validation evidence.",
            ]
        )
        env = {
            "HERMES_FLOW_WORKFLOW_ID": workflow["id"],
            "HERMES_FLOW_RUN_ID": run_id,
            "HERMES_FLOW_TASK_ID": task["id"],
            "HERMES_FLOW_TASK_RUN_ID": task_run_id,
            "HERMES_FLOW_EXECUTION_DIR": str(cwd),
            "HERMES_FLOW_REVIEW": "1",
        }
        result = executor.run(prompt=prompt, cwd=cwd, env=env, log_path=log_path)
        outcome = "passed" if result.exit_code == 0 else "failed"
        self.db.save_summary(
            run_id,
            "review",
            result.summary,
            task_id=task["id"],
            payload={"outcome": outcome, "executor": result.metadata, "output_excerpt": result.output_excerpt},
        )
        self.db.record_event(
            run_id,
            "ai_review_finished",
            f"AI review {outcome}: {task['title']}",
            task_run_id=task_run_id,
            task_id=task["id"],
            payload={"outcome": outcome, "exit_code": result.exit_code},
        )
        return result

    def _guardrail_stop(self, run_id: str, task_id: str, reason: str, payload: dict) -> None:
        self.db.update_run(
            run_id,
            status="guardrail_stopped",
            current_task_id=task_id,
            guardrail_reason=reason,
            finished_at=now_iso(),
        )
        self.db.update_task(task_id, status="guardrail_stopped")
        self.db.record_event(
            run_id,
            "guardrail_stopped",
            f"Workflow stopped by guardrail: {reason}",
            task_id=task_id,
            payload={"trigger_reason": reason, **payload},
        )

    @staticmethod
    def _guardrail_payload(
        *,
        task_id: str,
        attempts: int,
        executed_steps: int,
        executed_path: list[str],
        start_monotonic: float,
    ) -> dict:
        return {
            "task_id": task_id,
            "attempts": attempts,
            "executed_steps": executed_steps,
            "loop_path": executed_path,
            "elapsed_seconds": int(time.monotonic() - start_monotonic),
        }

    def _executor_for(self, template: Optional[dict]) -> BaseExecutor:
        if not template:
            return HermesCLIExecutor({})
        if template["type"] == "pty_cli":
            return PtyCLIExecutor(template.get("config") or {})
        if template["type"] == "acp":
            return ACPExecutor(template.get("config") or {})
        return HermesCLIExecutor(template.get("config") or {})

    def _executor_for_task(self, workflow: dict, task: dict) -> BaseExecutor:
        metadata = task.get("metadata") or {}
        mode = str(metadata.get("executor_mode") or "ai_agent")
        if mode == "claude_code_cli":
            return PtyCLIExecutor({"command": "claude -p", "append_prompt": True, "idle_timeout_seconds": 30})
        if mode == "opencode_cli":
            return PtyCLIExecutor({"command": "opencode run", "append_prompt": True, "idle_timeout_seconds": 30})
        executor_template = self.db.get_agent_template(task.get("agent_template_id") or workflow.get("default_agent_template_id"))
        return self._executor_for(executor_template)

    @staticmethod
    def _ensure_runnable(workflow: dict) -> None:
        status = workflow.get("status") or "confirmed"
        if workflow.get("template_key") or status != "confirmed":
            raise ValueError("Workflow must be confirmed before it can run.")

    def _execution_dir(self, workflow: dict, task: dict) -> Path:
        raw = task.get("execution_dir") or workflow.get("root_dir") or os.getcwd()
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path
        root = Path(workflow.get("root_dir") or os.getcwd()).expanduser()
        return (root / path).resolve()

    def _build_prompt(self, workflow: dict, task: dict, attempt: int) -> str:
        parent_context = self._context_summaries(workflow, task)
        return "\n".join(
            [
                f"Workflow goal: {workflow.get('goal', '')}",
                f"Task: {task.get('title', '')}",
                f"Task goal: {task.get('goal', '')}",
                f"Acceptance criteria: {task.get('acceptance_criteria', '')}",
                f"Attempt: {attempt}",
                f"Guardrails: max loop iterations {workflow.get('max_loop_iterations')}, max task steps {workflow.get('max_task_steps')}, max duration minutes {workflow.get('max_duration_minutes')}.",
                "Stay within the task execution directory unless explicit approval is requested.",
                parent_context,
            ]
        )

    def _context_summaries(self, workflow: dict, task: dict) -> str:
        parent_ids = {
            edge["source_task_id"]
            for edge in workflow.get("edges", [])
            if edge["target_task_id"] == task["id"]
            and edge["edge_type"] in {"dependency", "success", "failure", "always"}
        }
        if not parent_ids:
            return "Parent summaries: none."
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, content, payload_json
                FROM summaries
                WHERE kind = 'task'
                  AND task_id IN ({})
                ORDER BY created_at DESC
                LIMIT 8
                """.format(",".join("?" for _ in parent_ids)),
                tuple(parent_ids),
            ).fetchall()
        if not rows:
            return "Parent summaries: none yet."
        lines = ["Parent summaries:"]
        for row in rows:
            lines.append(f"- {row['task_id']}: {row['content'][:800]}")
        return "\n".join(lines)

    @staticmethod
    def _dependencies_satisfied(target_id: str, edges: list[dict], task_outcomes: dict[str, str]) -> bool:
        deps = [edge["source_task_id"] for edge in edges if edge["target_task_id"] == target_id and edge["edge_type"] == "dependency"]
        return all(task_outcomes.get(dep) == "passed" for dep in deps)

    def _existing_task_state(self, run_id: str) -> tuple[dict[str, str], Counter[str]]:
        status = self.db.get_run_status(run_id) or {}
        outcomes: dict[str, str] = {}
        attempts: Counter[str] = Counter()
        for task_run in status.get("task_runs", []):
            task_id = task_run.get("task_id")
            if not task_id:
                continue
            attempts[task_id] = max(attempts[task_id], int(task_run.get("attempt") or 1))
            if task_run.get("status") in {"passed", "failed"}:
                outcomes[task_id] = task_run["status"]
        return outcomes, attempts

    def _seed_ready_from_outcomes(self, ready: deque, workflow: dict, task_outcomes: dict[str, str]) -> None:
        for task in workflow.get("tasks", []):
            task_id = task["id"]
            status = task_outcomes.get(task_id)
            if not status:
                continue
            for edge in workflow.get("edges", []):
                if edge["source_task_id"] != task_id:
                    continue
                target_id = edge["target_task_id"]
                if edge["edge_type"] in {status_to_route(status), "always"}:
                    if self._dependencies_satisfied(target_id, workflow["edges"], task_outcomes):
                        self._queue_ready(ready, target_id, task_outcomes, allow_revisit=False)
                if edge["edge_type"] == "dependency" and not self._has_incoming_route(target_id, workflow["edges"]):
                    if self._dependencies_satisfied(target_id, workflow["edges"], task_outcomes):
                        self._queue_ready(ready, target_id, task_outcomes, allow_revisit=False)

    @staticmethod
    def _has_incoming_route(target_id: str, edges: list[dict]) -> bool:
        return any(edge["target_task_id"] == target_id and edge["edge_type"] in {"success", "failure", "always"} for edge in edges)

    @staticmethod
    def _queue_ready(ready: deque, target_id: str, task_outcomes: dict[str, str], *, allow_revisit: bool = False) -> None:
        if (allow_revisit or target_id not in task_outcomes) and target_id not in ready:
            ready.append(target_id)


def status_to_route(status: str) -> str:
    return "success" if status == "passed" else "failure"


def _ai_review_enabled(task: dict) -> bool:
    return bool((task.get("metadata") or {}).get("ai_review_enabled"))

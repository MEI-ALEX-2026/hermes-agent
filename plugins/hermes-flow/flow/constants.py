from __future__ import annotations

DEFAULT_MAX_LOOP_ITERATIONS = 5
DEFAULT_MAX_TASK_STEPS = 30
DEFAULT_MAX_DURATION_MINUTES = 180

TASK_STATUSES = {
    "draft",
    "pending",
    "ready",
    "running",
    "waiting_input",
    "waiting_approval",
    "validating",
    "reviewing",
    "passed",
    "failed",
    "skipped",
    "stopped",
    "guardrail_stopped",
    "cancelled",
    "interrupted",
}

EDGE_TYPES = {"dependency", "success", "failure", "always", "manual"}
EXECUTOR_TYPES = {"hermes_cli", "acp", "pty_cli"}

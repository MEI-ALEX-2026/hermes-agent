from __future__ import annotations


def classify_failure(summary: str, validation_outputs: list[dict]) -> str:
    text = (summary + "\n" + "\n".join(v.get("output_summary", "") for v in validation_outputs)).lower()
    if "timeout" in text:
        return "timeout"
    if "permission" in text or "denied" in text:
        return "permission"
    if "assert" in text or "failed" in text or "error" in text:
        return "validation_failure"
    return "unknown"


def build_run_summary(run: dict) -> str:
    status = run.get("status", "unknown")
    steps = run.get("executed_steps", 0)
    guardrail = run.get("guardrail_reason")
    line = f"Run {run.get('id')} finished with status {status} after {steps} step(s)."
    if guardrail:
        line += f" Guardrail: {guardrail}."
    return line

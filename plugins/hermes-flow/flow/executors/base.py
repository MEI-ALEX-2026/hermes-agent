from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class ExecutionResult:
    status: str
    exit_code: int
    summary: str
    output_excerpt: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)


class BaseExecutor:
    executor_type = "base"

    def run(
        self,
        *,
        prompt: str,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> ExecutionResult:
        raise NotImplementedError

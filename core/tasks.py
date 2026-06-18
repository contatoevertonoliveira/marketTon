"""Task primitiva para orquestração."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskResult:
    task_id: str
    ok: bool
    summary: str = ""
    artifacts: dict = field(default_factory=dict)


@dataclass
class Task:
    id: str
    name: str
    run: Any

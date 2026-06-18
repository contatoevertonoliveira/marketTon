"""Orquestrador com controle de ciclo de vida: start / pause / stop."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Iterable

from core.tasks import Task, TaskResult

Memory = dict


@dataclass
class AgentController:
    memory_path: Path = Path(__file__).resolve().parent.parent / "memory" / "state.json"
    _running: bool = False
    _paused: bool = False
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _pause_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _thread: threading.Thread | None = None
    queue: Queue = field(default_factory=Queue)
    memory: dict = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)
    on_result: Callable[[TaskResult], None] | None = None

    def load_memory(self) -> None:
        if self.memory_path.exists():
            self.memory = json.loads(self.memory_path.read_text(encoding="utf-8"))
        else:
            self.memory = {"status": "stopped", "updated_at": datetime.now().isoformat()}

    def save_memory(self) -> None:
        self.memory["updated_at"] = datetime.now().isoformat()
        self.memory_path.write_text(json.dumps(self.memory, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def status(self) -> str:
        with self._lock:
            if not self._running:
                return "stopped"
            if self._paused:
                return "paused"
            return "running"

    def start(self, tasks: Iterable[Task] | None = None) -> None:
        with self._lock:
            if self._running:
                return
            if tasks is not None:
                self.tasks = list(tasks)
            self._running = True
            self._paused = False
            self._stop_event.clear()
            self._pause_event.clear()
            self.memory["status"] = "running"
            self.save_memory()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._paused = True
            self.memory["status"] = "paused"
            self.save_memory()

    def resume(self) -> None:
        with self._lock:
            if not self._running or not self._paused:
                return
            self._paused = False
            self._pause_event.set()
            self.memory["status"] = "running"
            self.save_memory()

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._paused = False
            self._stop_event.set()
            self._pause_event.set()
            self.memory["status"] = "stopped"
            self.save_memory()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def enqueue(self, task: Task) -> None:
        self.queue.put(task)

    def _run_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            while self._paused and not self._stop_event.is_set():
                self._pause_event.wait(1.0)
            if self._stop_event.is_set():
                break
            try:
                task = self.queue.get(timeout=1.0)
            except Exception:
                continue
            if task is None:
                continue
            try:
                result = task.run(self.memory)
                if self.on_result:
                    try:
                        self.on_result(result)
                    except Exception:
                        pass
                self.memory["last_task"] = {
                    "id": task.id,
                    "name": task.name,
                    "finished_at": datetime.now().isoformat(),
                    "ok": result.ok,
                    "artifacts": result.artifacts,
                }
                self.save_memory()
            except Exception as e:  # noqa: BLE001
                self.memory["last_error"] = str(e)
                self.save_memory()

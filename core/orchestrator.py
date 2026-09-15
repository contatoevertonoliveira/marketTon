"""Orquestrador com controle de ciclo de vida: start / pause / stop."""
from __future__ import annotations

import inspect
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Iterable

from core.tasks import Task, TaskResult

Memory = dict


@dataclass
class AgentController:
    memory_path: Path = Path(__file__).resolve().parent.parent / "memory" / "state.json"
    # Intervalo entre ciclos completos do pipeline, em segundos.
    #   None -> executa o pipeline UMA vez e para (comportamento one-shot).
    #   0    -> recicla imediatamente, sem pausa (usado em teste).
    #   > 0  -> recicla após o intervalo (o ciclo periódico do briefing seção 15).
    # A distinção entre None e 0 é deliberada: antes não existia, e o resultado
    # era um laço que nunca parava nem executava.
    cycle_interval_seconds: float | None = 3600.0
    # Gravar cada execução em `jobs`/`job_events`. Desligável para ambientes sem
    # banco — observabilidade não pode ser o que impede o pipeline de rodar.
    persist_jobs: bool = True
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
            # `_paused` NÃO é zerado aqui: uma pausa solicitada antes do start
            # precisa ser respeitada. Zerá-la fazia a pausa ser silenciosamente
            # desfeita e o pipeline rodava mesmo assim.
            self._stop_event.clear()
            self._pause_event.clear()
            self.memory["status"] = "paused" if self._paused else "running"
            self.save_memory()
            # Alimentar a fila é o que faz o pipeline executar. Sem isto o laço
            # não tinha o que consumir e nenhum agente rodava, nunca.
            for task in self.tasks:
                self.queue.put(task)
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def pause(self) -> None:
        """Solicita pausa. Válida também antes do start, para segurar o pipeline."""
        with self._lock:
            self._paused = True
            self.memory["status"] = "paused" if self._running else self.memory.get("status", "stopped")
            self.save_memory()

    def resume(self) -> None:
        with self._lock:
            if not self._paused:
                return
            self._paused = False
            self._pause_event.set()
            if self._running:
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
        # Uma thread não pode fazer join de si mesma: o caminho one-shot chama
        # `stop()` de dentro do próprio laço, e ali a saída já está garantida
        # pelas flags acima.
        if (
            self._thread
            and self._thread.is_alive()
            and self._thread is not threading.current_thread()
        ):
            self._thread.join(timeout=10)

    def enqueue(self, task: Task) -> None:
        self.queue.put(task)

    def _run_loop(self) -> None:
        """Consome a fila, reciclando o pipeline conforme o intervalo configurado."""
        while self._running and not self._stop_event.is_set():
            if self._paused:
                self._pause_event.wait(1.0)
                self._pause_event.clear()
                continue

            # Fila vazia significa que o ciclo atual terminou.
            if self.queue.empty():
                if not self.tasks:
                    # Sem pipeline declarado: não há busy-wait, apenas espera.
                    self._stop_event.wait(0.05)
                    continue
                if self.cycle_interval_seconds is None:
                    # One-shot: terminou o pipeline, encerra sozinho.
                    self.stop()
                    break
                for task in self.tasks:
                    self.queue.put(task)

            try:
                task = self.queue.get(timeout=1.0)
            except Empty:
                continue
            if task is None:
                continue
            if self._paused or self._stop_event.is_set():
                # Devolve a task para que uma pausa nunca descarte trabalho.
                self.queue.put(task)
                continue

            try:
                result = self.execute_task(task)
                if result is not None:
                    self._record_result(task, result)
            except Exception as e:  # noqa: BLE001
                self._record_error(task, e)

            if (
                self.cycle_interval_seconds
                and self.queue.empty()
                and not self._stop_event.is_set()
            ):
                self._stop_event.wait(self.cycle_interval_seconds)

    def _record_result(self, task: Task, result: TaskResult) -> None:
        entry = {
            "id": task.id,
            "name": task.name,
            "finished_at": datetime.now().isoformat(),
            "ok": result.ok,
            "summary": result.summary,
            "artifacts": result.artifacts,
        }
        self.memory["last_task"] = entry
        history = self.memory.setdefault("task_history", [])
        history.append(entry)
        del history[:-50]
        self.save_memory()
        if self.on_result:
            try:
                self.on_result(result)
            except Exception:  # noqa: BLE001
                pass

    def _record_error(self, task: Task, error: Exception) -> None:
        entry = {
            "id": task.id,
            "name": task.name,
            "finished_at": datetime.now().isoformat(),
            "ok": False,
            "error": str(error),
        }
        self.memory["last_error"] = entry
        history = self.memory.setdefault("task_history", [])
        history.append(entry)
        del history[:-50]
        self.save_memory()

    # --- Persistência em banco -------------------------------------------------

    def execute_task(self, task: Task) -> TaskResult | None:
        """Executa uma task, gravando em `jobs`/`job_events` quando há banco.

        A execução passa por `job_run`, então o histórico fica consultável em
        `/jobs` em vez de viver apenas no último registro de `memory/state.json`.
        Um arquivo com um registro só não é histórico — é uma foto.

        Se a sessão de banco não puder ser aberta, a task roda mesmo assim e o
        motivo fica em memória. Observabilidade não pode ser o que impede o
        pipeline de rodar.
        """
        from core.services.jobs import job_run

        session = None
        if self.persist_jobs:
            try:
                from core.db.session import get_session_factory

                session = get_session_factory()()
            except Exception as exc:  # noqa: BLE001
                self.memory["last_persistence_error"] = str(exc)
                session = None

        if session is None:
            return task.run(self.memory)

        # A task recebe a sessão quando a assinatura aceita — os agentes da Fase 3
        # têm `session=` como parâmetro nomeado. Os que não têm continuam
        # funcionando sem banco.
        accepts_session = "session" in inspect.signature(task.run).parameters

        try:
            with job_run(
                session,
                job_type=f"pipeline.{task.id}",
                agent=task.id,
                triggered_by="orchestrator",
            ) as handle:
                self.memory["current_job_id"] = handle.id
                if accepts_session:
                    result = task.run(self.memory, session=session)
                else:
                    result = task.run(self.memory)

                if isinstance(result, TaskResult):
                    handle.add_event(result.summary or "task concluída", level="INFO")
                    handle.finish(summary=result.summary, result=result.artifacts)
                return result
        except Exception as exc:  # noqa: BLE001
            # `job_run` grava a falha e propaga; aqui apenas devolvemos `None` para
            # que o laço registre o erro em memória sem derrubar o pipeline.
            self.memory["last_persistence_error"] = str(exc)
            raise
        finally:
            session.close()

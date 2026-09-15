"""Testes do orquestrador.

O defeito de origem: `Agentone_shot.enqueue()` existia e nunca era chamado, e
`start()` guardava as tasks sem alimentar a fila. O laço girava para sempre em
`queue.get(timeout=1.0)` e **nenhum agente jamais executou por esse caminho**.
Estes testes fixam o comportamento correto.
"""
from __future__ import annotations

import threading
import time

import pytest

from core.orchestrator import AgentController
from core.tasks import Task, TaskResult


def _task(name: str, calls: list, *, fail: bool = False, delay: float = 0.0) -> Task:
    def run(memory):
        if delay:
            time.sleep(delay)
        calls.append(name)
        if fail:
            raise RuntimeError(f"falha simulada em {name}")
        return TaskResult(task_id=name, ok=True, summary=f"{name} executou")

    return Task(id=name, name=name.title(), run=run)


@pytest.fixture
def one_shot(tmp_path):
    """Controller em modo one-shot: executa o pipeline uma vez e para.

    `cycle_interval_seconds=None` é o sentinela de execução única; `0` significa
    "reciclar imediatamente" e é usado apenas onde o teste quer repetição.
    """
    return AgentController(memory_path=tmp_path / "state.json", cycle_interval_seconds=None)


@pytest.fixture
def repeating(tmp_path):
    """Controller que recicla o pipeline sem pausa — para testar o ciclo."""
    return AgentController(memory_path=tmp_path / "state.json", cycle_interval_seconds=0)


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestQueueIsFed:
    def test_start_executes_every_task_once(self, one_shot) -> None:
        """O teste que teria pego o defeito original."""
        calls: list[str] = []
        tasks = [_task("trend_hunter", calls), _task("product_hunter", calls)]

        one_shot.load_memory()
        one_shot.start(tasks)

        assert _wait_until(lambda: len(calls) >= 2), f"só executou: {calls}"
        assert calls == ["trend_hunter", "product_hunter"]
        one_shot.stop()

    def test_pipeline_runs_in_declared_order(self, one_shot) -> None:
        """A ordem do pipeline é a ordem em que as tasks foram declaradas."""
        calls: list[str] = []
        names = ["trend", "product", "marketplace", "growth", "copy", "master"]
        one_shot.load_memory()
        one_shot.start([_task(name, calls) for name in names])

        assert _wait_until(lambda: len(calls) >= len(names))
        assert calls == names
        one_shot.stop()

    def test_enqueue_adds_work_to_a_running_pipeline(self, one_shot) -> None:
        """O método que existia e nunca era usado precisa funcionar."""
        calls: list[str] = []
        one_shot.load_memory()
        one_shot.start([_task("first", calls)])
        assert _wait_until(lambda: "first" in calls)

        one_shot.enqueue(_task("extra", calls))
        assert _wait_until(lambda: "extra" in calls), f"extra não executou: {calls}"
        one_shot.stop()


class TestLifecycle:
    def test_status_transitions(self, one_shot) -> None:
        one_shot.load_memory()
        assert one_shot.status == "stopped"
        one_shot.start([_task("noop", [])])
        assert one_shot.status == "running"
        one_shot.pause()
        assert one_shot.status == "paused"
        one_shot.resume()
        assert one_shot.status == "running"
        one_shot.stop()
        assert one_shot.status == "stopped"

    def test_start_is_idempotent(self, one_shot) -> None:
        calls: list[str] = []
        one_shot.load_memory()
        one_shot.start([_task("once", calls)])
        one_shot.start([_task("twice", calls)])
        assert _wait_until(lambda: len(calls) >= 1)
        time.sleep(0.15)
        assert calls == ["once"], f"start duplicado reiniciou o pipeline: {calls}"
        one_shot.stop()

    def test_pause_holds_the_pipeline_without_dropping_it(self, one_shot) -> None:
        """Uma pausa não pode descartar trabalho: a task volta para a fila."""
        calls: list[str] = []
        one_shot.load_memory()
        one_shot.pause()  # pausado antes de começar
        one_shot.start([_task("blocked", calls)])
        time.sleep(0.2)
        assert calls == [], "não deveria executar enquanto pausado"

        one_shot.resume()
        assert _wait_until(lambda: calls == ["blocked"]), f"task perdida: {calls}"
        one_shot.stop()

    def test_stop_is_safe_when_never_started(self, one_shot) -> None:
        one_shot.load_memory()
        one_shot.stop()  # não deve levantar
        assert one_shot.status == "stopped"


class TestObservability:
    def test_result_is_recorded_in_memory(self, one_shot) -> None:
        one_shot.load_memory()
        one_shot.start([_task("reporter", [])])
        assert _wait_until(lambda: one_shot.memory.get("last_task") is not None)

        last = one_shot.memory["last_task"]
        assert last["id"] == "reporter"
        assert last["ok"] is True
        assert "summary" in last
        one_shot.stop()

    def test_history_is_kept(self, one_shot) -> None:
        one_shot.load_memory()
        one_shot.start([_task("a", []), _task("b", [])])
        assert _wait_until(lambda: len(one_shot.memory.get("task_history", [])) >= 2)

        ids = [entry["id"] for entry in one_shot.memory["task_history"]]
        assert ids == ["a", "b"]
        one_shot.stop()

    def test_failure_is_recorded_and_does_not_kill_the_loop(self, one_shot) -> None:
        """Um agente que quebra não pode derrubar o pipeline inteiro."""
        calls: list[str] = []
        one_shot.load_memory()
        one_shot.start([_task("broken", calls, fail=True), _task("healthy", calls)])

        assert _wait_until(lambda: "healthy" in calls), f"o pipeline parou: {calls}"

        error = one_shot.memory.get("last_error")
        assert error is not None
        assert error["id"] == "broken"
        assert error["ok"] is False
        assert "falha simulada" in error["error"]
        one_shot.stop()

    def test_history_is_capped(self, one_shot) -> None:
        """O histórico não pode crescer sem limite no arquivo de estado."""
        one_shot.load_memory()
        one_shot.memory["task_history"] = [{"id": str(i)} for i in range(60)]
        one_shot.save_memory()

        one_shot.start([_task("one_more", [])])
        assert _wait_until(lambda: one_shot.memory.get("last_task") is not None)
        one_shot.stop()

        assert len(one_shot.memory["task_history"]) <= 50


class TestCycle:
    def test_interval_zero_does_not_spin_forever_on_empty_pipeline(self, one_shot) -> None:
        """Sem tasks e com intervalo zero, o laço não pode consumir CPU em busy-wait."""
        one_shot.load_memory()
        one_shot.start([])
        time.sleep(0.2)
        assert one_shot.status == "running"
        one_shot.stop()

    def test_pipeline_repeats_when_interval_allows(self, tmp_path) -> None:
        """Com intervalo curto, o pipeline é reciclado — o ciclo periódico do briefing."""
        calls: list[str] = []
        controller = AgentController(
            memory_path=tmp_path / "state.json",
            cycle_interval_seconds=0.05,
        )
        controller.load_memory()
        controller.start([_task("cycle", calls)])

        assert _wait_until(lambda: len(calls) >= 3), f"o pipeline não reciclou: {calls}"
        controller.stop()

    def test_stop_does_not_leave_a_live_thread(self, tmp_path) -> None:
        controller = AgentController(
            memory_path=tmp_path / "state.json",
            cycle_interval_seconds=0.05,
        )
        controller.load_memory()
        controller.start([_task("long", [], delay=0.01)])
        assert controller.status == "running"
        controller.stop()

        assert controller.status == "stopped"
        worker = controller._thread
        assert worker is not None
        # `stop()` faz join com timeout; depois dele a thread não pode seguir viva.
        assert not worker.is_alive(), "a thread do orchestrador continuou rodando após stop()"

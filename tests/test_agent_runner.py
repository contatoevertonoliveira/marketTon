"""Supervisor do agente: quando roda, como roda e o que ele isola.

O Claude Code nunca é chamado de verdade aqui: o processo filho é substituído por um `runner` falso. O que
os testes travam:

* só roda com o modo agente ligado, uma rodada por vez, e a rotina diária só em autonomia independente;
* a rodada recebe **só** o servidor do marketTon, lista fechada de ferramentas e ambiente mínimo;
* a sessão do agente é emitida pelo backend (token), sem senha;
* login do Claude Code vencido vira pedido no chat e pausa as tentativas, em vez de insistir.
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.agent_chat import AgentMessage
from core.db.agent_runs import AgentRun
from core.db.auth import Role, User
from core.services import agent_chat
from core.services import agent_runner as ar
from core.services.app_settings import set_agent_autonomy, set_agent_mode
from core.services.auth import AccountInactive, AuthError, create_user, issue_agent_session
from core.services.security import decode_access_token

PASSWORD = "SenhaDeTeste2026"


@pytest.fixture
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(factory):
    with factory() as session:
        yield session


@pytest.fixture
def ready(db):
    """Modo ligado, usuário do agente criado, tarefa de ativação já concluída (estado de rotina)."""
    create_user(db, username="claude_agent", password=PASSWORD, role=Role.BOT)
    set_agent_mode(db, enabled=True, actor="dono")
    task = agent_chat.post_activation_task(db)
    agent_chat.set_status(db, task.id, "done")
    agent_chat.mark_read(db, "agent")
    db.commit()
    return db


def at(hour, minute=0, day=22):
    """Um instante de hora local conhecida (o supervisor decide pela hora local)."""
    return datetime(2026, 10, day, hour, minute).astimezone()


def _run(db, trigger, status="ok", started=None, finished=None):
    started = started or datetime.now(UTC)
    db.add(AgentRun(trigger=trigger, status=status, started_at=started, finished_at=finished or started))
    db.commit()


# ------------------------------------------------------------------- quando roda --------


def test_nothing_runs_with_the_mode_off_or_without_an_agent_user(db):
    assert ar.decide_trigger(db, now=at(9)) is None
    create_user(db, username="claude_agent", password=PASSWORD, role=Role.BOT)
    db.commit()
    assert ar.decide_trigger(db, now=at(9)) is None  # usuário existe, modo desligado
    set_agent_mode(db, enabled=True, actor="x")
    set_agent_autonomy(db, level="independent", actor="x")
    assert ar.decide_trigger(db, now=at(9)) == "morning"  # agora sim


def test_open_activation_task_triggers_activation_even_when_supervised(db):
    create_user(db, username="claude_agent", password=PASSWORD, role=Role.BOT)
    set_agent_mode(db, enabled=True, actor="x")
    agent_chat.post_activation_task(db)
    db.commit()
    assert ar.decide_trigger(db, now=at(3)) == "activation"  # supervisionado e fora do horário: ativação roda mesmo assim
    _run(db, "activation", status="failed")
    assert ar.decide_trigger(db, now=at(3)) is None  # não insiste logo após uma tentativa
    assert ar.decide_trigger(db, now=datetime.now(UTC).astimezone() + timedelta(minutes=21)) == "activation"


def test_operator_message_triggers_a_chat_run_with_a_cooldown(ready):
    agent_chat.post_message(ready, author="user", text="olhe o fone de novo")
    ready.commit()
    assert ar.decide_trigger(ready, now=at(3)) == "chat"
    _run(ready, "chat")
    assert ar.decide_trigger(ready, now=at(3)) is None  # intervalo mínimo entre rodadas de chat
    later = datetime.now(UTC).astimezone() + timedelta(minutes=6)
    assert ar.decide_trigger(ready, now=later) == "chat"
    agent_chat.mark_read(ready, "agent")  # o agente leu: nada a fazer
    ready.commit()
    assert ar.decide_trigger(ready, now=later) is None


def test_daily_routines_only_in_independent_autonomy_and_once_per_period(ready):
    assert ar.decide_trigger(ready, now=at(9)) is None  # supervisionado: sem rotina sozinha
    set_agent_autonomy(ready, level="independent", actor="x")
    ready.commit()

    assert ar.decide_trigger(ready, now=at(3)) is None  # de madrugada não roda
    assert ar.decide_trigger(ready, now=at(9)) == "morning"
    assert ar.decide_trigger(ready, now=at(20)) is None  # noite sem venda, clique nem mensagem: nada a analisar

    agent_chat.post_message(ready, author="user", text="como foi o dia?")  # sinal novo...
    agent_chat.mark_read(ready, "agent")  # ...que o agente já leu (senão seria uma rodada de chat)
    ready.commit()
    assert ar.decide_trigger(ready, now=at(20)) == "evening"

    now_local = datetime.now(UTC).astimezone()
    _run(ready, "morning", started=now_local)
    assert ar.decide_trigger(ready, now=now_local.replace(hour=9, minute=0)) is None  # manhã de hoje já foi


def test_only_one_run_at_a_time_and_stale_running_rows_do_not_block(ready):
    set_agent_autonomy(ready, level="independent", actor="x")
    _run(ready, "manual", status="running", started=datetime.now(UTC))
    assert ar.decide_trigger(ready, now=at(9)) is None  # já tem uma em andamento
    ready.query(AgentRun).delete()
    _run(ready, "manual", status="running", started=datetime.now(UTC) - timedelta(hours=3))  # processo que caiu
    ready.commit()
    assert ar.decide_trigger(ready, now=at(9)) == "morning"


def test_waiting_for_claude_login_pauses_retries_but_manual_overrides(ready):
    agent_chat.post_message(ready, author="user", text="oi")
    ready.commit()
    finished = datetime.now(UTC)
    _run(ready, "chat", status="needs_login", started=finished, finished=finished)
    assert ar.decide_trigger(ready, now=at(3)) is None  # aguardando o login
    assert ar.decide_trigger(ready, manual=True) == "manual"
    soon = datetime.now(UTC).astimezone() + timedelta(minutes=16)
    assert ar.decide_trigger(ready, now=soon) == "chat"  # passou o intervalo: tenta de novo


# ------------------------------------------------------------------- como roda --------


class _Proc:
    def __init__(self, out="feito", err="", code=0):
        self.stdout, self.stderr, self.returncode = out, err, code


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setattr(ar, "find_claude", lambda: "C:/fake/claude.exe")
    monkeypatch.setattr(ar, "prefetch", lambda factory: None)  # a sincronização prévia não faz parte destes testes


def test_a_run_gets_only_the_marketton_server_a_closed_tool_list_and_a_minimal_environment(ready, factory, fake_claude, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://segredo")
    monkeypatch.setenv("JWT_SECRET_KEY", "segredo-jwt")
    monkeypatch.setenv("AI_API_KEY", "segredo-ia")
    seen = {}

    def runner(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return _Proc()

    run_id = ar.execute_run(factory, "activation", runner=runner)

    command, kwargs = seen["command"], seen["kwargs"]
    assert command[1] == "-p" and "Execute a rotina de ativação" in command[2] and "SEGUNDO PLANO" in command[2]
    assert "--strict-mcp-config" in command  # nenhum outro servidor MCP da máquina
    assert command[command.index("--allowedTools") + 1] == "mcp__marketton"
    denied = command[command.index("--disallowedTools") + 1 : command.index("--output-format")]
    assert {"Bash", "Edit", "Write", "WebFetch", "WebSearch", "Read"} <= set(denied)
    assert "--dangerously-skip-permissions" not in command and "--no-session-persistence" in command

    env = kwargs["env"]
    assert "DATABASE_URL" not in env and "JWT_SECRET_KEY" not in env and "AI_API_KEY" not in env  # nada do backend vaza
    assert not any("PASSWORD" in k or "SECRET" in k for k in env)  # e nenhuma senha
    claims = decode_access_token(env["MARKETTON_AGENT_ACCESS_TOKEN"])
    assert claims["sub"] == "claude_agent" and claims["role"] == "bot"  # sessão do agente, emitida pelo backend
    assert kwargs["timeout"] == 25 * 60

    with factory() as s:
        run = s.get(AgentRun, run_id)
        assert (run.trigger, run.status, run.exit_code, run.output_tail) == ("activation", "ok", 0, "feito")
        assert s.scalar(select(User).where(User.username == "claude_agent")).last_login_at is not None  # "Claude conectou"


def test_expired_claude_login_becomes_a_chat_request_renewed_instead_of_duplicated(ready, factory, fake_claude):
    failing = lambda *a, **k: _Proc(out="", err="Not logged in · Please run /login", code=1)  # noqa: E731
    first = ar.execute_run(factory, "chat", runner=failing)
    second = ar.execute_run(factory, "chat", runner=failing)

    with factory() as s:
        assert s.get(AgentRun, first).status == "needs_login" and s.get(AgentRun, second).status == "needs_login"
        requests = s.scalars(select(AgentMessage).where(AgentMessage.kind == "request")).all()
        assert len(requests) == 1  # um cartão só
        assert requests[0].meta["resource"] == "login_claude_code" and requests[0].meta["reminders"] == 1
        assert "/login" in requests[0].text and requests[0].status == "open"
        assert not s.scalars(select(AgentMessage).where(AgentMessage.kind == "alert")).all()  # não vira alerta de falha


def test_other_failures_timeouts_and_start_errors_are_recorded_and_reported(ready, factory, fake_claude):
    run = ar.execute_run(factory, "morning", runner=lambda *a, **k: _Proc(out="x", err="boom", code=2))
    timed = ar.execute_run(factory, "evening", runner=lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("claude", 5)))
    oserr = ar.execute_run(factory, "manual", runner=lambda *a, **k: (_ for _ in ()).throw(OSError("sem acesso")))
    with factory() as s:
        assert (s.get(AgentRun, run).status, s.get(AgentRun, timed).status, s.get(AgentRun, oserr).status) == ("failed", "timeout", "failed")
        assert s.get(AgentRun, run).error == "saída com código 2" and "boom" in s.get(AgentRun, run).output_tail
        alerts = s.scalars(select(AgentMessage).where(AgentMessage.kind == "alert")).all()
        assert len(alerts) == 3 and all("terminou com problema" in a.text for a in alerts)


def test_missing_claude_code_is_a_clear_request_not_a_crash(ready, factory, monkeypatch):
    monkeypatch.setattr(ar, "find_claude", lambda: None)
    run_id = ar.execute_run(factory, "activation", runner=lambda *a, **k: pytest.fail("não deveria executar"))
    with factory() as s:
        assert s.get(AgentRun, run_id).status == "failed" and "não encontrado" in s.get(AgentRun, run_id).error
        (request,) = s.scalars(select(AgentMessage).where(AgentMessage.kind == "request")).all()
        assert request.meta["resource"] == "claude_code_instalado"


def test_supervisor_tick_decides_and_runs_one_round_and_manual_is_honoured(ready, factory, fake_claude):
    calls = []
    supervisor = ar.AgentSupervisor(factory, runner=lambda command, **k: calls.append(command) or _Proc())
    assert supervisor.tick() is None and calls == []  # nada a fazer: rotina concluída, supervisionado

    agent_chat.post_message(ready, author="user", text="bom dia")
    ready.commit()
    assert supervisor.tick() is not None and len(calls) == 1 and "mensagens novas no chat" in calls[0][2]

    supervisor.request_manual()
    assert supervisor.tick() is not None and "pediu uma rodada agora" in calls[1][2]
    assert supervisor.current is None  # liberou o "em execução"


def test_agent_session_is_only_for_bot_users(db):
    human = create_user(db, username="pessoa", password=PASSWORD, role=Role.ADMIN)
    with pytest.raises(AuthError, match="papel bot"):
        issue_agent_session(db, human)  # não é um atalho para entrar como pessoa
    bot = create_user(db, username="bot2", password=PASSWORD, role=Role.BOT)
    bot.is_active = False
    with pytest.raises(AccountInactive):
        issue_agent_session(db, bot)


def test_command_is_built_without_shell_and_with_the_prompt_as_one_argument(tmp_path):
    cmd = ar.build_command("claude", "faça A; depois B && C", tmp_path / "mcp.json")
    assert cmd[:3] == ["claude", "-p", "faça A; depois B && C"]  # lista, não texto de shell: sem injeção por ";" ou "&&"


def test_runtime_status_reports_the_last_runs_and_login_wait(ready, factory, fake_claude, monkeypatch):
    ar.execute_run(factory, "chat", runner=lambda *a, **k: _Proc(out="", err="Please run /login", code=1))
    with factory() as s:
        status = ar.runtime_status(s)
    assert status["waiting_for_login"] is True and status["claude_found"] is True
    assert status["runs"][0]["status"] == "needs_login" and status["schedule"] == {"morning_from_hour": 8, "evening_from_hour": 19}
    assert status["usage_today"]["runs"] == 1 and status["usage_today"]["cost_usd"] == 0


# ----------------------------------------------------------------- custo-benefício ---------


def test_command_is_lean_native_tools_off_json_usage_budget_and_effort(tmp_path):
    cmd = ar.build_command("claude", "oi", tmp_path / "mcp.json", trigger="chat")
    assert cmd[cmd.index("--tools") + 1] == ""  # sem ferramentas nativas: é o que derruba ~40 mil tokens por rodada
    assert "--disable-slash-commands" in cmd and cmd[cmd.index("--setting-sources") + 1] == "project"
    assert cmd[cmd.index("--output-format") + 1] == "json" and "--max-budget-usd" in cmd
    assert cmd[cmd.index("--effort") + 1] == "low" and cmd[cmd.index("--model") + 1] == "sonnet"
    assert ar.build_command("claude", "oi", tmp_path / "m.json", trigger="morning")[
        ar.build_command("claude", "oi", tmp_path / "m.json", trigger="morning").index("--effort") + 1] == "medium"
    assert ar.agent_cwd().is_dir()  # pasta própria e vazia: não carrega o CLAUDE.md do projeto


def test_usage_is_read_from_the_json_output_and_stored_on_the_run(ready, factory, fake_claude):
    import json
    payload = {"type": "result", "is_error": False, "result": "Feito. 1 produto escolhido.", "num_turns": 7,
               "total_cost_usd": 0.1234, "modelUsage": {"claude-sonnet-5-5": {}},
               "usage": {"input_tokens": 10, "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 500, "output_tokens": 800}}
    run_id = ar.execute_run(factory, "chat", runner=lambda *a, **k: _Proc(out=json.dumps(payload)))
    with factory() as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "ok" and run.output_tail == "Feito. 1 produto escolhido."  # só o texto, não o JSON
        assert (run.model, run.num_turns, run.tokens_in, run.tokens_out, run.cost_usd) == ("claude-sonnet-5-5", 7, 3510, 800, 0.1234)
        assert ar.usage_today(s)["cost_usd"] == 0.1234


def test_a_budget_stop_is_reported_as_a_failed_run_with_a_clear_reason(ready, factory, fake_claude):
    import json
    payload = {"type": "result", "is_error": True, "subtype": "error_max_budget_usd", "result": "", "total_cost_usd": 1.02}
    run_id = ar.execute_run(factory, "chat", runner=lambda *a, **k: _Proc(out=json.dumps(payload), code=1))
    with factory() as s:
        run = s.get(AgentRun, run_id)
        assert run.status == "failed" and "teto de custo" in run.error and run.cost_usd == 1.02


def test_plain_text_output_still_works_and_has_no_usage():
    assert ar.parse_output("rodada feita") == ("rodada feita", {})
    assert ar.parse_output("") == ("", {})


def test_daily_caps_stop_automatic_runs_but_not_the_manual_one(ready):
    agent_chat.post_message(ready, author="user", text="oi")
    ready.commit()
    now = datetime.now(UTC).astimezone()
    assert ar.decide_trigger(ready, now=now) == "chat"
    for _ in range(8):  # teto de rodadas automáticas por dia
        _run(ready, "evening", started=now - timedelta(minutes=30))
    assert ar.decide_trigger(ready, now=now) is None and ar.budget_exhausted(ready, now)
    assert ar.decide_trigger(ready, now=now, manual=True) == "manual"

    ready.query(AgentRun).delete()
    ready.add(AgentRun(trigger="morning", status="ok", started_at=now - timedelta(minutes=30), cost_usd=3.5))  # teto de custo
    ready.commit()
    assert ar.decide_trigger(ready, now=now) is None


def test_new_signal_means_an_operator_message_a_sale_or_a_click_since_the_last_run(ready):
    assert ar._has_new_signal(ready, datetime.now(UTC) - timedelta(hours=1)) is False
    agent_chat.post_message(ready, author="user", text="x")
    ready.commit()
    assert ar._has_new_signal(ready, datetime.now(UTC) - timedelta(hours=1)) is True


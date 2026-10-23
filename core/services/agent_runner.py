"""Supervisor do agente: dispara o Claude em segundo plano, sem terminal aberto.

Com o **modo agente ligado**, o backend roda o Claude Code em modo sem tela (`claude -p`) quando
há trabalho, e só então:

* **ativação** — há uma tarefa de ativação aberta;
* **chat** — o operador escreveu e o agente ainda não leu (com intervalo mínimo entre rodadas);
* **manhã / noite** — rotinas diárias, só em autonomia `independent` (já calibrada);
* **manual** — o operador pediu "rodar agora".

Segurança — o que o Claude sem tela enxerga e pode fazer:

* **Só o servidor do marketTon** (`--strict-mcp-config`): nenhum outro servidor MCP da máquina;
* **lista fechada de ferramentas**: as do marketTon; terminal, edição de arquivos e web ficam
  proibidos (`--disallowedTools`);
* **sem senha**: o backend emite a sessão do agente e entrega o token só ao processo filho;
* **ambiente mínimo**: o processo filho não herda variáveis do backend (banco, segredos);
* a API continua aplicando papel `bot`, trava do modo agente e auditoria.

Custo-benefício (o foco de quem paga cada token):

* **contexto mínimo**: `--tools ""` tira as ferramentas nativas do Claude Code (a maior parte do prompt — de ~42 mil para
  ~3 mil tokens por rodada), sem skills/plugins/configurações de usuário e numa pasta vazia (sem `CLAUDE.md`);
* **modelo e esforço sob medida** (`AGENT_MODEL`, `AGENT_EFFORT*`): responder o chat usa esforço baixo;
* **o código faz o que não precisa de IA**: vendas e cliques são sincronizados pelo backend antes da rodada;
* **tetos**: orçamento por rodada (`--max-budget-usd`), por dia e número de rodadas por dia;
* **não roda à toa**: a rotina da noite só roda se houve venda, clique ou mensagem desde a última rodada;
* **medição**: custo, turnos e tokens de cada rodada ficam registrados e aparecem na tela.

Login do Claude Code: acontece uma única vez, no terminal (`claude` → `/login`), e fica salvo na conta do
Windows. Se expirar, a rodada falha com um sinal claro: o supervisor **pede no chat**, pausa as
tentativas por um tempo e volta sozinho depois.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import get_settings
from core.db.agent_chat import AgentMessage
from core.db.agent_runs import AgentRun
from core.db.auth import Role, User
from core.db.tracking import ClickEvent, Sale
from core.services import agent_chat
from core.services.app_settings import agent_autonomy, agent_mode_enabled
from core.services.auth import issue_agent_session

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TICK_SECONDS = 30
CHAT_COOLDOWN = timedelta(minutes=5)
LOGIN_RETRY = timedelta(minutes=15)
OUTPUT_TAIL = 3000
PREFETCH_EVERY = timedelta(minutes=30)  # no máximo uma sincronização "grátis" a cada tanto
MORNING_UNTIL, EVENING_UNTIL = 14, 24  # a rotina de cada turno ainda vale até estas horas locais

# Único servidor liberado. Os nomes das ferramentas ficam `mcp__marketton__<ferramenta>`.
ALLOWED_TOOLS = ["mcp__marketton"]
DENIED_TOOLS = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Read", "Glob", "Grep"]

_LOGIN_SIGNS = re.compile(
    r"not logged in|please run /login|run /login|invalid api key|oauth token has expired|authentication_error|"
    r"credit balance|unauthorized|log in to|sign in", re.I)

COMMON = (
    "\n\nVocê roda em SEGUNDO PLANO, sem ninguém olhando o terminal. Não faça perguntas que exijam resposta imediata: "
    "deixe dúvidas e pedidos no chat (`chat_send`, `request_resource`). Use só as ferramentas do marketTon. "
    "Termine com uma resposta de 1 a 3 linhas dizendo o que foi feito.\n"
    "SEJA ECONÔMICO (cada token custa): leia só a seção do manual de que precisa (`agent_playbook` com `section`), chame cada "
    "ferramenta uma vez, use `limit` pequeno (até 10), não repita consulta nem pedido, e não reescreva o que já está no chat."
)
PROMPTS = {
    "activation": (
        "Execute a rotina de ativação do marketTon: leia `agent_playbook` (completo, é a primeira vez) e `chat_inbox` e siga a tarefa aberta "
        "(saúde, vendas, análise do catálogo e do portfólio, escolha dos produtos, relatório no chat, pedidos de recurso). "
        "Ao terminar, conclua a tarefa com `complete_task`."
    ),
    "chat": (
        "O operador deixou mensagens novas no chat do marketTon. Leia `chat_inbox` (e `agent_playbook` com `section` "
        "só se precisar de uma regra), responda com `chat_send` e faça o que ele pediu dentro das suas ferramentas e limites."
    ),
    "morning": (
        "Rotina da MANHÃ do marketTon (`agent_playbook` com section=\"1\" e section=\"2\"): `chat_inbox`, `system_health`, "
        "`goals_status` (metas do mês), `daily_review` (vendas e cliques já foram sincronizados pelo sistema: resuma as vendas novas), trate o que o "
        "checklist apontar, escolha o produto do dia e deixe o plano de conteúdo no chat. Cobre os recursos pendentes mais "
        "importantes com `request_resource` (renova, não duplica)."
    ),
    "evening": (
        "Rotina da NOITE do marketTon (`agent_playbook` com section=\"2\"): `chat_inbox`, `goals_status`, `sales_performance` (vendas e "
        "cliques já foram sincronizados pelo sistema), o que performou e o que não, ajuste de ângulo/produto, plano do dia "
        "seguinte. Registre o resumo no chat."
    ),
    "manual": (
        "O operador pediu uma rodada agora. Leia `chat_inbox` e `agent_playbook` (section=\"2\"), execute a rotina do "
        "período do dia e registre o resultado no chat."
    ),
}

# Variáveis de ambiente que o Windows/Claude precisam; nada do ambiente do backend além disto.
_ENV_WHITELIST = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "ComSpec", "USERPROFILE", "HOME", "HOMEDRIVE",
    "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "TEMP", "TMP", "USERNAME",
    "COMPUTERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "LANG", "LC_ALL", "TERM", "SHELL",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS",
)


# --------------------------------------------------------------------- decisão ---------


def _local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone()


def _agent_user(session: Session) -> User | None:
    return session.scalar(select(User).where(User.role == Role.BOT, User.is_active.is_(True)).order_by(User.id))


def _runs_since(session: Session, since: datetime) -> list[AgentRun]:
    # Filtro em Python: comparar timestamps no SQL varia de precisão entre bancos.
    return [r for r in session.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(200))
            if (r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=UTC)) >= since]


def decide_trigger(session: Session, *, now: datetime | None = None, manual: bool = False) -> str | None:
    """Qual rodada fazer agora, ou `None`. Não escreve nada."""
    settings = get_settings()
    now_local = _local(now or datetime.now(UTC))
    if not agent_mode_enabled(session) or _agent_user(session) is None:
        return None

    recent = list(session.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(50)))
    if any(r.status == "running" and _is_live(r) for r in recent):
        return None  # uma rodada por vez (vale também entre processos)
    last_login_fail = next((r for r in recent if r.status == "needs_login"), None)
    if last_login_fail and recent[0].id == last_login_fail.id:
        finished = last_login_fail.finished_at or last_login_fail.started_at
        if (now_local - _local(finished)) < LOGIN_RETRY and not manual:
            return None  # aguardando o login do Claude Code

    if manual:
        return "manual"
    if budget_exhausted(session, now_local):
        return None  # teto do dia (rodadas ou custo): só o "rodar agora" manual passa

    open_activation = session.scalar(select(AgentMessage.id).where(
        AgentMessage.kind == "task", AgentMessage.status == "open", AgentMessage.meta["task"].as_string() == "activation_routine"))
    if open_activation:
        # Só repete a ativação depois de uma rodada que não a concluiu (falha) e esperando um pouco.
        last_act = next((r for r in recent if r.trigger == "activation"), None)
        if last_act is None or (now_local - _local(last_act.finished_at or last_act.started_at)) >= timedelta(minutes=20):
            return "activation"

    unread_from_user = session.scalar(select(AgentMessage.id).where(
        AgentMessage.author == "user", AgentMessage.read_by_agent.is_(False)))
    if unread_from_user:
        last_chat = next((r for r in recent if r.trigger == "chat"), None)
        if last_chat is None or (now_local - _local(last_chat.started_at)) >= CHAT_COOLDOWN:
            return "chat"

    if agent_autonomy(session) == "independent":
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today = _runs_since(session, midnight)
        done = {r.trigger for r in today}
        morning_from, evening_from = settings.agent_morning_hour, settings.agent_evening_hour
        if evening_from <= now_local.hour < EVENING_UNTIL and "evening" not in done:
            since = max([midnight] + [_local(r.started_at) for r in today if r.status == "ok"])
            if _has_new_signal(session, since):  # sem venda, clique nem mensagem nova, a noite não teria o que analisar
                return "evening"
        if morning_from <= now_local.hour < MORNING_UNTIL and "morning" not in done:
            return "morning"
    return None


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def _has_new_signal(session: Session, since: datetime) -> bool:
    """Houve venda, clique ou mensagem do operador desde `since`? (comparação em Python: precisão varia entre bancos)"""
    user_msg = select(AgentMessage.created_at).where(AgentMessage.author == "user")
    for query in (select(Sale.created_at), select(ClickEvent.created_at), user_msg):
        stamp = _aware(session.scalar(query.order_by(query.selected_columns[0].desc()).limit(1)))
        if stamp is not None and stamp >= since:
            return True
    return False


def usage_today(session: Session, now_local: datetime | None = None) -> dict:
    """Rodadas e custo de hoje (hora local), para os tetos e para a tela."""
    now_local = now_local or _local(datetime.now(UTC))
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    runs = _runs_since(session, midnight)
    settings = get_settings()
    return {
        "runs": len([r for r in runs if r.trigger != "manual"]),
        "max_runs": settings.agent_max_runs_per_day,
        "cost_usd": round(sum(r.cost_usd or 0 for r in runs), 4),
        "daily_budget_usd": settings.agent_daily_budget_usd,
        "tokens": sum((r.tokens_in or 0) + (r.tokens_out or 0) for r in runs),
    }


def budget_exhausted(session: Session, now_local: datetime | None = None) -> bool:
    u = usage_today(session, now_local)
    return u["runs"] >= u["max_runs"] or u["cost_usd"] >= u["daily_budget_usd"]


def _is_live(run: AgentRun) -> bool:
    """Uma rodada 'running' só vale se começou há menos que o timeout (senão é resto de um processo que caiu)."""
    limit = timedelta(minutes=get_settings().agent_run_timeout_minutes + 5)
    started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - started < limit


# --------------------------------------------------------------------- execução ---------


def find_claude() -> str | None:
    configured = get_settings().agent_claude_bin.strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("claude")
    if found:
        return found
    # O backend pode ter subido de um terminal cujo PATH não inclui a pasta do instalador do Claude Code.
    for candidate in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if candidate.exists():
            return str(candidate)
    return None


def effort_for(trigger: str) -> str:
    settings = get_settings()
    return settings.agent_effort_chat if trigger == "chat" else settings.agent_effort


def build_command(claude_bin: str, prompt: str, mcp_config: Path, *, trigger: str = "manual") -> list[str]:
    settings = get_settings()
    command = [
        claude_bin, "-p", prompt,
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--tools", "",  # nenhuma ferramenta nativa: só as do marketTon (e o prompt fica ~40 mil tokens menor)
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DENIED_TOOLS,
        "--disable-slash-commands", "--setting-sources", "project",  # sem skills, plugins nem configuração do usuário
        "--output-format", "json", "--no-session-persistence",
        "--max-budget-usd", str(settings.agent_run_budget_usd),
        "--effort", effort_for(trigger),
    ]
    if settings.agent_model.strip():
        command += ["--model", settings.agent_model.strip()]
    return command


def agent_cwd() -> Path:
    """Pasta vazia e própria: o Claude Code não carrega o CLAUDE.md nem a memória do projeto a cada rodada."""
    path = Path(tempfile.gettempdir()) / "marketton-agent-cwd"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_output(raw: str | None) -> tuple[str, dict]:
    """Separa o texto da resposta do consumo (a saída `json` do Claude Code). Se não for JSON, devolve o texto cru."""
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text, {}
    if not isinstance(data, dict) or "result" not in data and "usage" not in data:
        return text, {}
    usage = data.get("usage") or {}
    models = list((data.get("modelUsage") or {}).keys())
    meta = {
        "model": models[0] if models else None,
        "num_turns": data.get("num_turns"),
        "tokens_in": sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")) or None,
        "tokens_out": usage.get("output_tokens"),
        "cost_usd": data.get("total_cost_usd"),
        "is_error": bool(data.get("is_error")),
        "subtype": data.get("subtype"),
    }
    return str(data.get("result") or ""), meta


def prefetch(session_factory: Callable[[], Session]) -> None:
    """Sincroniza vendas e cliques por código (sem IA, sem custo de token) antes de uma rodada. Falha em silêncio."""
    global _last_prefetch
    now = datetime.now(UTC)
    if _last_prefetch and now - _last_prefetch < PREFETCH_EVERY:
        return
    _last_prefetch = now
    from backend.deps import get_adapters  # import tardio: a camada de serviços não depende da API
    from core.services import aistudio, link_shortener, meta_campaigns, sales_sync

    with session_factory() as session:
        for name, job in (("vendas", lambda: sales_sync.sync_sales(session, get_adapters(), since_days=30)),
                          ("cliques", lambda: link_shortener.sync_clicks(session)),
                          ("anúncios", lambda: meta_campaigns.sync_metrics(session)),
                          ("criativos", lambda: aistudio.reconcile(session))):
            try:
                job()
                session.commit()
            except Exception as exc:  # noqa: BLE001 - serviço não configurado ou fora do ar não pode travar a rodada
                session.rollback()
                logger.info("sincronização prévia de %s não feita: %s", name, exc)


_last_prefetch: datetime | None = None


def child_env(token: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}
    env["MARKETTON_API_URL"] = f"http://127.0.0.1:{get_settings().port}"
    env["MARKETTON_AGENT_ACCESS_TOKEN"] = token
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def _write_mcp_config() -> Path:
    config = {"mcpServers": {"marketton": {
        "command": sys.executable, "args": ["-m", "mcp_server"],
        "env": {"PYTHONPATH": str(PROJECT_ROOT)},
    }}}
    path = Path(tempfile.gettempdir()) / "marketton-agent-mcp.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _tail(text: str | None) -> str:
    text = (text or "").strip()
    return text[-OUTPUT_TAIL:]


def execute_run(
    session_factory: Callable[[], Session],
    trigger: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> int | None:
    """Faz uma rodada completa e registra o resultado. Devolve o id da rodada."""
    runner = runner or subprocess.run
    claude = find_claude()

    with session_factory() as session:
        run = AgentRun(trigger=trigger, status="running", started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        run_id = run.id

        if claude is None:
            _finish(session, run, status="failed", error="Claude Code não encontrado no PATH")
            agent_chat.upsert_open_request(session, text=(
                "**Instalar o Claude Code**\nPor quê: o agente roda em segundo plano pelo Claude Code, que não foi "
                "encontrado nesta máquina.\nComo fornecer: instale o Claude Code e abra `claude` uma vez para entrar na sua conta."),
                meta={"resource": "claude_code_instalado", "category": "credencial"})
            session.commit()
            return run_id

        user = _agent_user(session)
        token = issue_agent_session(session, user)
        session.commit()

    if trigger in ("morning", "evening", "manual"):
        prefetch(session_factory)
    command = build_command(claude, PROMPTS[trigger] + COMMON, _write_mcp_config(), trigger=trigger)
    started = datetime.now(UTC)
    try:
        kwargs = {"capture_output": True, "stdin": subprocess.DEVNULL, "text": True, "encoding": "utf-8", "errors": "replace",
                  "timeout": get_settings().agent_run_timeout_minutes * 60, "env": child_env(token), "cwd": str(agent_cwd())}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: nada de janela de terminal
        proc = runner(command, **kwargs)
        out, err, code = proc.stdout, proc.stderr, proc.returncode
        out, usage = parse_output(out)
        status, error = ("ok", None) if code == 0 and not usage.get("is_error") else ("failed", f"saída com código {code}")
        if usage.get("subtype") == "error_max_budget_usd":
            error = "o teto de custo da rodada foi atingido (AGENT_RUN_BUDGET_USD)"
        if code != 0 and _LOGIN_SIGNS.search(f"{out}\n{err}"):
            status, error = "needs_login", "o Claude Code não está logado"
    except subprocess.TimeoutExpired as exc:
        out, err, code, status, error = (exc.stdout or ""), (exc.stderr or ""), None, "timeout", "passou do tempo máximo"
        usage = {}
    except OSError as exc:
        out, err, code, status, error = "", str(exc), None, "failed", f"não foi possível iniciar: {exc}"
        usage = {}

    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        _finish(session, run, status=status, error=error, exit_code=code,
                output=(out if status == "ok" else f"{out}\n{err}"), started=started)
        run.model, run.num_turns = usage.get("model"), usage.get("num_turns")
        run.tokens_in, run.tokens_out, run.cost_usd = usage.get("tokens_in"), usage.get("tokens_out"), usage.get("cost_usd")
        if status == "needs_login":
            agent_chat.upsert_open_request(session, text=(
                "**Entrar no Claude Code (uma vez)**\nPor quê: o agente roda em segundo plano pelo Claude Code, e o login "
                "da sua conta expirou ou nunca foi feito.\nComo fornecer: abra um terminal, rode `claude` e use `/login`. "
                "Depois disso o agente volta a trabalhar sozinho (o sistema tenta de novo em alguns minutos)."),
                meta={"resource": "login_claude_code", "category": "credencial"})
        elif status in ("failed", "timeout"):
            agent_chat.post_message(session, author="system", kind="alert",
                                    text=f"⚠️ Rodada do agente ({trigger}) terminou com problema: {error}. Veja o painel de execução em segundo plano.")
        session.commit()
    return run_id


def _finish(session: Session, run: AgentRun, *, status: str, error: str | None = None, exit_code: int | None = None,
            output: str | None = None, started: datetime | None = None) -> None:
    now = datetime.now(UTC)
    run.status, run.error, run.exit_code = status, (error or None), exit_code
    run.finished_at = now
    run.duration_seconds = round((now - (started or run.started_at)).total_seconds(), 1)
    run.output_tail = _tail(output)
    session.flush()


# --------------------------------------------------------------------- supervisor ---------


class AgentSupervisor(threading.Thread):
    """Laço em segundo plano: a cada `TICK_SECONDS` decide e executa uma rodada, se houver."""

    def __init__(self, session_factory: Callable[[], Session], *, tick: float = TICK_SECONDS,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
        super().__init__(name="agent-supervisor", daemon=True)
        self._factory, self._tick, self._runner = session_factory, tick, runner
        self._stop_event, self._wake, self._manual = threading.Event(), threading.Event(), False
        self.current: str | None = None

    def request_manual(self) -> None:
        self._manual = True
        self._wake.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    def tick(self) -> int | None:
        manual, self._manual = self._manual, False
        with self._factory() as session:
            trigger = decide_trigger(session, manual=manual)
        if trigger is None:
            return None
        self.current = trigger
        try:
            return execute_run(self._factory, trigger, runner=self._runner)
        finally:
            self.current = None

    def run(self) -> None:  # pragma: no cover - laço de thread; a lógica está em `tick`
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - o supervisor nunca pode morrer por um erro passageiro
                logger.exception("falha no supervisor do agente")
            self._wake.wait(self._tick)
            self._wake.clear()


_supervisor: AgentSupervisor | None = None


def start_supervisor(session_factory: Callable[[], Session]) -> AgentSupervisor | None:
    global _supervisor
    if not get_settings().agent_autorun or _supervisor is not None:
        return _supervisor
    _supervisor = AgentSupervisor(session_factory)
    _supervisor.start()
    logger.info("supervisor do agente iniciado (%s)", "Claude Code encontrado" if find_claude() else "Claude Code NÃO encontrado")
    return _supervisor


def stop_supervisor() -> None:
    global _supervisor
    if _supervisor is not None:
        _supervisor.stop()
        _supervisor = None


def get_supervisor() -> AgentSupervisor | None:
    return _supervisor


def runtime_status(session: Session) -> dict:
    """Estado para a tela: o que está rodando, se o Claude Code existe, últimas rodadas."""
    runs = list(session.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(10)))
    blocked = bool(runs and runs[0].status == "needs_login")
    sup = get_supervisor()
    return {
        "autorun": get_settings().agent_autorun,
        "supervisor_alive": bool(sup and sup.is_alive()),
        "claude_found": find_claude() is not None,
        "running_now": sup.current if sup else None,
        "waiting_for_login": blocked,
        "usage_today": usage_today(session),
        "settings": {"model": get_settings().agent_model or "padrão do Claude Code", "effort": get_settings().agent_effort,
                     "effort_chat": get_settings().agent_effort_chat, "run_budget_usd": get_settings().agent_run_budget_usd},
        "schedule": {"morning_from_hour": get_settings().agent_morning_hour, "evening_from_hour": get_settings().agent_evening_hour},
        "runs": [{
            "id": r.id, "trigger": r.trigger, "status": r.status,
            "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_seconds": r.duration_seconds, "error": r.error, "output_tail": r.output_tail,
            "model": r.model, "num_turns": r.num_turns, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "cost_usd": r.cost_usd,
        } for r in runs],
    }

"""Serviço de autenticação: registro, login, refresh, revogação e auditoria.

Regras de negócio ficam aqui, não nos endpoints. Cada decisão está justificada no
lugar onde é tomada, porque auth é a área em que um detalhe silencioso vira
vulnerabilidade.

Princípios aplicados:

* **Bloqueio temporário após tentativas falhas.** Sem isso, a única defesa contra
  força bruta seria a boa vontade do atacante.
* **Mesma mensagem para usuário inexistente e senha errada.** Distinguir os dois
  permite enumerar contas válidas.
* **Refresh token com estado, guardado como hash.** Permite logout real, que um JWT
  puro não oferece, e um vazamento do banco não permite usar os tokens.
* **Auditoria de toda ação sensível**, com ator e resultado. O briefing seção 7 já
  exige autor nas transições de portfólio; aqui é o mesmo princípio para contas.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.auth import AuditLog, RefreshToken, Role, User
from core.services.security import (
    SecurityError,
    TokenExpired,
    TokenInvalid,
    create_token_pair,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    validate_password_strength,
    verify_password,
)

# Bloqueio após N falhas, por M minutos. Valores conservadores: a operação tem
# poucos usuários legítimos, então bloquear cedo custa pouco e protege muito.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


class AuthError(RuntimeError):
    """Falha de autenticação. A mensagem é segura para exibir ao cliente."""


class InvalidCredentials(AuthError):
    """Usuário ou senha incorretos — deliberadamente indistinguíveis."""


class AccountLocked(AuthError):
    """Conta temporariamente bloqueada por tentativas falhas."""


class AccountInactive(AuthError):
    """Conta desativada por um administrador."""


class UserExists(AuthError):
    """Nome de usuário já em uso."""


class WeakPassword(AuthError):
    """Senha não atende às regras mínimas."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class AuthResult:
    user: User
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(value: datetime | None) -> datetime | None:
    """SQLite devolve datetime sem tzinfo; comparar com aware levanta TypeError."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def audit(
    session: Session,
    *,
    actor: str | None,
    action: str,
    outcome: str = "success",
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Registra uma ação sensível. Não faz commit: o chamador decide a transação."""
    record = AuditLog(
        actor=actor,
        actor_role=actor_role,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    session.add(record)
    return record


# --- Usuários -----------------------------------------------------------------


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: Role = Role.VIEWER,
    email: str | None = None,
    created_by: str | None = None,
) -> User:
    """Cria um usuário com senha hasheada e política de força aplicada."""
    username = username.strip()
    if not username:
        raise AuthError("nome de usuário é obrigatório")

    problems = validate_password_strength(password)
    if problems:
        raise WeakPassword(problems)

    if get_user_by_username(session, username) is not None:
        raise UserExists(f"o usuário '{username}' já existe")

    user = User(
        username=username,
        email=email or None,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        password_changed_at=_now(),
        created_by=created_by,
    )
    session.add(user)
    session.flush()
    return user


def set_password(session: Session, user: User, password: str) -> None:
    """Troca a senha e revoga todos os refresh tokens do usuário.

    Revogar é necessário: sem isso, uma sessão aberta antes da troca continuaria
    válida, o que anula o propósito de trocar a senha após um incidente.
    """
    problems = validate_password_strength(password)
    if problems:
        raise WeakPassword(problems)

    user.password_hash = hash_password(password)
    user.password_changed_at = _now()
    user.failed_login_count = 0
    user.locked_until = None
    revoke_all_user_tokens(session, user.id)


def set_active(session: Session, user: User, *, active: bool) -> None:
    """Ativa ou desativa a conta. Desativar revoga os tokens existentes."""
    user.is_active = active
    if not active:
        revoke_all_user_tokens(session, user.id)


# --- Login --------------------------------------------------------------------


def authenticate(
    session: Session,
    *,
    username: str,
    password: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> User:
    """Valida credenciais, com bloqueio por tentativas e trilha de auditoria."""
    user = get_user_by_username(session, username)

    if user is None:
        # Auditoria registra a tentativa, mas a resposta ao cliente é idêntica à de
        # senha errada — distinguir permitiria enumerar contas válidas.
        audit(
            session,
            actor=username,
            action="auth.login",
            outcome="failure",
            detail="usuário inexistente",
            client_ip=client_ip,
            user_agent=user_agent,
        )
        session.commit()
        raise InvalidCredentials("usuário ou senha incorretos")

    locked_until = _ensure_aware(user.locked_until)
    if locked_until is not None and locked_until > _now():
        remaining = int((locked_until - _now()).total_seconds() // 60) + 1
        audit(
            session,
            actor=username,
            action="auth.login",
            outcome="locked",
            actor_role=user.role.value,
            detail=f"bloqueado por mais {remaining} minuto(s)",
            client_ip=client_ip,
            user_agent=user_agent,
        )
        session.commit()
        raise AccountLocked(
            f"conta temporariamente bloqueada por tentativas falhas. "
            f"Tente novamente em {remaining} minuto(s)."
        )

    if not user.is_active:
        audit(
            session,
            actor=username,
            action="auth.login",
            outcome="inactive",
            actor_role=user.role.value,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        session.commit()
        raise AccountInactive("conta desativada")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        detail = f"senha incorreta ({user.failed_login_count}/{MAX_FAILED_LOGINS})"

        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
            detail = f"senha incorreta; conta bloqueada por {LOCKOUT_MINUTES} minutos"

        audit(
            session,
            actor=username,
            action="auth.login",
            outcome="failure",
            actor_role=user.role.value,
            detail=detail,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        session.commit()
        raise InvalidCredentials("usuário ou senha incorretos")

    # Sucesso: zera o contador e, se o custo do hash mudou, regrava.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    audit(
        session,
        actor=username,
        action="auth.login",
        outcome="success",
        actor_role=user.role.value,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    session.flush()
    return user


def login(
    session: Session,
    *,
    username: str,
    password: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> AuthResult:
    """Autentica e emite o par de tokens."""
    user = authenticate(
        session, username=username, password=password, client_ip=client_ip, user_agent=user_agent
    )

    from config.settings import get_settings

    pair, refresh_hash, refresh_expires = create_token_pair(
        subject=user.username, role=user.role.value, settings=get_settings()
    )

    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
            user_agent=(user_agent or "")[:255] or None,
            client_ip=client_ip,
        )
    )
    session.commit()
    session.refresh(user)

    return AuthResult(
        user=user,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


# --- Sessão -------------------------------------------------------------------


def resolve_access_token(session: Session, token: str) -> User:
    """Resolve o usuário a partir do access token.

    Revalida contra o banco em vez de confiar apenas no JWT: um usuário desativado
    ou com papel alterado precisa perder o acesso imediatamente, e um token sem
    estado manteria o papel antigo até expirar.
    """
    try:
        payload = decode_access_token(token)
    except TokenExpired as exc:
        raise AuthError("token expirado") from exc
    except TokenInvalid as exc:
        raise AuthError(str(exc)) from exc

    username = payload.get("sub")
    if not username:
        raise AuthError("token sem sujeito")

    user = get_user_by_username(session, username)
    if user is None:
        raise AuthError("usuário do token não existe mais")
    if not user.is_active:
        raise AccountInactive("conta desativada")

    return user


def refresh_session(
    session: Session,
    *,
    refresh_token: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> AuthResult:
    """Troca um refresh token válido por um par novo, **rotacionando** o refresh.

    A rotação é deliberada: um refresh token reutilizável indefinidamente é um
    segredo de longa duração. Emitindo um novo a cada uso e revogando o anterior,
    a janela de exploração de um vazamento fica limitada ao intervalo entre usos.
    """
    token_hash = hash_refresh_token(refresh_token)
    stored = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    if stored is None:
        audit(
            session,
            actor=None,
            action="auth.refresh",
            outcome="failure",
            detail="refresh token desconhecido",
            client_ip=client_ip,
            user_agent=user_agent,
        )
        session.commit()
        raise AuthError("refresh token inválido")

    if not stored.is_usable:
        audit(
            session,
            actor=None,
            action="auth.refresh",
            outcome="failure",
            detail="refresh token expirado ou revogado",
            client_ip=client_ip,
            user_agent=user_agent,
        )
        session.commit()
        raise AuthError("refresh token expirado ou revogado. Faça login novamente.")

    user = session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthError("conta indisponível")

    # Rotação: revoga o usado antes de emitir o próximo.
    stored.revoked_at = _now()

    from config.settings import get_settings

    pair, refresh_hash, refresh_expires = create_token_pair(
        subject=user.username, role=user.role.value, settings=get_settings()
    )
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
            user_agent=(user_agent or "")[:255] or None,
            client_ip=client_ip,
        )
    )
    audit(
        session,
        actor=user.username,
        action="auth.refresh",
        outcome="success",
        actor_role=user.role.value,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    session.commit()

    return AuthResult(
        user=user,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


def revoke_refresh_token(session: Session, refresh_token: str) -> bool:
    """Revoga um refresh token específico. Devolve se algo foi revogado."""
    token_hash = hash_refresh_token(refresh_token)
    stored = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if stored is None or stored.revoked_at is not None:
        return False
    stored.revoked_at = _now()
    return True


def revoke_all_user_tokens(session: Session, user_id: int) -> int:
    """Revoga todos os refresh tokens do usuário. Usado em troca de senha e logout global."""
    active = session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    ).all()
    now = _now()
    for token in active:
        token.revoked_at = now
    return len(active)


def prune_expired_tokens(session: Session, *, older_than_days: int = 30) -> int:
    """Remove tokens expirados há mais de N dias. Higiene, não segurança."""
    cutoff = _now() - timedelta(days=older_than_days)
    expired = session.scalars(
        select(RefreshToken).where(RefreshToken.expires_at < cutoff)
    ).all()
    for token in expired:
        session.delete(token)
    return len(expired)


# --- Bootstrap ----------------------------------------------------------------


def ensure_admin(
    session: Session,
    *,
    username: str,
    password: str,
) -> User | None:
    """Cria o primeiro administrador quando não existe nenhum usuário.

    Existe porque a API precisa de um caminho de entrada: sem usuário nenhum, não
    há como autenticar para criar o primeiro. Só age quando a tabela está vazia, e
    nunca altera uma conta existente.
    """
    existing_count = session.scalar(select(User.id).limit(1))
    if existing_count is not None:
        return None

    user = create_user(
        session,
        username=username,
        password=password,
        role=Role.ADMIN,
        created_by="bootstrap",
    )
    audit(
        session,
        actor="bootstrap",
        action="auth.bootstrap_admin",
        outcome="success",
        actor_role=Role.ADMIN.value,
        resource_type="user",
        resource_id=str(user.id),
        detail=f"administrador inicial '{username}' criado",
    )
    session.commit()
    session.refresh(user)
    return user


__all__ = [
    "LOCKOUT_MINUTES",
    "MAX_FAILED_LOGINS",
    "AccountInactive",
    "AccountLocked",
    "AuthError",
    "AuthResult",
    "InvalidCredentials",
    "SecurityError",
    "UserExists",
    "WeakPassword",
    "audit",
    "authenticate",
    "create_user",
    "ensure_admin",
    "get_user_by_username",
    "login",
    "prune_expired_tokens",
    "refresh_session",
    "resolve_access_token",
    "revoke_all_user_tokens",
    "revoke_refresh_token",
    "set_active",
    "set_password",
]

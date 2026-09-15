"""Endpoints de autenticação e gestão de usuários.

Contrato que o frontend consome:

1. `POST /auth/login` com usuário e senha → par de tokens.
2. Guarda o access token em memória e o refresh token de forma persistente.
3. A cada requisição, `Authorization: Bearer <access>`.
4. Ao receber 401 por expiração, `POST /auth/refresh` com o refresh token → par novo.
   O refresh **rotaciona**: o token usado é revogado, então o cliente precisa
   substituir o que guardou.
5. `GET /auth/me` devolve papel e permissões, para o frontend montar a navegação.

O frontend usa as permissões para **esconder** o que o usuário não pode fazer. Quem
recusa a requisição é a API — o briefing seção 13 pede que as regras fiquem no
backend.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.deps import get_session
from backend.security import (
    CurrentUser,
    Principal,
    optional_principal,
    record_action,
    require,
)
from core.db.auth import AuditLog, Role, User
from core.roles import role_matrix
from core.services.auth import (
    AccountInactive,
    AccountLocked,
    AuthError,
    InvalidCredentials,
    UserExists,
    WeakPassword,
    create_user,
    login,
    refresh_session,
    revoke_all_user_tokens,
    revoke_refresh_token,
    set_active,
    set_password,
)
from core.services.security import SecurityError

router = APIRouter(prefix="/auth", tags=["autenticação"])


# --- Schemas ------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    all_sessions: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    role: str
    is_active: bool
    last_login_at: str | None = None


class MeResponse(UserOut):
    """Inclui as permissões para o frontend montar a navegação."""

    permissions: list[str]


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=256)
    role: Role = Role.VIEWER
    email: str | None = None


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


# --- Helpers ------------------------------------------------------------------


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


def _token_response(result) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
    )


# --- Sessão -------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse, summary="Autenticar")
def do_login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> TokenResponse:
    """Autentica e devolve o par de tokens.

    Não exige token — é o ponto de entrada. Erros são deliberadamente genéricos:
    distinguir "usuário não existe" de "senha errada" permitiria enumerar contas.
    """
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    try:
        result = login(
            session,
            username=payload.username,
            password=payload.password,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
    except AccountLocked as exc:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(exc)) from exc
    except AccountInactive as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidCredentials as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return _token_response(result)


@router.post("/refresh", response_model=TokenResponse, summary="Renovar sessão")
def do_refresh(payload: RefreshRequest, request: Request, session: Session = Depends(get_session)) -> TokenResponse:
    """Troca o refresh token por um par novo, rotacionando o anterior.

    Se este endpoint devolver 401, o cliente precisa fazer login de novo: significa
    token expirado, revogado ou desconhecido.
    """
    try:
        result = refresh_session(
            session,
            refresh_token=payload.refresh_token,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return _token_response(result)


@router.post("/logout", summary="Encerrar sessão")
def do_logout(
    payload: LogoutRequest,
    session: Session = Depends(get_session),
    # Anotação `Optional` é obrigatória: sem ela o FastAPI interpreta o default
    # `None` como dependência e falha na montagem da rota.
    principal: Optional[Principal] = Depends(optional_principal),
) -> dict:
    """Revoga o refresh token informado, ou todas as sessões do usuário.

    Acessível sem access token válido quando o refresh é informado — o contrário
    impediria o logout justamente quando o usuário mais precisa dele.
    """
    revoked = 0

    if payload.all_sessions:
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="autenticação necessária para encerrar todas as sessões",
            )
        revoked = revoke_all_user_tokens(session, principal.user.id)
        record_action(
            session,
            principal,
            action="auth.logout_all",
            resource_type="user",
            resource_id=str(principal.user.id),
            detail=f"{revoked} sessão(ões) encerrada(s)",
        )
    elif payload.refresh_token:
        if revoke_refresh_token(session, payload.refresh_token):
            revoked = 1

    session.commit()
    return {"ok": True, "revoked": revoked}


@router.get("/me", response_model=MeResponse, summary="Identidade atual")
def me(principal: CurrentUser) -> MeResponse:
    """Usuário autenticado, com papel e permissões.

    É o que o frontend chama no boot para saber o que exibir.
    """
    base = _user_out(principal.user)
    return MeResponse(**base.model_dump(), permissions=principal.permissions)


# --- Administração de usuários ------------------------------------------------


@router.get("/permissions", summary="Matriz de papéis e permissões")
def permission_matrix(principal: CurrentUser) -> dict:
    """Matriz completa. Serve de documentação viva do modelo de autorização."""
    return {
        "roles": [role.value for role in Role],
        "matrix": role_matrix(),
        "current_role": principal.role.value,
        "current_permissions": principal.permissions,
    }


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require("users.manage"))])
def list_users(
    session: Session = Depends(get_session),
    limit: int = 100,
    offset: int = 0,
) -> list[UserOut]:
    users = session.scalars(select(User).order_by(User.username).limit(limit).offset(offset))
    return [_user_out(user) for user in users]


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("users.manage"))],
)
def create_user_endpoint(
    payload: CreateUserRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require("users.manage")),
) -> UserOut:
    """Cria um usuário. Senha fraca é recusada com a lista de problemas."""
    try:
        user = create_user(
            session,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            email=payload.email,
            created_by=principal.username,
        )
    except UserExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except WeakPassword as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "senha não atende aos requisitos", "problems": exc.problems},
        ) from exc
    except (AuthError, SecurityError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    record_action(
        session,
        principal,
        action="auth.user_created",
        resource_type="user",
        resource_id=str(user.id),
        detail=f"papel {user.role.value}",
    )
    session.commit()
    session.refresh(user)
    return _user_out(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require("users.manage"))],
)
def update_user_endpoint(
    user_id: int,
    payload: UpdateUserRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require("users.manage")),
) -> UserOut:
    """Altera papel, ativa/desativa a conta ou troca a senha.

    Duas travas deliberadas contra auto-bloqueio: um administrador não pode
    rebaixar nem desativar a própria conta. Sem isso, um admin pode se trancar
    fora do sistema e não haveria outro caminho de volta.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"usuário {user_id} não encontrado")

    is_self = user.username == principal.username

    if payload.role is not None and payload.role != user.role:
        if is_self and payload.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="um administrador não pode rebaixar a própria conta",
            )
        user.role = payload.role
        record_action(
            session,
            principal,
            action="auth.role_changed",
            resource_type="user",
            resource_id=str(user.id),
            detail=f"novo papel: {payload.role.value}",
        )

    if payload.is_active is not None and payload.is_active != user.is_active:
        if is_self and not payload.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="um administrador não pode desativar a própria conta",
            )
        set_active(session, user, active=payload.is_active)
        record_action(
            session,
            principal,
            action="auth.user_activated" if payload.is_active else "auth.user_deactivated",
            resource_type="user",
            resource_id=str(user.id),
        )

    if payload.password is not None:
        try:
            set_password(session, user, payload.password)
        except WeakPassword as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "senha não atende aos requisitos", "problems": exc.problems},
            ) from exc
        record_action(
            session,
            principal,
            action="auth.password_reset",
            resource_type="user",
            resource_id=str(user.id),
            detail="sessões existentes revogadas",
        )

    session.commit()
    session.refresh(user)
    return _user_out(user)


# --- Auditoria ----------------------------------------------------------------


@router.get("/audit", dependencies=[Depends(require("audit.view"))])
def list_audit(
    session: Session = Depends(get_session),
    action: str | None = None,
    actor: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Trilha de auditoria das ações sensíveis."""
    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
    if actor:
        statement = statement.where(AuditLog.actor == actor)
    if outcome:
        statement = statement.where(AuditLog.outcome == outcome)
    statement = statement.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)

    return [
        {
            "id": record.id,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "actor": record.actor,
            "actor_role": record.actor_role,
            "action": record.action,
            "outcome": record.outcome,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "detail": record.detail,
            "client_ip": record.client_ip,
        }
        for record in session.scalars(statement)
    ]


@router.get("/audit/summary", dependencies=[Depends(require("audit.view"))])
def audit_summary(session: Session = Depends(get_session)) -> dict:
    """Resumo da trilha: falhas de login por ator e ações por tipo.

    Serve para detectar tentativa de força bruta sem ler log de servidor.
    """
    by_action = session.execute(
        select(AuditLog.action, AuditLog.outcome, func.count(AuditLog.id)).group_by(
            AuditLog.action, AuditLog.outcome
        )
    ).all()

    failed_logins = session.execute(
        select(AuditLog.actor, func.count(AuditLog.id))
        .where(AuditLog.action == "auth.login", AuditLog.outcome != "success")
        .group_by(AuditLog.actor)
        .order_by(desc(func.count(AuditLog.id)))
        .limit(10)
    ).all()

    return {
        "by_action": [
            {"action": action, "outcome": outcome, "count": int(count)}
            for action, outcome, count in by_action
        ],
        "failed_logins_by_actor": [
            {"actor": actor, "failures": int(count)} for actor, count in failed_logins
        ],
    }

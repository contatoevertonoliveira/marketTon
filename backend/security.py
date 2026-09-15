"""Dependências de autenticação e autorização do FastAPI.

Como usar nos routers::

    from backend.security import CurrentUser, require

    @router.post("/items", dependencies=[Depends(require("portfolio.manage"))])
    def create(...): ...

    @router.get("/me")
    def me(user: CurrentUser): ...

O padrão é **negar por padrão**: um endpoint sem `require(...)` só é acessível a
usuário autenticado. Para expor algo publicamente é preciso declarar
explicitamente, o que torna a decisão visível em revisão de código.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.deps import get_session
from config.settings import get_settings
from core.db.auth import Role, User
from core.roles import has_permission, permissions_for
from core.services.auth import (
    AccountInactive,
    AuthError,
    audit,
    resolve_access_token,
)

# `auto_error=False` para podermos devolver 401 com mensagem própria em vez do
# 403 genérico que o HTTPBearer emite quando falta o header.
_bearer = HTTPBearer(auto_error=False, description="Token JWT de acesso")


@dataclass(frozen=True)
class Principal:
    """Identidade autenticada da requisição.

    Passar o objeto inteiro (e não só o `user_id`) evita que cada endpoint precise
    reconsultar o banco para conhecer o papel.
    """

    user: User
    username: str
    role: Role
    client_ip: str | None = None
    user_agent: str | None = None

    @property
    def permissions(self) -> list[str]:
        return permissions_for(self.role)

    def can(self, permission: str) -> bool:
        return has_permission(self.role, permission)


def _client_ip(request: Request) -> str | None:
    """IP do cliente, respeitando `X-Forwarded-For` quando atrás de proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _unauthenticated(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    session: Session = Depends(get_session),
) -> Principal:
    """Resolve a identidade a partir do access token.

    Quando `AUTH_ENABLED=false`, devolve um principal sintético de administrador
    para permitir desenvolvimento local. Isso é deliberadamente gritante: o `/health`
    reporta o modo e `validate_production_readiness` o inclui na lista de problemas.
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return Principal(
            user=User(  # type: ignore[arg-type] - objeto transiente, não persistido
                id=0,
                username="anonymous-dev",
                password_hash="",
                role=Role.ADMIN,
            ),
            username="anonymous-dev",
            role=Role.ADMIN,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

    if credentials is None or not credentials.credentials:
        raise _unauthenticated("credencial ausente. Envie o header Authorization: Bearer <token>")

    try:
        user = resolve_access_token(session, credentials.credentials)
    except AccountInactive as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AuthError as exc:
        raise _unauthenticated(str(exc)) from exc

    return Principal(
        user=user,
        username=user.username,
        role=user.role,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


CurrentUser = Annotated[Principal, Depends(get_principal)]


def require(permission: str):
    """Cria a dependência que exige uma permissão.

    Devolve uma função para que o nome da permissão apareça na assinatura do
    endpoint — quem lê o código vê qual permissão protege o quê.
    """

    def dependency(principal: CurrentUser) -> Principal:
        if not principal.can(permission):
            # 403 e não 401: o usuário está autenticado, apenas não tem o direito.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": f"permissão negada: '{permission}'",
                    "role": principal.role.value,
                    "required_permission": permission,
                },
            )
        return principal

    # O nome fica legível no /docs, que é onde o frontend descobre o contrato.
    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency


def require_any(*permissions: str):
    """Exige ao menos uma das permissões listadas."""

    def dependency(principal: CurrentUser) -> Principal:
        if not any(principal.can(permission) for permission in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": f"permissão negada: requer uma de {list(permissions)}",
                    "role": principal.role.value,
                },
            )
        return principal

    dependency.__name__ = "require_any_" + "_".join(p.replace(".", "_") for p in permissions)
    return dependency


def record_action(
    session: Session,
    principal: Principal,
    *,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    detail: str | None = None,
) -> None:
    """Registra uma ação sensível na trilha de auditoria.

    Não faz commit: o endpoint já está dentro de uma transação e o registro precisa
    cair junto com a mudança que ele descreve.
    """
    audit(
        session,
        actor=principal.username,
        actor_role=principal.role.value,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        client_ip=principal.client_ip,
        user_agent=principal.user_agent,
    )


async def optional_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
) -> Principal | None:
    """Identidade quando presente, `None` quando anônimo.

    Usado por endpoints que mudam de comportamento conforme o papel, em vez de
    simplesmente bloquear.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        user = resolve_access_token(session, token)
    except (AuthError, AccountInactive):
        return None

    return Principal(
        user=user,
        username=user.username,
        role=user.role,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


__all__ = [
    "CurrentUser",
    "Principal",
    "get_principal",
    "optional_principal",
    "record_action",
    "require",
    "require_any",
]

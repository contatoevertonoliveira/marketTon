"""Permissões por papel, aplicadas pelo backend.

Este módulo existia antes, mas era importado **apenas pelo Streamlit** — ou seja, a
autorização vivia no frontend. O briefing seção 13 é explícito: regras, scores,
estados, permissões e decisões operacionais devem permanecer centralizados no
backend. O frontend pode esconder um botão; quem recusa a requisição é a API.

O que mudou em relação à versão anterior:

* O enum `Role` agora é o de `core/db/auth.py`, persistido no banco. Antes havia um
  enum em `core/roles.py` e outro papel em JSONL relativo ao diretório de trabalho,
  além de uma tabela `roles` inútil.
* As permissões cobrem as operações que a API de fato expõe, não um conjunto
  genérico herdado.
* Existe uma permissão por **operação de escrita**, não apenas por área: ler o
  catálogo e coletar do marketplace são coisas diferentes.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.db.auth import Role

# Ordem hierárquica, do mais ao menos privilegiado. Usada para permitir que um
# papel herde o que os inferiores podem fazer em leitura.
HIERARCHY: tuple[Role, ...] = (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)


@dataclass(frozen=True)
class Permission:
    name: str
    description: str
    allowed_roles: tuple[Role, ...]


PERMISSIONS: tuple[Permission, ...] = (
    # --- Catálogo -------------------------------------------------------------
    Permission("catalog.view", "Ver produtos e procedência", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    Permission("catalog.ingest", "Coletar catálogo dos marketplaces", (Role.ADMIN, Role.MANAGER, Role.OPERATOR)),
    Permission("catalog.manage", "Inativar produtos e ajustar catálogo", (Role.ADMIN, Role.MANAGER)),
    # --- Scoring --------------------------------------------------------------
    Permission("scoring.view", "Ver scores e explicações", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    Permission("scoring.compute", "Executar cálculo de score", (Role.ADMIN, Role.MANAGER, Role.OPERATOR)),
    Permission("scoring.calibrate", "Publicar nova versão de algoritmo", (Role.ADMIN,)),
    # --- Portfólio ------------------------------------------------------------
    Permission("portfolio.view", "Ver portfólio e trilha de estados", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    Permission("portfolio.manage", "Adicionar produtos e mover estados", (Role.ADMIN, Role.MANAGER, Role.OPERATOR)),
    Permission("portfolio.affiliate", "Marcar afiliação e remover produto", (Role.ADMIN, Role.MANAGER)),
    # --- Criativos ------------------------------------------------------------
    Permission("creatives.view", "Ver materiais criativos", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    Permission("creatives.edit", "Criar e mover status de materiais", (Role.ADMIN, Role.MANAGER, Role.OPERATOR)),
    Permission("creatives.approve", "Aprovar material para publicação", (Role.ADMIN, Role.MANAGER)),
    # --- Publicação -----------------------------------------------------------
    Permission("publication.publish", "Publicar material aprovado", (Role.ADMIN, Role.MANAGER)),
    # --- Operação -------------------------------------------------------------
    Permission("operations.view", "Ver painel diário e revisão semanal", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    Permission("agents.run", "Iniciar e parar agentes", (Role.ADMIN, Role.MANAGER)),
    Permission("jobs.view", "Ver histórico de execução", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    # --- Administração --------------------------------------------------------
    Permission("connectors.manage", "Configurar credenciais de marketplace", (Role.ADMIN,)),
    Permission("users.manage", "Criar, desativar e alterar usuários", (Role.ADMIN,)),
    Permission("audit.view", "Ver trilha de auditoria", (Role.ADMIN,)),
    Permission("support.view", "Ver feedback e preferências", (Role.ADMIN, Role.MANAGER, Role.OPERATOR)),
    Permission("support.manage", "Gerenciar feedback e grupos", (Role.ADMIN, Role.MANAGER)),
    Permission("billing.view", "Ver pagamentos", (Role.ADMIN, Role.MANAGER)),
)

PERMISSIONS_BY_NAME: dict[str, Permission] = {permission.name: permission for permission in PERMISSIONS}


class PermissionDenied(PermissionError):
    """Papel sem a permissão exigida. Distinto de não autenticado (401 vs 403)."""


def has_permission(role: Role | str, permission_name: str) -> bool:
    """True se o papel satisfaz a permissão.

    Permissão desconhecida devolve `False`: negar por padrão é a escolha segura.
    Se um endpoint exigir uma permissão que não existe aqui, ele fica inacessível —
    o que é um erro visível e corrigível, em vez de um buraco silencioso.
    """
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False

    permission = PERMISSIONS_BY_NAME.get(permission_name)
    if permission is None:
        return False
    return role in permission.allowed_roles


def require_permission(role: Role | str, permission_name: str) -> None:
    """Levanta `PermissionDenied` quando falta permissão."""
    if not has_permission(role, permission_name):
        raise PermissionDenied(
            f"o papel '{role.value if isinstance(role, Role) else role}' não tem a permissão "
            f"'{permission_name}'"
        )


def permissions_for(role: Role) -> list[str]:
    """Lista de permissões do papel. Serve para o frontend saber o que exibir.

    Expor a lista é diferente de confiar nela: o frontend usa para esconder botão,
    a API continua recusando a requisição.
    """
    return sorted(
        permission.name
        for permission in PERMISSIONS
        if role in permission.allowed_roles
    )


def role_matrix() -> dict[str, list[str]]:
    """Matriz completa papel → permissões, para documentação e auditoria."""
    return {role.value: permissions_for(role) for role in Role}


# --- Compatibilidade com o dashboard legado -----------------------------------


class RoleManager:
    """Compatibilidade: gerencia papéis pelo banco, com a interface antiga.

    A versão anterior guardava papéis em `data/user_roles.jsonl`, relativo ao
    diretório de trabalho — o que significa que o arquivo ia parar em lugares
    diferentes conforme de onde o processo fosse iniciado, além de duplicar o
    conceito de papel que já existia no banco.

    Esta implementação mantém os métodos que o dashboard chama, mas lê e escreve
    na tabela `users`. O dashboard está em processo de aposentadoria; o shim existe
    para não deixá-lo quebrado durante a transição.
    """

    def __init__(self, path: str | None = None):  # noqa: ARG002 - assinatura legada
        self._session_factory = None

    def _session(self):
        from core.db.session import get_session_factory

        return get_session_factory()()

    def get_role(self, user_id: int) -> Role:
        from core.db.auth import User

        session = self._session()
        try:
            user = session.get(User, user_id)
            return user.role if user else Role.VIEWER
        finally:
            session.close()

    def set_role(self, user_id: int, role: Role, granted_by: int | None = None) -> None:  # noqa: ARG002
        from core.db.auth import User

        session = self._session()
        try:
            user = session.get(User, user_id)
            if user is not None:
                user.role = role
                session.commit()
        finally:
            session.close()

    def has_permission(self, user_id: int, permission: str) -> bool:
        return has_permission(self.get_role(user_id), permission)

    def list_users(self) -> list[dict]:
        from core.db.auth import User

        session = self._session()
        try:
            users = session.query(User).all()
            return [
                {
                    "user_id": user.id,
                    "username": user.username,
                    "role": user.role.value,
                    "is_active": user.is_active,
                }
                for user in users
            ]
        finally:
            session.close()


__all__ = [
    "HIERARCHY",
    "PERMISSIONS",
    "PERMISSIONS_BY_NAME",
    "Permission",
    "PermissionDenied",
    "RoleManager",
    "has_permission",
    "permissions_for",
    "require_permission",
    "role_matrix",
]

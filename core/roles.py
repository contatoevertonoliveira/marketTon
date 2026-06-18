"""Roles e permissões do sistema."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from integrations.user_preferences import find_by_user, list_preferences, save_preference, UserPref


class Role(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    VIEWER = "viewer"
    BOT = "bot"


@dataclass(frozen=True)
class Permission:
    name: str
    description: str
    allowed_roles: tuple[Role, ...]


PERMISSIONS: list[Permission] = [
    Permission("agents.run", "Permite iniciar/parar agentes", (Role.ADMIN, Role.MANAGER)),
    Permission("agents.pause", "Permite pausar agentes", (Role.ADMIN, Role.MANAGER)),
    Permission("reports.view", "Permite ver relatórios", (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER)),
    Permission("reports.edit", "Permite editar relatórios", (Role.ADMIN, Role.MANAGER)),
    Permission("marketplace.manage", "Permite gerenciar marketplaces", (Role.ADMIN, Role.MANAGER)),
    Permission("ads.manage", "Permite gerenciar anúncios", (Role.ADMIN, Role.MANAGER)),
    Permission("feedback.view", "Permite ver feedback", (Role.ADMIN, Role.MANAGER, Role.OPERATOR)),
    Permission("feedback.manage", "Permite gerenciar feedback", (Role.ADMIN,)),
    Permission("users.manage", "Permite gerenciar usuários", (Role.ADMIN,)),
    Permission("roles.manage", "Permite gerenciar roles", (Role.ADMIN,)),
    Permission("billing.view", "Permite ver billing", (Role.ADMIN, Role.MANAGER)),
    Permission("billing.manage", "Permite gerenciar billing", (Role.ADMIN,)),
]


@dataclass
class UserRole:
    user_id: int
    role: Role
    granted_by: int | None = None
    granted_at: str = field(default_factory=lambda: __import__("datetime").datetime.now().isoformat())


class RoleManager:
    def __init__(self, path: str | None = None):
        self.path = path or "data/user_roles.jsonl"
        self._cache: dict[int, Role] = {}
        self._load()

    def _load(self) -> None:
        from pathlib import Path
        p = Path(self.path)
        if not p.exists():
            return
        for line in p.read_text(encoding="utf-8").strip().splitlines():
            try:
                obj = __import__("json").loads(line)
                user_id = int(obj.get("user_id"))
                role = Role(obj.get("role", Role.VIEWER.value))
                self._cache[user_id] = role
            except Exception:
                continue

    def _save(self, user_id: int, role: Role, granted_by: int | None = None) -> None:
        from pathlib import Path
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "user_id": user_id,
            "role": role.value,
            "granted_by": granted_by,
            "granted_at": __import__("datetime").datetime.now().isoformat(),
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(__import__("json").dumps(record, ensure_ascii=False) + "\n")
        self._cache[user_id] = role

    def get_role(self, user_id: int) -> Role:
        return self._cache.get(user_id, Role.VIEWER)

    def set_role(self, user_id: int, role: Role, granted_by: int | None = None) -> None:
        self._save(user_id, role, granted_by)

    def has_permission(self, user_id: int, permission: str) -> bool:
        role = self.get_role(user_id)
        for perm in PERMISSIONS:
            if perm.name == permission:
                return role in perm.allowed_roles
        return False

    def list_users(self) -> list[dict[str, Any]]:
        items = list_preferences(limit=5000)
        users = []
        seen = set()
        for item in items:
            uid = int(item.get("user_id"))
            if uid in seen:
                continue
            seen.add(uid)
            users.append({
                "user_id": uid,
                "username": item.get("username"),
                "role": self.get_role(uid).value,
            })
        return users

"""Group blocker repository: allow/block management."""
from __future__ import annotations

from integrations.group_blocker.models import GroupBlockManager, GroupStatus

_manager: GroupBlockManager | None = None


def get_manager() -> GroupBlockManager:
    global _manager
    if _manager is None:
        _manager = GroupBlockManager()
    return _manager


def allow_group(group_id: int, updated_by: int | None = None, reason: str | None = None):
    return get_manager().set_status(group_id, GroupStatus.ALLOWED, updated_by=updated_by, reason=reason)


def block_group(group_id: int, updated_by: int | None = None, reason: str | None = None):
    return get_manager().set_status(group_id, GroupStatus.BLOCKED, updated_by=updated_by, reason=reason)


def is_group_allowed(group_id: int) -> bool:
    return get_manager().is_allowed(group_id)

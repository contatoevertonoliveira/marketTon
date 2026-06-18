'''Group blocker data models.'''
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class GroupStatus(str, Enum):
    ALLOWED = 'allowed'
    BLOCKED = 'blocked'


@dataclass
class GroupRecord:
    group_id: int
    title: str | None
    status: GroupStatus = GroupStatus.ALLOWED
    reason: str | None = None
    updated_by: int | None = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            'group_id': self.group_id,
            'title': self.title,
            'status': self.status.value,
            'reason': self.reason,
            'updated_by': self.updated_by,
            'updated_at': self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> 'GroupRecord':
        return GroupRecord(
            group_id=int(data['group_id']),
            title=data.get('title'),
            status=GroupStatus(data.get('status', GroupStatus.ALLOWED.value)),
            reason=data.get('reason'),
            updated_by=int(data['updated_by']) if data.get('updated_by') is not None else None,
            updated_at=data.get('updated_at', datetime.now().isoformat()),
        )


class GroupBlockManager:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path(__file__).resolve().parent.parent.parent / 'data' / 'groups_block.jsonl'
        self._cache: dict[int, GroupRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding='utf-8').strip().splitlines():
            try:
                rec = GroupRecord.from_dict(json.loads(line))
                self._cache[rec.group_id] = rec
            except Exception:
                continue

    def _save(self, record: GroupRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + '\n')
        self._cache[record.group_id] = record

    def set_status(self, group_id: int, status: GroupStatus, updated_by: int | None = None, reason: str | None = None) -> 'GroupRecord':
        record = self._cache.get(group_id) or GroupRecord(group_id=group_id, title=None)
        record.status = status
        record.reason = reason
        record.updated_by = updated_by
        record.updated_at = datetime.now().isoformat()
        self._save(record)
        return record

    def get(self, group_id: int) -> GroupRecord | None:
        return self._cache.get(group_id)

    def is_allowed(self, group_id: int) -> bool:
        rec = self._cache.get(group_id)
        if rec is None:
            return True
        return rec.status == GroupStatus.ALLOWED

    def list_groups(self, status_filter: GroupStatus | None = None) -> list['GroupRecord']:
        items = list(self._cache.values())
        if status_filter is not None:
            items = [i for i in items if i.status == status_filter]
        return sorted(items, key=lambda x: x.updated_at, reverse=True)

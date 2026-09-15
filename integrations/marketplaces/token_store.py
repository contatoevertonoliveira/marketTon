"""Armazenamento de tokens OAuth de marketplace.

Necessidade concreta: o adapter do Mercado Livre renova o `access_token` quando
recebe 401, mas gravava o token novo apenas em memória — a cada reinício da API o
token voltava a ser o do `.env`, já expirado, e o ciclo começava de novo com um
401. O refresh precisa sobreviver ao processo.

Segredos ficam em arquivo separado do `.env` (que é editado à mão) e fora do
controle de versão. Permissão restrita quando a plataforma permite.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "marketplace_tokens.json"


@dataclass
class TokenSet:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    @property
    def expires_within(self) -> bool:
        """True quando falta menos de 10 minutos — hora de renovar preventivamente."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at - timedelta(minutes=10)


class TokenStore:
    """Leitura e escrita de tokens por marketplace."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_PATH

    def _read_all(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("não foi possível ler %s: %s", self.path, exc)
            return {}

    def load(self, marketplace: str) -> TokenSet | None:
        data = self._read_all().get(marketplace)
        if not data:
            return None
        expires_at = data.get("expires_at")
        return TokenSet(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
        )

    def save(self, marketplace: str, tokens: TokenSet) -> None:
        data = self._read_all()
        data[marketplace] = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._restrict_permissions()

    def _restrict_permissions(self) -> None:
        """Tenta restringir a permissão. Em Windows isso é majoritariamente no-op."""
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            logger.debug("não foi possível restringir permissão de %s: %s", self.path, exc)

    def clear(self, marketplace: str) -> None:
        data = self._read_all()
        if data.pop(marketplace, None) is not None:
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


__all__ = ["DEFAULT_PATH", "TokenSet", "TokenStore"]

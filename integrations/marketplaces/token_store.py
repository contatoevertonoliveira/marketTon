"""Armazenamento de tokens OAuth de marketplace, no Postgres.

Antes os tokens viviam em `data/marketplace_tokens.json`, um arquivo fora do
banco — enquanto o resto da credencial (client_id/secret/redirect_uri) já
vivia em `marketplace_credentials` desde a Fase 2. Isso quebrava o princípio
de que o banco é a fonte única de verdade: o token de acesso real de uma
integração conectada não aparecia em lugar nenhum da tela de Integrações, não
sobrevivia a um ambiente sem esse arquivo, e não era visível a quem
inspecionasse o banco para saber o estado de uma credencial.

Agora tudo sobre uma credencial de marketplace — estática (client_id, secret,
redirect_uri) e dinâmica (access_token, refresh_token, validade) — vive na
mesma linha de `MarketplaceCredential.values`. A chave da validade
(`token_expires_at_iso`) é deliberadamente diferente do atributo
`MLConfig.token_expires_at` (que é `datetime`, não `str`): assim
`backend/deps.py::_apply_credential_overrides`, que sobrepõe qualquer chave de
`values` que bata com um atributo do `cfg`, nunca tenta atribuir uma string
onde o adapter espera um `datetime`. `access_token`/`refresh_token` já são
`str` nos três configs, então a sobreposição genérica funciona sem ajuste — e
como bônus, um token renovado por `save()` passa a valer no próximo
`get_adapters()` de qualquer processo, não só no que fez a renovação.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

logger = logging.getLogger(__name__)


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
    """Leitura e escrita de tokens OAuth por marketplace, no Postgres."""

    def load(self, marketplace: str) -> TokenSet | None:
        from core.db.base import Marketplace
        from core.db.marketplace_credentials import MarketplaceCredential
        from core.db.session import session_scope

        try:
            enum_value = Marketplace(marketplace)
        except ValueError:
            return None

        try:
            with session_scope() as session:
                row = session.scalar(
                    select(MarketplaceCredential).where(
                        MarketplaceCredential.marketplace == enum_value
                    )
                )
                if row is None or not row.values.get("access_token"):
                    return None
                expires_at_iso = row.values.get("token_expires_at_iso")
                return TokenSet(
                    access_token=row.values.get("access_token", ""),
                    refresh_token=row.values.get("refresh_token", ""),
                    expires_at=datetime.fromisoformat(expires_at_iso) if expires_at_iso else None,
                )
        except Exception as exc:  # noqa: BLE001 - banco fora do ar não pode derrubar o adapter
            logger.warning("não foi possível ler token de '%s': %s", marketplace, exc)
            return None

    def save(self, marketplace: str, tokens: TokenSet) -> None:
        from core.db.base import Marketplace
        from core.db.marketplace_credentials import MarketplaceCredential
        from core.db.session import session_scope

        enum_value = Marketplace(marketplace)
        with session_scope() as session:
            row = session.scalar(
                select(MarketplaceCredential).where(
                    MarketplaceCredential.marketplace == enum_value
                )
            )
            if row is None:
                row = MarketplaceCredential(marketplace=enum_value, enabled=True, values={})
                session.add(row)
                session.flush()
            merged = dict(row.values)
            merged["access_token"] = tokens.access_token
            merged["refresh_token"] = tokens.refresh_token
            merged["token_expires_at_iso"] = tokens.expires_at.isoformat() if tokens.expires_at else None
            row.values = merged

    def clear(self, marketplace: str) -> None:
        from core.db.base import Marketplace
        from core.db.marketplace_credentials import MarketplaceCredential
        from core.db.session import session_scope

        try:
            enum_value = Marketplace(marketplace)
        except ValueError:
            return
        with session_scope() as session:
            row = session.scalar(
                select(MarketplaceCredential).where(
                    MarketplaceCredential.marketplace == enum_value
                )
            )
            if row is None:
                return
            merged = dict(row.values)
            merged.pop("access_token", None)
            merged.pop("refresh_token", None)
            merged.pop("token_expires_at_iso", None)
            row.values = merged


__all__ = ["TokenSet", "TokenStore"]

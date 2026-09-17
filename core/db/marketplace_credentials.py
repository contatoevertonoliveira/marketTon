"""Credenciais de integração de marketplace, editáveis em tempo de execução.

O `.env`/`config/settings.py` continuam existindo como fonte de *defaults* de
processo, mas um operador precisa poder trocar uma credencial (ou religar um
marketplace) sem reiniciar a API — é para isso que esta tabela existe. A
permissão `connectors.manage` (`core/roles.py`) já previa isto; faltava o
modelo e o endpoint.

Segredos ficam em texto plano no Postgres, consistente com a postura de
segurança atual do projeto (nenhum outro segredo do domínio é criptografado
em repouso ainda). Fica como item de hardening futuro.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, Marketplace, TimestampMixin, enum_column


class MarketplaceCredential(Base, TimestampMixin):
    """Uma linha por marketplace. `values` guarda os campos daquele esquema de
    autenticação específico (client_id/secret, partner_id/key, access_key/
    secret_key, etc.) — o esquema exato vive em `backend/routers/marketplaces.py`.

    PK surrogate (`id`), não `marketplace`: convenção do projeto — toda PK
    precisa compilar para `INTEGER` puro no SQLite (ver
    `tests/test_schema.py::test_primary_keys_are_portable_to_sqlite`), o que uma
    coluna de enum/string não faz. `marketplace` fica com `UniqueConstraint`.
    """

    __tablename__ = "marketplace_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    marketplace: Mapped[Marketplace] = mapped_column(
        enum_column(Marketplace, "marketplace"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Preenchido quando o fluxo OAuth (Mercado Livre) inicia uma tentativa de
    # login, para validar o `state` no callback e não persistir o access_token
    # de um redirect forjado.
    oauth_state: Mapped[str | None] = mapped_column(String(64))
    # PKCE (RFC 7636): a Mercado Livre exige `code_verifier` na troca do código
    # por token quando o app tem PKCE habilitado — descoberto ao vivo via
    # `invalid_request: code_verifier is a required parameter`. Gerado junto
    # com `oauth_state` no início do fluxo, consumido no callback.
    oauth_code_verifier: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (UniqueConstraint("marketplace", name="uq_marketplace_credentials_marketplace"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MarketplaceCredential {self.marketplace.value} enabled={self.enabled}>"

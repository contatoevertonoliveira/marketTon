"""Modelos de autenticação e autorização.

Substitui duas implementações anteriores que não funcionavam juntas:

* Uma tabela `users` em `core/db.py` com `password TEXT NOT NULL` — **texto puro**,
  sem nenhuma dependência de hashing no projeto, e em código morto.
* Um `RoleManager` em `core/roles.py` que guardava papéis em JSONL relativo ao
  diretório de trabalho, importado **apenas pelo Streamlit**. As permissões viviam
  no frontend, o inverso do que o briefing seção 13 exige.

Agora papel e usuário vivem no banco, e a API é quem decide — o frontend só
apresenta.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base, TimestampMixin, enum_column


class Role(str, enum.Enum):
    """Papéis do sistema, do mais ao menos privilegiado.

    `BOT` existe para integrações automatizadas: um token de bot não deve ser
    confundido com um operador humano na trilha de auditoria.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    VIEWER = "viewer"
    BOT = "bot"


class User(Base, TimestampMixin):
    """Usuário da plataforma.

    `password_hash` guarda apenas o hash Argon2. Não existe campo de senha em
    texto: a versão anterior tinha `password TEXT NOT NULL`, o que significa que
    qualquer senha cadastrada ficaria legível no banco.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        enum_column(Role, "role"),
        nullable=False,
        default=Role.VIEWER,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Bloqueio de conta após tentativas falhas. Simples e suficiente: sem isto, a
    # única defesa contra força bruta seria a boa vontade do atacante.
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[str | None] = mapped_column(String(64))

    tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} ({self.role.value})>"


class RefreshToken(Base, TimestampMixin):
    """Refresh token emitido, guardado como hash.

    Guardar o hash e não o token significa que um vazamento do banco não permite
    usar os tokens — apenas revogá-los. `revoked_at` permite logout real, que um
    JWT puro não oferece.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Contexto de emissão, para auditoria e para permitir revogar por dispositivo.
    user_agent: Mapped[str | None] = mapped_column(String(255))
    client_ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="tokens")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        Index("ix_refresh_tokens_user_active", "user_id", "revoked_at"),
    )

    @property
    def is_usable(self) -> bool:
        from datetime import UTC

        if self.revoked_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires > datetime.now(UTC)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RefreshToken user={self.user_id} revoked={self.revoked_at is not None}>"


class AuditLog(Base, TimestampMixin):
    """Trilha de auditoria de ações sensíveis.

    Necessário porque, a partir do momento em que existe autenticação, "quem fez
    isso?" passa a ter resposta — e uma resposta precisa ser registrada. O briefing
    seção 7 já exige autor nas transições de portfólio; aqui é o mesmo princípio
    para as ações de conta e de escrita.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success")

    detail: Mapped[str | None] = mapped_column(Text)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index("ix_audit_log_action_created", "action", "created_at"),
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} by {self.actor} ({self.outcome})>"


__all__ = ["AuditLog", "RefreshToken", "Role", "User"]

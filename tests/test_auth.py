"""Testes de autenticação e autorização.

Cobrem três camadas distintas:

1. **Primitivas de segurança** (`core/services/security.py`) — hashing e JWT.
2. **Serviço de auth** (`core/services/auth.py`) — bloqueio por tentativas, rotação
   de refresh, revogação, auditoria.
3. **Permissões** (`core/roles.py`) — a matriz papel × permissão.

O que se está protegendo aqui, em termos concretos: antes deste trabalho a API tinha
49 rotas sem autenticação, `PUT /support/preferences/{user_id}` deixava qualquer um
sobrescrever preferências de outro usuário, e `core/db.py` declarava
`password TEXT NOT NULL` — senha em texto puro.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from core.db.auth import AuditLog, RefreshToken, Role, User
from core.roles import (
    PERMISSIONS,
    PermissionDenied,
    has_permission,
    permissions_for,
    require_permission,
    role_matrix,
)
from core.services import security
from core.services.auth import (
    MAX_FAILED_LOGINS,
    AccountInactive,
    AccountLocked,
    AuthError,
    InvalidCredentials,
    UserExists,
    WeakPassword,
    authenticate,
    create_user,
    ensure_admin,
    login,
    prune_expired_tokens,
    refresh_session,
    resolve_access_token,
    revoke_all_user_tokens,
    revoke_refresh_token,
    set_active,
    set_password,
)

GOOD_PASSWORD = "SenhaForte2026"


class TestPasswordHashing:
    def test_hash_is_not_the_password(self) -> None:
        """O ponto inteiro: a senha não pode estar legível no banco."""
        hashed = security.hash_password(GOOD_PASSWORD)
        assert GOOD_PASSWORD not in hashed
        assert hashed.startswith("$argon2")

    def test_verify_accepts_correct_and_rejects_wrong(self) -> None:
        hashed = security.hash_password(GOOD_PASSWORD)
        assert security.verify_password(GOOD_PASSWORD, hashed) is True
        assert security.verify_password("outra-senha", hashed) is False

    def test_same_password_produces_different_hashes(self) -> None:
        """Salt por hash: dois usuários com a mesma senha não compartilham hash."""
        assert security.hash_password(GOOD_PASSWORD) != security.hash_password(GOOD_PASSWORD)

    def test_malformed_hash_returns_false_instead_of_raising(self) -> None:
        """Um hash corrompido não pode virar 500 e revelar que o usuário existe."""
        assert security.verify_password(GOOD_PASSWORD, "nao-e-um-hash") is False
        assert security.verify_password("", "") is False
        assert security.verify_password(GOOD_PASSWORD, "") is False

    def test_empty_password_is_rejected(self) -> None:
        with pytest.raises(security.SecurityError):
            security.hash_password("")

    @pytest.mark.parametrize(
        "weak",
        ["curta1", "1234567890", "somenteletras", "password", "senha", "marketton"],
    )
    def test_weak_passwords_are_rejected(self, weak: str) -> None:
        assert security.validate_password_strength(weak), f"'{weak}' deveria ser recusada"

    def test_strong_password_passes(self) -> None:
        assert security.validate_password_strength(GOOD_PASSWORD) == []


class TestJwt:
    def test_roundtrip_carries_subject_and_role(self) -> None:
        token = security.create_access_token(subject="ana", role="operator")
        payload = security.decode_access_token(token)
        assert payload["sub"] == "ana"
        assert payload["role"] == "operator"
        assert payload["typ"] == "access"
        assert payload["jti"]

    def test_expired_token_is_distinguishable_from_invalid(self) -> None:
        """A distinção permite ao cliente tentar refresh em vez de relogar."""
        token = security.create_access_token(
            subject="ana", role="viewer", expires_delta=timedelta(seconds=-10)
        )
        with pytest.raises(security.TokenExpired):
            security.decode_access_token(token)

        with pytest.raises(security.TokenInvalid):
            security.decode_access_token("nao.e.um.token")

    def test_tampered_token_is_rejected(self) -> None:
        """Assinatura inválida: o payload não pode ser editado pelo cliente."""
        token = security.create_access_token(subject="ana", role="viewer")
        header, payload, signature = token.split(".")
        tampered = f"{header}.{payload}.{'a' * len(signature)}"
        with pytest.raises(security.TokenInvalid):
            security.decode_access_token(tampered)

    def test_token_signed_with_other_secret_is_rejected(self) -> None:
        from config.settings import Settings

        other = Settings(jwt_secret_key="outro-segredo")
        token = security.create_access_token(subject="ana", role="admin", settings=other)
        with pytest.raises(security.TokenInvalid):
            security.decode_access_token(token)

    def test_refresh_token_hash_is_deterministic(self) -> None:
        token, hashed = security.generate_refresh_token()
        assert security.hash_refresh_token(token) == hashed
        assert token not in hashed, "o hash não pode conter o token"

    def test_dev_secret_is_detectable(self) -> None:
        """Um segredo conhecido permite forjar admin, então precisa ser visível.

        O valor é passado explicitamente porque o ambiente de teste define
        `JWT_SECRET_KEY` próprio; o que se verifica aqui é o comportamento do
        detector, não a configuração do ambiente.
        """
        from config.settings import Settings

        assert Settings(jwt_secret_key="dev-only-insecure-change-me").is_using_dev_secret is True
        assert Settings(jwt_secret_key="um-segredo-proprio").is_using_dev_secret is False

    def test_production_readiness_lists_blockers(self) -> None:
        """A lista permite ao /health mostrar todos os problemas de uma vez."""
        from config.settings import Settings

        insecure = Settings(
            jwt_secret_key="dev-only-insecure-change-me",
            auth_enabled=False,
            database_url="sqlite+pysqlite:///:memory:",
            allow_sqlite=True,
        )
        problems = insecure.validate_production_readiness()
        assert any("AUTH_ENABLED" in problem for problem in problems)
        assert any("JWT_SECRET_KEY" in problem for problem in problems)
        assert any("SQLite" in problem for problem in problems)

        secure = Settings(
            jwt_secret_key="um-segredo-proprio",
            auth_enabled=True,
            database_url="postgresql+psycopg://u:p@h/db",
            ai_enabled=True,
            ai_api_key="chave",
        )
        assert secure.validate_production_readiness() == []


class TestUserManagement:
    def test_password_is_stored_hashed(self, session) -> None:
        """O defeito do legado era `password TEXT NOT NULL` em texto puro."""
        user = create_user(session, username="ana", password=GOOD_PASSWORD, role=Role.OPERATOR)
        assert user.password_hash != GOOD_PASSWORD
        assert user.password_hash.startswith("$argon2")

    def test_duplicate_username_is_rejected(self, session) -> None:
        create_user(session, username="ana", password=GOOD_PASSWORD)
        with pytest.raises(UserExists):
            create_user(session, username="ana", password=GOOD_PASSWORD)

    def test_weak_password_is_rejected_with_reasons(self, session) -> None:
        with pytest.raises(WeakPassword) as exc:
            create_user(session, username="ana", password="123456")
        assert exc.value.problems

    def test_set_password_revokes_existing_sessions(self, session) -> None:
        """Trocar senha após incidente não pode deixar sessão antiga válida."""
        user = create_user(session, username="ana", password=GOOD_PASSWORD)
        session.commit()
        result = login(session, username="ana", password=GOOD_PASSWORD)
        assert session.scalar(
            select(RefreshToken).where(RefreshToken.revoked_at.is_(None))
        ) is not None

        set_password(session, user, "OutraSenhaForte2026")
        session.commit()

        active = session.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        ).all()
        assert active == []
        del result

    def test_deactivating_user_revokes_tokens(self, session) -> None:
        user = create_user(session, username="ana", password=GOOD_PASSWORD)
        session.commit()
        login(session, username="ana", password=GOOD_PASSWORD)

        set_active(session, user, active=False)
        session.commit()
        assert revoke_all_user_tokens(session, user.id) == 0, "já foram revogados"


class TestLogin:
    @pytest.fixture
    def user(self, session):
        user = create_user(session, username="ana", password=GOOD_PASSWORD, role=Role.OPERATOR)
        session.commit()
        return user

    def test_successful_login_returns_token_pair(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"
        assert result.expires_in > 0

        payload = security.decode_access_token(result.access_token)
        assert payload["sub"] == "ana"
        assert payload["role"] == "operator"

    def test_refresh_token_is_stored_hashed(self, session, user) -> None:
        """Vazamento do banco permite revogar, não usar."""
        result = login(session, username="ana", password=GOOD_PASSWORD)
        stored = session.scalars(select(RefreshToken)).all()
        assert len(stored) == 1
        assert stored[0].token_hash != result.refresh_token
        assert stored[0].token_hash == security.hash_refresh_token(result.refresh_token)

    def test_wrong_password_and_unknown_user_are_indistinguishable(self, session, user) -> None:
        """Distinguir permitiria enumerar contas válidas."""
        with pytest.raises(InvalidCredentials) as wrong_password:
            login(session, username="ana", password="SenhaErrada2026")
        with pytest.raises(InvalidCredentials) as unknown_user:
            login(session, username="nao-existe", password=GOOD_PASSWORD)

        assert str(wrong_password.value) == str(unknown_user.value)

    def test_failed_attempts_are_audited(self, session, user) -> None:
        with pytest.raises(InvalidCredentials):
            login(session, username="ana", password="SenhaErrada2026")

        records = session.scalars(
            select(AuditLog).where(AuditLog.action == "auth.login")
        ).all()
        assert len(records) == 1
        assert records[0].outcome == "failure"
        assert records[0].actor == "ana"

    def test_account_locks_after_repeated_failures(self, session, user) -> None:
        """Sem bloqueio, a única defesa contra força bruta é a boa vontade do atacante."""
        for _ in range(MAX_FAILED_LOGINS - 1):
            with pytest.raises(InvalidCredentials):
                login(session, username="ana", password="SenhaErrada2026")

        # A tentativa que atinge o limite bloqueia a conta.
        with pytest.raises(InvalidCredentials):
            login(session, username="ana", password="SenhaErrada2026")

        with pytest.raises(AccountLocked):
            login(session, username="ana", password=GOOD_PASSWORD)

    def test_successful_login_resets_failure_counter(self, session, user) -> None:
        for _ in range(3):
            with pytest.raises(InvalidCredentials):
                login(session, username="ana", password="SenhaErrada2026")

        login(session, username="ana", password=GOOD_PASSWORD)
        session.refresh(user)
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert user.last_login_at is not None

    def test_inactive_account_cannot_login(self, session, user) -> None:
        set_active(session, user, active=False)
        session.commit()
        with pytest.raises(AccountInactive):
            login(session, username="ana", password=GOOD_PASSWORD)

    def test_audit_records_success_with_role(self, session, user) -> None:
        login(session, username="ana", password=GOOD_PASSWORD)
        record = session.scalars(
            select(AuditLog).where(AuditLog.outcome == "success")
        ).one()
        assert record.actor == "ana"
        assert record.actor_role == "operator"


class TestTokenResolution:
    @pytest.fixture
    def user(self, session):
        user = create_user(session, username="ana", password=GOOD_PASSWORD, role=Role.MANAGER)
        session.commit()
        return user

    def test_valid_token_resolves_the_user(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        resolved = resolve_access_token(session, result.access_token)
        assert resolved.id == user.id
        assert resolved.username == "ana"

    def test_role_change_takes_effect_immediately(self, session, user) -> None:
        """O token carrega o papel, mas a revalidação no banco prevalece.

        Se confiássemos só no JWT, um usuário rebaixado manteria o papel antigo até
        o token expirar — até 12 horas de acesso indevido.
        """
        result = login(session, username="ana", password=GOOD_PASSWORD)
        assert security.decode_access_token(result.access_token)["role"] == "manager"

        user.role = Role.VIEWER
        session.commit()

        resolved = resolve_access_token(session, result.access_token)
        assert resolved.role == Role.VIEWER

    def test_deactivated_user_loses_access_immediately(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        set_active(session, user, active=False)
        session.commit()

        with pytest.raises(AccountInactive):
            resolve_access_token(session, result.access_token)

    def test_deleted_user_token_is_rejected(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        session.delete(user)
        session.commit()

        with pytest.raises(AuthError):
            resolve_access_token(session, result.access_token)


class TestRefreshRotation:
    @pytest.fixture
    def user(self, session):
        user = create_user(session, username="ana", password=GOOD_PASSWORD, role=Role.OPERATOR)
        session.commit()
        return user

    def test_refresh_issues_a_new_pair(self, session, user) -> None:
        first = login(session, username="ana", password=GOOD_PASSWORD)
        second = refresh_session(session, refresh_token=first.refresh_token)

        assert second.access_token != first.access_token
        assert second.refresh_token != first.refresh_token

    def test_used_refresh_token_is_revoked(self, session, user) -> None:
        """Rotação limita a janela de exploração de um refresh vazado."""
        first = login(session, username="ana", password=GOOD_PASSWORD)
        refresh_session(session, refresh_token=first.refresh_token)

        with pytest.raises(AuthError, match="expirado ou revogado"):
            refresh_session(session, refresh_token=first.refresh_token)

    def test_unknown_refresh_token_is_rejected_and_audited(self, session, user) -> None:
        with pytest.raises(AuthError, match="inválido"):
            refresh_session(session, refresh_token="token-inventado")

        record = session.scalars(
            select(AuditLog).where(AuditLog.action == "auth.refresh")
        ).one()
        assert record.outcome == "failure"

    def test_expired_refresh_token_is_rejected(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        stored = session.scalars(select(RefreshToken)).one()
        stored.expires_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()

        with pytest.raises(AuthError, match="expirado ou revogado"):
            refresh_session(session, refresh_token=result.refresh_token)

    def test_logout_revokes_the_refresh_token(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        assert revoke_refresh_token(session, result.refresh_token) is True
        session.commit()

        with pytest.raises(AuthError):
            refresh_session(session, refresh_token=result.refresh_token)

    def test_revoking_twice_reports_nothing_revoked(self, session, user) -> None:
        result = login(session, username="ana", password=GOOD_PASSWORD)
        assert revoke_refresh_token(session, result.refresh_token) is True
        assert revoke_refresh_token(session, result.refresh_token) is False

    def test_logout_all_revokes_every_session(self, session, user) -> None:
        login(session, username="ana", password=GOOD_PASSWORD)
        login(session, username="ana", password=GOOD_PASSWORD)
        login(session, username="ana", password=GOOD_PASSWORD)

        assert revoke_all_user_tokens(session, user.id) == 3
        session.commit()
        remaining = session.scalars(
            select(RefreshToken).where(RefreshToken.revoked_at.is_(None))
        ).all()
        assert remaining == []

    def test_prune_removes_only_old_expired_tokens(self, session, user) -> None:
        login(session, username="ana", password=GOOD_PASSWORD)
        old = session.scalars(select(RefreshToken)).one()
        old.expires_at = datetime.now(UTC) - timedelta(days=60)
        session.commit()

        login(session, username="ana", password=GOOD_PASSWORD)
        removed = prune_expired_tokens(session, older_than_days=30)
        assert removed == 1


class TestBootstrap:
    def test_creates_admin_when_table_is_empty(self, session) -> None:
        admin = ensure_admin(session, username="root", password=GOOD_PASSWORD)
        assert admin is not None
        assert admin.role == Role.ADMIN

        record = session.scalars(
            select(AuditLog).where(AuditLog.action == "auth.bootstrap_admin")
        ).one()
        assert record.actor == "bootstrap"

    def test_does_nothing_when_a_user_exists(self, session) -> None:
        """O bootstrap não pode sobrescrever uma conta existente."""
        create_user(session, username="ana", password=GOOD_PASSWORD, role=Role.VIEWER)
        session.commit()

        assert ensure_admin(session, username="root", password=GOOD_PASSWORD) is None

    def test_bootstrap_password_policy_applies(self, session) -> None:
        with pytest.raises(WeakPassword):
            ensure_admin(session, username="root", password="123456")


class TestPermissionMatrix:
    def test_admin_has_every_permission(self) -> None:
        for permission in PERMISSIONS:
            assert has_permission(Role.ADMIN, permission.name), permission.name

    def test_viewer_cannot_write_anything(self) -> None:
        """Leitura é o teto do viewer; qualquer escrita precisa de papel acima."""
        for permission in PERMISSIONS:
            if permission.name.endswith((".manage", ".edit", ".compute", ".ingest", ".run", ".calibrate", ".approve", ".publish", ".affiliate")):
                assert not has_permission(Role.VIEWER, permission.name), permission.name

    def test_operator_can_work_but_not_administer(self) -> None:
        assert has_permission(Role.OPERATOR, "portfolio.manage")
        assert has_permission(Role.OPERATOR, "creatives.edit")
        assert not has_permission(Role.OPERATOR, "users.manage")
        assert not has_permission(Role.OPERATOR, "connectors.manage")
        assert not has_permission(Role.OPERATOR, "creatives.approve")

    def test_bot_has_no_human_permissions(self) -> None:
        assert permissions_for(Role.BOT) == []

    def test_unknown_permission_is_denied_by_default(self) -> None:
        """Negar por padrão: uma permissão que não existe não pode virar acesso."""
        assert has_permission(Role.ADMIN, "permissao.inexistente") is False

    def test_unknown_role_string_is_denied(self) -> None:
        assert has_permission("superuser", "portfolio.view") is False

    def test_accepts_role_value_as_string(self) -> None:
        assert has_permission("admin", "users.manage") is True

    def test_require_permission_raises_with_context(self) -> None:
        with pytest.raises(PermissionDenied, match="users.manage"):
            require_permission(Role.VIEWER, "users.manage")

    def test_require_permission_passes_for_allowed_role(self) -> None:
        require_permission(Role.ADMIN, "users.manage")  # não levanta

    def test_role_matrix_covers_every_role(self) -> None:
        matrix = role_matrix()
        assert set(matrix) == {role.value for role in Role}

    def test_every_permission_is_granted_to_at_least_one_role(self) -> None:
        """Permissão que nenhum papel tem seria um endpoint inacessível."""
        granted = {name for role in Role for name in permissions_for(role)}
        orphans = {permission.name for permission in PERMISSIONS} - granted
        assert not orphans, f"permissões sem nenhum papel: {sorted(orphans)}"

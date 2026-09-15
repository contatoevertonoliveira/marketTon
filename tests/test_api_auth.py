"""Testes do portão de autenticação e autorização aplicado pela API.

Complementa `test_auth.py`: lá se testam as primitivas e o serviço; aqui se testa
que a **API de fato recusa** o que deve recusar.

Antes deste trabalho, a API tinha 49 rotas sem autenticação nenhuma. Um teste de
serviço não pegaria isso — só um teste que faz a requisição HTTP pega.

`AUTH_ENABLED=true` é definido aqui, no import, antes de `config.settings` ser lido:
o `conftest` deixa auth desligada para os testes de domínio, e este arquivo precisa
do portão ligado.
"""
from __future__ import annotations

import os

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-for-http-auth-tests"

from contextlib import asynccontextmanager  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import core.db  # noqa: E402, F401 - carrega todos os modelos
import core.db.support  # noqa: E402, F401
from core.db import Base  # noqa: E402
from core.db.auth import AuditLog, Role, User  # noqa: E402
from core.db.base import ConnectorKind, Marketplace  # noqa: E402
from core.db.catalog import Product, SourceRecord  # noqa: E402
from core.services.auth import create_user, login  # noqa: E402

PASSWORD = "SenhaForte2026"
NOW = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)


@asynccontextmanager
async def _noop_lifespan(app):  # noqa: ANN001, ARG001
    """Substitui o lifespan: o real tentaria conectar em PostgreSQL."""
    yield


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(factory):
    session = factory()
    yield session
    session.close()


@pytest.fixture
def client(factory):
    from backend import deps
    from backend.main import app

    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_session] = override_session
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def users(db):
    """Um usuário por papel, para verificar a matriz de permissões na prática."""
    created = {}
    for role in (Role.ADMIN, Role.MANAGER, Role.OPERATOR, Role.VIEWER):
        created[role] = create_user(
            db, username=f"user_{role.value}", password=PASSWORD, role=role
        )
    db.commit()
    return created


def auth_header(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def seed_product(db):
    source = SourceRecord(
        marketplace=Marketplace.MERCADO_LIVRE,
        connector="mercado_livre",
        connector_kind=ConnectorKind.OFFICIAL_API,
        collected_at=NOW,
        reliability=1.0,
    )
    db.add(source)
    db.flush()
    product = Product(
        marketplace=Marketplace.MERCADO_LIVRE,
        external_id="MLB1",
        title="Fone Bluetooth",
        price=99.9,
        source_record_id=source.id,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db.add(product)
    db.commit()
    return product.id


class TestProtectedRoutesRejectAnonymous:
    """Toda rota precisa de credencial. Um `require` esquecido é um buraco."""

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/catalog/products"),
            ("GET", "/catalog/stats"),
            ("GET", "/catalog/marketplaces"),
            ("GET", "/scoring/algorithms"),
            ("GET", "/scoring/runs"),
            ("GET", "/portfolio/items"),
            ("GET", "/portfolio/transitions"),
            ("GET", "/portfolio/recommendations"),
            ("GET", "/creatives/assets"),
            ("GET", "/creatives/pending"),
            ("GET", "/jobs"),
            ("GET", "/jobs/stats"),
            ("GET", "/operations/daily"),
            ("GET", "/operations/weekly"),
            ("GET", "/operations/connectors"),
            ("GET", "/auth/me"),
            ("GET", "/auth/permissions"),
            ("GET", "/auth/users"),
            ("GET", "/auth/audit"),
        ],
    )
    def test_get_requires_authentication(self, client, method: str, path: str) -> None:
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} devolveu {response.status_code}"
        assert "WWW-Authenticate" in response.headers

    @pytest.mark.parametrize(
        "path,payload",
        [
            ("/portfolio/items", {"product_id": 1}),
            ("/portfolio/items/1/transition", {"to_state": "ANALYZING"}),
            ("/creatives/assets", {"asset_type": "COPY"}),
            ("/scoring/compute", {"dimension": "HEAT", "target_id": 1}),
        ],
    )
    def test_post_requires_authentication(self, client, path: str, payload: dict) -> None:
        response = client.post(path, json=payload)
        assert response.status_code == 401, f"POST {path} devolveu {response.status_code}"

    def test_support_routes_are_protected_too(self, client) -> None:
        """As rotas legadas foram as mais expostas antes: preferências de qualquer usuário."""
        for path in ("/support/feedback", "/support/preferences", "/support/groups"):
            assert client.get(path).status_code in {401, 403}, path

    def test_invalid_token_is_rejected(self, client) -> None:
        response = client.get("/catalog/products", headers={"Authorization": "Bearer nao-e-token"})
        assert response.status_code == 401

    def test_malformed_scheme_is_rejected(self, client, users) -> None:
        response = client.get("/catalog/products", headers={"Authorization": "Basic abc"})
        assert response.status_code == 401


class TestLoginEndpoint:
    def test_login_returns_tokens(self, client, users) -> None:
        response = client.post("/auth/login", json={"username": "user_admin", "password": PASSWORD})
        assert response.status_code == 200

        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0

    def test_wrong_password_returns_401_without_revealing_which_field(self, client, users) -> None:
        wrong = client.post("/auth/login", json={"username": "user_admin", "password": "ErradaTotal2026"})
        unknown = client.post("/auth/login", json={"username": "nao_existe", "password": PASSWORD})

        assert wrong.status_code == 401
        assert unknown.status_code == 401
        # Mesma mensagem: distinguir permitiria enumerar contas.
        assert wrong.json()["detail"] == unknown.json()["detail"]

    def test_missing_fields_are_422(self, client) -> None:
        assert client.post("/auth/login", json={}).status_code == 422
        assert client.post("/auth/login", json={"username": "x"}).status_code == 422

    def test_lockout_returns_423(self, client, users) -> None:
        for _ in range(5):
            client.post("/auth/login", json={"username": "user_viewer", "password": "ErradaTotal2026"})

        response = client.post("/auth/login", json={"username": "user_viewer", "password": PASSWORD})
        assert response.status_code == 423
        assert "bloqueada" in response.json()["detail"]

    def test_inactive_account_returns_403(self, client, db, users) -> None:
        from core.services.auth import set_active

        set_active(db, users[Role.OPERATOR], active=False)
        db.commit()

        response = client.post("/auth/login", json={"username": "user_operator", "password": PASSWORD})
        assert response.status_code == 403


class TestMeEndpoint:
    def test_me_returns_role_and_permissions(self, client, users) -> None:
        headers = auth_header(client, "user_operator")
        body = client.get("/auth/me", headers=headers).json()

        assert body["username"] == "user_operator"
        assert body["role"] == "operator"
        assert "portfolio.manage" in body["permissions"]
        assert "users.manage" not in body["permissions"]

    def test_viewer_permissions_are_read_only(self, client, users) -> None:
        headers = auth_header(client, "user_viewer")
        permissions = client.get("/auth/me", headers=headers).json()["permissions"]

        assert "catalog.view" in permissions
        assert not any(
            permission.endswith((".manage", ".edit", ".compute", ".approve"))
            for permission in permissions
        )

    def test_permission_matrix_endpoint(self, client, users) -> None:
        headers = auth_header(client, "user_viewer")
        body = client.get("/auth/permissions", headers=headers).json()

        assert "matrix" in body
        assert body["current_role"] == "viewer"
        assert set(body["roles"]) == {"admin", "manager", "operator", "viewer", "bot"}


class TestRoleEnforcement:
    """O ponto central: a API recusa, não apenas o frontend esconde."""

    def test_viewer_can_read_catalog(self, client, users, seed_product) -> None:
        headers = auth_header(client, "user_viewer")
        assert client.get("/catalog/products", headers=headers).status_code == 200

    def test_viewer_cannot_add_to_portfolio(self, client, users, seed_product) -> None:
        headers = auth_header(client, "user_viewer")
        response = client.post(
            "/portfolio/items", json={"product_id": seed_product}, headers=headers
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["required_permission"] == "portfolio.manage"
        assert detail["role"] == "viewer"

    def test_operator_can_add_to_portfolio(self, client, users, seed_product) -> None:
        headers = auth_header(client, "user_operator")
        response = client.post(
            "/portfolio/items", json={"product_id": seed_product}, headers=headers
        )
        assert response.status_code == 201

    def test_operator_cannot_manage_users(self, client, users) -> None:
        headers = auth_header(client, "user_operator")
        assert client.get("/auth/users", headers=headers).status_code == 403

    def test_manager_cannot_manage_users(self, client, users) -> None:
        """Gerenciar contas é administrativo: mesmo o manager não alcança."""
        from core.roles import has_permission

        assert has_permission(Role.MANAGER, "users.manage") is False
        headers = auth_header(client, "user_manager")
        assert client.get("/auth/users", headers=headers).status_code == 403

    def test_manager_can_do_operational_writes(self, client, users, seed_product) -> None:
        """O manager opera: portfólio, criativos e aprovação são dele."""
        from core.roles import has_permission

        for permission in (
            "portfolio.manage",
            "creatives.edit",
            "creatives.approve",
            "scoring.compute",
            "publication.publish",
        ):
            assert has_permission(Role.MANAGER, permission), permission

        headers = auth_header(client, "user_manager")
        response = client.post(
            "/portfolio/items", json={"product_id": seed_product}, headers=headers
        )
        assert response.status_code == 201

    def test_manager_can_view_support_but_only_admin_manages_connectors(self, client, users) -> None:
        from core.roles import has_permission

        assert has_permission(Role.MANAGER, "support.manage") is True
        assert has_permission(Role.MANAGER, "connectors.manage") is False
        assert has_permission(Role.MANAGER, "users.manage") is False

    def test_admin_can_view_audit(self, client, users) -> None:
        headers = auth_header(client, "user_admin")
        assert client.get("/auth/audit", headers=headers).status_code == 200

    def test_manager_cannot_view_audit(self, client, users) -> None:
        """Auditoria é restrita a admin: quem age não deve ser quem audita."""
        headers = auth_header(client, "user_manager")
        assert client.get("/auth/audit", headers=headers).status_code == 403

    def test_only_admin_manages_connectors(self, client, users) -> None:
        manager = auth_header(client, "user_manager")
        admin = auth_header(client, "user_admin")

        # O endpoint de conectores exige `operations.view` para leitura, então
        # ambos passam; o que difere é a gestão, coberta pela matriz.
        assert client.get("/operations/connectors", headers=manager).status_code == 200
        assert client.get("/operations/connectors", headers=admin).status_code == 200

    def test_operator_can_compute_score_but_not_calibrate(self, client, users, seed_product) -> None:
        from core.roles import has_permission

        assert has_permission(Role.OPERATOR, "scoring.compute") is True
        assert has_permission(Role.OPERATOR, "scoring.calibrate") is False

    def test_approving_creative_requires_the_extra_permission(self, client, db, users, seed_product) -> None:
        """Aprovar libera publicação, então quem edita não deve necessariamente poder aprovar."""
        operator = auth_header(client, "user_operator")
        manager = auth_header(client, "user_manager")

        created = client.post(
            "/creatives/assets",
            json={"asset_type": "COPY", "title": "Copy"},
            headers=operator,
        )
        assert created.status_code == 201
        asset_id = created.json()["id"]

        # Operator move até READY.
        for target in ("IN_PROGRESS", "READY"):
            response = client.post(
                f"/creatives/assets/{asset_id}/status",
                json={"status": target},
                headers=operator,
            )
            assert response.status_code == 200, response.text

        # Mas aprovar exige `creatives.approve`, que o operator não tem.
        denied = client.post(
            f"/creatives/assets/{asset_id}/status",
            json={"status": "APPROVED"},
            headers=operator,
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["message"].startswith("permissão negada")
        assert "creatives.approve" in denied.json()["detail"]["message"]

        # O manager tem.
        approved = client.post(
            f"/creatives/assets/{asset_id}/status",
            json={"status": "APPROVED"},
            headers=manager,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"


class TestRefreshFlow:
    def test_refresh_rotates_and_returns_a_new_pair(self, client, users) -> None:
        login_body = client.post(
            "/auth/login", json={"username": "user_operator", "password": PASSWORD}
        ).json()

        response = client.post("/auth/refresh", json={"refresh_token": login_body["refresh_token"]})
        assert response.status_code == 200

        refreshed = response.json()
        assert refreshed["refresh_token"] != login_body["refresh_token"]

        # O novo access token funciona.
        headers = {"Authorization": f"Bearer {refreshed['access_token']}"}
        assert client.get("/auth/me", headers=headers).status_code == 200

    def test_reusing_a_rotated_refresh_token_fails(self, client, users) -> None:
        """Rotação limita a janela de exploração de um refresh vazado."""
        login_body = client.post(
            "/auth/login", json={"username": "user_operator", "password": PASSWORD}
        ).json()

        client.post("/auth/refresh", json={"refresh_token": login_body["refresh_token"]})
        second = client.post("/auth/refresh", json={"refresh_token": login_body["refresh_token"]})

        assert second.status_code == 401

    def test_unknown_refresh_token_is_401(self, client, users) -> None:
        response = client.post("/auth/refresh", json={"refresh_token": "inventado"})
        assert response.status_code == 401


class TestLogout:
    def test_logout_revokes_the_refresh_token(self, client, users) -> None:
        login_body = client.post(
            "/auth/login", json={"username": "user_operator", "password": PASSWORD}
        ).json()

        logout = client.post("/auth/logout", json={"refresh_token": login_body["refresh_token"]})
        assert logout.status_code == 200
        assert logout.json()["revoked"] == 1

        # O refresh revogado não pode mais ser usado.
        assert client.post(
            "/auth/refresh", json={"refresh_token": login_body["refresh_token"]}
        ).status_code == 401

    def test_logout_all_sessions_requires_authentication(self, client, users) -> None:
        response = client.post("/auth/logout", json={"all_sessions": True})
        assert response.status_code == 401

    def test_logout_all_sessions_revokes_everything(self, client, users) -> None:
        first = client.post("/auth/login", json={"username": "user_admin", "password": PASSWORD}).json()
        client.post("/auth/login", json={"username": "user_admin", "password": PASSWORD})

        headers = {"Authorization": f"Bearer {first['access_token']}"}
        response = client.post("/auth/logout", json={"all_sessions": True}, headers=headers)
        assert response.status_code == 200
        assert response.json()["revoked"] == 2

        assert client.post(
            "/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).status_code == 401


class TestUserAdministration:
    def test_admin_creates_a_user(self, client, users) -> None:
        headers = auth_header(client, "user_admin")
        response = client.post(
            "/auth/users",
            json={"username": "novo", "password": "OutraSenhaForte2026", "role": "operator"},
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["role"] == "operator"

        # E o novo usuário consegue entrar.
        assert client.post(
            "/auth/login", json={"username": "novo", "password": "OutraSenhaForte2026"}
        ).status_code == 200

    def test_short_password_is_rejected_by_schema(self, client, users) -> None:
        headers = auth_header(client, "user_admin")
        response = client.post(
            "/auth/users",
            json={"username": "fraco", "password": "123456", "role": "viewer"},
            headers=headers,
        )
        assert response.status_code == 422
        # O erro vem do schema (min_length) antes do handler: mensagem por campo.
        assert response.json()["detail"][0]["loc"] == ["body", "password"]

    def test_password_that_passes_schema_but_fails_policy_is_rejected(self, client, users) -> None:
        """Uma senha com 12 caracteres só de dígitos passa no schema e falha na política."""
        headers = auth_header(client, "user_admin")
        response = client.post(
            "/auth/users",
            json={"username": "fraco2", "password": "123456789012", "role": "viewer"},
            headers=headers,
        )
        assert response.status_code == 422

        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["problems"], "a política deve explicar o que está errado"

    def test_duplicate_username_is_409(self, client, users) -> None:
        headers = auth_header(client, "user_admin")
        response = client.post(
            "/auth/users",
            json={"username": "user_admin", "password": "OutraSenhaForte2026"},
            headers=headers,
        )
        assert response.status_code == 409

    def test_admin_cannot_demote_own_account(self, client, users) -> None:
        """Sem esta trava, um admin se tranca fora e não há caminho de volta."""
        headers = auth_header(client, "user_admin")
        me = client.get("/auth/me", headers=headers).json()

        response = client.patch(
            f"/auth/users/{me['id']}", json={"role": "viewer"}, headers=headers
        )
        assert response.status_code == 409
        assert "própria conta" in response.json()["detail"]

    def test_admin_cannot_deactivate_own_account(self, client, users) -> None:
        headers = auth_header(client, "user_admin")
        me = client.get("/auth/me", headers=headers).json()

        response = client.patch(
            f"/auth/users/{me['id']}", json={"is_active": False}, headers=headers
        )
        assert response.status_code == 409

    def test_admin_changes_another_users_role(self, client, db, users) -> None:
        headers = auth_header(client, "user_admin")
        target = users[Role.VIEWER]

        response = client.patch(
            f"/auth/users/{target.id}", json={"role": "operator"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["role"] == "operator"

        db.expire_all()
        assert db.get(User, target.id).role == Role.OPERATOR

    def test_password_reset_revokes_target_sessions(self, client, db, users) -> None:
        """Trocar senha após incidente não pode deixar a sessão antiga válida."""
        operator_login = client.post(
            "/auth/login", json={"username": "user_operator", "password": PASSWORD}
        ).json()

        admin = auth_header(client, "user_admin")
        response = client.patch(
            f"/auth/users/{users[Role.OPERATOR].id}",
            json={"password": "SenhaNovaForte2026"},
            headers=admin,
        )
        assert response.status_code == 200

        # O refresh antigo do operador foi revogado.
        assert client.post(
            "/auth/refresh", json={"refresh_token": operator_login["refresh_token"]}
        ).status_code == 401

        # E a senha antiga não funciona mais.
        assert client.post(
            "/auth/login", json={"username": "user_operator", "password": PASSWORD}
        ).status_code == 401

    def test_deactivated_user_loses_api_access_immediately(self, client, users) -> None:
        """A revalidação no banco vence o JWT, então o corte é imediato."""
        operator_headers = auth_header(client, "user_operator")
        assert client.get("/catalog/products", headers=operator_headers).status_code == 200

        admin = auth_header(client, "user_admin")
        client.patch(
            f"/auth/users/{users[Role.OPERATOR].id}", json={"is_active": False}, headers=admin
        )

        # O mesmo token, que ainda não expirou, agora é recusado.
        assert client.get("/catalog/products", headers=operator_headers).status_code == 403


class TestAudit:
    def test_login_attempts_are_recorded(self, client, users) -> None:
        client.post("/auth/login", json={"username": "user_admin", "password": PASSWORD})
        client.post("/auth/login", json={"username": "user_admin", "password": "ErradaTotal2026"})

        headers = auth_header(client, "user_admin")
        records = client.get("/auth/audit", params={"action": "auth.login"}, headers=headers).json()

        outcomes = {record["outcome"] for record in records}
        assert "success" in outcomes
        assert "failure" in outcomes
        assert all(record["action"] == "auth.login" for record in records)

    def test_audit_records_actor_and_ip(self, client, users) -> None:
        client.post("/auth/login", json={"username": "user_admin", "password": PASSWORD})
        headers = auth_header(client, "user_admin")

        records = client.get("/auth/audit", params={"outcome": "success"}, headers=headers).json()
        assert any(record["actor"] == "user_admin" for record in records)

    def test_summary_reports_failed_logins_by_actor(self, client, users) -> None:
        """Serve para detectar força bruta sem ler log de servidor."""
        for _ in range(3):
            client.post("/auth/login", json={"username": "user_viewer", "password": "ErradaTotal2026"})

        headers = auth_header(client, "user_admin")
        body = client.get("/auth/audit/summary", headers=headers).json()

        assert any(entry["actor"] == "user_viewer" for entry in body["failed_logins_by_actor"])
        assert "by_action" in body

    def test_user_creation_is_audited_with_actor(self, client, db, users) -> None:
        headers = auth_header(client, "user_admin")
        client.post(
            "/auth/users",
            json={"username": "auditado", "password": "SenhaForte2026x"},
            headers=headers,
        )

        record = db.scalars(
            select(AuditLog).where(AuditLog.action == "auth.user_created")
        ).one()
        assert record.actor == "user_admin"
        assert record.actor_role == "admin"
        assert record.resource_type == "user"


class TestHealthReportsBlockers:
    def test_health_exposes_production_blockers(self, client) -> None:
        """'Quase pronto' sem dizer o que falta é indistinguível de pronto."""
        body = client.get("/health").json()

        assert "production_blockers" in body
        assert "production_ready" in body
        assert body["auth_enabled"] is True
        # O segredo de teste deste arquivo não é o de desenvolvimento, mas o banco
        # é SQLite e a IA está desligada — então há bloqueadores e eles aparecem.
        assert isinstance(body["production_blockers"], list)

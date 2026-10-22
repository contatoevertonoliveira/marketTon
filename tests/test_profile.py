"""Perfil do próprio usuário: dados de contato, nome de usuário e senha.

Roda com a autenticação **ligada** (como `test_api_auth.py`): com ela desligada o
`Principal` é sintético e não há usuário real para editar.
"""
from __future__ import annotations

import os

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-for-http-auth-tests"

from contextlib import asynccontextmanager  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import core.db  # noqa: E402, F401 - carrega todos os modelos
import core.db.support  # noqa: E402, F401
from core.db import Base  # noqa: E402
from core.db.auth import Role  # noqa: E402
from core.services.auth import create_user  # noqa: E402

PASSWORD = "SenhaDeTeste2026"
NEW_PASSWORD = "NovaSenhaForte2026"


@asynccontextmanager
async def _noop_lifespan(app):  # noqa: ANN001, ARG001
    yield


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(factory):
    """TestClient logado de verdade como o usuário `dono`."""
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
        setup = factory()
        create_user(setup, username="dono", password=PASSWORD, role=Role.ADMIN)
        setup.commit()
        setup.close()
        response = test_client.post("/auth/login", json={"username": "dono", "password": PASSWORD})
        assert response.status_code == 200, response.text
        test_client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield test_client
    app.dependency_overrides.clear()


def _login(client, username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_me_exposes_profile_fields(client):
    body = client.get("/auth/me").json()
    assert body["username"] == "dono"
    assert body["full_name"] is None and body["phone"] is None and body["company"] is None
    assert body["relogin_required"] is False


def test_update_contact_data_and_clear_a_field(client):
    r = client.patch(
        "/auth/me",
        json={"full_name": " Everton Felix ", "email": "e@example.com", "phone": "11 99999-0000", "company": "Felix"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Everton Felix"  # espaços aparados
    assert body["email"] == "e@example.com" and body["company"] == "Felix"
    assert body["relogin_required"] is False

    cleared = client.patch("/auth/me", json={"phone": ""}).json()
    assert cleared["phone"] is None and cleared["full_name"] == "Everton Felix"  # ausente = não mexe


def test_invalid_email_is_rejected(client):
    r = client.patch("/auth/me", json={"email": "sem-arroba"})
    assert r.status_code == 422 and "e-mail" in r.json()["detail"]


def test_username_change_requires_relogin_and_old_session_stops_working(client):
    r = client.patch("/auth/me", json={"username": "novo.dono"})
    assert r.status_code == 200 and r.json()["relogin_required"] is True
    # O nome de usuário é o `sub` do token: a sessão antiga deixa de valer.
    assert client.get("/auth/me").status_code == 401
    assert _login(client, "novo.dono", PASSWORD).status_code == 200


def test_username_must_be_unique_and_well_formed(client, factory):
    session = factory()
    create_user(session, username="outra_pessoa", password="OutraSenha2026", role=Role.VIEWER)
    session.commit()
    session.close()

    assert client.patch("/auth/me", json={"username": "outra_pessoa"}).status_code == 409
    assert client.patch("/auth/me", json={"username": "a b"}).status_code == 422
    assert client.patch("/auth/me", json={"username": "ab"}).status_code == 422


def test_email_cannot_duplicate_another_account(client, factory):
    session = factory()
    create_user(session, username="outra_pessoa", password="OutraSenha2026", role=Role.VIEWER, email="dup@example.com")
    session.commit()
    session.close()
    assert client.patch("/auth/me", json={"email": "dup@example.com"}).status_code == 409


def test_password_change_requires_current_and_revokes_sessions(client):
    wrong = client.post("/auth/me/password", json={"current_password": "errada1234", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 403

    ok = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200 and ok.json()["relogin_required"] is True

    assert _login(client, "dono", PASSWORD).status_code == 401
    assert _login(client, "dono", NEW_PASSWORD).status_code == 200


def test_weak_or_unchanged_new_password_is_refused(client):
    weak = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": "1234567890"})
    assert weak.status_code == 422
    same = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422 and "diferente" in same.json()["detail"]
    assert _login(client, "dono", PASSWORD).status_code == 200  # nada mudou


def test_wrong_current_password_counts_toward_lockout(client):
    for _ in range(5):
        assert client.post(
            "/auth/me/password", json={"current_password": "errada1234", "new_password": NEW_PASSWORD}
        ).status_code == 403
    locked = client.post("/auth/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert locked.status_code == 423  # nem a senha certa passa enquanto bloqueado


def test_changes_are_written_to_the_audit_trail(client):
    client.patch("/auth/me", json={"full_name": "X"})
    client.post("/auth/me/password", json={"current_password": "errada1234", "new_password": NEW_PASSWORD})
    actions = {(a["action"], a["outcome"]) for a in client.get("/auth/audit").json()}
    assert ("auth.profile_updated", "success") in actions
    assert ("auth.password_changed", "failure") in actions

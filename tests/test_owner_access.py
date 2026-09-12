"""Hosted owner boundary, including sessions and invite bypasses."""

import pytest

from sabermetrics import db
from sabermetrics.ui.app import create_app
from scripts.setup_db import setup_database


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "owner.db"
    setup_database(path)
    return path


@pytest.fixture
def app(db_path):
    app = create_app(db_path)
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def owner_mode(app):
    app.config["OWNER_EMAIL"] = "owner@example.com"


def make_user(db_path, email="owner@example.com", role="admin", status="active"):
    return db.UsersRepo(db_path).create(
        email=email,
        display_name="Test",
        role=role,
        status=status,
        password_hash=db.hash_password("test-password-123"),
    )


def login(client, email="owner@example.com"):
    return client.post("/login", data={"email": email, "password": "test-password-123"})


def test_owner_can_sign_in(client, db_path):
    make_user(db_path)
    assert login(client).status_code == 302
    assert client.get("/").status_code == 200


@pytest.mark.parametrize(
    "email,role,status",
    [
        ("other@example.com", "admin", "active"),
        ("member@example.com", "user", "active"),
        ("owner@example.com", "user", "active"),
        ("owner@example.com", "admin", "disabled"),
    ],
)
def test_other_accounts_cannot_sign_in(client, db_path, email, role, status):
    make_user(db_path, email, role, status)
    assert login(client, email).status_code == 200
    assert client.get("/").status_code == 302


@pytest.mark.parametrize("change", ["disable", "demote", "allowlist"])
def test_existing_session_is_revoked(client, app, db_path, change):
    uid = make_user(db_path)
    login(client)
    if change == "disable":
        db.UsersRepo(db_path).set_status(uid, "disabled")
    elif change == "demote":
        with db.connect(db_path) as conn:
            conn.execute("UPDATE users SET role='user' WHERE id=?", (uid,))
            conn.commit()
    else:
        app.config["OWNER_EMAIL"] = "replacement@example.com"
    assert client.get("/").status_code == 302


def test_invite_cannot_enable_another_login(client, db_path):
    uid = make_user(db_path, "invited@example.com", status="invited")
    token = db.InviteRepo(db_path).create(uid)
    assert client.get("/invite/" + token).status_code == 403
    assert client.post("/invite/" + token, data={}).status_code == 403
    assert db.UsersRepo(db_path).get(uid)["status"] == "invited"


def test_owner_cannot_create_or_enable_other_accounts(client, db_path):
    uid = make_user(db_path)
    login(client)
    for path in [
        "/admin/users/create",
        f"/admin/users/{uid}/status",
        f"/admin/users/{uid}/reinvite",
        f"/admin/users/{uid}/quota",
    ]:
        assert client.post(path, data={}).status_code == 403


def test_hosted_entrypoint_fails_closed(monkeypatch):
    from sabermetrics.server import main

    monkeypatch.delenv("SABER_OWNER_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="OWNER_EMAIL"):
        main()
    monkeypatch.setenv("SABER_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("SABER_SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        main()

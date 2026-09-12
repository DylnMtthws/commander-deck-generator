"""Offline installed-package smoke; run inside the image with a disposable /data."""

import os
import runpy
from pathlib import Path

from sabermetrics import db
from sabermetrics.ui.app import create_app

path = Path("/data/smoke.db")
runpy.run_path("/app/scripts/setup_db.py")["setup_database"](path)
users = db.UsersRepo(path)
owner = users.create(
    email="owner@example.com",
    display_name="Owner",
    role="admin",
    status="active",
    password_hash=db.hash_password("offline-password"),
)
users.create(
    email="other@example.com",
    display_name="Other",
    role="admin",
    status="active",
    password_hash=db.hash_password("offline-password"),
)
os.environ["SABER_OWNER_EMAIL"] = "owner@example.com"
app = create_app(path)
app.config.update(
    TESTING=True,
    SESSION_COOKIE_SECURE=False,
    WTF_CSRF_ENABLED=False,
    RATELIMIT_ENABLED=False,
)
client = app.test_client()
assert client.get("/healthz").json["status"] == "ok"
assert b"Sabermetrics" in client.get("/login").data
assert (
    client.post(
        "/login", data={"email": "other@example.com", "password": "offline-password"}
    ).status_code
    == 200
)
assert client.get("/").status_code == 302
assert (
    client.post(
        "/login", data={"email": "owner@example.com", "password": "offline-password"}
    ).status_code
    == 302
)
assert client.get("/").status_code == 200
assert client.get("/explore").status_code == 200
assert client.get("/decks").status_code == 200
assert client.post("/admin/users/create").status_code == 403
users.set_status(owner, "disabled")
assert client.get("/").status_code == 302
print(
    "Installed templates, routes, owner login, account exclusion, and session revocation passed"
)

"""Offline installed-package smoke; run inside the image with a disposable /data."""

from __future__ import annotations

import os
import runpy
from pathlib import Path

from sabermetrics import db
from sabermetrics.runtime import (
    apply_schema_migrations,
    assert_installed_scoring_values,
    assert_readiness,
    insert_synthetic_cards_at,
    prepare_public_corpus,
    query_empty_corpus_safe_at,
    setup_database,
)
from sabermetrics.ui.app import create_app


def _setup_database(path: Path) -> None:
    """Create schema using the image script when present, else the package API."""
    script = Path("/app/scripts/setup_db.py")
    if script.is_file():
        runpy.run_path(str(script))["setup_database"](path)
        return
    setup_database(path)


def run_scoring_and_schema_smoke(db_path: Path) -> None:
    """Real scoring loaders, empty-corpus SQL, synthetic prepare, re-migration."""
    assert_installed_scoring_values()
    print("Installed scoring loaders (real expected values) passed")

    query_empty_corpus_safe_at(db_path)
    print("Empty-corpus SQL paths passed")

    inserted = insert_synthetic_cards_at(db_path)
    stats = prepare_public_corpus(db_path)
    assert inserted == 4
    assert stats["role_tags"]["tagged_cards"] >= 1
    assert stats["ramp_candidates"]["rows"] >= 1

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        ramp = conn.execute(
            "SELECT produced_colors FROM ramp_candidates WHERE card_id = 'syn-ramp-rock'"
        ).fetchone()
        assert ramp is not None
        tags = conn.execute(
            "SELECT role_tags FROM cards WHERE id = 'syn-ramp-rock'"
        ).fetchone()
        assert tags is not None and tags[0]
        users_before = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()

    version = apply_schema_migrations(db_path)
    again = prepare_public_corpus(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        users_after = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        still = conn.execute(
            "SELECT name FROM cards WHERE id = 'syn-ramp-rock'"
        ).fetchone()
    finally:
        conn.close()
    assert users_after == users_before
    assert still[0] == "Synthetic Mana Rock"
    assert again["role_tags"]["tagged_cards"] == 0 or again["ramp_candidates"].get(
        "skipped"
    )
    assert version
    print("Synthetic card preparation and repeated migration passed")


def main() -> None:
    path = Path("/data/smoke.db")
    _setup_database(path)
    assert_readiness(path)
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

    # The installed package must carry prompts, not just importable Python modules.
    from sabermetrics.config import settings
    from sabermetrics.reasoning.prompts import load_prompt

    assert "schema" in load_prompt("profile_synthesis").lower()
    assert settings.llm.profile_model == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    assert settings.llm.fit_model == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    print("Installed generation prompts and DeepSeek defaults passed")

    run_scoring_and_schema_smoke(path)
    print("Installed runtime scoring, empty-corpus SQL, and synthetic preparation passed")


if __name__ == "__main__":
    main()

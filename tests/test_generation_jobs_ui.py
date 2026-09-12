"""UI tests for async generation jobs, auth/CSRF, warnings, and fake-progress removal."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sabermetrics import db
from sabermetrics.generation_jobs import GENERIC_FAILURE
from sabermetrics.reasoning.client import _cost_context
from sabermetrics.ui.app import create_app
from scripts.setup_db import setup_database

XHR = {"X-Requested-With": "XMLHttpRequest"}
PROFILE_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sabermetrics"
    / "ui"
    / "templates"
    / "profile_view.html"
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "jobs_ui.db"
    setup_database(path)
    return path


@pytest.fixture
def app(db_path):
    application = create_app(db_path)
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
        GENERATION_JOBS_ENABLE_WORKER=False,
    )
    yield application
    manager = application.extensions.get("generation_jobs")
    if manager is not None:
        manager.shutdown()


def _user(db_path, email="a@local", quota=20):
    return db.UsersRepo(db_path).create(
        email=email,
        display_name=email.split("@")[0],
        role="user",
        status="active",
        password_hash=db.hash_password("password123"),
        monthly_deck_quota=quota,
    )


def _login(client, uid):
    with client.session_transaction() as sess:
        sess["_user_id"] = uid
        sess["_fresh"] = True


def _ajax_generate(client, **overrides):
    data = {
        "commander_id": "cmdx",
        "budget": "200",
        "power": "3",
    }
    data.update(overrides)
    return client.post("/generate-deck", data=data, headers=XHR)


def _seed_card(db_path, card_id="cmdx", name="Synthetic Commander"):
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO cards (id, oracle_id, name, mana_cost, cmc, type_line, "
            "oracle_text, color_identity, keywords, is_legal_commander, "
            "is_legal_in_99, set_code, rarity) VALUES ("
            "?, ?, ?, '{G}', 3, 'Legendary Creature — Test', "
            "'Synthetic oracle text.', '[]', '[]', 1, 1, 'tst', 'rare')",
            (card_id, card_id + "-oracle", name),
        )
        conn.commit()


def _seed_deck(db_path, deck_id, owner_id, rationale, commander_id="cmdx"):
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO generated_decks (id, commander_id, owner_id, cards_json, "
            "rationale, budget_usd, power_target, estimated_bracket) "
            "VALUES (?, ?, ?, '[]', ?, 200, 3, 3)",
            (deck_id, commander_id, owner_id, json.dumps(rationale)),
        )
        conn.commit()


def _fake_build(captured, progress_callback):
    ctx = _cost_context.get() or {}
    deck_id = captured["deck_id"]
    assert ctx.get("user_id") == captured["owner_id"]
    assert ctx.get("deck_id") == deck_id
    conn = sqlite3.connect(captured["db_path"])
    try:
        conn.execute(
            "INSERT INTO cost_log (call_type, model, cost_usd, user_id, deck_id) "
            "VALUES ('fit', 'test-model', 0.01, ?, ?)",
            (ctx.get("user_id"), ctx.get("deck_id")),
        )
        conn.commit()
    finally:
        conn.close()
    progress_callback("validate", 10)
    progress_callback("optimize", 60)
    progress_callback("persist", 90)
    return deck_id


def _cost_count(db_path):
    with db.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM cost_log").fetchone()[0]


def test_prompt_returns_202_json(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    resp = _ajax_generate(client)
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert body["status_url"].endswith(f"/jobs/{body['job_id']}/status")
    assert "deck_url" in body
    public = resp.get_json()
    assert "request_json" not in public
    assert "owner_id" not in public


def test_double_post_is_deduplicated(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    first = _ajax_generate(client)
    second = _ajax_generate(client)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.get_json()["job_id"] == second.get_json()["job_id"]
    job_id = first.get_json()["job_id"]
    done = app.extensions["generation_jobs"].execute_job(job_id)
    assert done.status == "completed"
    third = _ajax_generate(client)
    assert third.status_code == 202
    assert third.get_json()["job_id"] != job_id


def test_owner_isolation_and_missing_job(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    owner = _user(db_path, "owner@local")
    other = _user(db_path, "other@local")
    client = app.test_client()
    _login(client, owner)
    job_id = _ajax_generate(client).get_json()["job_id"]

    _login(client, other)
    hidden = client.get(f"/jobs/{job_id}/status", headers=XHR)
    assert hidden.status_code == 404
    assert hidden.get_json()["error"] == "not found"
    html = client.get(f"/jobs/{job_id}")
    assert html.status_code == 404

    missing = client.get("/jobs/does-not-exist/status", headers=XHR)
    assert missing.status_code == 404


def test_missing_auth_json_is_401(app) -> None:
    client = app.test_client()
    resp = client.post("/generate-deck", data={"commander_id": "cmdx"}, headers=XHR)
    assert resp.status_code == 401
    status = client.get("/jobs/abc/status", headers=XHR)
    assert status.status_code == 401


def test_expired_session_cannot_read_job(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    job_id = _ajax_generate(client).get_json()["job_id"]
    db.UsersRepo(db_path).set_status(uid, "disabled")
    resp = client.get(f"/jobs/{job_id}/status", headers=XHR)
    assert resp.status_code == 401


def test_csrf_required_when_enabled(db_path) -> None:
    application = create_app(db_path)
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=True,
        RATELIMIT_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
        GENERATION_JOBS_ENABLE_WORKER=False,
    )
    uid = _user(db_path)
    client = application.test_client()
    _login(client, uid)
    denied = client.post(
        "/generate-deck",
        data={"commander_id": "cmdx", "budget": "200", "power": "3"},
        headers=XHR,
    )
    assert denied.status_code == 400

    home = client.get("/")
    assert home.status_code == 200
    match = re.search(r'name="csrf-token" content="([^"]+)"', home.data.decode())
    assert match
    token = match.group(1)
    allowed = client.post(
        "/generate-deck",
        data={"commander_id": "cmdx", "budget": "200", "power": "3"},
        headers={**XHR, "X-CSRFToken": token},
    )
    assert allowed.status_code == 202
    application.extensions["generation_jobs"].shutdown()


def test_success_failure_and_poll_does_not_spend(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    job_id = _ajax_generate(client).get_json()["job_id"]
    assert _cost_count(db_path) == 0

    status = client.get(f"/jobs/{job_id}/status", headers=XHR)
    assert status.status_code == 200
    assert status.get_json()["status"] == "queued"
    assert _cost_count(db_path) == 0

    done = app.extensions["generation_jobs"].execute_job(job_id)
    assert done.status == "completed"
    assert _cost_count(db_path) == 1

    again = client.get(f"/jobs/{job_id}/status", headers=XHR)
    body = again.get_json()
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["stage"] == "completed"
    assert body["deck_url"].endswith(f"/deck/{done.deck_id}")
    assert _cost_count(db_path) == 1

    def boom(captured, progress_callback):
        raise RuntimeError("sk-live-key provider {\"error\":\"nope\"}")

    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", boom)
    fail_id = _ajax_generate(client, commander_id="other").get_json()["job_id"]
    failed = app.extensions["generation_jobs"].execute_job(fail_id)
    assert failed.status == "failed"
    assert failed.error == GENERIC_FAILURE
    payload = client.get(f"/jobs/{fail_id}/status", headers=XHR).get_json()
    assert payload["error"] == GENERIC_FAILURE
    assert "sk-live-key" not in json.dumps(payload)
    assert "provider" not in json.dumps(payload)


def test_worker_cost_attribution_uses_captured_owner(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    job_id = _ajax_generate(client).get_json()["job_id"]
    app.extensions["generation_jobs"].execute_job(job_id)
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, deck_id, cost_usd FROM cost_log"
        ).fetchone()
    assert row["user_id"] == uid
    assert row["deck_id"]
    assert float(row["cost_usd"]) == 0.01


def test_quota_rechecked_at_execution(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path, quota=1)
    _seed_card(db_path)
    client = app.test_client()
    _login(client, uid)
    job_id = _ajax_generate(client).get_json()["job_id"]
    _seed_deck(db_path, "already", uid, {})
    done = app.extensions["generation_jobs"].execute_job(job_id)
    assert done.status == "failed"
    assert "Monthly limit reached" in (done.error or "")
    assert _cost_count(db_path) == 0


def test_non_js_post_redirects_to_job_page(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    resp = client.post(
        "/generate-deck",
        data={"commander_id": "cmdx", "budget": "100", "power": "2"},
    )
    assert resp.status_code == 302
    assert "/jobs/" in resp.headers["Location"]
    page = client.get(resp.headers["Location"])
    assert page.status_code == 200
    html = page.data.decode()
    assert "Queued" in html or "queued" in html
    assert "does not invent progress" in html or "Refresh status" in html


def test_conflict_hides_other_owners_job_id(app, db_path, monkeypatch) -> None:
    monkeypatch.setattr("sabermetrics.ui.routes._execute_generation", _fake_build)
    owner = _user(db_path, "owner@local")
    other = _user(db_path, "other@local")
    client = app.test_client()
    _login(client, owner)
    job_id = _ajax_generate(client).get_json()["job_id"]
    _login(client, other)
    resp = _ajax_generate(client, commander_id="someone-else")
    assert resp.status_code == 409
    body = resp.get_json()
    assert "job_id" not in body
    assert job_id not in json.dumps(body)


def test_quality_warnings_render_and_legacy_decks_ok(app, db_path) -> None:
    uid = _user(db_path)
    _seed_card(db_path)
    _seed_deck(
        db_path,
        "new-deck",
        uid,
        {
            "narrative": {"game_plan": "Play cards.", "key_synergies": [],
                          "weaknesses": [], "suggested_play_pattern": ""},
            "composition": {"total_price_usd": 10, "average_cmc": 2,
                            "mana_curve": [0] * 8, "type_distribution": {},
                            "component_counts": {}},
            "quality_warnings": [
                "Unmet target: clone package",
                {"code": "missing_signals", "message": "Embeddings unavailable"},
            ],
            "signals": {"empirical": False},
        },
    )
    _seed_deck(
        db_path,
        "old-deck",
        uid,
        {
            "narrative": {"game_plan": "Old plan.", "key_synergies": [],
                          "weaknesses": [], "suggested_play_pattern": ""},
            "composition": {"total_price_usd": 10, "average_cmc": 2,
                            "mana_curve": [0] * 8, "type_distribution": {},
                            "component_counts": {}},
        },
    )
    client = app.test_client()
    _login(client, uid)
    fresh = client.get("/deck/new-deck")
    assert fresh.status_code == 200
    body = fresh.data.decode()
    assert "Build notes" in body
    assert "Unmet target: clone package" in body
    assert "Embeddings unavailable" in body
    assert "Scoring signal unavailable: empirical" in body

    legacy = client.get("/deck/old-deck")
    assert legacy.status_code == 200
    assert "Build notes" not in legacy.data.decode()
    assert b"Old plan." in legacy.data or b"Strategy" in legacy.data


def test_profile_view_has_no_fake_timer_progress() -> None:
    html = PROFILE_TEMPLATE.read_text(encoding="utf-8")
    assert "hold my mana rock" not in html
    assert "Summoning the commander" not in html
    assert "p += (90 - p)" not in html
    assert "flavorTimer" not in html
    assert "status_url" in html
    assert "Lost connection. Retrying" in html


def test_create_app_does_not_start_worker_during_pytest(app) -> None:
    manager = app.extensions["generation_jobs"]
    assert manager.is_leader is False
    assert manager._worker_thread is None


@pytest.mark.parametrize("budget,power", [("nan", "3"), ("inf", "3"), ("-1", "3"), ("100", "6")])
def test_invalid_constraints_do_not_enqueue(app, db_path, budget, power):
    uid = _user(db_path)
    client = app.test_client()
    _login(client, uid)
    response = client.post("/generate-deck", data={"commander_id": "cmdx", "budget": budget, "power": power}, headers=XHR)
    assert response.status_code == 400
    with db.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0

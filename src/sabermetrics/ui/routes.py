"""Flask routes (D7.3).

Endpoints:
- GET /                         Home / commander selector
- GET /commander/<name>/profile Commander profile view
- POST /generate-deck           Enqueue deck generation (202 + job)
- GET /jobs/<job_id>            Owner-scoped job page (non-JS progress)
- GET /jobs/<job_id>/status     Owner-scoped JSON job status
- GET /deck/<deck_id>           View generated deck
- GET /report                   Cost and usage report
"""

import json
import logging
import math
import sqlite3
import uuid
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from sabermetrics import db
from sabermetrics.analytics.cvar import PRICE_FLOOR_USD
from sabermetrics.generation_jobs import (
    JobConflict,
    JobManager,
    JobUserError,
    WorkerUnavailable,
    request_fingerprint,
)
from sabermetrics.ui.explore_filters import ABILITY_OPTIONS, WUBRG, build_explore_query

bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)


def _parse_json_col(value, default="[]"):
    """Decode a JSON-encoded text column into a Python object."""
    if isinstance(value, str):
        try:
            return json.loads(value or default)
        except json.JSONDecodeError:
            return json.loads(default)
    return value if value is not None else json.loads(default)


def _can_access_deck(owner_id: str | None) -> bool:
    """A deck is visible to its owner or any admin."""
    return bool(
        owner_id == current_user.id or getattr(current_user, "is_admin", False)
    )


def _monthly_spend(db_path: Path) -> float:
    """Total LLM spend across all users in the trailing 30 days."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log "
            "WHERE timestamp >= datetime('now', '-30 days')"
        ).fetchone()[0]
    finally:
        conn.close()


def _quota_reset_label() -> str:
    """Human label for when the per-user monthly quota next resets."""
    from datetime import UTC, date, datetime

    today = datetime.now(UTC).date()
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return date(year, month, 1).strftime("%B 1")


def _generation_blocked(is_ajax: bool, message: str, status: int):
    """Return a blocked-generation response (JSON for XHR, else flash+redirect)."""
    if is_ajax:
        return jsonify({"error": message}), status
    flash(message, "error")
    return redirect(request.referrer or url_for("main.index"))


@bp.before_request
def _require_login():
    """Gate every user-portal route behind an authenticated, active session.

    Public auth routes (login/logout/invite) live in the ``auth`` blueprint and
    are unaffected. Static assets are served by the app's own static endpoint,
    also outside this blueprint.
    """
    if not current_user.is_authenticated:
        from sabermetrics.ui.auth import login_manager

        return login_manager.unauthorized()
    return None


def _db_path() -> Path:
    return current_app.config["DB_PATH"]


def _job_manager() -> JobManager:
    manager = current_app.extensions.get("generation_jobs")
    if manager is None:
        from sabermetrics.generation_jobs import attach_to_app

        manager = attach_to_app(current_app)
    return manager


def _wants_json() -> bool:
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def _quality_warning_messages(rationale: dict | None) -> list[str]:
    """Normalize quality_warnings / unavailable signals for old and new decks."""
    if not isinstance(rationale, dict):
        return []
    messages: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        item = " ".join(str(text).split())
        if item and item not in seen:
            seen.add(item)
            messages.append(item)

    raw = rationale.get("quality_warnings")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                add(item.get("message") or item.get("code") or item.get("kind") or "")
            elif item:
                add(item)
    elif isinstance(raw, dict):
        for kind, items in raw.items():
            kind_label = str(kind).replace("_", " ")
            if isinstance(items, list):
                if not items:
                    continue
                for item in items:
                    if isinstance(item, dict):
                        add(item.get("message") or f"{kind_label}: {item}")
                    else:
                        add(f"{kind_label}: {item}" if item else kind_label)
            elif items is True:
                add(kind_label)
            elif items:
                add(f"{kind_label}: {items}")
    elif isinstance(raw, str) and raw.strip():
        add(raw)

    meta = rationale.get("meta") if isinstance(rationale.get("meta"), dict) else {}
    unavailable = (
        rationale.get("signals_unavailable")
        or meta.get("signals_unavailable")
        or []
    )
    if isinstance(unavailable, list):
        for name in unavailable:
            add(f"Scoring signal unavailable: {name}")
    signals = rationale.get("signals")
    if isinstance(signals, dict):
        for name, live in signals.items():
            if live is False:
                add(f"Scoring signal unavailable: {name}")
    return messages


def _assert_execution_allowed(captured: dict) -> None:
    """Re-check cost ceiling and per-user quota inside the worker."""
    from sabermetrics.config import settings

    db_path = Path(captured["db_path"])
    owner_id = captured["owner_id"]
    quota = int(captured["quota"])
    if _monthly_spend(db_path) >= settings.llm.monthly_cost_ceiling_usd:
        raise JobUserError(
            "Generation is paused: the monthly cost ceiling has been reached. "
            "Please try again next month."
        )
    used = db.DecksRepo(db_path).count_this_month(owner_id)
    if used >= quota:
        raise JobUserError(
            f"Monthly limit reached ({used}/{quota} decks). "
            f"Your quota resets {_quota_reset_label()}."
        )


def _execute_generation(captured: dict, progress_callback) -> str:
    """Run the builder with captured request values (no Flask request context)."""
    from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest

    db_path = Path(captured["db_path"])
    deck_id = captured["deck_id"]
    builder = DeckBuilder(db_path, progress_callback=progress_callback)
    request = DeckBuildRequest(
        commander_id=captured["commander_id"],
        budget_usd=captured["budget_usd"],
        power_target=captured["power_target"],
        strategy=captured["strategy"],
        user_intent=captured["user_intent"],
        deck_name=captured["deck_name"],
        owner_id=captured["owner_id"],
        deck_id=deck_id,
    )
    result = builder.build(request)
    db.DecksRepo(db_path).set_owner(result.deck.id, captured["owner_id"])
    return result.deck.id


def _make_generation_work(captured: dict):
    """Callable stored on the job: quotas, cost attribution, then the builder."""

    def work(progress_callback) -> str:
        _assert_execution_allowed(captured)
        deck_id = str(uuid.uuid4())
        payload = {**captured, "deck_id": deck_id}
        from sabermetrics.reasoning.client import cost_attribution

        with cost_attribution(payload["owner_id"], deck_id):
            return _execute_generation(payload, progress_callback)

    return work


def _job_json_response(job, *, status_code: int = 200):
    deck_url = None
    if job.status == "completed" and job.deck_id:
        deck_url = url_for("main.view_deck", deck_id=job.deck_id)
    body = job.to_public_dict(deck_url=deck_url)
    body["status_url"] = url_for("main.job_status", job_id=job.id)
    body["job_url"] = url_for("main.view_job", job_id=job.id)
    response = jsonify(body)
    response.status_code = status_code
    response.headers["Location"] = body["status_url"]
    return response


def _owner_job_or_none(job_id: str):
    job = _job_manager().get(job_id)
    if job is None or job.owner_id != current_user.id:
        return None
    return job


@bp.route("/")
def index():
    """Home dashboard: quota meter, recent decks, favorite quick-builds, stats."""
    db_path = _db_path()
    user_id = current_user.id

    decks_repo = db.DecksRepo(db_path)
    favs = db.FavoritesRepo(db_path)

    recent_decks = decks_repo.list_for_owner(user_id, limit=6)
    fav_commanders = favs.list_commanders(user_id)
    for c in fav_commanders:
        c["color_identity"] = _parse_json_col(c.get("color_identity"))

    used = decks_repo.count_this_month(user_id)
    quota = current_user.monthly_deck_quota
    total_decks = len(decks_repo.list_for_owner(user_id))

    stats = {
        "decks": total_decks,
        "favorites": len(fav_commanders),
        "quota_used": used,
        "quota": quota,
        "quota_remaining": max(0, quota - used),
        "quota_pct": min(100, round(used / quota * 100)) if quota else 0,
    }

    return render_template(
        "home.html",
        recent_decks=recent_decks,
        fav_commanders=fav_commanders[:6],
        stats=stats,
    )


@bp.route("/explore")
def explore():
    """Browse legal commanders with color/ability/price/CMC filters."""
    db_path = _db_path()
    eq = build_explore_query(request.args)

    sql = (
        "SELECT id, name, type_line, color_identity, keywords, mana_cost, cmc, "
        "image_uri, price_usd, rarity FROM commander_candidates "
        f"WHERE {eq.where_sql} ORDER BY {eq.order_sql} LIMIT ? OFFSET ?"
    )
    # Fetch one extra row to detect a next page without a COUNT query.
    params = [*eq.params, eq.limit + 1, eq.offset]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as e:
        logger.warning("Explore query error: %s", e)
        rows = []
    finally:
        conn.close()

    has_next = len(rows) > eq.limit
    rows = rows[: eq.limit]
    for r in rows:
        r["color_identity"] = _parse_json_col(r.get("color_identity"))

    fav_ids = db.FavoritesRepo(db_path).commander_ids(current_user.id)

    return render_template(
        "explore.html",
        results=rows,
        eq=eq,
        has_next=has_next,
        fav_ids=fav_ids,
        all_colors=WUBRG,
        all_abilities=ABILITY_OPTIONS,
    )


@bp.route("/decks")
def decks():
    """List the current user's generated decks (with optional name search)."""
    db_path = _db_path()
    query = request.args.get("q", "").strip().lower()

    all_decks = db.DecksRepo(db_path).list_for_owner(current_user.id)
    if query:
        all_decks = [
            d
            for d in all_decks
            if query in (d.get("commander_name") or "").lower()
            or query in (d.get("deck_name") or "").lower()
        ]
    fav_ids = db.FavoritesRepo(db_path).deck_ids(current_user.id)

    return render_template("decks.html", decks=all_decks, fav_ids=fav_ids, query=query)


@bp.route("/favorites/commanders")
def favorite_commanders():
    """Grid of the user's favorited commanders."""
    db_path = _db_path()
    commanders = db.FavoritesRepo(db_path).list_commanders(current_user.id)
    for c in commanders:
        c["color_identity"] = _parse_json_col(c.get("color_identity"))
    return render_template("favorites_commanders.html", commanders=commanders)


@bp.route("/favorites/decks")
def favorite_decks():
    """List the user's favorited decks."""
    db_path = _db_path()
    decks_list = db.FavoritesRepo(db_path).list_decks(current_user.id)
    return render_template("favorites_decks.html", decks=decks_list)


@bp.route("/favorites/commander/<commander_id>/toggle", methods=["POST"])
def toggle_favorite_commander(commander_id: str):
    """Async: toggle a commander favorite. Returns the new state."""
    favorited = db.FavoritesRepo(_db_path()).toggle_commander(
        current_user.id, commander_id
    )
    return jsonify({"favorited": favorited})


@bp.route("/favorites/deck/<deck_id>/toggle", methods=["POST"])
def toggle_favorite_deck(deck_id: str):
    """Async: toggle a deck favorite (only decks the user can access)."""
    db_path = _db_path()
    owner = db.DecksRepo(db_path).owner_of(deck_id)
    if owner is None:
        return jsonify({"error": "not found"}), 404
    if not _can_access_deck(owner):
        return jsonify({"error": "forbidden"}), 403
    favorited = db.FavoritesRepo(db_path).toggle_deck(current_user.id, deck_id)
    return jsonify({"favorited": favorited})


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    """View and edit the current user's profile."""
    db_path = _db_path()
    users = db.UsersRepo(db_path)

    if request.method == "POST":
        display_name = (request.form.get("display_name") or "").strip()
        avatar = (request.form.get("avatar_emoji") or "").strip() or None
        if not display_name:
            flash("Display name can't be empty.", "error")
        else:
            users.update_profile(current_user.id, display_name, avatar)
            flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))

    decks_repo = db.DecksRepo(db_path)
    used = decks_repo.count_this_month(current_user.id)
    quota = current_user.monthly_deck_quota
    return render_template(
        "profile.html",
        used=used,
        quota=quota,
        remaining=max(0, quota - used),
        total_decks=len(decks_repo.list_for_owner(current_user.id)),
    )


@bp.route("/profile/password", methods=["POST"])
def change_password():
    """Change the current user's password (requires the current one)."""
    db_path = _db_path()
    users = db.UsersRepo(db_path)
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    row = users.get(current_user.id)
    if not db.verify_password(row.get("password_hash"), current):
        flash("Current password is incorrect.", "error")
    elif len(new) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    else:
        users.set_password(current_user.id, db.hash_password(new))
        flash("Password changed.", "success")
    return redirect(url_for("main.profile"))


@bp.route("/commander/<path:name>/profile")
def commander_profile(name: str):
    """View commander profile."""
    db_path = _db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Find commander
        cursor = conn.execute(
            "SELECT id, name FROM cards "
            "WHERE name LIKE ? AND is_legal_commander = 1 "
            "GROUP BY name LIMIT 1",
            (f"%{name}%",),
        )
        row = cursor.fetchone()
        if row is None:
            return render_template("profile_view.html", error=f"Commander not found: {name}")

        commander_id = row["id"]
        commander_name = row["name"]

        # Try to load cached profile
        profile_cursor = conn.execute(
            "SELECT profile_json, generated_at FROM commander_profiles "
            "WHERE commander_id = ? AND is_stale = 0 "
            "ORDER BY generated_at DESC LIMIT 1",
            (commander_id,),
        )
        profile_row = profile_cursor.fetchone()

        profile = None
        if profile_row:
            profile = json.loads(profile_row["profile_json"])
            profile["_generated_at"] = profile_row["generated_at"]

        # Get EDHREC data
        edhrec_cursor = conn.execute(
            "SELECT * FROM edhrec_commander_data WHERE commander_id = ?",
            (commander_id,),
        )
        edhrec_row = edhrec_cursor.fetchone()
        edhrec = dict(edhrec_row) if edhrec_row else None
        if edhrec:
            for field in ("themes", "top_cards"):
                val = edhrec.get(field, "[]")
                if isinstance(val, str):
                    edhrec[field] = json.loads(val)

        # Get card data
        card_cursor = conn.execute(
            "SELECT * FROM cards WHERE id = ?", (commander_id,)
        )
        card_row = card_cursor.fetchone()
        card = dict(card_row) if card_row else {}
        for field in ("color_identity", "keywords"):
            val = card.get(field, "[]")
            if isinstance(val, str):
                card[field] = json.loads(val)

    finally:
        conn.close()

    return render_template(
        "profile_view.html",
        commander_name=commander_name,
        commander_id=commander_id,
        card=card,
        profile=profile,
        edhrec=edhrec,
    )


@bp.route("/generate-deck", methods=["POST"])
def generate_deck():
    """Enqueue deck generation; POST returns promptly with a job id."""
    db_path = _db_path()

    commander_id = (request.form.get("commander_id") or "").strip()
    strategy = request.form.get("strategy") or None
    user_intent = request.form.get("user_intent") or None
    deck_name = request.form.get("deck_name") or None
    is_ajax = _wants_json()

    try:
        budget = float(request.form.get("budget", 200))
        power = int(request.form.get("power", 3))
    except (TypeError, ValueError):
        return _generation_blocked(is_ajax, "Invalid budget or power.", 400)

    if not math.isfinite(budget) or budget <= 0 or not 1 <= power <= 5:
        return _generation_blocked(is_ajax, "Budget must be positive and power must be from 1 to 5.", 400)

    if not commander_id:
        if is_ajax:
            return jsonify({"error": "No commander selected"}), 400
        return redirect(url_for("main.index"))

    from sabermetrics.config import settings

    # Global cost ceiling (friendly pre-check; the worker re-checks at execution).
    if _monthly_spend(db_path) >= settings.llm.monthly_cost_ceiling_usd:
        return _generation_blocked(
            is_ajax,
            "Generation is paused: the monthly cost ceiling has been reached. "
            "Please try again next month.",
            503,
        )

    # Per-user monthly quota (admin-overridable; global default otherwise).
    decks_repo = db.DecksRepo(db_path)
    used = decks_repo.count_this_month(current_user.id)
    quota = current_user.monthly_deck_quota
    if used >= quota:
        return _generation_blocked(
            is_ajax,
            f"Monthly limit reached ({used}/{quota} decks). "
            f"Your quota resets {_quota_reset_label()}.",
            429,
        )

    captured = {
        "db_path": str(db_path),
        "owner_id": current_user.id,
        "quota": quota,
        "commander_id": commander_id,
        "budget_usd": budget,
        "power_target": power,
        "strategy": strategy,
        "user_intent": user_intent,
        "deck_name": deck_name,
    }
    fingerprint = request_fingerprint(
        current_user.id,
        commander_id,
        budget,
        power,
        strategy,
        user_intent,
        deck_name,
    )
    try:
        job = _job_manager().submit(
            owner_id=current_user.id,
            fingerprint=fingerprint,
            request_payload=captured,
            work=_make_generation_work(captured),
        )
    except WorkerUnavailable as exc:
        return _generation_blocked(is_ajax, str(exc), 503)
    except JobConflict as exc:
        if is_ajax:
            body = {"error": str(exc)}
            if exc.owned and exc.job is not None:
                body["job_id"] = exc.job.id
                body["status_url"] = url_for("main.job_status", job_id=exc.job.id)
                body["job_url"] = url_for("main.view_job", job_id=exc.job.id)
            return jsonify(body), 409
        flash(str(exc), "error")
        if exc.owned and exc.job is not None:
            return redirect(url_for("main.view_job", job_id=exc.job.id))
        return redirect(request.referrer or url_for("main.index"))

    if is_ajax:
        return _job_json_response(job, status_code=202)
    return redirect(url_for("main.view_job", job_id=job.id))


@bp.route("/jobs/<job_id>")
def view_job(job_id: str):
    """Owner-scoped HTML job page. Reloads real status; no pretend progress."""
    job = _owner_job_or_none(job_id)
    if job is None:
        abort(404)
    if job.status == "completed" and job.deck_id:
        return redirect(url_for("main.view_deck", deck_id=job.deck_id))
    return render_template("job_status.html", job=job)


@bp.route("/jobs/<job_id>/status")
def job_status(job_id: str):
    """Owner-scoped JSON status. Polling never starts work or spends."""
    job = _owner_job_or_none(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    return _job_json_response(job)


@bp.route("/deck/<deck_id>/delete", methods=["POST"])
def delete_deck(deck_id: str):
    """Delete a generated deck (owner or admin only)."""
    db_path = _db_path()
    owner = db.DecksRepo(db_path).owner_of(deck_id)
    if owner is not None and not _can_access_deck(owner):
        abort(403)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM favorite_decks WHERE deck_id = ?", (deck_id,))
        conn.execute("DELETE FROM generated_decks WHERE id = ?", (deck_id,))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("main.decks"))


@bp.route("/deck/<deck_id>/card/<path:card_id>/feedback", methods=["POST"])
def card_feedback(deck_id: str, card_id: str):
    """Owner-only: save a thumbs vote + comment for a card in this deck."""
    db_path = _db_path()
    owner = db.DecksRepo(db_path).owner_of(deck_id)
    if owner is None:
        return jsonify({"error": "not found"}), 404
    if owner != current_user.id:
        return jsonify({"error": "forbidden"}), 403

    vote = request.form.get("vote") or None
    if vote not in (None, "up", "down"):
        return jsonify({"error": "invalid vote"}), 400
    comment = request.form.get("comment")
    card_name = request.form.get("card_name") or ""
    db.FeedbackRepo(db_path).upsert_card(
        current_user.id, deck_id, card_id, card_name, vote, comment
    )
    return jsonify({"ok": True, "vote": vote, "comment": (comment or "").strip()})


@bp.route("/deck/<deck_id>/feedback", methods=["POST"])
def deck_feedback(deck_id: str):
    """Owner-only: save the deck's overall verdict + comment."""
    db_path = _db_path()
    owner = db.DecksRepo(db_path).owner_of(deck_id)
    if owner is None:
        return jsonify({"error": "not found"}), 404
    if owner != current_user.id:
        return jsonify({"error": "forbidden"}), 403

    verdict = request.form.get("verdict") or None
    if verdict not in (None, "good", "bad", "mixed"):
        return jsonify({"error": "invalid verdict"}), 400
    comment = request.form.get("comment")
    db.FeedbackRepo(db_path).upsert_deck(current_user.id, deck_id, verdict, comment)
    return jsonify({"ok": True, "verdict": verdict})


@bp.route("/deck/<deck_id>")
def view_deck(deck_id: str):
    """View a generated deck."""
    db_path = _db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT gd.*, c.name as commander_name, c.type_line, "
            "c.mana_cost, c.oracle_text, c.color_identity, c.image_uri "
            "FROM generated_decks gd "
            "JOIN cards c ON gd.commander_id = c.id "
            "WHERE gd.id = ?",
            (deck_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return render_template("deck_view.html", error="Deck not found")

        # Privacy: a deck is visible only to its owner (or an admin).
        owner_id = row["owner_id"]
        if owner_id is not None and not _can_access_deck(owner_id):
            abort(403)

        deck_data = dict(row)
        deck_data["cards"] = json.loads(deck_data.get("cards_json", "[]"))
        deck_data["rationale"] = json.loads(deck_data.get("rationale", "{}"))

        ci = deck_data.get("color_identity", "[]")
        if isinstance(ci, str):
            deck_data["color_identity"] = json.loads(ci)

        # Enrich cards with full card data
        card_ids = [c.get("card_id", "") for c in deck_data["cards"]]
        if card_ids:
            placeholders = ",".join("?" for _ in card_ids)
            card_cursor = conn.execute(
                f"SELECT id, name, type_line, mana_cost, cmc, oracle_text, "
                f"rarity, image_uri FROM cards WHERE id IN ({placeholders})",
                card_ids,
            )
            card_lookup = {r["id"]: dict(r) for r in card_cursor}

            for card_entry in deck_data["cards"]:
                full = card_lookup.get(card_entry.get("card_id", ""), {})
                card_entry.update(full)

            # Enrich basic lands (synthetic IDs not in cards table)
            basic_names = set()
            for card_entry in deck_data["cards"]:
                if card_entry.get("card_id", "").startswith("basic-"):
                    name = card_entry.get("name", "")
                    card_entry.setdefault("type_line", f"Basic Land \u2014 {name}")
                    card_entry.setdefault("mana_cost", "")
                    card_entry.setdefault("cmc", 0.0)
                    if name and not card_entry.get("image_uri"):
                        basic_names.add(name)

            if basic_names:
                bp = ",".join("?" for _ in basic_names)
                basic_cursor = conn.execute(
                    f"SELECT name, MIN(image_uri) as image_uri FROM cards "
                    f"WHERE name IN ({bp}) AND image_uri IS NOT NULL "
                    f"GROUP BY name",
                    list(basic_names),
                )
                basic_images = {r["name"]: r["image_uri"] for r in basic_cursor}
                for card_entry in deck_data["cards"]:
                    if (card_entry.get("card_id", "").startswith("basic-")
                            and not card_entry.get("image_uri")):
                        name = card_entry.get("name", "")
                        img = basic_images.get(name)
                        if img:
                            card_entry["image_uri"] = img
                        elif name:
                            # Scryfall named-card image fallback
                            safe = name.replace(" ", "+")
                            card_entry["image_uri"] = (
                                f"https://api.scryfall.com/cards/named"
                                f"?exact={safe}&format=image&version=normal"
                            )

            # Get latest prices by card_id
            price_cursor = conn.execute(
                f"SELECT card_id, price_usd FROM card_prices "
                f"WHERE card_id IN ({placeholders}) "
                f"ORDER BY snapshot_date DESC",
                card_ids,
            )
            price_lookup: dict[str, float] = {}
            for r in price_cursor:
                # Latest NON-NULL snapshot per printing. Coercing a NULL
                # latest snapshot to the floor showed $1-8 staples
                # (Vandalblast, Swiftfoot Boots, Beast Within) as $0.05 and
                # blocked the name-based fallback below from ever firing --
                # a printing with no price anywhere falls through to the
                # cheapest-priced OTHER printing of the same card instead.
                if r["card_id"] not in price_lookup and r["price_usd"] is not None:
                    price_lookup[r["card_id"]] = r["price_usd"]

            # Fallback: for cards without prices (promo printings, legacy
            # decks), look up cheapest price by card name
            missing_names = set()
            for card_entry in deck_data["cards"]:
                cid = card_entry.get("card_id", "")
                if cid not in price_lookup and not cid.startswith("basic-"):
                    name = card_entry.get("name", "")
                    if name:
                        missing_names.add(name)

            name_price_lookup: dict[str, float] = {}
            if missing_names:
                name_placeholders = ",".join("?" for _ in missing_names)
                name_price_cursor = conn.execute(
                    f"SELECT c.name, MIN(cp.price_usd) as min_price "
                    f"FROM cards c JOIN card_prices cp ON c.id = cp.card_id "
                    f"WHERE c.name IN ({name_placeholders}) "
                    f"AND cp.price_usd IS NOT NULL "
                    f"GROUP BY c.name",
                    list(missing_names),
                )
                for r in name_price_cursor:
                    name_price_lookup[r["name"]] = r["min_price"]

            for card_entry in deck_data["cards"]:
                cid = card_entry.get("card_id", "")
                if cid in price_lookup:
                    card_entry["price_usd"] = price_lookup[cid]
                elif card_entry.get("name", "") in name_price_lookup:
                    card_entry["price_usd"] = name_price_lookup[
                        card_entry["name"]
                    ]
                else:
                    card_entry["price_usd"] = PRICE_FLOOR_USD

            # Recalculate total price from corrected per-card prices
            recalculated_total = sum(
                float(c.get("price_usd", 0) or 0) for c in deck_data["cards"]
            )
            if "rationale" in deck_data and "composition" in deck_data["rationale"]:
                deck_data["rationale"]["composition"]["total_price_usd"] = round(
                    recalculated_total, 2
                )

        # Group cards by role
        by_role: dict[str, list] = {}
        for card in deck_data["cards"]:
            role = card.get("slot_role", "other")
            if role not in by_role:
                by_role[role] = []
            by_role[role].append(card)
        deck_data["cards_by_role"] = by_role

        # Group cards by card type (default view), aggregating duplicates
        from collections import Counter
        name_counts: Counter[str] = Counter()
        name_info: dict[str, dict] = {}
        for card in deck_data["cards"]:
            name = card.get("name", "Unknown")
            name_counts[name] += 1
            if name not in name_info:
                name_info[name] = card

        by_type: dict[str, list] = {}
        for name, qty in name_counts.items():
            card = name_info[name]
            type_line = (card.get("type_line") or "").lower()
            if "land" in type_line or card.get("slot_role") == "land":
                card_type = "Land"
            elif "creature" in type_line:
                card_type = "Creature"
            elif "instant" in type_line:
                card_type = "Instant"
            elif "sorcery" in type_line:
                card_type = "Sorcery"
            elif "artifact" in type_line:
                card_type = "Artifact"
            elif "enchantment" in type_line:
                card_type = "Enchantment"
            elif "planeswalker" in type_line:
                card_type = "Planeswalker"
            elif "battle" in type_line:
                card_type = "Battle"
            else:
                card_type = "Other"
            entry = dict(card)
            entry["qty"] = qty
            if card_type not in by_type:
                by_type[card_type] = []
            by_type[card_type].append(entry)
        deck_data["cards_by_type"] = by_type

    finally:
        conn.close()

    # --- Compute chart data for dashboard ---
    from sabermetrics.pipeline.mana_base import count_color_pips, parse_land_colors
    from sabermetrics.pipeline.slot_assigner import get_target_composition

    rationale = deck_data.get("rationale", {})
    comp = rationale.get("composition", {})
    component_counts = comp.get("component_counts", {})
    commander_colors = deck_data.get("color_identity", [])
    power_target = deck_data.get("power_target", 3)

    # Average CVAR
    cvar_values = [
        c.get("cvar_score", 0)
        for c in deck_data["cards"]
        if c.get("cvar_score") is not None
    ]
    avg_cvar = round(
        sum(cvar_values) / len(cvar_values), 2
    ) if cvar_values else 0.0

    # Radar chart: actual component counts vs targets
    target_comp = get_target_composition(power_target)
    wipe_targets = {1: 2, 2: 2, 3: 3, 4: 3, 5: 4}
    tutor_targets = {1: 0, 2: 1, 3: 2, 4: 3, 5: 5}
    chart_components = {
        "labels": ["Ramp", "Draw", "Removal", "Wipes", "Tutors", "Win Cons"],
        "actual": [
            component_counts.get("ramp", 0),
            component_counts.get("draw", 0),
            component_counts.get("removal", 0),
            component_counts.get("board_wipes", 0),
            component_counts.get("tutors", 0),
            component_counts.get("win_conditions", 0),
        ],
        "target": [
            target_comp.get("ramp", 0),
            target_comp.get("draw", 0),
            target_comp.get("removal", 0),
            wipe_targets.get(power_target, 3),
            tutor_targets.get(power_target, 2),
            target_comp.get("wincon", 0),
        ],
    }

    # Pip counts vs mana sources per commander color
    pip_counts = count_color_pips(deck_data["cards"])
    source_counts: dict[str, int] = {c: 0 for c in commander_colors}
    for card in deck_data["cards"]:
        tl = (card.get("type_line") or "").lower()
        if "land" in tl:
            info = parse_land_colors(
                card.get("oracle_text") or "",
                card.get("type_line") or "",
                commander_colors,
            )
            for color in info.colors_produced:
                if color in source_counts:
                    source_counts[color] += 1

    chart_pip_vs_sources = {
        "colors": commander_colors,
        "pips": [
            pip_counts.get(c, {}).get("total_pips", 0)
            for c in commander_colors
        ],
        "sources": [source_counts.get(c, 0) for c in commander_colors],
    }

    # Value scatter: CVAR vs price for non-land cards
    chart_value_scatter = []
    for card in deck_data["cards"]:
        tl = (card.get("type_line") or "").lower()
        if "land" in tl:
            continue
        chart_value_scatter.append({
            "name": card.get("name", "Unknown"),
            "cvar": round(card.get("cvar_score", 0), 2),
            "price": round(card.get("price_usd", 0) or 0, 2),
            "role": card.get("slot_role", "other"),
        })

    # Feedback: only the deck's owner rates it (admins viewing get read-only).
    owner_id = deck_data.get("owner_id")
    can_feedback = owner_id is not None and owner_id == current_user.id
    feedback_repo = db.FeedbackRepo(db_path)
    card_feedback = feedback_repo.card_map(current_user.id, deck_id) if can_feedback else {}
    deck_feedback = feedback_repo.deck(current_user.id, deck_id) if can_feedback else None

    quality_warnings = _quality_warning_messages(rationale)

    return render_template(
        "deck_view.html",
        deck=deck_data,
        avg_cvar=avg_cvar,
        chart_mana_curve=comp.get("mana_curve", [0] * 8),
        chart_type_dist=comp.get("type_distribution", {}),
        chart_components=chart_components,
        chart_pip_vs_sources=chart_pip_vs_sources,
        chart_value_scatter=chart_value_scatter,
        can_feedback=can_feedback,
        card_feedback=card_feedback,
        deck_feedback=deck_feedback,
        quality_warnings=quality_warnings,
    )


@bp.route("/report")
def cost_report():
    """Cost and usage report."""
    db_path = _db_path()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Spend by call type (last 30 days)
        cursor = conn.execute(
            "SELECT call_type, "
            "COUNT(*) as call_count, "
            "SUM(cost_usd) as total_cost, "
            "SUM(input_tokens) as total_input, "
            "SUM(output_tokens) as total_output "
            "FROM cost_log "
            "WHERE timestamp >= datetime('now', '-30 days') "
            "GROUP BY call_type "
            "ORDER BY total_cost DESC"
        )
        by_type = [dict(row) for row in cursor]

        # Total spend last 30 days
        total_cursor = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total "
            "FROM cost_log "
            "WHERE timestamp >= datetime('now', '-30 days')"
        )
        total_30d = total_cursor.fetchone()["total"]

        # Project annual
        annual_projection = total_30d * 12

        # Monthly ceiling
        from sabermetrics.config import settings
        ceiling = settings.llm.monthly_cost_ceiling_usd

        # Recent calls
        recent_cursor = conn.execute(
            "SELECT call_type, model, cost_usd, input_tokens, "
            "output_tokens, timestamp "
            "FROM cost_log "
            "ORDER BY timestamp DESC LIMIT 20"
        )
        recent_calls = [dict(row) for row in recent_cursor]

        # Generated deck count
        deck_cursor = conn.execute(
            "SELECT COUNT(*) as count FROM generated_decks"
        )
        deck_count = deck_cursor.fetchone()["count"]

        # Profile count
        profile_cursor = conn.execute(
            "SELECT COUNT(*) as count FROM commander_profiles WHERE is_stale = 0"
        )
        profile_count = profile_cursor.fetchone()["count"]

    except sqlite3.Error as e:
        logger.warning("Report query error: %s", e)
        by_type = []
        total_30d = 0.0
        annual_projection = 0.0
        ceiling = 5.0
        recent_calls = []
        deck_count = 0
        profile_count = 0
    finally:
        conn.close()

    return render_template(
        "cost_report.html",
        by_type=by_type,
        total_30d=total_30d,
        annual_projection=annual_projection,
        ceiling=ceiling,
        recent_calls=recent_calls,
        deck_count=deck_count,
        profile_count=profile_count,
    )

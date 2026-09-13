"""Acquisition, validation and cache behaviour for public EDHREC evidence.

Every test supplies a fake transport; nothing here touches the network.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from sabermetrics.intelligence.evidence import (
    FRESH_DAYS,
    MAX_RESPONSE_BYTES,
    VERSION,
    FetchError,
    HttpResponse,
    SelectionEvidence,
    cache_path,
    cohort_for_power,
    commander_slug,
    load_selection_evidence,
    parse_payload,
    source_url_for,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
KORVOLD = {"name": "Korvold, Fae-Cursed King"}


def view(name, num_decks=500, potential_decks=1000, **kwargs):
    return {
        "name": name,
        "sanitized": commander_slug(name),
        "num_decks": num_decks,
        "potential_decks": potential_decks,
        **kwargs,
    }


def payload(
    commander="Korvold, Fae-Cursed King",
    cohort="general",
    cardlists=None,
    **top_level,
):
    header = f"{commander} (Commander)"
    if cohort == "cedh":
        header += " - cEDH"
    if cardlists is None:
        cardlists = [
            {
                "tag": "topcards",
                "header": "Top Cards",
                "cardviews": [
                    view("Mayhem Devil", 800, 1000, synergy=0.42),
                    view("Sol Ring", 900, 1000, synergy=0.01),
                ],
            },
            {
                "tag": "utilitylands",
                "header": "Utility Lands",
                "cardviews": [view("Command Tower", 700, 1000, synergy=0.02)],
            },
        ]
    body = {
        "header": header,
        "creature": 29,
        "instant": 11,
        "land": 34,
        "basic": 12,
        "container": {"json_dict": {"cardlists": cardlists}},
    }
    body.update(top_level)
    return body


def fake_fetch(mapping, calls=None):
    """Transport returning canned responses; unmapped urls are 404."""

    def _fetch(url):
        if calls is not None:
            calls.append(url)
        result = mapping.get(url)
        if result is None:
            return HttpResponse(404, b"")
        if isinstance(result, Exception):
            raise result
        if isinstance(result, HttpResponse):
            return result
        return HttpResponse(200, json.dumps(result).encode())

    return _fetch


def load(commander=KORVOLD, power=3, cache_dir=None, mapping=None, **kwargs):
    return load_selection_evidence(
        commander,
        power,
        cache_dir,
        fetch=fake_fetch(mapping or {}),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


# --- slugs and cohorts ----------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Korvold, Fae-Cursed King", "korvold-fae-cursed-king"),
        ("Kenrith's Transformation", "kenriths-transformation"),
        ("Ratadrabik of Urborg", "ratadrabik-of-urborg"),
        ("Jan Jansen, Chaos Crafter", "jan-jansen-chaos-crafter"),
        ("Kroxa, Titan of Death's Hunger", "kroxa-titan-of-deaths-hunger"),
        ("Ojer Axonil, Deepest Might // Temple of Power", "ojer-axonil-deepest-might"),
        ("Rograkh, Son of Rohgahh", "rograkh-son-of-rohgahh"),
        ("Ach! Hans, Run!", "ach-hans-run"),
        ("Jötun Grunt", "jotun-grunt"),
        ("Sisay’s Ring", "sisays-ring"),
    ],
)
def test_slug_handles_punctuation_and_faces(name, expected):
    assert commander_slug(name) == expected


def test_cohort_and_url_selection():
    assert cohort_for_power(5) == "cedh"
    assert cohort_for_power(3) == "general"
    assert source_url_for("kinnan-bonder-prodigy", "cedh").endswith(
        "/kinnan-bonder-prodigy/cedh.json"
    )
    assert source_url_for("korvold-fae-cursed-king", "general").endswith(
        "/korvold-fae-cursed-king.json"
    )


# --- happy path -----------------------------------------------------------


def test_available_evidence_parses_public_fields(tmp_path):
    url = source_url_for("korvold-fae-cursed-king", "general")
    ev = load(cache_dir=tmp_path, mapping={url: payload()})

    assert ev.status == "available"
    assert isinstance(ev, SelectionEvidence)
    assert ev.source_url == url
    assert ev.commander_name == "Korvold, Fae-Cursed King"
    assert ev.cohort == "general"
    assert ev.retrieved_at == NOW
    assert ev.sample_size == 1000
    assert ev.inclusion["Mayhem Devil"] == pytest.approx(0.8)
    assert ev.inclusion["Command Tower"] == pytest.approx(0.7)
    assert all(0.0 <= r <= 1.0 for r in ev.inclusion.values())
    assert ev.synergy["Mayhem Devil"] == pytest.approx(0.42)
    assert ev.composition == {
        "creature": 29.0,
        "instant": 11.0,
        "land": 34.0,
        "basic": 12.0,
    }
    assert ev.limitations and any("no win rate" in n for n in ev.limitations)
    assert ev.usable


def test_all_recommendation_lists_included_basics_kept(tmp_path):
    lists = [
        {
            "tag": "newcards",
            "header": "New Cards",
            "cardviews": [view("Smaug, Wicked Worm", 100, 1000)],
        },
        {
            "tag": "highsynergycards",
            "header": "High Synergy Cards",
            "cardviews": [view("Dockside Extortionist", 400, 1000)],
        },
        {"tag": "lands", "header": "Lands", "cardviews": [view("Forest", 950, 1000)]},
        {
            "tag": "planeswalkers",
            "header": "Planeswalkers",
            "cardviews": [view("Chandra, Torch of Defiance", 120, 1000)],
        },
        {
            "tag": "tokens",
            "header": "Tokens",
            "cardviews": [view("Treasure Token", 900, 1000)],
        },
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )

    # Planeswalkers are real cards; tokens are not.
    assert set(ev.inclusion) == {
        "Smaug, Wicked Worm",
        "Dockside Extortionist",
        "Forest",
        "Chandra, Torch of Defiance",
    }
    assert any("non-deck recommendation lists ignored" in n for n in ev.limitations)


def test_commander_excluded_and_names_deduped_by_max_rate(tmp_path):
    lists = [
        {
            "tag": "topcards",
            "header": "Top Cards",
            "cardviews": [
                view("Sol Ring", 900, 1000, synergy=0.01),
                view("Korvold, Fae-Cursed King", 1000, 1000),
            ],
        },
        {
            "tag": "manaartifacts",
            "header": "Mana Artifacts",
            "cardviews": [view("Sol Ring", 950, 1000, synergy=0.03)],
        },
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )

    assert "Korvold, Fae-Cursed King" not in ev.inclusion
    assert ev.inclusion["Sol Ring"] == pytest.approx(0.95)  # max, not summed
    assert ev.synergy["Sol Ring"] == pytest.approx(0.03)


def test_rates_come_from_deck_counts_not_synergy(tmp_path):
    lists = [
        {
            "tag": "topcards",
            "header": "Top Cards",
            "cardviews": [view("Mayhem Devil", 300, 1000, synergy=0.95)],
        }
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )
    assert ev.inclusion["Mayhem Devil"] == pytest.approx(0.3)


def test_legacy_inclusion_percent_supported(tmp_path):
    entry = {"name": "Mayhem Devil", "inclusion": 62.5, "potential_decks": 1000}
    lists = [
        {
            "tag": "topcards",
            "header": "Top Cards",
            "cardviews": [view("Sol Ring", 900, 1000), entry],
        }
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )
    assert ev.inclusion["Mayhem Devil"] == pytest.approx(0.625)


# --- validation -----------------------------------------------------------


def test_mismatched_commander_identity_is_unavailable(tmp_path):
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                commander="Prosper, Tome-Bound"
            )
        },
    )
    assert ev.status == "unavailable"
    assert ev.inclusion == {}
    assert ev.limitations


def test_cedh_never_falls_back_to_general(tmp_path):
    general_url = source_url_for("kinnan-bonder-prodigy", "general")
    cedh_url = source_url_for("kinnan-bonder-prodigy", "cedh")
    calls = []
    ev = load_selection_evidence(
        {"name": "Kinnan, Bonder Prodigy"},
        5,
        tmp_path,
        # cEDH url 404s, general url would parse fine if we fell back.
        fetch=fake_fetch({general_url: payload("Kinnan, Bonder Prodigy")}, calls),
        now=NOW,
    )
    assert ev.status == "unavailable"
    assert ev.cohort == "cedh"
    assert ev.sample_size == 0
    assert calls and all(c == cedh_url for c in calls)


def test_general_cohort_rejects_cedh_page(tmp_path):
    """A redirect that serves the cEDH page must not be read as general."""
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(cohort="cedh")
        },
    )
    assert ev.status == "unavailable"


def test_cedh_cohort_parses_cedh_page(tmp_path):
    cedh_url = source_url_for("kinnan-bonder-prodigy", "cedh")
    ev = load_selection_evidence(
        {"name": "Kinnan, Bonder Prodigy"},
        5,
        tmp_path,
        fetch=fake_fetch({cedh_url: payload("Kinnan, Bonder Prodigy", cohort="cedh")}),
        now=NOW,
    )
    assert ev.status == "available"
    assert ev.cohort == "cedh"
    assert ev.source_url == cedh_url


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "Bad", "num_decks": float("nan"), "potential_decks": 1000},
        {"name": "Bad", "num_decks": float("inf"), "potential_decks": 1000},
        {"name": "Bad", "num_decks": 1500, "potential_decks": 1000},
        {"name": "Bad", "num_decks": -5, "potential_decks": 1000},
        {"name": "Bad", "num_decks": 10, "potential_decks": 0},
        {"name": "Bad", "num_decks": 10, "potential_decks": "many"},
        {"name": "", "num_decks": 10, "potential_decks": 1000},
        {"num_decks": 10, "potential_decks": 1000},
    ],
)
def test_non_finite_or_out_of_range_entries_are_dropped(tmp_path, bad):
    lists = [
        {
            "tag": "topcards",
            "header": "Top Cards",
            "cardviews": [view("Sol Ring", 900, 1000), bad],
        }
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )
    assert ev.status == "available"
    assert set(ev.inclusion) == {"Sol Ring"}
    assert ev.sample_size == 1000


def test_out_of_range_synergy_dropped_but_inclusion_kept(tmp_path):
    lists = [
        {
            "tag": "topcards",
            "header": "Top Cards",
            "cardviews": [
                view("Sol Ring", 900, 1000, synergy=42.0),
                view("Mayhem Devil", 800, 1000, synergy=float("nan")),
            ],
        }
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )
    assert ev.synergy == {}
    assert set(ev.inclusion) == {"Sol Ring", "Mayhem Devil"}


def test_implausible_composition_counts_dropped(tmp_path):
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                land=34, creature=-3, instant=float("inf"), sorcery=5000
            )
        },
    )
    assert ev.composition == {"land": 34.0, "basic": 12.0}


def test_zero_sample_is_unavailable(tmp_path):
    lists = [
        {
            "tag": "topcards",
            "header": "Top Cards",
            "cardviews": [view("Sol Ring", 0, 0)],
        }
    ]
    ev = load(
        cache_dir=tmp_path,
        mapping={
            source_url_for("korvold-fae-cursed-king", "general"): payload(
                cardlists=lists
            )
        },
    )
    assert ev.status == "unavailable"
    assert ev.sample_size == 0


@pytest.mark.parametrize(
    "body",
    [
        {"header": "Korvold, Fae-Cursed King (Commander)"},
        {"header": "Korvold, Fae-Cursed King (Commander)", "container": {}},
        {
            "header": "Korvold, Fae-Cursed King (Commander)",
            "container": {"json_dict": {"cardlists": []}},
        },
        [],
        "nope",
    ],
)
def test_malformed_payloads_are_unavailable(tmp_path, body):
    ev = load(
        cache_dir=tmp_path,
        mapping={source_url_for("korvold-fae-cursed-king", "general"): body},
    )
    assert ev.status == "unavailable"


def test_parse_payload_is_directly_testable():
    size, inclusion, synergy, composition, limits = parse_payload(
        payload(), "Korvold, Fae-Cursed King", "general"
    )
    assert size == 1000
    assert inclusion and synergy and composition and limits


# --- transport failures ---------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(404, b""),
        HttpResponse(500, b""),
        HttpResponse(200, b"{not json"),
        HttpResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1)),
        FetchError("connection reset"),
        TimeoutError("timed out"),
    ],
)
def test_transport_failures_return_unavailable_without_raising(tmp_path, response):
    ev = load(
        cache_dir=tmp_path,
        mapping={source_url_for("korvold-fae-cursed-king", "general"): response},
    )
    assert ev.status == "unavailable"
    assert ev.inclusion == {} and ev.sample_size == 0
    assert ev.limitations


def test_missing_commander_name_is_unavailable(tmp_path):
    assert (
        load_selection_evidence({}, 3, tmp_path, fetch=fake_fetch({}), now=NOW).status
        == "unavailable"
    )
    assert (
        load_selection_evidence(
            {"name": "!!!"}, 3, tmp_path, fetch=fake_fetch({}), now=NOW
        ).status
        == "unavailable"
    )


def test_at_most_two_requests_per_load(tmp_path):
    calls = []
    url = source_url_for("korvold-fae-cursed-king", "general")
    load_selection_evidence(
        KORVOLD,
        3,
        tmp_path,
        fetch=fake_fetch({url: FetchError("boom")}, calls),
        now=NOW,
    )
    assert len(calls) == 2


def test_client_errors_are_not_retried(tmp_path):
    calls = []
    url = source_url_for("korvold-fae-cursed-king", "general")
    load_selection_evidence(
        KORVOLD,
        3,
        tmp_path,
        fetch=fake_fetch({url: HttpResponse(404, b"")}, calls),
        now=NOW,
    )
    assert len(calls) == 1


# --- cache ----------------------------------------------------------------


def test_fresh_cache_avoids_second_request(tmp_path):
    url = source_url_for("korvold-fae-cursed-king", "general")
    calls = []
    fetch = fake_fetch({url: payload()}, calls)
    first = load_selection_evidence(KORVOLD, 3, tmp_path, fetch=fetch, now=NOW)
    later = NOW + timedelta(days=FRESH_DAYS - 1)
    second = load_selection_evidence(KORVOLD, 3, tmp_path, fetch=fetch, now=later)

    assert len(calls) == 1
    assert second.status == "available"
    assert second.retrieved_at == NOW
    assert second.inclusion == first.inclusion


def test_cache_is_keyed_by_commander_cohort_and_version(tmp_path):
    general = cache_path(tmp_path, "korvold-fae-cursed-king", "general")
    cedh = cache_path(tmp_path, "korvold-fae-cursed-king", "cedh")
    other = cache_path(tmp_path, "prosper-tome-bound", "general")
    assert general != cedh != other
    assert general.parent.name == VERSION

    url = source_url_for("korvold-fae-cursed-king", "general")
    load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: payload()}), now=NOW
    )
    assert general.exists() and not cedh.exists()
    record = json.loads(general.read_text())
    assert record["version"] == VERSION and record["cohort"] == "general"
    assert "payload" in record  # public json only
    assert not list(general.parent.glob("*.tmp"))


def test_stale_cache_is_flagged_when_refresh_fails(tmp_path, caplog):
    url = source_url_for("korvold-fae-cursed-king", "general")
    load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: payload()}), now=NOW
    )

    later = NOW + timedelta(days=FRESH_DAYS + 1)
    with caplog.at_level("WARNING"):
        ev = load_selection_evidence(
            KORVOLD,
            3,
            tmp_path,
            fetch=fake_fetch({url: FetchError("offline")}),
            now=later,
        )

    assert ev.status == "stale"
    assert ev.retrieved_at == NOW
    assert ev.inclusion  # still usable, but visibly dated
    assert ev.limitations[0].startswith("STALE:")
    assert "stale selection evidence" in caplog.text


def test_refresh_false_never_fetches(tmp_path):
    url = source_url_for("korvold-fae-cursed-king", "general")
    calls = []
    load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: payload()}), now=NOW
    )
    later = NOW + timedelta(days=FRESH_DAYS + 1)
    ev = load_selection_evidence(
        KORVOLD,
        3,
        tmp_path,
        refresh=False,
        fetch=fake_fetch({url: payload()}, calls),
        now=later,
    )
    assert calls == []
    assert ev.status == "stale"


def test_refresh_false_without_cache_is_unavailable(tmp_path):
    ev = load_selection_evidence(
        KORVOLD, 3, tmp_path, refresh=False, fetch=fake_fetch({}), now=NOW
    )
    assert ev.status == "unavailable"


def test_failed_refresh_does_not_corrupt_valid_cache(tmp_path):
    url = source_url_for("korvold-fae-cursed-king", "general")
    load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: payload()}), now=NOW
    )
    path = cache_path(tmp_path, "korvold-fae-cursed-king", "general")
    before = path.read_text()

    later = NOW + timedelta(days=FRESH_DAYS + 1)
    for bad in (
        HttpResponse(200, b"{broken"),
        HttpResponse(500, b""),
        payload(commander="Prosper, Tome-Bound"),
    ):
        load_selection_evidence(
            KORVOLD, 3, tmp_path, fetch=fake_fetch({url: bad}), now=later
        )
        assert path.read_text() == before


def test_corrupt_cache_is_ignored_and_replaced(tmp_path):
    path = cache_path(tmp_path, "korvold-fae-cursed-king", "general")
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    url = source_url_for("korvold-fae-cursed-king", "general")

    ev = load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: payload()}), now=NOW
    )
    assert ev.status == "available"
    assert json.loads(path.read_text())["version"] == VERSION


def test_cache_written_under_a_different_version_is_ignored(tmp_path):
    path = cache_path(tmp_path, "korvold-fae-cursed-king", "general")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": "selection-evidence.v0",
                "slug": "korvold-fae-cursed-king",
                "cohort": "general",
                "retrieved_at": NOW.isoformat(),
                "payload": payload(),
            }
        )
    )
    ev = load_selection_evidence(
        KORVOLD, 3, tmp_path, refresh=False, fetch=fake_fetch({}), now=NOW
    )
    assert ev.status == "unavailable"


def test_successful_refresh_replaces_stale_cache(tmp_path):
    url = source_url_for("korvold-fae-cursed-king", "general")
    load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: payload()}), now=NOW
    )
    later = NOW + timedelta(days=FRESH_DAYS + 1)
    fresh = payload(
        cardlists=[
            {
                "tag": "topcards",
                "header": "Top Cards",
                "cardviews": [view("Sol Ring", 990, 1200)],
            }
        ]
    )
    ev = load_selection_evidence(
        KORVOLD, 3, tmp_path, fetch=fake_fetch({url: fresh}), now=later
    )
    assert ev.status == "available"
    assert ev.retrieved_at == later
    assert ev.sample_size == 1200
    assert set(ev.inclusion) == {"Sol Ring"}


# --- provenance -----------------------------------------------------------


def test_result_is_serialisable_provenance(tmp_path):
    url = source_url_for("korvold-fae-cursed-king", "general")
    ev = load(cache_dir=tmp_path, mapping={url: payload()})
    dumped = json.loads(ev.model_dump_json())
    assert dumped["version"] == VERSION
    assert dumped["source_url"] == url
    assert dumped["status"] == "available"
    assert dumped["sample_size"] == 1000


def test_no_win_rate_or_causal_field_exposed():
    fields = set(SelectionEvidence.model_fields)
    assert not any(
        bad in name.lower()
        for name in fields
        for bad in ("winrate", "win_rate", "equity", "causal")
    )

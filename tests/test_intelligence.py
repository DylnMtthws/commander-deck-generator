"""Independent regressions for the observed Aesi mechanical failures."""

import json

import numpy as np
import pytest

from sabermetrics.intelligence.cards import annotate, facts_for, usable_land
from sabermetrics.intelligence.simulation import (
    compiled_land,
    paired_improvement,
    run_probe,
)
from sabermetrics.intelligence.strategy import assess_plan, make_plan, reserve_plan


def card(name, text="", types="Creature", **kwargs):
    return {
        "id": name,
        "name": name,
        "oracle_text": text,
        "type_line": types,
        "price_usd": 1.0,
        **kwargs,
    }


def test_prerequisites_not_keyword_matching():
    paliano = card(
        "Draft City",
        "{T}: Add one mana of any color chosen as you drafted cards named Draft City.",
        "Land",
    )
    assert facts_for(paliano).exclusion
    gate = card(
        "Gate",
        "{T}: Add {C}.\n{T}: Add one mana of any color that a Gate you control could produce.",
        "Land — Gate",
    )
    assert not usable_land(gate, ["G", "U"])
    tutor = card(
        "Search",
        "Choose target creature. Search your library for a creature card with the same name as that creature, put it onto the battlefield tapped, then shuffle.",
        "Instant",
    )
    assert facts_for(tutor).exclusion
    recursion = annotate(
        card(
            "Protector",
            "When this creature is turned face up, return target card from your graveyard to your hand.",
            role_tags='["removal"]',
        )
    )
    assert "removal" not in json.loads(recursion["role_tags"])
    assert "recursion" in json.loads(recursion["role_tags"])
    transform = annotate(
        card(
            "Student",
            "Flying\nWhenever this creature attacks, investigate. // −3: Return target instant card from your graveyard to your hand. If it is green, add one mana of any color.",
            "Creature // Planeswalker",
            role_tags='["ramp"]',
        )
    )
    assert "ramp" not in json.loads(transform["role_tags"])


def test_plan_reserves_affordable_functional_package():
    plan = make_plan(
        card(
            "Commander",
            "Landfall — Whenever a land you control enters, you may draw a card.",
        ),
        "Landfall",
    )
    pool = [
        card(
            "Ramp " + str(i),
            "Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.",
            "Sorcery",
        )
        for i in range(3)
    ]
    pool += [
        card(
            "Payoff " + str(i),
            "Landfall — Whenever a land you control enters, create a 1/1 green creature token and draw a card.",
        )
        for i in range(6)
    ]
    pool += [
        card("Explorer", "You may play an additional land on each of your turns."),
        card("Recursor", "You may play lands from your graveyard."),
    ]
    reserved = reserve_plan(plan, pool, 200)
    assert assess_plan(plan, reserved)["status"] == "satisfied"
    assert sum(c["price_usd"] for c in reserved) <= 60
    assert len({c["name"] for c in reserved}) == len(reserved)
    poor = make_plan(card("Commander"), "Landfall")
    assert assess_plan(poor, reserve_plan(poor, pool, 1))["status"] == "partial"


def test_probe_compiler_refuses_unsupported_land_mechanics():
    with pytest.raises(ValueError):
        compiled_land(
            card(
                "Bounce",
                "{T}: Add {G}.\nWhen this land enters, return a land you control to its owner's hand.",
                "Land",
            )
        )
    with pytest.raises(ValueError):
        compiled_land(
            card(
                "Check",
                "This land enters tapped unless you control a Forest.\n{T}: Add {G} or {U}.",
                "Land",
            )
        )
    assert (
        compiled_land(
            card("Simple", "This land enters tapped.\n{T}: Add {G} or {U}.", "Land")
        )["colors"]
        == 18
    )


def test_no_simulator_is_not_zero_or_a_win_claim(monkeypatch):
    monkeypatch.delenv("SABER_RESOURCE_PROBE_BIN", raising=False)
    monkeypatch.delenv("SABER_RESOURCE_PROBE_URL", raising=False)
    result = run_probe([], card("Commander"))
    assert result["status"] == "unavailable"
    assert "result" not in result


def test_paired_interval_does_not_claim_zero_uncertainty():
    a = {"result": {"cast_samples": [0] * 2000}}
    b = {"result": {"cast_samples": [1] * 2000}}
    r = paired_improvement(a, b)
    assert r["improved"]
    assert r["interval"][0] < 1
    assert not paired_improvement(a, a)["improved"]


def test_native_cpp_probe_when_explicitly_enabled(monkeypatch):
    import os

    binary = os.getenv("TEST_RESOURCE_PROBE_BIN")
    if not binary:
        pytest.skip("native C++ integration enabled explicitly")
    cards = [
        card("Forest", types="Basic Land — Forest", price_usd=0) for _ in range(99)
    ]
    commander = card("Commander", mana_cost="{G}", color_identity=["G"])
    result = run_probe(cards, commander, games=100, binary=binary)
    assert result["status"] == "measured", result
    assert result["result"]["commander_cast_count"] == 100
    assert result["result"]["lands_mean"] == 6
    assert "Not a win rate" in result["scope"]


def test_accepted_swaps_use_current_objective(monkeypatch):
    """A→B improves, but C→D is better only than the stale pass-start score."""
    import sabermetrics.pipeline.greedy_optimizer as opt
    from sabermetrics.analytics.synergy_matrix import SynergyMatrix
    from sabermetrics.pipeline.slot_assigner import SlotAssignment

    def c(n):
        return card(n, price_usd=0, role_tags='["utility"]')

    a, b, c1, d = [c(n) for n in "ABCD"]
    deck = [
        SlotAssignment(card=a, slot_role="utility", score=0),
        SlotAssignment(card=c1, slot_role="utility", score=0),
    ]
    scores = {
        frozenset("AC"): 0.0,
        frozenset("BC"): 10.0,
        frozenset("BD"): 5.0,
        frozenset("AD"): -1.0,
    }
    monkeypatch.setattr(
        opt,
        "deck_objective",
        lambda cards, *a, **kw: scores.get(frozenset(c["name"] for c in cards), -10.0),
    )
    synergy = SynergyMatrix(
        np.zeros((4, 4), dtype=np.float32),
        dict(zip("ABCD", range(4))),
        dict(enumerate("ABCD")),
    )
    out, _ = opt.swap_refine(deck, [a, b, c1, d], synergy, {}, budget=1, max_passes=1)
    assert {a.card["name"] for a in out} == {"B", "C"}


def test_land_access_and_reminder_text_do_not_satisfy_ramp():
    fetch = card(
        "Fetch",
        "{T}, Sacrifice this land: Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.",
        "Land",
    )
    assert "land_ramp" not in facts_for(fetch).capabilities
    assert "land_access" in facts_for(fetch).capabilities
    token = card(
        "Token maker",
        'Create a Lander token. (It has "{2}, {T}, Sacrifice this token: Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.")',
    )
    assert "ramp" not in facts_for(token).roles
    energy = card(
        "Energy",
        "Landfall — Whenever a land you control enters, you get {E}.\nPay eight {E}: Create a 6/6 creature token.",
    )
    assert "landfall_tokens" not in facts_for(energy).capabilities
    clue = card(
        "Clues",
        'Landfall — Whenever a land you control enters, investigate. (Create a Clue token. It has "Draw a card.")',
    )
    assert "landfall_cards" in facts_for(clue).capabilities
    assert "landfall_board" not in facts_for(clue).capabilities


def test_prepared_facts_are_optional_versioned_and_database_safe(tmp_path, monkeypatch):
    import sqlite3

    from sabermetrics.intelligence.cards import fact_key
    from sabermetrics.runtime.prepare_card_facts import prepare

    db = tmp_path / "cards.db"
    output = tmp_path / "facts.json"
    c = card("Engine", "You may play an additional land on each of your turns.")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE cards(id TEXT, oracle_id TEXT, name TEXT, oracle_text TEXT, type_line TEXT)"
        )
        conn.execute(
            "INSERT INTO cards VALUES(?,?,?,?,?)",
            ("1", "a", c["name"], c["oracle_text"], c["type_line"]),
        )
    before = db.read_bytes()
    expected = facts_for(c)
    receipt = prepare(db, output)
    assert receipt["compiled_shapes"] == 1
    assert db.read_bytes() == before
    with pytest.raises(ValueError):
        prepare(db, db)
    monkeypatch.setenv("SABER_CARD_FACTS", str(output))
    assert facts_for(c) == expected
    data = json.loads(output.read_text())
    data["entries"][fact_key(c)]["oracle_hash"] = "stale"
    data["entries"][fact_key(c)]["roles"] = ["wrong"]
    output.write_text(json.dumps(data))
    assert facts_for(c) == expected
    for raw in ("[]", "{", '{"version":"old","entries":{}}'):
        output.write_text(raw)
        assert facts_for(c) == expected


@pytest.mark.parametrize("fault", ["hash", "samples", "scenario", "metric", "shape"])
def test_invalid_probe_results_never_become_measurements(monkeypatch, fault):
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace

    import sabermetrics.intelligence.simulation as sim

    def fake_run(argv, **kwargs):
        req = json.loads(Path(argv[-1]).read_text())
        canonical = json.dumps(
            req, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        payload = dict(
            schema_version="resource-probe-result.v1",
            scenario="commander-land-engine-only.v1",
            deck_identity=req["deck_identity"],
            simulation_input_sha256="sha256:"
            + hashlib.sha256(("resource-probe.v1\n" + canonical).encode()).hexdigest(),
            games=10,
            turns=6,
            cast_samples=[1] * 10,
            commander_cast_count=10,
            lands_mean=6,
            commander_draws_mean=0,
        )
        if fault == "hash":
            payload["simulation_input_sha256"] = "bad"
        if fault == "samples":
            payload["cast_samples"] = [1]
        if fault == "scenario":
            payload["scenario"] = "invented"
        if fault == "metric":
            payload["lands_mean"] = float("nan")
        if fault == "shape":
            payload = []
        return SimpleNamespace(stdout=json.dumps(payload).encode())

    monkeypatch.setattr(sim.subprocess, "run", fake_run)
    result = sim.run_probe(
        [card("Forest", types="Basic Land — Forest")] * 99,
        card("Commander", mana_cost="{G}"),
        games=10,
        binary="fake",
    )
    assert result["status"] == "unavailable"
    assert "result" not in result


def test_mana_search_requires_held_out_confirmation_and_keeps_spells(monkeypatch):
    from copy import deepcopy

    import sabermetrics.intelligence.alternatives as alt
    from sabermetrics.pipeline.slot_assigner import SlotAssignment

    assignments = [
        SlotAssignment(
            card=card("Forest", types="Basic Land — Forest"), slot_role="land", score=0
        )
        for _ in range(38)
    ] + [
        SlotAssignment(card=card(f"Spell {i}"), slot_role="utility", score=0)
        for i in range(61)
    ]
    original = deepcopy(assignments)
    calls = []

    def probe(cards, commander, games=2000, seed=12345, **kwargs):
        calls.append((games, seed))
        changed = any(c["name"] == "Island" for c in cards)
        # Screening looks great; fresh confirmation does not support it.
        success = int(changed and seed == 12345)
        return {
            "status": "measured",
            "scope": "test scenario",
            "result": {"cast_samples": [success] * games, "games": games},
        }

    monkeypatch.setattr(alt, "run_probe", probe)
    result, evidence = alt.compare_mana_variants(
        assignments, card("Commander", color_identity=["G", "U"])
    )
    assert result == original
    assert assignments == original
    assert calls[-2:] == [(5000, 837291), (5000, 837291)]
    assert not evidence["confirmation"]["improved"]
    assert evidence["selected"] == "baseline"

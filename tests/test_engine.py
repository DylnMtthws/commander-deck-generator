"""Engine package integration: reservation, review, persist, and hard gates.

Policy helpers live in test_intent.py / test_quality.py. These tests drive
DeckBuilder so the builder cannot ignore the contract.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sabermetrics.models.llm_responses import CardFitResponse, DeckSynthesisResponse
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest
from sabermetrics.pipeline.intent import is_copy_on_entry_creature
from sabermetrics.pipeline.slot_assigner import SlotAssignment
from sabermetrics.pipeline.trace import GenerationTracer

FIXTURE = Path(__file__).parent / "fixtures/cards/aang_quality.json"
CLONE_NAMES = {
    "Spark Double",
    "Sakashima of a Thousand Faces",
    "Clever Impersonator",
    "Clone",
}


def public_cards():
    return json.loads(FIXTURE.read_text())["cards"]


def _seed_db(path: Path, *, clone_price: float = 5.0, filler_price: float = 1.0) -> str:
    from scripts.setup_db import setup_database

    setup_database(path)
    records = public_cards()
    commander_id = records[0]["id"]
    with sqlite3.connect(path) as conn:
        for raw in records:
            faces = raw.get("card_faces") or []
            conn.execute(
                "INSERT INTO cards (id,oracle_id,name,mana_cost,cmc,type_line,"
                "oracle_text,color_identity,keywords,is_legal_commander,"
                "is_legal_in_99,set_code,rarity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    raw["id"],
                    raw["oracle_id"],
                    raw["name"],
                    raw.get("mana_cost")
                    or (faces[0].get("mana_cost", "") if faces else ""),
                    raw["cmc"],
                    raw["type_line"],
                    raw.get("oracle_text")
                    or " // ".join(f["oracle_text"] for f in faces),
                    json.dumps(raw["color_identity"]),
                    json.dumps(raw["keywords"]),
                    int(raw["id"] == commander_id),
                    1,
                    raw["set"],
                    raw["rarity"],
                ),
            )
            price = clone_price if raw["name"] in CLONE_NAMES else 5.0
            conn.execute(
                "INSERT INTO card_prices(card_id,price_usd,snapshot_date) VALUES (?,?,?)",
                (raw["id"], price, "2026-09-12"),
            )
        conn.execute(
            "INSERT INTO cards (id,oracle_id,name,mana_cost,cmc,type_line,"
            "oracle_text,color_identity,keywords,is_legal_commander,"
            "is_legal_in_99,set_code,rarity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "green-cmdr",
                "green-cmdr-oracle",
                "Llanowar Test Guide",
                "{G}",
                1,
                "Legendary Creature — Elf Druid",
                "{T}: Add {G}.",
                '["G"]',
                "[]",
                1,
                1,
                "test",
                "rare",
            ),
        )
        conn.execute(
            "INSERT INTO card_prices(card_id,price_usd,snapshot_date) VALUES (?,?,?)",
            ("green-cmdr", 1.0, "2026-09-12"),
        )
        for i in range(90):
            oracle = [
                "Flying. When this creature enters, draw a card.",
                "When this creature enters, search your library for a basic land card, put it onto the battlefield tapped, then shuffle.",
                "When this creature enters, destroy target artifact.",
            ][i % 3]
            conn.execute(
                "INSERT INTO cards (id,oracle_id,name,mana_cost,cmc,type_line,"
                "oracle_text,color_identity,keywords,is_legal_commander,"
                "is_legal_in_99,set_code,rarity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"review-{i}",
                    f"review-oracle-{i}",
                    f"Review Value Creature {i}",
                    "{2}{G}",
                    3,
                    "Creature — Elf",
                    oracle,
                    '["G"]',
                    "[]",
                    0,
                    1,
                    "test",
                    "common",
                ),
            )
            conn.execute(
                "INSERT INTO card_prices(card_id,price_usd,snapshot_date) VALUES (?,?,?)",
                (f"review-{i}", filler_price, "2026-09-12"),
            )
        conn.commit()
    return commander_id


def _patch_builder_io(monkeypatch, canned_profile, commander_id, colors, captured=None):
    profile = canned_profile(commander_id, colors)
    monkeypatch.setattr(
        "sabermetrics.reasoning.profiler.ProfileManager.generate_profile",
        lambda *a, **k: profile,
    )
    fake_model = SimpleNamespace(
        encode=lambda texts, **kw: (
            np.ones(8) if isinstance(texts, str) else np.ones((len(texts), 8))
        )
    )
    monkeypatch.setattr(
        "sabermetrics.analytics.embeddings.EmbeddingService._load_model",
        lambda *a: fake_model,
    )
    monkeypatch.setattr(
        "sabermetrics.analytics.synergy_matrix._compute_embedding_matrix",
        lambda cards: (np.zeros((len(cards), len(cards)), dtype=np.float32), False),
    )
    monkeypatch.setattr(
        "sabermetrics.reasoning.fit.FitScorer.score_cards_batch",
        lambda self, cards, **kw: [
            (
                card,
                CardFitResponse(
                    fit_score=7, reasoning="Synthetic review", slot_role="utility"
                ),
            )
            for card in cards
        ],
    )

    def fake_synthesize(
        self, profile_summary, deck_cards_with_reasoning, bracket, bracket_reasoning
    ):
        if captured is not None:
            captured["cards"] = deck_cards_with_reasoning
            captured["bracket_reasoning"] = bracket_reasoning
            captured["bracket"] = bracket
        return (
            DeckSynthesisResponse(
                game_plan="Play the cards in the 99.",
                key_synergies=["Use copy-on-entry creatures if present."],
                weaknesses=["Heuristic bracket is not ground truth."],
                suggested_play_pattern="Sequence fair spells.",
            ),
            0.0,
        )

    monkeypatch.setattr(
        "sabermetrics.reasoning.synthesis.DeckSynthesizer.synthesize",
        fake_synthesize,
    )
    return profile


def test_clone_intent_survives_full_builder_and_persists_warnings(
    tmp_path, monkeypatch, canned_profile
):
    path = tmp_path / "engine-aang.db"
    commander_id = _seed_db(path)
    captured: dict = {}
    _patch_builder_io(
        monkeypatch, canned_profile, commander_id, ["G", "W", "U"], captured
    )
    stages = []
    result = DeckBuilder(
        path, progress_callback=lambda stage, percent: stages.append((stage, percent))
    ).build(
        DeckBuildRequest(
            commander_id=commander_id,
            budget_usd=1000,
            power_target=4,
            user_intent="4 mana copy creatures that keep the Aang triggered ability going almost infinitely",
        )
    )
    names = [c.card.name for c in result.deck.cards]
    assert len(names) == 99
    assert len(set(names) & CLONE_NAMES) >= 2
    assert result.pipeline_metrics["engine_status"] == "satisfied"
    assert result.deck.composition.total_price_usd <= 1000
    assert stages[-1] == ("completed", 100)
    stage_names = [s for s, _ in stages]
    for required in (
        "validate",
        "profile",
        "filter",
        "score",
        "template",
        "infrastructure",
        "optimize",
        "review",
        "narrative",
        "persist",
        "completed",
    ):
        assert required in stage_names

    facts = captured["cards"]
    clone_facts = [c for c in facts if c["name"] in CLONE_NAMES]
    assert clone_facts
    for fact in clone_facts:
        assert fact.get("oracle_text")
        assert "copy" in fact["oracle_text"].lower()
        assert fact.get("mana_value") == 4.0
        assert "creature" in (fact.get("type") or "").lower()
        assert fact.get("role")
    assert "heuristic" in captured["bracket_reasoning"].lower()

    with sqlite3.connect(path) as conn:
        saved = conn.execute(
            "SELECT rationale FROM generated_decks WHERE id=?", (result.deck.id,)
        ).fetchone()
    rationale = json.loads(saved[0])
    assert "quality_warnings" in rationale
    assert any(w["code"] == "bracket_estimate" for w in rationale["quality_warnings"])
    assert "stage_timings" in rationale
    assert rationale["stage_timings"].get("filter", 0) >= 0
    assert "stage_counts" in rationale
    assert rationale["stage_counts"].get("engine_reserved", 0) >= 2
    assert rationale["engine"]["status"] == "satisfied"
    assert not any(
        w["code"] in {"engine_unavailable", "engine_unsatisfied", "intent_unverified"}
        for w in rationale["quality_warnings"]
    )


def test_unaffordable_engine_is_infeasible_not_fulfilled(
    tmp_path, monkeypatch, canned_profile
):
    path = tmp_path / "engine-expensive.db"
    commander_id = _seed_db(path, clone_price=200.0, filler_price=1.0)
    _patch_builder_io(monkeypatch, canned_profile, commander_id, ["G", "W", "U"])
    result = DeckBuilder(path).build(
        DeckBuildRequest(
            commander_id=commander_id,
            budget_usd=50,
            power_target=4,
            user_intent="4 mana copy creatures",
        )
    )
    assert len(result.deck.cards) == 99
    assert result.pipeline_metrics["engine_status"] == "infeasible"
    names = {c.card.name for c in result.deck.cards}
    assert names.isdisjoint(CLONE_NAMES)
    assert any(w["code"] == "engine_unavailable" for w in result.quality_warnings)
    with sqlite3.connect(path) as conn:
        rationale = json.loads(
            conn.execute(
                "SELECT rationale FROM generated_decks WHERE id=?", (result.deck.id,)
            ).fetchone()[0]
        )
    assert any(w["code"] == "engine_unavailable" for w in rationale["quality_warnings"])
    assert rationale["engine"]["status"] == "infeasible"
    assert "fulfilled" not in json.dumps(rationale["quality_warnings"]).lower()


def test_no_intent_other_commander_does_not_require_clones(
    tmp_path, monkeypatch, canned_profile
):
    path = tmp_path / "engine-green.db"
    _seed_db(path)
    _patch_builder_io(monkeypatch, canned_profile, "green-cmdr", ["G"])
    result = DeckBuilder(path).build(
        DeckBuildRequest(
            commander_id="green-cmdr",
            budget_usd=200,
            power_target=3,
            user_intent=None,
        )
    )
    assert len(result.deck.cards) == 99
    assert result.pipeline_metrics["engine_status"] == "none"
    assert all(set(c.card.color_identity) <= {"G"} for c in result.deck.cards)
    assert not any(
        w["code"] in {"engine_unavailable", "engine_unsatisfied"}
        for w in result.quality_warnings
    )


def test_hostile_reviewer_cannot_strip_engine_package(tmp_path, monkeypatch):
    """Even if the vet scores every reviewed card 1, protected clones stay."""
    import sabermetrics.reasoning.fit as fit_mod
    from sabermetrics.models.llm_responses import CardFitResponse as Fit

    class HostileScorer:
        def __init__(self, db_path):
            self.db_path = db_path

        def score_cards_batch(self, cards, **kwargs):
            return [
                (
                    card,
                    Fit(fit_score=1, reasoning="Hostile reject", slot_role="utility"),
                )
                for card in cards
            ]

    monkeypatch.setattr(fit_mod, "FitScorer", HostileScorer)

    spark = {
        "id": "spark",
        "name": "Spark Double",
        "type_line": "Creature — Illusion",
        "oracle_text": "You may have this creature enter as a copy of a creature you control.",
        "price_usd": 5.0,
        "cmc": 4.0,
        "color_identity": ["U"],
        "_cvar_score": 0.1,
    }
    filler = {
        "id": "filler",
        "name": "Filler Elf",
        "type_line": "Creature — Elf",
        "oracle_text": "When this creature enters, draw a card.",
        "price_usd": 1.0,
        "cmc": 3.0,
        "color_identity": ["G"],
        "_cvar_score": 0.9,
        "_empirical_inclusion": 0.5,
    }
    bait = {
        "id": "bait",
        "name": "Hostile Bait",
        "type_line": "Creature — Horror",
        "oracle_text": "Trample",
        "price_usd": 1.0,
        "cmc": 2.0,
        "color_identity": ["G"],
        "_cvar_score": 0.99,
        "_empirical_inclusion": 0.8,
    }
    builder = DeckBuilder(tmp_path / "unused.db")
    builder._tracer = GenerationTracer(generation_id="hostile")
    builder._engine_protect_names = {"Spark Double"}
    builder._build_profile_summary = lambda pr: "profile"
    builder._empirical = None
    deck = [
        SlotAssignment(card=spark, slot_role="utility", score=0.1),
        SlotAssignment(card=filler, slot_role="utility", score=0.2),
    ]
    profile_result = SimpleNamespace(
        profile=SimpleNamespace(
            strategic_profile=SimpleNamespace(primary_archetype="midrange"),
            card_analysis=SimpleNamespace(color_identity=["G", "U", "W"]),
        )
    )
    out, cost = builder._llm_safety_check(
        deck,
        [spark, filler, bait],
        synergy=None,
        role_targets=None,
        profile_result=profile_result,
        request=DeckBuildRequest(commander_id="x", budget_usd=200.0),
        n_weakest=99,
        protected_names={"Spark Double"},
    )
    names = [a.card["name"] for a in out]
    assert "Spark Double" in names
    assert cost >= 0
    assert is_copy_on_entry_creature(spark)


def test_review_exception_is_surfaced_not_hidden(tmp_path, monkeypatch):
    import sabermetrics.reasoning.fit as fit_mod

    class BoomScorer:
        def __init__(self, db_path):
            self.db_path = db_path

        def score_cards_batch(self, cards, **kwargs):
            raise RuntimeError("vet exploded")

    monkeypatch.setattr(fit_mod, "FitScorer", BoomScorer)
    builder = DeckBuilder(tmp_path / "unused.db")
    builder._tracer = GenerationTracer(generation_id="boom")
    builder._review_failed = False
    builder._build_profile_summary = lambda pr: "profile"
    builder._empirical = None
    deck = [
        SlotAssignment(
            card={
                "id": "a",
                "name": "Some Creature",
                "type_line": "Creature",
                "price_usd": 1.0,
            },
            slot_role="utility",
            score=0.4,
        )
    ]
    profile_result = SimpleNamespace(
        profile=SimpleNamespace(
            strategic_profile=SimpleNamespace(primary_archetype="midrange"),
            card_analysis=SimpleNamespace(color_identity=["G"]),
        )
    )
    with pytest.raises(RuntimeError, match="vet exploded"):
        builder._llm_safety_check(
            deck,
            [a.card for a in deck],
            synergy=None,
            role_targets=None,
            profile_result=profile_result,
            request=DeckBuildRequest(commander_id="x", budget_usd=200.0),
            n_weakest=99,
        )


def test_final_validation_failure_never_persists_deck(
    tmp_path, monkeypatch, canned_profile
):
    from sabermetrics.errors import FatalError

    path = tmp_path / "hard-failure.db"
    commander_id = _seed_db(path)
    _patch_builder_io(monkeypatch, canned_profile, commander_id, ["G", "W", "U"])
    original = DeckBuilder._enforce_legality

    def corrupt(self, *args, **kwargs):
        assignments = original(self, *args, **kwargs)
        assignments[0].card["price_usd"] = 10001
        return assignments

    monkeypatch.setattr(DeckBuilder, "_enforce_legality", corrupt)
    with pytest.raises(FatalError, match="exceeds budget"):
        DeckBuilder(path).build(
            DeckBuildRequest(commander_id=commander_id, budget_usd=1000)
        )
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generated_decks").fetchone()[0] == 0


def test_summary_failure_never_falls_back_to_untrusted_profile(
    tmp_path, monkeypatch, canned_profile
):
    path = tmp_path / "summary-failure.db"
    commander_id = _seed_db(path)
    profile = _patch_builder_io(
        monkeypatch, canned_profile, commander_id, ["G", "W", "U"]
    )
    profile.profile.strategic_profile.game_plan_summary = "Black Lotus wins instantly."

    def broken(*args, **kwargs):
        raise ValueError("synthetic rendering failure")

    monkeypatch.setattr(
        "sabermetrics.reasoning.synthesis.DeckSynthesizer.synthesize", broken
    )
    result = DeckBuilder(path).build(
        DeckBuildRequest(commander_id=commander_id, budget_usd=1000)
    )
    assert "Black Lotus" not in result.deck.narrative.model_dump_json()
    assert any(
        w["code"] == "signal_unavailable" and "narrative" in w["message"]
        for w in result.quality_warnings
    )


def test_stage_describes_running_work_and_persisted_timings(
    tmp_path, monkeypatch, canned_profile
):
    path = tmp_path / "progress.db"
    commander_id = _seed_db(path)
    _patch_builder_io(monkeypatch, canned_profile, commander_id, ["G", "W", "U"])
    stages = []
    original = DeckBuilder._acquire_profile

    def checked(self, *args, **kwargs):
        assert stages[-1] == "profile"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DeckBuilder, "_acquire_profile", checked)
    result = DeckBuilder(
        path, progress_callback=lambda stage, percent: stages.append(stage)
    ).build(DeckBuildRequest(commander_id=commander_id, budget_usd=1000))
    with sqlite3.connect(path) as conn:
        rationale = json.loads(
            conn.execute(
                "SELECT rationale FROM generated_decks WHERE id=?", (result.deck.id,)
            ).fetchone()[0]
        )
    assert {"profile", "optimize", "review", "persist"} <= set(
        rationale["stage_timings"]
    )
    assert all(seconds >= 0 for seconds in rationale["stage_timings"].values())

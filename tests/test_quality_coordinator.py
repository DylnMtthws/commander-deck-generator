"""Independent acceptance checks authored separately from Cursor implementation."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sabermetrics.models.card import Card
from sabermetrics.models.evidence import EvidencePackage
from sabermetrics.reasoning.profiler import ProfileManager, ProfileRequest
from sabermetrics.reasoning.synthesis import DeckSynthesizer

FIXTURE = Path(__file__).parent / "fixtures/cards/aang_quality.json"


def public_cards():
    return json.loads(FIXTURE.read_text())["cards"]


def test_model_cannot_choose_profile_identity_or_provenance(
    tmp_path, monkeypatch, canned_profile
):
    raw = public_cards()[0]
    faces = raw.get("card_faces") or []
    card = Card(
        id=raw["id"],
        oracle_id=raw["oracle_id"],
        name=raw["name"],
        mana_cost=raw.get("mana_cost") or faces[0]["mana_cost"],
        cmc=raw["cmc"],
        type_line=raw["type_line"],
        oracle_text=raw.get("oracle_text")
        or " // ".join(f["oracle_text"] for f in faces),
        color_identity=raw["color_identity"],
        keywords=raw["keywords"],
        is_legal_commander=True,
        is_legal_in_99=True,
        set_code=raw["set"],
        rarity=raw["rarity"],
        last_updated=datetime.now(UTC),
    )
    intent = "4 mana copy creatures"
    evidence = EvidencePackage(
        commander=card,
        rulings=[],
        reddit_threads=[],
        primer_articles=[],
        reference_chunks=[],
        user_intent=intent,
    )
    payload = canned_profile("made-up-slug", ["B"]).profile.model_dump(mode="json")
    payload.update(
        commander_name="Wrong name",
        generated_at="2025-04-09T00:00:00Z",
        set_version="UNF",
    )
    payload["sources"]["rules_chunks_referenced"] = ["CR invented"]
    payload["sources"]["articles_referenced"] = ["https://example.invalid/fabricated"]
    payload["user_intent"] = {"provided": False, "description": "different intent"}
    fake = SimpleNamespace(
        call_with_cache=lambda **kw: SimpleNamespace(
            content=json.dumps(payload), cost_usd=0.001
        )
    )
    monkeypatch.setattr(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance",
        lambda *a, **k: fake,
    )
    before = datetime.now(UTC)
    profile, _ = ProfileManager(tmp_path / "unused.db")._generate_via_llm(
        evidence, ProfileRequest(commander_id=card.id, user_intent=intent)
    )
    assert profile.commander_id == card.id
    assert profile.commander_name == card.name
    assert profile.set_version == card.set_code
    assert profile.generated_at.tzinfo is not None
    assert profile.generated_at >= before
    assert profile.card_analysis.mana_cost == card.mana_cost
    assert set(profile.card_analysis.color_identity) == set(card.color_identity)
    assert profile.sources.rules_chunks_referenced == []
    assert profile.sources.articles_referenced == []
    assert profile.user_intent.description == intent


def test_final_narrative_does_not_repeat_untrusted_profile_or_model_claims(
    tmp_path, monkeypatch
):
    cards = []
    for raw in public_cards():
        if raw["name"].startswith(("Brazen Borrower", "Taigam,", "Peregrine Drake")):
            faces = raw.get("card_faces") or []
            cards.append(
                {
                    "name": raw["name"],
                    "cmc": raw["cmc"],
                    "mana_value": raw["cmc"],
                    "type_line": raw["type_line"],
                    "slot_role": "utility",
                    "oracle_text": raw.get("oracle_text")
                    or " // ".join(f["oracle_text"] for f in faces),
                }
            )
    bad = {
        "game_plan": "Spark Double makes an infinite engine.",
        "key_synergies": [
            "Sakashima of a Thousand Faces is in this deck.",
            "Taigam grants extra combat phases.",
        ],
        "weaknesses": [],
        "suggested_play_pattern": "Bounce your Aang with Brazen Borrower.",
    }
    fake = SimpleNamespace(
        call_with_cache=lambda **kw: SimpleNamespace(
            content=json.dumps(bad), cost_usd=0.001
        )
    )
    monkeypatch.setattr(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance",
        lambda *a, **k: fake,
    )
    result, _ = DeckSynthesizer(tmp_path / "unused.db").synthesize(
        profile_summary="Spark Double and Sakashima provide infinite ETBs. Taigam grants extra combat phases.",
        deck_cards_with_reasoning=cards,
        bracket=4,
        bracket_reasoning="Requested, not validated",
    )
    text = result.model_dump_json().lower()
    assert "spark double" not in text
    assert "sakashima" not in text
    assert "extra combat" not in text
    assert "bounce your aang" not in text
    assert "infinite" not in text


def test_real_builder_preserves_clone_engine_through_selection(
    tmp_path, monkeypatch, canned_profile
):
    import sqlite3

    import numpy as np

    from sabermetrics.models.llm_responses import CardFitResponse
    from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest
    from scripts.setup_db import setup_database

    path = tmp_path / "synthetic-aang.db"
    setup_database(path)
    records = public_cards()
    commander_id = records[0]["id"]
    with sqlite3.connect(path) as conn:
        for raw in records:
            faces = raw.get("card_faces") or []
            conn.execute(
                "INSERT INTO cards (id,oracle_id,name,mana_cost,cmc,type_line,oracle_text,color_identity,keywords,is_legal_commander,is_legal_in_99,set_code,rarity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            conn.execute(
                "INSERT INTO card_prices(card_id,price_usd,snapshot_date) VALUES (?,?,?)",
                (raw["id"], 5.0, "2026-09-12"),
            )
        for i in range(90):
            # Synthetic value creatures deliberately compete with the real clone engine.
            oracle = [
                "Flying. When this creature enters, draw a card.",
                "When this creature enters, search your library for a basic land card, put it onto the battlefield tapped, then shuffle.",
                "When this creature enters, destroy target artifact.",
            ][i % 3]
            conn.execute(
                "INSERT INTO cards (id,oracle_id,name,mana_cost,cmc,type_line,oracle_text,color_identity,keywords,is_legal_commander,is_legal_in_99,set_code,rarity) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                (f"review-{i}", 1.0, "2026-09-12"),
            )
    profile = canned_profile(commander_id, ["G", "W", "U"])
    profile.profile.commander_name = records[0]["name"]
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
    cards = result.deck.cards
    assert len(cards) == 99
    names = [c.card.name for c in cards]
    eligible = {
        "Spark Double",
        "Sakashima of a Thousand Faces",
        "Clever Impersonator",
        "Clone",
    }
    assert len(set(names) & eligible) >= 2
    assert result.deck.composition.total_price_usd <= 1000
    nonbasics = [n for n in names if n not in {"Forest", "Plains", "Island"}]
    assert len(nonbasics) == len(set(nonbasics))
    assert all(set(c.card.color_identity) <= {"G", "W", "U"} for c in cards)
    assert stages[-1] == ("completed", 100)
    with sqlite3.connect(path) as conn:
        saved = conn.execute(
            "SELECT rationale FROM generated_decks WHERE id=?", (result.deck.id,)
        ).fetchone()
        assert saved is not None
        assert "quality_warnings" in json.loads(saved[0])

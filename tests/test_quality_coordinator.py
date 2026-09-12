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

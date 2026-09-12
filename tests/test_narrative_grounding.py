"""Narrative grounding: facts-only rendering, membership, name-only, unknown cards."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from sabermetrics.models.llm_responses import DeckSynthesisResponse
from sabermetrics.reasoning.narrative_grounding import (
    card_facts_from_dicts,
    has_authoritative_facts,
    render_deck_narrative,
)
from sabermetrics.reasoning.prompts import _CACHE as _PROMPT_CACHE
from sabermetrics.reasoning.prompts import load_prompt
from sabermetrics.reasoning.synthesis import DeckSynthesizer
from tests.fixtures.grounding.public_card_facts import (
    AANG_COMMANDER,
    AANG_LIST_CARD,
    BRAZEN_BORROWER,
    PEREGRINE_DRAKE,
    SOL_RING,
    TAIGAM,
    UNKNOWN_CARD,
)

PROFILE_SUMMARY = (
    "Commander: Invented Commander From Summary\n"
    "Archetype: midrange\n"
    "Game Plan: Combat damage."
)


def _facts():
    return [AANG_LIST_CARD, BRAZEN_BORROWER, PEREGRINE_DRAKE, TAIGAM, SOL_RING]


def _prose_blob(response: DeckSynthesisResponse) -> str:
    return "\n".join(
        [
            response.game_plan,
            response.suggested_play_pattern,
            *response.key_synergies,
            *response.weaknesses,
        ]
    )


def test_deck_synthesis_prompt_does_not_blacklist_card_names() -> None:
    _PROMPT_CACHE.pop("deck_synthesis", None)
    template = load_prompt("deck_synthesis")
    assert "{profile_summary}" in template
    assert "{bracket}" in template
    assert "Spark Double" not in template
    assert "Sakashima" not in template
    assert "Black Lotus" not in template


def test_name_only_facts_are_not_authoritative() -> None:
    facts = card_facts_from_dicts([{"name": "Spark Double"}, {"name": "Sol Ring"}])
    assert has_authoritative_facts(facts) is False


def test_public_aang_oracle_is_used_not_fictional_combat_draw() -> None:
    oracle = (AANG_LIST_CARD["oracle_text"] or "").lower()
    assert "look at the top five cards" in oracle
    assert "earthbend" in oracle
    assert "deals combat damage to a player, draw a card" not in oracle
    blob = _prose_blob(
        render_deck_narrative(card_facts_from_dicts(_facts()), 3, "Target power level")
    ).lower()
    assert "look at the top five cards" in blob
    assert "deals combat damage to a player, draw a card" not in blob


def _run_synthesize(cards: list[dict], model_payload: dict | None, cost: float = 0.03):
    del model_payload, cost
    synth = DeckSynthesizer(Path("/tmp/unused-grounding.db"))
    fake = MagicMock()
    fake.call_with_cache.side_effect = AssertionError(
        "narrative must not call the model"
    )
    with patch(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance",
        return_value=fake,
    ):
        response, billed = synth.synthesize(
            profile_summary=PROFILE_SUMMARY,
            deck_cards_with_reasoning=cards,
            bracket=3,
            bracket_reasoning="Target power level",
        )
    return response, billed, fake


def test_sol_ring_only_list_does_not_name_absent_cards() -> None:
    hostile = {
        "game_plan": "Black Lotus wins the game immediately.",
        "key_synergies": [],
        "weaknesses": [],
        "suggested_play_pattern": "Cast Black Lotus.",
        "cited_cards": [],
        "suggestions": [],
        "mechanic_claims": [],
    }
    response, billed, fake = _run_synthesize([SOL_RING], hostile)
    blob = _prose_blob(response)
    assert "Black Lotus" not in blob
    assert "Sol Ring" in blob
    assert "{T}: Add {C}{C}." in blob
    assert "1 ramp" in blob or "Roles: 1 ramp" in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_untrusted_profile_summary_commander_is_not_copied() -> None:
    response, billed, fake = _run_synthesize([SOL_RING], None)
    blob = _prose_blob(response)
    assert "Invented Commander From Summary" not in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_absent_spark_double_and_sakashima_are_not_claimed() -> None:
    response, billed, fake = _run_synthesize(_facts(), {"game_plan": "Spark Double"})
    blob = _prose_blob(response)
    assert "Spark Double" not in blob
    assert "Sakashima" not in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_brazen_borrower_cannot_target_friendly_aang() -> None:
    response, billed, fake = _run_synthesize(_facts(), None)
    blob = _prose_blob(response).lower()
    assert "bounces friendly" not in blob
    assert "friendly aang" not in blob
    assert "brazen borrower" in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_peregrine_drake_mv5_is_not_treated_as_mv_le_4() -> None:
    response, billed, fake = _run_synthesize(_facts(), None)
    blob = _prose_blob(response)
    assert "Peregrine Drake" in blob
    assert "four-mana" not in blob.lower()
    assert "mv<=4" not in blob.lower()
    assert "mana value 5" in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_taigam_spell_copying_is_not_extra_combats() -> None:
    response, billed, fake = _run_synthesize(_facts(), None)
    blob = _prose_blob(response).lower()
    assert "extra combat" not in blob
    assert "additional combat" not in blob
    assert "taigam, master opportunist" in blob
    assert "copy" in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_empty_and_name_only_facts_stay_conservative() -> None:
    empty, cost_empty, fake_empty = _run_synthesize([], None)
    assert cost_empty == 0.0
    fake_empty.call_with_cache.assert_not_called()
    empty_blob = _prose_blob(empty).lower()
    assert "spark double" not in empty_blob
    assert "extra combat" not in empty_blob
    assert "flying" not in empty_blob
    assert "token" not in empty_blob
    assert "invented commander from summary" not in empty_blob

    name_only_cards = [{"name": "Spark Double"}, {"name": "Sol Ring"}]
    named, cost_named, fake_named = _run_synthesize(name_only_cards, None)
    assert cost_named == 0.0
    fake_named.call_with_cache.assert_not_called()
    blob = _prose_blob(named)
    assert "Spark Double" in blob
    assert "Sol Ring" in blob
    assert "clone" not in blob.lower()
    assert "flying" not in blob.lower()
    assert "extra combat" not in blob.lower()
    assert "token" not in blob.lower()
    assert "combo" not in blob.lower()
    assert "{T}: Add {C}{C}." not in blob


def test_adversarial_unknown_card_does_not_invent_abilities() -> None:
    hostile = {
        "game_plan": (
            "Uncatalogued Mystery has flying, makes tokens, and grants extra combats. "
            "Black Lotus wins the game immediately."
        ),
        "suggested_play_pattern": "Cast Black Lotus.",
        "key_synergies": ["Uncatalogued Mystery clones Aang."],
        "weaknesses": [],
        "cited_cards": ["Black Lotus"],
        "suggestions": [],
        "mechanic_claims": [],
    }
    response, billed, fake = _run_synthesize([UNKNOWN_CARD], hostile)
    blob = _prose_blob(response)
    assert "Uncatalogued Mystery" in blob
    assert "Black Lotus" not in blob
    assert "flying" not in blob.lower()
    assert "token" not in blob.lower()
    assert "extra combat" not in blob.lower()
    assert "clone" not in blob.lower()
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_unknown_name_beside_sol_ring_keeps_only_printed_sol_ring_text() -> None:
    cards = [SOL_RING, UNKNOWN_CARD]
    response, billed, fake = _run_synthesize(cards, None)
    blob = _prose_blob(response)
    assert "Sol Ring" in blob
    assert "{T}: Add {C}{C}." in blob
    assert "Uncatalogued Mystery" in blob
    assert "Black Lotus" not in blob
    mystery_line = next(
        line for line in response.key_synergies if "Uncatalogued Mystery" in line
    )
    assert "flying" not in mystery_line.lower()
    assert "token" not in mystery_line.lower()
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_rendered_narrative_includes_roles_and_unmet_warnings() -> None:
    response, billed, fake = _run_synthesize(_facts(), None)
    blob = _prose_blob(response)
    assert AANG_COMMANDER["name"] in blob
    assert "Roles:" in blob
    assert "This list has no card draw cards." in blob
    assert "look at the top five cards" in blob.lower()
    assert "Target power level" in blob
    assert billed == 0.0
    fake.call_with_cache.assert_not_called()


def test_single_legendary_in_main_deck_is_not_invented_commander():
    from sabermetrics.reasoning.narrative_grounding import (
        card_facts_from_dicts,
        render_deck_narrative,
    )

    facts = card_facts_from_dicts(
        [
            {
                "name": "Legendary Support",
                "type_line": "Legendary Creature",
                "role": "utility",
                "oracle_text": "Flying",
            }
        ]
    )
    result = render_deck_narrative(facts, 2, "")
    assert "is the commander" not in result.game_plan

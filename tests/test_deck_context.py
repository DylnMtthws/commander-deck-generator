"""Synthetic access providers exercise static rules, not actual library availability."""

from sabermetrics.intelligence.deck_context import validate_deck_context
from sabermetrics.intelligence.function_guard import validate_transition

COMMANDER = {"name": "Synthetic commander", "color_identity": ["U"]}


def draw(name, mv):
    return {
        "name": name,
        "oracle_text": "Draw two cards.",
        "type_line": "Instant",
        "mana_cost": f"{{{mv - 1}}}{{U}}",
        "cmc": mv,
        "color_identity": ["U"],
        "price_usd": 1,
    }


def tutor(text, mv=4):
    return {
        "name": "Synthetic access fixture",
        "oracle_text": text,
        "type_line": "Enchantment",
        "mana_cost": f"{{{mv - 1}}}{{U}}",
        "cmc": mv,
        "color_identity": ["U"],
        "price_usd": 1,
    }


def check(provider):
    return validate_transition(
        [draw("Weave Fate", 4), provider],
        [draw("Quick Study", 3), provider],
        COMMANDER,
        2,
    )


def test_lower_cost_draw_must_not_remove_exact_mana_value_access():
    result = check(
        tutor(
            "Search your library for an instant card with mana value 4, reveal it, then shuffle."
        )
    )
    assert not result["allowed"]
    assert result["deck_context"]["losses"][0]["before"] == 1
    assert result["deck_context"]["losses"][0]["after"] == 0


def test_upper_bound_access_is_preserved_by_cheaper_draw():
    result = check(
        tutor(
            "Search your library for an instant card with mana value 4 or less, reveal it, then shuffle."
        )
    )
    assert result["allowed"] and result["deck_context"]["checks"][0]["after"] == 1


def test_unrelated_card_type_access_does_not_block_draw_improvement():
    assert check(
        tutor(
            "Search your library for an artifact card with mana value 4, reveal it, then shuffle."
        )
    )["allowed"]


def test_unknown_cost_dependency_abstains():
    result = check(
        tutor("Search your library for a card with mana value X, then shuffle.")
    )
    assert not result["allowed"]
    assert result["deck_context"]["losses"][0]["kind"] == "unparsed_cost_sensitivity"


def test_transmute_preserves_matching_static_targets_and_excludes_provider():
    provider = tutor(
        "Transmute {1}{U}{U} (Search your library for a card with the same mana value as this card, reveal it, then shuffle.)"
    )
    result = check(provider)
    assert not result["allowed"]
    assert result["deck_context"]["checks"][0]["before"] == 1
    assert result["deck_context"]["checks"][0]["after"] == 0


def test_whole_package_cannot_compensate_exact_target_loss_with_unrelated_mana_value():
    provider = tutor(
        "Search your library for an instant card with mana value 4, reveal it, then shuffle."
    )
    a = [draw("A", 4), draw("B", 4), provider]
    b = [draw("C", 3), draw("D", 5), provider]
    result = validate_deck_context(a, b, COMMANDER)
    assert not result["allowed"] and result["checks"][0]["after"] == 0


def test_support_card_cast_trigger_checks_all_final_cards():
    provider = tutor("Whenever you cast an instant or sorcery spell, draw a card.")
    old, new = draw("A", 4), {**draw("B", 4), "type_line": "Creature — Wizard"}
    result = validate_deck_context([old, provider], [new, provider], COMMANDER)
    assert not result["allowed"] and result["losses"][0]["kind"] == "cast_category"


def test_unknown_dependency_does_not_claim_unchanged_deck_is_a_loss():
    provider = tutor("Cards with odd mana values have additional effects.")
    assert validate_deck_context([provider], [provider], COMMANDER)["allowed"]


def test_named_search_and_cast_dependencies_cannot_disappear():
    for text in [
        "Search your library for a card named Weave Fate, reveal it, then shuffle.",
        "Whenever you cast a spell named Weave Fate, draw a card.",
    ]:
        result = check(tutor(text))
        assert not result["allowed"]
        assert result["deck_context"]["losses"][0]["kind"] == "named_card_reference"


def test_unrelated_named_reference_is_not_a_blanket_veto():
    assert check(
        tutor("Search your library for a card named Sol Ring, reveal it, then shuffle.")
    )["allowed"]


def test_repair_search_skips_context_breaking_choice_and_finds_valid_alternative():
    from sabermetrics.intelligence.function_guard import guarded_repair

    provider = tutor(
        "Search your library for an instant card with mana value 4, reveal it, then shuffle."
    )
    old = draw("Old synthetic draw", 4)
    cheaper = {**draw("Cheaper synthetic draw", 3), "oracle_text": "Draw three cards."}
    retained_cost = {
        **draw("Same-cost synthetic draw", 4),
        "oracle_text": "Draw three cards.",
    }
    result, receipt = guarded_repair(
        [old, provider], [cheaper, retained_cost], COMMANDER, 2
    )
    assert result[0]["name"] == "Same-cost synthetic draw"
    assert receipt["guard"]["allowed"]

from copy import deepcopy

import pytest

from sabermetrics.intelligence.draw_portfolio import select_portfolio, trigger_group


def item(name, cost, score, text="Draw two cards.", typ="Instant"):
    return (
        {"name": name, "price_usd": cost, "oracle_text": text, "type_line": typ},
        score,
    )


def test_budget_search_does_not_let_one_expensive_redundant_engine_consume_package():
    damage = (
        "Whenever enchanted creature deals damage to an opponent, you may draw a card."
    )
    pool = [
        item("Cheap link", 1, 1.1, damage, "Enchantment"),
        item("Expensive link", 12, 1.05, damage, "Enchantment"),
        item("Other cheap link", 1, 1, damage, "Creature"),
        item(
            "Opponent engine",
            10,
            0.94,
            "Whenever an opponent casts a noncreature spell, draw a card.",
            "Enchantment",
        ),
        item("Smoothing", 0.1, 0.8, "Draw a card."),
    ]
    selected, receipt = select_portfolio(pool, 4, 13)
    assert {c["name"] for c, s in selected} == {
        "Cheap link",
        "Other cheap link",
        "Opponent engine",
        "Smoothing",
    }
    assert receipt["spent"] <= 13


def test_order_invariance_duplicates_and_input_immutability():
    pool = [item("A", 2, 0.9), item("A", 1, 0.9), item("B", 1, 0.8)]
    before = deepcopy(pool)
    a, ra = select_portfolio(pool, 2, 2)
    b, rb = select_portfolio(list(reversed(pool)), 2, 2)
    assert a == b and ra == rb and pool == before
    assert [c["name"] for c, s in a] == ["A", "B"]


def test_unknown_prices_and_vetoed_cards_cannot_enter():
    pool = [
        item("Missing", None, 10),
        item("Negative", -1, 10),
        item("Infinite", float("inf"), 10),
        ({**item("Vetoed", 1, 10)[0], "_anti_engine": True}, 10),
        item("Valid", 1, 0.5),
    ]
    selected, _receipt = select_portfolio(pool, 3, 2)
    assert [c["name"] for c, s in selected] == ["Valid"]


def test_zero_budget_never_means_unlimited():
    selected, receipt = select_portfolio(
        [item("Paid", 1, 10), item("Free", 0, 0.5)], 2, 0
    )
    assert [c["name"] for c, s in selected] == ["Free"] and receipt["spent"] == 0


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), -1])
def test_bad_budgets_rejected(budget):
    with pytest.raises(ValueError):
        select_portfolio([], 2, budget)


def test_unknown_cards_do_not_receive_distinct_diversity_credit_by_name():
    assert (
        trigger_group(item("A", 1, 1, "Unparsed rules")[0])
        == trigger_group(item("B", 1, 1, "Different unparsed rules")[0])
        == "unmodeled_draw"
    )


def test_counter_spending_draw_is_not_direct_cast_trigger_draw():
    card = item(
        "Synthetic counter draw",
        1,
        1,
        "Whenever you cast an instant or sorcery spell, put a counter on this. Remove five counters: Draw a card.",
        "Artifact",
    )[0]
    assert trigger_group(card) == "unmodeled_draw"
    card["oracle_text"] = (
        "Whenever you cast or copy an instant or sorcery spell, draw a card."
    )
    assert trigger_group(card) == "own_cast"
    card["oracle_text"] += " Then discard a card."
    assert trigger_group(card) == "unmodeled_draw"


def test_upfront_mana_policy_keeps_unknown_or_slow_draw_out_of_reserved_package():
    pool = [
        ({**item("Six mana", 1, 1)[0], "cmc": 6}, 1),
        ({**item("Early", 1, 0.8)[0], "cmc": 3}, 0.8),
        item("Unknown mana", 1, 2),
    ]
    selected, receipt = select_portfolio(pool, 2, 10, max_mana_value=5)
    assert [c["name"] for c, s in selected] == ["Early"]
    assert receipt["max_mana_value"] == 5

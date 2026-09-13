import json
from copy import deepcopy
from pathlib import Path

from sabermetrics.intelligence.draw_selection import audit, context, evaluate, repair

CARDS = json.loads(
    (
        Path(__file__).parents[1]
        / "docs/experiments/draw-selection/public-fixtures.json"
    ).read_text()
)["cards"]


def card(name, price=1):
    c = deepcopy(CARDS[name])
    if isinstance(c["color_identity"], str):
        c["color_identity"] = json.loads(c["color_identity"])
    c["price_usd"] = price
    c["role_tags"] = ["draw"]
    return c


def body(i, role="utility"):
    return {
        "name": f"body-{i}",
        "type_line": "Creature — Human",
        "oracle_text": "",
        "cmc": 2,
        "color_identity": [],
        "price_usd": 1,
        "role_tags": [role],
    }


def test_actual_cards_distinguish_filtering_and_advantage():
    ctx = context([body(i) for i in range(30)], {})
    assert not evaluate(card("Faithless Looting"), ctx)["credible"]
    assert evaluate(card("Harmonize"), ctx)["credible"]
    assert evaluate(card("Phyrexian Arena"), ctx)["independent"]
    assert not evaluate(card("The Unagi of Kyoshi Island"), ctx)["independent"]
    assert evaluate(card("Insight Engine"), ctx)["credible"]


def test_creature_engine_cannot_pass_in_spells_shell():
    sparse = context([], {})
    dense = context([body(i) for i in range(30)], {})
    assert not evaluate(card("Beast Whisperer"), sparse)["credible"]
    assert evaluate(card("Beast Whisperer"), dense)["credible"]


def test_missing_prices_and_illegal_colors_are_not_budget_alternatives():
    deck = [body(i) for i in range(10)]
    commander = {"name": "Example", "color_identity": ["U"]}
    unknown = card("Insight Engine")
    unknown.pop("price_usd")
    result, receipt = repair(deck, [card("Phyrexian Arena"), unknown], commander, 20)
    assert result == deck
    assert receipt["status"] == "unresolved"


def test_budget_alternatives_order_and_immutability():
    deck = [body(i) for i in range(30)]
    candidates = [
        card(n)
        for n in [
            "Harmonize",
            "Phyrexian Arena",
            "Insight Engine",
            "Beast Whisperer",
            "Guardian Project",
            "Sign in Blood",
        ]
    ]
    candidates += [card("Rhystic Study", 99)]
    commander = {"name": "Example", "color_identity": ["U", "B", "G"]}
    frozen = deepcopy((deck, candidates))
    a, receipt = repair(deck, candidates, commander, 30)
    b, _ = repair(deck, list(reversed(candidates)), commander, 30)
    assert a == b
    assert (deck, candidates) == frozen
    assert len(a) == len(deck)
    assert sum(c["price_usd"] for c in a) <= 30
    assert "Rhystic Study" not in {c["name"] for c in a}
    assert receipt["after"]["credible"] >= 4


def test_preserve_lands_and_real_non_draw_functions():
    deck = [body(i, "removal") for i in range(10)]
    deck[0].update(type_line="Land", name="Example land", role_tags=["land"])
    repaired, _ = repair(deck, [card("Harmonize")], {"color_identity": ["G"]}, 20)
    assert repaired == deck


def test_no_draw_credit_from_slot_or_tag_alone():
    fake = body(0, "draw")
    assert audit([fake], {}, 3)["credible"] == 0


def test_high_power_draw_setup_is_not_silently_cheap():
    assert not evaluate(card("The Unagi of Kyoshi Island"), context([], {}), 5)[
        "credible"
    ]

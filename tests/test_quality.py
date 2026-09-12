"""Final acceptance: hard failures vs labeled quality warnings."""

from sabermetrics.pipeline.intent import admit_engine_candidates, parse_user_intent
from sabermetrics.pipeline.quality import (
    evaluate_final_deck,
    ledger_review_cost,
    replacement_is_valid,
)


def _card(name, **kwargs) -> dict:
    data = {
        "name": name,
        "type_line": "Creature — Elf",
        "oracle_text": "Whenever this creature enters, draw a card.",
        "cmc": 2.0,
        "price_usd": 1.0,
        "color_identity": ["G"],
    }
    data.update(kwargs)
    return data


def _clone(name, legendary=False) -> dict:
    return _card(
        name,
        type_line=(
            "Legendary Creature — Shapeshifter"
            if legendary
            else "Creature — Shapeshifter"
        ),
        oracle_text="You may have this creature enter as a copy of any creature on the battlefield.",
        cmc=4.0,
        color_identity=["U"],
    )


def _assignments(n=99, extra=None):
    cards = extra or []
    need = n - len(cards)
    cards = list(cards) + [_card(f"Filler {i}") for i in range(need)]
    return cards


def test_evaluate_splits_failures_from_warnings():
    clones = [_clone("Spark Double"), _clone("Sakashima of a Thousand Faces")]
    req = parse_user_intent("4 mana copy creatures")
    engine = admit_engine_candidates(req, clones)
    report = evaluate_final_deck(
        assignments=_assignments(99, clones),
        commander_name="Aang, at the Crossroads // Aang, Destined Savior",
        commander_colors=["G", "W", "U"],
        budget_usd=1000,
        requested_bracket=4,
        estimated_bracket=2,
        engine=engine,
        engine_status="satisfied",
        signals={"rules": True, "embeddings": False},
        role_counts={"ramp": 2},
        role_targets={"ramp": 8},
        review_failed=True,
    )
    codes = {item.code for item in report.failures}
    warn_codes = {item.code for item in report.warnings}
    assert "deck_size" not in codes
    assert "over_budget" not in codes
    assert "bracket_estimate" in warn_codes
    assert "Power is an estimate" in next(
        w.message for w in report.warnings if w.code == "bracket_estimate"
    )
    assert "signal_unavailable" in warn_codes
    assert "unmet_role_target" in warn_codes
    assert "failed_final_review" in warn_codes
    assert "engine_unavailable" not in warn_codes
    dumped = report.as_rationale_list()
    assert any(row["code"] == "failed_final_review" for row in dumped)


def test_infeasible_engine_never_reported_satisfied():
    expensive = _clone("Spark Double")
    expensive["price_usd"] = 900.0
    req = parse_user_intent("copy creatures")
    engine = admit_engine_candidates(
        req,
        budget_valid_pool=[],
        color_legal_pool=[expensive],
        per_card_ceiling=25.0,
    )
    report = evaluate_final_deck(
        assignments=_assignments(99),
        commander_name="Aang",
        commander_colors=["G", "W", "U"],
        budget_usd=50,
        requested_bracket=4,
        estimated_bracket=2,
        engine=engine,
        engine_status="infeasible",
    )
    warn = next(w for w in report.warnings if w.code == "engine_unavailable")
    assert "not satisfied" in warn.message.lower() or "is not satisfied" in warn.message
    assert "fulfilled" not in warn.message.lower() or "not" in warn.message.lower()


def test_unsupported_intent_is_unverified_warning():
    req = parse_user_intent("make infinite extra combat steps")
    engine = admit_engine_candidates(req, [])
    report = evaluate_final_deck(
        assignments=_assignments(99),
        commander_name="Aang",
        commander_colors=["G", "U", "W"],
        budget_usd=200,
        requested_bracket=4,
        estimated_bracket=3,
        engine=engine,
        engine_status="unverified",
    )
    assert any(w.code == "intent_unverified" for w in report.warnings)
    assert not any(
        "fulfilled" in w.message.lower() and "un" not in w.message.lower()
        for w in report.warnings
    )


def test_hard_failures_for_size_singleton_color_budget():
    dup = _card("Sol Ring", color_identity=[], price_usd=5.0)
    off_color = _card("Lightning Bolt", color_identity=["R"], price_usd=1.0)
    pricey = _card("Mana Crypt", color_identity=[], price_usd=200.0)
    report = evaluate_final_deck(
        assignments=[dup, dup, off_color, pricey],
        commander_name="Aang",
        commander_colors=["G", "W", "U"],
        budget_usd=10,
        requested_bracket=3,
        estimated_bracket=3,
        engine=None,
        engine_status="none",
    )
    codes = {f.code for f in report.failures}
    assert "deck_size" in codes
    assert "singleton" in codes
    assert "color_identity" in codes
    assert "over_budget" in codes


def test_ledger_review_cost_never_subtracts():
    assert ledger_review_cost(-1.0, review_failed=False) == 0.0
    assert ledger_review_cost(0.04, review_failed=True) == 0.04
    assert ledger_review_cost(0.12, review_failed=False) == 0.12


def test_replacement_rejects_sentinel_and_singleton_and_color():
    ok, _ = replacement_is_valid(
        _card("New Card", price_usd=1.0, color_identity=["G"]),
        commander_colors={"G", "W", "U"},
        deck_names={"Spark Double"},
        max_price=10.0,
    )
    assert ok
    bad_price, why = replacement_is_valid(
        _card("Trap", price_usd=-1.0),
        commander_colors={"U"},
        deck_names=set(),
    )
    assert not bad_price
    assert "negative-cost sentinel" in why
    dup, _why_dup = replacement_is_valid(
        _card("Spark Double"),
        commander_colors={"U"},
        deck_names={"Spark Double"},
    )
    assert not dup
    off, why_off = replacement_is_valid(
        _card("Bolt", color_identity=["R"]),
        commander_colors={"G", "W", "U"},
        deck_names=set(),
    )
    assert not off
    assert "color" in why_off


def test_finite_top_n_does_not_leave_an_infinite_claim():
    aang = "When Aang enters, look at the top five cards of your library."
    report = evaluate_final_deck(
        assignments=_assignments(99),
        commander_name="Aang",
        commander_colors=["G", "U", "W"],
        budget_usd=200,
        requested_bracket=4,
        estimated_bracket=2,
        engine=None,
        engine_status="none",
        commander_oracle=aang,
    )
    assert not any("infinite" in item.message.lower() for item in report.all_items())


def test_colorless_commander_rejects_colored_replacements():
    valid, reason = replacement_is_valid(
        _card("Blue card", color_identity=["U"]),
        commander_colors=set(),
        deck_names=set(),
    )
    assert not valid
    assert "color identity" in reason


def test_final_hard_checks_reject_banned_and_invalid_price():
    report = evaluate_final_deck(
        assignments=_assignments(
            99, [_card("Bad card", price_usd=-5, is_legal_in_99=False)]
        ),
        commander_name="Commander",
        commander_colors=[],
        budget_usd=1000,
        requested_bracket=3,
        estimated_bracket=2,
        engine=None,
        engine_status="none",
    )
    assert {"invalid_price", "card_legality"} <= {item.code for item in report.failures}

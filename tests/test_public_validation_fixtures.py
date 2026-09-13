import json
from pathlib import Path

from sabermetrics.intelligence.land_policy import land_risks, risk_adjustment

FIXTURES = json.loads(
    (
        Path(__file__).parents[1]
        / "docs/experiments/selection-validation/public-fixtures.json"
    ).read_text()
)


def test_current_oracle_land_conditions():
    cards = FIXTURES["cards"]
    expected = {
        "Rainbow Vale": "opponent_gains_control",
        "Forsaken City": "upkeep_hand_exile",
        "Glimmervoid": "sacrifice_unless_artifact",
        "Thran Quarry": "sacrifice_unless_creature",
        "Phyrexian Tower": "mana_requires_sacrificing_resource",
    }
    for name, code in expected.items():
        risks = land_risks(cards[name])
        assert code in {r["code"] for r in risks}, (name, risks)
    assert not land_risks(cards["Command Tower"])
    assert risk_adjustment(
        cards["Glimmervoid"], [{"type_line": "Artifact"}] * 99
    ) > risk_adjustment(cards["Glimmervoid"])


def test_independent_public_claim_labels():
    from sabermetrics.intelligence.review import contradictions

    cards = FIXTURES["cards"]
    for row in FIXTURES["claim_labels"]:
        errors = contradictions(
            cards[row["card"]], row["reasoning"], cards["Y'shtola, Night's Blessed"]
        )
        assert bool(errors) == row["error"], (row, errors)


def test_real_transmute_and_named_target():
    from sabermetrics.intelligence.constraints import audit_deck, tutor_targets

    c = FIXTURES["cards"]
    targets = tutor_targets(
        c["Dizzy Spell"],
        [c[n] for n in ["Dizzy Spell", "Curiosity", "Gitaxian Probe", "Ophidian Eye"]],
    )
    assert targets["targets"] == ["Curiosity", "Gitaxian Probe"]
    assert tutor_targets(c["Dragon's Herald"], [c["Hellkite Overlord"]])["targets"] == [
        "Hellkite Overlord"
    ]
    assert any(
        f["code"] == "named_search_no_target"
        for f in audit_deck([c["Dragon's Herald"]], {})
    )


def test_pact_presence_does_not_declare_a_line():
    from sabermetrics.intelligence.constraints import audit_deck

    c = FIXTURES["cards"]
    deck = [c["Tainted Pact"], c["Thassa's Oracle"], c["Swamp"], c["Swamp"]]
    risks = audit_deck(deck, {})
    assert any(
        f["code"] == "pact_duplicate_names" and f["severity"] == "warning"
        for f in risks
    )
    assert any(
        f["code"] == "pact_duplicate_names" and f["severity"] == "error"
        for f in audit_deck(deck, {"_declared_lines": ["pact_library_empty"]})
    )

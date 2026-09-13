"""Land drawback policy: printed shapes, bounded penalties, no bans.

Fixtures are printed public Oracle text (Gatherer/Scryfall wording) plus
synthetic lands for shapes that need an isolated control. Every assertion is
about a *shape*. A drawback finding is never a legality claim: these tests
also pin the properties that keep it from becoming one, namely that the
zero-weight arm is the untouched baseline, that penalties are bounded, and
that a risky land can still outscore a clean one.
"""

import copy
import math
import random

import pytest

from sabermetrics.intelligence import land_policy
from sabermetrics.intelligence.land_policy import (
    MAX_TOTAL_PENALTY,
    SEVERITY_ORDER,
    SEVERITY_PENALTY,
    adjust_land_score,
    land_risks,
    risk_adjustment,
)


def land(name, text="", types="Land", **kwargs):
    return {"name": name, "oracle_text": text, "type_line": types, **kwargs}


def codes(card):
    return {risk["code"] for risk in land_risks(card)}


# ---------------------------------------------------------------------------
# Public oracle fixtures
# ---------------------------------------------------------------------------

RAINBOW_VALE = land(
    "Rainbow Vale",
    "{T}: Add one mana of any color. Target opponent gains control of Rainbow "
    "Vale at the beginning of the next end step.",
)
FORSAKEN_CITY = {
    "name": "Forsaken City",
    "oracle_text": "This land doesn't untap during your untap step.\nAt the beginning of your upkeep, you may exile a card from your hand. If you do, untap this land.\n{T}: Add one mana of any color.",
    "type_line": "Land",
    "cmc": 0.0,
    "mana_cost": "",
    "color_identity": "[]",
}

GLIMMERVOID = land(
    "Glimmervoid",
    "At the beginning of the end step, sacrifice Glimmervoid unless you "
    "control an artifact.\n"
    "{T}: Add one mana of any color.",
)
THRAN_QUARRY = land(
    "Thran Quarry",
    "At the beginning of your end step, sacrifice Thran Quarry unless you "
    "control a creature.\n"
    "{T}: Add one mana of any color.",
)
CITY_OF_BRASS = land(
    "City of Brass",
    "Whenever City of Brass becomes tapped, it deals 1 damage to you.\n"
    "{T}: Add one mana of any color.",
)
COMMAND_TOWER = land(
    "Command Tower",
    "{T}: Add one mana of any color in your commander's color identity.",
)
SCALDING_TARN = land(
    "Scalding Tarn",
    "{T}, Pay 1 life, Sacrifice Scalding Tarn: Search your library for an "
    "Island or Mountain card, put it onto the battlefield, then shuffle.",
)
MYSTIC_GATE = land(  # filter land
    "Mystic Gate",
    "{T}: Add {C}.\n{W/U}, {T}: Add {W}{W}, {W}{U}, or {U}{U}.",
)
ISLAND = land("Island", "", "Basic Land — Island")
SOL_RING = {
    "name": "Sol Ring",
    "oracle_text": "{T}: Add {C}{C}.",
    "type_line": "Artifact",
}

# Validation examples, with the full expected finding set for each.
VALIDATION_EXAMPLES = [
    (RAINBOW_VALE, {"opponent_gains_control"}),
    (
        FORSAKEN_CITY,
        {"does_not_untap", "upkeep_hand_exile"},
    ),
    (GLIMMERVOID, {"sacrifice_unless_artifact"}),
    (THRAN_QUARRY, {"sacrifice_unless_creature"}),
    (CITY_OF_BRASS, {"mana_source_damages_you"}),
    (COMMAND_TOWER, set()),
    (SCALDING_TARN, {"mana_requires_library_search"}),
    (MYSTIC_GATE, {"mana_requires_mana_payment"}),
]


@pytest.mark.parametrize(
    ("card", "expected"),
    VALIDATION_EXAMPLES,
    ids=[c["name"] for c, _ in VALIDATION_EXAMPLES],
)
def test_validation_examples(card, expected):
    assert codes(card) == expected


# ---------------------------------------------------------------------------
# Positives: one supported shape at a time
# ---------------------------------------------------------------------------


def test_loss_of_control_is_high_severity():
    (risk,) = land_risks(RAINBOW_VALE)
    assert risk["severity"] == "high"
    assert "control" in risk["message"]


def test_upkeep_sacrifice_and_no_untap_are_separate_findings():
    found = {r["code"]: r["severity"] for r in land_risks(FORSAKEN_CITY)}
    assert found["upkeep_hand_exile"] == "high"
    assert found["does_not_untap"] == "medium"


def test_upkeep_exile_detected():
    card = land(
        "Borrowed Ley Line",
        "At the beginning of your upkeep, exile it.\n{T}: Add {U}.",
    )
    assert codes(card) == {"upkeep_exile"}


def test_triggered_self_sacrifice_without_unless():
    card = land(
        "Fading Well",
        "At the beginning of your end step, sacrifice Fading Well.\n{T}: Add {G}.",
    )
    assert codes(card) == {"triggered_self_sacrifice"}


def test_sacrifice_unless_unmodelled_condition_stays_high():
    card = land(
        "Devotional Waste",
        "At the beginning of your end step, sacrifice Devotional Waste unless "
        "you control three or more Clerics.\n{T}: Add {W}.",
    )
    found = {r["code"]: r["severity"] for r in land_risks(card)}
    assert found == {"sacrifice_unless_condition": "high"}


def test_generic_activation_cost_is_flagged_but_low():
    (risk,) = land_risks(MYSTIC_GATE)
    assert risk["code"] == "mana_requires_mana_payment"
    assert risk["severity"] == "low"


def test_conditional_activation_restriction():
    card = land(
        "Gated Spring",
        "{T}: Add {G}. Activate only if you control a Forest.",
    )
    assert "conditional_mana_activation" in codes(card)


def test_restricted_mana_usage_and_conditional_colors():
    restricted = land(
        "Narrow Font",
        "{T}: Add {B}. Spend this mana only to cast creature spells.",
    )
    assert "mana_usage_restricted" in codes(restricted)
    pool = land(
        "Reflecting Pool",
        "{T}: Add one mana of any color that a land you control could produce.",
    )
    assert "color_depends_on_other_permanents" in codes(pool)


def test_pain_and_life_costs_are_low_not_disqualifying():
    confluence = land(
        "Mana Confluence",
        "{T}, Pay 1 life: Add one mana of any color.",
    )
    assert codes(confluence) == {"mana_costs_life"}
    assert all(r["severity"] == "low" for r in land_risks(CITY_OF_BRASS))


def test_missing_oracle_text_is_unknown_not_clean():
    card = land("Unprinted Land", "")
    assert codes(card) == {"land_oracle_text_unavailable"}


def test_no_verified_unconditional_source():
    card = land(
        "Silent Waste",
        "Whenever a creature dies, add {B}.",
    )
    assert "mana_requires_trigger" in codes(card)


# ---------------------------------------------------------------------------
# Negatives: shapes that must not be penalised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("card", [COMMAND_TOWER, ISLAND], ids=["tower", "basic"])
def test_clean_lands_have_no_findings(card):
    assert land_risks(card) == []
    assert risk_adjustment(card) == 0.0


def test_non_land_is_out_of_scope():
    assert land_risks(SOL_RING) == []
    assert risk_adjustment(SOL_RING) == 0.0


def test_fetch_sacrifice_is_a_cost_not_a_drawback():
    found = land_risks(SCALDING_TARN)
    assert [r["severity"] for r in found] == ["low"]
    assert "triggered_self_sacrifice" not in codes(SCALDING_TARN)


def test_self_sacrifice_in_an_activation_cost_is_not_a_trigger():
    card = land(
        "Crystal Vein",
        "{T}: Add {C}.\n{T}, Sacrifice Crystal Vein: Add {C}{C}.",
    )
    assert "triggered_self_sacrifice" not in codes(card)


def test_player_gaining_control_of_something_else_is_not_a_land_risk():
    card = land(
        "Volrath's Stronghold",
        "{T}: Add {C}.\n{1}{B}, {T}: Put target creature card from your "
        "graveyard on top of your library.",
    )
    assert "opponent_gains_control" not in codes(card)


# ---------------------------------------------------------------------------
# Invariance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("card", "expected"),
    VALIDATION_EXAMPLES,
    ids=[c["name"] for c, _ in VALIDATION_EXAMPLES],
)
def test_findings_do_not_depend_on_the_card_name(card, expected):
    for replacement in ("", "Zzzz Unknown Land", "Sol Ring"):
        renamed = dict(card, name=replacement)
        assert codes(renamed) == expected
    nameless = {k: v for k, v in card.items() if k != "name"}
    assert codes(nameless) == expected


def test_findings_do_not_depend_on_oracle_line_order():
    lines = FORSAKEN_CITY["oracle_text"].split("\n")
    expected = codes(FORSAKEN_CITY)
    rng = random.Random(7)
    for _ in range(10):
        shuffled = lines[:]
        rng.shuffle(shuffled)
        assert codes(dict(FORSAKEN_CITY, oracle_text="\n".join(shuffled))) == expected


def test_findings_are_ordered_by_severity_then_code():
    found = land_risks(FORSAKEN_CITY)
    ranks = [SEVERITY_ORDER.index(r["severity"]) for r in found]
    assert ranks == sorted(ranks)
    assert found == sorted(
        found, key=lambda r: (SEVERITY_ORDER.index(r["severity"]), r["code"])
    )


def test_every_finding_has_the_documented_shape():
    for card, _ in VALIDATION_EXAMPLES:
        for risk in land_risks(card):
            assert set(risk) == {"code", "severity", "message"}
            assert risk["severity"] in SEVERITY_ORDER
            assert risk["message"].strip()


def test_every_code_has_a_severity_and_a_message():
    assert set(land_policy.RISK_SEVERITY) == set(land_policy.RISK_MESSAGE)
    assert set(land_policy.RISK_SEVERITY.values()) <= set(SEVERITY_ORDER)
    assert set(land_policy.MITIGABLE_BY_DENSITY) <= set(land_policy.RISK_SEVERITY)
    assert set(SEVERITY_PENALTY) == set(SEVERITY_ORDER)


def test_risk_adjustment_ignores_deck_order():
    deck = artifact_deck(6, 30)
    baseline = risk_adjustment(GLIMMERVOID, deck)
    rng = random.Random(11)
    for _ in range(10):
        shuffled = deck[:]
        rng.shuffle(shuffled)
        assert risk_adjustment(GLIMMERVOID, shuffled) == baseline


# ---------------------------------------------------------------------------
# Penalties, mitigation and monotonicity
# ---------------------------------------------------------------------------


def artifact_deck(artifacts, size=20):
    return [
        (
            {"name": f"a{i}", "type_line": "Artifact"}
            if i < artifacts
            else {"name": f"s{i}", "type_line": "Sorcery"}
        )
        for i in range(size)
    ]


def test_penalties_are_negative_and_ordered_by_severity():
    assert risk_adjustment(RAINBOW_VALE) == pytest.approx(-SEVERITY_PENALTY["high"])
    assert risk_adjustment(GLIMMERVOID) == pytest.approx(-SEVERITY_PENALTY["medium"])
    assert risk_adjustment(CITY_OF_BRASS) == pytest.approx(-SEVERITY_PENALTY["low"])
    assert (
        risk_adjustment(RAINBOW_VALE)
        < risk_adjustment(GLIMMERVOID)
        < risk_adjustment(CITY_OF_BRASS)
        < 0.0
    )


def test_multiple_drawbacks_accumulate_but_stay_bounded():
    assert risk_adjustment(FORSAKEN_CITY) == pytest.approx(
        -(SEVERITY_PENALTY["high"] + SEVERITY_PENALTY["medium"])
    )
    piled_up = land(
        "Everything Land",
        "Everything Land doesn't untap during your untap step.\n"
        "At the beginning of your upkeep, sacrifice Everything Land.\n"
        "Target opponent gains control of Everything Land.\n"
        "{1}, {T}: Add {U}. Spend this mana only to cast instants. "
        "Everything Land deals 2 damage to you.",
    )
    assert len(land_risks(piled_up)) >= 4
    assert risk_adjustment(piled_up) == pytest.approx(-MAX_TOTAL_PENALTY)


def test_density_mitigates_a_board_requirement_monotonically():
    unmitigated = risk_adjustment(GLIMMERVOID)
    previous = unmitigated
    for artifacts in (0, 1, 2, 3, 4):
        adjusted = risk_adjustment(GLIMMERVOID, artifact_deck(artifacts))
        assert adjusted >= previous
        previous = adjusted
    assert risk_adjustment(GLIMMERVOID, artifact_deck(4)) > unmitigated


def test_mitigation_is_capped_below_full_relief():
    all_artifacts = risk_adjustment(GLIMMERVOID, artifact_deck(20))
    assert all_artifacts < 0.0
    # Past the target density the discount stops growing: board presence is a
    # prior, never a guarantee.
    assert all_artifacts == pytest.approx(
        risk_adjustment(GLIMMERVOID, artifact_deck(5))
    )


def test_mitigation_only_applies_to_the_matching_type():
    artifacts = artifact_deck(10)
    assert risk_adjustment(THRAN_QUARRY, artifacts) == pytest.approx(
        risk_adjustment(THRAN_QUARRY)
    )
    creatures = [{"name": f"c{i}", "type_line": "Creature — Human"} for i in range(20)]
    assert risk_adjustment(THRAN_QUARRY, creatures) > risk_adjustment(THRAN_QUARRY)
    # An unmodelled condition is never discounted by density.
    assert risk_adjustment(RAINBOW_VALE, creatures) == risk_adjustment(RAINBOW_VALE)


@pytest.mark.parametrize(
    "deck",
    [None, [], [{"name": "x"}]],
    ids=["none", "empty", "typeless"],
)
def test_absent_deck_context_means_no_mitigation(deck):
    assert risk_adjustment(GLIMMERVOID, deck) == pytest.approx(
        risk_adjustment(GLIMMERVOID)
    )


# ---------------------------------------------------------------------------
# adjust_land_score
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("score", [0.0, 0.37, 1.0, -2.5, 1e9])
def test_zero_weights_return_the_exact_baseline(score):
    risky = dict(RAINBOW_VALE, _selection_inclusion=0.9)
    assert adjust_land_score(risky, score) == score
    assert (
        adjust_land_score(risky, score, evidence_weight=0.0, risk_weight=0.0) == score
    )


def test_risk_weight_scales_the_penalty_monotonically():
    card = dict(FORSAKEN_CITY, _selection_inclusion=0.5)
    base = 1.0
    previous = adjust_land_score(card, base)
    for weight in (0.25, 0.5, 1.0, 2.0):
        adjusted = adjust_land_score(card, base, risk_weight=weight)
        assert adjusted < previous
        previous = adjusted
    assert adjust_land_score(card, base, risk_weight=1.0) == pytest.approx(
        base + risk_adjustment(card)
    )


def test_evidence_weight_scales_inclusion_monotonically():
    card = dict(COMMAND_TOWER, _selection_inclusion=0.8)
    previous = adjust_land_score(card, 0.5)
    for weight in (0.1, 0.5, 1.0):
        adjusted = adjust_land_score(card, 0.5, evidence_weight=weight)
        assert adjusted > previous
        previous = adjusted


def test_terms_are_separable():
    card = dict(GLIMMERVOID, _selection_inclusion=0.6)
    both = adjust_land_score(card, 0.4, evidence_weight=0.5, risk_weight=1.0)
    evidence_only = adjust_land_score(card, 0.4, evidence_weight=0.5)
    risk_only = adjust_land_score(card, 0.4, risk_weight=1.0)
    assert both == pytest.approx(evidence_only + risk_only - 0.4)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0.0),
        ("0.9", 0.0),
        (True, 0.0),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (float("-inf"), 0.0),
        (-3.0, 0.0),
        (5.0, 1.0),
        (0.25, 0.25),
    ],
)
def test_inclusion_is_clamped_and_never_raises(value, expected):
    card = dict(COMMAND_TOWER, _selection_inclusion=value)
    adjusted = adjust_land_score(card, 0.0, evidence_weight=1.0)
    assert math.isfinite(adjusted)
    assert adjusted == pytest.approx(expected)


def test_missing_inclusion_key_reads_as_zero():
    assert adjust_land_score(COMMAND_TOWER, 0.2, evidence_weight=1.0) == pytest.approx(
        0.2
    )


def test_non_finite_baseline_is_passed_through_unchanged():
    for score in (float("inf"), float("-inf")):
        assert adjust_land_score(RAINBOW_VALE, score, risk_weight=1.0) == score
    assert math.isnan(adjust_land_score(RAINBOW_VALE, float("nan"), risk_weight=1.0))


def test_a_drawback_is_not_a_ban():
    """A high-risk land with strong evidence can still beat a clean land."""
    risky = dict(RAINBOW_VALE, _selection_inclusion=0.95)
    clean = dict(COMMAND_TOWER, _selection_inclusion=0.05)
    weights = {"evidence_weight": 20.0, "risk_weight": 1.0}
    assert adjust_land_score(risky, 0.5, **weights) > adjust_land_score(
        clean, 0.5, **weights
    )
    # And the penalty alone can never drive a score to negative infinity.
    assert adjust_land_score(risky, 0.5, risk_weight=1.0) >= 0.5 - MAX_TOTAL_PENALTY


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_inputs_are_never_modified():
    card = dict(GLIMMERVOID, _selection_inclusion=0.4)
    deck = artifact_deck(6, 30)
    card_before = copy.deepcopy(card)
    deck_before = copy.deepcopy(deck)

    land_risks(card)
    risk_adjustment(card, deck)
    adjust_land_score(card, 0.5, evidence_weight=0.5, risk_weight=1.0)

    assert card == card_before
    assert deck == deck_before


def test_repeated_calls_are_stable():
    card = dict(THRAN_QUARRY, _selection_inclusion=0.3)
    first = land_risks(card)
    assert land_risks(card) == first
    # The returned records are the caller's; mutating them must not stick.
    first[0]["severity"] = "low"
    assert land_risks(card)[0]["severity"] == "medium"

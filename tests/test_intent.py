"""Grounded clone-engine intent: oracle traits, not card-name lists."""

from sabermetrics.pipeline.intent import (
    admit_engine_candidates,
    claims_infinite_loop,
    engine_rationale_dump,
    is_copy_on_entry_creature,
    is_keyword_counter_collector,
    looks_like_finite_top_n_effect,
    parse_user_intent,
    verify_engine_in_deck,
)


def _card(**kwargs) -> dict:
    base = {
        "id": kwargs.get("name", "x").lower().replace(" ", "-"),
        "name": "Test Card",
        "type_line": "Creature — Shapeshifter",
        "oracle_text": "",
        "cmc": 4.0,
        "price_usd": 5.0,
        "color_identity": ["U"],
    }
    base.update(kwargs)
    return base


SPARK = _card(
    name="Spark Double",
    type_line="Creature — Illusion",
    oracle_text=(
        "You may have this creature enter as a copy of a creature or "
        "planeswalker you control, except it enters with an additional "
        "+1/+1 counter on it if it's a creature, it isn't legendary."
    ),
)
SAKASHIMA = _card(
    name="Sakashima of a Thousand Faces",
    type_line="Legendary Creature — Human Rogue",
    oracle_text=(
        "You may have Sakashima enter as a copy of another creature you "
        "control, except it has Sakashima's other abilities.\n"
        'The "legend rule" doesn\'t apply to permanents you control.'
    ),
)
GENERIC_ETB = _card(
    name="Unnamed Facsimile",
    oracle_text=(
        "You may have this creature enter the battlefield as a copy of "
        "any creature on the battlefield."
    ),
)
ENTERS_AS_COPY = _card(
    name="Battlefield Mirror",
    oracle_text="This creature enters the battlefield as a copy of target creature.",
)
TOKEN_MAKER = _card(
    name="Token Copier Beast",
    oracle_text=(
        "When this creature enters, create a token that's a copy of " "target creature."
    ),
)
SUPER_ADAPTOID = _card(
    name="Super-Adaptoid",
    type_line="Legendary Artifact Creature — Robot Villain",
    cmc=2.0,
    oracle_text=(
        "Whenever Super-Adaptoid enters or attacks, choose another target "
        "creature. If that creature has haste and Super-Adaptoid doesn't, "
        "put a haste counter on Super-Adaptoid. Do the same for flying, "
        "first strike, double strike, deathtouch, indestructible, lifelink, "
        "menace, reach, trample, and vigilance."
    ),
)
KATHRIL = _card(
    name="Kathril, Aspect Warper",
    type_line="Legendary Creature — Nightmare Beast",
    oracle_text=(
        "When Kathril enters, put a flying counter on it for each card "
        "in your graveyard with flying. Do this for each keyword among "
        "cards in your graveyard."
    ),
)


def test_parse_intent_none_is_supported_absence():
    req = parse_user_intent(None)
    assert req.kind == "none"
    assert req.supported is True
    assert parse_user_intent("   ").kind == "none"


def test_parse_clone_intent_reads_mana_cap_from_text():
    req = parse_user_intent("4 mana copy creatures")
    assert req.kind == "clone_creature_mv"
    assert req.supported is True
    assert req.max_mana_value == 4.0
    assert req.min_count == 2

    four_word = parse_user_intent("four-mana copy creatures that clone Aang")
    assert four_word.kind == "clone_creature_mv"
    assert four_word.max_mana_value == 4.0


def test_unsupported_intent_is_unverified_not_fulfilled():
    req = parse_user_intent("infinite extra combats and treasure storm")
    assert req.kind == "unsupported"
    assert req.supported is False
    admission = admit_engine_candidates(req, budget_valid_pool=[SPARK])
    assert admission.status == "unverified"
    assert verify_engine_in_deck(admission, [SPARK]) == "unverified"


def test_copy_on_entry_is_generic_oracle_not_a_name_list():
    assert is_copy_on_entry_creature(SPARK)
    assert is_copy_on_entry_creature(SAKASHIMA)
    assert is_copy_on_entry_creature(GENERIC_ETB)
    assert is_copy_on_entry_creature(ENTERS_AS_COPY)
    # Named lookalikes without copy-on-entry text are not clones.
    assert not is_copy_on_entry_creature(TOKEN_MAKER)
    assert not is_copy_on_entry_creature(SUPER_ADAPTOID)
    assert not is_copy_on_entry_creature(KATHRIL)
    assert not is_copy_on_entry_creature(
        _card(
            name="Clone",
            type_line="Enchantment",
            oracle_text="Creatures you control have haste.",
        )
    )


def test_keyword_counter_collectors_are_not_clones():
    assert is_keyword_counter_collector(SUPER_ADAPTOID)
    assert is_keyword_counter_collector(KATHRIL)
    assert not is_keyword_counter_collector(SPARK)


def test_legendary_copier_is_still_admitted():
    req = parse_user_intent("clone creatures")
    admission = admit_engine_candidates(req, [SAKASHIMA, SPARK])
    names = {c["name"] for c in admission.admitted}
    assert "Sakashima of a Thousand Faces" in names
    sakashima_rec = next(r for r in admission.records if r.name.startswith("Sakashima"))
    assert sakashima_rec.admitted is True
    assert sakashima_rec.legendary is True
    assert "legend rule is not a list ban" in sakashima_rec.reason


def test_admission_traces_budget_and_mv_unavailability():
    req = parse_user_intent("4 mana copy creatures")
    expensive = {**SPARK, "price_usd": 80.0}
    over_mv = _card(
        name="Huge Clone",
        cmc=6.0,
        oracle_text="You may have this creature enter as a copy of any creature.",
        price_usd=1.0,
    )
    budget_pool = [GENERIC_ETB]
    color_pool = [GENERIC_ETB, expensive, over_mv, SUPER_ADAPTOID]
    admission = admit_engine_candidates(
        req,
        budget_valid_pool=budget_pool,
        color_legal_pool=color_pool,
        per_card_ceiling=25.0,
    )
    by_name = {r.name: r for r in admission.records}
    assert by_name["Spark Double"].admitted is False
    assert "over budget" in by_name["Spark Double"].reason
    assert by_name["Huge Clone"].admitted is False
    assert "exceeds cap" in by_name["Huge Clone"].reason
    assert by_name["Super-Adaptoid"].admitted is False
    assert "keyword/counter collector" in by_name["Super-Adaptoid"].reason
    assert admission.status == "infeasible"
    assert verify_engine_in_deck(admission, [GENERIC_ETB]) == "infeasible"


def test_feasible_package_selects_at_least_two_when_available():
    req = parse_user_intent("copy creatures")
    pool = [SPARK, SAKASHIMA, GENERIC_ETB, TOKEN_MAKER]
    admission = admit_engine_candidates(req, pool)
    assert admission.status == "satisfied"
    assert len(admission.selected) == 2
    assert all(is_copy_on_entry_creature(c) for c in admission.selected)
    assert TOKEN_MAKER["name"] not in admission.selected_names


def test_verify_counts_oracle_clones_in_the_finished_list():
    req = parse_user_intent("4 mana copy creatures")
    admission = admit_engine_candidates(req, [SPARK, SAKASHIMA])
    assert verify_engine_in_deck(admission, [SPARK, SAKASHIMA]) == "satisfied"
    # A third unnamed clone still satisfies the trait contract.
    assert (
        verify_engine_in_deck(admission, [GENERIC_ETB, ENTERS_AS_COPY]) == "satisfied"
    )
    assert (
        verify_engine_in_deck(admission, [TOKEN_MAKER, SUPER_ADAPTOID]) == "unsatisfied"
    )


def test_finite_top_five_is_not_an_infinite_loop():
    aang = (
        "When Aang enters, look at the top five cards of your library. "
        "You may put a creature card with mana value 4 or less from among "
        "them onto the battlefield."
    )
    assert looks_like_finite_top_n_effect(aang)
    assert not claims_infinite_loop(aang)
    assert claims_infinite_loop("This is a deterministic infinite combo")


def test_oracle_text_joins_card_faces():
    mdfc = _card(
        name="Split Clone",
        oracle_text=None,
        card_faces=[
            {
                "oracle_text": "You may have this creature enter as a copy of a creature you control.",
                "type_line": "Creature — Illusion",
            },
            {"oracle_text": "Draw a card.", "type_line": "Instant"},
        ],
    )
    assert is_copy_on_entry_creature(mdfc)


def test_engine_rationale_dump_is_json_safe():
    req = parse_user_intent("clone creatures")
    admission = admit_engine_candidates(req, [SPARK, SAKASHIMA])
    dumped = engine_rationale_dump(admission)
    assert dumped["status"] == "satisfied"
    assert "Spark Double" in dumped["admitted"]
    assert dumped["records"]


def test_real_restricted_copiers_cannot_fulfill_free_entry_engine():
    import json
    from pathlib import Path

    from sabermetrics.pipeline.intent import has_verified_copy_target

    cards = json.loads(
        (Path(__file__).parent / "fixtures/cards/restricted_clones.json").read_text()
    )["cards"]
    cards = [{**card, "price_usd": 0.1} for card in cards]
    assert all(is_copy_on_entry_creature(card) for card in cards)
    assert not any(has_verified_copy_target(card) for card in cards)
    admission = admit_engine_candidates(
        parse_user_intent("4 mana copy creatures"), [*cards, SPARK, SAKASHIMA]
    )
    assert admission.selected_names == {SPARK["name"], SAKASHIMA["name"]}
    assert verify_engine_in_deck(admission, cards) == "unsatisfied"
    assert verify_engine_in_deck(admission, [SPARK, SAKASHIMA]) == "satisfied"


def test_unrestricted_legend_handling_is_prioritized_over_cheap_regular_copy():
    admission = admit_engine_candidates(
        parse_user_intent("4 mana copy creatures"),
        [{**GENERIC_ETB, "price_usd": 0.1, "cmc": 2}, SPARK, SAKASHIMA],
    )
    assert admission.selected_names == {SPARK["name"], SAKASHIMA["name"]}

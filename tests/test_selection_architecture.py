from sabermetrics.analytics.cvar import compute_replacement_value
from sabermetrics.intelligence.selection import retain_candidates
from sabermetrics.intelligence.strategy import assess_plan, make_plan, reserve_plan
from sabermetrics.pipeline.deck_builder import _tokenize_engine_traits


def card(name, text="", types="Enchantment — Aura", cmc=1, score=0.1):
    return {
        "name": name,
        "id": name,
        "oracle_text": text,
        "type_line": types,
        "cmc": cmc,
        "price_usd": 1.0,
        "role_tags": '["draw"]',
        "_cvar_score": score,
    }


def test_package_and_evidence_survive_large_unrelated_pool():
    filler = [card(str(i), score=0.9) for i in range(3000)]
    curiosity = card(
        "Curiosity",
        "Whenever enchanted creature deals damage to an opponent, you may draw a card.",
    )
    overlooked = card("Independent cohort card", score=0.01)
    overlooked["_selection_inclusion"] = 0.8
    selected = retain_candidates(filler + [curiosity, overlooked], {"Curiosity"})
    assert {"Curiosity", "Independent cohort card"} <= {c["name"] for c in selected}
    assert len(selected) < 700


def test_draw_tag_cannot_prune_a_physical_land():
    land = card("Draw land", types="Land", score=0)
    pool = [card(str(i), score=0.9) for i in range(1000)] + [land]
    assert land in retain_candidates(pool, set())


def test_damage_draw_plan_requires_actual_commander_damage():
    commander = card(
        "Trigger commander",
        "Whenever you cast a noncreature spell, it deals 1 damage to each opponent.",
        "Legendary Creature",
    )
    plan = make_plan(commander, "curiosity effects", 5)
    assert plan.requirements["opponent_damage_draw"] == 2
    a = card(
        "First draw aura",
        "Whenever enchanted creature deals damage to an opponent, you may draw a card.",
    )
    b = card(
        "Draw partner",
        'As long as this creature is paired, each has "Whenever this creature deals damage to an opponent, draw a card."',
        "Creature",
    )
    combat = card(
        "Combat only",
        "Whenever enchanted creature deals combat damage to an opponent, draw a card.",
    )
    package = reserve_plan(plan, [a, b, combat], 100)
    assert a in package and b in package
    assert assess_plan(plan, [a, b])["counts"]["opponent_damage_draw"] == 2
    missing = assess_plan(plan, [a, combat])
    assert "opponent_damage_draw" in missing["missing"]
    no_damage = card(
        "Other commander",
        "Whenever you cast a noncreature spell, draw a card.",
        "Creature",
    )
    assert make_plan(no_damage, "curiosity effects").archetype == "general"


def test_printing_rarity_does_not_change_replacement_value():
    a = card("Same oracle")
    a["rarity"] = "common"
    b = {**a, "rarity": "mythic"}
    assert compute_replacement_value(a) == compute_replacement_value(b)


def test_tokenizer_does_not_turn_noncreature_into_creature():
    assert "creature" not in _tokenize_engine_traits(["noncreature spells"])


def test_typal_requirements_follow_text_not_commander_identity():
    for tribe in ["Goblin", "Dragon", "Vampire"]:
        commander = card(
            "Synthetic", f"Whenever you cast a {tribe} spell, draw a card.", "Creature"
        )
        plan = make_plan(commander, None)
        assert plan.requirements == {"creature_type:" + tribe.lower(): 16}


def test_vivi_zero_activation_and_noncombat_draw_have_verified_capabilities():
    from sabermetrics.intelligence.cards import facts_for

    vivi = card(
        "Synthetic mana commander",
        "{0}: Add X mana in any combination of {U} and/or {R}, where X is this creature's power. Activate only during your turn and only once each turn.",
        "Legendary Creature",
    )
    assert "power_based_mana_once_per_turn" in facts_for(vivi).capabilities
    niv = card(
        "Synthetic source payoff",
        "Whenever a source you control deals noncombat damage to an opponent, you draw that many cards.",
        "Creature",
    )
    assert "draw_on_opponent_damage" in facts_for(niv).capabilities


def test_unknown_alternative_requirement_is_not_a_free_cast():
    from sabermetrics.analytics.effective_cost import compute_effective_cmc

    c = card(
        "Unknown payment",
        "You may perform an unspecified action rather than pay this spell's mana cost.",
        "Instant",
        5,
    )
    assert compute_effective_cmc(c) == 5


def test_fetch_land_is_eligible_without_claiming_direct_mana():
    from sabermetrics.intelligence.cards import facts_for, usable_land

    card = {
        "name": "Scalding Tarn",
        "type_line": "Land",
        "oracle_text": "{T}, Pay 1 life, Sacrifice Scalding Tarn: Search your library for an Island or Mountain card, put it onto the battlefield, then shuffle.",
    }
    assert usable_land(card, ["U", "R"])
    assert not facts_for(card).land_colors
    assert not usable_land(card, ["G"])


def test_land_play_is_not_a_cast():
    from sabermetrics.analytics.effective_cost import casting_options

    assert not casting_options(
        {"name": "Island", "type_line": "Basic Land — Island", "cmc": 0}
    )[0]["is_cast"]

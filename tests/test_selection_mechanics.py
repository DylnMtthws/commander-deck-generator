"""Mechanical facts: conditional capabilities, role priority, casting options.

Fixtures are printed public oracle text (Gatherer/Scryfall wording) plus
synthetic cards for shapes that need an isolated negative control. Every
assertion is about a *shape*: a capability is only claimed when the printed
text says so, and a missing capability is an unknown, never a denial.
"""

import json

import pytest

from sabermetrics.analytics.effective_cost import (
    casting_options,
    compute_effective_cmc,
    parse_alternative_costs,
)
from sabermetrics.intelligence.cards import (
    VERSION,
    annotate,
    facts_for,
    order_roles,
    primary_role,
)
from tests.fixtures.grounding.public_card_facts import BRAZEN_BORROWER, SOL_RING


def card(name, text="", types="Creature", **kwargs):
    return {"name": name, "oracle_text": text, "type_line": types, **kwargs}


# ---------------------------------------------------------------------------
# Public oracle fixtures
# ---------------------------------------------------------------------------

CURIOSITY = card(
    "Curiosity",
    "Enchant creature\nWhenever enchanted creature deals damage to a player, draw a card.",
    "Enchantment — Aura",
)
TANDEM_LOOKOUT = card(
    "Tandem Lookout",
    "Soulbond (You may pair this creature with another unpaired creature when either enters.)\n"
    "This creature and the creature it's paired with each have \"Whenever this creature deals "
    'combat damage to a player, draw a card."',
)
NIV_MIZZET_VISIONARY = card(
    "Niv-Mizzet, Visionary",
    "Flying\nWhenever a creature you control deals combat damage to a player, draw that many cards.",
    "Legendary Creature — Dragon Avatar",
)
FIREBRAND_ARCHER = card(
    "Firebrand Archer",
    "Whenever you cast a noncreature spell, Firebrand Archer deals 1 damage to each opponent.",
)
LOTUS_PETAL = card(
    "Lotus Petal",
    "{T}, Sacrifice Lotus Petal: Add one mana of any color.",
    "Artifact",
    cmc=0,
)
LIONS_EYE_DIAMOND = card(
    "Lion's Eye Diamond",
    "{T}, Sacrifice Lion's Eye Diamond: Discard your hand. Add three mana of any one color.",
    "Artifact",
)
MOX_OPAL = card(
    "Mox Opal",
    "Metalcraft — {T}: Add one mana of any color. Activate only if you control three or more artifacts.",
    "Legendary Artifact",
)
ELVISH_SPIRIT_GUIDE = card(
    "Elvish Spirit Guide",
    "Exile this card from your hand: Add {G}.",
    "Creature — Elf Spirit",
)
JESKAS_WILL = card(
    "Jeska's Will",
    "Choose one. If you control a commander as you cast this spell, you may choose both.\n"
    "• Add {R} for each card in target opponent's hand.\n"
    "• Exile the top three cards of your library. You may play them this turn.",
    "Sorcery",
    cmc=3,
)
SELVALA = card(
    "Selvala, Heart of the Wilds",
    "{T}: Add X mana in any combination of colors, where X is the greatest power "
    "among creatures you control.",
    "Legendary Creature — Elf Scout",
)
FORCE_OF_WILL = card(
    "Force of Will",
    "You may pay 1 life and exile a blue card from your hand rather than pay this "
    "spell's mana cost.\nCounter target spell.",
    "Instant",
    cmc=5,
    mana_cost="{3}{U}{U}",
)
FIERCE_GUARDIANSHIP = card(
    "Fierce Guardianship",
    "If you control a commander, you may cast this spell without paying its mana cost.\n"
    "Counter target noncreature spell.",
    "Instant",
    cmc=3,
    mana_cost="{2}{U}",
)


# ---------------------------------------------------------------------------
# Conditional payoff shapes
# ---------------------------------------------------------------------------


def test_any_damage_draw_is_separated_from_combat_only_draw():
    curiosity = facts_for(CURIOSITY)
    assert "draw_on_opponent_damage" in curiosity.capabilities
    assert "draw_on_combat_damage" not in curiosity.capabilities
    assert (
        "requires_a_damage_source"
        in curiosity.capability_conditions["draw_on_opponent_damage"]
    )

    niv = facts_for(NIV_MIZZET_VISIONARY)
    assert "draw_on_combat_damage" in niv.capabilities
    # Combat-restricted draw must never be promoted to any-damage draw.
    assert "draw_on_opponent_damage" not in niv.capabilities
    assert (
        "requires_connecting_in_combat"
        in niv.capability_conditions["draw_on_combat_damage"]
    )


def test_draw_that_many_is_a_variable_draw_with_its_condition():
    niv = facts_for(NIV_MIZZET_VISIONARY)
    assert "draw_that_many" in niv.capabilities
    assert "draw" in niv.roles
    assert (
        "draw_amount_depends_on_variable_state"
        in niv.capability_conditions["draw_that_many"]
    )

    variable = facts_for(
        card(
            "Counter", "Draw cards equal to the number of Elves you control.", "Sorcery"
        )
    )
    assert "draw_variable" in variable.capabilities


def test_granted_quoted_trigger_is_unknown_not_a_claimed_capability():
    facts = facts_for(TANDEM_LOOKOUT)
    assert "draw_on_opponent_damage" not in facts.capabilities
    assert "granted_abilities_in_quoted_text_not_modeled" in facts.unknown


def test_noncreature_cast_damage_requires_a_cast_not_a_copy():
    archer = facts_for(FIREBRAND_ARCHER)
    assert "noncreature_cast_damage" in archer.capabilities
    assert (
        "requires_noncreature_spell_density"
        in archer.capability_conditions["noncreature_cast_damage"]
    )
    copier = facts_for(
        card(
            "Echo Mage",
            "Whenever you copy an instant or sorcery spell, Echo Mage deals 1 damage to each opponent.",
        )
    )
    assert "noncreature_cast_damage" not in copier.capabilities


def test_power_based_mana_marks_the_once_per_turn_restriction():
    limited = facts_for(
        card(
            "Grove Warden",
            "Once during each of your turns, you may add an amount of {G} equal to "
            "the greatest power among creatures you control.",
        )
    )
    assert "power_based_mana" in limited.capabilities
    assert "power_based_mana_once_per_turn" in limited.capabilities
    assert "once_per_turn_only" in limited.capability_conditions["power_based_mana"]

    unlimited = facts_for(SELVALA)
    assert "power_based_mana" in unlimited.capabilities
    # No printed restriction means no once-per-turn claim either way.
    assert "power_based_mana_once_per_turn" not in unlimited.capabilities
    assert (
        "mana_amount_depends_on_creature_power"
        in unlimited.capability_conditions["power_based_mana"]
    )


# ---------------------------------------------------------------------------
# Mana sources: repeatable vs burst
# ---------------------------------------------------------------------------


def test_tap_sacrifice_is_burst_mana_not_repeatable_ramp():
    petal = facts_for(LOTUS_PETAL)
    assert "burst_mana" in petal.capabilities
    assert "mana_source" not in petal.capabilities
    assert "ramp" not in petal.roles
    assert (
        "requires_sacrificing_the_source" in petal.capability_conditions["burst_mana"]
    )
    assert (
        "burst_mana_is_not_repeatable_ramp" in petal.capability_conditions["burst_mana"]
    )


def test_discard_and_sacrifice_mana_states_both_costs():
    led = facts_for(LIONS_EYE_DIAMOND)
    conditions = led.capability_conditions["burst_mana"]
    assert "burst_mana" in led.capabilities
    assert "requires_sacrificing_the_source" in conditions
    assert "requires_discarding_your_hand" in conditions


def test_metalcraft_mana_is_a_source_with_the_artifact_condition():
    opal = facts_for(MOX_OPAL)
    assert "mana_source" in opal.capabilities
    assert "ramp" in opal.roles
    assert (
        "requires_metalcraft_three_artifacts"
        in opal.capability_conditions["mana_source"]
    )


def test_spirit_guide_is_burst_mana_from_exile_not_a_cast():
    guide = facts_for(ELVISH_SPIRIT_GUIDE)
    assert "burst_mana" in guide.capabilities
    assert (
        "exiled_from_hand_instead_of_being_cast"
        in guide.capability_conditions["burst_mana"]
    )
    assert "ramp" not in guide.roles


def test_ritual_spell_mana_is_burst_with_a_variable_amount():
    will = facts_for(JESKAS_WILL)
    conditions = will.capability_conditions["burst_mana"]
    assert "burst_mana" in will.capabilities
    assert "one_shot_spell_mana" in conditions
    assert "mana_amount_varies" in conditions
    assert "ramp" not in will.roles

    ritual = facts_for(card("Dark Ritual", "Add {B}{B}{B}.", "Instant"))
    assert "burst_mana" in ritual.capabilities
    assert "mana_source" not in ritual.capabilities


def test_treasure_creation_is_burst_mana_requiring_a_sacrifice():
    treasure = facts_for(
        card("Sunlit Marsh", "Create three Treasure tokens.", "Sorcery")
    )
    assert "burst_mana" in treasure.capabilities
    assert (
        "requires_sacrificing_a_treasure"
        in treasure.capability_conditions["burst_mana"]
    )


def test_triggered_mana_is_not_a_mana_source():
    trigger = facts_for(
        card("Grove Elder", "Whenever a land you control enters, add {G}.")
    )
    assert "triggered_mana" in trigger.capabilities
    assert "mana_source" not in trigger.capabilities
    assert "burst_mana" not in trigger.capabilities
    assert "ramp" not in trigger.roles


def test_plain_tap_source_still_reads_as_repeatable_ramp():
    sol_ring = facts_for(dict(SOL_RING))
    assert "mana_source" in sol_ring.capabilities
    assert "burst_mana" not in sol_ring.capabilities
    assert "ramp" in sol_ring.roles


def test_creature_mana_notes_summoning_sickness():
    llanowar = facts_for(
        card("Llanowar Elves", "{T}: Add {G}.", "Creature — Elf Druid")
    )
    assert "creature_mana_requires_no_summoning_sickness" in (
        llanowar.capability_conditions["mana_source"]
    )


# ---------------------------------------------------------------------------
# Tutors
# ---------------------------------------------------------------------------


def test_unrestricted_tutor_records_destination_and_lack_of_restriction():
    demonic = facts_for(
        card(
            "Demonic Tutor",
            "Search your library for a card, then shuffle and put that card into your hand.",
            "Sorcery",
        )
    )
    assert "tutor" in demonic.capabilities
    assert "tutor_to_hand" in demonic.capabilities
    assert "tutor" in demonic.roles
    assert "tutor_unrestricted" in demonic.capability_conditions["tutor"]


def test_restricted_tutor_records_its_target_condition():
    worldly = facts_for(
        card(
            "Worldly Tutor",
            "Search your library for a creature card, reveal it, then shuffle and put "
            "that card on top of your library.",
            "Instant",
        )
    )
    assert "tutor_to_top" in worldly.capabilities
    conditions = worldly.capability_conditions["tutor"]
    assert "tutor_limited_to_creature" in conditions
    assert "tutored_card_still_has_to_be_drawn" in conditions


def test_land_search_stays_with_the_land_shapes_and_is_not_a_tutor():
    rampant = facts_for(
        card(
            "Rampant Growth",
            "Search your library for a basic land card, put it onto the battlefield "
            "tapped, then shuffle.",
            "Sorcery",
        )
    )
    assert "tutor" not in rampant.capabilities
    assert "land_ramp" in rampant.capabilities


def test_same_name_search_is_not_a_usable_tutor():
    facts = facts_for(
        card(
            "Mirror Search",
            "Search your library for a creature card with the same name as target "
            "creature, put it onto the battlefield, then shuffle.",
            "Instant",
        )
    )
    assert "tutor" not in facts.capabilities
    assert facts.exclusion
    assert "same_name_search_target_availability_unknown" in facts.unknown


# ---------------------------------------------------------------------------
# Unknowns and role priority
# ---------------------------------------------------------------------------


def test_version_is_bumped_so_prepared_snapshots_invalidate():
    assert VERSION == "card-facts.v3"
    assert facts_for(CURIOSITY).version == VERSION


def test_unrecognised_text_is_unknown_not_a_denial():
    facts = facts_for(card("Odd One", "Whenever this creature blocks, scry 1."))
    assert "no_supported_shape_detected" in facts.unknown
    assert facts.capabilities == []
    missing = facts_for(card("No Text", ""))
    assert "oracle_text_unavailable" in missing.unknown
    convoke = facts_for(
        card(
            "Convoker", "Convoke\nCreate a 1/1 white Soldier creature token.", "Sorcery"
        )
    )
    assert "convoke_mana_reduction_amount_unknown" in convoke.unknown


def test_role_priority_puts_land_first_and_is_not_alphabetical():
    assert order_roles({"draw", "land", "board_wipe"})[0] == "land"
    assert primary_role({"draw", "ramp"}) == "ramp"
    assert primary_role({"board_wipe", "removal"}) == "removal"
    assert primary_role(set()) == "utility"
    # Unknown roles keep a stable tail rather than jumping to the front.
    assert order_roles({"aristocrats", "draw"}) == ["draw", "aristocrats"]


def test_annotated_primary_role_of_a_drawing_land_is_land():
    facts = facts_for(
        card(
            "Study Hall",
            "{T}: Add {U}.\n{2}, {T}, Sacrifice this land: Draw a card.",
            "Land",
        )
    )
    assert facts.primary_role == "land"
    annotated = annotate(
        card(
            "Study Hall",
            "{T}: Add {U}.\n{2}, {T}, Sacrifice this land: Draw a card.",
            "Land",
        )
    )
    assert json.loads(annotated["role_tags"])[0] == "land"
    assert annotated["_primary_role"] == "land"


def test_annotation_keeps_discovery_only_roles_separate_from_verified_roles():
    annotated = annotate(
        card(
            "Mystery Engine",
            "Whenever this creature blocks, scry 1.",
            role_tags='["ramp", "counters"]',
        )
    )
    roles = json.loads(annotated["role_tags"])
    # An unverified discovery claim does not become a functional role...
    assert "ramp" not in roles
    assert "ramp" in annotated["_unverified_discovery_roles"]
    # ...and it is still visible as discovery-only, not erased as false.
    assert annotated["_discovery_roles"] == ["ramp", "counters"]
    assert "ramp" in annotated["_discovery_only_roles"]
    # Specialized discovery tags survive; verified roles are listed apart.
    assert "counters" in roles
    assert annotated["_verified_roles"] == facts_for(annotated).roles


def test_no_names_are_forced_beyond_basic_land_rules():
    """An unknown name with land text is read from the text, not a name list."""
    facts = facts_for(card("Nonexistent Land", "{T}: Add {G}.", "Land"))
    assert facts.land_colors == ["G"]
    basic = facts_for(card("Forest", "", "Basic Land — Forest"))
    assert basic.land_colors == ["G"]
    assert "oracle_text_unavailable" not in basic.unknown


# ---------------------------------------------------------------------------
# casting_options
# ---------------------------------------------------------------------------


def _methods(card_dict):
    return {o["method"]: o for o in casting_options(card_dict)}


def test_every_option_has_the_documented_shape_and_includes_a_normal_cast():
    options = casting_options({"cmc": 4, "oracle_text": "Flying"})
    assert options[0] == {
        "method": "normal",
        "mana_paid": 4.0,
        "conditions": [],
        "is_cast": True,
    }
    for option in casting_options(FORCE_OF_WILL):
        assert set(option) == {"method", "mana_paid", "conditions", "is_cast"}
        assert isinstance(option["mana_paid"], float)
        assert isinstance(option["conditions"], list)
        assert isinstance(option["is_cast"], bool)
        assert option["mana_paid"] >= 0.0


def test_printed_cmc_is_never_changed_by_option_analysis():
    subject = dict(FORCE_OF_WILL)
    before = json.dumps(subject, sort_keys=True)
    casting_options(subject)
    compute_effective_cmc(subject)
    assert json.dumps(subject, sort_keys=True) == before
    assert subject["cmc"] == 5
    assert _methods(subject)["normal"]["mana_paid"] == 5.0


def test_pitch_cost_records_card_and_life_requirements():
    option = _methods(FORCE_OF_WILL)["alternative_cost"]
    assert option["mana_paid"] == 0.0
    assert option["is_cast"] is True
    assert "costs_1_life" in option["conditions"]
    assert "requires_exiling_a_blue_card_from_hand" in option["conditions"]
    assert compute_effective_cmc(FORCE_OF_WILL) == 0.0


def test_commander_free_cast_records_the_commander_requirement():
    option = _methods(FIERCE_GUARDIANSHIP)["free_cast"]
    assert option["mana_paid"] == 0.0
    assert option["is_cast"] is True
    assert "requires_controlling_a_commander" in option["conditions"]


def test_unparsed_alternative_requirement_is_stated_rather_than_assumed_free():
    subject = card(
        "Odd Pitch",
        "You may perform an unusual ritual rather than pay this spell's mana cost.",
        "Instant",
        cmc=4,
    )
    option = _methods(subject)["alternative_cost"]
    assert option["conditions"] == ["alternative_cost_requirement_not_parsed"]


def test_phyrexian_mana_pays_life_for_each_phyrexian_symbol():
    subject = {
        "cmc": 3,
        "mana_cost": "{2}{W/P}",
        "oracle_text": "Destroy target creature.",
    }
    option = _methods(subject)["phyrexian"]
    assert option["mana_paid"] == 2.0
    assert option["is_cast"] is True
    assert option["conditions"] == ["pays_2_life_for_each_of_1_phyrexian_symbols"]
    assert compute_effective_cmc(subject) == 2.0


def test_convoke_does_not_assume_free_and_marks_the_unknown_reduction():
    subject = {
        "cmc": 4,
        "oracle_text": "Convoke\nCreate four 1/1 white Soldier tokens.",
    }
    option = _methods(subject)["convoke"]
    assert option["mana_paid"] == 4.0
    assert "convoke_reduction_amount_unknown" in option["conditions"]
    assert compute_effective_cmc(subject) == 4.0


@pytest.mark.parametrize(
    ("method", "text"),
    [("unearth", "Unearth {1}{B}"), ("transmute", "Transmute {1}{U}{U}")],
)
def test_graveyard_and_tutor_abilities_are_not_casts(method, text):
    subject = {"cmc": 5, "oracle_text": text}
    option = _methods(subject)[method]
    assert option["is_cast"] is False
    assert option["conditions"]
    # A non-cast option must never lower the effective casting cost.
    assert compute_effective_cmc(subject) == 5.0


def test_alternative_casts_keep_their_conditions_and_lower_effective_cost():
    subject = {"cmc": 5, "oracle_text": "Flying\nEvoke {1}{B}"}
    option = _methods(subject)["evoke"]
    assert option["is_cast"] is True
    assert option["mana_paid"] == 2.0
    assert "sacrificed_when_it_enters" in option["conditions"]
    assert compute_effective_cmc(subject) == 2.0
    assert parse_alternative_costs(subject["oracle_text"])  # unchanged public API


def test_flashback_is_a_cast_from_the_graveyard():
    subject = {"cmc": 4, "oracle_text": "Draw two cards.\nFlashback {5}{U}"}
    option = _methods(subject)["flashback"]
    assert option["is_cast"] is True
    assert option["mana_paid"] == 6.0
    assert "cast_only_from_your_graveyard" in option["conditions"]
    assert compute_effective_cmc(subject) == 4.0


def test_split_faces_are_listed_when_stored_text_supports_them():
    subject = {
        "name": "Wear // Tear",
        "cmc": 4,
        "mana_cost": "{1}{R} // {W}",
        "type_line": "Instant // Instant",
        "oracle_text": "Destroy target artifact.\n\nDestroy target enchantment.",
    }
    options = _methods(subject)
    faces = [o for o in casting_options(subject) if o["method"] == "split_face"]
    assert len(faces) == 2
    assert {o["mana_paid"] for o in faces} == {2.0, 1.0}
    assert any("face=Wear" in o["conditions"] for o in faces)
    assert options["normal"]["mana_paid"] == 4.0
    assert compute_effective_cmc(subject) == 1.0


def test_adventure_face_is_marked_and_the_land_back_face_is_not_a_cast_option():
    adventure = {
        "name": "Bonecrusher Giant",
        "cmc": 3,
        "type_line": "Creature — Giant // Instant — Adventure",
        "card_faces": [
            {
                "name": "Bonecrusher Giant",
                "mana_cost": "{2}{R}",
                "type_line": "Creature — Giant",
            },
            {
                "name": "Stomp",
                "mana_cost": "{1}{R}",
                "type_line": "Instant — Adventure",
            },
        ],
        "oracle_text": "Whenever this creature becomes the target of a spell, it deals 2 damage.",
    }
    options = casting_options(adventure)
    stomp = [o for o in options if o["method"] == "adventure"]
    assert len(stomp) == 1
    assert stomp[0]["mana_paid"] == 2.0
    assert "face=Stomp" in stomp[0]["conditions"]
    assert (
        "adventure_exiles_the_card_before_the_creature_is_cast"
        in stomp[0]["conditions"]
    )

    modal = {
        "name": "Shatterskull Smashing // Shatterskull, the Hammer Pass",
        "cmc": 1,
        "type_line": "Sorcery // Land",
        "card_faces": [
            {
                "name": "Shatterskull Smashing",
                "mana_cost": "{X}{X}{R}",
                "type_line": "Sorcery",
            },
            {
                "name": "Shatterskull, the Hammer Pass",
                "mana_cost": "",
                "type_line": "Land",
            },
        ],
        "oracle_text": "Deals X damage divided as you choose.",
    }
    assert [o["method"] for o in casting_options(modal)] == ["normal", "split_face"]


def test_missing_face_costs_are_reported_instead_of_guessed():
    subject = dict(BRAZEN_BORROWER, cmc=BRAZEN_BORROWER["mana_value"])
    options = casting_options(subject)
    assert [o["method"] for o in options] == ["normal"]
    assert "face_costs_not_available_in_stored_text" in options[0]["conditions"]
    assert compute_effective_cmc(subject) == subject["cmc"]

"""Focused tests for card_functions.function_profile.

Fixture names are used only to look cards up; the recognizer itself never sees
a meaningful name (see test_rename_invariance).
"""

from sabermetrics.intelligence.card_functions import function_profile

FIXTURES = {
    "Pongify": {
        "name": "Pongify",
        "oracle_text": "Destroy target creature. It can't be regenerated. Its controller creates a 3/3 green Ape creature token.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Instant",
    },
    "Generous Gift": {
        "name": "Generous Gift",
        "oracle_text": "Destroy target permanent. Its controller creates a 3/3 green Elephant creature token.",
        "mana_cost": "{2}{W}",
        "cmc": 3.0,
        "type_line": "Instant",
    },
    "Young Pyromancer": {
        "name": "Young Pyromancer",
        "oracle_text": "Whenever you cast an instant or sorcery spell, create a 1/1 red Elemental creature token.",
        "mana_cost": "{1}{R}",
        "cmc": 2.0,
        "type_line": "Creature — Human Shaman",
    },
    "Windfall": {
        "name": "Windfall",
        "oracle_text": "Each player discards their hand, then draws cards equal to the greatest number of cards a player discarded this way.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Sorcery",
    },
    "Elven Ambush": {
        "name": "Elven Ambush",
        "oracle_text": "Create a 1/1 green Elf Warrior creature token for each Elf you control.",
        "mana_cost": "{3}{G}",
        "cmc": 4.0,
        "type_line": "Instant",
    },
    "Elvish Harbinger": {
        "name": "Elvish Harbinger",
        "oracle_text": "When this creature enters, you may search your library for an Elf card, reveal it, then shuffle and put that card on top.\n{T}: Add one mana of any color.",
        "mana_cost": "{2}{G}",
        "cmc": 3.0,
        "type_line": "Creature — Elf Druid",
    },
    "Pearl Medallion": {
        "name": "Pearl Medallion",
        "oracle_text": "White spells you cast cost {1} less to cast.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
    },
    "Sensei's Divining Top": {
        "name": "Sensei's Divining Top",
        "oracle_text": "{1}: Look at the top three cards of your library, then put them back in any order.\n{T}: Draw a card, then put this artifact on top of its owner's library.",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "type_line": "Artifact",
    },
    "Treasure Cruise": {
        "name": "Treasure Cruise",
        "oracle_text": "Delve (Each card you exile from your graveyard while casting this spell pays for {1}.)\nDraw three cards.",
        "mana_cost": "{7}{U}",
        "cmc": 8.0,
        "type_line": "Sorcery",
    },
    "Dig Through Time": {
        "name": "Dig Through Time",
        "oracle_text": "Delve (Each card you exile from your graveyard while casting this spell pays for {1}.)\nLook at the top seven cards of your library. Put two of them into your hand and the rest on the bottom of your library in any order.",
        "mana_cost": "{6}{U}{U}",
        "cmc": 8.0,
        "type_line": "Instant",
    },
    "Counterspell": {
        "name": "Counterspell",
        "oracle_text": "Counter target spell.",
        "mana_cost": "{U}{U}",
        "cmc": 2.0,
        "type_line": "Instant",
    },
    "Swords to Plowshares": {
        "name": "Swords to Plowshares",
        "oracle_text": "Exile target creature. Its controller gains life equal to its power.",
        "mana_cost": "{W}",
        "cmc": 1.0,
        "type_line": "Instant",
    },
    "Nature's Lore": {
        "name": "Nature's Lore",
        "oracle_text": "Search your library for a Forest card, put that card onto the battlefield, then shuffle.",
        "mana_cost": "{1}{G}",
        "cmc": 2.0,
        "type_line": "Sorcery",
    },
    "Llanowar Elves": {
        "name": "Llanowar Elves",
        "oracle_text": "{T}: Add {G}.",
        "mana_cost": "{G}",
        "cmc": 1.0,
        "type_line": "Creature — Elf Druid",
    },
    "Lightning Greaves": {
        "name": "Lightning Greaves",
        "oracle_text": "Equipped creature has haste and shroud. (It can't be the target of spells or abilities.)\nEquip {0}",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact — Equipment",
    },
    "Swiftfoot Boots": {
        "name": "Swiftfoot Boots",
        "oracle_text": "Equipped creature has hexproof and haste. (It can't be the target of spells or abilities your opponents control. It can attack and {T} no matter when it came under your control.)\nEquip {1} ({1}: Attach to target creature you control. Equip only as a sorcery.)",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact — Equipment",
    },
    "Beast Whisperer": {
        "name": "Beast Whisperer",
        "oracle_text": "Whenever you cast a creature spell, draw a card.",
        "mana_cost": "{2}{G}{G}",
        "cmc": 4.0,
        "type_line": "Creature — Elf Druid",
    },
    "Rhystic Study": {
        "name": "Rhystic Study",
        "oracle_text": "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Enchantment",
    },
    "Brainstorm": {
        "name": "Brainstorm",
        "oracle_text": "Draw three cards, then put two cards from your hand on top of your library in any order.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Instant",
    },
    "Demonic Tutor": {
        "name": "Demonic Tutor",
        "oracle_text": "Search your library for a card, put that card into your hand, then shuffle.",
        "mana_cost": "{1}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
    },
}
KINDS = {
    "interaction",
    "mana",
    "cost_reduction",
    "tutor",
    "selection",
    "tokens",
    "haste",
    "protection",
    "card_flow",
}


def details(profile, kind):
    return {fn["detail"] for fn in profile["functions"] if fn["kind"] == kind}


def prereqs(profile, kind):
    return {
        p
        for fn in profile["functions"]
        if fn["kind"] == kind
        for p in fn["prerequisites"]
    }


def profile_of(name):
    return function_profile(FIXTURES[name])


def synthetic(oracle, type_line="Instant"):
    return function_profile(
        {
            "name": "Synthetic Card",
            "oracle_text": oracle,
            "type_line": type_line,
            "mana_cost": "{1}",
            "cmc": 1.0,
        }
    )


# --- schema and universal invariants ------------------------------------------------


def test_schema_and_evidence_is_exact_substring():
    for name, card in FIXTURES.items():
        p = function_profile(card)
        assert set(p) == {
            "status",
            "coverage",
            "functions",
            "creature_types",
            "evidence",
            "caveats",
        }, name
        assert p["status"] in {"supported", "partial", "unknown", "none"}, name
        assert p["caveats"], name
        assert any("never proves" in c for c in p["caveats"]), name
        for fn in p["functions"]:
            assert set(fn) == {
                "kind",
                "detail",
                "prerequisites",
                "evidence",
                "confidence",
            }, (name, fn)
            assert fn["kind"] in KINDS, (name, fn)
            assert fn["detail"] and isinstance(fn["prerequisites"], list), (name, fn)
            for item in fn["evidence"]:
                assert item in card["oracle_text"], (name, item)
        for item in p["evidence"]:
            assert item in card["oracle_text"], (name, item)


def test_rename_invariance():
    for name, card in FIXTURES.items():
        renamed = dict(card, name="Zzz Placeholder 000")
        assert function_profile(renamed) == function_profile(card), name


def test_every_fixture_is_recognized_at_least_partially():
    for name, card in FIXTURES.items():
        p = function_profile(card)
        assert p["functions"], name
        assert p["status"] in {"supported", "partial"}, name


# --- critical cards must expose their real functions ---------------------------------


def test_removal_with_token_downside():
    pongify = profile_of("Pongify")
    assert "destroy_target:creature" in details(pongify, "interaction")
    assert "removal_rider:no_regeneration" in details(pongify, "interaction")
    token = [d for d in details(pongify, "tokens") if "3/3_Ape" in d]
    assert token and "controlled_by=target_controller" in token[0]
    gift = profile_of("Generous Gift")
    assert "destroy_target:permanent" in details(gift, "interaction")
    assert any("3/3_Elephant" in d for d in details(gift, "tokens"))


def test_token_kinds_static_conditional_and_variable():
    pyromancer = profile_of("Young Pyromancer")
    assert any("1/1_Elemental:count=1" in d for d in details(pyromancer, "tokens"))
    assert "trigger:cast_instant_or_sorcery" in prereqs(pyromancer, "tokens")
    ambush = profile_of("Elven Ambush")
    assert any("1/1_Elf_Warrior:count=variable" in d for d in details(ambush, "tokens"))
    assert "requires:elves_on_battlefield" in prereqs(ambush, "tokens")


def test_printed_creature_types_not_token_types():
    assert profile_of("Young Pyromancer")["creature_types"] == ["Human", "Shaman"]
    assert "Elemental" not in profile_of("Young Pyromancer")["creature_types"]
    assert profile_of("Elven Ambush")["creature_types"] == []
    assert profile_of("Elvish Harbinger")["creature_types"] == ["Elf", "Druid"]
    assert profile_of("Lightning Greaves")["creature_types"] == []


def test_wheel_card_flow():
    windfall = profile_of("Windfall")
    assert "wheel:each_player_discards_hand_then_redraws" in details(
        windfall, "card_flow"
    )
    assert any("symmetrical" in c for c in windfall["caveats"])


def test_tutor_destinations_and_restrictions():
    harbinger = profile_of("Elvish Harbinger")
    assert "tutor_to_top_of_library:Elf" in details(harbinger, "tutor")
    assert "trigger:enters_the_battlefield" in prereqs(harbinger, "tutor")
    assert "mana_ability:any_color" in details(harbinger, "mana")
    assert "cost:tap_self" in prereqs(harbinger, "mana")
    assert "tutor_to_hand:any" in details(profile_of("Demonic Tutor"), "tutor")
    restricted = synthetic(
        "Search your library for a creature card with mana value 3 or less, "
        "put that card into your hand, then shuffle.",
        "Sorcery",
    )
    assert "tutor_to_hand:creature:mv_le_3" in details(restricted, "tutor")


def test_mana_source_vs_land_ramp_vs_nonland_search():
    assert "mana_ability:{G}" in details(profile_of("Llanowar Elves"), "mana")
    assert "requires:creature_without_summoning_sickness" in prereqs(
        profile_of("Llanowar Elves"), "mana"
    )
    assert "ramp_land_onto_battlefield:Forest" in details(
        profile_of("Nature's Lore"), "mana"
    )
    nonland = synthetic(
        "Search your library for a creature card, put that card onto the "
        "battlefield, then shuffle.",
        "Sorcery",
    )
    assert details(nonland, "mana") == set()
    assert "tutor_to_battlefield:creature" in details(nonland, "tutor")


def test_cost_reduction_generic_vs_colored_and_delve():
    medallion = profile_of("Pearl Medallion")
    assert "spell_cost_reduction:generic:{1}" in details(medallion, "cost_reduction")
    assert "applies:white_spells" in prereqs(medallion, "cost_reduction")
    colored = synthetic("Green spells you cast cost {G} less to cast.", "Artifact")
    assert "spell_cost_reduction:colored:{G}" in details(colored, "cost_reduction")
    for name in ("Treasure Cruise", "Dig Through Time"):
        p = profile_of(name)
        assert "delve:exile_graveyard_cards_to_pay_generic" in details(
            p, "cost_reduction"
        )
        assert "cost:graveyard_cards" in prereqs(p, "cost_reduction")


def test_selection_shapes_are_distinguished():
    top = profile_of("Sensei's Divining Top")
    assert "reorder_top_cards:3" in details(top, "selection")
    assert "self_to_top_of_library" in details(top, "selection")
    assert "draw:1" in details(top, "card_flow")
    assert "cost:activate_{1}" in prereqs(top, "selection")
    dig = profile_of("Dig Through Time")
    assert "dig_select:look_7_take_2_rest_bottom" in details(dig, "selection")
    assert "cards_to_hand:2" in details(dig, "card_flow")
    assert "reorder_top_cards:7" not in details(dig, "selection")
    brainstorm = profile_of("Brainstorm")
    assert "draw:3" in details(brainstorm, "card_flow")
    assert "hand_to_top_of_library:2" in details(brainstorm, "selection")
    assert "draw:3" in details(profile_of("Treasure Cruise"), "card_flow")


def test_granted_haste_and_protection_vs_own_keyword():
    greaves = profile_of("Lightning Greaves")
    assert "grants_haste:equipped_creature" in details(greaves, "haste")
    assert "grants_shroud:equipped_creature" in details(greaves, "protection")
    assert "requires:attached_to_creature" in prereqs(greaves, "haste")
    boots = profile_of("Swiftfoot Boots")
    assert "grants_hexproof:equipped_creature" in details(boots, "protection")
    assert "grants_haste:equipped_creature" in details(boots, "haste")
    own = synthetic("Haste", "Creature — Goblin")
    assert details(own, "haste") == {"self_haste"}
    assert prereqs(own, "haste") == set()


def test_triggered_card_flow_prerequisites():
    assert "trigger:cast_creature_spell" in prereqs(
        profile_of("Beast Whisperer"), "card_flow"
    )
    rhystic = profile_of("Rhystic Study")
    assert "trigger:opponent_casts_spell" in prereqs(rhystic, "card_flow")
    assert any("optional or conditional" in c for c in rhystic["caveats"])


def test_interaction_targets():
    assert "counter_target:spell" in details(profile_of("Counterspell"), "interaction")
    swords = profile_of("Swords to Plowshares")
    assert "exile_target:creature" in details(swords, "interaction")
    assert swords["status"] == "partial"  # lifegain rider is not modeled
    assert any("unmodeled clause" in c for c in swords["caveats"])


# --- synthetic negatives -------------------------------------------------------------


def test_no_oracle_text_is_none_status():
    p = synthetic("", "Creature — Bear")
    assert p["status"] == "none" and p["functions"] == []
    assert p["creature_types"] == ["Bear"] and p["caveats"]


def test_unrecognized_text_is_unknown_not_equivalent():
    p = synthetic("Whenever the moon waxes, the chorus answers.", "Enchantment")
    assert p["status"] == "unknown" and p["functions"] == []
    assert any("equivalence cannot be implied" in c for c in p["caveats"])
    flyer = synthetic("Flying", "Creature — Bird")
    assert flyer["status"] == "unknown"
    assert any("unmodeled clause" in c for c in flyer["caveats"])


def test_token_text_never_becomes_creature_types():
    p = synthetic("Create a 2/2 black Zombie creature token.", "Enchantment")
    assert p["creature_types"] == []
    assert any("2/2_Zombie" in d for d in details(p, "tokens"))


def test_no_false_positive_interaction_or_mana():
    p = synthetic("Target player gains 4 life.", "Instant")
    assert details(p, "interaction") == set() and details(p, "mana") == set()
    assert p["status"] == "unknown"


if __name__ == "__main__":
    failures = 0
    for key, value in sorted(globals().items()):
        if key.startswith("test_") and callable(value):
            try:
                value()
                print("PASS", key)
            except AssertionError as exc:
                failures += 1
                print("FAIL", key, exc)
    print("failures:", failures)


def test_function_confidence_is_not_full_card_coverage():
    for card in FIXTURES.values():
        p = function_profile(card)
        assert p["coverage"] == "incomplete"
        assert all(f["confidence"] in {"supported", "partial"} for f in p["functions"])


def test_opponent_draw_is_not_controller_draw():
    p = synthetic("Target opponent draws two cards.")
    assert "recipient:opponent" in prereqs(p, "card_flow")
    assert "recipient:controller" not in prereqs(p, "card_flow")


def test_adventure_cast_condition_does_not_become_generic_verified_trigger():
    p = synthetic(
        "Whenever you cast a creature spell that has an Adventure, draw a card.",
        "Creature — Human",
    )
    assert all(f["confidence"] == "partial" for f in p["functions"])
    assert any("adventure" in key for key in prereqs(p, "card_flow"))


def test_source_subtypes_exclude_back_face_and_tokens():
    p = synthetic(
        "Create a 1/1 green Elf creature token.",
        "Creature — Human Wizard // Enchantment",
    )
    assert p["creature_types"] == ["Human", "Wizard"]


def test_complex_activation_cost_is_not_silently_free():
    p = synthetic("{T}, Discard a card: Draw two cards.", "Creature — Human")
    assert all(f["confidence"] == "partial" for f in p["functions"])


def test_top_self_return_does_not_get_verified_plain_draw():
    p = profile_of("Sensei's Divining Top")
    assert any(
        f["confidence"] == "partial" for f in p["functions"] if f["kind"] == "card_flow"
    )

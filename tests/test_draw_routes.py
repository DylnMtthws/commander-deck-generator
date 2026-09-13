"""Executable pytest suite for draw_routes.route_profile using the frozen
public-fixtures.json next to this file. No external dependencies."""

import pytest

from sabermetrics.intelligence.draw_routes import parse_mana, route_profile

# Exact frozen public Oracle catalog; mutations below are synthetic adversaries.
FIXTURES = {
    "Action News Crew": {
        "name": "Action News Crew",
        "oracle_text": "Vigilance\nChannel — {6}, Discard this card: Put a +1/+1 counter on each creature you control. Draw a card.",
        "mana_cost": "{1}{W}",
        "cmc": 2.0,
        "type_line": "Creature — Human Citizen",
        "color_identity": '["W"]',
    },
    "Shoreline Salvager": {
        "name": "Shoreline Salvager",
        "oracle_text": "Whenever this creature deals combat damage to a player, if you control an Island, you may draw a card.",
        "mana_cost": "{3}{B}",
        "cmc": 4.0,
        "type_line": "Creature — Surrakar",
        "color_identity": '["B"]',
    },
    "Moldervine Reclamation": {
        "name": "Moldervine Reclamation",
        "oracle_text": "Whenever a creature you control dies, you gain 1 life and draw a card.",
        "mana_cost": "{3}{B}{G}",
        "cmc": 5.0,
        "type_line": "Enchantment",
        "color_identity": '["B", "G"]',
    },
    "Sanctuary Warden": {
        "name": "Sanctuary Warden",
        "oracle_text": "Flying\nThis creature enters with two shield counters on it.\nWhenever this creature enters or attacks, you may remove a counter from a creature or planeswalker you control. If you do, draw a card and create a 1/1 green and white Citizen creature token.",
        "mana_cost": "{4}{W}{W}",
        "cmc": 6.0,
        "type_line": "Creature — Angel Soldier",
        "color_identity": '["W"]',
    },
    "Mystic Remora": {
        "name": "Mystic Remora",
        "oracle_text": "Cumulative upkeep {1} (At the beginning of your upkeep, put an age counter on this permanent, then sacrifice it unless you pay its upkeep cost for each age counter on it.)\nWhenever an opponent casts a noncreature spell, you may draw a card unless that player pays {4}.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Enchantment",
        "color_identity": '["U"]',
    },
    "Phyrexian Arena": {
        "name": "Phyrexian Arena",
        "oracle_text": "At the beginning of your upkeep, you draw a card and you lose 1 life.",
        "mana_cost": "{1}{B}{B}",
        "cmc": 3.0,
        "type_line": "Enchantment",
        "color_identity": '["B"]',
    },
    "Rhystic Study": {
        "name": "Rhystic Study",
        "oracle_text": "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Enchantment",
        "color_identity": '["U"]',
    },
    "The Unagi of Kyoshi Island": {
        "name": "The Unagi of Kyoshi Island",
        "oracle_text": "Flash\nWard—Waterbend {4}. (Whenever this creature becomes the target of a spell or ability an opponent controls, counter it unless that player pays {4}. They can tap their artifacts and creatures to help. Each one pays for {1}.)\nWhenever an opponent draws their second card each turn, you draw two cards.",
        "mana_cost": "{3}{U}{U}",
        "cmc": 5.0,
        "type_line": "Legendary Creature — Serpent",
        "color_identity": '["U"]',
    },
    "Notion Thief": {
        "name": "Notion Thief",
        "oracle_text": "Flash\nIf an opponent would draw a card except the first one they draw in each of their draw steps, instead that player skips that draw and you draw a card.",
        "mana_cost": "{2}{U}{B}",
        "cmc": 4.0,
        "type_line": "Creature — Human Rogue",
        "color_identity": '["B", "U"]',
    },
    "Insight Engine": {
        "name": "Insight Engine",
        "oracle_text": "{2}, {T}: Put a charge counter on this artifact, then draw a card for each charge counter on it.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Artifact",
        "color_identity": '["U"]',
    },
    "Weave Fate": {
        "name": "Weave Fate",
        "oracle_text": "Draw two cards.",
        "mana_cost": "{3}{U}",
        "cmc": 4.0,
        "type_line": "Instant",
        "color_identity": '["U"]',
    },
    "Quick Study": {
        "name": "Quick Study",
        "oracle_text": "Draw two cards.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Instant",
        "color_identity": '["U"]',
    },
    "Opt": {
        "name": "Opt",
        "oracle_text": "Scry 1. (Look at the top card of your library. You may put that card on the bottom.)\nDraw a card.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Instant",
        "color_identity": '["U"]',
    },
    "Ponder": {
        "name": "Ponder",
        "oracle_text": "Look at the top three cards of your library, then put them back in any order. You may shuffle.\nDraw a card.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Sorcery",
        "color_identity": '["U"]',
    },
    "Divination": {
        "name": "Divination",
        "oracle_text": "Draw two cards.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Sorcery",
        "color_identity": '["U"]',
    },
    "Harmonize": {
        "name": "Harmonize",
        "oracle_text": "Draw three cards.",
        "mana_cost": "{2}{G}{G}",
        "cmc": 4.0,
        "type_line": "Sorcery",
        "color_identity": '["G"]',
    },
    "Skullclamp": {
        "name": "Skullclamp",
        "oracle_text": "Equipped creature gets +1/-1.\nWhenever equipped creature dies, draw two cards.\nEquip {1}",
        "mana_cost": "{1}",
        "cmc": 1.0,
        "type_line": "Artifact — Equipment",
        "color_identity": "[]",
    },
    "Idol of Oblivion": {
        "name": "Idol of Oblivion",
        "oracle_text": "{T}: Draw a card. Activate only if you created a token this turn.\n{8}, {T}, Sacrifice this artifact: Create a 10/10 colorless Eldrazi creature token.",
        "mana_cost": "{2}",
        "cmc": 2.0,
        "type_line": "Artifact",
        "color_identity": "[]",
    },
    "Bonder's Ornament": {
        "name": "Bonder's Ornament",
        "oracle_text": "{T}: Add one mana of any color.\n{4}, {T}: Each player who controls a permanent named Bonder's Ornament draws a card.",
        "mana_cost": "{3}",
        "cmc": 3.0,
        "type_line": "Artifact",
        "color_identity": "[]",
    },
    "Tocasia's Welcome": {
        "name": "Tocasia's Welcome",
        "oracle_text": "Whenever one or more creatures you control with mana value 3 or less enter, draw a card. This ability triggers only once each turn.",
        "mana_cost": "{2}{W}",
        "cmc": 3.0,
        "type_line": "Enchantment",
        "color_identity": '["W"]',
    },
    "Welcoming Vampire": {
        "name": "Welcoming Vampire",
        "oracle_text": "Flying\nWhenever one or more other creatures you control with power 2 or less enter, draw a card. This ability triggers only once each turn.",
        "mana_cost": "{2}{W}",
        "cmc": 3.0,
        "type_line": "Creature — Vampire",
        "color_identity": '["W"]',
    },
    "Esper Sentinel": {
        "name": "Esper Sentinel",
        "oracle_text": "Whenever an opponent casts their first noncreature spell each turn, draw a card unless that player pays {X}, where X is this creature's power.",
        "mana_cost": "{W}",
        "cmc": 1.0,
        "type_line": "Artifact Creature — Human Soldier",
        "color_identity": '["W"]',
    },
    "Ophidian Eye": {
        "name": "Ophidian Eye",
        "oracle_text": "Flash (You may cast this spell any time you could cast an instant.)\nEnchant creature\nWhenever enchanted creature deals damage to an opponent, you may draw a card.",
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Enchantment — Aura",
        "color_identity": '["U"]',
    },
    "Curiosity": {
        "name": "Curiosity",
        "oracle_text": "Enchant creature\nWhenever enchanted creature deals damage to an opponent, you may draw a card.",
        "mana_cost": "{U}",
        "cmc": 1.0,
        "type_line": "Enchantment — Aura",
        "color_identity": '["U"]',
    },
    "Tandem Lookout": {
        "name": "Tandem Lookout",
        "oracle_text": 'Soulbond (You may pair this creature with another unpaired creature when either enters. They remain paired for as long as you control both of them.)\nAs long as Tandem Lookout is paired with another creature, each of those creatures has "Whenever this creature deals damage to an opponent, draw a card."',
        "mana_cost": "{2}{U}",
        "cmc": 3.0,
        "type_line": "Creature — Human Scout",
        "color_identity": '["U"]',
    },
    "Inspiration": {
        "name": "Inspiration",
        "oracle_text": "Target player draws two cards.",
        "mana_cost": "{3}{U}",
        "cmc": 4.0,
        "type_line": "Instant",
        "color_identity": '["U"]',
    },
    "Read the Bones": {
        "name": "Read the Bones",
        "oracle_text": "Scry 2, then draw two cards. You lose 2 life. (To scry 2, look at the top two cards of your library, then put any number of them on the bottom and the rest on top in any order.)",
        "mana_cost": "{2}{B}",
        "cmc": 3.0,
        "type_line": "Sorcery",
        "color_identity": '["B"]',
    },
    "Sign in Blood": {
        "name": "Sign in Blood",
        "oracle_text": "Target player draws two cards and loses 2 life.",
        "mana_cost": "{B}{B}",
        "cmc": 2.0,
        "type_line": "Sorcery",
        "color_identity": '["B"]',
    },
    "Deadly Dispute": {
        "name": "Deadly Dispute",
        "oracle_text": 'As an additional cost to cast this spell, sacrifice an artifact or creature.\nDraw two cards and create a Treasure token. (It\'s an artifact with "{T}, Sacrifice this token: Add one mana of any color.")',
        "mana_cost": "{1}{B}",
        "cmc": 2.0,
        "type_line": "Instant",
        "color_identity": '["B"]',
    },
    "Village Rites": {
        "name": "Village Rites",
        "oracle_text": "As an additional cost to cast this spell, sacrifice a creature.\nDraw two cards.",
        "mana_cost": "{B}",
        "cmc": 1.0,
        "type_line": "Instant",
        "color_identity": '["B"]',
    },
    "Treasure Cruise": {
        "name": "Treasure Cruise",
        "oracle_text": "Delve (Each card you exile from your graveyard while casting this spell pays for {1}.)\nDraw three cards.",
        "mana_cost": "{7}{U}",
        "cmc": 8.0,
        "type_line": "Sorcery",
        "color_identity": '["U"]',
    },
    "Thoughtcast": {
        "name": "Thoughtcast",
        "oracle_text": "Affinity for artifacts (This spell costs {1} less to cast for each artifact you control.)\nDraw two cards.",
        "mana_cost": "{4}{U}",
        "cmc": 5.0,
        "type_line": "Sorcery",
        "color_identity": '["U"]',
    },
    "Reconnaissance Mission": {
        "name": "Reconnaissance Mission",
        "oracle_text": "Whenever a creature you control deals combat damage to a player, you may draw a card.\nCycling {2} ({2}, Discard this card: Draw a card.)",
        "mana_cost": "{2}{U}{U}",
        "cmc": 4.0,
        "type_line": "Enchantment",
        "color_identity": '["U"]',
    },
    "Military Intelligence": {
        "name": "Military Intelligence",
        "oracle_text": "Whenever you attack with two or more creatures, draw a card.",
        "mana_cost": "{1}{U}",
        "cmc": 2.0,
        "type_line": "Enchantment",
        "color_identity": '["U"]',
    },
}

ROUTE_KEYS = {
    "kind",
    "mana",
    "setup_mana",
    "cost",
    "draw_count",
    "net_cards",
    "repeatable",
    "prerequisites",
    "evidence",
    "supported",
}
KINDS = {"spell", "etb", "attack", "combat_damage", "activated", "channel", "triggered"}


def card(name, **overrides):
    c = dict(FIXTURES[name])
    c.update(overrides)
    return c


def only_route(profile):
    assert len(profile["routes"]) == 1, profile
    return profile["routes"][0]


def renamed(name, new_name):
    c = card(name)
    c["oracle_text"] = c["oracle_text"].replace(name, new_name)
    c["name"] = new_name
    return c


# ------------------------------------------------------------------ schema
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_schema_every_fixture(name):
    p = route_profile(card(name))
    assert set(p) == {"routes", "unknown_clauses", "complete"}
    assert isinstance(p["complete"], bool)
    assert all(isinstance(u, str) for u in p["unknown_clauses"])
    assert p["complete"] == (not p["unknown_clauses"])
    for r in p["routes"]:
        assert set(r) == ROUTE_KEYS
        assert r["kind"] in KINDS
        assert r["mana"] is None or isinstance(r["mana"], float)
        assert r["setup_mana"] is None or isinstance(r["setup_mana"], float)
        assert r["cost"] is None or isinstance(r["cost"], str)
        assert isinstance(r["repeatable"], bool) and isinstance(r["supported"], bool)
        assert isinstance(r["prerequisites"], list) and isinstance(r["evidence"], str)
        assert r["supported"] == ("unsupported" not in r["prerequisites"])


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_rename_invariance_every_fixture(name):
    assert route_profile(renamed(name, "Zzyzx Placeholder")) == route_profile(
        card(name)
    )


# ------------------------------------------------------------------ channel
def test_action_news_crew_channel_actual_cost():
    r = only_route(p := route_profile(card("Action News Crew")))
    assert p["complete"]
    assert r["kind"] == "channel" and r["mana"] == 6.0 and r["cost"] == "{6}"
    assert r["setup_mana"] == 0.0 and r["draw_count"] == 1 and r["net_cards"] == 0
    assert (
        r["repeatable"] is False
        and r["prerequisites"] == ["discard"]
        and r["supported"]
    )


def test_channel_rider_is_unknown_not_swallowed():
    c = card("Action News Crew")
    c["oracle_text"] = c["oracle_text"] + " You gain 3 life."
    p = route_profile(c)
    assert p["routes"] == [] and not p["complete"]
    assert p["unknown_clauses"] == [
        (
            "Channel — {6}, Discard this card: Put a +1/+1 counter on each creature you control. "
            "Draw a card. You gain 3 life."
        )
    ]


def test_channel_x_cost_override_unsupported():
    c = card("Action News Crew")
    c["oracle_text"] = c["oracle_text"].replace("{6}", "{X}{W}")
    r = only_route(route_profile(c))
    assert r["kind"] == "channel" and r["mana"] is None and r["cost"] == "{X}{W}"
    assert r["supported"] is False and "unsupported" in r["prerequisites"]


def test_channel_plain_draw_two():
    c = card(
        "Action News Crew",
        oracle_text="Channel — {2}{U}, Discard this card: Draw two cards.",
    )
    r = only_route(route_profile(c))
    assert r["mana"] == 3.0 and r["draw_count"] == 2 and r["net_cards"] == 1


# ------------------------------------------------------------- shoreline
def test_shoreline_salvager_island_gate():
    r = only_route(p := route_profile(card("Shoreline Salvager")))
    assert p["complete"] and r["kind"] == "combat_damage"
    assert r["mana"] == 0.0 and r["cost"] == "" and r["setup_mana"] == 4.0
    assert r["prerequisites"] == ["island", "combat_damage", "attack"]
    assert r["draw_count"] == 1 and r["repeatable"] and r["supported"]


def test_shoreline_named_self_reference_equivalent():
    c = card("Shoreline Salvager")
    c["oracle_text"] = c["oracle_text"].replace("this creature", "Shoreline Salvager")
    assert route_profile(c) == route_profile(card("Shoreline Salvager"))


def test_shoreline_without_island_gate_is_unknown():
    c = card("Shoreline Salvager")
    c["oracle_text"] = c["oracle_text"].replace("if you control an Island, ", "")
    p = route_profile(c)
    assert p["routes"] == [] and not p["complete"] and len(p["unknown_clauses"]) == 1


# ------------------------------------------------------------ moldervine
def test_moldervine_requires_creature_death():
    r = only_route(p := route_profile(card("Moldervine Reclamation")))
    assert p["complete"] and r["kind"] == "triggered" and r["repeatable"]
    assert r["prerequisites"] == ["creature_death"]
    assert r["mana"] == 0.0 and r["setup_mana"] == 5.0 and r["cost"] == ""


def test_moldervine_mutation_any_creature_is_unknown():
    c = card("Moldervine Reclamation")
    c["oracle_text"] = "Whenever a creature dies, you gain 1 life and draw a card."
    p = route_profile(c)
    assert p["routes"] == [] and p["unknown_clauses"] == [c["oracle_text"]]


# ------------------------------------------------------------- sanctuary
def test_sanctuary_warden_etb_and_attack():
    p = route_profile(card("Sanctuary Warden"))
    assert p["complete"] and [r["kind"] for r in p["routes"]] == ["etb", "attack"]
    etb, atk = p["routes"]
    assert (
        etb["mana"] == 6.0 and etb["setup_mana"] == 0.0 and etb["cost"] == "{4}{W}{W}"
    )
    assert (
        etb["net_cards"] == 0
        and not etb["repeatable"]
        and etb["prerequisites"] == ["counters"]
    )
    assert atk["mana"] == 0.0 and atk["setup_mana"] == 6.0 and atk["cost"] == ""
    assert atk["repeatable"] and atk["prerequisites"] == ["attack", "counters"]


def test_sanctuary_rider_mutation_unknown():
    c = card("Sanctuary Warden")
    c["oracle_text"] = c["oracle_text"].replace(
        "creature token.", "creature token. Then draw a card."
    )
    p = route_profile(c)
    assert p["routes"] == [] and not p["complete"]


# ---------------------------------------------------------- tax triggers
def test_mystic_remora_explicit_tax_and_upkeep():
    r = only_route(p := route_profile(card("Mystic Remora")))
    assert p["complete"] and r["kind"] == "triggered" and r["setup_mana"] == 1.0
    assert r["prerequisites"] == [
        "opponent_cast",
        "opponent_payment",
        "cumulative_upkeep",
    ]
    assert "{4}" in r["evidence"] and "noncreature" in r["evidence"]


def test_rhystic_study_generic_tax():
    r = only_route(p := route_profile(card("Rhystic Study")))
    assert p["complete"] and r["prerequisites"] == ["opponent_cast", "opponent_payment"]
    assert r["mana"] == 0.0 and r["setup_mana"] == 3.0 and "{1}" in r["evidence"]


def test_esper_sentinel_variable_tax_unknown():
    p = route_profile(card("Esper Sentinel"))
    assert p["routes"] == [] and not p["complete"]


# ------------------------------------------------------ other triggers
def test_phyrexian_arena_upkeep_life():
    r = only_route(p := route_profile(card("Phyrexian Arena")))
    assert (
        p["complete"]
        and r["prerequisites"] == ["life", "own_upkeep"]
        and r["repeatable"]
    )
    assert r["mana"] == 0.0 and r["setup_mana"] == 3.0 and r["draw_count"] == 1


def test_unagi_opponent_second_draw():
    r = only_route(p := route_profile(card("The Unagi of Kyoshi Island")))
    assert p["complete"] and r["draw_count"] == 2 and r["net_cards"] == 2
    assert r["prerequisites"] == ["opponent_second_draw"] and r["setup_mana"] == 5.0


@pytest.mark.parametrize(
    "name",
    [
        "Notion Thief",
        "Skullclamp",
        "Idol of Oblivion",
        "Bonder's Ornament",
        "Tocasia's Welcome",
        "Welcoming Vampire",
        "Ophidian Eye",
        "Curiosity",
        "Tandem Lookout",
        "Inspiration",
        "Read the Bones",
        "Sign in Blood",
        "Reconnaissance Mission",
        "Military Intelligence",
        "Deadly Dispute",
    ],
)
def test_unrecognized_draw_text_reported_unknown(name):
    p = route_profile(card(name))
    assert p["routes"] == [] and not p["complete"] and p["unknown_clauses"]
    assert all("draw" in u.lower() for u in p["unknown_clauses"])


# ---------------------------------------------------------------- spells
@pytest.mark.parametrize(
    "name,mana,draw,net",
    [
        ("Opt", 1.0, 1, 0),
        ("Ponder", 1.0, 1, 0),
        ("Divination", 3.0, 2, 1),
        ("Quick Study", 3.0, 2, 1),
        ("Weave Fate", 4.0, 2, 1),
        ("Harmonize", 4.0, 3, 2),
    ],
)
def test_spell_draw_net_cards(name, mana, draw, net):
    r = only_route(p := route_profile(card(name)))
    assert p["complete"] and r["kind"] == "spell" and r["supported"]
    assert (
        r["mana"] == mana
        and r["setup_mana"] == 0.0
        and r["cost"] == FIXTURES[name]["mana_cost"]
    )
    assert r["draw_count"] == draw and r["net_cards"] == net and not r["repeatable"]
    assert r["prerequisites"] == []


def test_village_rites_sacrifice_prerequisite():
    r = only_route(p := route_profile(card("Village Rites")))
    assert p["complete"] and r["prerequisites"] == ["sacrifice"] and r["supported"]
    assert r["mana"] == 1.0 and r["draw_count"] == 2


@pytest.mark.parametrize(
    "name,keyword", [("Treasure Cruise", "Delve"), ("Thoughtcast", "Affinity")]
)
def test_alternate_cost_reduces_confidence(name, keyword):
    p = route_profile(card(name))
    r = only_route(p)
    assert r["supported"] is False and "unsupported" in r["prerequisites"]
    assert not p["complete"] and any(keyword in u for u in p["unknown_clauses"])


def test_spell_extra_unmodelled_clause_unsupported():
    c = card("Opt", oracle_text="Counter target spell.\nDraw a card.")
    p = route_profile(c)
    r = only_route(p)
    assert r["supported"] is False and p["unknown_clauses"] == ["Counter target spell."]


def test_spell_additional_discard_cost_counts_cards():
    c = card(
        "Divination",
        oracle_text="As an additional cost to cast this spell, discard a card.\nDraw two cards.",
    )
    r = only_route(p := route_profile(c))
    assert p["complete"] and r["prerequisites"] == ["discard"] and r["net_cards"] == 0


def test_spell_unknown_additional_cost_unsupported():
    c = card(
        "Divination",
        oracle_text="As an additional cost to cast this spell, exile a card from your graveyard.\nDraw two cards.",
    )
    r = only_route(p := route_profile(c))
    assert r["supported"] is False and not p["complete"]


def test_spell_with_x_cost_unsupported():
    r = only_route(route_profile(card("Divination", mana_cost="{X}{U}")))
    assert r["mana"] is None and r["supported"] is False


# ------------------------------------------------------------- activated
def test_basic_tap_activated_draw():
    c = card("Insight Engine", oracle_text="{2}, {T}: Draw a card.")
    r = only_route(p := route_profile(c))
    assert p["complete"] and r["kind"] == "activated" and r["repeatable"]
    assert r["mana"] == 2.0 and r["setup_mana"] == 3.0 and r["cost"] == "{2}, {T}"
    assert (
        r["draw_count"] == 1 and r["net_cards"] == 1 and r["prerequisites"] == ["tap"]
    )


def test_activated_with_rider_is_unknown():
    c = card(
        "Insight Engine",
        oracle_text="{2}, {T}: Draw a card. Activate only during your turn.",
    )
    p = route_profile(c)
    assert p["routes"] == [] and p["unknown_clauses"] == [c["oracle_text"]]


def test_activated_hybrid_cost_unsupported():
    c = card("Insight Engine", oracle_text="{U/R}, {T}: Draw a card.")
    r = only_route(route_profile(c))
    assert r["mana"] is None and r["supported"] is False


# ---------------------------------------------------------------- misc
def test_no_draw_text_is_empty_and_complete():
    c = card("Action News Crew", oracle_text="Vigilance\nFlying")
    assert route_profile(c) == {"routes": [], "unknown_clauses": [], "complete": True}


def test_permanent_unknown_casting_cost_unsupported_route():
    r = only_route(route_profile(card("Rhystic Study", mana_cost="{2/U}{U}")))
    assert r["setup_mana"] is None and r["supported"] is False


@pytest.mark.parametrize(
    "cost,expected",
    [
        ("{2}{U}", 3.0),
        ("{U}", 1.0),
        ("{4}{W}{W}", 6.0),
        ("{0}", 0.0),
        ("{C}{C}", 2.0),
        ("{X}{U}", None),
        ("{2/U}", None),
        ("{U/P}", None),
        ("{T}", None),
        ("2U", None),
        ("{2}U", None),
        ("", None),
        (None, None),
        ("{2} {U}", None),
    ],
)
def test_parse_mana(cost, expected):
    assert parse_mana(cost) == expected


def test_missing_or_malformed_text_remains_unknown():
    for c in (
        {},
        {"oracle_text": None, "type_line": "Creature"},
        {"oracle_text": "", "type_line": None},
    ):
        assert not route_profile(c)["complete"]


def test_draw_step_is_not_a_draw_route():
    assert route_profile(
        card(
            "Action News Crew",
            oracle_text="At the beginning of your draw step, you lose 1 life.",
        )
    )["complete"]
    assert not route_profile(
        card(
            "Action News Crew",
            oracle_text="At the beginning of your draw step, you lose 1 life.",
        )
    )["routes"]


def test_impulse_and_hand_access_are_unverified_not_absent():
    for text in (
        "Exile the top card of your library. You may play it this turn.",
        "Put the top card of your library into your hand.",
    ):
        assert not route_profile(card("Action News Crew", oracle_text=text))["complete"]


def test_numeric_overflow_mana_unknown():
    assert parse_mana("{" + "9" * 1000 + "}") is None


def test_charge_counter_draw_retains_cost_without_inventing_yield():
    r = only_route(p := route_profile(card("Insight Engine")))
    assert p["complete"] and r["supported"]
    assert (r["kind"], r["mana"], r["setup_mana"]) == ("activated", 2, 3)
    assert r["draw_count"] is None and r["net_cards"] is None
    assert r["prerequisites"] == ["tap", "counters"]
    assert route_profile(renamed("Insight Engine", "Synthetic Artifact")) == p


def test_charge_counter_route_rejects_unrecognized_rider():
    c = card("Insight Engine")
    c["oracle_text"] += " Discard two cards."
    assert not route_profile(c)["routes"]
    assert not route_profile(c)["complete"]


@pytest.mark.parametrize(
    "limitation",
    [
        "You can't draw cards.",
        "You cannot draw more than one card each turn.",
        "Players can’t draw cards.",
        "If you would draw a card, exile the top card of your library instead.",
        "If a player would draw a card, that player gains 1 life instead.",
    ],
)
def test_known_draw_with_unresolved_draw_limitation_is_not_supported(limitation):
    p = route_profile(card("Quick Study", oracle_text="Draw two cards.\n" + limitation))
    assert not p["complete"] and len(p["routes"]) == 1
    assert p["routes"][0]["supported"] is False
    assert "unsupported" in p["routes"][0]["prerequisites"]
    assert limitation in p["unknown_clauses"]


@pytest.mark.parametrize(
    "other",
    [
        "Whenever you gain life, draw that many cards.",
        "Your opponents can't draw cards.",
        "If an opponent would draw a card, that player gains 1 life instead.",
    ],
)
def test_unknown_other_draw_function_keeps_independent_known_route(other):
    c = card("Phyrexian Arena")
    c["oracle_text"] += "\n" + other
    p = route_profile(c)
    assert not p["complete"] and p["unknown_clauses"]
    assert len(p["routes"]) == 1 and p["routes"][0]["supported"]

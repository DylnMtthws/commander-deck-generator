"""Stdlib tests for commander_mana_support. Fixtures are inlined from the
frozen public Oracle records so tests do not depend on fixture-file shipping.
"""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sabermetrics"
    / "intelligence"
    / "draw_acceleration.py"
)
_SPEC = importlib.util.spec_from_file_location("draw_acceleration", _MODULE_PATH)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
commander_mana_support = _MOD.commander_mana_support

# Inlined public-fixtures.json Oracle records (unicode em dash type lines).
ACTION_NEWS_CREW = {
    "name": "Action News Crew",
    "mana_cost": "{1}{W}",
    "cmc": 2.0,
    "type_line": "Creature \u2014 Human Citizen",
    "oracle_text": (
        "Vigilance\n"
        "Channel \u2014 {6}, Discard this card: Put a +1/+1 counter on each "
        "creature you control. Draw a card."
    ),
}
GIADA = {
    "name": "Giada, Font of Hope",
    "mana_cost": "{1}{W}",
    "cmc": 2.0,
    "type_line": "Legendary Creature \u2014 Angel",
    "oracle_text": (
        "Flying, vigilance\n"
        "Each other Angel you control enters with an additional +1/+1 counter "
        "on it for each Angel you already control.\n"
        "{T}: Add {W}. Spend this mana only to cast an Angel spell."
    ),
}
INSPIRING_OVERSEER = {
    "name": "Inspiring Overseer",
    "mana_cost": "{2}{W}",
    "cmc": 3.0,
    "type_line": "Creature \u2014 Angel Cleric",
    "oracle_text": (
        "Flying\nWhen this creature enters, you gain 1 life and draw a card."
    ),
}
SANCTUARY_WARDEN = {
    "name": "Sanctuary Warden",
    "mana_cost": "{4}{W}{W}",
    "cmc": 6.0,
    "type_line": "Creature \u2014 Angel Soldier",
    "oracle_text": (
        "Flying\n"
        "This creature enters with two shield counters on it.\n"
        "Whenever this creature enters or attacks, you may remove a counter "
        "from a creature or planeswalker you control. If you do, draw a card "
        "and create a 1/1 green and white Citizen creature token."
    ),
}
VIVI = {
    "name": "Vivi Ornitier",
    "mana_cost": "{1}{U}{R}",
    "cmc": 3.0,
    "type_line": "Legendary Creature \u2014 Wizard",
    "oracle_text": (
        "{0}: Add X mana in any combination of {U} and/or {R}, where X is "
        "Vivi Ornitier's power. Activate only during your turn and only once "
        "each turn.\n"
        "Whenever you cast a noncreature spell, put a +1/+1 counter on "
        "Vivi Ornitier and it deals 1 damage to each opponent."
    ),
}

_RESULT_KEYS = {
    "status",
    "mana_by_color",
    "applicable_pips",
    "casting_only",
    "restrictions",
    "setup_requirements",
    "reason",
}


def _angel(**overrides):
    card = {
        "name": "Test Angel",
        "mana_cost": "{W}",
        "cmc": 1.0,
        "type_line": "Creature \u2014 Angel",
        "oracle_text": "Flying",
    }
    card.update(overrides)
    return card


class CommanderManaSupportTests(unittest.TestCase):
    def _assert_shape(self, result):
        self.assertEqual(set(result), _RESULT_KEYS)
        self.assertIsInstance(result["status"], str)
        self.assertIsInstance(result["mana_by_color"], dict)
        self.assertIsInstance(result["applicable_pips"], int)
        self.assertIsInstance(result["casting_only"], bool)
        self.assertIsInstance(result["restrictions"], list)
        self.assertIsInstance(result["setup_requirements"], list)
        self.assertIsInstance(result["reason"], str)
        self.assertGreater(len(result["reason"]), 0)

    def _assert_unsupported(self, result):
        self._assert_shape(result)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["mana_by_color"], {})
        self.assertEqual(result["applicable_pips"], 0)
        self.assertFalse(result["casting_only"])
        self.assertEqual(result["restrictions"], [])
        self.assertEqual(result["setup_requirements"], [])

    def _assert_giada_verified(self, result):
        self._assert_shape(result)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["mana_by_color"], {"W": 1})
        self.assertEqual(result["applicable_pips"], 1)
        self.assertTrue(result["casting_only"])
        self.assertEqual(result["restrictions"], ["casting_only_angel"])
        self.assertEqual(
            result["setup_requirements"],
            [
                "commander_on_battlefield",
                "commander_untapped",
                "summoning_sickness_cleared_or_haste",
            ],
        )

    def test_giada_inspiring_overseer_verified(self):
        result = commander_mana_support(GIADA, INSPIRING_OVERSEER, route_kind="cast")
        self._assert_giada_verified(result)

    def test_giada_sanctuary_warden_verified_single_pip(self):
        result = commander_mana_support(GIADA, SANCTUARY_WARDEN)
        self._assert_giada_verified(result)
        self.assertEqual(SANCTUARY_WARDEN["cmc"], 6.0)
        self.assertNotIn("cmc", result)
        self.assertLess(result["applicable_pips"], 2)

    def test_action_news_crew_cast_unsupported(self):
        as_commander = commander_mana_support(
            ACTION_NEWS_CREW, INSPIRING_OVERSEER, route_kind="cast"
        )
        as_card = commander_mana_support(GIADA, ACTION_NEWS_CREW, route_kind="cast")
        self._assert_unsupported(as_commander)
        self._assert_unsupported(as_card)

    def test_action_news_crew_channel_unsupported(self):
        crew_channel = commander_mana_support(
            ACTION_NEWS_CREW, ACTION_NEWS_CREW, route_kind="channel"
        )
        giada_channel = commander_mana_support(
            GIADA, ACTION_NEWS_CREW, route_kind="channel"
        )
        angel_channel = commander_mana_support(
            GIADA, INSPIRING_OVERSEER, route_kind="channel"
        )
        angel_activation = commander_mana_support(
            GIADA, INSPIRING_OVERSEER, route_kind="activation"
        )
        self._assert_unsupported(crew_channel)
        self._assert_unsupported(giada_channel)
        self._assert_unsupported(angel_channel)
        self._assert_unsupported(angel_activation)

    def test_unknown_commander_unsupported(self):
        unknown = {
            "name": "Unknown Legend",
            "mana_cost": "{2}{G}",
            "cmc": 3.0,
            "type_line": "Legendary Creature \u2014 Elf",
            "oracle_text": "Trample",
        }
        result = commander_mana_support(unknown, INSPIRING_OVERSEER)
        self._assert_unsupported(result)

    def test_no_mana_cost_unsupported(self):
        missing = _angel()
        del missing["mana_cost"]
        empty = _angel(mana_cost="")
        self._assert_unsupported(commander_mana_support(GIADA, missing))
        self._assert_unsupported(commander_mana_support(GIADA, empty))

    def test_wrong_color_only_unsupported(self):
        result = commander_mana_support(GIADA, _angel(mana_cost="{U}{U}", cmc=2.0))
        self._assert_unsupported(result)

    def test_hybrid_cost_unsupported(self):
        hybrid = commander_mana_support(GIADA, _angel(mana_cost="{W/U}", cmc=1.0))
        variable = commander_mana_support(GIADA, _angel(mana_cost="{X}{W}", cmc=1.0))
        malformed = commander_mana_support(GIADA, _angel(mana_cost="2W", cmc=2.0))
        self._assert_unsupported(hybrid)
        self._assert_unsupported(variable)
        self._assert_unsupported(malformed)

    def test_altered_restrictive_oracle_unsupported(self):
        combat_rider = copy.deepcopy(GIADA)
        combat_rider["oracle_text"] = GIADA["oracle_text"].replace(
            "{T}: Add {W}. Spend this mana only to cast an Angel spell.",
            "{T}: Add {W}. Spend this mana only to cast an Angel spell. "
            "Activate only during combat.",
        )
        paid_tap = copy.deepcopy(GIADA)
        paid_tap["oracle_text"] = GIADA["oracle_text"].replace(
            "{T}: Add {W}. Spend this mana only to cast an Angel spell.",
            "{1}, {T}: Add {W}. Spend this mana only to cast an Angel spell.",
        )
        self._assert_unsupported(
            commander_mana_support(combat_rider, INSPIRING_OVERSEER)
        )
        self._assert_unsupported(commander_mana_support(paid_tap, INSPIRING_OVERSEER))

    def test_restriction_on_separate_line_rejected(self):
        restricted = copy.deepcopy(GIADA)
        restricted["oracle_text"] += "\nActivate only during combat."
        self._assert_unsupported(commander_mana_support(restricted, INSPIRING_OVERSEER))

    def test_inputs_immutable(self):
        commander = copy.deepcopy(GIADA)
        card = copy.deepcopy(INSPIRING_OVERSEER)
        commander_snapshot = copy.deepcopy(commander)
        card_snapshot = copy.deepcopy(card)
        commander_mana_support(commander, card, route_kind="cast")
        self.assertEqual(commander, commander_snapshot)
        self.assertEqual(card, card_snapshot)
        self.assertEqual(commander["cmc"], GIADA["cmc"])
        self.assertEqual(card["cmc"], INSPIRING_OVERSEER["cmc"])

    def test_generic_can_pay_w(self):
        generic_angel = _angel(name="Generic Angel", mana_cost="{3}", cmc=3.0)
        result = commander_mana_support(GIADA, generic_angel)
        self._assert_giada_verified(result)

    def test_vivi_state_dependent_no_assumptions(self):
        result = commander_mana_support(VIVI, INSPIRING_OVERSEER, route_kind="cast")
        self._assert_shape(result)
        self.assertEqual(result["status"], "state_dependent")
        self.assertEqual(result["mana_by_color"], {})
        self.assertEqual(result["applicable_pips"], 0)
        self.assertFalse(result["casting_only"])
        self.assertEqual(result["restrictions"], ["own_turn", "once_each_turn"])
        self.assertEqual(
            result["setup_requirements"],
            [
                "commander_on_battlefield",
                "power_and_activation_state_required",
            ],
        )
        setup = result["setup_requirements"]
        self.assertNotIn("commander_untapped", setup)
        self.assertNotIn("summoning_sickness_cleared_or_haste", setup)
        self.assertNotIn("discount", result)
        self.assertNotIn("fixed_mana", result)
        joined = " ".join(setup).lower()
        self.assertNotIn("tap", joined)
        self.assertNotIn("summoning", joined)

    def test_oracle_mention_and_angelic_substring_do_not_match(self):
        oracle_mention = {
            "name": "Human Chaplain",
            "mana_cost": "{1}{W}",
            "cmc": 2.0,
            "type_line": "Creature \u2014 Human Cleric",
            "oracle_text": "When this creature enters, create a 1/1 white Angel token.",
        }
        angelic = _angel(
            name="Angelic Something",
            type_line="Creature \u2014 Human",
            oracle_text="Angelic blessing. Flying",
        )
        self._assert_unsupported(commander_mana_support(GIADA, oracle_mention))
        self._assert_unsupported(commander_mana_support(GIADA, angelic))

    def test_kindred_angel_spell_is_eligible(self):
        kindred = {
            "name": "Kindred Angel Charm",
            "mana_cost": "{W}",
            "cmc": 1.0,
            "type_line": "Kindred Enchantment \u2014 Angel",
            "oracle_text": "Flying",
        }
        self._assert_giada_verified(commander_mana_support(GIADA, kindred))

    def test_noncreature_commander_fail_closed(self):
        noncreature = copy.deepcopy(GIADA)
        noncreature["type_line"] = "Legendary Enchantment \u2014 Aura"
        self._assert_unsupported(
            commander_mana_support(noncreature, INSPIRING_OVERSEER)
        )


if __name__ == "__main__":
    unittest.main()

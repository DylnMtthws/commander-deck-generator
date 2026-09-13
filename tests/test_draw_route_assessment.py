"""Tests for assess_draw_routes. Parser and commander helpers are monkeypatched."""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from sabermetrics.intelligence import draw_route_assessment as ASSESSMENT

UNSUPPORTED_SUPPORT = {
    "status": "unsupported",
    "mana_by_color": {},
    "applicable_pips": 0,
    "casting_only": True,
    "restrictions": [],
    "setup_requirements": [],
    "reason": "no applicable commander mana",
}


def _route(**overrides):
    base = {
        "kind": "spell",
        "mana": 3.0,
        "setup_mana": 0,
        "cost": "{2}{U}",
        "draw_count": 2,
        "net_cards": 1,
        "repeatable": False,
        "prerequisites": [],
        "evidence": "Draw two cards.",
        "supported": True,
    }
    base.update(overrides)
    return base


def _profile(*routes, unknown_clauses=None, complete=True):
    return {
        "routes": list(routes),
        "unknown_clauses": list(unknown_clauses or []),
        "complete": complete,
    }


def _assess(
    profile, card=None, support_cards=None, commander=None, power=3, support=None
):
    card = (
        {"name": "Test Card", "cmc": 2, "type_line": "Sorcery"}
        if card is None
        else card
    )
    support_cards = [] if support_cards is None else support_cards
    commander = {"name": "Test Commander"} if commander is None else commander
    if support is None:
        support_fn = lambda *args, **kwargs: dict(UNSUPPORTED_SUPPORT)
    elif callable(support):
        support_fn = support
    else:
        support_fn = lambda *args, **kwargs: copy.deepcopy(support)
    with (
        patch.object(ASSESSMENT, "route_profile", return_value=profile),
        patch.object(
            ASSESSMENT, "commander_mana_support", side_effect=support_fn
        ) as helper,
    ):
        result = ASSESSMENT.assess_draw_routes(
            card, support_cards, commander, power=power
        )
    return result, helper


class AssessDrawRoutesTests(unittest.TestCase):
    def test_positive_draw_two_available_independent(self):
        profile = _profile(_route(kind="spell", mana=3, draw_count=2, net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["independent"])
        self.assertEqual(result["routes"][0]["status"], "available")
        self.assertEqual(result["routes"][0]["gross_mana"], 3)
        self.assertIsNone(result["routes"][0]["conditional_mana"])

    def test_etb_cantrip_not_independent(self):
        profile = _profile(_route(kind="etb", mana=2, draw_count=1, net_cards=0))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "available")
        self.assertFalse(result["independent"])

    def test_action_news_crew_channel_six_blocked_not_printed_two(self):
        card = {
            "name": "Action News Crew",
            "cmc": 2,
            "mana_cost": "{1}{W}",
            "type_line": "Creature — Human Citizen",
        }
        profile = _profile(
            _route(
                kind="channel",
                mana=6,
                setup_mana=0,
                cost="{6}",
                draw_count=1,
                net_cards=0,
                prerequisites=["discard"],
                evidence="Channel — {6}, Discard this card: Put a +1/+1 counter on each creature you control. Draw a card.",
            )
        )
        result, helper = _assess(profile, card=card)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["independent"])
        route = result["routes"][0]
        self.assertEqual(route["status"], "blocked")
        self.assertEqual(route["gross_mana"], 6)
        self.assertNotEqual(route["gross_mana"], card["cmc"])
        self.assertIn("exceeds_tempo_cap", route["reasons"])
        helper.assert_called()
        self.assertEqual(helper.call_args.kwargs.get("route_kind"), "channel")

    def test_activation_cost_one_setup_five_not_independent(self):
        profile = _profile(
            _route(
                kind="activated",
                mana=1,
                setup_mana=5,
                cost="{1}",
                draw_count=2,
                net_cards=1,
            )
        )
        result, _ = _assess(profile)
        route = result["routes"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["independent"])
        self.assertEqual(route["gross_mana"], 1)
        self.assertIsNone(route["conditional_mana"])
        self.assertEqual(route["initial_total_mana"], 6)
        self.assertNotEqual(route["gross_mana"], 5)
        self.assertEqual(route["status"], "blocked")

    def test_island_supported_by_type_line_subtype(self):
        support_cards = [
            {
                "name": "Tropical Sanctuary",
                "type_line": "Basic Land — Island",
                "oracle_text": "({T}: Add {U}.)",
            }
        ]
        profile = _profile(_route(prerequisites=["island"], mana=2, net_cards=1))
        result, _ = _assess(profile, support_cards=support_cards)
        self.assertEqual(result["status"], "available")
        self.assertFalse(result["independent"])
        self.assertNotIn("missing_current_island_support", result["reasons"])

    def test_island_missing_current_support_blocked(self):
        support_cards = [
            {
                "name": "Island Sanctuary",
                "type_line": "Enchantment",
                "oracle_text": "Creatures cannot attack you unless their controller pays {1} for each Island they control.",
            },
            {
                "name": "Forest",
                "type_line": "Basic Land — Forest",
            },
        ]
        profile = _profile(_route(prerequisites=["island"], mana=2, net_cards=1))
        result, _ = _assess(profile, support_cards=support_cards)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["independent"])
        self.assertIn("missing_current_island_support", result["routes"][0]["reasons"])
        self.assertIn("missing_current_island_support", result["reasons"])

    def test_island_name_only_without_type_line_unverified(self):
        support_cards = [{"name": "Island", "oracle_text": "Island"}]
        profile = _profile(_route(prerequisites=["island"], mana=2, net_cards=1))
        result, _ = _assess(profile, support_cards=support_cards)
        self.assertEqual(result["status"], "unverified")
        self.assertIn("unknown_island_support", result["routes"][0]["reasons"])

    def test_optimistic_one_w_giada_warden_six_conditional_preserves_gross(self):
        card = {
            "name": "Warden of the Angel Host",
            "mana_cost": "{5}{W}",
            "cmc": 6,
            "type_line": "Creature — Angel",
        }
        commander = {"name": "Giada, Font of Hope"}
        profile = _profile(_route(kind="spell", mana=6, cost="{5}{W}", net_cards=1))

        def giada_support(commander_card, assessed_card, route_kind="cast"):
            if route_kind != "cast":
                return dict(UNSUPPORTED_SUPPORT)
            type_line = assessed_card.get("type_line") or ""
            if "Angel" not in type_line.split("—")[-1]:
                return dict(UNSUPPORTED_SUPPORT)
            return {
                "status": "verified",
                "mana_by_color": {"W": 1},
                "applicable_pips": 1,
                "casting_only": True,
                "restrictions": ["Angel"],
                "setup_requirements": [],
                "reason": "Giada produces {W}",
            }

        result, helper = _assess(
            profile, card=card, commander=commander, support=giada_support
        )
        self.assertEqual(result["status"], "conditional")
        self.assertFalse(result["independent"])
        route = result["routes"][0]
        self.assertEqual(route["status"], "conditional")
        self.assertEqual(route["gross_mana"], 6)
        self.assertEqual(route["conditional_mana"], 5)
        self.assertEqual(route["commander_support"]["status"], "verified")
        self.assertEqual(route["commander_support"]["applicable_pips"], 1)
        self.assertEqual(helper.call_args.kwargs.get("route_kind"), "cast")

    def test_giada_non_angel_six_blocked(self):
        card = {
            "name": "Warden of Beasts",
            "mana_cost": "{5}{G}",
            "cmc": 6,
            "type_line": "Creature — Beast",
        }
        commander = {"name": "Giada, Font of Hope"}
        profile = _profile(_route(kind="spell", mana=6, net_cards=1))

        def giada_support(commander_card, assessed_card, route_kind="cast"):
            type_line = assessed_card.get("type_line") or ""
            if route_kind == "cast" and "Angel" in type_line:
                return {
                    "status": "verified",
                    "mana_by_color": {"W": 1},
                    "applicable_pips": 1,
                    "casting_only": True,
                    "restrictions": ["Angel"],
                    "setup_requirements": [],
                    "reason": "Giada produces {W}",
                }
            return dict(UNSUPPORTED_SUPPORT)

        result, helper = _assess(
            profile, card=card, commander=commander, support=giada_support
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["routes"][0]["gross_mana"], 6)
        self.assertIn("exceeds_tempo_cap", result["routes"][0]["reasons"])
        self.assertEqual(helper.call_args.kwargs.get("route_kind"), "cast")

    def test_giada_cannot_help_channel_six(self):
        card = {
            "name": "Angel Channeler",
            "cmc": 2,
            "type_line": "Creature — Angel",
        }
        commander = {"name": "Giada, Font of Hope"}
        profile = _profile(_route(kind="channel", mana=6, net_cards=1))

        def giada_support(commander_card, assessed_card, route_kind="cast"):
            if route_kind != "cast":
                return dict(UNSUPPORTED_SUPPORT)
            return {
                "status": "verified",
                "mana_by_color": {"W": 1},
                "applicable_pips": 1,
                "casting_only": True,
                "restrictions": ["Angel"],
                "setup_requirements": [],
                "reason": "Giada produces {W}",
            }

        result, helper = _assess(
            profile, card=card, commander=commander, support=giada_support
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["routes"][0]["gross_mana"], 6)
        self.assertEqual(helper.call_args.kwargs.get("route_kind"), "channel")
        self.assertNotEqual(helper.call_args.kwargs.get("route_kind"), "cast")

    def test_vivi_state_dependent_cannot_overcap_or_discount(self):
        card = {"name": "Expensive Draw", "cmc": 6, "type_line": "Sorcery"}
        commander = {"name": "Vivi Ornitier"}
        profile = _profile(_route(kind="spell", mana=6, net_cards=1))
        support = {
            "status": "state_dependent",
            "mana_by_color": {"U": 1, "R": 1},
            "applicable_pips": 2,
            "casting_only": False,
            "restrictions": [],
            "setup_requirements": ["counters"],
            "reason": "Vivi mana depends on counters",
        }
        result, _ = _assess(profile, card=card, commander=commander, support=support)
        self.assertEqual(result["status"], "blocked")
        route = result["routes"][0]
        self.assertEqual(route["gross_mana"], 6)
        self.assertNotEqual(route["gross_mana"], 5)
        self.assertIn("exceeds_tempo_cap", route["reasons"])
        self.assertIn("state_dependent_commander_mana", route["reasons"])

    def test_life_prerequisite_conditional(self):
        profile = _profile(_route(prerequisites=["life"], mana=2, net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "conditional")
        self.assertFalse(result["independent"])
        self.assertIn("requires_life", result["routes"][0]["reasons"])

    def test_opponent_prerequisite_conditional(self):
        profile = _profile(_route(prerequisites=["opponent_cast"], mana=2, net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "conditional")
        self.assertFalse(result["independent"])
        self.assertIn("requires_opponent_cast", result["routes"][0]["reasons"])

    def test_death_prerequisite_conditional(self):
        profile = _profile(
            _route(prerequisites=["creature_death"], mana=2, net_cards=1)
        )
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "conditional")
        self.assertFalse(result["independent"])
        self.assertIn("requires_creature_death", result["routes"][0]["reasons"])

    def test_counters_prerequisite_conditional(self):
        profile = _profile(_route(prerequisites=["counters"], mana=2, net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "conditional")
        self.assertFalse(result["independent"])
        self.assertIn("requires_counters", result["routes"][0]["reasons"])

    def test_gross_mana_immutability_and_no_input_mutation(self):
        card = {"name": "Warden", "cmc": 6, "type_line": "Creature — Angel"}
        commander = {"name": "Giada, Font of Hope"}
        support_cards = [{"name": "Plains", "type_line": "Basic Land — Plains"}]
        route = _route(kind="spell", mana=6, net_cards=1, prerequisites=[])
        profile = _profile(route)
        originals = {
            "card": copy.deepcopy(card),
            "commander": copy.deepcopy(commander),
            "support_cards": copy.deepcopy(support_cards),
            "route": copy.deepcopy(route),
            "profile": copy.deepcopy(profile),
        }
        support = {
            "status": "verified",
            "mana_by_color": {"W": 1},
            "applicable_pips": 1,
            "casting_only": True,
            "restrictions": ["Angel"],
            "setup_requirements": [],
            "reason": "Giada produces {W}",
        }
        result, _ = _assess(
            profile,
            card=card,
            support_cards=support_cards,
            commander=commander,
            support=support,
        )
        self.assertEqual(result["routes"][0]["gross_mana"], 6)
        self.assertEqual(card, originals["card"])
        self.assertEqual(commander, originals["commander"])
        self.assertEqual(support_cards, originals["support_cards"])
        self.assertEqual(route, originals["route"])
        self.assertEqual(profile, originals["profile"])
        self.assertNotIn("status", route)
        self.assertNotIn("gross_mana", route)

    def test_multiple_routes_one_viable_overall_available(self):
        cheap = _route(kind="spell", mana=2, net_cards=1)
        expensive = _route(kind="channel", mana=6, net_cards=1)
        unknown = _route(kind="triggered", mana=None, net_cards=1, supported=True)
        profile = _profile(
            expensive, unknown, cheap, unknown_clauses=["other clause"], complete=False
        )
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["independent"])
        statuses = [route["status"] for route in result["routes"]]
        self.assertEqual(statuses, ["blocked", "unverified", "available"])

    def test_malformed_nan_mana_unverified_never_free(self):
        profile = _profile(_route(mana=float("nan"), net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["independent"])
        self.assertIsNone(result["routes"][0]["gross_mana"])
        self.assertIn("unknown_mana_cost", result["routes"][0]["reasons"])

    def test_boolean_and_negative_mana_unverified(self):
        for mana in (True, False, -1, float("inf")):
            with self.subTest(mana=mana):
                profile = _profile(_route(mana=mana, net_cards=1))
                result, _ = _assess(profile)
                self.assertEqual(result["status"], "unverified")
                self.assertFalse(result["independent"])
                self.assertIsNone(result["routes"][0]["gross_mana"])

    def test_unrecognized_prerequisite_unverified(self):
        profile = _profile(_route(prerequisites=["custom_ritual"], mana=2, net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["independent"])
        self.assertIn("unknown_prerequisite", result["routes"][0]["reasons"])

    def test_unsupported_prerequisite_unverified(self):
        profile = _profile(_route(prerequisites=["unsupported"], mana=2, net_cards=1))
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "unverified")
        self.assertIn("unsupported_prerequisite", result["routes"][0]["reasons"])

    def test_empty_complete_routes_blocked(self):
        result, _ = _assess(_profile())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reasons"], ["no_actual_draw_route"])

    def test_empty_incomplete_routes_unverified(self):
        result, _ = _assess(_profile(complete=False))
        self.assertEqual(result["status"], "unverified")

    def test_unknown_clauses_do_not_erase_proved_positive_route(self):
        profile = _profile(
            _route(mana=2, net_cards=1),
            unknown_clauses=["unparsed extra mode"],
            complete=False,
        )
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["independent"])

    def test_blocked_plus_unknown_clauses_overall_unverified(self):
        profile = _profile(
            _route(kind="channel", mana=6, net_cards=1),
            unknown_clauses=["maybe another draw"],
            complete=False,
        )
        result, _ = _assess(profile)
        self.assertEqual(result["status"], "unverified")

    def test_power_caps(self):
        cases = (
            (3, 5, "available"),
            (4, 4, "available"),
            (4, 5, "blocked"),
            (5, 3, "available"),
            (5, 4, "blocked"),
        )
        for power, mana, expected in cases:
            with self.subTest(power=power, mana=mana):
                profile = _profile(_route(mana=mana, net_cards=1))
                result, _ = _assess(profile, power=power)
                self.assertEqual(result["status"], expected)

    def test_tap_combat_and_upkeep_are_conditional(self):
        cases = (
            (["tap"], "requires_tap"),
            (["combat_damage"], "requires_combat_damage"),
            (["attack"], "requires_attack"),
            (["cumulative_upkeep"], "requires_cumulative_upkeep"),
            (["opponent_payment"], "requires_opponent_payment"),
        )
        for prereqs, reason in cases:
            with self.subTest(prereqs=prereqs):
                profile = _profile(_route(prerequisites=prereqs, mana=2, net_cards=1))
                result, _ = _assess(profile)
                self.assertEqual(result["status"], "conditional")
                self.assertFalse(result["independent"])
                self.assertIn(reason, result["routes"][0]["reasons"])

    def test_empty_support_cards_island_blocked_not_future(self):
        profile = _profile(_route(prerequisites=["island"], mana=2, net_cards=1))
        result, _ = _assess(profile, support_cards=[])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_current_island_support", result["reasons"])
        self.assertNotIn("impossible", "".join(result["reasons"]))

    def test_activation_setup_over_cap_blocked_without_using_setup_as_cost(self):
        profile = _profile(
            _route(kind="activated", mana=1, setup_mana=6, cost="{1}", net_cards=1)
        )
        result, _ = _assess(profile)
        route = result["routes"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(route["gross_mana"], 1)
        self.assertIsNone(route["conditional_mana"])
        self.assertEqual(route["initial_total_mana"], 7)
        self.assertIn("exceeds_tempo_cap", route["reasons"])

    def test_etb_overcap_uses_cast_route_kind(self):
        card = {"name": "Angel Warden", "type_line": "Creature — Angel", "cmc": 6}
        profile = _profile(_route(kind="etb", mana=6, net_cards=1))
        support = {
            "status": "verified",
            "mana_by_color": {"W": 1},
            "applicable_pips": 1,
            "casting_only": True,
            "restrictions": ["Angel"],
            "setup_requirements": [],
            "reason": "Giada produces {W}",
        }
        result, helper = _assess(profile, card=card, support=support)
        self.assertEqual(result["status"], "conditional")
        self.assertFalse(result["independent"])
        self.assertEqual(result["routes"][0]["gross_mana"], 6)
        self.assertEqual(helper.call_args.kwargs.get("route_kind"), "cast")


if __name__ == "__main__":
    unittest.main()


def test_setup_unknown_is_not_free():
    result, _ = _assess(_profile(_route(kind="activated", mana=1, setup_mana=None)))
    assert result["status"] == "unverified"


def test_passive_trigger_deployment_is_counted():
    result, _ = _assess(_profile(_route(kind="triggered", mana=0, setup_mana=6)))
    assert result["status"] == "blocked"
    assert result["routes"][0]["initial_total_mana"] == 6


def test_affordable_activation_is_conditional():
    result, _ = _assess(_profile(_route(kind="activated", mana=1, setup_mana=2)))
    assert result["status"] == "conditional"
    assert not result["independent"]


def test_island_requires_land_type_and_ignores_face_union():
    profile = _profile(_route(prerequisites=["island"]))
    result, _ = _assess(profile, support_cards=[{"type_line": "Creature — Island"}])
    assert result["status"] == "blocked"
    result, _ = _assess(
        profile, support_cards=[{"type_line": "Creature — Wizard // Land — Island"}]
    )
    assert result["status"] == "unverified"


def test_malformed_prerequisites_never_raise():
    for value in [None, 7, "tap", [None], [{}]]:
        result, _ = _assess(_profile(_route(prerequisites=value)))
        assert result["status"] == "unverified"


def test_draw_count_must_be_known_positive():
    for value in [None, 0, False, float("nan")]:
        result, _ = _assess(_profile(_route(draw_count=value)))
        assert result["status"] == "unverified"


def test_dynamic_island_oracle_is_not_static_support():
    profile = _profile(_route(prerequisites=["island"]))
    for oracle in [
        "Enchanted land is an Island.",
        "Each land is an Island in addition to its other land types.",
        "Target land becomes an Island in addition to its other types until end of turn.",
        "Lands you control are Islands.",
    ]:
        support = [{"type_line": "Enchantment", "oracle_text": oracle}]
        result, _ = _assess(profile, support_cards=support)
        assert result["status"] == "unverified"
        support.append({"type_line": "Basic Land — Island"})
        result, _ = _assess(profile, support_cards=support)
        assert result["status"] == "available"


def test_own_upkeep_is_conditional():
    result, _ = _assess(
        _profile(
            _route(
                kind="triggered",
                mana=0,
                setup_mana=3,
                prerequisites=["own_upkeep", "life"],
            )
        )
    )
    assert result["status"] == "conditional"
    assert not result["independent"]


def test_known_nonisland_multiface_support_does_not_hide_missing_island():
    profile = _profile(_route(prerequisites=["island"]))
    cards = [
        {"type_line": "Creature — Elf // Land"},
        {
            "type_line": "Creature — Elf",
            "card_faces": [{"type_line": "Creature — Elf"}, {"type_line": "Land"}],
        },
    ]
    for card in cards:
        result, _ = _assess(profile, support_cards=[card])
        assert result["status"] == "blocked"
    cards[1]["card_faces"][1]["oracle_text"] = "Target land becomes an Island."
    result, _ = _assess(profile, support_cards=[cards[1]])
    assert result["status"] == "unverified"

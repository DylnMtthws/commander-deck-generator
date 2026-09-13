"""Replacement cards must not inherit unrelated draw slots during rebalancing."""

import numpy as np
import pytest

from sabermetrics.analytics.synergy_matrix import SynergyMatrix
from sabermetrics.pipeline.greedy_optimizer import rebalance_budget
from sabermetrics.pipeline.slot_assigner import SlotAssignment


def card(name, text, price, score, type_line="Instant"):
    return {
        "id": name,
        "name": name,
        "oracle_text": text,
        "type_line": type_line,
        "price_usd": price,
        "_cvar_score": score,
        "cmc": 2,
        "role_tags": [],
    }


def matrix(cards):
    return SynergyMatrix(
        matrix=np.zeros((len(cards), len(cards)), dtype=np.float32),
        card_id_to_index={c["id"]: i for i, c in enumerate(cards)},
        index_to_card_id={i: c["id"] for i, c in enumerate(cards)},
    )


@pytest.mark.parametrize("phase", ["upgrade", "downgrade"])
@pytest.mark.parametrize(
    "name,text,kind,expected",
    [
        (
            "Arcane Signet",
            "{T}: Add one mana of any color in your commander's color identity.",
            "Artifact",
            "ramp",
        ),
        (
            "Fierce Guardianship",
            "If you control a commander, you may cast this spell without paying its mana cost.\nCounter target noncreature spell.",
            "Instant",
            None,
        ),
        ("Divination", "Draw two cards.", "Sorcery", "draw"),
    ],
)
def test_replacement_role_comes_from_incoming_card(phase, name, text, kind, expected):
    old = card(
        "Outgoing draw engine", "Draw a card.", 10 if phase == "downgrade" else 0.2, 0.1
    )
    incoming = card(name, text, 1, 0.95, kind)
    cards = [old, incoming]
    out, stats = rebalance_budget(
        [SlotAssignment(card=old, slot_role="draw", score=0.1)],
        cards,
        matrix(cards),
        {},
        budget=2,
        max_expensive_checked=0,
    )
    assert stats["upgrades" if phase == "upgrade" else "downgrades"] == 1
    assert out[0].card["name"] == name
    if expected is None:
        # Existing classifier does not yet recognize every counterspell shape.
        # Pin the corruption regression without freezing that unrelated gap.
        assert out[0].slot_role != "draw"
    else:
        assert out[0].slot_role == expected


def test_unbundle_reclassifies_substitute_and_funded_replacements():
    expensive = card("Expensive draw engine", "Draw a card.", 40, 0.65)
    fillers = [card(f"Draw filler {i}", "Draw a card.", 0.2, 0.2) for i in range(3)]
    substitute = card(
        "Arcane Signet",
        "{T}: Add one mana of any color in your commander's color identity.",
        0.5,
        0.6,
        "Artifact",
    )
    upgrades = [
        card(f"Synthetic counter {i}", "Counter target spell.", 12, 0.9)
        for i in range(3)
    ]
    cards = [expensive, *fillers, substitute, *upgrades]
    out, stats = rebalance_budget(
        [
            SlotAssignment(card=c, slot_role="draw", score=c["_cvar_score"])
            for c in [expensive, *fillers]
        ],
        cards,
        matrix(cards),
        {},
        budget=40.6,
    )
    assert stats["unbundles"] == 1
    assert {a.card["name"] for a in out} == {
        substitute["name"],
        *(c["name"] for c in upgrades),
    }
    assert [a.slot_role for a in out if a.card["name"] == "Arcane Signet"] == ["ramp"]
    assert all(
        a.slot_role == "removal"
        for a in out
        if a.card["name"].startswith("Synthetic counter")
    )


def test_retained_card_keeps_existing_assignment():
    retained = card(
        "Existing contextual assignment",
        "{T}: Add one mana of any color.",
        1,
        0.9,
        "Artifact",
    )
    assignment = SlotAssignment(card=retained, slot_role="utility", score=0.9)
    out, stats = rebalance_budget(
        [assignment], [retained], matrix([retained]), {}, budget=1
    )
    assert stats["upgrades"] == stats["unbundles"] == stats["downgrades"] == 0
    assert out[0].slot_role == "utility"

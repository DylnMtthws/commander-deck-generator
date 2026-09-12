"""Equality tests for accelerated rule-matrix construction.

Compares ``build_rule_matrix`` to nested ``_match_rules`` (the reference).
Tests observe scores, dtype, symmetry and diagonal — not the mask internals.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from sabermetrics.analytics.synergy_matrix import (
    EMBEDDING_WEIGHT,
    RULE_WEIGHT,
    _load_synergy_rules,
    _match_rules,
    build_rule_matrix,
    build_synergy_matrix,
)

# ---------------------------------------------------------------------------
# Reference (nested pairwise _match_rules) — the semantics under test
# ---------------------------------------------------------------------------


def _reference_rule_matrix(candidates: list[dict], rules: list[dict]) -> np.ndarray:
    n = len(candidates)
    matrix = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            score = _match_rules(candidates[i], candidates[j], rules)
            matrix[i, j] = score
            matrix[j, i] = score
    return matrix


def _assert_equal_to_reference(candidates: list[dict], rules: list[dict]) -> np.ndarray:
    got = build_rule_matrix(candidates, rules)
    expected = _reference_rule_matrix(candidates, rules)
    assert got.dtype == np.float32
    assert got.shape == (len(candidates), len(candidates))
    assert np.array_equal(got, expected), (
        f"rule matrix diverged from nested _match_rules\n"
        f"got max={got.max()} expected max={expected.max()}\n"
        f"mismatch count={int(np.count_nonzero(got != expected))}"
    )
    if len(candidates) > 0:
        assert np.all(np.diag(got) == 0)
        assert np.array_equal(got, got.T)
    return got


def _card(
    card_id: str = "c",
    *,
    oracle_text: object = "",
    type_line: object = "Creature",
    keywords: object = "[]",
    cmc: object = 3,
    **extra: object,
) -> dict:
    card = {
        "id": card_id,
        "oracle_text": oracle_text,
        "type_line": type_line,
        "keywords": keywords,
        "cmc": cmc,
    }
    card.update(extra)
    return card


# ---------------------------------------------------------------------------
# Empty / trivial shapes
# ---------------------------------------------------------------------------


def test_empty_candidates_empty_rules() -> None:
    got = _assert_equal_to_reference([], [])
    assert got.shape == (0, 0)


def test_empty_candidates_with_rules() -> None:
    rules = [
        {
            "trigger": {"text_contains": ["token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.8,
        }
    ]
    _assert_equal_to_reference([], rules)


def test_candidates_with_empty_rules() -> None:
    cards = [
        _card("a", oracle_text="Create a token"),
        _card("b", oracle_text="Sacrifice a creature"),
    ]
    got = _assert_equal_to_reference(cards, [])
    assert np.all(got == 0)


def test_single_candidate_zero_diagonal() -> None:
    cards = [_card("solo", oracle_text="Create a token and sacrifice it")]
    rules = [
        {
            "trigger": {"text_contains": ["create", "token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.9,
        }
    ]
    got = _assert_equal_to_reference(cards, rules)
    assert got.shape == (1, 1)
    assert got[0, 0] == 0


# ---------------------------------------------------------------------------
# Strength max, symmetry, both orientations
# ---------------------------------------------------------------------------


def test_strength_max_not_sum() -> None:
    """Two matching rules contribute the larger strength, not a sum."""
    trigger = _card("t", oracle_text="Create a 1/1 creature token")
    payoff = _card("p", oracle_text="Sacrifice a creature: draw a card")
    rules = [
        {
            "trigger": {"text_contains": ["create", "token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.4,
        },
        {
            "trigger": {"text_contains": ["token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.9,
        },
    ]
    got = _assert_equal_to_reference([trigger, payoff], rules)
    assert got[0, 1] == np.float32(0.9)


def test_bidirectional_trigger_payoff() -> None:
    """A as trigger/B as payoff and the reverse both count; max is used."""
    a = _card("a", oracle_text="Create a token. Sacrifice a creature.")
    b = _card("b", oracle_text="Create a token. Sacrifice a creature.")
    rules = [
        {
            "trigger": {"text_contains": ["create", "token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.75,
        }
    ]
    got = _assert_equal_to_reference([a, b], rules)
    assert got[0, 1] == got[1, 0] == np.float32(0.75)


def test_unrelated_pair_is_zero() -> None:
    a = _card("a", oracle_text="Search your library for a basic land card")
    b = _card(
        "b", oracle_text="Flying. When this enters, gain 3 life.", keywords='["Flying"]'
    )
    rules = [
        {
            "trigger": {"text_contains": ["create", "token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.8,
        }
    ]
    got = _assert_equal_to_reference([a, b], rules)
    assert got[0, 1] == 0.0


def test_default_strength_when_missing() -> None:
    a = _card("a", oracle_text="proliferate")
    b = _card("b", oracle_text="put a +1/+1 counter on target")
    rules = [
        {
            "trigger": {"text_contains": ["proliferate"]},
            "payoff": {"text_contains": ["+1/+1 counter"]},
        }
    ]
    got = _assert_equal_to_reference([a, b], rules)
    assert got[0, 1] == np.float32(0.5)


# ---------------------------------------------------------------------------
# Arbitrary clause combinations
# ---------------------------------------------------------------------------


def test_all_clause_fields_together() -> None:
    match = _card(
        "hit",
        oracle_text="Create a token. Draw a card.",
        type_line="Instant",
        keywords='["Prowess"]',
        cmc=1,
    )
    miss_text = _card(
        "miss-text",
        oracle_text="Draw a card.",
        type_line="Instant",
        keywords='["Prowess"]',
        cmc=1,
    )
    miss_type = _card(
        "miss-type",
        oracle_text="Create a token. Draw a card.",
        type_line="Creature",
        keywords='["Prowess"]',
        cmc=1,
    )
    miss_kw = _card(
        "miss-kw",
        oracle_text="Create a token. Draw a card.",
        type_line="Instant",
        keywords='["Flying"]',
        cmc=1,
    )
    miss_cmc = _card(
        "miss-cmc",
        oracle_text="Create a token. Draw a card.",
        type_line="Instant",
        keywords='["Prowess"]',
        cmc=5,
    )
    payoff = _card(
        "pay",
        oracle_text="Whenever you cast an instant or sorcery, copy it.",
        type_line="Enchantment",
        cmc=3,
    )
    rules = [
        {
            "trigger": {
                "text_contains": ["create", "token"],
                "text_contains_any": ["draw a card", "discard a card"],
                "keywords": ["Prowess", "Trample"],
                "type_includes": ["Instant", "Sorcery"],
                "cmc_range": [0, 2],
            },
            "payoff": {"text_contains": ["copy"]},
            "strength": 0.85,
        }
    ]
    cards = [match, miss_text, miss_type, miss_kw, miss_cmc, payoff]
    got = _assert_equal_to_reference(cards, rules)
    assert got[0, 5] == np.float32(0.85)
    assert got[1, 5] == got[2, 5] == got[3, 5] == got[4, 5] == 0.0


def test_text_contains_any_and_empty_clause() -> None:
    producer = _card("prod", oracle_text="Put a +1/+1 counter on target creature.")
    scales = _card(
        "sc", oracle_text="If counters would be put, that many plus one instead."
    )
    unrelated = _card("u", oracle_text="Counter target spell.")
    empty_trigger_rule = {
        "trigger": {},
        "payoff": {"text_contains_any": ["that many plus one", "twice that many"]},
        "strength": 1.0,
    }
    real_rule = {
        "trigger": {"text_contains": ["+1/+1 counter"]},
        "payoff": {"text_contains_any": ["that many plus one", "twice that many"]},
        "strength": 0.8,
    }
    cards = [producer, scales, unrelated]
    _assert_equal_to_reference(cards, [empty_trigger_rule, real_rule])


def test_empty_list_fields_do_not_filter() -> None:
    """Empty lists are skipped by the reference; a truthy empty-list clause matches all."""
    a = _card("a", oracle_text="alpha")
    b = _card("b", oracle_text="beta")
    rules = [
        {
            "trigger": {
                "text_contains": [],
                "keywords": [],
                "type_includes": [],
                "text_contains_any": [],
            },
            "payoff": {"text_contains": []},
            "strength": 0.3,
        }
    ]
    got = _assert_equal_to_reference([a, b], rules)
    assert got[0, 1] == np.float32(0.3)


def test_cmc_range_wrong_length_ignored() -> None:
    a = _card("a", oracle_text="untap target land", cmc=99)
    b = _card("b", oracle_text="{T}: add mana", cmc=99)
    rules = [
        {
            "trigger": {"text_contains": ["untap"], "cmc_range": [0]},
            "payoff": {"text_contains": ["{t}:"], "cmc_range": [1, 2, 3]},
            "strength": 0.7,
        }
    ]
    got = _assert_equal_to_reference([a, b], rules)
    assert got[0, 1] == np.float32(0.7)


# ---------------------------------------------------------------------------
# Malformed / missing metadata — same interpretation as reference
# ---------------------------------------------------------------------------


def test_missing_and_null_oracle_is_not_filled_from_name() -> None:
    """Rule matching must not invent oracle text from the card name."""
    named = _card(
        "named",
        oracle_text=None,
        type_line="Creature",
        name="Create Token Generator",
    )
    del named["oracle_text"]
    missing_key = {"id": "mk", "name": "Sacrifice Outlet", "type_line": "Creature"}
    payoff = _card("p", oracle_text="Sacrifice a creature")
    trigger = _card("t", oracle_text="Create a 1/1 creature token")
    rules = [
        {
            "trigger": {"text_contains": ["create", "token"]},
            "payoff": {"text_contains": ["sacrifice"]},
            "strength": 0.8,
        }
    ]
    cards = [named, missing_key, payoff, trigger]
    got = _assert_equal_to_reference(cards, rules)
    assert got[0, 2] == 0.0
    assert got[1, 3] == 0.0
    assert got[2, 3] == np.float32(0.8)


def test_invalid_keywords_and_null_fields() -> None:
    cards = [
        _card("bad-json", keywords="{not-json", oracle_text="draw a card", cmc=1),
        _card(
            "kw-none",
            keywords=None,
            oracle_text="draw a card",
            type_line=None,
            cmc=None,
        ),
        _card(
            "kw-list", keywords=["Prowess", "Flying"], oracle_text="draw a card", cmc=1
        ),
        _card("kw-empty-str", keywords="", oracle_text="draw a card", cmc=1),
        _card(
            "pay",
            keywords='["Prowess"]',
            oracle_text="haste",
            type_line="Creature",
            cmc=2,
        ),
    ]
    rules = [
        {
            "trigger": {"text_contains": ["draw a card"], "cmc_range": [0, 2]},
            "payoff": {"keywords": ["Prowess"]},
            "strength": 0.6,
        }
    ]
    _assert_equal_to_reference(cards, rules)


def test_cmc_falsey_values_match_reference() -> None:
    cards = [
        _card("zero", oracle_text="draw a card", cmc=0),
        _card("false", oracle_text="draw a card", cmc=False),
        _card("empty-str-cmc", oracle_text="draw a card", cmc=""),
        _card("pay", oracle_text="prowess matters", keywords='["Prowess"]', cmc=1),
    ]
    rules = [
        {
            "trigger": {"text_contains": ["draw a card"], "cmc_range": [0, 2]},
            "payoff": {"keywords": ["Prowess"]},
            "strength": 0.6,
        }
    ]
    _assert_equal_to_reference(cards, rules)


# ---------------------------------------------------------------------------
# Public / synthetic card samples
# ---------------------------------------------------------------------------


def test_oracle_corpus_public_sample_against_loaded_rules() -> None:
    from tests.oracle_corpus import CORPUS

    cards = []
    for i, (key, raw) in enumerate(CORPUS):
        card = dict(raw)
        card.setdefault("id", key)
        card.setdefault("keywords", "[]")
        cards.append(card)
    rules = _load_synergy_rules()
    got = _assert_equal_to_reference(cards, rules)
    assert got.shape == (len(cards), len(cards))


def test_aang_quality_fixture_as_published_metadata() -> None:
    """Public Aang fixture cards are scored as published; faces are not invented."""
    path = Path(__file__).parent / "fixtures" / "cards" / "aang_quality.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cards = []
    for raw in payload["cards"]:
        cards.append(
            {
                "id": raw.get("id"),
                "name": raw.get("name"),
                "oracle_text": raw.get("oracle_text"),
                "type_line": raw.get("type_line"),
                "keywords": raw.get("keywords"),
                "cmc": raw.get("cmc"),
            }
        )
    rules = _load_synergy_rules()
    _assert_equal_to_reference(cards, rules)


# ---------------------------------------------------------------------------
# Randomized shapes (seeded)
# ---------------------------------------------------------------------------

_PHRASES = [
    "create",
    "token",
    "sacrifice",
    "enters the battlefield",
    "exile",
    "return",
    "draw a card",
    "+1/+1 counter",
    "proliferate",
    "copy",
    "instant or sorcery",
    "untap",
    "land",
    "{T}:",
    "costs",
    "less to cast",
    "trample",
    "creatures you control get +",
    "that many plus one",
]
_TYPES = ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Land"]
_KWS = ["Flying", "Prowess", "Trample", "Haste", "Miracle", "Defender"]


def _random_clause(rng: np.random.Generator) -> dict:
    kind = int(rng.integers(0, 8))
    if kind == 0:
        return {}
    clause: dict = {}
    if kind in (1, 5, 6, 7):
        k = int(rng.integers(1, 3))
        clause["text_contains"] = [
            str(p) for p in rng.choice(_PHRASES, size=k, replace=False)
        ]
    if kind in (2, 5, 7):
        k = int(rng.integers(1, 3))
        clause["text_contains_any"] = [
            str(p) for p in rng.choice(_PHRASES, size=k, replace=False)
        ]
    if kind in (3, 6):
        k = int(rng.integers(1, 3))
        clause["keywords"] = [str(p) for p in rng.choice(_KWS, size=k, replace=False)]
    if kind in (4, 7):
        clause["type_includes"] = [str(rng.choice(_TYPES))]
    if rng.random() < 0.4:
        lo = int(rng.integers(0, 4))
        hi = int(rng.integers(lo, 12))
        clause["cmc_range"] = [lo, hi]
    if rng.random() < 0.1:
        clause["text_contains"] = []
    return clause


def _random_card(rng: np.random.Generator, idx: int) -> dict:
    n_phrases = int(rng.integers(0, 5))
    oracle = " ".join(
        str(p) for p in rng.choice(_PHRASES, size=n_phrases, replace=True)
    )
    type_line = str(rng.choice(_TYPES))
    kw_mode = int(rng.integers(0, 5))
    chosen_kw = [
        str(p) for p in rng.choice(_KWS, size=int(rng.integers(0, 3)), replace=False)
    ]
    if kw_mode == 0:
        keywords: object = json.dumps(chosen_kw)
    elif kw_mode == 1:
        keywords = chosen_kw
    elif kw_mode == 2:
        keywords = "not-json"
    elif kw_mode == 3:
        keywords = None
    else:
        keywords = "[]"
    cmc_mode = int(rng.integers(0, 4))
    if cmc_mode == 0:
        cmc: object = int(rng.integers(0, 10))
    elif cmc_mode == 1:
        cmc = None
    elif cmc_mode == 2:
        cmc = float(rng.integers(0, 8))
    else:
        cmc = 0
    card = _card(
        f"r{idx}", oracle_text=oracle, type_line=type_line, keywords=keywords, cmc=cmc
    )
    if rng.random() < 0.1:
        card["oracle_text"] = None
    if rng.random() < 0.05:
        del card["type_line"]
    return card


def _random_rules(rng: np.random.Generator, n_rules: int) -> list[dict]:
    rules = []
    for i in range(n_rules):
        rules.append(
            {
                "id": f"rand-{i}",
                "trigger": _random_clause(rng),
                "payoff": _random_clause(rng),
                "strength": float(rng.choice([0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])),
            }
        )
    return rules


@pytest.mark.parametrize(
    "n_cards,n_rules,seed",
    [
        (0, 4, 1),
        (1, 3, 2),
        (2, 0, 3),
        (2, 1, 4),
        (5, 8, 5),
        (11, 3, 6),
        (17, 12, 7),
        (24, 7, 8),
        (32, 15, 9),
    ],
)
def test_randomized_shapes_equal_reference(
    n_cards: int, n_rules: int, seed: int
) -> None:
    rng = np.random.default_rng(seed)
    cards = [_random_card(rng, i) for i in range(n_cards)]
    rules = _random_rules(rng, n_rules)
    _assert_equal_to_reference(cards, rules)


def test_loaded_synergy_rules_on_synthetic_varied_facts() -> None:
    rng = np.random.default_rng(20260912)
    cards = [_random_card(rng, i) for i in range(40)]
    # Sprinkle known-good synergies so the matrix is not all zeros.
    cards[0] = _card(
        "tok", oracle_text="Create two 1/1 green Saproling creature tokens."
    )
    cards[1] = _card(
        "sac", oracle_text="Sacrifice a creature: Each opponent loses 1 life."
    )
    cards[2] = _card(
        "etb", oracle_text="Whenever a creature enters the battlefield, draw a card."
    )
    cards[3] = _card(
        "blink", oracle_text="Exile target creature, then return it to the battlefield."
    )
    _assert_equal_to_reference(cards, _load_synergy_rules())


# ---------------------------------------------------------------------------
# Hybrid path still consumes the accelerated rule matrix
# ---------------------------------------------------------------------------


def test_build_synergy_matrix_rule_signal_matches_build_rule_matrix() -> None:
    cards = [
        _card("a", oracle_text="Create a 1/1 creature token"),
        _card("b", oracle_text="Sacrifice a creature: draw a card"),
        _card("c", oracle_text="Flying"),
    ]
    for card, role in zip(cards, ("engine", "payoff", "utility")):
        card["role_tags"] = json.dumps([role])

    rules = _load_synergy_rules()
    rule = build_rule_matrix(cards, rules)
    n = len(cards)
    zeros = np.zeros((n, n), dtype=np.float32)
    with patch(
        "sabermetrics.analytics.synergy_matrix._compute_embedding_matrix",
        return_value=(zeros, True),
    ):
        hybrid = build_synergy_matrix(cards, "cmdr", Path("unused.db"))

    expected = RULE_WEIGHT * rule + EMBEDDING_WEIGHT * zeros
    np.testing.assert_allclose(hybrid.matrix, expected, rtol=0, atol=0)
    assert EMBEDDING_WEIGHT + RULE_WEIGHT == pytest.approx(1.0)


def test_malformed_unreached_clause_preserves_short_circuit():
    cards = [_card("a", cmc="bad"), _card("b", cmc="bad")]
    rules = [
        {
            "trigger": {"text_contains": ["never present"]},
            "payoff": {"cmc_range": [0, 3]},
            "strength": 1.0,
        }
    ]
    _assert_equal_to_reference(cards, rules)

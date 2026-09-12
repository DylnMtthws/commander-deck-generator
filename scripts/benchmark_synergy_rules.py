"""Benchmark accelerated rule-matrix construction vs nested ``_match_rules``.

Builds a deterministic synthetic candidate set with varied oracle facts and
compares ``build_rule_matrix`` to the pairwise reference. Reports wall time,
equality, and the reduction in rule-matching time. Does not load embeddings.

Usage:
    PYTHONPATH=src python scripts/benchmark_synergy_rules.py [--n 220]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from sabermetrics.analytics.synergy_matrix import (
    _load_synergy_rules,
    _match_rules,
    build_rule_matrix,
)

# Public-style synthetic oracle lines covering trigger/payoff vocabulary in
# config/synergy_rules.yaml. No production records.
_ORACLE_FACTS = (
    "Create two 1/1 green Saproling creature tokens.",
    "Sacrifice a creature: Each opponent loses 1 life.",
    "Creatures you control get +1/+1.",
    "Creatures you control have trample.",
    "Whenever a creature enters the battlefield, draw a card.",
    "Exile target creature, then return it to the battlefield.",
    "If a creature entering causes an ability to trigger, it triggers an additional time.",
    "Untap target land.",
    "{T}: Add {G}.",
    "If you would add mana, add that much plus {1} additional mana instead.",
    "Spells you cast cost {1} less to cast.",
    "{X}{R}: This deals X damage to any target.",
    "Whenever you cast an instant or sorcery spell, copy that spell.",
    "Draw a card.",
    "Put a +1/+1 counter on target creature.",
    "If one or more +1/+1 counters would be put on a creature you control, that many plus one +1/+1 counters are put on it instead.",
    "At the beginning of your end step, proliferate.",
    "Whenever you sacrifice a permanent, each opponent loses 1 life.",
    "Search your library for an Equipment card and put it onto the battlefield.",
    "Enchanted creature gets +2/+2.",
    "You may cast instant spells as though they had flash.",
    "Artifact spells you cast cost {1} less to cast.",
    "Whenever you cast a creature spell, create a 1/1 token.",
    "Flying. Prowess.",
    "Miracle {1}{W}",
    "Partner",
    "This spell costs {1} less to cast if it's from the command zone.",
    "Move a counter from target creature onto another target creature.",
    "For each counter on this, draw a card.",
    "Counter target spell.",
    "This land enters tapped.",
    "",
)

_TYPE_LINES = (
    "Creature — Elf Druid",
    "Instant",
    "Sorcery",
    "Artifact",
    "Enchantment",
    "Artifact — Equipment",
    "Land",
    "Legendary Creature — Human Wizard",
)

_KEYWORDS = (
    ["Flying"],
    ["Prowess"],
    ["Trample"],
    ["Miracle"],
    ["Flying", "Prowess"],
    [],
)


def _synthetic_candidates(n: int, seed: int = 20260912) -> list[dict]:
    rng = np.random.default_rng(seed)
    cards: list[dict] = []
    for i in range(n):
        n_facts = int(rng.integers(1, 4))
        facts = [str(x) for x in rng.choice(_ORACLE_FACTS, size=n_facts, replace=False)]
        kw = _KEYWORDS[int(rng.integers(0, len(_KEYWORDS)))]
        kw_mode = int(rng.integers(0, 3))
        if kw_mode == 0:
            keywords: object = json.dumps(kw)
        elif kw_mode == 1:
            keywords = list(kw)
        else:
            keywords = "[]"
        cards.append(
            {
                "id": f"syn-{i}",
                "name": f"Synthetic {i}",
                "oracle_text": " ".join(facts),
                "type_line": str(_TYPE_LINES[int(rng.integers(0, len(_TYPE_LINES)))]),
                "keywords": keywords,
                "cmc": int(rng.integers(0, 9)),
            }
        )
    return cards


def _reference_rule_matrix(candidates: list[dict], rules: list[dict]) -> np.ndarray:
    n = len(candidates)
    matrix = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            score = _match_rules(candidates[i], candidates[j], rules)
            matrix[i, j] = score
            matrix[j, i] = score
    return matrix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=220, help="candidate count (default 220)"
    )
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args(argv)
    if args.n < 200:
        raise SystemExit("--n must be >= 200 (spec requires 200+ candidates)")

    candidates = _synthetic_candidates(args.n, seed=args.seed)
    rules = _load_synergy_rules()

    t0 = time.perf_counter()
    reference = _reference_rule_matrix(candidates, rules)
    reference_seconds = time.perf_counter() - t0

    t1 = time.perf_counter()
    accelerated = build_rule_matrix(candidates, rules)
    accelerated_seconds = time.perf_counter() - t1

    equal = bool(
        accelerated.dtype == np.float32 and np.array_equal(accelerated, reference)
    )
    if reference_seconds > 0:
        reduction = 1.0 - (accelerated_seconds / reference_seconds)
    else:
        reduction = 0.0

    print(f"candidates: {len(candidates)}")
    print(f"rules: {len(rules)}")
    print(f"reference_seconds: {reference_seconds:.6f}")
    print(f"accelerated_seconds: {accelerated_seconds:.6f}")
    print(f"equal: {equal}")
    print(f"reduction: {reduction:.1%}")
    print(f"nonzero_pairs: {int(np.count_nonzero(np.triu(accelerated, 1)))}")
    return 0 if equal else 1


if __name__ == "__main__":
    raise SystemExit(main())

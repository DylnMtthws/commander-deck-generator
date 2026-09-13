"""Deterministic before/after selection receipts.

This module is a pure reporter. It does not mutate the supplied card lists or
decision records, does not apply or rewrite selection choices, and does not
infer quality, support, or a resolution from reasons or alternatives.
Unsupported and unresolved evidence is echoed as given.

``build_receipt(before, after, decisions)`` schema
--------------------------------------------------

``before`` / ``after`` items are dicts with:

* ``name`` (non-empty str)
* ``count`` (optional positive int, not bool; default 1)

Repeated names — typical for basic lands — are a multiset. A row with
``count: 3`` is the same as three rows of the same name.

``decisions`` items are dicts with:

* ``card`` (non-empty str)
* ``action`` (``keep``, ``replace``, or ``unresolved``)
* ``reason`` (str; preserved verbatim)
* ``alternatives`` (list of str)
* optional extra metrics (copied through)

Return value (JSON-serializable)::

    {
      "added": [{"name": str, "count": int}, ...],      # sorted by name
      "removed": [{"name": str, "count": int}, ...],    # sorted by name
      "unchanged": [{"name": str, "count": int}, ...],  # sorted by name
      "decisions": [decision, ...],                     # sorted by card
      "unresolved": [decision, ...],                    # unresolved subsequence
    }

Duplicate per-card decisions are rejected rather than merged. Nonfinite
numeric metrics (including nested ``score`` / ``price`` values) are rejected.
Finite negatives are allowed except on ``count`` / ``quantity``.
"""

# Invalid inputs use ValueError by the reporting API contract.
# ruff: noqa: TRY004
from __future__ import annotations

import copy
import math
from typing import Any, Final

VALID_ACTIONS: Final = frozenset({"keep", "replace", "unresolved"})
REQUIRED_DECISION_FIELDS: Final = ("card", "action", "reason", "alternatives")
QUANTITY_KEYS: Final = frozenset({"count", "quantity"})
ACTION_UNRESOLVED: Final = "unresolved"


def build_receipt(
    before: list[dict],
    after: list[dict],
    decisions: list[dict],
) -> dict:
    """Diff two card bags and echo selection decisions without mutating them.

    Args:
        before: Card dicts with ``name`` and optional positive ``count``
            (default 1). Repeated names are accumulated as a multiset.
        after: Card dicts in the same shape as ``before``.
        decisions: Per-card records with ``card``, ``action`` (``keep``,
            ``replace``, or ``unresolved``), ``reason``, ``alternatives``,
            and optional extra metrics.

    Returns:
        JSON-serializable dict with ``added``, ``removed``, ``unchanged``,
        ``decisions``, and ``unresolved``. Diff entries are ``{name, count}``
        sorted by name. ``decisions`` is sorted by card. ``unresolved`` lists
        the unresolved decisions (same objects as in ``decisions``) so the
        evidence is not dropped.

    Raises:
        ValueError: Non-list inputs, non-dict rows, empty names, invalid or
            nonpositive ``count``, duplicate per-card decisions, malformed
            decisions, or nonfinite numeric metrics.
    """
    before_counts = _aggregate_cards(before, "before")
    after_counts = _aggregate_cards(after, "after")
    added, removed, unchanged = _multiset_diff(before_counts, after_counts)
    parsed_decisions = _parse_decisions(decisions)
    unresolved = [
        decision
        for decision in parsed_decisions
        if decision["action"] == ACTION_UNRESOLVED
    ]
    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "decisions": parsed_decisions,
        "unresolved": unresolved,
    }


def _aggregate_cards(cards: list[dict], label: str) -> dict[str, int]:
    if not isinstance(cards, list):
        raise ValueError(f"{label} must be a list of dicts")
    counts: dict[str, int] = {}
    for index, raw in enumerate(cards):
        name, count = _parse_card(raw, f"{label}[{index}]")
        counts[name] = counts.get(name, 0) + count
    return counts


def _parse_card(raw: Any, path: str) -> tuple[str, int]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a dict")
    if "name" not in raw:
        raise ValueError(f"{path} missing fields: name")
    name = _require_name(raw["name"], f"{path}.name")
    if "count" in raw:
        count = _require_positive_int(raw["count"], f"{path}.count")
    else:
        count = 1
    _validate_numeric_tree(raw, path=path)
    return name, count


def _multiset_diff(
    before_counts: dict[str, int],
    after_counts: dict[str, int],
) -> tuple[
    list[dict[str, str | int]], list[dict[str, str | int]], list[dict[str, str | int]]
]:
    added: list[dict[str, str | int]] = []
    removed: list[dict[str, str | int]] = []
    unchanged: list[dict[str, str | int]] = []
    for name in sorted(set(before_counts) | set(after_counts)):
        previous = before_counts.get(name, 0)
        current = after_counts.get(name, 0)
        overlap = min(previous, current)
        if current > previous:
            added.append({"name": name, "count": current - previous})
        if previous > current:
            removed.append({"name": name, "count": previous - current})
        if overlap:
            unchanged.append({"name": name, "count": overlap})
    return added, removed, unchanged


def _parse_decisions(decisions: list[dict]) -> list[dict[str, Any]]:
    if not isinstance(decisions, list):
        raise ValueError("decisions must be a list of dicts")
    parsed: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    duplicates: set[str] = set()
    for index, raw in enumerate(decisions):
        decision = _parse_decision(raw, index)
        card = decision["card"]
        if card in seen:
            duplicates.add(card)
        else:
            seen[card] = index
        parsed.append(decision)
    if duplicates:
        names = ", ".join(repr(name) for name in sorted(duplicates))
        raise ValueError(f"duplicate card decisions: {names}")
    parsed.sort(key=lambda decision: decision["card"])
    return parsed


def _parse_decision(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"decisions[{index}] must be a dict")
    missing = [field for field in REQUIRED_DECISION_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"decisions[{index}] missing fields: {', '.join(missing)}")
    _require_name(raw["card"], f"decisions[{index}].card")
    action = raw["action"]
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        raise ValueError(
            f"decisions[{index}].action must be one of "
            f"{sorted(VALID_ACTIONS)}, got {action!r}"
        )
    if not isinstance(raw["reason"], str):
        raise ValueError(f"decisions[{index}].reason must be str")
    alternatives = raw["alternatives"]
    if not isinstance(alternatives, list):
        raise ValueError(f"decisions[{index}].alternatives must be a list of str")
    for alt_index, alternative in enumerate(alternatives):
        if not isinstance(alternative, str):
            raise ValueError(
                f"decisions[{index}].alternatives[{alt_index}] must be str"
            )
    _validate_numeric_tree(raw, path=f"decisions[{index}]")
    return copy.deepcopy(raw)


def _require_name(value: Any, path: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _require_positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be a positive integer, not bool")
    if value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _validate_numeric_tree(value: Any, *, path: str, key: str | None = None) -> None:
    if isinstance(value, dict):
        for nested_key, nested in value.items():
            nested_name = nested_key if isinstance(nested_key, str) else None
            nested_path = (
                f"{path}.{nested_key}" if isinstance(nested_key, str) else f"{path}[]"
            )
            _validate_numeric_tree(nested, path=nested_path, key=nested_name)
        return
    if isinstance(value, (list, tuple)):
        for nested_index, nested in enumerate(value):
            _validate_numeric_tree(nested, path=f"{path}[{nested_index}]", key=key)
        return
    if key in QUANTITY_KEYS:
        _require_positive_int(value, path)
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} is a nonfinite numeric metric")

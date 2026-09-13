"""Deterministic before/after function-coverage receipts.

This module is a pure reporter. It does not mutate the supplied card lists,
does not select or rewrite sources, and does not claim improvement. Input
rows are prepared mechanical facts (stable id, name, functions), not raw
database dicts and not live Oracle extraction.

``compare_functions(before, after, protected_ids=())`` schema
-------------------------------------------------------------

Each card dict has:

* ``id`` (required non-empty str; identity for the multiset)
* ``name`` (non-empty str)
* ``count`` (optional positive int, not bool; default 1)
* ``functions`` (list of fact dicts)
* ``coverage_complete`` (optional bool, defaults false; true permits known-empty facts)

Each function dict has:

* ``key`` (non-empty str)
* ``scope`` (non-empty str; distinct targets stay distinct)
* ``confidence`` (``supported``, ``partial``, or ``unknown``)
* ``evidence`` (list of str)

Repeated rows with the same ``id`` are a multiset. A row with ``count: 3``
is the same as three rows of that id. The same id must carry a consistent
name and normalized function facts (within one arm, and across before/after);
otherwise ``ValueError`` — the caller must use the same facts oracle on both
arms.

Identical ``key``/``scope``/``confidence``/``evidence`` entries on one card
are collapsed so they do not double-count. Conflicting duplicates of the
same ``key``/``scope`` raise ``ValueError``.

Only ``supported`` functions with nonempty evidence contribute to supported
coverage. ``supported`` with empty evidence is invalid. Partial and unknown
functions never offset a supported loss.

Return value (JSON-serializable)::

    {
      "added": [{"id", "name", "count"}, ...],
      "removed": [{"id", "name", "count"}, ...],
      "lost_functions": [{"key", "scope", "before", "after", "lost"}, ...],
      "protected_removed": [{"id", "name", "count"}, ...],
      "unknown_removals": [{"id", "name", "count", "reason"}, ...],
      "changed": bool,
      "status": "unchanged" | "changes_observed",
    }

``lost_functions`` lists only positive decreases of supported counts per
``key``/``scope`` across copies. ``unknown_removals`` lists removed cards
that lack explicit complete coverage or have any partial/unknown function; the reason
names incomplete functional coverage and never implies a bad card. Removed
protected ids are reported even when a same-role replacement is present.
Identical before/after multisets yield ``status: "unchanged"``. There is
never an improvement claim.
"""

# Invalid inputs use ValueError by the reporting API contract.
# ruff: noqa: TRY004
from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final

VALID_CONFIDENCE: Final = frozenset({"supported", "partial", "unknown"})
CONFIDENCE_SUPPORTED: Final = "supported"
STATUS_UNCHANGED: Final = "unchanged"
STATUS_CHANGES_OBSERVED: Final = "changes_observed"
QUANTITY_KEYS: Final = frozenset({"count", "quantity"})
REQUIRED_CARD_FIELDS: Final = ("id", "name", "functions")
REQUIRED_FUNCTION_FIELDS: Final = ("key", "scope", "confidence", "evidence")
UNKNOWN_REMOVAL_REASON: Final = (
    "incomplete functional coverage; not every function is supported with "
    "evidence, so this removal is a coverage gap rather than a card quality "
    "judgment"
)


@dataclass(frozen=True, slots=True)
class _Fn:
    key: str
    scope: str
    confidence: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Card:
    card_id: str
    name: str
    count: int
    functions: tuple[_Fn, ...]
    coverage_complete: bool


def compare_functions(
    before: list[dict],
    after: list[dict],
    protected_ids: Collection[str] = (),
) -> dict:
    """Diff two prepared function-fact bags without mutating them.

    Args:
        before: Card dicts with required ``id``, ``name``, ``functions``, and
            optional positive ``count`` (default 1). Repeated ids accumulate
            as a multiset.
        after: Card dicts in the same shape as ``before``.
        protected_ids: Ids whose removal is always listed in
            ``protected_removed``, including same-role replacements.

    Returns:
        JSON-serializable dict with ``added``, ``removed``, ``lost_functions``,
        ``protected_removed``, ``unknown_removals``, ``changed``, and
        ``status``. Card rows are ``{id, name, count}`` (plus ``reason`` on
        unknown removals), sorted by id then name. Lost-function rows are
        sorted by key then scope.

    Raises:
        ValueError: Non-list inputs, malformed cards/functions, empty ids or
            names, nonpositive or bool ``count``, inconsistent facts for the
            same id, conflicting duplicate functions, ``supported`` without
            evidence, oracle mismatch between arms, or nonfinite numerics.
    """
    protected = _parse_protected_ids(protected_ids)
    before_bag = _aggregate_cards(before, "before")
    after_bag = _aggregate_cards(after, "after")
    _assert_same_oracle(before_bag, after_bag)
    added, removed = _multiset_diff(before_bag, after_bag)
    lost_functions = _lost_supported(before_bag, after_bag)
    protected_removed = [row for row in removed if row["id"] in protected]
    unknown_removals = _unknown_removals(removed, before_bag)
    changed = bool(added or removed)
    return {
        "added": added,
        "removed": removed,
        "lost_functions": lost_functions,
        "protected_removed": protected_removed,
        "unknown_removals": unknown_removals,
        "changed": changed,
        "status": STATUS_CHANGES_OBSERVED if changed else STATUS_UNCHANGED,
    }


def _parse_protected_ids(protected_ids: Collection[str]) -> frozenset[str]:
    if isinstance(protected_ids, (str, bytes)):
        raise ValueError("protected_ids must be a collection of strings, not a string")
    try:
        items = list(protected_ids)
    except TypeError as exc:
        raise ValueError("protected_ids must be a collection of strings") from exc
    parsed: list[str] = []
    for index, item in enumerate(items):
        parsed.append(_require_nonempty_str(item, f"protected_ids[{index}]"))
    return frozenset(parsed)


def _aggregate_cards(cards: list[dict], label: str) -> dict[str, _Card]:
    if not isinstance(cards, list):
        raise ValueError(f"{label} must be a list of dicts")
    bag: dict[str, _Card] = {}
    for index, raw in enumerate(cards):
        card = _parse_card(raw, f"{label}[{index}]")
        existing = bag.get(card.card_id)
        if existing is None:
            bag[card.card_id] = card
            continue
        if (
            existing.name != card.name
            or existing.functions != card.functions
            or existing.coverage_complete != card.coverage_complete
        ):
            raise ValueError(
                f"{label}[{index}] id {card.card_id!r} has inconsistent name "
                "or function facts"
            )
        bag[card.card_id] = _Card(
            card_id=existing.card_id,
            name=existing.name,
            count=existing.count + card.count,
            functions=existing.functions,
            coverage_complete=existing.coverage_complete,
        )
    return bag


def _parse_card(raw: Any, path: str) -> _Card:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a dict")
    missing = [field for field in REQUIRED_CARD_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{path} missing fields: {', '.join(missing)}")
    card_id = _require_nonempty_str(raw["id"], f"{path}.id")
    name = _require_nonempty_str(raw["name"], f"{path}.name")
    if "count" in raw:
        count = _require_positive_int(raw["count"], f"{path}.count")
    else:
        count = 1
    functions = _parse_functions(raw["functions"], f"{path}.functions")
    _validate_numeric_tree(raw, path=path)
    complete = raw.get("coverage_complete", False)
    if not isinstance(complete, bool):
        raise ValueError(f"{path}.coverage_complete must be bool")
    return _Card(
        card_id=card_id,
        name=name,
        count=count,
        functions=functions,
        coverage_complete=complete,
    )


def _parse_functions(raw: Any, path: str) -> tuple[_Fn, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{path} must be a list of dicts")
    by_key_scope: dict[tuple[str, str], _Fn] = {}
    for index, item in enumerate(raw):
        function = _parse_function(item, f"{path}[{index}]")
        ident = (function.key, function.scope)
        existing = by_key_scope.get(ident)
        if existing is None:
            by_key_scope[ident] = function
        elif existing != function:
            raise ValueError(
                f"{path} has conflicting duplicate function "
                f"{function.key!r}/{function.scope!r}"
            )
    return tuple(
        sorted(
            by_key_scope.values(),
            key=lambda fn: (fn.key, fn.scope, fn.confidence, fn.evidence),
        )
    )


def _parse_function(raw: Any, path: str) -> _Fn:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a dict")
    missing = [field for field in REQUIRED_FUNCTION_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{path} missing fields: {', '.join(missing)}")
    key = _require_nonempty_str(raw["key"], f"{path}.key")
    scope = _require_nonempty_str(raw["scope"], f"{path}.scope")
    confidence = raw["confidence"]
    if not isinstance(confidence, str) or confidence not in VALID_CONFIDENCE:
        raise ValueError(
            f"{path}.confidence must be one of {sorted(VALID_CONFIDENCE)}, "
            f"got {confidence!r}"
        )
    evidence_raw = raw["evidence"]
    if not isinstance(evidence_raw, list):
        raise ValueError(f"{path}.evidence must be a list of str")
    evidence_items: list[str] = []
    for index, item in enumerate(evidence_raw):
        if not isinstance(item, str):
            raise ValueError(f"{path}.evidence[{index}] must be str")
        evidence_items.append(item)
    if confidence == CONFIDENCE_SUPPORTED and not evidence_items:
        raise ValueError(f"{path} supported confidence requires nonempty evidence")
    evidence = tuple(sorted(set(evidence_items)))
    return _Fn(key=key, scope=scope, confidence=confidence, evidence=evidence)


def _assert_same_oracle(before: dict[str, _Card], after: dict[str, _Card]) -> None:
    for card_id in sorted(set(before) & set(after)):
        left = before[card_id]
        right = after[card_id]
        if (
            left.name != right.name
            or left.functions != right.functions
            or left.coverage_complete != right.coverage_complete
        ):
            raise ValueError(
                f"card {card_id!r} has different facts in before and after; "
                "caller must use the same facts oracle on both arms"
            )


def _multiset_diff(
    before: dict[str, _Card],
    after: dict[str, _Card],
) -> tuple[list[dict[str, str | int]], list[dict[str, str | int]]]:
    added: list[dict[str, str | int]] = []
    removed: list[dict[str, str | int]] = []
    for card_id in sorted(set(before) | set(after)):
        previous = before.get(card_id)
        current = after.get(card_id)
        previous_count = 0 if previous is None else previous.count
        current_count = 0 if current is None else current.count
        canonical = current if current is not None else previous
        if canonical is None:
            continue
        name = canonical.name
        if current_count > previous_count:
            added.append(
                {"id": card_id, "name": name, "count": current_count - previous_count}
            )
        if previous_count > current_count:
            removed.append(
                {"id": card_id, "name": name, "count": previous_count - current_count}
            )
    added.sort(key=lambda row: (row["id"], row["name"]))
    removed.sort(key=lambda row: (row["id"], row["name"]))
    return added, removed


def _supported_counts(bag: dict[str, _Card]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for card in bag.values():
        for function in card.functions:
            if function.confidence != CONFIDENCE_SUPPORTED:
                continue
            ident = (function.key, function.scope)
            counts[ident] = counts.get(ident, 0) + card.count
    return counts


def _lost_supported(
    before: dict[str, _Card],
    after: dict[str, _Card],
) -> list[dict[str, str | int]]:
    previous = _supported_counts(before)
    current = _supported_counts(after)
    lost_rows: list[dict[str, str | int]] = []
    for ident in sorted(set(previous) | set(current)):
        before_count = previous.get(ident, 0)
        after_count = current.get(ident, 0)
        lost = before_count - after_count
        if lost <= 0:
            continue
        key, scope = ident
        lost_rows.append(
            {
                "key": key,
                "scope": scope,
                "before": before_count,
                "after": after_count,
                "lost": lost,
            }
        )
    lost_rows.sort(key=lambda row: (row["key"], row["scope"]))
    return lost_rows


def _unknown_removals(
    removed: list[dict[str, str | int]],
    before: dict[str, _Card],
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for row in removed:
        card = before[str(row["id"])]
        has_incomplete = any(
            function.confidence != CONFIDENCE_SUPPORTED for function in card.functions
        )
        if card.coverage_complete and not has_incomplete:
            continue
        rows.append(
            {
                "id": card.card_id,
                "name": card.name,
                "count": row["count"],
                "reason": UNKNOWN_REMOVAL_REASON,
                "coverage_complete": False,
            }
        )
    rows.sort(key=lambda item: (item["id"], item["name"]))
    return rows


def _require_nonempty_str(value: Any, path: str) -> str:
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

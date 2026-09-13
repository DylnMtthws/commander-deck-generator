"""Watchlisted candidate snapshots for diagnostic inspection.

This module is a pure reporter. It does not call models, networks, or the
pipeline, and it does not infer scores or rewrite candidate lists. A
``CandidateTrace`` records which watched names appear in a candidate iterable
at a named stage, copying only public semantic and scoring fields.

``CandidateTrace(names)``, ``record(stage, cards)``, ``to_dict()`` schema
------------------------------------------------------------------------

``names`` is an iterable of exact, case-sensitive, nonempty strings. Blank
(empty or whitespace-only) and non-string values are rejected. Duplicates
collapse to a sorted unique list. Matching never casefolds or strips, so
``"Sol Ring"``, ``"sol ring"``, and ``"Sol Ring "`` stay distinct.

``stage`` is a nonempty string. Stages append in ``record`` call order;
duplicate labels are distinct observations, not merges.

``cards`` is an iterable of card dicts. Every row is validated before the
stage is committed. Each watched name is listed on the stage (explicit
``present: false`` when absent). Every matching printing is kept, in input
order, including identical duplicate records.

Return value (JSON-serializable)::

    {
      "names": [str, ...],  # sorted unique watched names
      "stages": [
        {
          "stage": str,
          "cards": [
            {
              "name": str,
              "present": bool,
              "matches": [whitelisted card dict, ...],  # input order
            },
            ...  # watched-name order
          ],
        },
        ...
      ],
    }

Copied card dicts include only present whitelist keys. Nested values are
deep-copied so later mutations of the input (or of a ``to_dict()`` result)
cannot change recorded history. Instances do not share state.
"""

# Invalid inputs use ValueError by the reporting API contract.
# ruff: noqa: TRY004
from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any, Final

PUBLIC_SEMANTIC_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "oracle_id",
    "name",
    "oracle_text",
    "type_line",
    "mana_cost",
    "cmc",
    "mana_value",
    "color_identity",
    "colors",
    "power",
    "toughness",
    "keywords",
    "layout",
    "is_legal_commander",
    "is_legal_in_99",
    "price_usd",
    "current_price_usd",
)

SCORING_FIELDS: Final[tuple[str, ...]] = (
    "_cvar_score",
    "_selection_inclusion",
    "_selection_synergy",
    "_selection_base_score",
    "_verified_roles",
    "_empirical_inclusion",
    "_empirical_synergy",
    "_anti_engine",
    "_categorical_exclusion",
    "role_tags",
    "functional_categories",
)

CARD_FIELD_WHITELIST: Final[tuple[str, ...]] = PUBLIC_SEMANTIC_FIELDS + SCORING_FIELDS


class CandidateTrace:
    """Record watchlisted candidate printings at named diagnostic stages.

    Args:
        names: Iterable of exact watched card names. Duplicates are dropped;
            the stored order is sorted unique. Matching is case-sensitive and
            does not strip.

    Raises:
        ValueError: ``names`` is a string, is not iterable, or contains a
            non-string or blank name.
    """

    def __init__(self, names: Iterable[str]) -> None:
        self._names: tuple[str, ...] = _normalize_names(names)
        self._stages: list[dict[str, Any]] = []

    def record(self, stage: str, cards: Iterable[Mapping[str, Any]]) -> None:
        """Snapshot watched names against a candidate iterable.

        Validation of ``stage`` and every card row finishes before the stage
        is appended, so a failed call does not partially record.

        Args:
            stage: Nonempty stage label. Duplicate labels are allowed and
                stored as separate observations in call order.
            cards: Iterable of card dicts. Each dict must include a nonempty
                ``name`` string. Extra keys are ignored.

        Raises:
            ValueError: Blank or non-string ``stage``, ``cards`` is a string or
                mapping rather than an iterable of dicts, or a row is
                malformed.
        """
        stage_name = _require_nonempty_str(stage, "stage")
        rows = _parse_cards(cards)
        self._stages.append(_build_stage(stage_name, self._names, rows))

    def to_dict(self) -> dict[str, Any]:
        """Return a deep copy of the recorded names and stages.

        Returns:
            ``{"names": [...], "stages": [...]}``. Each call returns a new
            object graph so mutations of the result cannot alter internal
            state.
        """
        return copy.deepcopy(
            {
                "names": list(self._names),
                "stages": self._stages,
            }
        )


def _normalize_names(names: Any) -> tuple[str, ...]:
    items = _as_sequence(names, "names", allow_mapping=True)
    unique: set[str] = set()
    for index, raw in enumerate(items):
        unique.add(_require_nonempty_str(raw, f"names[{index}]"))
    return tuple(sorted(unique))


def _parse_cards(cards: Any) -> list[dict[str, Any]]:
    items = _as_sequence(cards, "cards", allow_mapping=False)
    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        parsed.append(_parse_card(raw, f"cards[{index}]"))
    return parsed


def _parse_card(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a dict")
    if "name" not in raw:
        raise ValueError(f"{path} missing fields: name")
    _require_nonempty_str(raw["name"], f"{path}.name")
    return raw


def _build_stage(
    stage: str,
    names: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    for name in names:
        matches = [_project_card(row) for row in rows if row["name"] == name]
        cards.append(
            {
                "name": name,
                "present": bool(matches),
                "matches": matches,
            }
        )
    return {"stage": stage, "cards": cards}


def _project_card(card: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for field in CARD_FIELD_WHITELIST:
        if field in card:
            projected[field] = copy.deepcopy(card[field])
    return projected


def _as_sequence(value: Any, label: str, *, allow_mapping: bool) -> list[Any]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an iterable of values, not a string")
    if not allow_mapping and isinstance(value, Mapping):
        raise ValueError(f"{label} must be an iterable of card dicts, not a mapping")
    try:
        return list(value)
    except TypeError as exc:
        raise ValueError(f"{label} must be iterable") from exc


def _require_nonempty_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{path} must be a non-empty string")
    return value

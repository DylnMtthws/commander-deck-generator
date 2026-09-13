"""Descriptive summaries of isolated generator-arm experiments.

This module is a pure reporter. It does not run the pipeline, invent a
composite score, pick a winner, or attach confidence intervals / p-values.
Small ``n`` only supports descriptive paired deltas.

``summarize(rows)`` schema
--------------------------

Each input row is a ``dict`` with required fields:

* ``case_id`` (str)
* ``arm`` (str)
* ``repeat`` (int; bools rejected)
* ``status`` (``"completed"`` or ``"failed"``)
* ``hard_failures`` (int)
* ``flagged_cards`` (int)
* ``price`` (finite float)
* ``budget`` (finite float; must be nonzero when ``status == "completed"``)
* ``elapsed`` (finite float)

Additional keys are optional metrics. Finite numeric extras that appear on
every completed row of an arm are included in that arm's medians only. They
are never used to rank arms or to fill paired deltas.

Return value (JSON-serializable)::

    {
      "schema_version": "experiment-report.v1",
      "disclaimer": <str>,  # no CI / significance / winner claims
      "arms": [
        {
          "arm": str,
          "attempted": int,   # completed + failed; failures stay in this n
          "completed": int,
          "failed": int,
          "medians": {
            "hard_failures": number | None,  # completed rows only
            "flagged_cards": number | None,
            "elapsed": number | None,
            "price": number | None,
            "budget": number | None,
            <optional metric>: number | None,  # sorted name, completed only
          },
        },
        ...
      ],
      "comparisons": [
        {
          "arm": str,              # non-baseline arm
          "versus": "baseline",
          "attempted_pairs": int,  # keys present on BOTH arms, any status
          "completed_pairs": int,  # both completed; median n
          "median_deltas": {       # candidate - baseline; completed pairs only
            "hard_failures": number | None,
            "flagged_cards": number | None,
            "elapsed": number | None,
            "price": number | None,
          },
          "paired": [
            {
              "case_id": str,
              "repeat": int,
              "delta_hard_failures": number,
              "delta_flagged_cards": number,
              "delta_elapsed": number,
              "delta_price": number,
            },
            ...
          ],
          "unpaired": [  # both arms have the key; at least one failed
            {
              "case_id": str,
              "repeat": int,
              "reason": "failed_arm" | "failed_baseline" | "failed_both",
              "baseline_status": "completed" | "failed",
              "arm_status": "completed" | "failed",
            },
            ...
          ],
          "missing": [  # exact (case_id, repeat) absent on one arm
            {
              "case_id": str,
              "repeat": int,
              "reason": "missing_arm" | "missing_baseline",
              "baseline_status": "completed" | "failed" | None,
              "arm_status": "completed" | "failed" | None,
            },
            ...
          ],
        },
        ...
      ],
    }

Pairing uses the exact ``(case_id, repeat)`` tuple; ``case_id`` alone is not
a key. Duplicate ``(arm, case_id, repeat)`` raises ``ValueError``. Empty
``rows`` is a valid report (empty ``arms`` / ``comparisons``). Input rows
and the input list are not mutated. Arm / pair / missing order is
deterministic (baseline first, then lexical arm name; pairs by
``(case_id, repeat)``).
"""

# All invalid row inputs use ValueError by the reporting API contract.
# ruff: noqa: TRY004
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from typing import Any, Final

SCHEMA_VERSION: Final = "experiment-report.v1"
BASELINE_ARM: Final = "baseline"
DISCLAIMER: Final = (
    "Descriptive paired deltas only. Small n does not support confidence "
    "intervals or significance claims. No composite score or ranked winner."
)

STATUS_COMPLETED: Final = "completed"
STATUS_FAILED: Final = "failed"
VALID_STATUSES: Final = frozenset({STATUS_COMPLETED, STATUS_FAILED})

REQUIRED_FIELDS: Final = (
    "case_id",
    "arm",
    "repeat",
    "status",
    "hard_failures",
    "flagged_cards",
    "price",
    "budget",
    "elapsed",
)
INT_FIELDS: Final = ("repeat", "hard_failures", "flagged_cards")
FLOAT_FIELDS: Final = ("price", "budget", "elapsed")
MEDIAN_FIELDS: Final = (
    "hard_failures",
    "flagged_cards",
    "elapsed",
    "price",
    "budget",
)
PAIR_DELTA_FIELDS: Final = (
    "hard_failures",
    "flagged_cards",
    "elapsed",
    "price",
)

_Row = dict[str, Any]
_PairKey = tuple[str, int]


def summarize(rows: list[dict]) -> dict:
    """Collapse experiment rows into per-arm counts, medians, and paired deltas.

    Args:
        rows: Experiment observations. See module docstring for the exact
            input and output schema.

    Returns:
        JSON-serializable report. Failed runs remain in ``attempted`` and in
        comparison ``attempted_pairs``; they are listed under ``unpaired``
        instead of being dropped so a completed-only median looks like the
        full sample.

    Raises:
        ValueError: Duplicate ``(arm, case_id, repeat)``, non-finite
            numerics, zero budget on a completed row, missing/invalid
            required fields, or a non-list ``rows`` value.
    """
    parsed = _parse_rows(rows)
    by_arm = _index_by_arm(parsed)
    arm_names = _ordered_arm_names(by_arm)
    baseline_index = by_arm.get(BASELINE_ARM, {})

    arms = [_arm_summary(name, by_arm[name]) for name in arm_names]
    comparisons = [
        _comparison_summary(name, by_arm[name], baseline_index)
        for name in arm_names
        if name != BASELINE_ARM
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "disclaimer": DISCLAIMER,
        "arms": arms,
        "comparisons": comparisons,
    }


def _parse_rows(rows: list[dict]) -> list[_Row]:
    if not isinstance(rows, list):
        raise ValueError("rows must be a list of dicts")
    parsed: list[_Row] = []
    seen: set[tuple[str, str, int]] = set()
    for index, raw in enumerate(rows):
        row = _parse_row(raw, index)
        identity = (row["arm"], row["case_id"], row["repeat"])
        if identity in seen:
            raise ValueError(
                "duplicate arm/case_id/repeat: "
                f"({row['arm']!r}, {row['case_id']!r}, {row['repeat']})"
            )
        seen.add(identity)
        parsed.append(row)
    return parsed


def _parse_row(raw: Any, index: int) -> _Row:
    if not isinstance(raw, dict):
        raise ValueError(f"row {index} must be a dict")
    required = (
        REQUIRED_FIELDS
        if raw.get("status") == STATUS_COMPLETED
        else ("case_id", "arm", "repeat", "status", "elapsed", "budget")
    )
    missing = [name for name in required if name not in raw]
    if missing:
        raise ValueError(f"row {index} missing fields: {', '.join(missing)}")

    case_id = _require_str(raw["case_id"], "case_id", index)
    arm = _require_str(raw["arm"], "arm", index)
    status = raw["status"]
    if not isinstance(status, str) or status not in VALID_STATUSES:
        raise ValueError(
            f"row {index} status must be 'completed' or 'failed', got {status!r}"
        )

    parsed: _Row = {
        "case_id": case_id,
        "arm": arm,
        "status": status,
        "repeat": _require_int(raw["repeat"], "repeat", index),
        "hard_failures": (
            _require_int(raw["hard_failures"], "hard_failures", index)
            if "hard_failures" in raw
            else None
        ),
        "flagged_cards": (
            _require_int(raw["flagged_cards"], "flagged_cards", index)
            if "flagged_cards" in raw
            else None
        ),
        "price": (
            _require_float(raw["price"], "price", index) if "price" in raw else None
        ),
        "budget": _require_float(raw["budget"], "budget", index),
        "elapsed": _require_float(raw["elapsed"], "elapsed", index),
        "optional": _optional_metrics(raw, index),
    }
    for field in (
        "repeat",
        "hard_failures",
        "flagged_cards",
        "price",
        "elapsed",
        "budget",
    ):
        if parsed[field] is not None and parsed[field] < 0:
            raise ValueError(f"row {index} negative {field}")
    if status == STATUS_COMPLETED and parsed["budget"] == 0.0:
        raise ValueError(f"row {index} zero budget invalid for completed run")
    return parsed


def _optional_metrics(raw: Mapping[str, Any], index: int) -> dict[str, float]:
    extras: dict[str, float] = {}
    for key, value in raw.items():
        if key in REQUIRED_FIELDS:
            continue
        if not isinstance(key, str):
            raise ValueError(f"row {index} optional metric names must be str")
        if not _is_number(value):
            continue
        extras[key] = _require_float(value, key, index)
    return extras


def _index_by_arm(parsed: list[_Row]) -> dict[str, dict[_PairKey, _Row]]:
    by_arm: dict[str, dict[_PairKey, _Row]] = {}
    for row in parsed:
        arm_rows = by_arm.setdefault(row["arm"], {})
        arm_rows[(row["case_id"], row["repeat"])] = row
    return by_arm


def _ordered_arm_names(by_arm: Mapping[str, Any]) -> list[str]:
    names = sorted(by_arm)
    if BASELINE_ARM in by_arm:
        names.remove(BASELINE_ARM)
        names.insert(0, BASELINE_ARM)
    return names


def _arm_summary(name: str, indexed: Mapping[_PairKey, _Row]) -> dict[str, Any]:
    rows = list(indexed.values())
    completed = [row for row in rows if row["status"] == STATUS_COMPLETED]
    failed = len(rows) - len(completed)
    medians: dict[str, Any] = {
        field: _median([row[field] for row in completed]) for field in MEDIAN_FIELDS
    }
    optional_keys = _shared_optional_keys(completed)
    for key in optional_keys:
        medians[key] = _median([row["optional"][key] for row in completed])
    return {
        "arm": name,
        "attempted": len(rows),
        "completed": len(completed),
        "failed": failed,
        "medians": medians,
    }


def _shared_optional_keys(completed: list[_Row]) -> list[str]:
    if not completed:
        return []
    shared = set(completed[0]["optional"])
    for row in completed[1:]:
        shared.intersection_update(row["optional"])
    return sorted(shared)


def _comparison_summary(
    arm_name: str,
    arm_index: Mapping[_PairKey, _Row],
    baseline_index: Mapping[_PairKey, _Row],
) -> dict[str, Any]:
    paired: list[dict[str, Any]] = []
    unpaired: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    deltas: dict[str, list[float]] = {field: [] for field in PAIR_DELTA_FIELDS}

    for key in sorted(set(arm_index) | set(baseline_index)):
        case_id, repeat = key
        arm_row = arm_index.get(key)
        base_row = baseline_index.get(key)
        if arm_row is None or base_row is None:
            missing.append(
                _gap_entry(
                    case_id,
                    repeat,
                    reason="missing_arm" if arm_row is None else "missing_baseline",
                    baseline_row=base_row,
                    arm_row=arm_row,
                )
            )
            continue
        if (
            arm_row["status"] == STATUS_COMPLETED
            and base_row["status"] == STATUS_COMPLETED
        ):
            entry = {
                "case_id": case_id,
                "repeat": repeat,
            }
            for field in PAIR_DELTA_FIELDS:
                delta = arm_row[field] - base_row[field]
                entry[f"delta_{field}"] = delta
                deltas[field].append(delta)
            paired.append(entry)
            continue
        if arm_row["status"] == STATUS_FAILED and base_row["status"] == STATUS_FAILED:
            reason = "failed_both"
        elif arm_row["status"] == STATUS_FAILED:
            reason = "failed_arm"
        else:
            reason = "failed_baseline"
        unpaired.append(
            _gap_entry(
                case_id,
                repeat,
                reason=reason,
                baseline_row=base_row,
                arm_row=arm_row,
            )
        )

    attempted_pairs = len(paired) + len(unpaired)
    return {
        "arm": arm_name,
        "versus": BASELINE_ARM,
        "attempted_pairs": attempted_pairs,
        "completed_pairs": len(paired),
        "median_deltas": {field: _median(values) for field, values in deltas.items()},
        "paired": paired,
        "unpaired": unpaired,
        "missing": missing,
    }


def _gap_entry(
    case_id: str,
    repeat: int,
    *,
    reason: str,
    baseline_row: _Row | None,
    arm_row: _Row | None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "repeat": repeat,
        "reason": reason,
        "baseline_status": None if baseline_row is None else baseline_row["status"],
        "arm_status": None if arm_row is None else arm_row["status"],
    }


def _median(values: list[Any]) -> Any:
    if not values:
        return None
    return statistics.median(values)


def _require_str(value: Any, field: str, index: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"row {index} {field} must be str")
    return value


def _require_int(value: Any, field: str, index: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"row {index} {field} must be an int")
    if isinstance(value, int):
        return value
    if _is_number(value):
        number = _require_float(value, field, index)
        as_int = int(number)
        if number == as_int:
            return as_int
    raise ValueError(f"row {index} {field} must be an int")


def _require_float(value: Any, field: str, index: int) -> float:
    if not _is_number(value):
        raise ValueError(f"row {index} {field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"row {index} nonfinite numeric field: {field}")
    return number


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

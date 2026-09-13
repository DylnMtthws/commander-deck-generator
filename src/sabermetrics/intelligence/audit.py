"""Pure selection-audit summaries and fit-verdict provenance labels.

This module does not call the deck builder, models, or data stores. The
coordinator maps generation traces into records and attaches the JSON-safe
summary to diagnostic payloads. Absence of a name in the record list is not
evidence that the card is missing from the catalog.
"""

from __future__ import annotations

import math
from typing import Any, Final

FIT_REVIEWED: Final = "reviewed"
FIT_UNREVIEWED: Final = "unreviewed"
FIT_UNRESOLVED: Final = "unresolved"

FINAL_STATUSES: Final = ("retained", "excluded", "unknown")
TERMINAL_ACTIONS: Final = frozenset({"retained", "excluded"})

_STATUS_KEY_CANDIDATES: Final = (
    "fit_verdict",
    "verdict_status",
    "review_status",
    "fit_review",
    "fit_review_status",
)

_STATUS_ALIASES: Final = {
    FIT_REVIEWED: FIT_REVIEWED,
    "complete": FIT_REVIEWED,
    FIT_UNREVIEWED: FIT_UNREVIEWED,
    "not_reviewed": FIT_UNREVIEWED,
    "not reviewed": FIT_UNREVIEWED,
    "none": FIT_UNREVIEWED,
    FIT_UNRESOLVED: FIT_UNRESOLVED,
    "incomplete": FIT_UNRESOLVED,
    "failed": FIT_UNRESOLVED,
    "flagged": FIT_UNRESOLVED,
    "partial": FIT_UNRESOLVED,
}

_UNREVIEWED_REASON_MARKERS: Final = frozenset(
    {
        "",
        "synergy-optimizer selected",
        "auto-scored",
        "default score assigned",
    }
)

_UNRESOLVED_REASON_MARKERS: Final = frozenset(
    {
        "no verdict returned.",
        "no verdict returned",
        "scoring failed; default score assigned.",
        "scoring failed; default score assigned",
    }
)

_HISTORY_OPTIONAL_KEYS: Final = (
    "score",
    "scores",
    "score_components",
    "fit_score",
    "fit10",
    "llm_fit_score",
    "watchlisted",
    "watchlist",
    "card_id",
    "timestamp",
)


def summarize_selection_audit(records: list[dict]) -> dict:
    """Collapse per-card traces into final dispositions plus full history.

    Args:
        records: Selection events with ``name`` (or ``card_name``), ``stage``,
            ``action``, ``reason``, and optional scores. Terminal actions are
            only ``retained`` and ``excluded``. Provisional actions such as
            ``rejected`` and ``re-admitted`` stay in history and never become
            the final status.

    Returns:
        JSON-serializable dict with ``counts`` and ``cards``. Each card has
        ``name``, ``final_status``, ``stage``, ``reason``, and ``history``.
        Duplicate rows for the same name are all retained in ``history``.
        Empty input yields empty cards; missing names are not invented.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        entry = _history_entry(raw)
        name = entry["name"]
        if not name:
            continue
        if name not in grouped:
            grouped[name] = []
            order.append(name)
        grouped[name].append(entry)

    cards: list[dict[str, Any]] = []
    retained = excluded = unknown = 0
    for name in order:
        history = grouped[name]
        terminal = _last_terminal(history)
        if terminal is None:
            status = "unknown"
            stage = history[-1]["stage"]
            reason = history[-1]["reason"]
            unknown += 1
        else:
            status = _norm_action(terminal["action"])
            stage = terminal["stage"]
            reason = terminal["reason"]
            if status == "retained":
                retained += 1
            else:
                excluded += 1
        cards.append(
            {
                "name": name,
                "final_status": status,
                "stage": stage,
                "reason": reason,
                "history": history,
            }
        )

    return {
        "counts": {
            "records": sum(len(grouped[name]) for name in order),
            "cards": len(cards),
            "retained": retained,
            "excluded": excluded,
            "unknown": unknown,
        },
        "cards": cards,
    }


def classify_fit_verdict(payload: dict | None) -> str:
    """Label fit metadata as reviewed, unreviewed, or unresolved.

    A numeric ``fit10`` / ``fit_score`` / ``llm_fit_score`` is never enough
    to claim review. Default optimizer scores, including a 10-point scale
    value of 10, stay unreviewed unless an explicit verdict status or review
    flag is present. Incomplete or failed reviews are unresolved.

    Args:
        payload: Card or verdict dict. ``None`` or a non-dict is unreviewed.

    Returns:
        One of ``reviewed``, ``unreviewed``, ``unresolved``.
    """
    if not isinstance(payload, dict):
        return FIT_UNREVIEWED

    explicit = _explicit_fit_status(payload)
    if _unresolved_review(payload, explicit):
        return FIT_UNRESOLVED
    if explicit == FIT_REVIEWED:
        return FIT_REVIEWED
    if explicit == FIT_UNREVIEWED:
        return FIT_UNREVIEWED
    if payload.get("reviewed") is True:
        return FIT_REVIEWED
    if payload.get("reviewed") is False:
        return FIT_UNREVIEWED

    reason = _fit_reason_text(payload)
    lowered = reason.lower().strip()
    if lowered in _UNRESOLVED_REASON_MARKERS:
        return FIT_UNRESOLVED
    if lowered in _UNREVIEWED_REASON_MARKERS:
        return FIT_UNREVIEWED
    return FIT_UNREVIEWED


def is_terminal_action(action: Any) -> bool:
    """Return True when ``action`` is an explicit retained/excluded decision."""
    return _norm_action(action) in TERMINAL_ACTIONS


def _last_terminal(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    terminal = None
    for event in history:
        if is_terminal_action(event.get("action")):
            terminal = event
    return terminal


def _norm_action(action: Any) -> str:
    return _as_text(action).lower().replace(" ", "_").replace("-", "_")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return str(value).strip()
    return ""


def _card_name(raw: dict[str, Any]) -> str:
    value = raw.get("name")
    if value is None or value == "":
        value = raw.get("card_name")
    return _as_text(value)


def _history_entry(raw: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": _card_name(raw),
        "stage": _as_text(raw.get("stage")),
        "action": _as_text(raw.get("action")),
        "reason": _as_text(raw.get("reason")),
    }
    for key in _HISTORY_OPTIONAL_KEYS:
        if key not in raw:
            continue
        encoded = _jsonable(raw[key])
        if encoded is _OMIT:
            continue
        entry[key] = encoded
    return entry


_OMIT = object()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        encoded_list: list[Any] = []
        for item in value:
            nested = _jsonable(item)
            if nested is _OMIT:
                continue
            encoded_list.append(nested)
        return encoded_list
    if isinstance(value, dict):
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            nested = _jsonable(item)
            if nested is _OMIT:
                continue
            encoded[key] = nested
        return encoded
    return _OMIT


def _explicit_fit_status(payload: dict[str, Any]) -> str | None:
    sources: list[Any] = [payload]
    nested = payload.get("verdict")
    if isinstance(nested, dict):
        sources.append(nested)
    for source in sources:
        for key in _STATUS_KEY_CANDIDATES:
            status = _alias_status(source.get(key))
            if status is not None:
                return status
        status = _alias_status(source.get("status"))
        if status is not None:
            return status
    return None


def _alias_status(value: Any) -> str | None:
    text = _as_text(value).lower().replace("-", "_")
    if not text:
        return None
    spaced = text.replace("_", " ")
    return _STATUS_ALIASES.get(text) or _STATUS_ALIASES.get(spaced)


def _unresolved_review(payload: dict[str, Any], explicit: str | None) -> bool:
    if explicit == FIT_UNRESOLVED:
        return True
    if payload.get("unresolved") is True:
        return True
    if payload.get("review_failed") is True:
        return True
    if payload.get("incomplete") is True:
        return True
    if payload.get("last_batch_complete") is False:
        return True
    attempted = (
        explicit == FIT_REVIEWED
        or payload.get("reviewed") is True
        or payload.get("verdict_complete") is False
        or payload.get("has_verdict") is False
    )
    if not attempted:
        return False
    if payload.get("verdict_complete") is False:
        return True
    return payload.get("has_verdict") is False


def _fit_reason_text(payload: dict[str, Any]) -> str:
    for key in ("_fit_reasoning", "reasoning", "reason"):
        text = _as_text(payload.get(key))
        if text:
            return text
    nested = payload.get("verdict")
    if isinstance(nested, dict):
        return _as_text(nested.get("reasoning") or nested.get("reason"))
    return ""

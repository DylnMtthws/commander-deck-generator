"""Final-deck acceptance: hard validation vs labeled quality warnings.

Validation failures are legality/size/budget/singleton defects. Quality
warnings cover unmet targets, missing signals, unavailable engines, failed
review, and requested-vs-estimated bracket. The bracket classifier is a
heuristic, never ground truth.

Review failure must not hide, and must not subtract spend via a negative
cost sentinel.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from sabermetrics.pipeline.intent import (
    EngineAdmission,
    EngineStatus,
    claims_infinite_loop,
    looks_like_finite_top_n_effect,
)

Severity = Literal["failure", "warning"]

_BASIC_LAND_NAMES: set[str] = {
    "Plains",
    "Island",
    "Swamp",
    "Mountain",
    "Forest",
    "Wastes",
    "Snow-Covered Plains",
    "Snow-Covered Island",
    "Snow-Covered Swamp",
    "Snow-Covered Mountain",
    "Snow-Covered Forest",
}

_PRICE_EPSILON = 1e-6


class QualityItem(BaseModel):
    """One inspectable acceptance finding."""

    severity: Severity
    code: str
    message: str


class AcceptanceReport(BaseModel):
    """Split validation failures from quality warnings."""

    failures: list[QualityItem] = Field(default_factory=list)
    warnings: list[QualityItem] = Field(default_factory=list)

    def all_items(self) -> list[QualityItem]:
        return list(self.failures) + list(self.warnings)

    def as_rationale_list(self) -> list[dict]:
        return [item.model_dump() for item in self.all_items()]


def ledger_review_cost(reported_cost: float, review_failed: bool) -> float:
    """Map a review cost onto the spend ledger.

    A negative sentinel (historically -1.0 on vet failure) must never
    subtract dollars. Consumed calls remain charged even when review fails.
    """
    del review_failed
    if not math.isfinite(reported_cost) or reported_cost < 0:
        return 0.0
    return float(reported_cost)


def replacement_is_valid(
    card: dict,
    *,
    commander_colors: set[str] | None,
    deck_names: set[str],
    max_price: float | None = None,
) -> tuple[bool, str]:
    """Gate a post-review replacement before it is accepted.

    Negative prices are sentinels, not discounts. Color identity and
    singleton still apply. Missing oracle/type/MV is allowed only as
    empty evidence — callers must not fabricate those fields.
    """
    name = card.get("name", "")
    if not name:
        return False, "replacement missing name"
    if name not in _BASIC_LAND_NAMES and name in deck_names:
        return False, f"replacement '{name}' would violate singleton"
    try:
        price = float(card.get("price_usd") or 0.0)
    except (TypeError, ValueError):
        return False, f"replacement '{name}' has non-numeric price"
    if not math.isfinite(price) or price < 0:
        return False, f"replacement '{name}' rejected: negative-cost sentinel"
    if max_price is not None and price > max_price + _PRICE_EPSILON:
        return False, f"replacement '{name}' exceeds remaining budget"
    if commander_colors is not None:
        ci = _color_identity(card)
        if not ci <= commander_colors:
            return False, f"replacement '{name}' is out of color identity"
    return True, "ok"


def evaluate_final_deck(
    *,
    assignments: list,
    commander_name: str,
    commander_colors: list[str] | set[str],
    budget_usd: float,
    requested_bracket: int,
    estimated_bracket: int | None,
    engine: EngineAdmission | None,
    engine_status: EngineStatus,
    signals: dict[str, bool] | None = None,
    role_counts: dict[str, int] | None = None,
    role_targets: dict[str, int] | None = None,
    review_failed: bool = False,
    commander_oracle: str | None = None,
    legality_backfill: int = 0,
) -> AcceptanceReport:
    """Run meaningful final acceptance on the assembled 99.

    Distinguishes hard failures from labeled warnings. Never claims an
    unsupported or infeasible engine was fulfilled. Never asserts that a
    finite top-N library look is a deterministic infinite loop.
    """
    report = AcceptanceReport()
    cards = [_card_of(a) for a in assignments]
    colors = set(commander_colors or [])

    if len(assignments) != 99:
        report.failures.append(
            QualityItem(
                severity="failure",
                code="deck_size",
                message=f"Expected 99 cards plus commander; assembled {len(assignments)}.",
            )
        )

    seen: set[str] = set()
    for card in cards:
        name = card.get("name", "")
        try:
            price = float(card.get("price_usd"))
        except (TypeError, ValueError):
            price = float("nan")
        if not math.isfinite(price) or price < 0:
            report.failures.append(
                QualityItem(
                    severity="failure",
                    code="invalid_price",
                    message=f"'{name}' has no valid nonnegative price.",
                )
            )
        if card.get("is_legal_in_99") in (False, 0):
            report.failures.append(
                QualityItem(
                    severity="failure",
                    code="card_legality",
                    message=f"'{name}' is not legal in the 99.",
                )
            )
        if name == commander_name:
            report.failures.append(
                QualityItem(
                    severity="failure",
                    code="commander_in_99",
                    message=f"Commander '{commander_name}' leaked into the 99.",
                )
            )
        if name and name not in _BASIC_LAND_NAMES:
            if name in seen:
                report.failures.append(
                    QualityItem(
                        severity="failure",
                        code="singleton",
                        message=f"Singleton violation: '{name}' appears more than once.",
                    )
                )
            seen.add(name)
        ci = _color_identity(card)
        if not ci <= colors:
            report.failures.append(
                QualityItem(
                    severity="failure",
                    code="color_identity",
                    message=f"'{name}' is outside the commander's color identity.",
                )
            )

    total_price = sum(_nonneg_price(c) for c in cards)
    if total_price > budget_usd + _PRICE_EPSILON:
        report.failures.append(
            QualityItem(
                severity="failure",
                code="over_budget",
                message=(
                    f"Deck total ${total_price:.2f} exceeds budget ${budget_usd:.2f}."
                ),
            )
        )

    _engine_findings(report, engine, engine_status)
    _role_findings(report, role_counts, role_targets)
    _signal_findings(report, signals)

    if review_failed:
        report.warnings.append(
            QualityItem(
                severity="warning",
                code="failed_final_review",
                message=(
                    "The bounded card review left unresolved selections or incomplete verdicts. Review the flagged choices before playing."
                ),
            )
        )

    report.warnings.append(
        QualityItem(
            severity="warning",
            code="bracket_estimate",
            message=(
                f"Requested bracket {requested_bracket}; estimated bracket "
                f"{estimated_bracket if estimated_bracket is not None else 'unknown'}. "
                "Power is an estimate based on the selected cards."
            ),
        )
    )

    if legality_backfill > 2:
        report.warnings.append(
            QualityItem(
                severity="warning",
                code="legality_backfill",
                message=(
                    f"Legality repair backfilled {legality_backfill} basic lands "
                    "because an upstream stage under-produced."
                ),
            )
        )

    # Explicit non-claim: finite top-N hits are not infinite combos.
    if looks_like_finite_top_n_effect(commander_oracle):
        for item in report.all_items():
            if claims_infinite_loop(item.message):
                item.message = (
                    "Finite top-of-library looks are not a deterministic "
                    "infinite loop; suppressed an infinite-combo claim."
                )
                item.code = "finite_top_n_not_infinite"

    return report


def _engine_findings(
    report: AcceptanceReport,
    engine: EngineAdmission | None,
    status: EngineStatus,
) -> None:
    if engine is None or status == "none":
        return
    req = engine.requirement
    if status == "unverified":
        report.warnings.append(
            QualityItem(
                severity="warning",
                code="intent_unverified",
                message=(
                    "User intent was provided but is not a supported engine "
                    f"contract ({req.raw_intent!r}). It is unverified, not fulfilled."
                ),
            )
        )
        return
    if status == "infeasible":
        missing = [r.model_dump() for r in engine.records if not r.admitted]
        detail = "; ".join(
            r.reason
            for r in engine.records
            if not r.admitted and r.reason.startswith("unavailable")
        ) or ("no copy-on-entry creatures in the legal budget-valid pool")
        report.warnings.append(
            QualityItem(
                severity="warning",
                code="engine_unavailable",
                message=(
                    "Requested clone engine is infeasible under legality/budget. "
                    f"It is not satisfied. {detail}"
                ),
            )
        )
        _ = missing  # records stay on the engine object for the rationale
        return
    if status == "unsatisfied":
        report.warnings.append(
            QualityItem(
                severity="warning",
                code="engine_unsatisfied",
                message=(
                    f"Clone engine required at least {req.min_count} copy-on-entry "
                    "creatures in the final list; the finished deck does not meet "
                    "that target. Not reporting the intent as fulfilled."
                ),
            )
        )
        return
    # status == satisfied: no warning. Presence is recorded on the engine
    # rationale object, not as a quality complaint.


def _role_findings(
    report: AcceptanceReport,
    role_counts: dict[str, int] | None,
    role_targets: dict[str, int] | None,
) -> None:
    if not role_targets:
        return
    counts = role_counts or {}
    for role, target in role_targets.items():
        if target <= 0:
            continue
        have = counts.get(role, 0)
        if have < target:
            report.warnings.append(
                QualityItem(
                    severity="warning",
                    code="unmet_role_target",
                    message=f"Unmet role target: {role} {have} < {target}.",
                )
            )


def _signal_findings(
    report: AcceptanceReport,
    signals: dict[str, bool] | None,
) -> None:
    if not signals:
        return
    missing = sorted(name for name, live in signals.items() if not live)
    for name in missing:
        report.warnings.append(
            QualityItem(
                severity="warning",
                code="signal_unavailable",
                message=f"Scoring/data signal '{name}' was unavailable for this build.",
            )
        )


def _card_of(assignment) -> dict:
    if isinstance(assignment, dict):
        return assignment
    card = getattr(assignment, "card", assignment)
    return card if isinstance(card, dict) else {}


def _color_identity(card: dict) -> set[str]:
    ci = card.get("color_identity", [])
    if isinstance(ci, str):
        import json

        try:
            ci = json.loads(ci)
        except (json.JSONDecodeError, TypeError):
            ci = []
    return set(ci or [])


def _nonneg_price(card: dict) -> float:
    try:
        price = float(card.get("price_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, price)

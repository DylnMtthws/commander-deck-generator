"""Synthetic diagnostics for selection-audit summaries and fit provenance."""

from __future__ import annotations

import json
import math

from sabermetrics.intelligence.audit import (
    FIT_REVIEWED,
    FIT_UNRESOLVED,
    FIT_UNREVIEWED,
    classify_fit_verdict,
    is_terminal_action,
    summarize_selection_audit,
)


def _event(name, stage, action, reason="", **extra):
    row = {"name": name, "stage": stage, "action": action, "reason": reason}
    row.update(extra)
    return row


def test_empty_traces_do_not_invent_catalog_gaps():
    summary = summarize_selection_audit([])
    assert summary["cards"] == []
    assert summary["counts"] == {
        "records": 0,
        "cards": 0,
        "retained": 0,
        "excluded": 0,
        "unknown": 0,
    }
    assert "catalog" not in summary
    dumped = json.loads(json.dumps(summary))
    assert dumped["cards"] == []


def test_provisional_rejected_is_unknown_not_excluded():
    summary = summarize_selection_audit(
        [
            _event(
                "Audit Alpha",
                "pareto",
                "rejected",
                "dominated on the frontier",
                score=0.12,
            )
        ]
    )
    card = summary["cards"][0]
    assert card["name"] == "Audit Alpha"
    assert card["final_status"] == "unknown"
    assert card["stage"] == "pareto"
    assert card["reason"] == "dominated on the frontier"
    assert len(card["history"]) == 1
    assert card["history"][0]["action"] == "rejected"
    assert summary["counts"]["excluded"] == 0
    assert summary["counts"]["unknown"] == 1


def test_provisional_readmitted_is_unknown_not_retained():
    summary = summarize_selection_audit(
        [
            _event("Audit Beta", "pareto", "rejected", "dominated"),
            _event("Audit Beta", "swap_refine", "re-admitted", "role floor"),
        ]
    )
    card = summary["cards"][0]
    assert card["final_status"] == "unknown"
    assert [row["action"] for row in card["history"]] == ["rejected", "re-admitted"]
    assert summary["counts"]["retained"] == 0
    assert summary["counts"]["unknown"] == 1


def test_explicit_retained_beats_earlier_provisional_reject():
    summary = summarize_selection_audit(
        [
            _event("Audit Gamma", "pareto", "rejected", "dominated"),
            _event("Audit Gamma", "final", "retained", "in the 99", score=0.81),
        ]
    )
    card = summary["cards"][0]
    assert card["final_status"] == "retained"
    assert card["stage"] == "final"
    assert card["reason"] == "in the 99"
    assert len(card["history"]) == 2
    assert summary["counts"]["retained"] == 1
    assert summary["counts"]["unknown"] == 0


def test_explicit_excluded_beats_earlier_placed_trace():
    summary = summarize_selection_audit(
        [
            _event("Audit Delta", "greedy_fill", "placed", "filled ramp"),
            _event("Audit Delta", "legality", "excluded", "color identity"),
        ]
    )
    card = summary["cards"][0]
    assert card["final_status"] == "excluded"
    assert card["stage"] == "legality"
    assert card["reason"] == "color identity"
    assert summary["counts"]["excluded"] == 1


def test_later_provisional_reject_does_not_override_retained():
    summary = summarize_selection_audit(
        [
            _event("Audit Epsilon", "final", "retained", "kept"),
            _event("Audit Epsilon", "note", "rejected", "stale frontier row"),
        ]
    )
    assert summary["cards"][0]["final_status"] == "retained"
    assert summary["cards"][0]["reason"] == "kept"
    assert len(summary["cards"][0]["history"]) == 2


def test_later_terminal_wins_among_explicit_decisions():
    summary = summarize_selection_audit(
        [
            _event("Audit Zeta", "mid", "excluded", "cut for budget"),
            _event("Audit Zeta", "final", "retained", "reinstated after cut"),
        ]
    )
    assert summary["cards"][0]["final_status"] == "retained"
    assert summary["cards"][0]["stage"] == "final"


def test_duplicates_keep_full_watchlisted_history():
    records = [
        _event(
            "Audit Eta",
            "pareto",
            "rejected",
            "first look",
            watchlisted=True,
            score=0.2,
        ),
        _event(
            "Audit Eta",
            "pareto",
            "rejected",
            "second look",
            watchlisted=True,
            score=0.2,
        ),
        _event(
            "Audit Eta",
            "final",
            "retained",
            "protected package",
            watchlisted=True,
        ),
    ]
    summary = summarize_selection_audit(records)
    card = summary["cards"][0]
    assert len(card["history"]) == 3
    assert [row["reason"] for row in card["history"]] == [
        "first look",
        "second look",
        "protected package",
    ]
    assert all(row["watchlisted"] is True for row in card["history"])
    assert summary["counts"]["records"] == 3
    assert summary["counts"]["cards"] == 1


def test_card_name_alias_and_optional_scores_are_json_safe():
    summary = summarize_selection_audit(
        [
            {
                "card_name": "Audit Theta",
                "stage": "llm_safety",
                "action": "flagged",
                "reason": "no safe replacement",
                "score": 0.5,
                "scores": {"cvar": 0.4, "fit": float("nan")},
                "score_components": {"synergy": 0.1},
                "fit10": 10,
            }
        ]
    )
    card = summary["cards"][0]
    assert card["name"] == "Audit Theta"
    assert card["final_status"] == "unknown"
    history = card["history"][0]
    assert history["score"] == 0.5
    assert history["fit10"] == 10
    assert history["scores"]["fit"] is None
    dumped = json.dumps(summary)
    loaded = json.loads(dumped)
    assert loaded["cards"][0]["history"][0]["score_components"]["synergy"] == 0.1
    assert math.isfinite(loaded["counts"]["records"])


def test_skips_non_dicts_and_nameless_rows_without_inventing_cards():
    summary = summarize_selection_audit(
        [
            "not-a-record",
            None,
            {"stage": "pareto", "action": "rejected"},
            _event("Audit Iota", "final", "excluded", "banned"),
        ]
    )
    assert summary["counts"]["cards"] == 1
    assert summary["counts"]["records"] == 1
    assert summary["cards"][0]["name"] == "Audit Iota"
    assert summary["cards"][0]["final_status"] == "excluded"


def test_multiple_cards_first_seen_order():
    summary = summarize_selection_audit(
        [
            _event("Audit Kappa", "pareto", "placed", "kept"),
            _event("Audit Lambda", "final", "excluded", "cut"),
            _event("Audit Kappa", "final", "retained", "in deck"),
        ]
    )
    assert [card["name"] for card in summary["cards"]] == [
        "Audit Kappa",
        "Audit Lambda",
    ]
    assert summary["cards"][0]["final_status"] == "retained"
    assert summary["cards"][1]["final_status"] == "excluded"
    assert summary["counts"]["retained"] == 1
    assert summary["counts"]["excluded"] == 1
    assert summary["counts"]["unknown"] == 0


def test_numeric_fit10_alone_is_unreviewed():
    assert classify_fit_verdict({"fit10": 10}) == FIT_UNREVIEWED
    assert classify_fit_verdict({"fit_score": 10}) == FIT_UNREVIEWED
    assert classify_fit_verdict({"llm_fit_score": 5}) == FIT_UNREVIEWED
    assert classify_fit_verdict({"fit_score": 8, "score": 0.8}) == FIT_UNREVIEWED
    assert classify_fit_verdict(None) == FIT_UNREVIEWED
    assert classify_fit_verdict({"_fit_reasoning": "Synergy-optimizer selected"}) == (
        FIT_UNREVIEWED
    )
    assert classify_fit_verdict({"reasoning": "Auto-scored", "fit_score": 7}) == (
        FIT_UNREVIEWED
    )


def test_explicit_review_status_is_reviewed():
    assert (
        classify_fit_verdict(
            {
                "fit_score": 9,
                "reviewed": True,
                "reasoning": "Matches the landfall payoff clause.",
            }
        )
        == FIT_REVIEWED
    )
    assert classify_fit_verdict({"review_status": "reviewed", "fit10": 4}) == (
        FIT_REVIEWED
    )
    assert classify_fit_verdict({"fit_verdict": "reviewed"}) == FIT_REVIEWED


def test_incomplete_or_failed_review_is_unresolved():
    assert (
        classify_fit_verdict(
            {"reviewed": True, "verdict_complete": False, "fit_score": 5}
        )
        == FIT_UNRESOLVED
    )
    assert classify_fit_verdict({"review_failed": True, "fit10": 10}) == FIT_UNRESOLVED
    assert classify_fit_verdict({"review_status": "unresolved"}) == FIT_UNRESOLVED
    assert classify_fit_verdict({"unresolved": True, "reviewed": True}) == (
        FIT_UNRESOLVED
    )
    assert classify_fit_verdict(
        {"reasoning": "No verdict returned.", "fit_score": 5}
    ) == (FIT_UNRESOLVED)
    assert classify_fit_verdict({"last_batch_complete": False}) == FIT_UNRESOLVED


def test_explicit_unreviewed_status_wins_over_numeric_score():
    assert classify_fit_verdict({"fit_verdict": "unreviewed", "fit10": 10}) == (
        FIT_UNREVIEWED
    )
    assert classify_fit_verdict({"reviewed": False, "fit_score": 10}) == FIT_UNREVIEWED


def test_terminal_action_helper_ignores_provisional_verbs():
    assert is_terminal_action("retained")
    assert is_terminal_action("EXCLUDED")
    assert not is_terminal_action("rejected")
    assert not is_terminal_action("re-admitted")
    assert not is_terminal_action("placed")
    assert not is_terminal_action(None)

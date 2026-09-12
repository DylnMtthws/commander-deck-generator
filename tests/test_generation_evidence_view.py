"""Render generation evidence from deck.rationale.intelligence.

Partial is rendered directly with Flask/Jinja fixtures. No routes, auth, or
database. Synthetic payloads only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import Flask, render_template

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src" / "sabermetrics" / "ui" / "templates"
PARTIAL = TEMPLATES / "_generation_evidence.html"
DECK_VIEW = TEMPLATES / "deck_view.html"


@pytest.fixture
def app() -> Flask:
    application = Flask(__name__, template_folder=str(TEMPLATES))
    application.config["TESTING"] = True
    return application


def _render(app: Flask, intelligence=None, *, deck=None) -> str:
    if deck is None:
        deck = {"rationale": {}}
        if intelligence is not None:
            deck["rationale"]["intelligence"] = intelligence
    with app.app_context():
        return render_template("_generation_evidence.html", deck=deck)


def _measured_intelligence() -> dict:
    return {
        "version": "generation-intelligence.v1",
        "plan": {
            "archetype": "landfall",
            "status": "partial",
            "requirements": {"land_drops": 8, "payoff": 4, "protection": 3},
            "counts": {"land_drops": 8, "payoff": 2, "protection": 3},
            "missing": {"payoff": {"actual": 2, "required": 4}},
            "evidence": [
                {
                    "card": "Ashaya, Soul of the Wild",
                    "requirement": "landfall_payoff",
                    "reason": "Creature lands trigger landfall.",
                }
            ],
            "limitations": ["Token copies of lands are not modeled."],
        },
        "findings": [
            {
                "code": "unverified_prerequisite",
                "card": "Gond Gate",
                "message": "Needs a supporting Gate; that setup is unverified.",
                "severity": "warning",
            }
        ],
        "decisions": [
            {
                "card": "Ashaya, Soul of the Wild",
                "requirement": "landfall_payoff",
                "reason": "Creature lands trigger landfall.",
            }
        ],
        "simulation": {
            "status": "measured",
            "scope": "Land sequencing and commander casts through the named turn.",
            "baseline": {
                "games": 2000,
                "turns": 8,
                "commander_cast_count": 1.42,
                "lands_mean": 6.1,
                "commander_draws_mean": 0.8,
                "assumptions": [
                    "No opponents, combat, or stack.",
                    "Opening hands keep any two lands.",
                ],
            },
            "comparisons": [
                {
                    "variant": "More extra land plays",
                    "delta": 0.18,
                    "interval": [0.09, 0.27],
                    "metric": "lands_mean",
                    "improved": True,
                }
            ],
            "selected": "More extra land plays",
            "confirmation": {
                "games": 10000,
                "seed": "secret-seed-xyz",
                "hash": "a" * 40,
            },
        },
        "deck_hash": "abc123deadbeefabc123deadbeefffff",
        "input_hash": "fff00011122233344455566677788899",
    }


def test_missing_evidence_renders_empty(app) -> None:
    html = _render(app, intelligence=None)
    assert html.strip() == ""
    assert "Strategy plan" not in html
    assert "Simulation" not in html
    assert "Generation evidence" not in html


def test_legacy_rationale_without_intelligence_renders_empty(app) -> None:
    html = _render(
        app,
        deck={
            "rationale": {
                "narrative": {"game_plan": "Play lands."},
                "composition": {"total_price_usd": 10},
            }
        },
    )
    assert html.strip() == ""
    assert "Play lands." not in html
    assert "Strategy plan" not in html


def test_non_dict_intelligence_does_not_dump_json(app) -> None:
    raw = '{"status": "measured", "baseline": {"games": 0}}'
    html = _render(app, intelligence=raw)
    assert html.strip() == ""
    assert "games" not in html
    assert "{" not in html


def test_measured_result_shows_plan_scope_assumptions_and_land_only(app) -> None:
    html = _render(app, _measured_intelligence())
    assert "Strategy plan" in html
    assert "landfall" in html
    assert "Some requirements unmet" in html
    assert "Missing requirements" in html
    assert "payoff" in html
    assert "2 of 4 required" in html
    assert "Ashaya, Soul of the Wild" in html
    assert "Creature lands trigger landfall." in html
    assert "Token copies of lands are not modeled." in html
    assert "Role coverage" in html
    assert "8 of 8" in html
    assert "Scope:" in html
    assert "Land sequencing and commander casts through the named turn." in html
    assert "Assumptions" in html
    assert "No opponents, combat, or stack." in html
    assert "Opening hands keep any two lands." in html
    assert "Games" in html
    assert "2000" in html
    assert "Turn" in html
    assert ">8<" in html or "\n8<" in html or ">8</" in html
    assert "Commander affordability in a land-only scenario" in html
    assert "1.42" in html
    assert "not a win rate" in html
    assert "Average lands" in html
    assert "6.10" in html
    assert "More extra land plays" in html
    assert "0.18" in html
    assert "0.09" in html
    assert "0.27" in html
    assert "lands mean" in html
    assert "Confirmation used 10000 games." in html
    assert "Selected comparison:" in html


def test_measured_result_does_not_claim_overall_strength_or_win_rate(app) -> None:
    html = _render(app, _measured_intelligence()).lower()
    assert "win rate" not in html or "not a win rate" in html
    assert "overall deck strength improved" not in html
    assert "deck strength improved" not in html
    # The phrase "win rate" appears only as a negation of that claim.
    assert html.count("win rate") == 1
    assert "not a win rate" in html


def test_measured_result_hides_hashes_ids_schema_and_json(app) -> None:
    html = _render(app, _measured_intelligence())
    assert "generation-intelligence.v1" not in html
    assert "commander_cast_count" not in html
    assert "lands_mean" not in html
    assert "commander_draws_mean" not in html
    assert "unverified_prerequisite" not in html
    assert "abc123deadbeef" not in html
    assert "fff000111222333" not in html
    assert "secret-seed-xyz" not in html
    assert "a" * 40 not in html
    assert '{"' not in html
    assert "card_id" not in html


def test_unsupported_result_is_plain_language_not_a_zero_score(app) -> None:
    intel = {
        "version": "generation-intelligence.v1",
        "plan": {
            "archetype": "landfall",
            "status": "complete",
            "requirements": {"payoff": 4},
            "counts": {"payoff": 4},
            "missing": {},
            "evidence": [
                {
                    "card": "Aesi, Tyrant of Gyre Strait",
                    "requirement": "payoff",
                    "reason": "Draws on landfall.",
                }
            ],
            "limitations": [],
        },
        "findings": [],
        "decisions": [],
        "simulation": {
            "status": "unsupported",
            "reason": "Combat and interaction are not modeled.",
            "scope": "should not appear",
            "baseline": {
                "games": 0,
                "turns": 0,
                "commander_cast_count": 0,
                "lands_mean": 0.0,
                "commander_draws_mean": 0.0,
                "assumptions": ["fabricated"],
            },
            "comparisons": [
                {
                    "variant": "Aggro cut",
                    "delta": 0.0,
                    "interval": [0.0, 0.0],
                    "metric": "win_rate",
                    "improved": True,
                }
            ],
            "selected": "Aggro cut",
        },
    }
    html = _render(app, intel)
    assert "This simulation scenario is not supported." in html
    assert "Combat and interaction are not modeled." in html
    assert "should not appear" not in html
    assert "fabricated" not in html
    assert "Difference:" not in html
    assert "Commander affordability" not in html
    assert "win_rate" not in html
    assert "win rate" not in html.lower()
    assert "overall deck strength" not in html.lower()
    assert "Aggro cut" not in html
    assert "0.00" not in html
    assert "Sampling range" not in html
    assert "Aesi, Tyrant of Gyre Strait" in html


def test_unavailable_simulation_is_plain_language(app) -> None:
    html = _render(
        app,
        {
            "plan": {"archetype": "value"},
            "simulation": {
                "status": "unavailable",
                "reason": "The simulator did not accept this request.",
                "baseline": {"games": 0, "turns": 0, "commander_cast_count": 0},
            },
        },
    )
    assert "Simulation was not available for this deck." in html
    assert "The simulator did not accept this request." in html
    assert "Commander affordability" not in html
    assert "0.00" not in html
    assert "Games" not in html


def test_malicious_card_and_reason_text_is_escaped(app) -> None:
    payload = '<script>alert("xss")</script>'
    img = "<img src=x onerror=alert(1)>"
    html = _render(
        app,
        {
            "plan": {
                "archetype": payload,
                "status": "partial",
                "requirements": {payload: 2},
                "counts": {payload: 0},
                "missing": {payload: {"actual": 0, "required": 2}},
                "evidence": [
                    {
                        "card": payload,
                        "requirement": payload,
                        "reason": img,
                    }
                ],
                "limitations": [img],
            },
            "findings": [
                {
                    "code": payload,
                    "card": payload,
                    "message": img,
                    "severity": "warning",
                }
            ],
            "decisions": [{"card": payload, "requirement": "payoff", "reason": img}],
            "simulation": {
                "status": "measured",
                "scope": payload,
                "reason": img,
                "baseline": {
                    "games": 10,
                    "turns": 4,
                    "commander_cast_count": 1,
                    "lands_mean": 3,
                    "commander_draws_mean": 1,
                    "assumptions": [img],
                },
                "comparisons": [
                    {
                        "variant": payload,
                        "delta": 0.5,
                        "interval": [0.1, 0.9],
                        "metric": "lands_mean",
                        "improved": False,
                    }
                ],
                "selected": payload,
            },
        },
    )
    assert payload not in html
    assert img not in html
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "alert(&#34;xss&#34;)" in html or "alert(&quot;xss&quot;)" in html
    assert "&lt;img" in html


def test_findings_are_collapsed_with_remainder_count(app) -> None:
    findings = [
        {
            "code": f"code_{i}",
            "card": f"Card {i}",
            "message": f"Note {i}",
            "severity": "warning",
        }
        for i in range(25)
    ]
    html = _render(app, {"findings": findings})
    assert "<details" in html
    assert "Review notes (25)" in html
    assert "Card 0" in html
    assert "Card 19" in html
    assert "Note 19" in html
    assert "Card 20" not in html
    assert "Note 24" not in html
    assert "5 more not shown" in html
    assert "code_0" not in html


def test_partial_has_no_safe_filter_and_deck_view_includes_it() -> None:
    partial = PARTIAL.read_text(encoding="utf-8")
    deck_view = DECK_VIEW.read_text(encoding="utf-8")
    stripped = re.sub(r"\{#.*?#\}", "", partial, flags=re.S)
    assert "|safe" not in stripped
    assert "{% include '_generation_evidence.html' %}" in deck_view
    assert PARTIAL.is_file()

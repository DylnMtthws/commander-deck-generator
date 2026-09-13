"""No-model holdout mana replay against a frozen empirical spell sample."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from sabermetrics.intelligence.cards import usable_land
from sabermetrics.intelligence.evidence import load_selection_evidence
from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.intelligence.land_policy import land_risks
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest
from sabermetrics.pipeline.mana_base import build_mana_base


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    cases = json.loads(
        (root / "docs/experiments/selection-validation/cases.json").read_text()
    )["cases"]
    chosen = Experiment(
        **json.loads(
            (root / "docs/experiments/selection-validation/selected.json").read_text()
        )["settings"]
    )
    rows = []
    for case in cases:
        if case["split"] != "holdout":
            continue
        con = sqlite3.connect(args.database)
        cid = con.execute(
            "select id from cards where name=? and is_legal_commander=1 order by id limit 1",
            (case["name"],),
        ).fetchone()[0]
        con.close()
        req = DeckBuildRequest(
            commander_id=cid, budget_usd=case["budget"], power_target=case["power"]
        )
        builder = DeckBuilder(args.database)
        commander = builder._validate_request(req)
        cards = builder._filter_candidates(req, commander)
        ev = load_selection_evidence(
            commander.model_dump(), case["power"], args.evidence, refresh=False
        )
        if ev.status != "available":
            raise RuntimeError("Missing frozen public evidence for " + case["name"])
        rates = {n.casefold(): r for n, r in ev.inclusion.items()}
        for c in cards:
            c["_selection_inclusion"] = rates.get(c["name"].casefold(), 0.0)
        spells = sorted(
            [c for c in cards if "Land" not in c["type_line"].split("//")[0]],
            key=lambda c: (-c["_selection_inclusion"], c["name"]),
        )[:60]
        sample_hash = hashlib.sha256(
            json.dumps(
                [(c["name"], c["oracle_text"], c["price_usd"]) for c in spells],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        lands = [
            c
            for c in cards
            if "Land" in c["type_line"].split("//")[0]
            and usable_land(c, commander.color_identity)
        ]
        for arm, config in [("baseline", Experiment()), ("candidate", chosen)]:
            with using(config):
                deck = build_mana_base(
                    [(c, {"cvar_score": 0.0}) for c in lands],
                    spells,
                    commander.color_identity,
                    35,
                    max_budget=case["budget"] * 0.25,
                )
            risks = [
                {"card": a.card["name"], "risks": land_risks(a.card)} for a in deck
            ]
            high = [
                x["card"]
                for x in risks
                if any(r["severity"] == "high" for r in x["risks"])
            ]
            row = {
                "case_id": case["case_id"],
                "arm": arm,
                "scope": "mana-stage only; 60-card empirical spell sample, not a generated deck",
                "sample_sha256": sample_hash,
                "evidence_url": ev.source_url,
                "land_count": len(deck),
                "price": sum(float(a.card.get("price_usd") or 0) for a in deck),
                "high_risk_lands": high,
                "lands": [a.card["name"] for a in deck],
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
        (args.output / "rows.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()

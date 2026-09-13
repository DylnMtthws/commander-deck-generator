"""Frozen-stage screening. No model calls and no complete-deck quality claim."""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

from sabermetrics.intelligence.cards import usable_land
from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.intelligence.land_policy import SEVERITY_PENALTY, VERSION
from sabermetrics.intelligence.selection import evidence_score, retain_candidates
from sabermetrics.pipeline.mana_base import build_mana_base

# Independent regression watchlist from the prior manual assessment. These are
# diagnostic adverse examples, not a card-selection blacklist.
WATCH = {"Rainbow Vale", "Forsaken City", "Thran Quarry"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--prior-results", type=Path, required=True)
    p.add_argument("--evidence-weights", default="0.25,0.45,0.65")
    args = p.parse_args()
    evidence_weights = [float(v) for v in args.evidence_weights.split(",")]
    rows = []
    for rank, budget in [(5, 50), (6, 5000), (2, 1500)]:
        data = json.loads((args.directory / f"pool-{rank}.json").read_text())
        cards = data["cards"]
        protected = set(data["protected"]) & {c["name"] for c in cards}
        deck = json.loads((args.prior_results / f"{rank:02d}.json").read_text())["deck"]
        spells = [
            x["card"]
            for x in deck["cards"]
            if "Land" not in x["card"]["type_line"].split("//")[0]
        ]
        lands = [
            c
            for c in cards
            if "Land" in c["type_line"].split("//")[0]
            and usable_land(c, data["commander"]["color_identity"])
        ]
        recall = {}
        mana = {}
        for ew, br in itertools.product(evidence_weights, [0, 12]):
            started = time.monotonic()
            with using(Experiment(evidence_weight=ew, budget_recall=br)):
                scored = [
                    dict(
                        c,
                        _cvar_score=evidence_score(
                            c, float(c["_selection_base_score"])
                        ),
                    )
                    for c in cards
                ]
                kept = retain_candidates(scored, protected)
            afford = [
                c
                for c in kept
                if float(c.get("price_usd") or 0) <= 1
                and "Land" not in c["type_line"].split("//")[0]
            ]
            recall[ew, br] = {
                "retained": len(kept),
                "affordable_nonlands": len(afford),
                "affordable_verified_roles": sorted(
                    {r for c in afford for r in c.get("_facts", {}).get("roles", [])}
                ),
                "protected_missing": sorted(protected - {c["name"] for c in kept}),
                "seconds": time.monotonic() - started,
            }
        for le, lr in itertools.product([0, 10, 20], [0, 1, 2]):
            started = time.monotonic()
            with using(Experiment(land_evidence_weight=le, land_risk_weight=lr)):
                built = build_mana_base(
                    [(c, {"cvar_score": 0}) for c in lands],
                    spells,
                    data["commander"]["color_identity"],
                    sum(
                        "Land" in x["card"]["type_line"].split("//")[0]
                        for x in deck["cards"]
                    ),
                    max_budget=budget * 0.30,
                )
            names = [a.card["name"] for a in built]
            mana[le, lr] = {
                "lands": names,
                "watchlist_selected": sorted(set(names) & WATCH),
                "land_price": sum(float(a.card.get("price_usd") or 0) for a in built),
                "seconds": time.monotonic() - started,
            }
        for ew, le, lr, br in itertools.product(
            evidence_weights, [0, 10, 20], [0, 1, 2], [0, 12]
        ):
            rows.append(
                {
                    "rank": rank,
                    "settings": Experiment(ew, le, lr, br).to_dict(),
                    "recall": recall[ew, br],
                    "mana": mana[le, lr],
                }
            )
        print(
            json.dumps(
                {
                    "rank": rank,
                    "configurations": len(evidence_weights) * 18,
                    "distinct_recall_runs": len(evidence_weights) * 2,
                    "distinct_mana_runs": 9,
                    "baseline_watch": mana[0, 0]["watchlist_selected"],
                    "strong_watch": mana[20, 2]["watchlist_selected"],
                    "baseline_recall": recall[0.45, 0]["retained"],
                    "expanded_recall": recall[0.45, 12]["retained"],
                }
            ),
            flush=True,
        )
        (args.directory / "screen.json").write_text(
            json.dumps(
                {
                    "scope": "separable frozen-stage screen; not complete builds",
                    "land_policy_version": VERSION,
                    "severity_penalty": SEVERITY_PENALTY,
                    "rows": rows,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

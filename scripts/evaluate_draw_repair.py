"""Controlled post-selection draw intervention on frozen complete decks.

No model calls. Each baseline and intervention share the exact same starting list.
"""

import argparse
import json
import os
import sqlite3
from pathlib import Path

from sabermetrics.intelligence.cards import annotate
from sabermetrics.intelligence.draw_selection import repair
from sabermetrics.intelligence.evidence import load_selection_evidence
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for file in sorted(args.input.glob("*.json")):
        data = json.loads(file.read_text())
        if not isinstance(data, dict) or "deck" not in data:
            continue
        deck = data["deck"]
        cmd = deck["commander"]
        params = deck["parameters"]
        builder = DeckBuilder(args.database)
        con = sqlite3.connect(args.database)
        cid = con.execute(
            "select id from cards where name=? and is_legal_commander=1 limit 1",
            (cmd["name"],),
        ).fetchone()[0]
        con.close()
        req = DeckBuildRequest(
            commander_id=cid,
            budget_usd=params["budget_usd"],
            power_target=params["power_target"],
        )
        commander = builder._validate_request(req)
        candidates = [
            annotate(c)
            for c in builder._load_role_tags(builder._filter_candidates(req, commander))
        ]
        evidence = load_selection_evidence(
            commander.model_dump(),
            req.power_target,
            Path(os.environ["SABER_SELECTION_EVIDENCE"]),
            refresh=False,
        )
        rates = {n.casefold(): r for n, r in evidence.inclusion.items()}
        catalog = {c["name"]: c for c in candidates}
        for c in candidates:
            c["_selection_inclusion"] = rates.get(c["name"].casefold(), 0)
        cards = []
        for entry in deck["cards"]:
            c = dict(catalog.get(entry["card"]["name"], annotate(entry["card"])))
            c["price_usd"] = entry["card"]["current_price_usd"]
            cards.append(c)
        # All non-draw roles are protected by repair. Protect independently
        # recognized strategy ingredients as well, not legacy slot labels.
        from sabermetrics.intelligence.strategy import make_plan, matches_requirement

        plan = make_plan(commander.model_dump(), None, req.power_target)
        protected = {
            c["name"]
            for c in cards
            if any(matches_requirement(c, r) for r in plan.requirements)
        }
        fixed, receipt = repair(
            cards,
            candidates,
            commander.model_dump(),
            req.budget_usd,
            req.power_target,
            protected=protected,
        )
        row = {
            "case": file.stem,
            "commander": cmd["name"],
            "budget": req.budget_usd,
            "power": req.power_target,
            "before": receipt["before"]["credible"],
            "after": receipt["after"]["credible"],
            "independent_before": receipt["before"]["independent"],
            "independent_after": receipt["after"]["independent"],
            "status": receipt["status"],
            "swaps": receipt["decisions"],
            "price": sum(c["price_usd"] for c in fixed),
            "count": len(fixed),
        }
        (args.output / (file.stem + ".json")).write_text(
            json.dumps({"row": row, "receipt": receipt, "cards": fixed}, indent=2)
        )
        rows.append(row)
        (args.output / "rows.json").write_text(json.dumps(rows, indent=2))
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()

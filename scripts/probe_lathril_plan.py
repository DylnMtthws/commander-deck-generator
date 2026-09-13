"""Development follow-up after seeing Lathril's held-out failure.

An explicit Elf requirement is an experimental intervention, not an automatically
validated general compiler. Model review is disabled in both arms.
"""

import argparse
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from screen_budget import Replay, forbidden

from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.intelligence.strategy import make_plan
from sabermetrics.pipeline.deck_builder import DeckBuildRequest
from sabermetrics.reasoning.client import ModelClient


def explicit_plan(commander, intent, power=3):
    original = make_plan(commander, intent, power)
    return original.model_copy(
        update={
            "archetype": "typal",
            "requirements": {"creature_type:elf": 16},
            "limitations": [
                "Explicit experimental Elf requirement; not a generic inferred plan or proof of ten untapped Elves."
            ],
        }
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ModelClient.call_with_cache = forbidden
    con = sqlite3.connect(args.database)
    cid = con.execute(
        "select id from cards where name='Lathril, Blade of the Elves' and is_legal_commander=1 order by id limit 1"
    ).fetchone()[0]
    con.close()
    rows = []
    for arm, plan in [
        ("general", make_plan),
        ("explicit_elf_requirement", explicit_plan),
    ]:
        with (
            using(
                Experiment(
                    land_evidence_weight=10, land_risk_weight=1, budget_recall=12
                )
            ),
            patch("sabermetrics.intelligence.strategy.make_plan", plan),
        ):
            result = Replay(args.database).build(
                DeckBuildRequest(
                    commander_id=cid,
                    budget_usd=100,
                    power_target=3,
                    deck_name="offline-lathril-" + arm,
                )
            )
        cards = [x.card.model_dump(mode="json") for x in result.deck.cards]
        row = {
            "arm": arm,
            "scope": "offline full selection, no model review; Lathril is now development-exposed",
            "price": result.deck.composition.total_price_usd,
            "card_count": len(cards),
            "elf_count": sum("Elf" in c["type_line"] for c in cards),
            "non_elf_creatures": [
                c["name"]
                for c in cards
                if "Creature" in c["type_line"] and "Elf" not in c["type_line"]
            ],
            "names": [c["name"] for c in cards],
        }
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "names"}), flush=True)
    (args.output / "rows.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()

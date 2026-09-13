"""Development-only complete selection replay with model calls forbidden."""

import argparse
import itertools
import json
import sqlite3
import time
from pathlib import Path

from sabermetrics.config import settings
from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest
from sabermetrics.reasoning.client import ModelClient

WATCH = {
    "Rock Jockey",
    "Goblin Rock Sled",
    "Hedron Scrabbler",
    "Belligerent Whiptail",
    "Dragon's Herald",
    "Troop of Ponies",
    "Hithlain Rope",
    "Bearer of the Heavens",
    "Magnetic Snuffler",
    "Unchained Berserker",
}


def forbidden(*args, **kwargs):
    raise AssertionError("Model calls forbidden in offline selection replay")


class Replay(DeckBuilder):
    land_share = 0.2

    def _derive_template(self, profile, request):
        return (
            super()
            ._derive_template(profile, request)
            .model_copy(update={"land_budget_share": self.land_share})
        )

    def _llm_safety_check(self, deck, *args, **kwargs):
        self._review_failed = True
        return deck, 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    ModelClient.call_with_cache = forbidden
    con = sqlite3.connect(args.database)
    cid = con.execute(
        "select id from cards where name='Krenko, Mob Boss' and is_legal_commander=1 order by id limit 1"
    ).fetchone()[0]
    con.close()
    previous = settings.pipeline.budget_reserve_per_slot
    rows = []
    try:
        for share, reserve in itertools.product([0.08, 0.20], [0.10, 0.25, 0.50, 1.0]):
            settings.pipeline.budget_reserve_per_slot = reserve
            builder = Replay(args.database)
            builder.land_share = share
            t = time.monotonic()
            with using(
                Experiment(
                    evidence_weight=0.45,
                    land_evidence_weight=10,
                    land_risk_weight=1,
                    budget_recall=12,
                )
            ):
                result = builder.build(
                    DeckBuildRequest(
                        commander_id=cid,
                        budget_usd=50,
                        power_target=1,
                        deck_name=f"offline-budget-{share}-{reserve}",
                    )
                )
            cards = [x.card.model_dump(mode="json") for x in result.deck.cards]
            names = {c["name"] for c in cards}
            row = {
                "land_share": share,
                "reserve_dollars": reserve,
                "elapsed": time.monotonic() - t,
                "price": result.deck.composition.total_price_usd,
                "cards": len(cards),
                "weak_watchlist": sorted(names & WATCH),
                "goblin_count": sum("Goblin" in c["type_line"] for c in cards),
                "llm_review": "disabled, no calls permitted",
                "names": [c["name"] for c in cards],
            }
            rows.append(row)
            (args.output / "rows.json").write_text(json.dumps(rows, indent=2))
            print(
                json.dumps({k: v for k, v in row.items() if k != "names"}), flush=True
            )
    finally:
        settings.pipeline.budget_reserve_per_slot = previous


if __name__ == "__main__":
    main()

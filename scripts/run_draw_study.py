"""Paired real builds with final mechanics audit; no embedded credentials."""

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
from pathlib import Path

from run_selection_study import assess

from sabermetrics.intelligence.draw_selection import audit
from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--cases", type=Path, default=Path("docs/experiments/draw-selection/cases.json")
    )
    p.add_argument("--only", default="")
    p.add_argument("--repeat", type=int, default=0)
    p.add_argument("--offline", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    builder_class = DeckBuilder
    if args.offline:
        from screen_budget import Replay, forbidden

        from sabermetrics.reasoning.client import ModelClient

        ModelClient.call_with_cache = forbidden
        builder_class = Replay
    cases = json.loads(args.cases.read_text())["cases"]
    if args.only:
        cases = [c for c in cases if c["case_id"] in args.only.split(",")]
    h = hashlib.sha256()
    for f in sorted(Path("src").rglob("*.py")):
        h.update(str(f).encode())
        h.update(f.read_bytes())
    rows = []
    for index, case in enumerate(cases):
        con = sqlite3.connect(args.database)
        cid = con.execute(
            "select id from cards where name=? and is_legal_commander=1 limit 1",
            (case["name"],),
        ).fetchone()[0]
        con.close()
        arms = [("baseline", False), ("candidate", True)]
        if (index + args.repeat) % 2:
            arms.reverse()
        for arm, enabled in arms:
            key = f"{case['case_id']}-{arm}-{args.repeat}"
            start = time.monotonic()

            def progress(stage, value, key=key):
                print(json.dumps({"run": key, "stage": stage}), flush=True)

            row = {
                **case,
                "arm": arm,
                "repeat": args.repeat,
                "source_sha256": h.hexdigest(),
                "offline": args.offline,
            }
            try:
                builder = builder_class(args.database, progress_callback=progress)
                with using(
                    Experiment(
                        land_evidence_weight=10,
                        land_risk_weight=1,
                        budget_recall=12,
                        draw_selection=enabled,
                    )
                ):
                    result = builder.build(
                        DeckBuildRequest(
                            commander_id=cid,
                            budget_usd=case["budget"],
                            power_target=case["power"],
                            deck_name=key,
                        )
                    )
                data = result.model_dump(mode="json")
                cards = [x["card"] for x in data["deck"]["cards"]]
                draw = audit(cards, data["deck"]["commander"], case["power"])
                row.update(
                    status="completed",
                    elapsed=time.monotonic() - start,
                    profile_generated=result.profile_was_generated,
                    llm_cost=result.total_cost_usd,
                    **assess(result),
                )
                row["draw_credible"] = draw["credible"]
                row["draw_independent"] = draw["independent"]
                row["draw_cards"] = [r["card"] for r in draw["cards"] if r["credible"]]
                row["draw_package_status"] = builder._intelligence.get(
                    "draw_selection", {}
                ).get("status", "baseline")
                (args.output / (key + ".json")).write_text(json.dumps(data, indent=2))
                (args.output / (key + "-intelligence.json")).write_text(
                    json.dumps(builder._intelligence, indent=2)
                )
                (args.output / (key + "-draw-audit.json")).write_text(
                    json.dumps(draw, indent=2)
                )
            except Exception as exc:  # noqa: BLE001
                row.update(
                    status="failed",
                    elapsed=time.monotonic() - start,
                    error_type=type(exc).__name__,
                )
                (args.output / (key + "-error.txt")).write_text(traceback.format_exc())
            rows.append(row)
            (args.output / "rows.json").write_text(json.dumps(rows, indent=2))
            print(json.dumps(row), flush=True)
    return int(any(r["status"] != "completed" for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())

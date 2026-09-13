"""Run explicit paid benchmark cases in a disposable public-corpus database.

HF_TOKEN comes from the operator's environment, never arguments or output.
This command does not create users, deploy, or connect to production storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
from pathlib import Path

from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("docs/specs/selection-intelligence/evaluation.json"),
    )
    parser.add_argument("--ranks", default="")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.cases.read_text())
    selected = {int(x) for x in args.ranks.split(",") if x}
    source = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted((source / "src").rglob("*.py")):
        digest.update(str(path.relative_to(source)).encode())
        digest.update(path.read_bytes())
    rows = []
    for case in cases["cases"]:
        if selected and case["rank"] not in selected:
            continue
        conn = sqlite3.connect(args.database)
        row = conn.execute(
            "select id from cards where name=? and is_legal_commander=1 order by id limit 1",
            (case["name"],),
        ).fetchone()
        conn.close()
        if row is None:
            rows.append(
                {
                    **case,
                    "status": "failed",
                    "error": "Commander missing from public catalog",
                }
            )
            continue
        started = time.time()

        def progress(stage, value, case=case, started=started):
            print(
                json.dumps(
                    {
                        "rank": case["rank"],
                        "name": case["name"],
                        "stage": stage,
                        "progress": value,
                        "elapsed": round(time.time() - started, 1),
                    }
                ),
                flush=True,
            )

        try:
            result = DeckBuilder(args.database, progress_callback=progress).build(
                DeckBuildRequest(
                    commander_id=row[0],
                    budget_usd=case["budget"],
                    power_target=case["power"],
                    user_intent=case.get("intent"),
                    deck_name=f"Selection evaluation {case['rank']}: {case['name']}",
                )
            )
            path = args.output / f"{case['rank']:02d}.json"
            path.write_text(json.dumps(result.model_dump(mode="json"), indent=2))
            summary = {
                **case,
                "status": "completed",
                "deck_id": result.deck.id,
                "elapsed": round(time.time() - started, 2),
                "estimated_cost": result.total_cost_usd,
                "result_path": str(path),
                "source_sha256": digest.hexdigest(),
            }
        except Exception as exc:  # noqa: BLE001
            (args.output / f"{case['rank']:02d}-error.txt").write_text(
                traceback.format_exc()
            )
            summary = {
                **case,
                "status": "failed",
                "error_type": type(exc).__name__,
                "elapsed": round(time.time() - started, 2),
                "source_sha256": digest.hexdigest(),
            }
        rows.append(summary)
        (args.output / "summary.json").write_text(
            json.dumps({"cohort": cases, "runs": rows}, indent=2)
        )
        print(json.dumps(summary), flush=True)
    return 0 if rows and all(r["status"] == "completed" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

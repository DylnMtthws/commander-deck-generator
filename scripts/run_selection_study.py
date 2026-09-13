"""Paired real generation experiments; credentials only from environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
from collections import Counter
from pathlib import Path

from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest


def assess(result):
    from sabermetrics.intelligence.constraints import audit_deck
    from sabermetrics.intelligence.land_policy import land_risks
    from sabermetrics.intelligence.review import contradictions

    deck = result.deck.model_dump(mode="json")
    cards = [c["card"] for c in deck["cards"]]
    names = Counter(c["name"] for c in cards)
    issues = []
    if len(cards) != 99:
        issues.append("count")
    for card in cards:
        if card["current_price_usd"] is None:
            issues.append("unpriced:" + card["name"])
        if card["name"] == deck["commander"]["name"]:
            issues.append("commander_in_library")
        if not card["is_legal_in_99"]:
            issues.append("legality:" + card["name"])
        if not set(card["color_identity"]) <= set(deck["commander"]["color_identity"]):
            issues.append("color:" + card["name"])
        if (
            names[card["name"]] > 1
            and "Basic" not in card["type_line"]
            and "any number of cards named" not in (card["oracle_text"] or "")
        ):
            issues.append("singleton:" + card["name"])
    price = sum(float(c["current_price_usd"] or 0) for c in cards)
    if price > deck["parameters"]["budget_usd"] + 0.001:
        issues.append("budget")
    dependencies = audit_deck(cards, deck["commander"])
    claims = [
        {
            "card": x["card"]["name"],
            "status": x["llm_fit"]["status"],
            "errors": contradictions(
                x["card"], x["llm_fit"]["reasoning"], deck["commander"]
            ),
        }
        for x in deck["cards"]
        if x["llm_fit"]["status"] != "unreviewed"
    ]
    claims = [c for c in claims if c["errors"]]
    risks = [
        {"card": c["name"], "risks": land_risks(c)}
        for c in cards
        if "Land" in c["type_line"].split("//")[0]
    ]
    risks = [r for r in risks if r["risks"]]
    return {
        "hard_failures": len(set(issues))
        + sum(f["severity"] in ("error", "failure") for f in dependencies)
        + sum(c["status"] == "reviewed" for c in claims),
        "mechanical_failures": sorted(set(issues)),
        "flagged_cards": len(
            {r["card"] for r in risks}
            | {d["card"] for d in dependencies}
            | {c["card"] for c in claims}
        ),
        "price": round(price, 2),
        "dependency_findings": dependencies,
        "claim_findings": claims,
        "land_risks": risks,
        "review_status": dict(Counter(x["llm_fit"]["status"] for x in deck["cards"])),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--selected", type=Path, required=True)
    p.add_argument(
        "--cases",
        type=Path,
        default=Path("docs/experiments/selection-validation/cases.json"),
    )
    p.add_argument("--only", default="")
    p.add_argument("--repeat", type=int, default=0)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    chosen = Experiment(**json.loads(args.selected.read_text())["settings"])
    rows = []
    cases = json.loads(args.cases.read_text())["cases"]
    if args.only:
        cases = [c for c in cases if c["case_id"] in args.only.split(",")]
    source = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for path in sorted((source / "src").rglob("*.py")):
        h.update(str(path.relative_to(source)).encode())
        h.update(path.read_bytes())
    for index, case in enumerate(cases):
        conn = sqlite3.connect(args.database)
        cid = conn.execute(
            "select id from cards where name=? and is_legal_commander=1 order by id limit 1",
            (case["name"],),
        ).fetchone()[0]
        conn.close()
        arms = [("baseline", Experiment()), ("candidate", chosen)]
        if (index + args.repeat) % 2:
            arms.reverse()
        for arm, config in arms:
            started = time.monotonic()
            key = f"{case['case_id']}-{arm}-{args.repeat}"

            def progress(stage, value, key=key, started=started):
                print(
                    json.dumps(
                        {
                            "run": key,
                            "stage": stage,
                            "elapsed": round(time.monotonic() - started, 1),
                        }
                    ),
                    flush=True,
                )

            row = {
                **case,
                "arm": arm,
                "repeat": args.repeat,
                "source_sha256": h.hexdigest(),
                "settings": config.to_dict(),
            }
            try:
                with using(config):
                    result = DeckBuilder(
                        args.database, progress_callback=progress
                    ).build(
                        DeckBuildRequest(
                            commander_id=cid,
                            budget_usd=case["budget"],
                            power_target=case["power"],
                            deck_name=key,
                        )
                    )
                (args.output / f"{key}.json").write_text(
                    json.dumps(result.model_dump(mode="json"), indent=2)
                )
                row.update(
                    status="completed",
                    elapsed=time.monotonic() - started,
                    profile_generated=result.profile_was_generated,
                    llm_cost=result.total_cost_usd,
                    **assess(result),
                )
            except Exception as exc:  # noqa: BLE001
                (args.output / f"{key}-error.txt").write_text(traceback.format_exc())
                row.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    elapsed=time.monotonic() - started,
                )
            rows.append(row)
            (args.output / "rows.json").write_text(json.dumps(rows, indent=2))
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in row.items()
                        if k
                        in [
                            "case_id",
                            "arm",
                            "status",
                            "elapsed",
                            "hard_failures",
                            "flagged_cards",
                            "price",
                            "error_type",
                        ]
                    }
                ),
                flush=True,
            )
    return int(any(r["status"] != "completed" for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())

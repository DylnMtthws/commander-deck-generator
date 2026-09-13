"""Paired function-preservation study with independent final-transition checks."""

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
from collections import Counter
from dataclasses import replace
from pathlib import Path

from run_selection_study import assess

from sabermetrics.intelligence.draw_selection import audit
from sabermetrics.intelligence.experiment import Experiment, production_policy, using
from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest


def offline_builder_class():
    """Disable model review without inheriting budget-screen template tuning."""
    from screen_budget import Replay

    class ProductionReplay(Replay):
        _derive_template = DeckBuilder._derive_template

    return ProductionReplay


def output_cards(data):
    """Normalize persisted DeckCard prices without inventing zero-price cards."""
    cards = []
    for wrapper in data["deck"]["cards"]:
        card = dict(wrapper["card"])
        value = wrapper.get("price_usd", wrapper.get("current_price_usd"))
        if value is None:
            value = card.get("current_price_usd", card.get("price_usd"))
        card["price_usd"] = value
        cards.append(card)
    return cards


def damage_role_failures(data):
    """Audit all persisted damage spells, including unchanged baseline cards."""
    from sabermetrics.pipeline.slot_assigner import complete_damage_role

    return [
        {
            "card": wrapper["card"]["name"],
            "actual": wrapper["slot_role"],
            "expected": "removal",
        }
        for wrapper in data["deck"]["cards"]
        if complete_damage_role(wrapper["card"]) == "removal"
        and wrapper["slot_role"] != "removal"
    ]


def _printed_list(card, key):
    value = card.get(key)
    if isinstance(value, str):
        value = json.loads(value) if value else None
    # Card.keywords defaults to []; synthesized basics may omit that field.
    # Printed colors use None for unknown and must not receive this treatment.
    if key == "keywords" and value is None:
        return ()
    return tuple(sorted(value)) if value is not None else None


def _snapshot_multiset(cards):
    """Ignore order/printing IDs, retaining functional data, price and actual role."""
    from sabermetrics.intelligence.draw_selection import price
    from sabermetrics.intelligence.function_guard import stable_id

    return Counter(
        (
            stable_id(card),
            price(card),
            card.get("_slot_role"),
            _printed_list(card, "colors"),
            _printed_list(card, "keywords"),
        )
        for card in cards
    )


def audit_upstream(data, upstream, policy, budget, protected):
    """Bind receipts to this request and independently audit saved stage boundaries."""
    from sabermetrics.intelligence.function_guard import stable_id, validate_transition
    from sabermetrics.intelligence.upstream_guard import audit_transactions

    errors = []
    result = {"errors": errors, "cumulative": None}
    commander = data["deck"]["commander"]
    try:
        records = upstream.get("transactions", [])
        snapshots = upstream.get("snapshots", {})
        if upstream.get("policy") != policy:
            errors.append("upstream_policy_mismatch")
        required = ("greedy", "after_strategy_variant", "after_rebalance", "final")
        for key in required:
            if key not in snapshots:
                errors.append("missing_snapshot:" + key)
        if len(records) != 2:
            errors.append("missing_optimizer_transactions")
        for index, (stage, record) in enumerate(zip(("swap", "rebalance"), records)):
            if record.get("stage") != stage:
                errors.append(f"{index}:stage_mismatch")
            mode = record.get("mode")
            if mode != policy[stage + "_policy"]:
                errors.append(f"{index}:mode_mismatch")
            if record.get("status") not in {"accepted", "rejected", "error"}:
                errors.append(f"{index}:invalid_transaction_status")
            if record.get("budget") != budget:
                errors.append(f"{index}:budget_mismatch")
            recorded_commander = record.get("commander") or {}
            if (
                stable_id(recorded_commander) != stable_id(commander)
                or _printed_list(recorded_commander, "colors")
                != _printed_list(commander, "colors")
                or _printed_list(recorded_commander, "keywords")
                != _printed_list(commander, "keywords")
            ):
                errors.append(f"{index}:commander_mismatch")
            if set(record.get("protected", [])) != set(protected):
                errors.append(f"{index}:protected_mismatch")
        result["transactions"] = audit_transactions(records)
        errors.extend(result["transactions"]["errors"])
        for position, key, error in (
            (0, "after_strategy_variant", "first_transaction_input_mismatch"),
            (-1, "after_rebalance", "last_transaction_output_mismatch"),
        ):
            boundary = "before" if position == 0 else "after"
            if (
                records
                and key in snapshots
                and _snapshot_multiset(records[position][boundary])
                != _snapshot_multiset(snapshots[key])
            ):
                errors.append(error)
        persisted = output_cards(data)
        for card, wrapper in zip(persisted, data["deck"]["cards"], strict=True):
            card["_slot_role"] = wrapper["slot_role"]
        if "final" in snapshots and _snapshot_multiset(
            snapshots["final"]
        ) != _snapshot_multiset(persisted):
            errors.append("final_snapshot_persistence_mismatch")
        if "greedy" in snapshots:
            result["cumulative"] = validate_transition(
                snapshots["greedy"], persisted, commander, budget, protected
            )
        # An unproved cumulative transition is a strategic finding, not an
        # automatic failure of a deliberately unguarded comparator policy.
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append("malformed_upstream_receipt:" + type(exc).__name__)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--cases", type=Path, default=Path("docs/experiments/draw-selection/cases.json")
    )
    p.add_argument("--only", default="")
    p.add_argument("--repeat", type=int, default=0)
    p.add_argument("--arms", default="baseline,candidate")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--trace-card", action="append", default=[])
    p.add_argument(
        "--policy-json",
        type=Path,
        help="Explicit registered scoring settings; arm controls guarded selection",
    )
    args = p.parse_args()
    base_policy = production_policy()
    if args.policy_json:
        base_policy = Experiment(**json.loads(args.policy_json.read_text()))
        if not base_policy.preserve_functions:
            p.error("Study runner does not admit unguarded replacement policies")
    args.output.mkdir(parents=True, exist_ok=True)
    builder_class = DeckBuilder
    if args.offline:
        from screen_budget import forbidden

        from sabermetrics.reasoning.client import ModelClient

        ModelClient.call_with_cache = forbidden
        builder_class = offline_builder_class()
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
        arms = [
            (arm, arm == "candidate") for arm in case.get("arms", args.arms).split(",")
        ]
        if any(arm not in {"baseline", "candidate"} for arm, _ in arms):
            p.error("--arms must contain baseline and/or candidate")
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
                "policy": replace(base_policy, draw_selection=enabled).to_dict(),
            }
            builder = None
            try:
                builder = builder_class(args.database, progress_callback=progress, trace_names=tuple(args.trace_card))
                with using(replace(base_policy, draw_selection=enabled)):
                    result = builder.build(
                        DeckBuildRequest(
                            commander_id=cid,
                            budget_usd=case["budget"],
                            power_target=case["power"],
                            deck_name=key,
                        )
                    )
                data = result.model_dump(mode="json")
                cards = output_cards(data)
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
                receipt = builder._intelligence.get("draw_selection", {})
                row["guard_mode"] = receipt.get("mode", "baseline")
                row["reported_guard"] = receipt.get("guard")
                row["decisions"] = receipt.get("decisions", [])
                row["validation_errors"] = []
                upstream = builder._intelligence.get("upstream", {})
                protected = set(builder._protected_names or ()) | set(
                    getattr(builder, "_engine_protect_names", ()) or ()
                )
                row["upstream_audit"] = audit_upstream(
                    data, upstream, row["policy"], case["budget"], protected
                )
                row["upstream_cumulative"] = row["upstream_audit"]["cumulative"]
                row["validation_errors"].extend(row["upstream_audit"]["errors"])
                row["damage_role_failures"] = damage_role_failures(data)
                if row["damage_role_failures"]:
                    row["validation_errors"].append("complete_damage_role_mismatch")
                if enabled:
                    from sabermetrics.intelligence.function_guard import (
                        validate_transition,
                    )

                    baseline = receipt.get("baseline_cards")
                    if baseline is None:
                        row["validation_errors"].append("missing_internal_baseline")
                    else:
                        protected = set(builder._protected_names or ()) | set(
                            getattr(builder, "_engine_protect_names", ()) or ()
                        )
                        check = validate_transition(
                            baseline,
                            cards,
                            data["deck"]["commander"],
                            case["budget"],
                            protected,
                        )
                        row["final_transition"] = check
                        row["applied_swaps"] = (
                            len(check["proofs"]) if check["improved"] else 0
                        )
                        row["final_card_roles"] = {
                            x["card"]["name"]: x["slot_role"]
                            for x in data["deck"]["cards"]
                        }
                        row["swap_slot_roles"] = [
                            {
                                "incoming": proof["incoming"],
                                "role": row["final_card_roles"].get(proof["incoming"]),
                            }
                            for proof in check["proofs"]
                        ]
                        for proof in check["proofs"]:
                            if (
                                proof.get("family") == "damage"
                                and row["final_card_roles"].get(proof["incoming"])
                                != "removal"
                            ):
                                row["validation_errors"].append(
                                    "damage_replacement_role_mismatch"
                                )
                        if not check["allowed"]:
                            row["validation_errors"].append("unsafe_final_transition")
                        if receipt.get("mode") == "audit_only" and check["changed"]:
                            row["validation_errors"].append("audit_only_mutated_cards")
                        (
                            args.output / (key + "-transition-validation.json")
                        ).write_text(
                            json.dumps(
                                {"protected_names": sorted(protected), **check},
                                indent=2,
                            )
                        )
                else:
                    row["applied_swaps"] = 0

            except Exception as exc:  # noqa: BLE001
                row.update(
                    status="failed",
                    elapsed=time.monotonic() - start,
                    error_type=type(exc).__name__,
                )
                (args.output / (key + "-error.txt")).write_text(traceback.format_exc())
                if builder is not None:
                    (args.output / (key + "-intelligence.json")).write_text(
                        json.dumps(getattr(builder, "_intelligence", {}), indent=2)
                    )
            rows.append(row)
            (args.output / "rows.json").write_text(json.dumps(rows, indent=2))
            print(json.dumps(row), flush=True)
    return int(
        any(
            r["status"] != "completed"
            or r.get("validation_errors")
            or r.get("hard_failures", 0)
            for r in rows
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

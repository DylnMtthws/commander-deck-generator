"""C++ ingredient-access sampling; deliberately not a gameplay/win simulator."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from sabermetrics.intelligence.strategy import StrategyPlan, matches_requirement


def engine_access(
    cards: list[dict],
    plan: StrategyPlan,
    *,
    binary: str | None = None,
    games: int = 20000,
    seed: int = 1701,
) -> dict:
    binary = binary or os.getenv("SABER_RESOURCE_PROBE_BIN")
    if not plan.requirements:
        return {"status": "not_applicable", "reason": "No supported ingredient plan."}
    if not binary:
        return {
            "status": "unavailable",
            "reason": "Native ingredient-access sampler not configured.",
        }
    if len(cards) != 99:
        return {"status": "unavailable", "reason": "Exactly 99 library slots required."}
    # Per-deck abundance requirements are not opening-hand requirements.
    # Measure seeing one of each ingredient class (explicitly label this).
    names = list(plan.requirements)[:8]
    groups = [{"name": r, "minimum": 1} for r in names]
    masks = [
        sum(1 << i for i, name in enumerate(names) if matches_requirement(c, name))
        for c in cards
    ]
    fingerprint = json.dumps(
        [
            (
                c.get("oracle_id") or c.get("id") or c.get("name"),
                c.get("oracle_text"),
                c.get("type_line"),
            )
            for c in cards
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    identity = "sha256:" + hashlib.sha256(fingerprint.encode()).hexdigest()
    request = {
        "schema_version": "engine-access-request.v1",
        "masks": masks,
        "groups": groups,
        "seen": [7, 10, 14],
        "games": games,
        "seed": seed,
        "deck_identity": identity,
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    try:
        with tempfile.TemporaryDirectory(prefix="engine-access-") as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(request))
            completed = subprocess.run(
                [binary, "--engine-access-request", str(path)],
                capture_output=True,
                timeout=5,
                check=True,
                env={"PATH": os.environ.get("PATH", "")},
            )
        if len(completed.stdout) > 1_000_000:
            raise ValueError("oversize response")
        result = json.loads(completed.stdout)
        if (
            result.get("schema_version") != "engine-access-result.v1"
            or result.get("deck_identity") != identity
            or result.get("input_sha256") != digest
            or result.get("games") != games
            or result.get("groups") != groups
            or result.get("seen") != [7, 10, 14]
        ):
            raise ValueError("unbound response")
        joint = result.get("joint_hits")
        hits = result.get("group_hits")
        if (
            not isinstance(joint, list)
            or len(joint) != 3
            or not isinstance(hits, list)
            or len(hits) != 3
        ):
            raise ValueError("invalid samples")
        for row in hits:
            if not isinstance(row, list) or len(row) != len(groups):
                raise ValueError("invalid group samples")
        if any(
            type(n) is not int or n < 0 or n > games
            for n in joint + [n for row in hits for n in row]
        ):
            raise ValueError("invalid counts")
        return {
            "status": "measured",
            "scenario": result["scenario"],
            "games": games,
            "seen": result["seen"],
            "groups": groups,
            "joint_access_fraction": [n / games for n in joint],
            "group_access_fraction": [[n / games for n in row] for row in hits],
            "input_sha256": digest,
            "limitations": [
                "Seeing at least one of each listed ingredient class, not casting or completing the engine.",
                "No mulligans, tutors, extra draws, mana, opponents or win probability. Conditional cards may be unplayable in the sampled hand.",
            ],
        }
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        return {
            "status": "unavailable",
            "reason": "Native ingredient-access result unavailable or failed verification: "
            + type(exc).__name__,
        }

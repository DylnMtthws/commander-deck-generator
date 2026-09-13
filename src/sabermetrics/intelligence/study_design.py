"""Registered, bounded experiments over implemented selection controls only."""

import hashlib
import itertools
import json
from dataclasses import replace

from sabermetrics.intelligence.experiment import production_policy

FACTORS = {
    "budget_recall": (0, 12),
    "land_evidence_weight": (0.0, 10.0),
    "land_risk_weight": (0.0, 1.0),
    "draw_selection": (False, True),
}


def configurations():
    """Full small grid; always preserve functions, never unguarded repair."""
    rows = []
    for values in itertools.product(*FACTORS.values()):
        policy = replace(production_policy(), **dict(zip(FACTORS, values, strict=True)))
        settings = policy.to_dict()
        key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        rows.append(
            {"id": key, "policy": settings, "production": policy == production_policy()}
        )
    return rows


def register(cases, *, repeats, max_builds, source_sha256, data_sha256):
    """Construct a plan, never launch models or silently truncate costly work."""
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if type(max_builds) is not int or max_builds < 1:
        raise ValueError("max_builds must be a positive integer")
    if not cases or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("cases must be nonempty and uniquely identified")
    for digest in (source_sha256, data_sha256):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("source/data SHA256 required")
    arms = configurations()
    count = len(cases) * len(arms) * repeats
    if count > max_builds:
        raise ValueError(f"planned {count} builds exceeds explicit cap {max_builds}")
    return {
        "schema": "selection-study.v1",
        "status": "registered_not_executed",
        "source_sha256": source_sha256,
        "data_sha256": data_sha256,
        "cases": cases,
        "configurations": arms,
        "repeats": repeats,
        "planned_builds": count,
        "max_builds": max_builds,
        "limits": [
            "No proof that all possible fixes are covered.",
            "Code/data changes require separate revision comparisons.",
            "Registration does not authorize or execute model calls.",
        ],
    }

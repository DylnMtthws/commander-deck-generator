"""Reject native results that are not bound to this exact request."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from sabermetrics.intelligence.access import engine_access
from sabermetrics.intelligence.strategy import StrategyPlan


@pytest.mark.parametrize("mutation", ["identity", "hash", "groups", "counts", "none"])
def test_native_binding(monkeypatch, mutation):
    def run(args, **kwargs):
        with open(args[2]) as stream:
            request = json.load(stream)
        result = {
            "schema_version": "engine-access-result.v1",
            "scenario": "random-library-ingredient-access.v1",
            "deck_identity": request["deck_identity"],
            "input_sha256": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest(),
            "games": request["games"],
            "groups": request["groups"],
            "seen": request["seen"],
            "joint_hits": [0, 1, 2],
            "group_hits": [[0], [1], [2]],
        }
        if mutation == "identity":
            result["deck_identity"] = "sha256:" + "0" * 64
        if mutation == "hash":
            result["input_sha256"] = "sha256:" + "0" * 64
        if mutation == "groups":
            result["groups"] = []
        if mutation == "counts":
            result["joint_hits"] = [-1, 1, 2]
        return SimpleNamespace(stdout=json.dumps(result).encode())

    monkeypatch.setattr("sabermetrics.intelligence.access.subprocess.run", run)
    result = engine_access(
        [
            {"name": str(i), "oracle_text": "", "type_line": "Creature"}
            for i in range(99)
        ],
        StrategyPlan(requirements={"instant_spell": 1}),
        binary="test-native",
        games=10,
    )
    assert result["status"] == ("measured" if mutation == "none" else "unavailable")

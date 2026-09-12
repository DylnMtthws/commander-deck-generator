"""Bounded adapter to the C++ resource probe. No invented simulation fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from sabermetrics.intelligence.cards import BASICS, COLORS

VERSION = "resource-probe-request.v1"


def compiled_land(card: dict, commander_colors: list[str] | None = None) -> dict:
    """Compile only simple, explicitly supported mana lands.

    The scenario ignores noncommander spells, not unrecognized land rules.
    A refusal is propagated as coverage, never simulated as a blank source.
    """
    name = card.get("name", "")
    types = card.get("type_line") or (f"Basic Land — {name}" if name in BASICS else "")
    identity = str(
        card.get("oracle_id") or card.get("id") or card.get("card_id") or name
    )
    result = {"id": identity, "land": False, "colors": 0, "tapped": False}
    if "land" not in types.lower():
        return result
    if "//" in types:
        raise ValueError("modal/transform land requires face-aware model")
    result["land"] = True
    if name in BASICS:
        result["colors"] = 1 << COLORS.index(BASICS[name])
        return result
    text = str(card.get("oracle_text") or "").lower().strip()
    # Only full supported text shapes, not a loose substring that overlooks
    # upkeep costs, bounce, replacement effects or a second prerequisite.
    text = re.sub(r"\([^)]*\)", "", text).strip()
    if text.startswith("this land enters tapped."):
        result["tapped"] = True
        text = text[len("this land enters tapped.") :].strip()
    if text == "{t}: add one mana of any color in your commander's color identity.":
        if not commander_colors:
            raise ValueError("commander colors required")
        result["colors"] = sum(1 << COLORS.index(c) for c in set(commander_colors))
        return result
    if re.fullmatch(r"\{t\}: add \{[cwubrg]\}(?: or \{[cwubrg]\})?\.", text):
        result["colors"] = sum(
            1 << COLORS.index(c.upper())
            for c in set(re.findall(r"\{([wubrg])\}", text))
        )
        return result
    # Intrinsic subtype mana is allowed only with no remaining ability text.
    if not text:
        for basic, color in BASICS.items():
            if basic in types:
                result["colors"] |= 1 << COLORS.index(color)
        if result["colors"]:
            return result
    raise ValueError("land has effects outside resource-probe.v1")


def compile_request(
    cards: list[dict], commander: dict, games: int = 2000, seed: int = 12345
) -> dict:
    if len(cards) != 99:
        raise ValueError("99 library cards required")
    symbols = re.findall(r"\{([^}]+)\}", commander.get("mana_cost") or "")
    if not symbols or any(not s.isdigit() and s not in COLORS for s in symbols):
        raise ValueError("commander cost unsupported by resource probe")
    generic = sum(int(s) for s in symbols if s.isdigit())
    pips = [symbols.count(c) for c in COLORS]
    compiled = [compiled_land(c, commander.get("color_identity")) for c in cards]
    identities = [c["id"] for c in compiled]
    identity = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(identities, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    # Only this full two-clause shape licenses a commander land engine.
    text = (commander.get("oracle_text") or "").strip()
    aesi_shape = re.fullmatch(
        r"You may play an additional land on each of your turns\.\s*Landfall [—–-] Whenever a land you control enters, you may draw a card\.",
        text,
    )
    return {
        "schema_version": VERSION,
        "cards": compiled,
        "commander_cost": {"generic": generic, "pips": pips},
        "extra_land_plays": 1 if aesi_shape else 0,
        "landfall_draw": 1 if aesi_shape else 0,
        "games": games,
        "turns": 6,
        "seed": seed,
        "deck_identity": identity,
    }


async def _remote_probe(url: str, request: dict, timeout: float) -> dict | None:
    """One wall-clock budget covers discovery, connection and response reading.

    HTTP phase timeouts alone are insufficient: several individually timely
    responses can otherwise exceed the caller's total comparison deadline.
    The synchronous generation worker owns this short-lived event loop.
    """
    headers = {}
    token = os.getenv("SABER_RESOURCE_PROBE_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False
        ) as client:
            caps = await client.get(url.rstrip("/") + "/capabilities")
            caps.raise_for_status()
            capability = caps.json().get("resource_probe", {})
            if (
                not capability.get("enabled")
                or capability.get("request_schema") != VERSION
            ):
                return None
            response = await client.post(
                url.rstrip("/") + "/resource-simulate", json=request, headers=headers
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise ValueError("oversize result")
            return response.json()


def run_probe(
    cards: list[dict],
    commander: dict,
    *,
    games: int = 2000,
    seed: int = 12345,
    binary: str | None = None,
    timeout: float = 10.0,
) -> dict:
    """Use configured local binary or private service; refuse unsupported inputs."""
    binary = binary or os.getenv("SABER_RESOURCE_PROBE_BIN")
    url = os.getenv("SABER_RESOURCE_PROBE_URL")
    if not binary and not url:
        return {
            "status": "unavailable",
            "reason": "Resource simulator is not configured.",
        }
    try:
        request = compile_request(cards, commander, games, seed)
    except ValueError as exc:
        return {"status": "unsupported", "reason": str(exc)}
    try:
        if binary:
            with tempfile.TemporaryDirectory(prefix="deck-resource-") as folder:
                path = Path(folder) / "request.json"
                path.write_text(json.dumps(request, ensure_ascii=False))
                result = subprocess.run(
                    [binary, "--resource-request", str(path)],
                    capture_output=True,
                    timeout=timeout,
                    check=True,
                )
                if len(result.stdout) > 1_000_000:
                    raise ValueError("oversize result")
                payload = json.loads(result.stdout)
        else:
            payload = asyncio.run(_remote_probe(url, request, timeout))
            if payload is None:
                return {
                    "status": "unsupported",
                    "reason": "Resource scenario is not enabled by simulator capabilities.",
                }

        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "resource-probe-result.v1"
            or payload.get("scenario") != "commander-land-engine-only.v1"
            or payload.get("deck_identity") != request["deck_identity"]
        ):
            raise ValueError("simulation identity/schema mismatch")
        canonical = json.dumps(
            request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        expected = (
            "sha256:"
            + hashlib.sha256(("resource-probe.v1\n" + canonical).encode()).hexdigest()
        )
        if payload.get("simulation_input_sha256") != expected:
            raise ValueError("simulation input mismatch")
        samples = payload.get("cast_samples")
        if (
            payload.get("games") != games
            or payload.get("turns") != 6
            or not isinstance(samples, list)
            or len(samples) != games
            or any(type(s) is not int or s not in (0, 1) for s in samples)
        ):
            raise ValueError("invalid simulation samples")
        if payload.get("commander_cast_count") != sum(samples):
            raise ValueError("invalid success count")
        for key in ("lands_mean", "commander_draws_mean"):
            if not math.isfinite(float(payload[key])) or payload[key] < 0:
                raise ValueError("invalid metric")
        return {
            "status": "measured",
            "result": payload,
            "scope": "Land and declared commander engine only; excludes all other spells and opponents. Not a win rate.",
        }
    except (
        OSError,
        subprocess.SubprocessError,
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        TimeoutError,
    ):
        return {
            "status": "unavailable",
            "reason": "Resource simulator failed or returned an invalid result.",
        }


def paired_improvement(baseline: dict, candidate: dict) -> dict:
    """Fixed-budget paired interval; caller must use fresh confirmation seeds."""
    a = baseline["result"]["cast_samples"]
    b = candidate["result"]["cast_samples"]
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("unpaired samples")
    diffs = [y - x for x, y in zip(a, b)]
    mean = sum(diffs) / len(diffs)
    # Hoeffding for paired differences in [-1,1]; conservative even for
    # all-identical samples, unlike a zero-variance Wald interval.
    radius = math.sqrt(2 * math.log(40) / len(diffs))
    return {
        "delta": mean,
        "interval": [max(-1.0, mean - radius), min(1.0, mean + radius)],
        "improved": mean - radius > 0.01,
        "metric": "commander_cast_by_turn_6_under_land_only_scenario",
    }

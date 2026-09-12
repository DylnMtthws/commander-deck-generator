"""Public card facts for grounding tests. Loaded from the coordinator Aang fixture.

No production records. Oracle text comes from tests/fixtures/cards/aang_quality.json
plus well-known public Sol Ring printing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_AANG_QUALITY_PATH = Path(__file__).resolve().parents[1] / "cards" / "aang_quality.json"
_FIXTURE_UPDATED = datetime(2026, 9, 12, tzinfo=UTC)


def _load_quality_cards() -> dict[str, dict[str, Any]]:
    payload = json.loads(_AANG_QUALITY_PATH.read_text(encoding="utf-8"))
    return {card["name"]: card for card in payload["cards"]}


def _front_face(raw: dict[str, Any]) -> dict[str, Any]:
    faces = raw.get("card_faces") or []
    if faces and isinstance(faces[0], dict):
        return faces[0]
    return {}


def _combined_oracle(raw: dict[str, Any]) -> str | None:
    if isinstance(raw.get("oracle_text"), str) and raw["oracle_text"].strip():
        return raw["oracle_text"]
    faces = raw.get("card_faces") or []
    chunks: list[str] = []
    for face in faces:
        if not isinstance(face, dict):
            continue
        name = (face.get("name") or "").strip()
        text = (face.get("oracle_text") or "").strip()
        if name and text:
            chunks.append(f"{name}\n{text}")
        elif text:
            chunks.append(text)
    return "\n\n".join(chunks) if chunks else None


def _card_record(raw: dict[str, Any]) -> dict[str, Any]:
    front = _front_face(raw)
    legalities = (
        raw.get("legalities") if isinstance(raw.get("legalities"), dict) else {}
    )
    commander_legal = legalities.get("commander") == "legal"
    return {
        "id": raw["id"],
        "oracle_id": raw["oracle_id"],
        "name": raw["name"],
        "mana_cost": raw.get("mana_cost") or front.get("mana_cost"),
        "cmc": float(raw.get("cmc") or 0.0),
        "type_line": raw.get("type_line") or front.get("type_line") or "",
        "oracle_text": _combined_oracle(raw),
        "color_identity": list(raw.get("color_identity") or []),
        "keywords": list(raw.get("keywords") or []),
        "is_legal_commander": commander_legal
        and "legendary"
        in (raw.get("type_line") or front.get("type_line") or "").lower(),
        "is_legal_in_99": commander_legal,
        "set_code": str(raw.get("set") or "").upper(),
        "rarity": raw.get("rarity") or "rare",
        "last_updated": _FIXTURE_UPDATED,
    }


def _list_card(
    raw: dict[str, Any],
    *,
    role: str,
    name: str | None = None,
) -> dict[str, Any]:
    record = _card_record(raw)
    front = _front_face(raw)
    return {
        "name": name or front.get("name") or record["name"],
        "mana_value": record["cmc"],
        "oracle_text": record["oracle_text"],
        "type_line": record["type_line"],
        "role": role,
    }


_QUALITY = _load_quality_cards()
_AANG_RAW = _QUALITY["Aang, at the Crossroads // Aang, Destined Savior"]
_BRAZEN_RAW = _QUALITY["Brazen Borrower // Petty Theft"]
_PEREGRINE_RAW = _QUALITY["Peregrine Drake"]
_TAIGAM_RAW = _QUALITY["Taigam, Master Opportunist"]
_SPARK_RAW = _QUALITY["Spark Double"]
_SAKASHIMA_RAW = _QUALITY["Sakashima of a Thousand Faces"]

AANG_COMMANDER = _card_record(_AANG_RAW)
AANG_FRONT_NAME = str(_front_face(_AANG_RAW).get("name") or "Aang, at the Crossroads")

AANG_LIST_CARD = _list_card(_AANG_RAW, role="commander", name=AANG_COMMANDER["name"])
BRAZEN_BORROWER = _list_card(_BRAZEN_RAW, role="removal", name="Brazen Borrower")
PEREGRINE_DRAKE = _list_card(_PEREGRINE_RAW, role="ramp")
TAIGAM = _list_card(_TAIGAM_RAW, role="utility")
SPARK_DOUBLE = _list_card(_SPARK_RAW, role="utility")
SAKASHIMA = _list_card(_SAKASHIMA_RAW, role="utility")

# Public printed text (Gatherer/Scryfall); not present in aang_quality.json.
SOL_RING = {
    "name": "Sol Ring",
    "mana_value": 1.0,
    "oracle_text": "{T}: Add {C}{C}.",
    "type_line": "Artifact",
    "role": "ramp",
}

UNKNOWN_CARD = {"name": "Uncatalogued Mystery"}

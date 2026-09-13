"""Canonical printed values survive ingestion without invented body or color data."""

import json
import sqlite3

from sabermetrics.db import row_to_card
from sabermetrics.ingestion.scryfall import ScryfallIngestion
from sabermetrics.runtime.schema import SCHEMA_VERSION, setup_database


def raw_card(**changes):
    return {
        "id": "fixture",
        "oracle_id": "oracle-fixture",
        "name": "Printed fixture",
        "mana_cost": "{R}",
        "cmc": 1,
        "type_line": "Creature — Goblin",
        "oracle_text": "",
        "color_identity": ["R"],
        "colors": ["R"],
        "power": "1",
        "toughness": "1",
        "set": "test",
        "rarity": "common",
        "legalities": {"commander": "legal"},
        "prices": {"usd": "0.10"},
        **changes,
    }


def test_existing_rows_migrate_to_unknown_without_losing_data(tmp_path):
    path = tmp_path / "old.db"
    setup_database(path, quiet=True)
    with sqlite3.connect(path) as conn:
        for view in ("card_candidates", "commander_candidates"):
            conn.execute(f"DROP VIEW {view}")
        for field in ("power", "toughness", "colors"):
            conn.execute(f"ALTER TABLE cards DROP COLUMN {field}")
        conn.execute(
            "INSERT INTO cards(id, oracle_id, name) VALUES ('old','oracle','Old')"
        )
    setup_database(path, quiet=True)
    setup_database(path, quiet=True)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT name,power,toughness,colors FROM cards"
        ).fetchone() == ("Old", None, None, None)
        assert (
            conn.execute(
                "SELECT count(*) FROM _schema_version WHERE version=?",
                (SCHEMA_VERSION,),
            ).fetchone()[0]
            == 1
        )


def test_ingest_hydrate_and_candidate_view_preserve_printed_values(tmp_path):
    path = tmp_path / "cards.db"
    setup_database(path, quiet=True)
    card = raw_card(power="*", toughness="1+*", colors=[])
    assert ScryfallIngestion(path)._ingest_cards([card])[:3] == (1, 1, 0)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM card_candidates").fetchone()
        assert row["power"] == "*" and row["toughness"] == "1+*"
        hydrated = row_to_card(row)
    assert hydrated.power == "*" and hydrated.toughness == "1+*"
    assert hydrated.colors == [] and hydrated.color_identity == ["R"]
    assert hydrated.model_dump()["colors"] == []


def test_missing_values_stay_unknown_including_multiface_cards(tmp_path):
    path = tmp_path / "cards.db"
    setup_database(path, quiet=True)
    card = raw_card(card_faces=[{"power": "9", "toughness": "9", "colors": ["G"]}])
    for key in ("power", "toughness", "colors"):
        card.pop(key)
    assert ScryfallIngestion(path)._ingest_cards([card])[2] == 0
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        hydrated = row_to_card(conn.execute("SELECT * FROM cards").fetchone())
    assert hydrated.power is None and hydrated.toughness is None
    assert hydrated.colors is None
    assert hydrated.color_identity == ["R"]


def test_reingestion_updates_printed_values(tmp_path):
    path = tmp_path / "cards.db"
    setup_database(path, quiet=True)
    source = ScryfallIngestion(path)
    source._ingest_cards([raw_card()])
    source._ingest_cards([raw_card(power="2", toughness="3", colors=["U", "R"])])
    with sqlite3.connect(path) as conn:
        power, toughness, colors = conn.execute(
            "SELECT power,toughness,colors FROM cards"
        ).fetchone()
    assert (power, toughness, json.loads(colors)) == ("2", "3", ["U", "R"])


def test_commander_loader_retains_printed_body_and_colors(tmp_path):
    from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest

    path = tmp_path / "cards.db"
    setup_database(path, quiet=True)
    ScryfallIngestion(path)._ingest_cards(
        [
            raw_card(
                type_line="Legendary Creature — Goblin",
                power="2",
                toughness="4",
                colors=[],
            )
        ]
    )
    builder = DeckBuilder(path)
    commander = builder._validate_request(
        DeckBuildRequest(commander_id="fixture", budget_usd=100, power_target=3)
    )
    assert (commander.power, commander.toughness, commander.colors) == ("2", "4", [])
    assert commander.color_identity == ["R"]


def test_final_deck_model_retains_printed_body_colors_and_role(tmp_path):
    import time
    from types import SimpleNamespace

    from sabermetrics.models.deck import DeckClassification, DeckNarrative
    from sabermetrics.pipeline.deck_builder import DeckBuilder, DeckBuildRequest
    from sabermetrics.pipeline.slot_assigner import SlotAssignment

    path = tmp_path / "cards.db"
    setup_database(path, quiet=True)
    ScryfallIngestion(path)._ingest_cards(
        [raw_card(type_line="Legendary Creature — Goblin")]
    )
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        card = dict(conn.execute("SELECT * FROM cards").fetchone())
    card.update(colors='["R"]', power="*", toughness="1+*")
    builder = DeckBuilder(path)
    builder._signals = {}
    request = DeckBuildRequest(commander_id="fixture", budget_usd=100, power_target=3)
    deck = builder._build_deck_model(
        builder._validate_request(request),
        request,
        SimpleNamespace(commander_id="fixture"),
        SimpleNamespace(
            assignments=[SlotAssignment(card=card, slot_role="utility", score=0)],
            total_price=0.1,
        ),
        DeckNarrative(
            game_plan="fixture",
            key_synergies=[],
            weaknesses=[],
            suggested_play_pattern="fixture",
        ),
        DeckClassification(estimated_bracket=1, bracket_reasoning="fixture"),
        0,
        time.time(),
    )
    serialized = deck.model_dump(mode="json")["cards"][0]
    assert serialized["card"]["power"] == "*"
    assert serialized["card"]["toughness"] == "1+*"
    assert serialized["card"]["colors"] == ["R"]
    assert serialized["slot_role"] == "utility"

"""Both the historical JSON and current compressed JSONL bulk formats."""

import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

from sabermetrics.ingestion.scryfall import ScryfallIngestion


@pytest.mark.parametrize("key", ["download_uri", "jsonl_download_uri"])
def test_bulk_metadata_supports_both_download_keys(tmp_path, key):
    response = MagicMock()
    response.json.return_value = {
        "data": [{"type": "default_cards", key: "https://data.scryfall.io/cards"}]
    }
    with patch("httpx.get", return_value=response):
        assert (
            ScryfallIngestion(tmp_path / "unused.db")._get_bulk_download_url()
            == "https://data.scryfall.io/cards"
        )


@pytest.mark.parametrize("suffix", [".json", ".jsonl.gz"])
def test_download_reads_array_and_compressed_lines(tmp_path, suffix):
    cards = [{"id": "first", "name": "Card One"}, {"id": "second", "name": "Card Two"}]
    raw = (
        json.dumps(cards).encode()
        if suffix == ".json"
        else gzip.compress(("\n".join(json.dumps(c) for c in cards) + "\n").encode())
    )
    response = MagicMock()
    response.headers = {"content-length": str(len(raw))}
    response.iter_bytes.return_value = [raw]
    context = MagicMock()
    context.__enter__.return_value = response
    with patch("httpx.stream", return_value=context):
        assert (
            ScryfallIngestion(tmp_path / "unused.db")._download_bulk_data(
                "https://data.scryfall.io/cards" + suffix
            )
            == cards
        )

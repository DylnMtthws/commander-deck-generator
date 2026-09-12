"""Prepared embedding cache, empty retrieval, and operator CLI."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from sabermetrics.analytics.embeddings import (
    CACHE_ENV,
    REVISION_ENV,
    VECTOR_FORMAT,
    EmbeddingService,
)
from sabermetrics.reference_layer.retriever import ReferenceQuery, ReferenceRetriever
from sabermetrics.runtime.prepare_embeddings import (
    main as prepare_main,
)
from sabermetrics.runtime.prepare_embeddings import (
    prepare_public_card_embeddings,
)
from sabermetrics.runtime.synthetic import SYNTHETIC_CARDS

DIM = 8


def _vec_for(text: str, dim: int = DIM) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    return rng.standard_normal(dim).astype(np.float32)


class RecordingModel:
    """Deterministic in-process encoder. Never touches the network."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def encode(self, texts, show_progress_bar=False, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(texts, str):
            self.calls.append([texts])
            return _vec_for(texts, self.dim)
        seq = list(texts)
        self.calls.append(seq)
        return np.stack([_vec_for(t, self.dim) for t in seq])

    @property
    def texts_encoded(self) -> list[str]:
        return [t for call in self.calls for t in call]


def _bind_model(
    monkeypatch: pytest.MonkeyPatch, model: RecordingModel
) -> RecordingModel:
    monkeypatch.setattr(EmbeddingService, "_load_model", lambda self: model)
    return model


def _service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs
) -> tuple[EmbeddingService, RecordingModel]:
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    cache_path = kwargs.pop("cache_path", tmp_path / "emb.sqlite")
    revision = kwargs.pop("revision", "test-rev")
    svc = EmbeddingService(cache_path=cache_path, revision=revision, **kwargs)
    return svc, model


def _cards_db(path: Path, rows: list[tuple[str, str]] | None = None) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE cards (id TEXT, oracle_id TEXT, name TEXT, oracle_text TEXT)"
    )
    conn.execute("CREATE TABLE users (id TEXT, email TEXT)")
    conn.execute("CREATE TABLE generated_decks (id TEXT, owner_id TEXT)")
    conn.execute("INSERT INTO users VALUES ('user-1', 'secret@example.com')")
    if rows is None:
        for card in SYNTHETIC_CARDS:
            conn.execute(
                "INSERT INTO cards (id, oracle_id, name, oracle_text) VALUES (?,?,?,?)",
                (card["id"], card["oracle_id"], card["name"], card["oracle_text"]),
            )
    else:
        for i, (oracle_id, text) in enumerate(rows):
            conn.execute(
                "INSERT INTO cards (id, oracle_id, name, oracle_text) VALUES (?,?,?,?)",
                (f"id-{i}", oracle_id, f"Card {i}", text),
            )
    conn.commit()
    conn.close()
    return path


def _reference_db(path: Path, *, with_embedding: bool) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE reference_chunks (
            id TEXT PRIMARY KEY,
            document TEXT,
            section TEXT,
            tier INTEGER,
            content TEXT,
            embedding BLOB
        )
        """)
    blob = np.ones(4, dtype=np.float32).tobytes() if with_embedding else None
    conn.execute(
        "INSERT INTO reference_chunks VALUES (?,?,?,?,?,?)",
        (
            "c1",
            "comprehensive_rules",
            "CR 702",
            1,
            "Flying is an evasion ability.",
            blob,
        ),
    )
    conn.commit()
    conn.close()
    return path


# --- persistence / invalidation ---


def test_restart_reuses_disk_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    svc1, model1 = _service(tmp_path, monkeypatch, cache_path=cache)
    first = svc1.embed("synthetic oracle: draw a card")
    assert model1.texts_encoded == ["synthetic oracle: draw a card"]

    svc2, model2 = _service(tmp_path, monkeypatch, cache_path=cache)
    second = svc2.embed("synthetic oracle: draw a card")
    assert model2.calls == []
    assert np.allclose(first, second)
    assert first.dtype == np.float32
    assert np.isfinite(first).all()


def test_text_change_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, model = _service(tmp_path, monkeypatch)
    a = svc.embed("alpha")
    b = svc.embed("alpha!")
    assert not np.allclose(a, b)
    assert model.texts_encoded == ["alpha", "alpha!"]


def test_model_name_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    svc_a = EmbeddingService(model_name="model-a", cache_path=cache, revision="r1")
    svc_a.embed("same-text")
    svc_b = EmbeddingService(model_name="model-b", cache_path=cache, revision="r1")
    svc_b.embed("same-text")
    assert model.texts_encoded == ["same-text", "same-text"]


def test_revision_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    svc_r1, model1 = _service(tmp_path, monkeypatch, cache_path=cache, revision="rev-1")
    svc_r1.embed("same-text")
    svc_r2, model2 = _service(tmp_path, monkeypatch, cache_path=cache, revision="rev-2")
    svc_r2.embed("same-text")
    assert model2.texts_encoded == ["same-text"]
    assert svc_r1.revision_pinned is True
    assert svc_r2.revision_pinned is True


def test_env_activates_cache_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "from-env.sqlite"
    monkeypatch.setenv(CACHE_ENV, str(cache))
    monkeypatch.setenv(REVISION_ENV, "env-rev")
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    first = EmbeddingService()
    first.embed("env-text")
    second = EmbeddingService()
    second.embed("env-text")
    assert first.revision_pinned is True
    assert model.texts_encoded == ["env-text"]
    assert cache.is_file()


def test_unset_revision_is_not_claimed_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REVISION_ENV, raising=False)
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    svc = EmbeddingService(
        cache_path=tmp_path / "emb.sqlite", revision=None, use_env=False
    )
    assert svc.revision_pinned is False
    svc.embed("x")
    assert not (tmp_path / "emb.sqlite").exists()


def test_revision_passed_to_sentence_transformer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeST:
        def __init__(self, name, **kwargs):  # type: ignore[no-untyped-def]
            captured["name"] = name
            captured["kwargs"] = kwargs

        def encode(self, texts, **kwargs):  # type: ignore[no-untyped-def]
            return _vec_for(texts if isinstance(texts, str) else texts[0])

    fake_mod = ModuleType("sentence_transformers")
    fake_mod.SentenceTransformer = FakeST  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake_mod)

    pinned = EmbeddingService(revision="abc123def", use_env=False)
    pinned._load_model()
    assert captured["kwargs"]["revision"] == "abc123def"

    captured.clear()
    unpinned = EmbeddingService(use_env=False)
    unpinned._load_model()
    assert "revision" not in captured["kwargs"]


# --- batching ---


def test_duplicate_texts_encoded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, model = _service(tmp_path, monkeypatch)
    out = svc.embed_batch(
        ["tap add green", "tap add green", "draw a card", "tap add green"]
    )
    assert len(out) == 4
    assert np.allclose(out[0], out[1])
    assert np.allclose(out[0], out[3])
    assert not np.allclose(out[0], out[2])
    assert model.calls == [["tap add green", "draw a card"]]


def test_empty_batch_does_not_load_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, model = _service(tmp_path, monkeypatch)
    assert svc.embed_batch([]) == []
    assert model.calls == []


# --- corruption / dimension ---


def _insert_cache_row(
    cache: Path,
    *,
    text: str,
    vector: bytes,
    dim: int,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    revision: str = "test-rev",
    dtype: str = "float32",
    fmt: str = VECTOR_FORMAT,
) -> None:
    conn = sqlite3.connect(str(cache))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prepared_embeddings (
            model_name TEXT NOT NULL,
            revision TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            dim INTEGER NOT NULL,
            dtype TEXT NOT NULL,
            format TEXT NOT NULL,
            vector BLOB NOT NULL,
            PRIMARY KEY (model_name, revision, text_hash)
        )
        """)
    conn.execute(
        "INSERT OR REPLACE INTO prepared_embeddings VALUES (?,?,?,?,?,?,?)",
        (
            model_name,
            revision,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            dim,
            dtype,
            fmt,
            vector,
        ),
    )
    conn.commit()
    conn.close()


def test_corrupt_blob_recomputes_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    text = "landfall trigger"
    _insert_cache_row(cache, text=text, vector=b"not-a-vector", dim=8)
    svc, model = _service(tmp_path, monkeypatch, cache_path=cache)
    result = svc.embed(text)
    assert model.texts_encoded == [text]
    assert result.shape == (DIM,)
    assert not np.allclose(result, np.zeros(DIM, dtype=np.float32))
    assert np.isfinite(result).all()


def test_nonfinite_cache_entry_recomputes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    text = "infinite mana"
    bad = np.array([1.0, np.inf, 0.0, np.nan, 1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    _insert_cache_row(cache, text=text, vector=bad.tobytes(), dim=8)
    svc, model = _service(tmp_path, monkeypatch, cache_path=cache)
    result = svc.embed(text)
    assert model.texts_encoded == [text]
    assert np.isfinite(result).all()
    assert not np.allclose(result, np.zeros(DIM))


def test_wrong_dimension_recomputes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    text = "dim mismatch"
    tiny = np.ones(3, dtype=np.float32)
    svc, model = _service(tmp_path, monkeypatch, cache_path=cache)
    primed = svc.embed("primer")
    assert primed.shape == (DIM,)
    _insert_cache_row(cache, text=text, vector=tiny.tobytes(), dim=3)
    fresh, model2 = _service(tmp_path, monkeypatch, cache_path=cache)
    result = fresh.embed(text)
    assert text in model2.texts_encoded
    assert result.shape == (DIM,)
    assert result.shape != tiny.shape
    assert np.isfinite(result).all()


def test_incompatible_format_recomputes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    text = "pickled-looking"
    payload = b"\x80\x04" + np.zeros(8, dtype=np.float32).tobytes()
    _insert_cache_row(cache, text=text, vector=payload, dim=8, fmt="pickle")
    svc, model = _service(tmp_path, monkeypatch, cache_path=cache)
    result = svc.embed(text)
    assert model.texts_encoded == [text]
    assert result.dtype == np.float32


def test_disk_vectors_are_raw_float32_not_pickle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    svc, _model = _service(tmp_path, monkeypatch, cache_path=cache)
    vec = svc.embed("raw bytes")
    conn = sqlite3.connect(str(cache))
    dim, dtype_name, fmt, blob = conn.execute(
        "SELECT dim, dtype, format, vector FROM prepared_embeddings"
    ).fetchone()
    conn.close()
    assert dtype_name == "float32"
    assert fmt == VECTOR_FORMAT
    restored = np.frombuffer(blob, dtype=np.float32)
    assert restored.shape == (dim,)
    assert np.allclose(restored, vec)
    src = Path("src/sabermetrics/analytics/embeddings.py").read_text()
    assert "pickle" not in src


# --- missing / unwritable cache ---


def test_missing_cache_file_computes_and_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "nested" / "missing" / "emb.sqlite"
    assert not cache.exists()
    svc, model = _service(tmp_path, monkeypatch, cache_path=cache)
    vec = svc.embed("created on demand")
    assert model.texts_encoded == ["created on demand"]
    assert cache.is_file()
    assert vec.shape == (DIM,)


def test_unwritable_cache_still_computes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise PermissionError("cache is read-only")

    monkeypatch.setattr(sqlite3, "connect", boom)
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    svc = EmbeddingService(cache_path=cache, revision="r")
    vec = svc.embed("still works")
    assert np.isfinite(vec).all()
    assert vec.shape == (DIM,)
    assert model.texts_encoded == ["still works"]
    # Second call uses in-memory cache, not zeros.
    again = svc.embed("still works")
    assert np.allclose(vec, again)
    assert model.texts_encoded == ["still works"]


def test_parent_is_file_cache_still_computes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "not-a-dir"
    parent.write_text("blocked")
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    svc = EmbeddingService(cache_path=parent / "emb.sqlite", revision="r")
    vec = svc.embed("no directory")
    assert np.isfinite(vec).all()
    assert not np.allclose(vec, np.zeros(DIM))


def test_memory_api_without_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    svc = EmbeddingService(use_env=False)
    a = svc.embed("mem")
    b = svc.embed("mem")
    assert np.allclose(a, b)
    assert model.texts_encoded == ["mem"]
    assert svc.cache_size == 1
    svc.clear_cache()
    assert svc.cache_size == 0


def test_cache_errors_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise OSError("disk failed")

    monkeypatch.setattr(sqlite3, "connect", boom)
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    svc = EmbeddingService(cache_path=tmp_path / "x.sqlite", revision="r")
    caplog.set_level("WARNING")
    for i in range(10):
        svc.embed(f"text-{i}")
    warnings = [r for r in caplog.records if "embedding cache" in r.getMessage()]
    assert 0 < len(warnings) <= 3


def test_concurrent_writers_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "emb.sqlite"
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    errors: list[BaseException] = []
    texts = [f"thread-text-{i}" for i in range(8)]

    def worker(text: str) -> None:
        try:
            svc = EmbeddingService(cache_path=cache, revision="r")
            vec = svc.embed(text)
            assert np.isfinite(vec).all()
        except BaseException as exc:  # noqa: BLE001 — collect then fail
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in texts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # Fresh instance reads everyone's vectors from disk.
    reader, reader_model = _service(
        tmp_path, monkeypatch, cache_path=cache, revision="r"
    )
    for text in texts:
        got = reader.embed(text)
        assert got.shape == (DIM,)
    assert reader_model.calls == []


# --- retriever empty corpus ---


def test_empty_embedding_corpus_skips_encoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _reference_db(tmp_path / "ref.db", with_embedding=False)
    constructed: list[str] = []

    class BoomIndexer:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            constructed.append("init")
            raise AssertionError("encoder must not be constructed")

        def compute_embedding(self, text: str) -> np.ndarray:
            constructed.append("embed")
            raise AssertionError("encoder must not run")

    monkeypatch.setattr(
        "sabermetrics.reference_layer.indexer.EmbeddingIndexer", BoomIndexer
    )
    retriever = ReferenceRetriever(db)
    result = retriever.retrieve(ReferenceQuery(query_text="flying evasion"))
    assert result == []
    assert constructed == []


def test_empty_table_skips_encoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE reference_chunks "
        "(id TEXT, document TEXT, section TEXT, tier INTEGER, content TEXT, embedding BLOB)"
    )
    conn.commit()
    conn.close()
    constructed = []

    class BoomIndexer:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            constructed.append("init")

    monkeypatch.setattr(
        "sabermetrics.reference_layer.indexer.EmbeddingIndexer", BoomIndexer
    )
    result = ReferenceRetriever(db).retrieve(ReferenceQuery(query_text="anything"))
    assert result == []
    assert constructed == []


def test_nonempty_corpus_uses_indexer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _reference_db(tmp_path / "ref.db", with_embedding=True)
    used = []

    class FakeIndexer:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            used.append("init")

        def compute_embedding(self, text: str) -> np.ndarray:
            used.append(text)
            return np.ones(4, dtype=np.float32)

    monkeypatch.setattr(
        "sabermetrics.reference_layer.indexer.EmbeddingIndexer", FakeIndexer
    )
    result = ReferenceRetriever(db).retrieve(ReferenceQuery(query_text="flying"))
    assert used[0] == "init"
    assert "flying" in used
    assert len(result) == 1
    assert result[0].id == "c1"
    assert result[0].similarity_score > 0


def test_text_search_fallback_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _reference_db(tmp_path / "ref.db", with_embedding=True)

    class BrokenIndexer:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        def compute_embedding(self, text: str) -> np.ndarray:
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "sabermetrics.reference_layer.indexer.EmbeddingIndexer", BrokenIndexer
    )
    result = ReferenceRetriever(db).retrieve(
        ReferenceQuery(query_text="flying evasion")
    )
    assert len(result) == 1
    assert result[0].id == "c1"
    assert result[0].similarity_score > 0


# --- operator CLI ---


def test_prepare_embeddings_incremental(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REVISION_ENV, "test-revision")
    db = _cards_db(tmp_path / "app.db")
    cache = tmp_path / "cache.sqlite"
    model = RecordingModel()
    _bind_model(monkeypatch, model)

    first = prepare_public_card_embeddings(db, cache, batch_size=2)
    assert first["oracle_ids"] == len(SYNTHETIC_CARDS)
    assert first["unique_texts"] == len(SYNTHETIC_CARDS)
    assert first["newly_encoded"] == len(SYNTHETIC_CARDS)
    assert first["cache_hits"] == 0
    encoded_first = list(model.texts_encoded)

    second = prepare_public_card_embeddings(db, cache, batch_size=2)
    assert second["newly_encoded"] == 0
    assert second["cache_hits"] == len(SYNTHETIC_CARDS)
    assert model.texts_encoded == encoded_first


def test_prepare_embeddings_dedupes_oracle_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _cards_db(
        tmp_path / "app.db",
        rows=[
            ("oid-a", "First text."),
            ("oid-a", "First text."),
            ("oid-b", "Second text."),
        ],
    )
    cache = tmp_path / "cache.sqlite"
    model = RecordingModel()
    _bind_model(monkeypatch, model)
    stats = prepare_public_card_embeddings(db, cache, batch_size=64)
    assert stats["oracle_ids"] == 2
    assert stats["unique_texts"] == 2
    assert sorted(model.texts_encoded) == ["First text.", "Second text."]


def test_prepare_cli_json_and_skips_empty_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _cards_db(
        tmp_path / "app.db",
        rows=[
            ("oid-keep", "Keep this oracle text."),
            ("oid-blank", "   "),
        ],
    )
    cache = tmp_path / "cache.sqlite"
    _bind_model(monkeypatch, RecordingModel())
    rc = prepare_main(["--db", str(db), "--cache", str(cache), "--batch-size", "8"])
    assert rc == 0
    stats = json.loads(capsys.readouterr().out.strip())
    assert stats["oracle_ids"] == 1
    assert stats["newly_encoded"] == 1
    assert stats["batch_size"] == 8


def test_prepare_does_not_read_user_tables() -> None:
    src = Path("src/sabermetrics/runtime/prepare_embeddings.py").read_text()
    assert "FROM cards" in src
    assert "FROM users" not in src
    assert "FROM generated_decks" not in src
    assert "FROM decks" not in src
    assert "FROM favorite" not in src
    embeddings_src = Path("src/sabermetrics/analytics/embeddings.py").read_text()
    assert "pickle" not in embeddings_src


def test_prepare_not_on_request_path() -> None:
    app = Path("src/sabermetrics/ui/app.py").read_text()
    routes = Path("src/sabermetrics/ui/routes.py").read_text()
    assert "prepare_embeddings" not in app
    assert "prepare_embeddings" not in routes

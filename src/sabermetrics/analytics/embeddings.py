"""Embedding wrapper for application-wide use (D4.8).

Wraps sentence-transformers for computing text embeddings with
in-memory caching of recently embedded texts.

Optional persistent SQLite cache (separate from the application database)
is activated by SABER_EMBEDDING_CACHE. SABER_EMBEDDING_REVISION is the
explicit model-version key stored with each vector; it is passed through
to SentenceTransformer only when set.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CACHE_ENV = "SABER_EMBEDDING_CACHE"
REVISION_ENV = "SABER_EMBEDDING_REVISION"
VECTOR_DTYPE_NAME = "float32"
VECTOR_FORMAT = "raw_f32"
_MAX_CACHE_DIAGNOSTICS = 3
_UNPINNED_REVISION = ""

_CACHE_SCHEMA = """
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
"""

_CACHE_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_cache_meta (
    model_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    dim INTEGER NOT NULL,
    dtype TEXT NOT NULL,
    format TEXT NOT NULL,
    PRIMARY KEY (model_name, revision)
)
"""


def _text_hash(text: str) -> str:
    """Exact UTF-8 SHA-256 of the text; no normalization."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else None


def _env_revision() -> str | None:
    raw = os.environ.get(REVISION_ENV, "").strip()
    return raw or None


class EmbeddingCache:
    """LRU cache for text embeddings."""

    def __init__(self, max_size: int = 10000) -> None:
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> np.ndarray | None:
        """Get cached embedding, moving it to end (most recent)."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, embedding: np.ndarray) -> None:
        """Cache an embedding, evicting oldest if at capacity."""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = embedding
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            self._cache[key] = embedding

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


class EmbeddingService:
    """Application-wide embedding service with caching.

    Lazy-loads the sentence-transformers model on first use.
    Caches recent embeddings in memory for fast repeated lookups.
    When SABER_EMBEDDING_CACHE is set, also persists float32 vectors in
    a SQLite file keyed by model name, revision, text hash, and format.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        cache_size: int = 10000,
        *,
        cache_path: Path | str | None = None,
        revision: str | None = None,
        use_env: bool = True,
    ) -> None:
        self._model_name = model_name
        self._model = None
        self._cache = EmbeddingCache(max_size=cache_size)
        self._mem_lock = threading.Lock()
        if cache_path is not None:
            self._cache_path: Path | None = Path(cache_path)
        elif use_env:
            self._cache_path = _env_path(CACHE_ENV)
        else:
            self._cache_path = None
        if revision is not None:
            self._revision = revision.strip() or None
        elif use_env:
            self._revision = _env_revision()
        else:
            self._revision = None
        self._revision_key = self._revision if self._revision else _UNPINNED_REVISION
        if self._cache_path is not None and self._revision is None:
            logger.warning(
                "Persistent embeddings require SABER_EMBEDDING_REVISION; using memory cache."
            )
            self._cache_path = None
        self._expected_dim: int | None = None
        self._cache_log_count = 0
        self._disk_lock = threading.Lock()

    def _load_model(self):  # type: ignore[no-untyped-def]
        """Lazy-load the embedding model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            if self._revision:
                logger.info(
                    "Loading embedding model: %s (revision=%s)",
                    self._model_name,
                    self._revision,
                )
                self._model = SentenceTransformer(
                    self._model_name, revision=self._revision
                )
            else:
                logger.info(
                    "Loading embedding model: %s (revision not pinned)",
                    self._model_name,
                )
                self._model = SentenceTransformer(self._model_name)
        return self._model

    def _cache_key(self, text: str) -> str:
        """Generate an in-memory cache key for text (exact content hash)."""
        return _text_hash(text)

    def _note_cache_error(self, message: str, *args: object) -> None:
        if self._cache_log_count >= _MAX_CACHE_DIAGNOSTICS:
            return
        self._cache_log_count += 1
        logger.warning(message, *args)

    def _validate_vector(
        self, raw: object, *, expected_dim: int | None
    ) -> np.ndarray | None:
        """Accept finite 1-d float32 vectors only; never coerce NaN/Inf to zero."""
        try:
            vec = np.asarray(raw, dtype=np.float32)
        except (TypeError, ValueError):
            return None
        if vec.ndim != 1:
            return None
        if vec.ndim != 1 or vec.size == 0:
            return None
        if expected_dim is not None and int(vec.size) != int(expected_dim):
            return None
        if vec.dtype != np.float32:
            vec = vec.astype(np.float32, copy=False)
        if not np.isfinite(vec).all():
            return None
        return np.ascontiguousarray(vec, dtype=np.float32)

    @contextmanager
    def _open_cache(self) -> Iterator[sqlite3.Connection | None]:
        """Short-lived SQLite connection. Yields None if cache is unavailable."""
        if self._cache_path is None:
            yield None
            return
        conn: sqlite3.Connection | None = None
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._cache_path), timeout=0.2)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=200")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_CACHE_SCHEMA)
            conn.execute(_CACHE_META_SCHEMA)
        except (OSError, sqlite3.Error, ValueError, TypeError) as e:
            self._note_cache_error("embedding cache unavailable (%s)", type(e).__name__)
            self._cache_path = None  # avoid repeated timeout cost for this worker
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error as close_error:
                    self._note_cache_error(
                        "embedding cache close failed (%s)", type(close_error).__name__
                    )
            yield None
            return
        try:
            yield conn
        finally:
            try:
                conn.close()
            except sqlite3.Error as close_error:
                self._note_cache_error(
                    "embedding cache close failed (%s)", type(close_error).__name__
                )

    def _disk_get(self, text: str) -> np.ndarray | None:
        if self._cache_path is None:
            return None
        text_hash = _text_hash(text)
        with self._disk_lock:
            try:
                with self._open_cache() as conn:
                    if conn is None:
                        return None
                    meta = conn.execute(
                        """
                        SELECT dim, dtype, format FROM embedding_cache_meta
                        WHERE model_name = ? AND revision = ?
                        """,
                        (self._model_name, self._revision_key),
                    ).fetchone()
                    if meta is not None:
                        meta_dim, meta_dtype, meta_fmt = meta
                        if (
                            meta_dtype != VECTOR_DTYPE_NAME
                            or meta_fmt != VECTOR_FORMAT
                            or int(meta_dim) <= 0
                        ):
                            return None
                        if self._expected_dim is None:
                            self._expected_dim = int(meta_dim)
                        elif self._expected_dim != int(meta_dim):
                            return None
                    row = conn.execute(
                        """
                        SELECT dim, dtype, format, vector
                        FROM prepared_embeddings
                        WHERE model_name = ? AND revision = ? AND text_hash = ?
                        """,
                        (self._model_name, self._revision_key, text_hash),
                    ).fetchone()
                    if row is None:
                        return None
                    dim, dtype_name, fmt, blob = row
                    required_dim = self._expected_dim
                    if required_dim is not None and int(dim) != int(required_dim):
                        conn.execute(
                            """
                            DELETE FROM prepared_embeddings
                            WHERE model_name = ? AND revision = ? AND text_hash = ?
                            """,
                            (self._model_name, self._revision_key, text_hash),
                        )
                        conn.commit()
                        return None
                    if dtype_name != VECTOR_DTYPE_NAME or fmt != VECTOR_FORMAT:
                        conn.execute(
                            """
                            DELETE FROM prepared_embeddings
                            WHERE model_name = ? AND revision = ? AND text_hash = ?
                            """,
                            (self._model_name, self._revision_key, text_hash),
                        )
                        conn.commit()
                        return None
                    if not isinstance(blob, (bytes, memoryview, bytearray)):
                        return None
                    blob_bytes = bytes(blob)
                    if dim <= 0 or len(blob_bytes) != int(dim) * 4:
                        conn.execute(
                            """
                            DELETE FROM prepared_embeddings
                            WHERE model_name = ? AND revision = ? AND text_hash = ?
                            """,
                            (self._model_name, self._revision_key, text_hash),
                        )
                        conn.commit()
                        return None
                    vec = np.frombuffer(blob_bytes, dtype=np.float32).copy()
                    validated = self._validate_vector(
                        vec, expected_dim=self._expected_dim
                    )
                    if validated is None:
                        conn.execute(
                            """
                            DELETE FROM prepared_embeddings
                            WHERE model_name = ? AND revision = ? AND text_hash = ?
                            """,
                            (self._model_name, self._revision_key, text_hash),
                        )
                        conn.commit()
                        return None
                    if self._expected_dim is None:
                        self._expected_dim = int(validated.size)
                    return validated
            except (OSError, sqlite3.Error, ValueError, TypeError) as e:
                self._note_cache_error("embedding cache read failed: %s", e)
                return None

    def _disk_put(self, text: str, embedding: np.ndarray) -> None:
        if self._cache_path is None:
            return
        text_hash = _text_hash(text)
        payload = np.ascontiguousarray(embedding, dtype=np.float32).tobytes()
        with self._disk_lock:
            try:
                with self._open_cache() as conn:
                    if conn is None:
                        return
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO embedding_cache_meta
                        (model_name, revision, dim, dtype, format)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            self._model_name,
                            self._revision_key,
                            int(embedding.size),
                            VECTOR_DTYPE_NAME,
                            VECTOR_FORMAT,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO prepared_embeddings
                        (model_name, revision, text_hash, dim, dtype, format, vector)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self._model_name,
                            self._revision_key,
                            text_hash,
                            int(embedding.size),
                            VECTOR_DTYPE_NAME,
                            VECTOR_FORMAT,
                            payload,
                        ),
                    )
                    conn.commit()
            except (OSError, sqlite3.Error, ValueError, TypeError) as e:
                self._note_cache_error("embedding cache write failed: %s", e)

    def _lookup_cached(self, text: str) -> np.ndarray | None:
        key = self._cache_key(text)
        with self._mem_lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        disk = self._disk_get(text)
        if disk is None:
            return None
        with self._mem_lock:
            self._cache.put(key, disk)
        return disk

    def _store(self, text: str, embedding: np.ndarray) -> None:
        if self._expected_dim is None:
            self._expected_dim = int(embedding.size)
        key = self._cache_key(text)
        with self._mem_lock:
            self._cache.put(key, embedding)
        self._disk_put(text, embedding)

    def _encode_unique(self, texts: list[str]) -> list[np.ndarray]:
        model = self._load_model()
        if len(texts) == 1:
            raw = model.encode(texts[0], show_progress_bar=False)
            arrays = [raw]
        else:
            raw = model.encode(texts, show_progress_bar=False)
            arrays = list(raw)
        if len(arrays) != len(texts):
            raise ValueError("embedding model returned an incomplete batch")
        out: list[np.ndarray] = []
        for text, raw_vec in zip(texts, arrays):
            validated = self._validate_vector(raw_vec, expected_dim=self._expected_dim)
            if validated is None:
                raise ValueError(
                    "embedding model returned a non-finite or incompatible "
                    f"vector for text hash {_text_hash(text)[:12]}"
                )
            if self._expected_dim is None:
                self._expected_dim = int(validated.size)
            out.append(validated)
        return out

    def embed(self, text: str) -> np.ndarray:
        """Compute embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as numpy array.
        """
        cached = self._lookup_cached(text)
        if cached is not None:
            return cached

        embedding = self._encode_unique([text])[0]
        self._store(text, embedding)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Compute embeddings for a batch of texts.

        Checks cache first, only computes uncached embeddings.
        Repeated texts in the same batch are encoded once.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        results: list[np.ndarray | None] = [None] * len(texts)
        missing_order: list[str] = []
        missing_indices: dict[str, list[int]] = {}

        for i, text in enumerate(texts):
            cached = self._lookup_cached(text)
            if cached is not None:
                results[i] = cached
                continue
            if text not in missing_indices:
                missing_order.append(text)
                missing_indices[text] = []
            missing_indices[text].append(i)

        if missing_order:
            encoded = self._encode_unique(missing_order)
            for text, emb in zip(missing_order, encoded):
                self._store(text, emb)
                for idx in missing_indices[text]:
                    results[idx] = emb

        return results  # type: ignore[return-value]

    def similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts.

        Args:
            text_a: First text.
            text_b: Second text.

        Returns:
            Cosine similarity score (0.0 to 1.0).
        """
        emb_a = self.embed(text_a)
        emb_b = self.embed(text_b)
        dot = np.dot(emb_a, emb_b)
        norm = np.linalg.norm(emb_a) * np.linalg.norm(emb_b)
        if norm == 0:
            return 0.0
        return float(dot / norm)

    @property
    def cache_size(self) -> int:
        """Current cache size."""
        return self._cache.size

    @property
    def revision_pinned(self) -> bool:
        """True only when an explicit model revision key is set."""
        return self._revision is not None

    def clear_cache(self) -> None:
        """Clear the in-memory embedding cache (disk cache is left intact)."""
        with self._mem_lock:
            self._cache.clear()


# Module-level singleton
_embedding_service: EmbeddingService | None = None


def get_embedding_service(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> EmbeddingService:
    """Get the singleton EmbeddingService instance."""
    global _embedding_service
    if _embedding_service is None or _embedding_service._model_name != model_name:
        _embedding_service = EmbeddingService(model_name=model_name)
    return _embedding_service

"""Durable owner-scoped generation jobs with a bounded in-process worker.

Replaces request-blocking AJAX generation. Job records live in an additive
SQLite table created by this module (setup_db is not required). A held
per-database file lock chooses a single leader process: only that process
runs work or recovers abandoned jobs. Other Flask apps that merely open the
same DB (diagnostics, extra create_app calls) can read status but must not
execute or mark live work failed.

Work is a caller-supplied ``work(progress_callback) -> deck_id``. Cost
attribution, quotas, and builder construction belong in that callable so
this module stays a generic job runtime.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sabermetrics.errors import LLMCostCeilingExceeded

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed")
MAX_ACTIVE_JOBS = 1

STAGE_LABELS = {
    "queued": "Queued",
    "validate": "Validating commander",
    "profile": "Building commander profile",
    "filter": "Filtering legal cards",
    "score": "Scoring candidates",
    "template": "Deriving deck template",
    "infrastructure": "Filling infrastructure",
    "optimize": "Optimizing the 99",
    "review": "Reviewing risky picks",
    "narrative": "Writing the game plan",
    "persist": "Saving the deck",
    "completed": "Complete",
}

GENERIC_FAILURE = "Deck generation failed. You can retry from the commander page."
RESTART_FAILURE = (
    "The server restarted while this build was in progress. "
    "Unfinished work was not billed again. Please retry."
)
BUSY_MESSAGE = (
    "A deck is already being generated on this host. Please try again shortly."
)
OWNED_BUSY_MESSAGE = (
    "You already have a deck generating. Wait for it to finish or open its status page."
)

ProgressCallback = Callable[[str, int], None]
WorkFn = Callable[[ProgressCallback], str]


class JobUserError(Exception):
    """Failure whose message is safe to persist and show to the owner."""


class WorkerUnavailable(JobUserError):
    """This process cannot accept executable work."""


class JobConflict(Exception):
    """Another active job blocks submission."""

    def __init__(
        self,
        message: str,
        *,
        job: JobRecord | None = None,
        owned: bool = False,
    ) -> None:
        super().__init__(message)
        self.job = job
        self.owned = owned


@dataclass(frozen=True)
class JobRecord:
    """Owner-scoped generation job as stored in SQLite."""

    id: str
    owner_id: str
    status: str
    stage: str | None
    progress: int
    error: str | None
    deck_id: str | None
    fingerprint: str
    request_json: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def elapsed_seconds(self) -> float:
        start = self.started_at or self.created_at
        end = self.finished_at
        try:
            t0 = _parse_ts(start)
            t1 = _parse_ts(end) if end else datetime.now(UTC)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, round((t1 - t0).total_seconds(), 1))

    @property
    def stage_label(self) -> str:
        return label_for_stage(self.stage, status=self.status)

    def to_public_dict(self, *, deck_url: str | None = None) -> dict:
        """JSON-safe status payload: real stage/progress only, no secrets."""
        return {
            "job_id": self.id,
            "status": self.status,
            "stage": self.stage,
            "stage_label": self.stage_label,
            "progress": int(self.progress or 0),
            "elapsed_seconds": self.elapsed_seconds,
            "deck_id": self.deck_id,
            "deck_url": deck_url,
            "error": self.error,
            "updated_at": self.updated_at,
        }


def label_for_stage(stage: str | None, *, status: str | None = None) -> str:
    """Human-readable label for a real builder stage (never invented names)."""
    if status == "queued" and not stage:
        return STAGE_LABELS["queued"]
    if not stage:
        return "In progress" if status == "running" else STAGE_LABELS["queued"]
    if stage in STAGE_LABELS:
        return STAGE_LABELS[stage]
    return stage.replace("_", " ").strip().capitalize() or "In progress"


def request_fingerprint(
    owner_id: str,
    commander_id: str,
    budget_usd: float,
    power_target: int,
    strategy: str | None,
    user_intent: str | None,
    deck_name: str | None,
) -> str:
    """Stable hash of an owner's generate-deck submission."""
    payload = {
        "owner_id": owner_id,
        "commander_id": commander_id,
        "budget_usd": round(float(budget_usd), 2),
        "power_target": int(power_target),
        "strategy": strategy or "",
        "user_intent": user_intent or "",
        "deck_name": deck_name or "",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_error(exc: BaseException) -> str:
    """Persist a user-safe error; never exception, provider, or secret bodies."""
    if isinstance(exc, JobUserError):
        text = str(exc).strip()
        return text or GENERIC_FAILURE
    if isinstance(exc, LLMCostCeilingExceeded):
        return "Generation stopped: the monthly cost ceiling was reached mid-build."
    return GENERIC_FAILURE


def lock_path_for(db_path: Path) -> Path:
    """Per-database leader lock file (held for the life of the worker)."""
    path = Path(db_path)
    return path.with_name(path.name + ".generation_jobs.lock")


def should_start_worker(config: Mapping | None = None) -> bool:
    """Whether create_app should attempt to become leader and run work.

    Tests must opt in. Pytest is detected even when TESTING is set after
    ``create_app`` returns. Production Waitress calls create_app without
    those flags, so the live process starts the worker.
    """
    cfg = config or {}
    explicit = cfg.get("GENERATION_JOBS_ENABLE_WORKER")
    if explicit is True:
        return True
    if explicit is False:
        return False
    if cfg.get("TESTING"):
        return False
    env = os.environ.get("SABER_JOBS_WORKER", "").strip().lower()
    if env in {"0", "false", "no", "off"}:
        return False
    return not os.environ.get("PYTEST_CURRENT_TEST")


def ensure_schema(db_path: Path) -> None:
    """Idempotently create the additive generation_jobs table."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS generation_jobs (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                deck_id TEXT,
                fingerprint TEXT NOT NULL,
                request_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_generation_jobs_status
                ON generation_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_generation_jobs_owner
                ON generation_jobs(owner_id);
            CREATE INDEX IF NOT EXISTS idx_generation_jobs_fingerprint
                ON generation_jobs(owner_id, fingerprint, status);
            """)
        conn.commit()
    finally:
        conn.close()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _row_to_job(row: sqlite3.Row | None) -> JobRecord | None:
    if row is None:
        return None
    return JobRecord(
        id=row["id"],
        owner_id=row["owner_id"],
        status=row["status"],
        stage=row["stage"],
        progress=int(row["progress"] or 0),
        error=row["error"],
        deck_id=row["deck_id"],
        fingerprint=row["fingerprint"],
        request_json=row["request_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


class JobManager:
    """SQLite-backed job store plus optional single-threaded worker.

    ``enable_worker=True`` tries to acquire the per-DB file lock. Failure
    means another live process already leads; this instance stays read/write
    for enqueue + status but will not recover orphans or run work.
    """

    def __init__(self, db_path: Path, *, enable_worker: bool = False) -> None:
        self.db_path = Path(db_path)
        self._worker_requested = enable_worker
        self._mutex = threading.Lock()
        self._work: dict[str, WorkFn] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._leader_fh = None
        self._is_leader = False
        if self.db_path.exists() or enable_worker:
            ensure_schema(self.db_path)
        if enable_worker:
            self.ensure_leader_worker()

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def lock_path(self) -> Path:
        return lock_path_for(self.db_path)

    def ensure_leader_worker(self) -> bool:
        """Become leader if the lock is free, recover orphans, start worker."""
        if self._is_leader and self._worker_thread and self._worker_thread.is_alive():
            return True
        if not self.try_become_leader():
            logger.info(
                "generation jobs follower for %s (leader lock held elsewhere)",
                self.db_path,
            )
            return False
        self.recover_orphans()
        self._start_worker_thread()
        return True

    def try_become_leader(self) -> bool:
        """Non-blocking exclusive lock. Held until shutdown or process exit."""
        if self._is_leader:
            return True
        try:
            import fcntl
        except ImportError:
            logger.warning("fcntl unavailable; generation job leader lock disabled")
            return False
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Must stay open: flock is released when the fd closes.
        fh = open(self.lock_path, "a+b")  # noqa: SIM115
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        except OSError:
            fh.close()
            logger.exception("generation job leader lock failed")
            return False
        self._leader_fh = fh
        self._is_leader = True
        logger.info("generation jobs leader for %s", self.db_path)
        return True

    def recover_orphans(self) -> int:
        """Fail queued/running jobs left by a dead leader. Leader-only."""
        if not self._is_leader:
            return 0
        if not self.db_path.exists():
            return 0
        ensure_schema(self.db_path)
        now = _now()
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE generation_jobs "
                "SET status = 'failed', error = ?, updated_at = ?, "
                "finished_at = COALESCE(finished_at, ?) "
                "WHERE status IN ('queued', 'running')",
                (RESTART_FAILURE, now, now),
            )
            conn.commit()
            n = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()
        if n:
            logger.info("marked %s abandoned generation job(s) failed", n)
        with self._mutex:
            self._work.clear()
        return n

    def submit(
        self,
        *,
        owner_id: str,
        fingerprint: str,
        request_payload: dict,
        work: WorkFn,
    ) -> JobRecord:
        """Enqueue work or return the in-flight duplicate. Atomic vs peers."""
        if self._stop.is_set() or (self._worker_requested and not self.is_leader):
            raise WorkerUnavailable(
                "Generation worker is unavailable. Please retry shortly."
            )
        ensure_schema(self.db_path)
        now = _now()
        job_id = uuid.uuid4().hex
        payload = json.dumps(request_payload, sort_keys=True, default=str)
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            active = [
                _row_to_job(r)
                for r in conn.execute(
                    "SELECT * FROM generation_jobs WHERE status IN ('queued', 'running') "
                    "ORDER BY created_at ASC"
                ).fetchall()
            ]
            duplicate = next(
                (
                    j
                    for j in active
                    if j and j.owner_id == owner_id and j.fingerprint == fingerprint
                ),
                None,
            )
            if duplicate is not None:
                conn.commit()
                return duplicate
            if active:
                blocker = active[0]
                conn.commit()
                owned = bool(blocker and blocker.owner_id == owner_id)
                raise JobConflict(
                    OWNED_BUSY_MESSAGE if owned else BUSY_MESSAGE,
                    job=blocker if owned else None,
                    owned=owned,
                )
            if len(active) >= MAX_ACTIVE_JOBS:
                conn.commit()
                raise JobConflict(BUSY_MESSAGE)
            conn.execute(
                "INSERT INTO generation_jobs ("
                "id, owner_id, status, stage, progress, error, deck_id, "
                "fingerprint, request_json, created_at, updated_at, "
                "started_at, finished_at"
                ") VALUES (?, ?, 'queued', NULL, 0, NULL, NULL, ?, ?, ?, ?, NULL, NULL)",
                (job_id, owner_id, fingerprint, payload, now, now),
            )
            # Publish the callable before making its queued row visible.
            with self._mutex:
                self._work[job_id] = work
            conn.commit()
        except JobConflict:
            raise
        except sqlite3.Error:
            conn.rollback()
            with self._mutex:
                self._work.pop(job_id, None)
            raise
        finally:
            conn.close()
        self._wake.set()
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> JobRecord | None:
        if not self.db_path.exists():
            return None
        conn = _connect(self.db_path)
        try:
            try:
                row = conn.execute(
                    "SELECT * FROM generation_jobs WHERE id = ?", (job_id,)
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            return _row_to_job(row)
        finally:
            conn.close()

    def execute_job(self, job_id: str) -> JobRecord:
        """Run one queued job on this thread. Deterministic test hook."""
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        self._run_claimed(job_id)
        done = self.get(job_id)
        assert done is not None
        return done

    def shutdown(self) -> None:
        """Stop the worker and release the leader lock."""
        self._stop.set()
        self._wake.set()
        thread = self._worker_thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)
        if thread is not None and thread.is_alive():
            # Keep ownership until the in-flight callable actually finishes.
            return
        self._release_leader()

    def _release_leader(self) -> None:
        self._worker_thread = None
        fh = self._leader_fh
        self._leader_fh = None
        self._is_leader = False
        if fh is not None:
            try:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            try:
                fh.close()
            except OSError:
                pass

    def _start_worker_thread(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="generation-jobs",
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        try:
            while not self._stop.is_set():
                job_id = self._claim_next()
                if job_id:
                    try:
                        self._run_claimed(job_id)
                    except Exception as exc:  # noqa: BLE001 - isolate jobs without logging provider payloads
                        logger.error(
                            "generation worker failed on job %s (%s)",
                            job_id,
                            type(exc).__name__,
                        )
                    continue
                self._wake.wait(timeout=1.0)
                self._wake.clear()
        finally:
            self._release_leader()

    def _claim_next(self) -> str | None:
        if not self._is_leader or self._stop.is_set():
            return None
        if not self.db_path.exists():
            return None
        now = _now()
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM generation_jobs WHERE status = 'queued' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            job_id = row["id"]
            conn.execute(
                "UPDATE generation_jobs SET status = 'running', started_at = ?, "
                "updated_at = ? WHERE id = ? AND status = 'queued'",
                (now, now, job_id),
            )
            conn.commit()
            return job_id
        except sqlite3.Error:
            conn.rollback()
            logger.exception("failed to claim generation job")
            return None
        finally:
            conn.close()

    def _run_claimed(self, job_id: str) -> None:
        now = _now()
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM generation_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                conn.commit()
                return
            if row["status"] == "queued":
                conn.execute(
                    "UPDATE generation_jobs SET status = 'running', "
                    "started_at = COALESCE(started_at, ?), updated_at = ? "
                    "WHERE id = ?",
                    (now, now, job_id),
                )
            elif row["status"] != "running":
                conn.commit()
                return
            else:
                conn.execute(
                    "UPDATE generation_jobs SET updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

        with self._mutex:
            work = self._work.get(job_id)
        if work is None:
            self._finish_failed(job_id, RESTART_FAILURE)
            return

        def progress_callback(stage: str, progress: int) -> None:
            self._record_progress(job_id, stage, progress)

        try:
            deck_id = work(progress_callback)
        except Exception as exc:  # noqa: BLE001 - isolate jobs without logging provider payloads
            logger.error("generation job %s failed (%s)", job_id, type(exc).__name__)
            self._finish_failed(job_id, safe_error(exc))
            return
        if not deck_id:
            self._finish_failed(job_id, GENERIC_FAILURE)
            return
        self._finish_completed(job_id, str(deck_id))

    def _record_progress(self, job_id: str, stage: str, progress: int) -> None:
        """Store builder-emitted stage/progress. Does not mark the job complete."""
        label = str(stage or "").strip() or None
        try:
            pct = int(progress)
        except (TypeError, ValueError):
            pct = 0
        pct = max(0, min(100, pct))
        now = _now()
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "UPDATE generation_jobs SET stage = ?, progress = ?, updated_at = ? "
                "WHERE id = ? AND status = 'running'",
                (label, pct, now, job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _finish_completed(self, job_id: str, deck_id: str) -> None:
        now = _now()
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "UPDATE generation_jobs SET status = 'completed', stage = 'completed', "
                "progress = 100, deck_id = ?, error = NULL, updated_at = ?, "
                "finished_at = ? WHERE id = ?",
                (deck_id, now, now, job_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self._mutex:
            self._work.pop(job_id, None)

    def _finish_failed(self, job_id: str, message: str) -> None:
        now = _now()
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "UPDATE generation_jobs SET status = 'failed', error = ?, "
                "updated_at = ?, finished_at = ? WHERE id = ?",
                (message, now, now, job_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self._mutex:
            self._work.pop(job_id, None)


def attach_to_app(app) -> JobManager:
    """Create a JobManager on ``app.extensions`` and optionally start the worker."""
    db_path = Path(app.config["DB_PATH"])
    enable = should_start_worker(app.config)
    manager = JobManager(db_path, enable_worker=enable)
    app.extensions["generation_jobs"] = manager
    return manager

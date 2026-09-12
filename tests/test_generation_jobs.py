"""Unit tests for durable generation jobs (leader lock, restart, progress)."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sabermetrics.errors import LLMCostCeilingExceeded
from sabermetrics.generation_jobs import (
    GENERIC_FAILURE,
    RESTART_FAILURE,
    JobConflict,
    JobManager,
    JobUserError,
    ensure_schema,
    lock_path_for,
    request_fingerprint,
    safe_error,
    should_start_worker,
)
from scripts.setup_db import setup_database

LOCK_HOLDER = r"""
import fcntl
import sys
import time

path = sys.argv[1]
fh = open(path, "a+b")
fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
sys.stdout.write("LOCKED\n")
sys.stdout.flush()
time.sleep(60)
"""


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "jobs.db"
    setup_database(path)
    return path


@pytest.fixture
def manager(db_path):
    mgr = JobManager(db_path, enable_worker=False)
    yield mgr
    mgr.shutdown()


def _work_ok(progress_callback):
    progress_callback("validate", 5)
    progress_callback("optimize", 70)
    progress_callback("persist", 95)
    return "deck-ok"


def _work_boom(progress_callback):
    progress_callback("profile", 20)
    raise RuntimeError('hf_secret_token provider body {"choices":[]}')


def test_fingerprint_is_stable() -> None:
    a = request_fingerprint("u", "cmd", 200.0, 3, None, None, None)
    b = request_fingerprint("u", "cmd", 200, 3, "", "", "")
    assert a == b
    assert a != request_fingerprint("u", "cmd", 201, 3, None, None, None)


def test_safe_error_strips_provider_and_secrets() -> None:
    leaked = RuntimeError('hf_secret_token provider body {"choices":[]}')
    msg = safe_error(leaked)
    assert msg == GENERIC_FAILURE
    assert "hf_secret" not in msg
    assert "choices" not in msg
    assert "provider" not in msg
    assert safe_error(JobUserError("Monthly limit reached (1/1 decks).")) == (
        "Monthly limit reached (1/1 decks)."
    )
    assert "ceiling" in safe_error(LLMCostCeilingExceeded("spent 99")).lower()


def test_should_not_start_worker_under_pytest() -> None:
    assert should_start_worker({}) is False
    assert should_start_worker({"TESTING": True}) is False
    assert should_start_worker({"GENERATION_JOBS_ENABLE_WORKER": True}) is True
    assert should_start_worker({"GENERATION_JOBS_ENABLE_WORKER": False}) is False


def test_submit_and_execute_records_real_progress(manager) -> None:
    job = manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_ok,
    )
    assert job.status == "queued"
    assert job.progress == 0
    done = manager.execute_job(job.id)
    assert done.status == "completed"
    assert done.deck_id == "deck-ok"
    assert done.stage == "completed"
    assert done.progress == 100
    public = done.to_public_dict(deck_url="/deck/deck-ok")
    assert public["deck_url"] == "/deck/deck-ok"
    assert "request_json" not in public
    assert "owner_id" not in public
    assert "fingerprint" not in public


def test_duplicate_submit_returns_same_job(manager) -> None:
    first = manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_ok,
    )
    second = manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_boom,
    )
    assert first.id == second.id
    done = manager.execute_job(first.id)
    assert done.status == "completed"
    assert done.deck_id == "deck-ok"


def test_second_distinct_job_is_rejected(manager) -> None:
    manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_ok,
    )
    with pytest.raises(JobConflict) as exc:
        manager.submit(
            owner_id="owner-b",
            fingerprint="fp-b",
            request_payload={"commander_id": "other"},
            work=_work_ok,
        )
    assert exc.value.owned is False
    assert exc.value.job is None


def test_failed_job_sanitizes_error_and_allows_retry(manager) -> None:
    job = manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_boom,
    )
    done = manager.execute_job(job.id)
    assert done.status == "failed"
    assert done.error == GENERIC_FAILURE
    assert "hf_secret" not in (done.error or "")
    retry = manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_ok,
    )
    assert retry.id != job.id
    assert manager.execute_job(retry.id).status == "completed"


def test_leader_recover_marks_abandoned_and_does_not_rerun(manager, db_path) -> None:
    calls = []

    def work(progress_callback):
        calls.append("ran")
        return "deck-x"

    job = manager.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=work,
    )
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE generation_jobs SET status = 'running', started_at = created_at "
        "WHERE id = ?",
        (job.id,),
    )
    conn.commit()
    conn.close()

    assert manager.try_become_leader() is True
    n = manager.recover_orphans()
    assert n == 1
    abandoned = manager.get(job.id)
    assert abandoned is not None
    assert abandoned.status == "failed"
    assert abandoned.error == RESTART_FAILURE
    again = manager.execute_job(job.id)
    assert again.status == "failed"
    assert calls == []


def test_follower_does_not_recover_live_job(db_path) -> None:
    """Another process holding the lock must not look like a restart."""
    owner = JobManager(db_path, enable_worker=False)
    job = owner.submit(
        owner_id="owner-a",
        fingerprint="fp-a",
        request_payload={"commander_id": "cmd"},
        work=_work_ok,
    )
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE generation_jobs SET status = 'running', started_at = created_at "
        "WHERE id = ?",
        (job.id,),
    )
    conn.commit()
    conn.close()

    lock_path = lock_path_for(db_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", LOCK_HOLDER, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert "LOCKED" in line
        follower = JobManager(db_path, enable_worker=True)
        try:
            assert follower.is_leader is False
            assert follower.recover_orphans() == 0
            live = follower.get(job.id)
            assert live is not None
            assert live.status == "running"
        finally:
            follower.shutdown()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    leader = JobManager(db_path, enable_worker=True)
    try:
        assert leader.is_leader is True
        assert leader.get(job.id).status == "failed"
        assert leader.get(job.id).error == RESTART_FAILURE
    finally:
        leader.shutdown()
        owner.shutdown()


def test_worker_thread_runs_queued_job(db_path) -> None:
    mgr = JobManager(db_path, enable_worker=True)
    try:
        assert mgr.is_leader is True
        job = mgr.submit(
            owner_id="owner-a",
            fingerprint="fp-a",
            request_payload={"commander_id": "cmd"},
            work=_work_ok,
        )
        deadline = time.time() + 5
        done = mgr.get(job.id)
        while (
            done
            and done.status not in ("completed", "failed")
            and time.time() < deadline
        ):
            time.sleep(0.05)
            done = mgr.get(job.id)
        assert done is not None
        assert done.status == "completed"
        assert done.deck_id == "deck-ok"
    finally:
        mgr.shutdown()


def test_ensure_schema_is_idempotent(db_path) -> None:
    ensure_schema(db_path)
    ensure_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='generation_jobs'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_callable_exists_when_queued_transaction_becomes_visible(manager, monkeypatch):
    import sabermetrics.generation_jobs as jobs

    original = jobs._connect
    calls = []

    class Connection:
        def __init__(self, path):
            self.inner = original(path)
            self.job_id = None

        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO generation_jobs"):
                self.job_id = params[0]
            return self.inner.execute(sql, params)

        def commit(self):
            self.inner.commit()
            if self.job_id:
                job_id, self.job_id = self.job_id, None
                # Force the worker to see the row immediately after commit.
                manager.execute_job(job_id)

        def __getattr__(self, key):
            return getattr(self.inner, key)

    monkeypatch.setattr(jobs, "_connect", Connection)
    job = manager.submit(
        owner_id="u",
        fingerprint="fp",
        request_payload={},
        work=lambda progress: calls.append("executed") or "deck",
    )
    assert job.status == "completed"
    assert calls == ["executed"]


def test_draining_worker_keeps_leader_lock_until_work_finishes(db_path):
    import threading

    from sabermetrics.generation_jobs import WorkerUnavailable

    started, finish = threading.Event(), threading.Event()
    leader = JobManager(db_path, enable_worker=True)
    follower = None

    def work(progress):
        started.set()
        assert finish.wait(10)
        return "deck"

    try:
        job = leader.submit(
            owner_id="u", fingerprint="fp", request_payload={}, work=work
        )
        assert started.wait(3)
        leader.shutdown()
        follower = JobManager(db_path, enable_worker=True)
        assert not follower.is_leader
        assert follower.get(job.id).status == "running"
        with pytest.raises(WorkerUnavailable):
            follower.submit(
                owner_id="u", fingerprint="other", request_payload={}, work=_work_ok
            )
        finish.set()
        deadline = time.monotonic() + 3
        while leader.get(job.id).status == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert leader.get(job.id).status == "completed"
    finally:
        finish.set()
        leader.shutdown()
        if follower:
            follower.shutdown()


def test_failed_work_does_not_log_exception_payload(manager, caplog):
    job = manager.submit(
        owner_id="u", fingerprint="fp", request_payload={}, work=_work_boom
    )
    assert manager.execute_job(job.id).status == "failed"
    assert "hf_secret_token" not in caplog.text
    assert "choices" not in caplog.text

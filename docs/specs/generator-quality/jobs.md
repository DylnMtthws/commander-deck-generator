# Package 4 — durable jobs and truthful UI

Own new generation_jobs module, ui/routes.py, ui/app.py, profile_view.html,
deck_view.html and new job/UI tests. Do not edit builder, setup_db or server.py;
new module may idempotently create its own additive jobs table. Consume the shared
builder callback and rationale quality_warnings contract in README.md.

Replace request-blocking AJAX generation with a bounded in-process worker and
SQLite job records (no Redis/service). POST returns 202 + job ID/status URL quickly;
status endpoint exposes only real stage/progress. Capture user/request values
before leaving request context. Recreate cost attribution INSIDE worker. Persist
queued/running/completed/failed state, safe errors, time and deck ID. On process
restart mark abandoned jobs failed with a helpful retry message, don't automatically
repeat expensive work. Enforce one active generator job (small shared host), reject
or return same active job on duplicate submission, atomically. Check costs/quotas
at execution too. Thread-safe SQLite connections and bounded queue; never leak
secrets or exception/provider bodies in status errors. Avoid a worker in tests
unless explicitly exercised; provide deterministic test hooks.

Owner login, CSRF, authorization and quotas remain required; other sessions cannot
read another owner's job. Polling must not trigger work or spend. Preserve a usable
non-JS response and existing endpoints where possible. UI displays real stage text,
elapsed time, completion redirect and safe failure/retry behavior. Handle HTTP/network
errors, reload/resume and terminal-state polling stop. No timer-based pretend stage
names or advancing percentages. Display final quality warnings and unavailable
signals; older decks without new fields must render.

Tests: prompt 202, deduplicated double POST, owner isolation, missing/expired auth,
CSRF, success/failure/restart, worker cost attribution, no duplicate cost on polls,
visible warnings and removal of fake progress. Keep changes focused and accessible.

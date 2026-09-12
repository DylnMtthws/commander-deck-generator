# Hosting the generator

The public hostname is `generate.decklab.studio`. The service uses a separate
container, SQLite database, owner allowlist, session signing key, and model
credential. It does not share writable data or login cookies with Deck Lab.

Build the Dockerfile with `SABER_BUILD_SHA` set to the exact source revision.
Mount a generator-only volume at `/data`; initialize it using
`python scripts/setup_db.py --db-path /data/sabermetrics.db` and load a public
card/price corpus. Provision only the intended admin account. Supply
`SABER_OWNER_EMAIL`, a strong `SABER_SECRET_KEY`, `SABER_COOKIE_SECURE=1`, and
`DEEPSEEK_API_KEY` through a private environment file.

The container entry point refuses startup without an owner email or a stable
secret of at least 32 characters. Its port 8080 belongs behind an HTTPS reverse
proxy, not directly on the public internet. Forwarded headers are trusted for
one proxy hop. `/healthz` checks database access and reports the build revision.

The current deployment adds a host-specific reverse-proxy route to the existing
Caddy gateway. Preserve the apex, www, and QA routes; validate the new config
before a graceful reload. Never recreate Deck Lab's app to deploy this service.
Bound generator CPU/memory to protect the other workloads on the same host.

Back up the generator database using SQLite's online backup API. Treat its
model cache as disposable. Restore only into the generator's own data directory;
Deck Lab production/QA paths are never valid restore targets.

Historical deployment documents elsewhere in this restored tree describe the
original private/local deployment and are retained as development history.

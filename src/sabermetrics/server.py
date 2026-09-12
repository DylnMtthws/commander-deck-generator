"""Container entry point; refuse public serving without an explicit owner."""

import logging
import os
from pathlib import Path

from waitress import serve

from sabermetrics.runtime import apply_schema_migrations, assert_readiness
from sabermetrics.ui.app import create_app


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if not os.environ.get("SABER_OWNER_EMAIL", "").strip():
        raise RuntimeError("SABER_OWNER_EMAIL is required")
    if len(os.environ.get("SABER_SECRET_KEY", "")) < 32:
        raise RuntimeError(
            "A stable SABER_SECRET_KEY of at least 32 characters is required"
        )
    # Required config must be present before serving. Schema migrations are
    # additive and do not fetch external sources or reseed user data.
    assert_readiness(db_path=None)
    db_path = Path(os.environ.get("SABER_DB_PATH", "/data/sabermetrics.db"))
    apply_schema_migrations(db_path)
    assert_readiness(db_path)
    app = create_app(db_path)
    serve(app, host="0.0.0.0", port=8080, threads=4)


if __name__ == "__main__":
    main()

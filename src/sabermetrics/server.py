"""Container entry point; refuse public serving without an explicit owner."""

import os
from pathlib import Path

from waitress import serve

from sabermetrics.ui.app import create_app


def main():
    if not os.environ.get("SABER_OWNER_EMAIL", "").strip():
        raise RuntimeError("SABER_OWNER_EMAIL is required")
    if len(os.environ.get("SABER_SECRET_KEY", "")) < 32:
        raise RuntimeError(
            "A stable SABER_SECRET_KEY of at least 32 characters is required"
        )
    app = create_app(Path(os.environ.get("SABER_DB_PATH", "/data/sabermetrics.db")))
    serve(app, host="0.0.0.0", port=8080, threads=4)


if __name__ == "__main__":
    main()

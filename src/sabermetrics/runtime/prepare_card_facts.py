"""Publish an immutable public-card facts snapshot, separate from user data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from sabermetrics.intelligence.cards import VERSION, fact_key, facts_for


def prepare(db: Path, output: Path) -> dict:
    """Read only the cards table; atomically publish versioned compiled facts."""
    if db.resolve() == output.resolve():
        raise ValueError("snapshot must be separate from application database")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT name,oracle_text,type_line FROM cards ORDER BY oracle_id,id"
        ).fetchall()
    entries = {}
    for name, text, types in rows:
        card = {"name": name, "oracle_text": text, "type_line": types}
        entries[fact_key(card)] = facts_for(card).model_dump()
    payload = {"version": VERSION, "entries": entries}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as f:
        temporary = Path(f.name)
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "public_rows": len(rows),
        "compiled_shapes": len(entries),
        "version": VERSION,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.db.resolve() == args.output.resolve():
        parser.error("snapshot must be separate from application database")
    print(json.dumps(prepare(args.db, args.output)))


if __name__ == "__main__":
    main()

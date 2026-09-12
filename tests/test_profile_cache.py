"""Profile cache round-trips for real commanders (follow-up to criterion 4).

The finding in criterion 4 was that every real build pays for Sonnet profile
synthesis. Investigation showed the *cache mechanism is correct* — the reason
was simply that no real profile had ever been stored (the seed rows in
commander_profiles use synthetic UUIDs that match no card). This test locks in
the correct behavior: once a profile is stored under a real commander_id, the
next build hits the cache for free (no API call). Cached rows must also carry
canonical name and set metadata; invented identity is not reused.
"""

import sqlite3
from pathlib import Path

import pytest

from sabermetrics.models.profile import CommanderProfile

DB = Path("data/sabermetrics.db")


@pytest.mark.skipif(not DB.exists(), reason="needs card DB")
def test_profile_cache_round_trips_for_real_commander(build_db, canned_profile) -> None:
    from sabermetrics.reasoning.profiler import ProfileManager, ProfileRequest

    row = sqlite3.connect(str(build_db)).execute(
        "SELECT id, name, set_code FROM cards WHERE is_legal_commander = 1 LIMIT 1"
    ).fetchone()
    cid, name, set_code = row[0], row[1], row[2]

    mgr = ProfileManager(build_db)
    # No real profile cached yet (the seed rows are orphaned fake UUIDs).
    assert mgr._get_cached_profile(cid, None) is None

    stored = canned_profile(cid, ["G"]).profile
    payload = stored.model_dump()
    payload["commander_name"] = name
    payload["set_version"] = set_code
    profile = CommanderProfile(**payload)
    mgr._store_profile(profile, None, None)

    # Now it hits — direct lookup and the full generate_profile path.
    got = mgr._get_cached_profile(cid, None)
    assert got is not None and got.commander_id == cid
    assert got.commander_name == name
    assert got.set_version == set_code

    result = mgr.generate_profile(ProfileRequest(commander_id=cid))
    assert result.cache_hit is True
    assert result.generation_cost_usd == 0.0  # no API call on a hit

    # A different commander still misses (cache is keyed correctly).
    assert mgr._get_cached_profile("no-such-commander", None) is None

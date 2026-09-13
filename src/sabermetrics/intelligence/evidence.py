"""Bounded acquisition of public EDHREC selection evidence.

Evidence is descriptive only: observed inclusion rates and EDHREC's own
synergy figure for a commander cohort. Nothing here is a win rate, and
nothing here is causal. A missing, mismatched or unparsable page yields an
explicit ``unavailable`` result rather than a silent substitution, so the
caller can never mistake absent evidence for weak evidence.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

VERSION = "selection-evidence.v1"
BASE_URL = "https://json.edhrec.com/pages/commanders"
USER_AGENT = "sabermetrics-selection-evidence/1 (+public-json)"

FRESH_DAYS = 7
TIMEOUT_SECONDS = 30.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_ATTEMPTS = 2  # one bounded retry, transport failures only

# Average-deck composition counts published at the top level of the page.
COMPOSITION_KEYS = (
    "creature",
    "instant",
    "sorcery",
    "artifact",
    "enchantment",
    "battle",
    "planeswalker",
    "land",
    "basic",
    "nonbasic",
)
MAX_COMPOSITION_COUNT = 100.0

# Recommendation lists that do not describe cards a deck may contain.
# Whole words only, so "Planeswalkers" is kept while "Planes" is not.
IGNORED_LIST_RE = re.compile(
    r"\b(tokens?|emblems?|dungeons?|schemes?|planes|phenomena|attractions?"
    r"|stickers?|contraptions?|related)\b"
)

Status = Literal["available", "unavailable", "stale"]
Cohort = Literal["general", "cedh"]


class SelectionEvidence(BaseModel):
    """Observed public deck-population evidence for one commander cohort."""

    version: str = VERSION
    status: Status
    source_url: str | None = None
    commander_name: str
    cohort: Cohort
    retrieved_at: datetime | None = None
    sample_size: int = 0
    inclusion: dict[str, float] = Field(default_factory=dict)
    synergy: dict[str, float] = Field(default_factory=dict)
    composition: dict[str, float] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        """True when rates may be consulted at all (stale included)."""
        return self.status in ("available", "stale") and self.sample_size > 0


@dataclass(frozen=True)
class HttpResponse:
    """Minimal response shape so tests can supply a fake transport."""

    status_code: int
    content: bytes


class FetchError(Exception):
    """Transport-level failure; retryable once."""


Fetcher = Callable[[str], HttpResponse]


def cohort_for_power(power: int) -> Cohort:
    """Power 5 reads the cEDH cohort; everything else reads the general one."""
    try:
        return "cedh" if int(power) >= 5 else "general"
    except (TypeError, ValueError):
        return "general"


def commander_slug(name: str) -> str:
    """EDHREC URL slug for a card name.

    Apostrophes, commas and periods are dropped rather than separated
    ("Kenrith's Transformation" -> "kenriths-transformation"), accents are
    folded, and only the front face of a split card is used.
    """
    front = str(name).split(" // ")[0]
    folded = unicodedata.normalize("NFKD", front)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.replace("’", "'").replace("‘", "'")
    slug = folded.lower()
    slug = re.sub(r"[',.]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def source_url_for(slug: str, cohort: Cohort) -> str:
    if cohort == "cedh":
        return f"{BASE_URL}/{slug}/cedh.json"
    return f"{BASE_URL}/{slug}.json"


def httpx_fetch(url: str) -> HttpResponse:
    """Default transport: bounded time, bounded body, no credentials."""
    import httpx

    try:
        with httpx.stream(
            "GET",
            url,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as resp:
            if resp.status_code != 200:
                return HttpResponse(resp.status_code, b"")
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise FetchError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
                chunks.append(chunk)
            return HttpResponse(200, b"".join(chunks))
    except FetchError:
        raise
    except Exception as exc:  # httpx transport/protocol errors
        raise FetchError(str(exc)) from exc


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _header_identity(payload: dict[str, Any]) -> tuple[str, bool]:
    """Return (commander name as published, page is the cEDH cohort)."""
    header = payload.get("header") or payload.get("title") or ""
    if not isinstance(header, str):
        return "", False
    is_cedh = "cedh" in header.lower()
    name = re.sub(r"\s*[-–]\s*cedh\s*$", "", header, flags=re.IGNORECASE)
    name = re.sub(r"\s*\((commander|edh)\)\s*$", "", name, flags=re.IGNORECASE)
    return name.strip(), is_cedh


def _ignored_list(cardlist: dict[str, Any]) -> bool:
    label = f"{cardlist.get('tag', '')} {cardlist.get('header', '')}".lower()
    return bool(IGNORED_LIST_RE.search(label))


def _card_rate(view: dict[str, Any], sample_size: int) -> float | None:
    """Inclusion rate for one cardview, or None when not trustworthy."""
    num = _finite(view.get("num_decks"))
    potential = _finite(view.get("potential_decks"))
    if num is not None and potential is not None and potential > 0:
        if num < 0 or potential > sample_size:
            return None
        rate = num / potential
        return rate if 0.0 <= rate <= 1.0 else None
    # Older payloads expose a percentage instead of the two counts.
    percent = _finite(view.get("inclusion"))
    if percent is None:
        return None
    rate = percent / 100.0
    return rate if 0.0 <= rate <= 1.0 else None


def _sample_size(cardlists: list[dict[str, Any]]) -> int:
    largest = 0
    for cardlist in cardlists:
        if _ignored_list(cardlist):
            continue
        for view in cardlist.get("cardviews") or []:
            if not isinstance(view, dict):
                continue
            potential = _finite(view.get("potential_decks"))
            if potential is not None and potential > largest:
                largest = int(potential)
    return largest


class ParseError(Exception):
    """Payload is present but cannot be trusted for this commander/cohort."""


def parse_payload(
    payload: Any,
    commander_name: str,
    cohort: Cohort,
) -> tuple[int, dict[str, float], dict[str, float], dict[str, float], list[str]]:
    """Validate a public EDHREC payload and extract observed rates.

    Raises:
        ParseError: shape, identity, cohort or sample size is unusable.
    """
    if not isinstance(payload, dict):
        raise ParseError("payload is not a JSON object")

    published_name, page_is_cedh = _header_identity(payload)
    wanted = commander_slug(commander_name)
    if not published_name or commander_slug(published_name) != wanted:
        raise ParseError(
            f"page identifies '{published_name or '?'}', expected '{commander_name}'"
        )
    if page_is_cedh != (cohort == "cedh"):
        served = "cedh" if page_is_cedh else "general"
        raise ParseError(f"requested {cohort} cohort but page serves {served}")

    container = payload.get("container")
    json_dict = container.get("json_dict") if isinstance(container, dict) else None
    cardlists = json_dict.get("cardlists") if isinstance(json_dict, dict) else None
    if not isinstance(cardlists, list) or not cardlists:
        raise ParseError("no container.json_dict.cardlists in payload")
    cardlists = [c for c in cardlists if isinstance(c, dict)]

    sample_size = _sample_size(cardlists)
    if sample_size <= 0:
        raise ParseError("no positive potential_decks sample in payload")

    inclusion: dict[str, float] = {}
    synergy: dict[str, float] = {}
    dropped = 0
    ignored_lists = 0

    for cardlist in cardlists:
        if _ignored_list(cardlist):
            ignored_lists += 1
            continue
        for view in cardlist.get("cardviews") or []:
            if not isinstance(view, dict):
                dropped += 1
                continue
            name = view.get("name")
            if not isinstance(name, str) or not name.strip():
                dropped += 1
                continue
            name = name.strip()
            if commander_slug(name) == wanted:
                continue  # the commander is not a recommendation
            rate = _card_rate(view, sample_size)
            if rate is None:
                dropped += 1
                continue
            # A card may appear in several lists; keep one rate, never a sum.
            if rate <= inclusion.get(name, -1.0):
                continue
            inclusion[name] = rate
            synergy.pop(name, None)
            value = _finite(view.get("synergy"))
            if value is not None and -1.0 <= value <= 1.0:
                synergy[name] = value

    if not inclusion:
        raise ParseError("no usable inclusion rates in payload")

    composition: dict[str, float] = {}
    for key in COMPOSITION_KEYS:
        value = _finite(payload.get(key))
        if value is not None and 0.0 <= value <= MAX_COMPOSITION_COUNT:
            composition[key] = value

    limitations = [
        "observed inclusion rates only; no win rate or causal effect is implied",
        f"edhrec {cohort} cohort, {sample_size} decks, {len(inclusion)} cards",
    ]
    if dropped:
        limitations.append(f"{dropped} recommendation entries failed validation")
    if ignored_lists:
        limitations.append(f"{ignored_lists} non-deck recommendation lists ignored")
    if not composition:
        limitations.append("no average-deck composition published")

    return sample_size, inclusion, synergy, composition, limitations


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def cache_path(cache_dir: Path, slug: str, cohort: Cohort) -> Path:
    return Path(cache_dir) / VERSION / f"{slug}__{cohort}.json"


def _read_cache(path: Path, slug: str, cohort: Cohort) -> tuple[Any, datetime] | None:
    """Return (payload, retrieved_at) from a valid cache entry, else None."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("version") != VERSION:
        return None
    if record.get("slug") != slug or record.get("cohort") != cohort:
        return None
    try:
        retrieved_at = datetime.fromisoformat(str(record.get("retrieved_at")))
    except ValueError:
        return None
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=UTC)
    if "payload" not in record:
        return None
    return record["payload"], retrieved_at


def _write_cache(
    path: Path,
    slug: str,
    cohort: Cohort,
    commander_name: str,
    url: str,
    payload: Any,
    retrieved_at: datetime,
) -> None:
    """Atomically replace the cache entry; a failure leaves the old one intact."""
    record = {
        "version": VERSION,
        "slug": slug,
        "cohort": cohort,
        "commander_name": commander_name,
        "source_url": url,
        "retrieved_at": retrieved_at.isoformat(),
        "payload": payload,
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("could not cache selection evidence for %s: %s", slug, exc)
        try:
            tmp.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _unavailable(
    commander_name: str, cohort: Cohort, url: str | None, reason: str
) -> SelectionEvidence:
    logger.info("selection evidence unavailable for %s: %s", commander_name, reason)
    return SelectionEvidence(
        status="unavailable",
        source_url=url,
        commander_name=commander_name,
        cohort=cohort,
        limitations=[f"selection evidence unavailable: {reason}"],
    )


def _fetch_payload(url: str, fetch: Fetcher) -> Any:
    """At most MAX_ATTEMPTS requests; 4xx is terminal, transport errors retry."""
    last: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            response = fetch(url)
        except Exception as exc:  # noqa: BLE001 - transport is caller supplied
            last = exc
            continue
        if response.status_code == 404:
            raise ParseError("no public edhrec page for this commander/cohort")
        if 400 <= response.status_code < 500:
            raise ParseError(f"edhrec returned HTTP {response.status_code}")
        if response.status_code != 200:
            last = FetchError(f"HTTP {response.status_code}")
            continue
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ParseError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
        try:
            return json.loads(response.content)
        except ValueError as exc:
            raise ParseError(f"invalid JSON: {exc}") from exc
    raise ParseError(f"fetch failed: {last}")


def load_selection_evidence(
    commander: dict,
    power: int,
    cache_dir: Path,
    refresh: bool = True,
    fetch: Fetcher | None = None,
    now: datetime | None = None,
) -> SelectionEvidence:
    """Load public EDHREC evidence for a commander at a power level.

    Never raises for acquisition problems: any failure returns an
    ``unavailable`` result, and a valid cache is preserved. A cache entry
    older than ``FRESH_DAYS`` that cannot be refreshed is returned with
    status ``stale`` plus a visible warning, never silently as current.

    Args:
        commander: Card dict; ``name`` identifies the page.
        power: Deck power; 5 selects the cEDH cohort, which is never
            silently replaced by the general cohort.
        cache_dir: Root for cached public JSON.
        refresh: Allow a network fetch when the cache is missing or stale.
        fetch: Injectable transport (tests pass a fake; default is httpx).
        now: Injectable clock for freshness checks.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    cohort = cohort_for_power(power)
    name = str((commander or {}).get("name") or "").strip()
    if not name:
        return _unavailable("", cohort, None, "commander has no name")
    slug = commander_slug(name)
    if not slug:
        return _unavailable(name, cohort, None, "commander name has no url slug")

    url = source_url_for(slug, cohort)
    path = cache_path(Path(cache_dir), slug, cohort)
    cached = _read_cache(path, slug, cohort)

    if cached is not None and now - cached[1] < timedelta(days=FRESH_DAYS):
        return _build(name, cohort, url, cached[0], cached[1], stale=False)

    if refresh:
        try:
            payload = _fetch_payload(url, fetch or httpx_fetch)
        except ParseError as exc:
            payload = None
            reason = str(exc)
        except Exception as exc:  # noqa: BLE001 - transport is caller supplied
            payload = None
            reason = f"fetch failed: {exc}"
        if payload is not None:
            evidence = _build(name, cohort, url, payload, now, stale=False)
            if evidence.status == "available":
                _write_cache(path, slug, cohort, name, url, payload, now)
            return evidence
    else:
        reason = "refresh disabled and no fresh cache"

    if cached is None:
        return _unavailable(name, cohort, url, reason)

    logger.warning(
        "using stale selection evidence for %s (%s cohort, retrieved %s): %s",
        name,
        cohort,
        cached[1].isoformat(),
        reason,
    )
    return _build(name, cohort, url, cached[0], cached[1], stale=True, reason=reason)


def _build(
    name: str,
    cohort: Cohort,
    url: str,
    payload: Any,
    retrieved_at: datetime,
    stale: bool,
    reason: str = "",
) -> SelectionEvidence:
    try:
        sample_size, inclusion, synergy, composition, limitations = parse_payload(
            payload, name, cohort
        )
    except ParseError as exc:
        return _unavailable(name, cohort, url, str(exc))
    if stale:
        limitations = [
            f"STALE: cached {retrieved_at.isoformat()}, refresh failed ({reason})",
            *limitations,
        ]
    return SelectionEvidence(
        status="stale" if stale else "available",
        source_url=url,
        commander_name=name,
        cohort=cohort,
        retrieved_at=retrieved_at,
        sample_size=sample_size,
        inclusion=inclusion,
        synergy=synergy,
        composition=composition,
        limitations=limitations,
    )

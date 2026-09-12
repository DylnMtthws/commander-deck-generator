"""Canonical profile metadata, oracle-backed card analysis, and cache checks.

Application inputs own identity, timestamps, set version, user intent, and
evidence provenance. Model output may supply strategic analysis, never those
fields. Unknown evidence stays unknown: only retrieved source IDs are cited.

Cached profiles are reused only when they carry an application-owned
provenance marker and match canonical identity, set, intent, and an aware
non-future timestamp. Unmarked legacy rows are rejected once.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from sabermetrics.models.card import Card
from sabermetrics.models.evidence import EvidencePackage, PrimerArticle, ReferenceChunk
from sabermetrics.models.profile import CommanderProfile, UserIntent

# Application-owned cache marker. Not a model field and not taken from LLM output.
CACHE_PROVENANCE_KEY = "_application_cache"
CACHE_PROVENANCE_VERSION = "grounding-v1"
_FUTURE_SKEW = timedelta(seconds=60)

_TRIGGER_RE = re.compile(
    r"\b(when|whenever|at the beginning|at the end)\b",
    re.IGNORECASE,
)
_EVASION_OR_PROTECTION = frozenset(
    {
        "flying",
        "shadow",
        "horsemanship",
        "fear",
        "intimidate",
        "menace",
        "skulk",
        "hexproof",
        "shroud",
        "ward",
        "protection",
        "indestructible",
        "reach",
        "trample",
        "first strike",
        "double strike",
    }
)


def utc_now() -> datetime:
    """Current time in UTC, timezone-aware."""
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    """Return a UTC-aware datetime; naive values are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def extract_json_payload(text: str) -> dict[str, Any]:
    """Parse a JSON object, stripping optional markdown fences."""
    response_text = (text or "").strip()
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        json_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            if line.startswith("```") and in_block:
                break
            if in_block:
                json_lines.append(line)
        response_text = "\n".join(json_lines)
    payload = json.loads(response_text)
    if not isinstance(payload, dict):
        raise TypeError("Model JSON payload must be an object")
    return payload


def retrieved_source_ids(evidence: EvidencePackage) -> set[str]:
    """IDs that were actually retrieved for this profile request."""
    allowed: set[str] = set()
    for chunk in evidence.reference_chunks:
        allowed.update(_chunk_ids(chunk))
    for article in evidence.primer_articles:
        allowed.update(_article_ids(article))
    return {item for item in allowed if item}


def _chunk_ids(chunk: ReferenceChunk) -> set[str]:
    ids = {chunk.id, chunk.document}
    if chunk.section:
        ids.add(chunk.section)
        ids.add(f"{chunk.document}/{chunk.section}")
    else:
        ids.add(f"{chunk.document}/general")
    return {item for item in ids if item}


def _article_ids(article: PrimerArticle) -> set[str]:
    return {item for item in (article.title, article.url, article.source) if item}


def filter_cited_ids(cited: list[str] | None, allowed: set[str]) -> list[str]:
    """Keep only identifiers present in the retrieved evidence set."""
    if not cited:
        return []
    return [item for item in cited if item in allowed]


def derive_card_analysis(
    commander: Card, model_analysis: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Mana cost/color always come from the card; abilities from oracle text.

    Model phrasing is kept only when it is a verbatim (case-insensitive)
    excerpt of the printed oracle text.
    """
    derived = _abilities_from_oracle(commander)
    model = model_analysis if isinstance(model_analysis, dict) else {}
    oracle = commander.oracle_text or ""

    core = model.get("core_mechanic")
    if not _verbatim_oracle_support(core, oracle):
        core = derived["core_mechanic"]

    triggered = _grounded_ability_list(
        model.get("triggered_abilities"), oracle, derived["triggered_abilities"]
    )
    activated = _grounded_ability_list(
        model.get("activated_abilities"), oracle, derived["activated_abilities"]
    )
    static = _grounded_ability_list(
        model.get("static_abilities"), oracle, derived["static_abilities"]
    )

    evasion = model.get("evasion_or_protection")
    if not _verbatim_oracle_support(evasion, oracle) and not _keyword_listed(
        evasion, commander.keywords
    ):
        evasion = derived["evasion_or_protection"]

    return {
        "mana_cost": commander.mana_cost or "",
        "color_identity": list(commander.color_identity),
        "core_mechanic": core or derived["core_mechanic"],
        "triggered_abilities": triggered,
        "activated_abilities": activated,
        "static_abilities": static,
        "evasion_or_protection": evasion,
    }


def apply_canonical_profile_metadata(
    profile_data: dict[str, Any],
    *,
    commander: Card,
    user_intent: str | None,
    evidence: EvidencePackage,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Override identity, time, set, intent, sources, and card analysis.

    Never setdefault these fields from model output.
    """
    data = dict(profile_data)
    generated = aware_utc(generated_at or utc_now())

    data["commander_id"] = commander.id
    data["commander_name"] = commander.name
    data["generated_at"] = generated
    data["set_version"] = commander.set_code
    data["card_analysis"] = derive_card_analysis(
        commander,
        (
            data.get("card_analysis")
            if isinstance(data.get("card_analysis"), dict)
            else None
        ),
    )
    data["user_intent"] = _canonical_user_intent(user_intent, data.get("user_intent"))
    data["sources"] = _canonical_sources(evidence, data.get("sources"))
    data.pop(CACHE_PROVENANCE_KEY, None)
    return data


def stamp_cache_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the application cache marker. Callers must not take this from the model."""
    data = dict(payload)
    intent = (
        data.get("user_intent") if isinstance(data.get("user_intent"), dict) else {}
    )
    description = intent.get("description")
    if not isinstance(description, str) or not description:
        description = None
    data[CACHE_PROVENANCE_KEY] = {
        "version": CACHE_PROVENANCE_VERSION,
        "commander_id": data.get("commander_id"),
        "commander_name": data.get("commander_name"),
        "set_version": data.get("set_version"),
        "intent_provided": bool(intent.get("provided")),
        "intent_description": description,
    }
    return data


def cache_row_schema_is_current(schema_version: str | None) -> bool:
    """True when the commander_profiles row was written by this application."""
    return schema_version == CACHE_PROVENANCE_VERSION


def profile_cache_is_valid(
    payload: dict[str, Any] | CommanderProfile,
    *,
    commander: Card,
    user_intent: str | None,
    now: datetime | None = None,
) -> bool:
    """True only with application provenance and matching identity/set/intent/time."""
    raw = _as_payload_dict(payload)
    if raw is None:
        return False
    provenance = raw.get(CACHE_PROVENANCE_KEY)
    if not isinstance(provenance, dict):
        return False
    if provenance.get("version") != CACHE_PROVENANCE_VERSION:
        return False
    try:
        profile = CommanderProfile(
            **{key: value for key, value in raw.items() if key != CACHE_PROVENANCE_KEY}
        )
    except (ValidationError, TypeError, ValueError):
        return False

    if provenance.get("commander_id") != commander.id:
        return False
    if provenance.get("commander_name") != commander.name:
        return False
    if provenance.get("set_version") != commander.set_code:
        return False
    if profile.commander_id != commander.id:
        return False
    if profile.commander_name != commander.name:
        return False
    if profile.set_version != commander.set_code:
        return False
    if not _aware_nonfuture_timestamp(profile.generated_at, now):
        return False
    if not _user_intent_matches(profile.user_intent, user_intent):
        return False
    prov_desc = provenance.get("intent_description")
    if not isinstance(prov_desc, str) or not prov_desc:
        prov_desc = None
    if bool(provenance.get("intent_provided")) != bool(user_intent):
        return False
    return prov_desc == (user_intent or None)


def _as_payload_dict(
    payload: dict[str, Any] | CommanderProfile,
) -> dict[str, Any] | None:
    if isinstance(payload, CommanderProfile):
        return json.loads(payload.model_dump_json())
    if isinstance(payload, dict):
        return payload
    return None


def _aware_nonfuture_timestamp(value: datetime, now: datetime | None) -> bool:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    current = aware_utc(now or utc_now())
    return aware_utc(value) <= current + _FUTURE_SKEW


def _user_intent_matches(stored: UserIntent, user_intent: str | None) -> bool:
    provided = bool(user_intent)
    if stored.provided != provided:
        return False
    stored_desc = stored.description if stored.description else None
    request_desc = user_intent if user_intent else None
    return stored_desc == request_desc


def _canonical_user_intent(
    user_intent: str | None, model_intent: Any
) -> dict[str, Any]:
    divergence = None
    if user_intent and isinstance(model_intent, dict):
        raw = model_intent.get("divergence_from_consensus")
        if isinstance(raw, str) and raw.strip():
            divergence = raw
    return {
        "provided": bool(user_intent),
        "description": user_intent,
        "divergence_from_consensus": divergence if user_intent else None,
    }


def _canonical_sources(evidence: EvidencePackage, model_sources: Any) -> dict[str, Any]:
    allowed = retrieved_source_ids(evidence)
    model = model_sources if isinstance(model_sources, dict) else {}
    rules = filter_cited_ids(
        _as_str_list(model.get("rules_chunks_referenced")), allowed
    )
    articles = filter_cited_ids(_as_str_list(model.get("articles_referenced")), allowed)
    if not rules:
        rules = [chunk.id for chunk in evidence.reference_chunks if chunk.id]
    if not articles:
        articles = [
            article.title for article in evidence.primer_articles if article.title
        ]
    return {
        "rules_chunks_referenced": rules,
        "articles_referenced": articles,
        "evidence_freshness": _evidence_freshness(evidence),
    }


def _evidence_freshness(evidence: EvidencePackage) -> dict[str, Any]:
    edhrec = evidence.edhrec_data or {}
    tourney = evidence.tournament_data or {}
    return {
        "edhrec_last_updated": edhrec.get("last_updated"),
        "topdeck_last_updated": tourney.get("last_updated"),
        "reddit_last_searched": utc_now() if evidence.reddit_threads else None,
    }


def _abilities_from_oracle(commander: Card) -> dict[str, Any]:
    sentences = _oracle_ability_lines(commander.oracle_text or "")
    triggered: list[str] = []
    activated: list[str] = []
    static: list[str] = []
    for sentence in sentences:
        if _is_activated(sentence):
            activated.append(sentence)
        elif _TRIGGER_RE.search(sentence):
            triggered.append(sentence)
        else:
            static.append(sentence)

    core_parts = triggered or activated or static
    core = (
        core_parts[0] if core_parts else (commander.oracle_text or commander.type_line)
    )
    evasion = _evasion_from_card(commander, static)
    return {
        "core_mechanic": core,
        "triggered_abilities": triggered,
        "activated_abilities": activated,
        "static_abilities": static,
        "evasion_or_protection": evasion,
    }


def _oracle_ability_lines(oracle: str) -> list[str]:
    lines: list[str] = []
    for raw in oracle.replace("\r\n", "\n").split("\n"):
        piece = raw.strip()
        if not piece:
            continue
        if piece.startswith("(") and piece.endswith(")"):
            continue
        for sentence in re.split(r"(?<=\.)\s+", piece):
            cleaned = sentence.strip()
            if cleaned:
                lines.append(cleaned)
    return lines


def _is_activated(sentence: str) -> bool:
    if ":" not in sentence:
        return False
    if sentence.startswith("("):
        return False
    cost, _sep, effect = sentence.partition(":")
    return bool(cost.strip()) and bool(effect.strip())


def _evasion_from_card(commander: Card, static: list[str]) -> str | None:
    found: list[str] = []
    keywords = [str(k).lower() for k in commander.keywords]
    blob = " ".join(static).lower()
    for keyword in sorted(_EVASION_OR_PROTECTION, key=len, reverse=True):
        if keyword in keywords or re.search(rf"\b{re.escape(keyword)}\b", blob):
            found.append(keyword)
    if not found:
        return None
    return ", ".join(found)


def _verbatim_oracle_support(value: Any, oracle: str) -> bool:
    if not isinstance(value, str) or not value.strip() or not oracle:
        return False
    return value.strip().lower() in oracle.lower()


def _keyword_listed(value: Any, keywords: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = {k.lower() for k in keywords}
    return all(
        part.strip().lower() in lowered for part in value.split(",") if part.strip()
    )


def _grounded_ability_list(
    model_value: Any, oracle: str, derived: list[str]
) -> list[str]:
    if not isinstance(model_value, list) or not model_value:
        return derived
    grounded = [
        item
        for item in model_value
        if isinstance(item, str) and _verbatim_oracle_support(item, oracle)
    ]
    return grounded or derived


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]

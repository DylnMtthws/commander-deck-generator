"""User-intent → grounded engine requirement (oracle traits, not card names).

The first supported engine is a mana-value-limited creature copy/clone
package. Eligibility is derived from copy-on-entry oracle text. Keyword-
counter collectors are not clones. Legendary copiers remain eligible: the
legend rule is a battlefield restriction, not a list-building ban.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

EngineKind = Literal["none", "clone_creature_mv", "unsupported"]
EngineStatus = Literal[
    "none",
    "unverified",
    "infeasible",
    "satisfied",
    "unsatisfied",
]

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Copy-on-entry: the creature itself enters as a copy. Token-makers that
# "create a token that's a copy" do not match. Covers both modern
# "enter as a copy" and "enters the battlefield as a copy" oracle.
_ENTER_AS_COPY = r"enter(?:s(?: the battlefield)?| the battlefield)? as a copy"
_COPY_ON_ENTRY = re.compile(
    rf"you may have .+ {_ENTER_AS_COPY}" rf"|{_ENTER_AS_COPY}",
    re.IGNORECASE,
)
_TOKEN_COPY = re.compile(
    r"create (?:a|one|\d+|that many) .+ token",
    re.IGNORECASE,
)

# Counter / keyword-hoarders. Only used when copy-on-entry is absent.
_COUNTER_COLLECTOR = re.compile(
    r"keyword counter"
    r"|\+1/\+1 counter"
    r"|proliferate"
    r"|double (?:each|the) (?:kind of )?counters?"
    r"|for each keyword"
    r"|counters on (?:it|this) for each"
    r"|put a \w+ counter",
    re.IGNORECASE,
)

_CLONE_INTENT = re.compile(
    r"\b(?:clone|clones|copy[ -]?clone|clone[ -]?copy)\b"
    r"|\bcopy(?:ing)?\s+creatures?\b"
    r"|\bcreature\s+cop(?:y|ies)\b"
    r"|\bcopy[ -]on[ -]entry\b"
    r"|\bfour-mana copy\b"
    r"|\b4-mana copy\b",
    re.IGNORECASE,
)

_MV_PATTERNS = (
    re.compile(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)[ -]mana\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d+)\s*[ -]?mana\b", re.IGNORECASE),
    re.compile(r"\bmv\s*<=?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bmana value\s*(?:of\s+|<=\s*)?(\d+)\b", re.IGNORECASE),
    re.compile(r"\bcmc\s*<=?\s*(\d+)\b", re.IGNORECASE),
)

# Finite library looks are not deterministic infinite loops.
_FINITE_TOP_N = re.compile(
    r"\btop\s+(?:five|four|three|two|\d+)\s+cards?\b",
    re.IGNORECASE,
)
_INFINITE_CLAIM = re.compile(
    r"\b(?:deterministic\s+)?infinite\s+(?:combo|loop|mana|turns?)\b",
    re.IGNORECASE,
)

DEFAULT_CLONE_MAX_MV = 4.0
DEFAULT_CLONE_MIN_COUNT = 2


class EngineRequirement(BaseModel):
    """Inspectable engine contract derived from user intent + oracle rules."""

    kind: EngineKind = "none"
    raw_intent: str | None = None
    max_mana_value: float | None = None
    min_count: int = DEFAULT_CLONE_MIN_COUNT
    supported: bool = False
    notes: str = ""


class EngineCandidateRecord(BaseModel):
    """Admission / unavailability record for one engine-shaped card."""

    name: str
    card_id: str | None = None
    admitted: bool
    reason: str
    mana_value: float | None = None
    price_usd: float | None = None
    legendary: bool = False


class EngineAdmission(BaseModel):
    """Result of scanning a legal pool for a requirement."""

    requirement: EngineRequirement
    admitted: list[dict] = Field(default_factory=list)
    records: list[EngineCandidateRecord] = Field(default_factory=list)
    selected: list[dict] = Field(default_factory=list)
    status: EngineStatus = "none"

    @property
    def selected_names(self) -> set[str]:
        return {c.get("name", "") for c in self.selected if c.get("name")}

    @property
    def admitted_names(self) -> set[str]:
        return {c.get("name", "") for c in self.admitted if c.get("name")}


def parse_user_intent(user_intent: str | None) -> EngineRequirement:
    """Turn free-text intent into a grounded engine requirement.

    Unsupported text is marked unverified (supported=False). Absence of
    intent is kind=none. Clone/copy phrasing becomes clone_creature_mv,
    with a mana-value cap taken from the text (default four).
    """
    raw = (user_intent or "").strip()
    if not raw:
        return EngineRequirement(kind="none", raw_intent=None, supported=True)

    if _CLONE_INTENT.search(raw):
        max_mv = _extract_mana_value_cap(raw)
        if max_mv is None:
            max_mv = DEFAULT_CLONE_MAX_MV
        return EngineRequirement(
            kind="clone_creature_mv",
            raw_intent=raw,
            max_mana_value=float(max_mv),
            min_count=DEFAULT_CLONE_MIN_COUNT,
            supported=True,
            notes=(
                "Creature copy-on-entry package, mana-value limited. "
                "Eligibility is oracle-text copy-on-entry, not a card-name list."
            ),
        )

    return EngineRequirement(
        kind="unsupported",
        raw_intent=raw,
        supported=False,
        notes="Intent was provided but is not a supported engine contract.",
    )


def _extract_mana_value_cap(text: str) -> int | None:
    for pattern in _MV_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        token = match.group(1).lower()
        if token in _NUMBER_WORDS:
            return _NUMBER_WORDS[token]
        try:
            return int(token)
        except ValueError:
            continue
    return None


def oracle_text_of(card: dict) -> str:
    """Authoritative oracle text; join faces when the top-level field is empty."""
    text = card.get("oracle_text")
    if text:
        return text
    faces = card.get("card_faces") or []
    parts = [face.get("oracle_text") or "" for face in faces if isinstance(face, dict)]
    return " // ".join(part for part in parts if part)


def type_line_of(card: dict) -> str:
    line = card.get("type_line")
    if line:
        return line
    faces = card.get("card_faces") or []
    parts = [face.get("type_line") or "" for face in faces if isinstance(face, dict)]
    return " // ".join(part for part in parts if part)


def is_creature_type(type_line: str | None) -> bool:
    """True when the front face is a creature."""
    if not type_line:
        return False
    front = type_line.split("//")[0].strip().lower()
    return "creature" in front


def is_legendary(type_line: str | None) -> bool:
    if not type_line:
        return False
    return "legendary" in type_line.split("//")[0].strip().lower()


def is_copy_on_entry_creature(card: dict) -> bool:
    """True iff this is a creature that enters as a copy of another permanent.

    Keyword-counter collectors without copy-on-entry text are not clones.
    Being legendary, or copying a legendary, does not disqualify the card.
    Token-makers that create a copy are not copy-on-entry creatures.
    """
    if not is_creature_type(type_line_of(card)):
        return False
    oracle = oracle_text_of(card)
    if not oracle or not _COPY_ON_ENTRY.search(oracle):
        return False
    # A spell that only makes a copy token is not itself a clone creature,
    # even if remnant "enter as a copy" wording appears on the token reminder.
    return not (_TOKEN_COPY.search(oracle) and "you may have" not in oracle.lower())


def is_keyword_counter_collector(card: dict) -> bool:
    """Counter/keyword hoarders that are not copy-on-entry clones."""
    if is_copy_on_entry_creature(card):
        return False
    oracle = oracle_text_of(card)
    return bool(_COUNTER_COLLECTOR.search(oracle))


def mana_value_of(card: dict) -> float | None:
    raw = card.get("cmc")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def looks_like_finite_top_n_effect(text: str | None) -> bool:
    """Finite top-of-library looks (top five, etc.) are not infinite loops."""
    return bool(_FINITE_TOP_N.search(text or ""))


def claims_infinite_loop(text: str | None) -> bool:
    return bool(_INFINITE_CLAIM.search(text or ""))


def admit_engine_candidates(
    requirement: EngineRequirement,
    budget_valid_pool: list[dict],
    color_legal_pool: list[dict] | None = None,
    per_card_ceiling: float | None = None,
) -> EngineAdmission:
    """Select a feasible engine package from the pre-prune legal pool.

    ``budget_valid_pool`` is the hard-filter output (color, legality, budget).
    ``color_legal_pool`` may include over-budget printings so unavailability
    is traced instead of silently omitted.

    Engine preservation never invents candidates that fail hard gates.
    """
    if requirement.kind == "none":
        return EngineAdmission(requirement=requirement, status="none")
    if requirement.kind == "unsupported" or not requirement.supported:
        return EngineAdmission(requirement=requirement, status="unverified")

    scan_pool = color_legal_pool if color_legal_pool is not None else budget_valid_pool
    budget_names = {c.get("name", "") for c in budget_valid_pool}
    budget_by_name = {c.get("name", ""): c for c in budget_valid_pool}

    records: list[EngineCandidateRecord] = []
    admitted: list[dict] = []
    seen: set[str] = set()

    for card in scan_pool:
        name = card.get("name", "")
        if not name or name in seen:
            continue
        if not is_copy_on_entry_creature(card):
            # Record creature-shaped counter collectors so they are not
            # silently treated as clones. Non-creatures are not engine
            # candidates and are omitted on purpose.
            if is_creature_type(type_line_of(card)) and is_keyword_counter_collector(
                card
            ):
                records.append(
                    EngineCandidateRecord(
                        name=name,
                        card_id=card.get("id"),
                        admitted=False,
                        reason="not a clone: keyword/counter collector, no copy-on-entry text",
                        mana_value=mana_value_of(card),
                        price_usd=_price(card),
                        legendary=is_legendary(type_line_of(card)),
                    )
                )
            continue
        seen.add(name)
        record = _classify_clone_card(
            card,
            requirement,
            in_budget_pool=name in budget_names,
            per_card_ceiling=per_card_ceiling,
        )
        records.append(record)
        if record.admitted:
            # Prefer the budget-gated printing so later stages share identity.
            admitted.append(budget_by_name.get(name, card))

    admitted.sort(
        key=lambda c: (
            mana_value_of(c) if mana_value_of(c) is not None else 99.0,
            _price(c) if _price(c) is not None else 0.0,
            c.get("name", ""),
        )
    )
    min_count = max(0, requirement.min_count)
    selected = admitted[: max(min_count, min(len(admitted), min_count))]
    # When more than min_count are cheap and legal, still keep the minimum
    # package (at least two when feasible). Extra clones can still be picked
    # later by the optimizer; reservation only guarantees the package.
    if len(admitted) >= min_count:
        selected = admitted[:min_count]
        # Feasible at admission; callers overwrite after the final list.
        status: EngineStatus = "satisfied"
    elif admitted:
        selected = list(admitted)
        status = "infeasible"
    else:
        selected = []
        status = "infeasible"

    return EngineAdmission(
        requirement=requirement,
        admitted=admitted,
        records=records,
        selected=selected,
        status=status,
    )


def _classify_clone_card(
    card: dict,
    requirement: EngineRequirement,
    *,
    in_budget_pool: bool,
    per_card_ceiling: float | None,
) -> EngineCandidateRecord:
    name = card.get("name", "")
    mv = mana_value_of(card)
    price = _price(card)
    legendary = is_legendary(type_line_of(card))
    # Legendary is NEVER a disqualifier. Record it for inspectability.
    if mv is None:
        return EngineCandidateRecord(
            name=name,
            card_id=card.get("id"),
            admitted=False,
            reason="unavailable: missing mana value; refusing to invent CMC",
            mana_value=None,
            price_usd=price,
            legendary=legendary,
        )
    cap = requirement.max_mana_value
    if cap is not None and mv > cap:
        return EngineCandidateRecord(
            name=name,
            card_id=card.get("id"),
            admitted=False,
            reason=f"unavailable: mana value {mv:g} exceeds cap {cap:g}",
            mana_value=mv,
            price_usd=price,
            legendary=legendary,
        )
    if not in_budget_pool:
        ceiling_note = ""
        if (
            per_card_ceiling is not None
            and price is not None
            and price > per_card_ceiling
        ):
            ceiling_note = (
                f" (price ${price:.2f} > per-card ceiling ${per_card_ceiling:.2f})"
            )
        elif price is None:
            ceiling_note = " (unpriced; budget gate excludes unknown prices)"
        else:
            ceiling_note = f" (price ${price:.2f} not in budget-valid pool)"
        return EngineCandidateRecord(
            name=name,
            card_id=card.get("id"),
            admitted=False,
            reason="unavailable: over budget" + ceiling_note,
            mana_value=mv,
            price_usd=price,
            legendary=legendary,
        )
    reason = "admitted: copy-on-entry creature within mana-value and budget"
    if legendary:
        reason += " (legendary copier still legal; legend rule is not a list ban)"
    return EngineCandidateRecord(
        name=name,
        card_id=card.get("id"),
        admitted=True,
        reason=reason,
        mana_value=mv,
        price_usd=price,
        legendary=legendary,
    )


def _price(card: dict) -> float | None:
    raw = card.get("price_usd", card.get("current_price_usd"))
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _meets_mana_value_cap(card: dict, requirement: EngineRequirement) -> bool:
    cap = requirement.max_mana_value
    if cap is None:
        return True
    mv = mana_value_of(card)
    return mv is not None and mv <= cap


def verify_engine_in_deck(
    admission: EngineAdmission,
    deck_cards: list[dict],
) -> EngineStatus:
    """Final-list engine status. Never reports fulfilled when it was not.

    Satisfaction is oracle-trait presence in the finished 99, not a
    hard-coded name list. Infeasible admission stays infeasible even if a
    stray clone landed.
    """
    req = admission.requirement
    if req.kind == "none":
        return "none"
    if req.kind == "unsupported" or not req.supported:
        return "unverified"
    if admission.status == "infeasible":
        # Even if a stray clone landed, do not claim the requested package
        # was satisfied when admission already knew it was infeasible.
        return "infeasible"
    matching = [
        card
        for card in deck_cards
        if is_copy_on_entry_creature(card) and _meets_mana_value_cap(card, req)
    ]
    if len(matching) >= req.min_count:
        return "satisfied"
    return "unsatisfied"


def engine_requirement_dump(requirement: EngineRequirement) -> dict:
    return requirement.model_dump()


def engine_rationale_dump(admission: EngineAdmission) -> dict:
    """Compact inspectable engine object for persisted rationale JSON."""
    return {
        "status": admission.status,
        "requirement": admission.requirement.model_dump(),
        "admitted": [c.get("name") for c in admission.admitted if c.get("name")],
        "selected": sorted(admission.selected_names),
        "records": [r.model_dump() for r in admission.records],
    }

"""Conservative, inspectable land drawback detection and score experiments.

A drawback is not an illegality. Glimmervoid is a fine land in a deck with
artifact density; a colored pain land is often worth the life. Nothing here
bans a card, and nothing here reads a card's *name*: every finding comes from
printed Oracle text and the type line, so a reprint under another name is
scored identically and a name nobody has heard of is scored on its text.

Three things are exposed:

``land_risks(card)``
    Printed drawbacks as ``{"code", "severity", "message"}`` records. Only
    supported printed shapes are claimed. A shape this module does not match
    is an unresolved reading, never a statement that the land is clean.

``risk_adjustment(card, deck=None)``
    A non-positive penalty. With a deck, a drawback whose condition is a
    board requirement (control an artifact / a creature) is *partly*
    mitigated by that deck's density. Density is a prior about how often the
    requirement is likely to be met; it never asserts that the board state is
    guaranteed, so mitigation is capped strictly below full relief.

``adjust_land_score(card, score, *, evidence_weight=0, risk_weight=0)``
    The experiment harness. At zero weights it returns the baseline score
    unchanged, bit for bit, so an experiment grid always contains a true
    control arm.

Every constant below is an **experiment hypothesis**, not a learned or
validated quantity. No severity penalty, mitigation target or cap in this
module was fit to observed decks or win data. They exist to be swept over a
grid and replaced by measurements; see
``docs/specs/selection-intelligence/land-experiment.md``.
"""

from __future__ import annotations

import math
import re

VERSION = "land-policy.v2-score-units"

# --- severity vocabulary ---------------------------------------------------
# "high"   drawback can cost the land, or the game, on its own
# "medium" drawback is conditional on state the deck may or may not have
# "low"    drawback is a real but routinely acceptable price
SEVERITY_ORDER = ("high", "medium", "low")

# HYPOTHESIS. Constant per-severity penalties in score units, chosen to be
# ordered and coarse, not calibrated. A "high" land is meant to need a clear
# reason to be kept, not to be unselectable.
SEVERITY_PENALTY: dict[str, float] = {
    "high": 12.0,
    "medium": 6.0,
    "low": 2.0,
}

# HYPOTHESIS. A land with several drawbacks should not accumulate an unbounded
# penalty; past some point the marginal information is small and the ordering
# against other lands is already decided.
MAX_TOTAL_PENALTY = 24.0

# HYPOTHESIS. Deck density at which a board requirement is treated as "as met
# as this module is willing to assume", and the largest share of a penalty
# density may ever remove. Mitigation is capped below 1.0 on purpose: an
# artifact-dense deck still draws hands without artifacts, and still has its
# board answered.
MITIGATION_TARGET_DENSITY = 0.25
MAX_MITIGATION = 0.75

# Risk codes whose condition is a board requirement a deck can be built toward,
# mapped to the permanent type that satisfies them.
MITIGABLE_BY_DENSITY: dict[str, str] = {
    "sacrifice_unless_artifact": "artifact",
    "sacrifice_unless_creature": "creature",
}

RISK_SEVERITY: dict[str, str] = {
    # Losing the permanent, or handing it over, with no way to pay out of it.
    "opponent_gains_control": "high",
    "upkeep_sacrifice_unless_cost_paid": "high",
    "upkeep_exile": "high",
    "upkeep_hand_exile": "high",
    "mana_requires_sacrificing_resource": "medium",
    "triggered_self_sacrifice": "high",
    "triggered_self_exile": "high",
    "sacrifice_unless_condition": "high",
    # Conditional on state the deck can influence, or on how mana is usable.
    "sacrifice_unless_artifact": "medium",
    "sacrifice_unless_creature": "medium",
    "does_not_untap": "medium",
    "conditional_mana_activation": "medium",
    "mana_usage_restricted": "medium",
    "color_depends_on_other_permanents": "medium",
    "mana_requires_sacrificing_the_land": "medium",
    "mana_requires_trigger": "medium",
    "no_unconditional_mana_ability": "medium",
    # Routine, frequently worth paying.
    "mana_requires_mana_payment": "low",
    "mana_costs_life": "low",
    "mana_source_damages_you": "low",
    "mana_requires_library_search": "low",
    "land_oracle_text_unavailable": "low",
}

RISK_MESSAGE: dict[str, str] = {
    "opponent_gains_control": (
        "an opponent can gain control of this land; the mana it made is not "
        "a permanent gain"
    ),
    "upkeep_sacrifice_unless_cost_paid": (
        "an upkeep cost must be paid every turn or the land is sacrificed"
    ),
    "upkeep_exile": "an upkeep trigger exiles this land",
    "upkeep_hand_exile": "untapping requires exiling a card from hand at upkeep",
    "mana_requires_sacrificing_resource": "the mana ability requires sacrificing another resource",
    "triggered_self_sacrifice": "a trigger sacrifices this land",
    "triggered_self_exile": "a trigger exiles this land",
    "sacrifice_unless_condition": (
        "the land is sacrificed unless a condition this module cannot tie to "
        "deck composition is met"
    ),
    "sacrifice_unless_artifact": (
        "the land is sacrificed unless you control an artifact; artifact "
        "density makes this likelier, it does not guarantee the board state"
    ),
    "sacrifice_unless_creature": (
        "the land is sacrificed unless you control a creature; creature "
        "density makes this likelier, it does not guarantee the board state"
    ),
    "does_not_untap": "this land does not untap during your untap step",
    "conditional_mana_activation": (
        "the mana ability can only be activated under a printed restriction"
    ),
    "mana_usage_restricted": "the mana produced may only be spent on some things",
    "color_depends_on_other_permanents": (
        "the colors produced depend on other permanents, not on this land alone"
    ),
    "mana_requires_sacrificing_the_land": (
        "mana is produced by sacrificing this land; it is one shot, not a source"
    ),
    "mana_requires_trigger": (
        "mana comes from a trigger, which is not a mana ability a player can "
        "rely on mid-cast"
    ),
    "no_unconditional_mana_ability": (
        "no unconditional printed mana ability was verified on this land"
    ),
    "mana_requires_mana_payment": (
        "producing this mana requires upfront mana; net production depends on "
        "the ability output"
    ),
    "mana_costs_life": "the mana ability costs life",
    "mana_source_damages_you": "using this land deals damage to you",
    "mana_requires_library_search": (
        "mana access requires searching the library for a land first"
    ),
    "land_oracle_text_unavailable": (
        "no Oracle text was available for this land; drawbacks are unknown, "
        "not absent"
    ),
}

BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest", "wastes")


# --------------------------------------------------------------------------
# Text handling
# --------------------------------------------------------------------------

# Ability words ("Landfall — Whenever ...") precede the trigger itself.
_TRIGGER_RE = re.compile(
    r"^(?:[a-z' \-]{0,30}—\s*)?(?:whenever|when |at the beginning)"
)
_UPKEEP_RE = re.compile(r"at the beginning of (?:your|each|the) upkeep")
_LOSS_OF_CONTROL_RE = re.compile(
    r"\b(?:opponent|player)s?\b[^.\n]{0,40}?gains? control"
)
_NO_UNTAP_RE = re.compile(
    r"doesn'?t untap during (?:your|its controller'?s) untap step"
)
_SAC_UNLESS_RE = re.compile(
    r"sacrifice\b[^.\n]{0,60}?\bunless you control ([^.,\n]{0,60})"
)
_SELF_EXILE_RE = re.compile(r"exile (?:it|this land|this permanent|this card)\b")
_ADD_RE = re.compile(r"\badd\b")
# Any mana symbol that is not the tap symbol: a real payment in an ability cost.
_PAYMENT_SYMBOL_RE = re.compile(r"\{(?!t\})[^}]{1,12}\}")
_PAY_LIFE_RE = re.compile(r"pay \d+ life")
_DAMAGE_TO_YOU_RE = re.compile(r"deals \d+ damage to you")
_BOARD_COLOR_RE = re.compile(
    r"could produce|among (?:permanents|lands|creatures) (?:you|an opponent)"
)
_FETCH_RE = re.compile(
    r"search your library for [^.\n]*"
    r"\b(?:land|plains|island|swamp|mountain|forest|wastes)\b"
    r"[^.\n]*onto the battlefield"
)
_ARTIFACT_CONDITION_RE = re.compile(r"^(?:an|another|any) artifacts?$")
_CREATURE_CONDITION_RE = re.compile(r"^(?:a|another|any) creatures?$")


def _front_type(card: dict) -> str:
    return str(card.get("type_line") or "").split("//")[0].lower()


def is_land(card: dict) -> bool:
    """True when the front face is a land; land policy says nothing else."""
    return "land" in _front_type(card)


def _oracle(card: dict) -> str:
    """Lowercased front-face Oracle text with reminder text removed."""
    text = str(card.get("oracle_text") or "").split(" // ")[0]
    return re.sub(r"\([^)]*\)", "", text).lower()


def _has_basic_type(card: dict) -> bool:
    front = _front_type(card)
    return any(basic in front for basic in BASIC_LAND_TYPES)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def _control_and_sacrifice_risks(lines: list[str], text: str, codes: set[str]) -> None:
    """Loss of control, upkeep taxes and triggered self-destruction."""
    add = codes.add
    if _LOSS_OF_CONTROL_RE.search(text):
        add("opponent_gains_control")
    if _NO_UNTAP_RE.search(text):
        add("does_not_untap")

    for line in lines:
        if not _TRIGGER_RE.match(line):
            # A sacrifice inside an activation cost is a price the controller
            # chooses to pay, not a drawback imposed on them.
            continue
        upkeep = bool(_UPKEEP_RE.search(line))
        if upkeep and re.search(r"exile a card from your hand", line):
            add("upkeep_hand_exile")
        # Current Oracle uses if-control-no as well as historical unless.
        absent = re.search(
            r"if you control no (artifacts|creatures), sacrifice (?:this land|it)", line
        )
        if absent:
            add(
                "sacrifice_unless_"
                + ("artifact" if absent[1] == "artifacts" else "creature")
            )
            continue
        match = _SAC_UNLESS_RE.search(line)
        if match:
            condition = match.group(1).strip()
            if _ARTIFACT_CONDITION_RE.match(condition):
                add("sacrifice_unless_artifact")
            elif _CREATURE_CONDITION_RE.match(condition):
                add("sacrifice_unless_creature")
            else:
                # Some other requirement. It may well be easy, but this module
                # cannot tie it to deck composition, so it is not discounted.
                add("sacrifice_unless_condition")
        elif "sacrifice" in line:
            if upkeep:
                add("upkeep_sacrifice_unless_cost_paid")
            else:
                add("triggered_self_sacrifice")
        elif _SELF_EXILE_RE.search(line):
            add("upkeep_exile" if upkeep else "triggered_self_exile")


def _mana_risks(card: dict, lines: list[str], text: str, codes: set[str]) -> None:
    """Classify printed mana abilities; direct sources are left unpenalised."""
    add = codes.add
    has_direct_source = _has_basic_type(card)

    for line in lines:
        if not _ADD_RE.search(line):
            continue
        if _TRIGGER_RE.match(line):
            add("mana_requires_trigger")
            continue
        head, separator, _ = line.partition(":")
        if not separator or _ADD_RE.search(head):
            # No activation cost at all; treat the printed mana as direct.
            has_direct_source = True
            head = ""
        if "spend this mana only" in line:
            add("mana_usage_restricted")
        if _BOARD_COLOR_RE.search(line):
            add("color_depends_on_other_permanents")
        if "activate only" in line:
            add("conditional_mana_activation")
            continue
        if not head:
            continue
        if "sacrifice" in head:
            if re.search(
                r"sacrifice (?:a|an|another) (?:creature|artifact|permanent)", head
            ):
                add("mana_requires_sacrificing_resource")
            else:
                add("mana_requires_sacrificing_the_land")
            continue
        if _PAYMENT_SYMBOL_RE.search(head):
            # Filtering: mana in, mana out. Useful fixing, but not a source
            # that can be relied on for a net increase in available mana.
            add("mana_requires_mana_payment")
            continue
        if "{t}" in head:
            has_direct_source = True
            if _PAY_LIFE_RE.search(head):
                add("mana_costs_life")

    if _DAMAGE_TO_YOU_RE.search(text):
        add("mana_source_damages_you")

    if has_direct_source:
        return
    if _FETCH_RE.search(text):
        # A fetch is an eligible source with a prerequisite, not a dead land.
        add("mana_requires_library_search")
    elif not text.strip():
        add("land_oracle_text_unavailable")
    elif not codes & {
        "conditional_mana_activation",
        "mana_requires_sacrificing_the_land",
        "mana_requires_trigger",
    }:
        # Only say "nothing unconditional was verified" when the reason has
        # not already been reported more precisely.
        add("no_unconditional_mana_ability")


def land_risks(card: dict) -> list[dict]:
    """Printed drawbacks of one land, most severe first.

    Returns ``[]`` for a non-land, and for a land whose printed text matches
    no supported drawback shape. An empty list means "no supported drawback
    shape was matched", which is weaker than "this land is safe".

    The card's ``name`` is never read: two cards with identical Oracle text
    and type line always produce identical findings.

    Args:
        card: Card dict; only ``oracle_text`` and ``type_line`` are consulted.

    Returns:
        A list of ``{"code", "severity", "message"}`` dicts, ordered by
        severity then code so the result is stable and comparable.
    """
    if not is_land(card):
        return []
    text = _oracle(card)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    codes: set[str] = set()
    _control_and_sacrifice_risks(lines, text, codes)
    _mana_risks(card, lines, text, codes)

    return [
        {
            "code": code,
            "severity": RISK_SEVERITY[code],
            "message": RISK_MESSAGE[code],
        }
        for code in sorted(
            codes, key=lambda c: (SEVERITY_ORDER.index(RISK_SEVERITY[c]), c)
        )
    ]


# --------------------------------------------------------------------------
# Scoring experiments
# --------------------------------------------------------------------------


def _type_densities(deck: list[dict] | None) -> dict[str, float] | None:
    """Share of deck entries whose front face has each mitigating type."""
    if deck is None:
        return None
    entries = [c for c in deck if isinstance(c, dict)]
    if not entries:
        return {}
    densities: dict[str, float] = {}
    for wanted in set(MITIGABLE_BY_DENSITY.values()):
        matches = sum(1 for c in entries if wanted in _front_type(c))
        densities[wanted] = matches / len(entries)
    return densities


def risk_adjustment(card: dict, deck: list[dict] | None = None) -> float:
    """Non-positive score penalty for a land's printed drawbacks.

    ``0.0`` when no supported drawback shape matched. Penalties are the
    constant per-severity hypotheses above, summed and then capped at
    ``MAX_TOTAL_PENALTY``.

    When ``deck`` is given, a drawback that asks for an artifact or a creature
    on board is discounted by that deck's density of the relevant type, up to
    ``MAX_MITIGATION``. This is a prior, not a guarantee: density says the
    requirement is more often met, not that it is met when it matters, so the
    penalty never reaches zero. Deck order does not affect the result, and
    neither ``card`` nor ``deck`` is modified.

    Args:
        card: Card dict; non-lands score ``0.0``.
        deck: Optional decklist providing mitigating density. ``None`` means
            "no deck context", which is scored as no mitigation at all.
    """
    densities = _type_densities(deck)
    penalty = 0.0
    for risk in land_risks(card):
        amount = SEVERITY_PENALTY[risk["severity"]]
        required = MITIGABLE_BY_DENSITY.get(risk["code"])
        if required is not None and densities is not None:
            met = min(1.0, densities.get(required, 0.0) / MITIGATION_TARGET_DENSITY)
            amount *= 1.0 - MAX_MITIGATION * met
        penalty += amount
    if penalty <= 0.0:
        return 0.0
    return -min(penalty, MAX_TOTAL_PENALTY)


def _inclusion(card: dict) -> float:
    """Observed inclusion rate in [0, 1]; missing or unusable reads as 0.0."""
    value = card.get("_selection_inclusion")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def adjust_land_score(
    card: dict,
    score: float,
    *,
    evidence_weight: float = 0.0,
    risk_weight: float = 0.0,
) -> float:
    """Combine a baseline land score with evidence and printed-risk terms.

    The adjustment is additive and separable::

        adjusted = score
                 + evidence_weight * inclusion
                 + risk_weight * risk_adjustment(card)

    ``risk_adjustment`` is non-positive, so a positive ``risk_weight`` is a
    penalty. Both weights default to zero, and at zero weights the baseline
    ``score`` is returned exactly, which makes a control arm of an experiment
    grid indistinguishable from not running this module at all. Neither weight
    can ban a card: the result is a score, and the caller keeps ranking.

    Inclusion is descriptive popularity evidence, never a win rate. A missing,
    non-numeric or non-finite ``_selection_inclusion`` clamps to ``0.0``
    rather than raising, and rates outside [0, 1] clamp into it.

    Args:
        card: Card dict; read-only.
        score: Baseline score from the caller's own model.
        evidence_weight: Weight on the observed inclusion rate.
        risk_weight: Weight on the printed-risk penalty. Deck-aware
            experiments should call ``risk_adjustment(card, deck)`` directly;
            this entry point deliberately scores a land on its own text.
    """
    base = float(score)
    if not math.isfinite(base):
        return base
    if evidence_weight == 0.0 and risk_weight == 0.0:
        return base
    evidence_term = evidence_weight * _inclusion(card)
    risk_term = risk_weight * risk_adjustment(card)
    return base + evidence_term + risk_term

"""Deterministic, conservative extraction of card-draw facts from Magic Oracle text.

This module exposes a single public entry point, :func:`draw_profile`, which maps a
card dict (as found in ``public-fixtures.json``) to a fixed-shape fact dict.

Scope and non-goals
-------------------
This is *not* a comprehensive Oracle-text parser. It recognises a small set of
conservative textual shapes. Anything outside those shapes is reported as
``status == "unknown"`` rather than guessed at. The printed Oracle text supplied
in the ``oracle_text`` field is the sole source of truth: there are no per-card
name lookups, overrides, or hard-coded card knowledge anywhere in this module,
so renaming a card cannot change its profile.

Only the Python standard library is used.
"""

from __future__ import annotations

import math
import re
from typing import Any

__all__ = ["PROFILE_KEYS", "draw_profile"]

PROFILE_KEYS = (
    "status",
    "mechanism",
    "net_cards",
    "mana_value",
    "activation_mana",
    "prerequisites",
    "evidence",
    "confidence",
    "caveats",
)

# --- status / mechanism / confidence vocabularies -------------------------------

STATUS_SUPPORTED = "supported"  # a recognised draw shape was parsed
STATUS_UNKNOWN = "unknown"  # draw wording present, but the shape is unsupported
STATUS_NONE = "none"  # the card's Oracle text contains no draw wording

MECHANISM_IMMEDIATE = "immediate"
MECHANISM_RECURRING_SELF = "recurring_self"
MECHANISM_RECURRING_OPPONENT = "recurring_opponent"
MECHANISM_ACTIVATED = "activated"
MECHANISM_CONDITIONAL = "conditional"

CONFIDENCE_SUPPORTED = "supported"
CONFIDENCE_PARTIAL = "partial"

NUMBER_WORDS = {
    "a": 1,
    "an": 1,
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
    "eleven": 11,
    "twelve": 12,
}
_NUM_ALT = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))

DRAW_AMOUNT_RE = re.compile(
    r"\bdraws?\s+(?:up\s+to\s+)?(?P<n>"
    + _NUM_ALT
    + r"|x|\d+)\s+(?:more\s+|additional\s+)?cards?\b"
)
DISCARD_AMOUNT_RE = re.compile(
    r"\bdiscards?\s+(?P<n>" + _NUM_ALT + r"|x|\d+)\s+cards?\b"
)
SCALING_RE = re.compile(
    r"\bfor each\b|\bequal to\b|\bthat many\b|\{x\}|\bx cards?\b|\bup to\b"
)
LIFE_LOSS_RE = re.compile(r"\blos(?:e|es)\s+\d+\s+life\b")
PAYS_RE = re.compile(r"\bunless that player pays\s+((?:\{[^}]*\})+)")


# --------------------------------------------------------------------------------
# Text handling helpers
# --------------------------------------------------------------------------------


def _mask_reminders(text: str) -> str:
    """Blank out parenthesised reminder text while preserving character offsets.

    Offsets are preserved so that evidence can be sliced out of the *original*
    string and therefore always be an exact substring of it.
    """
    return re.sub(r"\([^)]*\)", lambda m: " " * len(m.group(0)), text)


def _sentence_spans(text: str, masked: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of sentence-like chunks, newline- and period-delimited."""
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[^.\n]*\.|[^.\n]+", masked):
        start, end = match.start(), match.end()
        # Trim using the ORIGINAL characters so the slice stays an exact substring.
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        if not masked[start:end].strip():
            continue  # chunk was entirely reminder text
        spans.append((start, end))
    return spans


def _number(token: str) -> int | None:
    token = token.strip().lower()
    if token in NUMBER_WORDS:
        return NUMBER_WORDS[token]
    if token.isdigit():
        return int(token)
    return None  # "x" and anything else is not a fixed quantity


def _mana_symbols_value(cost: str) -> tuple[int | None, bool]:
    """Sum the mana symbols in ``cost``.

    Returns (value, exact). ``exact`` is False when a symbol could not be valued
    conservatively (e.g. ``{X}`` or hybrid), in which case value is None.
    """
    symbols = re.findall(r"\{([^}]*)\}", cost)
    total = 0
    for raw in symbols:
        sym = raw.strip().upper()
        if sym.isdigit():
            total += int(sym)
        elif sym in {"W", "U", "B", "R", "G", "C", "S"}:
            total += 1
        elif sym == "T" or sym == "Q":
            continue  # tap/untap symbols carry no mana value
        else:
            return None, False
    return total, True


def _mana_value(card: dict[str, Any]) -> int | None:
    cmc = card.get("cmc")
    if isinstance(cmc, bool):
        cmc = None
    if isinstance(cmc, (int, float)) and math.isfinite(cmc) and cmc >= 0:
        return int(cmc) if float(cmc).is_integer() else cmc
    cost = card.get("mana_cost")
    if isinstance(cost, str) and cost.strip():
        value, exact = _mana_symbols_value(cost)
        if exact:
            return value
    return None


# --------------------------------------------------------------------------------
# Clause classification
# --------------------------------------------------------------------------------


def _split_trigger(sentence_low: str) -> tuple[str, str]:
    """Split a triggered-ability sentence into (trigger, effect).

    The split point is the last comma whose suffix still mentions drawing, which
    keeps intervening 'if ...' clauses on the trigger side while tolerating
    effects that themselves contain commas.
    """
    best: int | None = None
    for match in re.finditer(r",", sentence_low):
        if re.search(r"\bdraws?\b", sentence_low[match.end() :]):
            best = match.end()
    if best is None:
        return sentence_low, sentence_low
    return sentence_low[:best], sentence_low[best:]


def _is_spell(type_line: str) -> bool:
    low = type_line.lower()
    return "instant" in low or "sorcery" in low


def _classify(sentence_low: str, type_line: str) -> dict[str, str] | None:
    """Classify one draw-bearing sentence, or return None if the shape is unsupported."""
    stripped = sentence_low.strip()

    activated = re.match(r"\s*(?P<cost>[^:]{1,80}):\s*(?P<effect>.+)$", stripped)
    if activated and "{" in activated.group("cost"):
        return {
            "kind": MECHANISM_ACTIVATED,
            "cost": activated.group("cost"),
            "trigger": activated.group("cost"),
            "effect": activated.group("effect"),
        }

    if re.search(r"\bwould draw\b", stripped) and "instead" in stripped:
        head, _, tail = stripped.partition("instead")
        return {
            "kind": MECHANISM_CONDITIONAL,
            "cost": "",
            "trigger": head,
            "effect": tail,
        }

    if stripped.startswith(("whenever", "at the beginning")):
        trigger, effect = _split_trigger(stripped)
        opponent_trigger = bool(
            re.search(r"whenever (?:an|each|a) opponent\b", trigger)
            or re.search(r"\bopponents?\s+(?:casts?|draws?|plays?)\b", trigger)
        )
        kind = (
            MECHANISM_RECURRING_OPPONENT
            if opponent_trigger
            else MECHANISM_RECURRING_SELF
        )
        return {"kind": kind, "cost": "", "trigger": trigger, "effect": effect}

    if _is_spell(type_line) and not stripped.startswith("as an additional cost"):
        return {
            "kind": MECHANISM_IMMEDIATE,
            "cost": "",
            "trigger": "",
            "effect": stripped,
        }

    return None


def _drawer(effect_low: str) -> str | None:
    """Identify who draws: 'you', 'target_player', 'opponent', or None."""
    effect = effect_low.strip().lstrip(",").strip()
    if re.search(r"\byou (?:may )?draws?\b", effect) or re.search(
        r"\byou gain \d+ life and draw\b", effect
    ):
        return "you"
    if re.match(r"(?:then\s+)?draws?\b", effect) or re.search(r", then draw\b", effect):
        return "you"  # imperative wording addresses the controller
    if re.search(r"\btarget player draws?\b", effect):
        return "target_player"
    if re.search(r"\b(?:each|that|an|the)\s+(?:opponent|player)s?\s+draws?\b", effect):
        return "opponent"
    if re.search(r"\bopponents?\s+draws?\b", effect):
        return "opponent"
    return None


# --------------------------------------------------------------------------------
# Prerequisite extraction
# --------------------------------------------------------------------------------


def _prerequisites(clause: dict[str, str], full_low: str) -> list[str]:
    trigger = clause["trigger"]
    effect = clause["effect"]
    prereqs: list[str] = []

    def add(token: str) -> None:
        if token not in prereqs:
            prereqs.append(token)

    if clause["kind"] == MECHANISM_ACTIVATED:
        if "{t}" in clause["cost"]:
            add("cost:tap_self")
        value, exact = _mana_symbols_value(clause["cost"])
        if exact and value:
            add(f"cost:mana:{value}")
        elif not exact:
            add("cost:mana:unknown")

    if re.search(r"at the beginning of your upkeep", trigger):
        add("trigger:your_upkeep")
    if re.search(r"at the beginning of your (?:end step|draw step)", trigger):
        add("trigger:your_end_or_draw_step")

    if re.search(r"whenever an opponent casts", trigger):
        add("trigger:opponent_casts_spell")

    if re.search(r"opponent (?:would )?draws?\b", trigger):
        if re.search(
            r"second card each turn|third card each turn|except the first one", trigger
        ):
            add("trigger:opponent_draws_extra_card")
        else:
            add("trigger:opponent_draws_card")
    if re.search(
        r"except the first one they draw in each of their draw steps", trigger
    ):
        add("excludes:first_draw_step_card")

    cast = re.search(
        r"whenever you cast (?:a|an|another)\s+(?P<what>[a-z]+)\s+spell", trigger
    )
    if cast:
        add("trigger:you_cast_spell")
        add("typal:{}".format(cast.group("what")))
    elif re.search(r"whenever you cast (?:a|an|another) spell", trigger):
        add("trigger:you_cast_spell")

    if re.search(
        r"creature you control enters|creature enters the battlefield under your control",
        trigger,
    ):
        add("trigger:creature_you_control_enters")
        if "nontoken" in trigger:
            add("restriction:nontoken")
        if re.search(r"doesn't have the same name", trigger):
            add("condition:unique_name")
        typal = re.search(
            r"whenever (?:a|an|another) (?:nontoken )?(?P<what>[a-z]+) you control enters",
            trigger,
        )
        if typal and typal.group("what") not in {"creature", "permanent", "nontoken"}:
            add("typal:{}".format(typal.group("what")))

    if re.search(r"equipped creature dies", trigger):
        add("trigger:equipped_creature_dies")
        add("requires:attached_to_creature")
    elif re.search(r"\bcreatures?\b[^,]*\b(?:dies|die)\b", trigger):
        add("trigger:creature_dies")
        if re.search(r"\bother creatures?\b", trigger):
            add("restriction:other_creatures")
        if re.search(
            r"creature you control (?:dies|die)|creatures you control (?:dies|die)",
            trigger,
        ):
            add("restriction:creature_you_control")

    if re.search(r"deals combat damage to a player", trigger):
        add("trigger:combat_damage_to_player")
        if re.search(r"creature you control deals", trigger):
            add("requires:creature_you_control")

    if re.search(r"\btarget player\b", effect):
        add("target:player")

    pays = PAYS_RE.search(effect)
    if pays:
        add(f"opponent_may_pay:{pays.group(1)}")

    if re.search(r"\byou may draw\b", effect):
        add("optional:controller_may")

    if SCALING_RE.search(effect):
        add("scaling:variable")

    sacrifice = re.search(
        r"as an additional cost to cast this spell,\s*sacrifice (?:a|an|one)\s+(?P<what>[a-z]+)",
        full_low,
    )
    if sacrifice:
        add("cost:sacrifice_{}".format(sacrifice.group("what")))
    elif "as an additional cost to cast this spell" in full_low:
        add("cost:additional_unparsed")

    if "this ability triggers only once each turn" in full_low:
        add("limit:once_each_turn")

    return sorted(prereqs)


# --------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------


def _empty_profile(
    status: str,
    mana_value: int | None,
    confidence: str,
    caveats: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "mechanism": None,
        "net_cards": None,
        "mana_value": mana_value,
        "activation_mana": None,
        "prerequisites": [],
        "evidence": [],
        "confidence": confidence,
        "caveats": list(caveats or []),
    }


def draw_profile(card: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic draw-fact profile for ``card``.

    ``card`` is expected to expose ``oracle_text`` (str), and optionally
    ``type_line`` (str), ``mana_cost`` (str) and ``cmc`` (number). The ``name``
    field, if present, is never read.
    """
    text = card.get("oracle_text") or ""
    if not isinstance(text, str):
        text = ""
    type_line = card.get("type_line") or ""
    if not isinstance(type_line, str):
        type_line = ""

    mana_value = _mana_value(card)
    masked = _mask_reminders(text)
    masked_low = masked.lower()

    if not re.search(r"\bdraws?\b", masked_low):
        return _empty_profile(STATUS_NONE, mana_value, CONFIDENCE_SUPPORTED)

    spans = _sentence_spans(text, masked)
    candidates: list[tuple[tuple[int, int], dict[str, str], str | None]] = []
    draw_sentences = 0
    for span in spans:
        sentence_low = masked_low[span[0] : span[1]]
        if not re.search(r"\bdraws?\b", sentence_low):
            continue
        draw_sentences += 1
        clause = _classify(sentence_low, type_line)
        if clause is None:
            continue
        who = _drawer(clause["effect"])
        if who is None:
            continue
        candidates.append((span, clause, who))

    if not candidates:
        return _empty_profile(
            STATUS_UNKNOWN,
            mana_value,
            CONFIDENCE_PARTIAL,
            [
                (
                    "Oracle text mentions drawing but matches no supported shape; "
                    "no draw facts were extracted."
                )
            ],
        )

    # Prefer a clause that draws cards for the controller, then an elective
    # target-player clause, then anything else. Ties resolve by text order.
    priority = {"you": 0, "target_player": 1, "opponent": 2}
    span, clause, who = min(candidates, key=lambda c: (priority.get(c[2], 3), c[0][0]))

    effect = clause["effect"]
    full_low = masked_low
    caveats: list[str] = []
    partial = False

    # --- amount --------------------------------------------------------------
    amount: int | None = None
    match = DRAW_AMOUNT_RE.search(effect)
    if match:
        amount = _number(match.group("n"))
    elif re.search(r"\bdraws? a card\b", effect):
        amount = 1
    if SCALING_RE.search(effect):
        amount = None
        caveats.append(
            "Draw quantity scales with a variable (X, counters, or a count); "
            "net_cards is not fixed."
        )
        partial = True
    elif amount is None:
        caveats.append("Draw quantity could not be read from the printed text.")
        partial = True

    # --- net cards per event -------------------------------------------------
    net: int | None = amount
    mechanism = clause["kind"]

    if who == "opponent":
        net = None
        caveats.append(
            "Cards are drawn by a player other than you; "
            "no net card gain for you is claimed."
        )
        partial = True
    elif mechanism == MECHANISM_IMMEDIATE and net is not None:
        net -= 1  # the spell consumes itself from your hand
        caveats.append("Net includes the spell itself leaving your hand.")
        if who == "target_player":
            caveats.append(
                "Net assumes you choose yourself as the target; "
                "targeting another player instead yields a net of -1 for you."
            )
            partial = True
    elif who == "target_player":
        net = None
        caveats.append(
            "The drawing player is chosen on resolution; "
            "net card gain for you is not fixed."
        )
        partial = True

    if mechanism != MECHANISM_IMMEDIATE:
        caveats.append(
            "net_cards is measured per triggering/activation event and "
            "excludes the cost of casting or maintaining this permanent."
        )

    # --- mandatory discard ---------------------------------------------------
    if re.search(r"discards? (?:your|their) hand", effect):
        net = None
        caveats.append("An accompanying hand discard makes the net unknown.")
        partial = True
    else:
        discard = DISCARD_AMOUNT_RE.search(effect)
        if discard:
            optional_discard = bool(
                re.search(r"\bmay\s+(?:\w+\s+){0,3}?discard", effect)
            )
            count = _number(discard.group("n"))
            if optional_discard:
                caveats.append("An optional discard is printed; it is not subtracted.")
                partial = True
            elif count is None:
                net = None
                caveats.append("A variable discard is printed; net is unknown.")
                partial = True
            elif net is not None:
                net -= count
                caveats.append(f"A mandatory discard of {count} card(s) is subtracted.")

    # --- sacrifice costs -----------------------------------------------------
    if re.search(r"as an additional cost to cast this spell,\s*sacrifice", full_low):
        net = None
        caveats.append(
            "A sacrificed permanent may be a token, so the card-count "
            "impact of the cost is unknown."
        )
        partial = True

    # --- optionality / dependence -------------------------------------------
    pays = PAYS_RE.search(effect)
    if pays:
        caveats.append(
            f"The draw does not happen if that player pays {pays.group(1)}; "
            "the printed text makes it their choice."
        )
        partial = True
    if re.search(r"\byou may draw\b", effect) and not pays:
        caveats.append("The draw is optional for you ('you may').")

    if mechanism == MECHANISM_CONDITIONAL:
        caveats.append(
            "This is a replacement effect; it applies only when the "
            "described draw would otherwise occur."
        )
        partial = True
    if re.search(
        r"except the first one they draw in each of their draw steps", clause["trigger"]
    ):
        caveats.append("The replacement excludes each opponent's first draw-step card.")
    if re.search(r"opponent (?:would )?draws?", clause["trigger"]):
        caveats.append(
            "Frequency depends on opponents drawing cards; "
            "with no extra draws this never triggers."
        )
        partial = True

    if re.search(r"doesn't have the same name", clause["trigger"]):
        caveats.append("An intervening name condition must hold for the draw to occur.")
        partial = True

    if LIFE_LOSS_RE.search(effect):
        caveats.append(
            "An accompanying life loss is printed; it is not a card-count effect."
        )

    if "this ability triggers only once each turn" in full_low:
        caveats.append("The ability is printed as triggering only once each turn.")

    if re.search(r"\bflashback\b|\bescape\b|\bjump-start\b|\bretrace\b", full_low):
        caveats.append(
            "An alternative casting option is printed; net_cards describes "
            "a single resolution only."
        )
        partial = True

    if re.search(r"\bequip \{", full_low):
        caveats.append(
            "An equip cost must be paid before this ability can trigger; "
            "that cost is not included in net_cards."
        )

    if draw_sentences > 1 or len(candidates) > 1:
        caveats.append(
            "The card prints more than one draw clause; this profile "
            "describes the first clause that draws cards for you."
        )
        partial = True

    # --- activation mana -----------------------------------------------------
    activation_mana: int | None = None
    if mechanism == MECHANISM_ACTIVATED:
        value, exact = _mana_symbols_value(clause["cost"])
        if exact:
            activation_mana = value
        else:
            caveats.append(
                "The activation cost contains a symbol that cannot be "
                "valued conservatively."
            )
            partial = True

    # --- evidence ------------------------------------------------------------
    evidence: list[str] = [text[span[0] : span[1]]]

    def add_evidence(pattern: str) -> None:
        for sp in spans:
            if re.search(pattern, masked_low[sp[0] : sp[1]]):
                snippet = text[sp[0] : sp[1]]
                if snippet not in evidence:
                    evidence.append(snippet)
                return

    if "as an additional cost to cast this spell" in full_low:
        add_evidence(r"as an additional cost to cast this spell")
    if "this ability triggers only once each turn" in full_low:
        add_evidence(r"this ability triggers only once each turn")
    if re.search(r"\bflashback\b", full_low):
        add_evidence(r"\bflashback\b")
    if re.search(r"\bequip \{", full_low):
        add_evidence(r"\bequip \{")

    prerequisites = _prerequisites(clause, full_low)

    # Confidence measures extraction coverage, not how often the effect happens.
    # Known opponent gates and variable quantities remain explicit prerequisites.
    partial = False
    if who == "opponent":
        return _empty_profile(
            (
                STATUS_UNKNOWN
                if "each player" in effect or mechanism.startswith("recurring")
                else STATUS_NONE
            ),
            mana_value,
            (
                CONFIDENCE_PARTIAL
                if "each player" in effect or mechanism.startswith("recurring")
                else CONFIDENCE_SUPPORTED
            ),
            ["No supported draw effect for the controller."],
        )
    if amount is None and not SCALING_RE.search(effect):
        partial = True
    if draw_sentences > 1 or len(candidates) > 1:
        partial = True
    if "cost:additional_unparsed" in prerequisites:
        partial = True
    trigger = clause["trigger"]
    if mechanism in {MECHANISM_RECURRING_SELF, MECHANISM_RECURRING_OPPONENT}:
        known_triggers = (
            r"at the beginning of your (?:upkeep|end step|draw step)",
            r"whenever an opponent casts a spell",
            r"whenever an opponent draws their second card each turn",
            r"whenever you cast (?:a|an|another) (?:[a-z]+ )?spell",
            r"whenever (?:a|an|another) (?:nontoken )?creature you control enters",
            r"whenever a nontoken creature you control enters, if it doesn't have the same name as another creature you control or a creature card in your graveyard",
            r"whenever equipped creature dies",
            r"whenever one or more other creatures die",
            r"whenever (?:a|an|another) creature(?: you control)? dies",
            r"whenever a creature you control deals combat damage to a player",
        )
        if not any(
            re.fullmatch(pattern, trigger.rstrip(", ")) for pattern in known_triggers
        ):
            prerequisites.append("condition:unparsed_trigger")
            partial = True
        if not any(p.startswith("trigger:") for p in prerequisites):
            prerequisites.append("condition:unparsed_trigger")
            partial = True
        if "if " in trigger and "condition:unique_name" not in prerequisites:
            prerequisites.append("condition:unparsed_gate")
            partial = True
    if mechanism == MECHANISM_CONDITIONAL and not (
        "trigger:opponent_draws_extra_card" in prerequisites
        and "excludes:first_draw_step_card" in prerequisites
        and "you draw" in effect
    ):
        partial = True
    if re.search(r"\bif\b|\bonly if\b", effect):
        prerequisites.append("condition:unparsed_effect_gate")
        partial = True
    if "unless" in effect and not PAYS_RE.search(effect):
        prerequisites.append("condition:unparsed_unless")
        partial = True
    if mechanism == MECHANISM_IMMEDIATE and SCALING_RE.search(effect):
        partial = True
    if mechanism == MECHANISM_ACTIVATED:
        parsed_cost = re.sub(r"\{[^}]+\}|[,\s]", "", clause["cost"])
        # These exact finite-resource shapes have both a cost and a printed cap.
        # The cap is shared with other abilities spending/adding those counters.
        finite_resources = (
            (
                r"(?:\{[^}]+\}[,\s]*)+remove a brick counter from this artifact",
                r"this artifact enters with three brick counters on it\.",
                3,
            ),
            (
                r"(?:\{[^}]+\}[,\s]*)+put a page counter on this artifact",
                r"when there are four or more page counters on this artifact, exile it\.",
                4,
            ),
        )
        for cost_pattern, source_pattern, limit in finite_resources:
            if re.fullmatch(cost_pattern, clause["cost"]) and re.search(
                source_pattern, full_low
            ):
                parsed_cost = ""
                prerequisites.append(f"resource:draw_activations:{limit}")
                add_evidence(source_pattern)
                caveats.append(
                    f"At most {limit} draw activations from the printed counter resource; other abilities can consume this allowance."
                )
                break
        if activation_mana is None or parsed_cost:
            prerequisites.append("cost:unparsed_activation")
            partial = True
        if "{q}" in clause["cost"]:
            prerequisites.append("cost:untap_self")
        if "charge counter" in effect:
            prerequisites.append("scaling:charge_counters")
    # Costs and restrictions in a separate sentence still constrain the draw.
    restrictions_low = full_low
    for pattern, identifier in (
        (
            r"activate only if you created a token this turn\.",
            "condition:created_token_this_turn",
        ),
        (
            r"activate only if you control three or more lands with the same name\.",
            "condition:three_lands_same_name",
        ),
    ):
        if re.search(pattern, full_low):
            prerequisites.append(identifier)
            restrictions_low = re.sub(pattern, "", restrictions_low)
            add_evidence(pattern)
    unsupported_side_effects = (
        r"you can't cast (?:more than|spells)|you may cast only|cast no more than",
        r"skip (?:your|that|the) (?:next )?(?:turn|untap|draw|combat)",
        r"put .*(?:on top|on the bottom).*library",
        r"shuffle .*card.*from your hand.*library",
        r"\bspree\b|\bchoose (?:one|two)\b|•",
        r"gains? control of",
        r"activate only",
        r"draw only",
        r"until end of turn",
        r"at the beginning.*sacrifice",
        r"exile .*card.*from your hand",
        r"costs? .* more to activate",
        r"\becho\s+\{|cumulative upkeep",
        r"at the beginning.*\bpay\b",
        r"maximum hand size.*reduced",
        r"\bblight\b",
    )
    if any(
        re.search(pattern, restrictions_low) for pattern in unsupported_side_effects
    ):
        prerequisites.append("condition:unparsed_global_restriction")
        partial = True
        net = None
    if "discard" in full_low and "discard" not in effect:
        prerequisites.append("cost:separate_discard_unparsed")
        partial = True
        net = None
    if _is_spell(type_line) and mechanism != MECHANISM_IMMEDIATE:
        prerequisites.append("restriction:nonpermanent_trigger_duration")
        partial = True
    if _is_spell(type_line) and not card.get("mana_cost"):
        prerequisites.append("cost:no_printed_mana_cost")
        partial = True
    if partial:
        caveats.append(
            "Some conditions or draw clauses are not fully parsed; do not treat as verified gain."
        )
    prerequisites = sorted(set(prerequisites))

    return {
        "status": STATUS_SUPPORTED,
        "mechanism": mechanism,
        "net_cards": net,
        "mana_value": mana_value,
        "activation_mana": activation_mana,
        "prerequisites": prerequisites,
        "evidence": evidence,
        "confidence": CONFIDENCE_PARTIAL if partial else CONFIDENCE_SUPPORTED,
        "caveats": caveats,
    }

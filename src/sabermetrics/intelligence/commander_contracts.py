"""Bounded, name-invariant reader of Magic Oracle records.

Two public APIs:

    commander_profile(commander) -> dict
    contribution(card, commander) -> dict

Both report ``coverage == "incomplete"`` unconditionally. Nothing here is a
substitution recommendation: a contract that is not detected, or a contribution
whose value is ``False``/``None``, means *this parser found no evidence* -- it
never means a swap is safe or that a relation is absent from the real card.

Detection is purely structural (regex over ``oracle_text`` / ``type_line``).
No card names are hard-coded and the ``name`` field is never read, so output is
invariant under renaming.
"""

import math
import re

COVERAGE = "incomplete"

_BASE_CAVEATS = (
    "coverage is incomplete: only the patterns implemented here are detected",
    "absence of a detected relation never proves a safe substitution",
    "evidence strings are exact substrings of the supplied oracle_text or type_line",
    "the 'name' field is never read; output is invariant under renaming",
)

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

# Grammatical / rules words that may appear capitalized but are not creature types.
_STOPWORDS = {
    "this",
    "each",
    "when",
    "whenever",
    "target",
    "create",
    "creature",
    "other",
    "another",
    "all",
    "you",
    "your",
    "the",
    "a",
    "an",
    "tap",
    "untap",
    "add",
    "draw",
    "sacrifice",
    "exile",
    "destroy",
    "put",
    "return",
    "spend",
    "activate",
    "menace",
    "flying",
    "vigilance",
    "defender",
    "land",
    "permanent",
    "player",
    "opponent",
    "card",
    "token",
    "spell",
    "if",
    "at",
    "as",
    "for",
    "it",
    "its",
    "that",
    "those",
    "up",
    "may",
    "search",
    "library",
    "hand",
    "graveyard",
    "battlefield",
    "damage",
    "life",
    "mana",
    "counter",
    "turn",
    "combat",
    "attack",
    "block",
    "gain",
    "lose",
    "number",
}

_CARD_TYPES = {
    "artifact",
    "battle",
    "creature",
    "enchantment",
    "instant",
    "kindred",
    "land",
    "planeswalker",
    "sorcery",
    "tribal",
}

_TRIBE_REF = re.compile(r"([A-Z][a-z]+) you control")
_TRIBE_SPELL = re.compile(r"cast an? ([A-Z][a-z]+) spell")
_TRIBE_CARD = re.compile(r"for an? ([A-Z][a-z]+) card")
_TRIBE_LOOSE = re.compile(r"\b([A-Z][a-z]+)s? (?:spells?|cards?)\b")
_TAP_THRESHOLD = re.compile(
    r"[Tt]ap ({}) (untapped )?([A-Z][a-z]+) you control".format("|".join(_NUMBER_WORDS))
)
_CAST_TRIGGER = re.compile(r"[Ww]henever you cast an? ([A-Za-z][A-Za-z ]*?) spell")
_MANA_RESTRICTION = re.compile(
    r"Spend this mana only to cast an? ([A-Za-z][A-Za-z ]*?) spell"
)
_TOKEN_CLAUSE = re.compile(r"[Cc]reates? [^.\n]*?creature tokens?[^.\n]*\.?")
_TOKEN_TYPES = re.compile(
    r"\d+/\d+ [a-z]+(?:[, and]+ [a-z]+)* ((?:[A-Z][a-z]+ )+)creature token"
)
_COUNT_BASIS = re.compile(r"the number of ([A-Z][a-z]+) you control")
_FOR_EACH_BASIS = re.compile(r"for each ([A-Z][a-z]+) you (?:already )?control")
_DEFENDER_SENTENCE = re.compile(r"[^.\n]*\bwith defender\b[^.\n]*\.?")
_MV_THRESHOLD = re.compile(r"mana value (\d+) or (less|greater)")
_MV_MENTION = re.compile(r"[^.\n]*\bmana value\b[^.\n]*\.?")
_POWER_SENTENCE = re.compile(
    r"[^.\n]*\b(?:where X is|equal to)\b[^.\n]*\bpower\b[^.\n]*\.?"
)
_KEYWORD_LINE = re.compile(r"^[A-Za-z][A-Za-z' \-]*(?:, [A-Za-z][A-Za-z' \-]*)*$")


def _text(card, key):
    value = card.get(key) if isinstance(card, dict) else None
    return value if isinstance(value, str) else ""


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _singular(word):
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tribe(word):
    return _slug(_singular(word))


def split_type_line(type_line):
    """Return (types, subtypes) as lowercase lists; em dash or hyphen separated."""
    type_line = type_line.split(" // ")[0]
    head, _, tail = type_line.replace("—", "-").partition("-")
    types = [t.lower() for t in head.split() if t.lower() in _CARD_TYPES]
    subtypes = [s.strip() for s in tail.split() if s.strip()]
    return types, subtypes


def creature_types(card):
    """Printed creature subtypes only. Tokens a card creates are NOT its subtypes."""
    types, subtypes = split_type_line(_text(card, "type_line"))
    return [s for s in subtypes] if "creature" in types else []


def cast_categories(card):
    """Categories under which this card is cast. Lands are never cast: they yield []."""
    types, _ = split_type_line(_text(card, "type_line"))
    if "land" in types:
        return []
    spell_types = list(types)
    if not spell_types:
        return []
    categories = list(spell_types)
    if "creature" not in spell_types:
        categories.append("noncreature")
    if {"instant", "sorcery"} & set(spell_types):
        categories.append("instant or sorcery")
    return categories


def has_defender_keyword(card):
    """True only if 'Defender' appears as a printed keyword line, not as a mention."""
    for line in _text(card, "oracle_text").split("\n"):
        line = re.sub(r"\([^)]*\)", "", line).strip().rstrip(".")
        if not line or not _KEYWORD_LINE.match(line):
            continue
        if any(part.strip().lower() == "defender" for part in line.split(",")):
            return True
    return False


def token_subtypes_produced(card):
    """Creature subtypes of tokens the card's text creates (distinct from printed subtypes)."""
    produced = []
    for match in _TOKEN_TYPES.finditer(_text(card, "oracle_text")):
        for word in match.group(1).split():
            slug = _slug(word)
            if slug and slug not in produced:
                produced.append(slug)
    return produced


def printed_mana_value(card):
    """Printed mana value from the record's cmc field, or None. Never defaults to 0."""
    value = card.get("cmc") if isinstance(card, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value) if float(value).is_integer() else float(value)


def _contract(kind, scope, requirements, evidence, confidence):
    return {
        "kind": kind,
        "scope": scope,
        "requirements": requirements,
        "evidence": list(dict.fromkeys(evidence)),
        "confidence": confidence,
    }


def _tribal_contracts(oracle, subtypes, caveats):
    parsed, contracts = {}, []
    for pattern, basis in (
        (_TRIBE_REF, "count_you_control"),
        (_TRIBE_SPELL, "cast_tribal_spell"),
        (_TRIBE_CARD, "search_tribal_card"),
    ):
        for match in pattern.finditer(oracle):
            tribe = _tribe(match.group(1))
            if tribe in _STOPWORDS:
                continue
            entry = parsed.setdefault(tribe, {"bases": [], "evidence": []})
            if basis not in entry["bases"]:
                entry["bases"].append(basis)
            entry["evidence"].append(match.group(0))

    thresholds = {}
    for match in _TAP_THRESHOLD.finditer(oracle):
        tribe = _tribe(match.group(3))
        thresholds[tribe] = {
            "count_threshold": _NUMBER_WORDS[match.group(1)],
            "state": "untapped" if match.group(2) else "any",
            "action": "tap_as_cost",
            "controlled": True,
        }
        entry = parsed.setdefault(tribe, {"bases": [], "evidence": []})
        entry["evidence"].append(match.group(0))

    for tribe, entry in parsed.items():
        requirements = {
            "basis": entry["bases"] or ["oracle_reference"],
            "controlled": True,
        }
        requirements.update(thresholds.get(tribe, {}))
        contracts.append(
            _contract(
                "tribal",
                f"tribal:{tribe}",
                requirements,
                entry["evidence"],
                "supported",
            )
        )

    for word in {_tribe(m.group(1)) for m in _TRIBE_LOOSE.finditer(oracle)}:
        if word in _STOPWORDS or word in parsed:
            continue
        caveats.append(f"tribal-looking reference '{word}' was not fully parsed")
        contracts.append(
            _contract(
                "tribal",
                f"tribal:{word}",
                {"basis": ["unparsed_reference"]},
                [
                    m.group(0)
                    for m in _TRIBE_LOOSE.finditer(oracle)
                    if _tribe(m.group(1)) == word
                ],
                "partial",
            )
        )

    for subtype in subtypes:
        tribe = _slug(subtype)
        if any(c["scope"] == f"tribal:{tribe}" for c in contracts):
            continue
        contracts.append(
            _contract(
                "tribal",
                f"tribal:printed:{tribe}",
                {"basis": ["printed_subtype"], "implies_tribal_payoff": False},
                [subtype],
                "partial",
            )
        )
    return contracts


def _cast_contracts(oracle):
    contracts = []
    for match in _CAST_TRIGGER.finditer(oracle):
        category = match.group(1)
        sentence_end = oracle.find(".", match.start())
        context = oracle[
            match.start() : sentence_end + 1 if sentence_end >= 0 else len(oracle)
        ]
        gated = bool(
            re.search(
                r"\bif\b|\bunless\b|spell (?:with|that)\b", context, re.IGNORECASE
            )
        )
        scope = (
            (f"cast:tribal:{_tribe(category)}")
            if category[:1].isupper()
            else f"cast:{_slug(category)}"
        )
        contracts.append(
            _contract(
                "cast",
                scope,
                {
                    "trigger": "on_cast",
                    "controller": "you",
                    "category": category.lower(),
                },
                [match.group(0), context],
                "partial" if gated else "supported",
            )
        )
    for match in _MANA_RESTRICTION.finditer(oracle):
        category = match.group(1)
        sentence_end = oracle.find(".", match.start())
        context = oracle[
            match.start() : sentence_end + 1 if sentence_end >= 0 else len(oracle)
        ]
        gated = bool(
            re.search(
                r"\bif\b|\bunless\b|spell (?:with|that)\b", context, re.IGNORECASE
            )
        )
        scope = (
            (f"cast:tribal:{_tribe(category)}")
            if category[:1].isupper()
            else f"cast:{_slug(category)}"
        )
        contracts.append(
            _contract(
                "cast",
                scope,
                {"restriction": "mana_spend_only", "category": category.lower()},
                [match.group(0)],
                "supported",
            )
        )
    return contracts


def _token_contracts(oracle):
    contracts = []
    for match in _TOKEN_CLAUSE.finditer(oracle):
        clause = match.group(0)
        produced = token_subtypes_produced({"oracle_text": clause})
        count = _COUNT_BASIS.search(clause) or _FOR_EACH_BASIS.search(clause)
        if count:
            requirements = {
                "scaling_basis": "count_permanents",
                "counted_type": _tribe(count.group(1)),
                "controlled": True,
            }
            confidence = "supported"
        else:
            requirements = {
                "scaling_basis": "prior_event_or_unparsed",
                "counted_type": None,
            }
            confidence = "partial"
        scope = "token_scaling:produced:%s" % ("_".join(produced) or "unparsed")
        contracts.append(
            _contract("token_scaling", scope, requirements, [clause], confidence)
        )
    return contracts


def _defender_contracts(oracle):
    contracts = []
    for match in _DEFENDER_SENTENCE.finditer(oracle):
        sentence = match.group(0)
        if "enters" in sentence:
            scope, confidence = "defender:etb", "supported"
        elif "combat damage" in sentence or "attack" in sentence:
            scope, confidence = "defender:combat", "supported"
        else:
            scope, confidence = "defender:reference", "partial"
        contracts.append(
            _contract(
                "defender",
                scope,
                {
                    "requires_keyword": "defender",
                    "printed_subtype_sufficient": False,
                    "zone": "battlefield",
                },
                [sentence],
                confidence,
            )
        )
    return contracts


def _mana_value_contracts(oracle):
    contracts, matched = [], False
    for match in _MV_THRESHOLD.finditer(oracle):
        matched = True
        contracts.append(
            _contract(
                "mana_value",
                "mana_value:{}_or_{}".format(*match.groups()),
                {"threshold": int(match.group(1)), "direction": match.group(2)},
                [match.group(0)],
                "supported",
            )
        )
    if not matched:
        for match in _MV_MENTION.finditer(oracle):
            contracts.append(
                _contract(
                    "mana_value",
                    "mana_value:unparsed",
                    {"threshold": None, "direction": None},
                    [match.group(0)],
                    "partial",
                )
            )
    return contracts


def _power_contracts(oracle):
    return [
        _contract(
            "power",
            "power:unparsed_reference",
            {"basis": "power_reference", "dynamic": True, "simulated": False},
            [m.group(0)],
            "partial",
        )
        for m in _POWER_SENTENCE.finditer(oracle)
        if "rather than" not in m.group(0)
    ]


def commander_profile(commander):
    """Structural contracts detected in a commander record. Always incomplete coverage."""
    oracle = _text(commander, "oracle_text")
    _, subtypes = split_type_line(_text(commander, "type_line"))
    caveats = list(_BASE_CAVEATS)
    contracts = (
        _tribal_contracts(oracle, subtypes, caveats)
        + _cast_contracts(oracle)
        + _token_contracts(oracle)
        + _defender_contracts(oracle)
        + _mana_value_contracts(oracle)
        + _power_contracts(oracle)
    )
    caveats.append(
        "printed subtypes are reported separately from tribal payoffs and "
        "from token subtypes a card produces"
    )
    if not oracle:
        caveats.append("no oracle_text supplied; no contract could be detected")
    return {"coverage": COVERAGE, "contracts": contracts, "caveats": caveats}


def _contribution(kind, scope, value, evidence, confidence):
    return {
        "kind": kind,
        "scope": scope,
        "value": value,
        "evidence": list(dict.fromkeys(evidence)),
        "confidence": confidence,
    }


def _tribal_contribution(contract, card_types, type_line):
    tribe = contract["scope"].split(":")[-1]
    match = next((t for t in card_types if _slug(t) == tribe), None)
    evidence = [match] if match and match in type_line else []
    if "count_threshold" in contract["requirements"]:
        # One body toward an explicit threshold; never evidence the cost can be paid.
        return _contribution(
            "tribal", contract["scope"], 1 if match else 0, evidence, "partial"
        )
    confidence = "partial" if contract["confidence"] == "partial" else "supported"
    return _contribution("tribal", contract["scope"], bool(match), evidence, confidence)


def _cast_contribution(contract, card, categories):
    scope, parts = contract["scope"], contract["scope"].split(":")
    if parts[1] == "tribal":
        _, printed_subtypes = split_type_line(_text(card, "type_line"))
        match = bool(categories) and any(_slug(t) == parts[2] for t in printed_subtypes)
        evidence = (
            [t for t in printed_subtypes if _slug(t) == parts[2]] if categories else []
        )
        return _contribution(
            "cast", scope, bool(match), evidence, contract["confidence"]
        )
    category = contract["requirements"].get("category", parts[-1])
    value = category in categories
    evidence = [_text(card, "type_line")] if value else []
    return _contribution("cast", scope, value, evidence, contract["confidence"])


def contribution(card, commander):
    """What a card structurally offers against a commander's detected contracts."""
    profile = commander_profile(commander)
    type_line = _text(card, "type_line")
    card_types, categories = creature_types(card), cast_categories(card)
    produced = token_subtypes_produced(card)
    caveats = list(_BASE_CAVEATS)
    caveats.append(
        "mana value is read from the record's numeric 'cmc' field, not from "
        "oracle text, and is None when absent rather than 0"
    )
    caveats.append(
        "power/toughness are not present in these records; no combat or "
        "activation outcome is simulated"
    )
    caveats.append(
        "token subtypes a card produces are not that card's printed subtypes"
    )
    if not categories and "land" in split_type_line(type_line)[0]:
        caveats.append("lands are not cast; no cast-category contribution is possible")

    contributions = []
    for contract in profile["contracts"]:
        kind, scope = contract["kind"], contract["scope"]
        if kind == "tribal":
            contributions.append(_tribal_contribution(contract, card_types, type_line))
        elif kind == "cast":
            contributions.append(_cast_contribution(contract, card, categories))
        elif kind == "token_scaling":
            counted = contract["requirements"].get("counted_type")
            if counted:
                match = next((t for t in card_types if _slug(t) == counted), None)
                contributions.append(
                    _contribution(
                        kind,
                        scope + ":counted_body",
                        1 if match else 0,
                        [match] if match else [],
                        "partial",
                    )
                )
            wanted = set(scope.split(":")[-1].split("_"))
            overlap = bool(wanted & set(produced))
            evidence = [
                m.group(0) for m in _TOKEN_CLAUSE.finditer(_text(card, "oracle_text"))
            ]
            contributions.append(
                _contribution(
                    kind,
                    scope + ":token_producer",
                    bool(overlap),
                    evidence if overlap else [],
                    "partial",
                )
            )
        elif kind == "defender":
            keyword = has_defender_keyword(card)
            evidence = (
                [
                    m.group(0)
                    for m in re.finditer(
                        r"\bdefender\b", _text(card, "oracle_text"), re.IGNORECASE
                    )
                ][:1]
                if keyword
                else []
            )
            contributions.append(
                _contribution(
                    kind,
                    scope,
                    keyword,
                    evidence,
                    "supported" if keyword else "partial",
                )
            )
        elif kind == "mana_value":
            value = printed_mana_value(card)
            confidence = (
                "supported"
                if (
                    value is not None
                    and contract["requirements"].get("threshold") is not None
                )
                else "partial"
            )
            contributions.append(_contribution(kind, scope, value, [], confidence))
        elif kind == "power":
            contributions.append(_contribution(kind, scope, None, [], "partial"))

    return {
        "coverage": COVERAGE,
        "contributions": contributions,
        "creature_types": card_types,
        "cast_categories": categories,
        "caveats": caveats,
    }

"""Bounded recognizer for mechanical card functions in Magic Oracle text.

`function_profile(card)` reports which *supported* mechanical functions a card's
printed Oracle text exposes, so a caller can reason about what a replacement
candidate would have to reproduce. It deliberately does not rate cards, rank
them, or claim equivalence: it is a template matcher over a bounded set of
clause shapes, not an Oracle parser and not a rules engine.

Status semantics:
    supported - recognized function clauses; never proof of complete coverage
    partial   - some functions recognized, other relevant clauses unmodeled
    unknown   - printed text present but no template matched
    none      - no printed Oracle text to analyze
"""

import re
from typing import Any

WORD_NUMBERS = {
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
}
COLOR_WORDS = {"white", "blue", "black", "red", "green", "colorless"}
LAND_WORDS = {"forest", "plains", "island", "swamp", "mountain", "land", "lands"}
CARD_TYPE_WORDS = {
    "creature",
    "land",
    "artifact",
    "enchantment",
    "instant",
    "sorcery",
    "planeswalker",
    "battle",
    "permanent",
}
GRANTABLE_HASTE = {"haste"}
GRANTABLE_PROTECTION = {"hexproof", "shroud", "indestructible", "ward"}
RELEVANT_WORDS = (
    "target",
    "destroy",
    "exile",
    "counter",
    "draw",
    "discard",
    "search",
    "token",
    "create",
    "sacrifice",
    "add ",
    "mana",
    "haste",
    "hexproof",
    "shroud",
    "damage",
    "life",
    "regenerat",
    "return",
    "look",
    "put",
    "cost",
    "shuffle",
    "+1/+1",
    "gains",
    "untap",
    "tap",
    "flying",
    "trample",
    "vigilance",
    "lifelink",
    "deathtouch",
    "menace",
    "flash",
    "protection",
    "first strike",
    "sacrifice",
    "copy",
)
IGNORABLE = (re.compile(r"^Equip\b"), re.compile(r"^Equipped creature\s*$"))

BASE_CAVEATS = [
    "coverage incomplete: only a bounded set of clause templates is recognized; this is not a full Oracle parser",
    "an empty or short function list never proves a replacement is safe, only that nothing was recognized",
    "recognized functions are printed facts; availability, timing, targeting legality and board state are not modeled",
]

TRIGGER_TEMPLATES = [
    (
        re.compile(r"Whenever you cast an instant or sorcery spell"),
        "trigger:cast_instant_or_sorcery",
    ),
    (re.compile(r"Whenever you cast a creature spell"), "trigger:cast_creature_spell"),
    (re.compile(r"Whenever an opponent casts a spell"), "trigger:opponent_casts_spell"),
    (re.compile(r"Whenever you cast ([^,]+?) spell"), "trigger:cast_spell_subset"),
    (re.compile(r"When(?:ever)? [^,]*?\benters\b"), "trigger:enters_the_battlefield"),
    (re.compile(r"\bWhen(ever)?\b"), "trigger:triggered_ability_unclassified"),
]
ACTIVATION_RE = re.compile(r"^((?:\{[^}]+\})(?:\s*,\s*\{[^}]+\})*)\s*:")


def _mask_reminders(text):
    """Blank parenthetical reminder text, preserving all character offsets."""
    return re.sub(r"\([^)]*\)", lambda m: " " * len(m.group(0)), text)


def _clauses(masked):
    """Yield (start, end, text) for sentence-like chunks of the masked text."""
    out = []
    offset = 0
    for line in masked.split("\n"):
        for match in re.finditer(r"[^.]+\.?", line):
            chunk = match.group(0)
            if chunk.strip():
                out.append((offset + match.start(), offset + match.end(), chunk))
        offset += len(line) + 1
    return out


def _number(word):
    word = (word or "").lower()
    if word.isdigit():
        return int(word)
    return WORD_NUMBERS.get(word)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_") or "unspecified"


def _plural(phrase):
    """Naive pluralization of the last word of a tribe/type phrase (Elf -> elves)."""
    words = phrase.strip().lower().split()
    if not words:
        return "unspecified"
    last = words[-1]
    if last.endswith("f"):
        last = last[:-1] + "ves"
    elif last.endswith(("s", "x", "ch", "sh")):
        last = last + "es"
    else:
        last = last + "s"
    return _slug(" ".join(words[:-1] + [last]))


def _containing_clause(clauses, position):
    for start, end, text in clauses:
        if start <= position < end:
            return text
    return ""


def _context_prerequisites(clause, type_line):
    """Prerequisites implied by the trigger or activation cost wrapping a clause."""
    prereqs = []
    body = clause.strip()
    activation = ACTIVATION_RE.match(body)
    if activation:
        symbols = activation.group(1).replace(" ", "")
        prereqs.append(
            "cost:tap_self" if symbols == "{T}" else f"cost:activate_{symbols}"
        )
        if "{T}" in symbols and "Creature" in type_line:
            prereqs.append("requires:creature_without_summoning_sickness")
    else:
        for pattern, label in TRIGGER_TEMPLATES:
            if pattern.search(body):
                prereqs.append(label)
                trigger_text = body.split(",", 1)[0]
                prereqs.append("trigger_scope:" + _slug(trigger_text))
                if label == "trigger:cast_spell_subset":
                    prereqs.append(
                        "requires:spell_subset:" + _slug(pattern.search(body).group(1))
                    )
                break
    return prereqs


class _Collector:
    def __init__(self, original, masked, type_line):
        self.original = original
        self.masked = masked
        self.type_line = type_line
        self.clauses = _clauses(masked)
        self.functions = []
        self.covered = []
        self.notes = []

    def add(self, kind, detail, match, prerequisites=(), context=True):
        span = (match.start(), match.end())
        self.covered.append(span)
        evidence = self.original[span[0] : span[1]].strip()
        snippets = [evidence]
        confidence = "supported"
        prereqs = list(prerequisites)
        if context:
            clause = _containing_clause(self.clauses, span[0])
            for start, end, _ in self.clauses:
                if start <= span[0] < end:
                    context_evidence = self.original[start:end].strip()
                    if context_evidence not in snippets:
                        snippets.append(context_evidence)
                    break
            if re.search(
                r"\b(?:unless|if)\b|that has an adventure|with power|with mana value",
                clause,
                re.IGNORECASE,
            ):
                confidence = "partial"
            if ":" in clause and not ACTIVATION_RE.match(clause.strip()):
                confidence = "partial"
                prereqs.append("cost:unparsed_activation")
            for prereq in _context_prerequisites(clause, self.type_line):
                if prereq not in prereqs:
                    prereqs.append(prereq)
            if re.search(r"\b(may|unless|if)\b", clause):
                note = f"clause is optional or conditional; condition not modeled: {clause.strip()!r}"
                if note not in self.notes:
                    self.notes.append(note)
        if "trigger:triggered_ability_unclassified" in prereqs:
            confidence = "partial"
        self.functions.append(
            {
                "kind": kind,
                "detail": detail,
                "prerequisites": prereqs,
                "evidence": snippets,
                "confidence": confidence,
            }
        )

    def finditer(self, pattern, flags=0):
        return list(re.finditer(pattern, self.masked, flags))


def _detect_interaction(c):
    for verb, kindname in (("Destroy", "destroy"), ("Exile", "exile")):
        for m in c.finditer(rf"{verb} target ([\w ]+?)(?=[.,])"):
            c.add("interaction", f"{kindname}_target:{_slug(m.group(1))}", m)
    for m in c.finditer(r"Counter target ([\w ]+?)(?=[.,])"):
        c.add("interaction", f"counter_target:{_slug(m.group(1))}", m)
    for m in c.finditer(
        r"deals? (\d+|X) damage to (any target|target [\w ]+?)(?=[.,])"
    ):
        c.add("interaction", f"damage_target:{_slug(m.group(2))}:{m.group(1)}", m)


def _detect_no_regeneration(c):
    for m in c.finditer(r"(?:It|They) can't be regenerated"):
        c.add("interaction", "removal_rider:no_regeneration", m, context=False)


def _detect_search(c):
    for m in c.finditer(r"[Ss]earch your library for ([^.]*?)(?=\.)"):
        body = m.group(1)
        head = body.split(",")[0]
        words = head.split()
        named = [w for w in words if w[:1].isupper()]
        typed = [w for w in words if w.lower() in CARD_TYPE_WORDS]
        restriction = "_".join(named + typed) or "any"
        mv = re.search(r"mana value (\d+) or less", body)
        if mv:
            restriction += f":mv_le_{mv.group(1)}"
        prereqs = ["requires:matching_card_in_library", "cost:shuffle_library"]
        lowered = body.lower()
        if "onto the battlefield" in lowered:
            if any(w.lower() in LAND_WORDS for w in named) or "basic land" in lowered:
                c.add("mana", f"ramp_land_onto_battlefield:{restriction}", m, prereqs)
            else:
                c.add("tutor", f"tutor_to_battlefield:{restriction}", m, prereqs)
        elif "into your hand" in lowered:
            c.add("tutor", f"tutor_to_hand:{restriction}", m, prereqs)
        elif "on top" in lowered:
            c.add("tutor", f"tutor_to_top_of_library:{restriction}", m, prereqs)
        else:
            c.add("tutor", f"tutor_destination_unmodeled:{restriction}", m, prereqs)


def _detect_mana(c):
    for m in c.finditer(
        r"\{T\}: Add (one mana of any color|\{[WUBRGC]\}(?:\s*\{[WUBRGC]\})*)"
    ):
        produced = m.group(1)
        detail = (
            "mana_ability:any_color"
            if produced.startswith("one mana")
            else "mana_ability:{}".format(produced.replace(" ", ""))
        )
        c.add("mana", detail, m)


def _detect_tokens(c):
    for m in c.finditer(
        r"[Cc]reates?\s+(?P<qty>[\w]+)\s+(?P<body>[^.]*?)\s+creature tokens?(?P<tail>[^.]*)"
    ):
        body, tail = m.group("body"), m.group("tail")
        power = re.search(r"(\d+|X)/(\d+|X)", body)
        pt = power.group(0) if power else "unspecified_pt"
        types = [
            w for w in body.split() if w[:1].isupper() and w.lower() not in COLOR_WORDS
        ]
        for_each = re.search(r"for each ([\w ]+?)(?: you control)?$", tail.strip())
        count = "variable" if for_each else (_number(m.group("qty")) or "variable")
        detail = "create_token:{}_{}:count={}".format(
            pt, "_".join(types) or "unspecified_type", count
        )
        clause = _containing_clause(c.clauses, m.start())
        if (
            re.search(r"(Its|That player's|Their) controller creates", clause)
            or "Its controller creates" in clause
        ):
            detail += ":controlled_by=target_controller"
        prereqs = []
        if for_each:
            tribe = for_each.group(1).strip().lower()
            plural = "elves" if tribe == "elf" else tribe + "s"
            prereqs.append(f"requires:{_slug(plural)}_on_battlefield")
        c.add("tokens", detail, m, prereqs)


def _detect_cost_reduction(c):
    for m in c.finditer(
        r"([A-Z][\w ]*?) spells you cast cost \{([^}]+)\} less to cast"
    ):
        subset, amount = m.group(1), m.group(2)
        axis = "generic" if amount.isdigit() else "colored"
        c.add(
            "cost_reduction",
            f"spell_cost_reduction:{axis}:{{{amount}}}",
            m,
            [f"applies:{_slug(subset)}_spells"],
        )
    for m in c.finditer(r"\bDelve\b"):
        c.add(
            "cost_reduction",
            "delve:exile_graveyard_cards_to_pay_generic",
            m,
            ["cost:graveyard_cards"],
            context=False,
        )


def _detect_grants(c):
    pattern = r"(Equipped creature|Creatures you control|Enchanted creature) (?:has|have|gains|gain) ([^.]*?)(?=\.)"
    for m in c.finditer(pattern):
        scope = _slug(m.group(1))
        keywords = [
            k.strip().lower() for k in re.split(r",| and ", m.group(2)) if k.strip()
        ]
        prereqs = (
            ["requires:attached_to_creature"]
            if scope != "creatures_you_control"
            else []
        )
        for keyword in keywords:
            if keyword in GRANTABLE_HASTE:
                c.add("haste", f"grants_haste:{scope}", m, prereqs)
            elif keyword in GRANTABLE_PROTECTION:
                c.add("protection", f"grants_{keyword}:{scope}", m, prereqs)
    for start, end, text in c.clauses:
        body = text.strip().rstrip(".")
        parts = [p.strip().lower() for p in re.split(r",| and ", body) if p.strip()]
        if not parts or not all(
            p in GRANTABLE_HASTE | GRANTABLE_PROTECTION for p in parts
        ):
            continue
        for keyword in parts:
            kind = "haste" if keyword in GRANTABLE_HASTE else "protection"
            c.covered.append((start, end))
            c.functions.append(
                {
                    "kind": kind,
                    "detail": f"self_{keyword}",
                    "prerequisites": [],
                    "evidence": [c.original[start:end].strip()],
                    "confidence": "supported",
                }
            )


def _detect_selection(c):
    for m in c.finditer(
        r"Look at the top (\w+) cards? of your library, then put them back in any order"
    ):
        c.add(
            "selection", "reorder_top_cards:%s" % (_number(m.group(1)) or m.group(1)), m
        )
    pattern = (
        r"Look at the top (\w+) cards? of your library\. Put (\w+) of them into your hand "
        r"and the rest on the bottom of your library in any order"
    )
    for m in c.finditer(pattern):
        looked, taken = _number(m.group(1)) or m.group(1), _number(
            m.group(2)
        ) or m.group(2)
        c.add("selection", f"dig_select:look_{looked}_take_{taken}_rest_bottom", m)
        c.add("card_flow", f"cards_to_hand:{taken}", m)
    for m in c.finditer(
        r"put (\w+) cards? from your hand on top of your library in any order"
    ):
        c.add(
            "selection",
            "hand_to_top_of_library:%s" % (_number(m.group(1)) or m.group(1)),
            m,
        )


def _detect_self_return(c):
    for m in c.finditer(r"put this \w+ on top of its owner's library"):
        c.add("selection", "self_to_top_of_library", m)


def _detect_card_flow(c):
    wheel = c.finditer(
        r"Each player discards their hand, then draws cards equal to[^.]*(?=\.)"
    )
    for m in wheel:
        c.add("card_flow", "wheel:each_player_discards_hand_then_redraws", m)
        note = (
            "symmetrical effect: opponents also gain the benefit; this is not weighed"
        )
        if note not in c.notes:
            c.notes.append(note)
    for m in c.finditer(r"[Dd]raws? (\w+) cards?"):
        count = _number(m.group(1))
        if count is not None:
            clause = _containing_clause(c.clauses, m.start())
            before = clause[: clause.lower().find(m.group(0).lower())].lower()
            if re.search(r"(?:each|target|an) opponent\s*$", before):
                recipient = "opponent"
            elif re.search(r"each player\s*$", before):
                recipient = "each_player"
            elif re.search(r"target player\s*$", before):
                recipient = "target_player"
            elif re.search(r"that player\s*$", before):
                recipient = "unparsed_player"
            else:
                recipient = "controller"
            c.add("card_flow", f"draw:{count}", m, ["recipient:" + recipient])
            if recipient == "unparsed_player":
                c.functions[-1]["confidence"] = "partial"
    if not wheel:
        for m in c.finditer(r"[Dd]iscards? (their hand|\w+ cards?)"):
            target = m.group(1)
            count = _number(target.split()[0])
            c.add(
                "card_flow",
                "discard:%s" % ("hand" if "hand" in target else count or "variable"),
                m,
            )


DETECTORS = (
    _detect_interaction,
    _detect_no_regeneration,
    _detect_self_return,
    _detect_search,
    _detect_mana,
    _detect_tokens,
    _detect_cost_reduction,
    _detect_grants,
    _detect_selection,
    _detect_card_flow,
)


def _creature_types(type_line):
    if "—" not in type_line and "-" not in type_line:
        return []
    type_line = type_line.split(" // ")[0]
    parts = re.split(r"—|-", type_line, maxsplit=1)
    left, right = parts[0], parts[1] if len(parts) > 1 else ""
    if "creature" not in left.lower():
        return []
    return [w for w in right.split() if w]


def _dedupe(functions):
    merged = {}
    for fn in functions:
        key = (fn["kind"], fn["detail"])
        if key in merged:
            target = merged[key]
            if fn.get("confidence") == "partial":
                target["confidence"] = "partial"
            for item in fn["evidence"]:
                if item not in target["evidence"]:
                    target["evidence"].append(item)
            for prereq in fn["prerequisites"]:
                if prereq not in target["prerequisites"]:
                    target["prerequisites"].append(prereq)
        else:
            merged[key] = fn
    return [merged[k] for k in sorted(merged)]


def _uncovered(collector):
    leftovers = []
    for start, end, text in collector.clauses:
        body = text.strip()
        if not body or any(p.match(body) for p in IGNORABLE):
            continue
        if any(s < end and start < e for s, e in collector.covered):
            continue
        lowered = body.lower()
        if any(word in lowered for word in RELEVANT_WORDS):
            leftovers.append(body)
    return leftovers


def function_profile(card: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded function profile for a card dict.

    card: {"oracle_text": str, "type_line": str, ...}. Card name is never used.
    """
    oracle = (card or {}).get("oracle_text") or ""
    type_line = (card or {}).get("type_line") or ""
    oracle = oracle if isinstance(oracle, str) else ""
    type_line = type_line if isinstance(type_line, str) else ""
    masked = _mask_reminders(oracle)
    collector = _Collector(oracle, masked, type_line)
    for detector in DETECTORS:
        detector(collector)
    functions = _dedupe(collector.functions)
    leftovers = _uncovered(collector)
    # Whole-clause evidence preserves context; a matched substring does not prove
    # every cost or side effect in that clause was interpreted.
    for fn in functions:
        for evidence in fn["evidence"]:
            if re.search(
                r"put this .*on top|exile .*from your hand|costs .*more to activate|\bunless\b",
                evidence,
                re.IGNORECASE,
            ):
                fn["confidence"] = "partial"
                if "condition:unparsed_context" not in fn["prerequisites"]:
                    fn["prerequisites"].append("condition:unparsed_context")

    caveats = list(BASE_CAVEATS) + list(collector.notes)
    for clause in leftovers:
        caveats.append(
            f"unmodeled clause, treat as a possible lost function: {clause!r}"
        )

    if not oracle.strip():
        status = "none"
    elif (
        functions
        and not leftovers
        and all(fn["confidence"] == "supported" for fn in functions)
    ):
        status = "supported"
    elif functions:
        status = "partial"
    else:
        status = "unknown"
    if status in ("partial", "unknown"):
        caveats.append(
            f"status {status}: unmodeled text may carry functions, so equivalence cannot be implied"
        )

    evidence = []
    for fn in functions:
        for item in fn["evidence"]:
            if item not in evidence:
                evidence.append(item)
    return {
        "status": status,
        "coverage": "incomplete",
        "functions": functions,
        "creature_types": _creature_types(type_line),
        "evidence": evidence,
        "caveats": caveats,
    }

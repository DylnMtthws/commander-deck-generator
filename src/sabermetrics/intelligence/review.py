"""Small falsifiable checks on model claims, never a general rules verifier."""

import re


def contradictions(card: dict, reasoning: str, commander: dict) -> list[str]:
    errors = []
    text = reasoning.lower()
    words = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
    }
    oracle = str(card.get("oracle_text") or "").lower()
    conditional = "rather than pay" in oracle or "without paying" in oracle
    for match in re.finditer(
        r"\b(?:a|an|this is a) (zero|one|two|three|four|five|six|seven)[ -]mana (?:instant|sorcery|spell|pump|artifact|creature|aura|counterspell)\b",
        text,
    ):
        if not conditional and words[match[1]] != float(card.get("cmc") or 0):
            errors.append("Model mana-cost claim contradicts printed card data.")
    types = str(card.get("type_line") or "").split(" // ")[0].lower()
    cmdr = str(commander.get("oracle_text") or "").lower()
    name = str(commander.get("name") or "").split(",")[0].lower()
    if (
        name
        and "whenever you cast a noncreature spell" in cmdr
        and "creature" not in types
        and "land" not in types
    ) and re.search(
        r"(?:it|this(?: card| spell| artifact| sorcery)?) (?:does not|doesn't) trigger "
        + re.escape(name),
        text,
    ):
        errors.append("Model cast-trigger claim contradicts commander and card types.")
    return list(dict.fromkeys(errors))

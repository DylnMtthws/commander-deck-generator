"""Printed card-type eligibility independent of upstream legality flags."""

import re

_MAIN_TYPES = {
    "artifact",
    "battle",
    "creature",
    "enchantment",
    "instant",
    "land",
    "planeswalker",
    "sorcery",
}
_SUPPLEMENTS = {
    "card",
    "conspiracy",
    "dungeon",
    "phenomenon",
    "plane",
    "scheme",
    "sticker",
    "stickers",
    "vanguard",
    "token",
    "emblem",
}


def main_deck_eligible(card):
    """Conservative front-face type grammar; this does not decide format bans."""
    typ = card.get("type_line") or ""
    front = typ.split("//")[0].strip().lower()
    head, _, subtypes = front.partition("—")
    types = set(re.findall(r"[a-z]+", head))
    if types & _SUPPLEMENTS or not types & _MAIN_TYPES:
        return False
    # Attractions/Contraptions belong to their separate supplementary decks.
    return not (set(re.findall(r"[a-z]+", subtypes)) & {"attraction", "contraption"})

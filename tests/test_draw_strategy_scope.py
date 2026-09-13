"""Printed typal prerequisites missed by the original commander compiler."""

from sabermetrics.intelligence.strategy import make_plan, matches_requirement


def test_plural_elf_activation_is_an_explicit_requirement():
    commander = {
        "name": "Lathril, Blade of the Elves",
        "type_line": "Legendary Creature — Elf Noble",
        "oracle_text": "Menace\nWhenever Lathril, Blade of the Elves deals combat damage to a player, create that many 1/1 green Elf Warrior creature tokens.\n{T}, Tap ten untapped Elves you control: Each opponent loses 10 life and you gain 10 life.",
    }
    plan = make_plan(commander, None, 3)
    assert plan.requirements == {"creature_type:elf": 16}
    assert matches_requirement(
        {"type_line": "Creature — Elf Druid"}, "creature_type:elf"
    )
    assert not matches_requirement(
        {"type_line": "Creature — Human Druid", "oracle_text": "Create an Elf token."},
        "creature_type:elf",
    )


def test_angel_spell_requirement_is_recognized():
    commander = {
        "name": "Giada, Font of Hope",
        "type_line": "Legendary Creature — Angel",
        "oracle_text": "Flying, vigilance\nEach other Angel you control enters with an additional +1/+1 counter on it for each Angel you already control.\n{T}: Add {W}. Spend this mana only to cast an Angel spell.",
    }
    assert make_plan(commander, None, 3).requirements == {"creature_type:angel": 16}

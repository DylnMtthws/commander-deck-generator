"""Load real scoring configuration values (not mere file existence)."""

from __future__ import annotations

from typing import Any

import yaml

from sabermetrics.config import config_path, load_settings


def load_installed_scoring_values() -> dict[str, Any]:
    """Resolve packaged scoring YAML and return concrete expected fields."""
    from sabermetrics.analytics.archetype_signatures import load_library
    from sabermetrics.analytics.synergy_matrix import _load_synergy_rules
    from sabermetrics.pipeline.mana_base import load_karsten_config

    settings = load_settings()
    rules = _load_synergy_rules()
    karsten = load_karsten_config()
    auto_includes = yaml.safe_load(config_path("auto_include_cards.yaml").read_text()) or {}
    game_changers = yaml.safe_load(config_path("game_changers.yaml").read_text()) or {}
    categories = yaml.safe_load(config_path("functional_categories.yaml").read_text()) or {}
    overrides = yaml.safe_load(config_path("role_tag_overrides.yaml").read_text()) or {}
    library = load_library()

    always_names = [e["name"] for e in auto_includes.get("always", [])]
    gc_by_name = {
        gc["card_name"]: gc.get("bracket_threshold")
        for gc in game_changers.get("game_changers", [])
        if isinstance(gc, dict) and "card_name" in gc
    }
    csr = karsten.get("color_source_requirements") or {}
    one_pip = csr.get(1) or csr.get("1") or {}

    return {
        "profile_model": settings.llm.profile_model,
        "fit_model": settings.llm.fit_model,
        "monthly_cost_ceiling_usd": settings.llm.monthly_cost_ceiling_usd,
        "synergy_rule_weight": settings.scoring.synergy_rule_weight,
        "first_synergy_rule_id": rules[0]["id"] if rules else None,
        "first_synergy_rule_strength": rules[0]["strength"] if rules else None,
        "karsten_one_pip_turn_1": one_pip.get("turn_1"),
        "karsten_land_count_3": (karsten.get("land_count_targets") or {}).get("3.0"),
        "karsten_reference_land_count": karsten.get("reference_land_count"),
        "sol_ring_auto_include": "Sol Ring" in always_names,
        "dockside_bracket_threshold": gc_by_name.get("Dockside Extortionist"),
        "mana_crypt_bracket_threshold": gc_by_name.get("Mana Crypt"),
        "aristocrats_archetype": "aristocrats" in library.archetypes,
        "treasure_generation_category": "treasure_generation"
        in (categories.get("categories") or {}),
        "rhystic_study_roles": (overrides.get("overrides") or {})
        .get("Rhystic Study", {})
        .get("role_tags"),
    }


def assert_installed_scoring_values(values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assert packaged scoring YAML contains the real expected constants."""
    values = values if values is not None else load_installed_scoring_values()
    assert values["profile_model"] == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    assert values["fit_model"] == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    assert values["monthly_cost_ceiling_usd"] == 15.0
    assert values["synergy_rule_weight"] == 0.615
    assert values["first_synergy_rule_id"] == "tokens_with_sacrifice_payoff"
    assert values["first_synergy_rule_strength"] == 0.8
    assert values["karsten_one_pip_turn_1"] == 22
    assert values["karsten_land_count_3"] == 36
    assert values["karsten_reference_land_count"] == 36
    assert values["sol_ring_auto_include"] is True
    assert values["dockside_bracket_threshold"] == 4
    assert values["mana_crypt_bracket_threshold"] == 4
    assert values["aristocrats_archetype"] is True
    assert values["treasure_generation_category"] is True
    assert values["rhystic_study_roles"] == ["draw"]
    return values

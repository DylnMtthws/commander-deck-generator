"""Tests for configuration loading (A1.5 acceptance gate)."""

from pathlib import Path

from sabermetrics.config import Settings, config_path, load_settings


def test_settings_load_from_yaml() -> None:
    """Settings load from config/settings.yaml without error."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    settings = load_settings(config_path)

    assert settings.user.default_budget_usd == 200
    assert settings.user.default_power_target == 3
    assert settings.llm.profile_model == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    assert settings.llm.fit_model == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    assert settings.llm.monthly_cost_ceiling_usd == 15.0
    assert settings.pipeline.hard_filter_target == 3000
    assert settings.output.deck_format == "json"


def test_settings_defaults_when_no_file() -> None:
    """Settings return valid defaults when config file is missing."""
    settings = load_settings(Path("/nonexistent/settings.yaml"))

    assert isinstance(settings, Settings)
    assert settings.user.default_budget_usd == 200
    assert settings.llm.prompt_caching is True


def test_settings_weights_sum_to_one() -> None:
    """Default CVAR weights sum to 1.0."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    settings = load_settings(config_path)
    weights = settings.user.default_weights
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.001


def test_settings_module_singleton() -> None:
    """The module-level settings singleton loads successfully."""
    from sabermetrics.config import settings

    assert isinstance(settings, Settings)
    assert settings.user.default_budget_usd > 0


def test_config_path_function_resolves_settings() -> None:
    """Shared config_path contract returns the packaged settings file."""
    path = config_path("settings.yaml")
    assert path.is_file()
    assert path.name == "settings.yaml"
    loaded = load_settings(path)
    assert loaded.llm.monthly_cost_ceiling_usd == 15.0

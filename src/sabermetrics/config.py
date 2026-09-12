"""Configuration loader for Sabermetrics.

Resolves packaged YAML via :func:`config_path` (``SABER_CONFIG_DIR`` first,
then package data). ``load_settings(explicit_path)`` remains usable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Safe config resource names: basename only, yaml suffix, no traversal.
_SAFE_CONFIG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml$")

REQUIRED_CONFIG_FILES: tuple[str, ...] = (
    "settings.yaml",
    "synergy_rules.yaml",
    "archetype_signatures.yaml",
    "karsten_mana_base.yaml",
    "auto_include_cards.yaml",
    "game_changers.yaml",
    "functional_categories.yaml",
    "role_tag_overrides.yaml",
)

OPTIONAL_CONFIG_FILES: tuple[str, ...] = (
    "strategic_articles.yaml",
    "set_mechanics_articles.yaml",
)


class ConfigError(Exception):
    """Missing, unsafe, malformed, or unreadable configuration resource."""


class UserSettings(BaseModel):
    """User preference settings."""

    default_budget_usd: float = 200
    default_power_target: int = 3
    default_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "synergy": 0.40,
            "replacement_value": 0.30,
            "mana_efficiency": 0.30,
            "price_efficiency": 0.0,
        }
    )


class ModelPricing(BaseModel):
    """Conservative USD-per-million estimates; update when provider rates change."""

    input: float = Field(default=0.06, ge=0)
    cached_input: float = Field(default=0.015, ge=0)
    output: float = Field(default=0.18, ge=0)


class LLMSettings(BaseModel):
    """LLM model and cost settings."""

    profile_model: str = "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    fit_model: str = "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    synthesis_model: str = "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    refresh_model: str = "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    template_model: str = "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
    provider_pricing: ModelPricing = Field(default_factory=ModelPricing)
    max_candidates_for_llm_fit: int = 50
    prompt_caching: bool = True
    monthly_cost_ceiling_usd: float = 5.0


class EmbeddingSettings(BaseModel):
    """Embedding model settings."""

    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    device: str = "cpu"
    cache_dir: str = "./data/embedding_cache"


class PipelineSettings(BaseModel):
    """Filter pipeline settings."""

    hard_filter_target: int = 3000
    embedding_filter_target: int = 200
    structural_filter_target: int = 200
    candidates_per_slot: int = 5
    # Per-card price ceiling as a fraction of total budget. At 0.25, a $200
    # deck admits up to $50 cards. SME-set: cards above a quarter of the
    # budget are judged not worth the concentration at any power level.
    # The old value (0.10) hard-excluded premium staples (Smothering Tithe,
    # Esper Sentinel) from the pool before scoring ever saw them.
    per_card_budget_fraction: float = 0.25
    # Greedy affordability floor: every unfilled slot keeps at least this many
    # dollars reserved, so one expensive pick can never starve the rest of the
    # deck below a fillable minimum.
    # $1/slot: at $0.25 the floor was decorative -- Sauron's expensive
    # corpus staples (Bowmasters $44, Nazgul $17) drained greedy's budget
    # to ~$5 with 21 slots left, nothing was affordable under the reserve,
    # and legality backfilled 21 basics into a 57-land deck.
    budget_reserve_per_slot: float = 1.0


class RefreshSettings(BaseModel):
    """Data refresh schedule flags."""

    scryfall_daily: bool = True
    topdeck_weekly: bool = True
    decklist_sources_weekly: bool = True
    edhrec_weekly: bool = True
    mtgapi_rulings_monthly: bool = True
    set_refresh_quarterly: bool = True


class OutputSettings(BaseModel):
    """Output format settings."""

    deck_format: str = "json"
    include_alternatives: bool = True
    alternatives_per_slot: int = 3


class KnowledgeBaseSettings(BaseModel):
    """Knowledge base build settings."""

    game_knights_archidekt_owner: str = "GameKnights"
    game_knights_fallback_deck_ids: list[str] = Field(default_factory=list)
    edhrec_articles: list[dict[str, str]] = Field(default_factory=list)


class ScoringSettings(BaseModel):
    """Tunable scoring weights for the synergy matrix and greedy optimizer.

    Defaults match the values previously hard-coded in
    ``analytics.synergy_matrix`` and ``pipeline.greedy_optimizer``; centralizing
    them here lets the weights be swept from config without code edits.
    """

    # Synergy matrix: blend of two pairwise signals (sum to 1.0). The
    # commander-conditioned co-occurrence signal was removed in Option A
    # criterion 3 — the tracked-deck corpus (max 4 decks/commander) is far too
    # sparse to compute an honest conditional co-occurrence rate. Its 0.35 was
    # redistributed proportionally onto rules and embeddings.
    synergy_rule_weight: float = 0.615
    synergy_embedding_weight: float = 0.385

    # Card Win Equity (CWE): additive boost from TopDeck.gg tournament outcomes,
    # revived once real data was ingested. Sample-gated so low-evidence entries
    # don't move scores; only a positive win-equity delta boosts a card.
    cwe_weight: float = 0.20
    cwe_min_sample: int = 5

    # Greedy fill: marginal value of adding a card.
    marginal_synergy_weight: float = 0.45
    marginal_role_cvar_weight: float = 0.35
    marginal_cvar_weight: float = 0.20

    # Greedy fill: bonus for cards common in the target variant's real decks.
    # Added on top of the weights above rather than folded into them: rescaling
    # to keep a sum of 1.0 would shrink the synergy/CVAR weight of every card
    # with no corpus data, which penalizes absence. Absence must stay neutral --
    # an unpopular card is the moneyball thesis, not a defect (ADR-005).
    marginal_empirical_weight: float = 0.25
    marginal_empirical_noisy_weight: float = 0.15

    # Stage 4 role generators (ramp/draw/removal/protection): the same empirical
    # bonus, added to each generator's 0-1 quality score. Separate weights from
    # the greedy ones above because that stage scores on the marginal-value
    # scale; these are on the generators' normalized 0-1 scale.
    generator_empirical_weight: float = 0.20
    generator_empirical_noisy_weight: float = 0.12

    # Ramp color fit: bonus (x overlap fraction) for rocks producing the
    # deck's colors in 2+ color identities. Ramp-and-fix beats ramp alone.
    ramp_color_fit_weight: float = 0.20

    # Anti-synergy veto: multiplier applied to the quality score of a card
    # that mass-removes the deck's own engine type ("destroy all enchantments"
    # in an enchantress deck). Near-zero so it never wins a slot on points;
    # auto-include placement excludes such cards outright.
    anti_synergy_penalty: float = 0.15

    # Combat-gated payoff discount: multiplier for cards whose payoff is
    # locked behind attacking with multiple creatures (battalion, raid,
    # 'prepared' MDFCs), applied when the target variant's real decks run
    # too few creatures to meet the condition. Eiganjo Dynastorian's
    # "return all enchantments" back half kept winning replacement slots on
    # text-match points in a deck whose 18 creatures don't want to attack.
    combat_gated_discount: float = 0.5
    combat_gated_creature_min: int = 25

    # Budget rebalancing (Stage 7): minimum deck-objective gain for any move.
    # This is the spend-down stopping rule: keep buying upgrades while real
    # gains exist, stop when they go asymptotic -- leftover budget then means
    # the market had nothing left worth buying, not a failure to spend.
    rebalance_min_gain: float = 0.003

    # Infrastructure generators: bonus (0-1 score scale) for a card whose type
    # is still below its empirical target, so e.g. enchantment-based removal
    # outranks an equal instant while an enchantress deck is short on
    # enchantments. Only applies when the template carries corpus targets.
    generator_type_need_weight: float = 0.15

    # LLM safety net targeting: with a reliable corpus, review uncorroborated
    # picks (inclusion below this rate) before merely weak ones. Rule/embedding
    # matching can hallucinate synergy ("aura" in oracle text != good aura
    # deck card); zero-corpus cards that ranked highly are exactly where that
    # happens, and the weakest-N ordering never reviewed them.
    safety_uncorroborated_max_inclusion: float = 0.10

    # Empirical staple reservation (Stage 3.5): cards this common in the target
    # variant's real decks get a reserved differentiator slot before the role
    # generators and greedy run. This is what actually lands the engine pieces
    # the corpus validates but the role scorers reject (they are payoffs, not
    # ramp/removal). Bounded on purpose -- reserve only strong-consensus cards
    # and only a fraction of the differentiator budget, so most slots stay open
    # for the reasoning engine's undervalued picks (the moneyball goal).
    empirical_reserve_min_inclusion: float = 0.45
    empirical_reserve_max_slots: int = 12
    empirical_reserve_max_fraction: float = 0.5
    # Cap growth with corpus size: reserve up to this fraction of the
    # ELIGIBLE staples when there are more than max_slots of them. The
    # sweep found corpora with 29-80 consensus staples against the fixed
    # 12-slot cap -- sub-$1 near-universal cards (Cultivate at 74% on
    # Bumbleflower) missed while the cap sat sized for Eriette's corpus.
    # max_fraction of the differentiator budget still bounds the total, so
    # most slots stay open for the moneyball picks (ADR-005).
    empirical_reserve_eligible_fraction: float = 0.4

    # Deck-level objective (components, all 0-1 normalized). Type coherence
    # keeps swap/rebalance from trading the engine type away -- the objective
    # is what those stages maximize, and it previously had no notion that an
    # enchantress deck must stay enchantment-dense.
    objective_synergy_density_weight: float = 0.28
    objective_role_coverage_weight: float = 0.22
    objective_alignment_weight: float = 0.18
    objective_avg_cvar_weight: float = 0.14
    objective_curve_coherence_weight: float = 0.08
    objective_type_coherence_weight: float = 0.10


class Settings(BaseModel):
    """Top-level settings container."""

    user: UserSettings = Field(default_factory=UserSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embeddings: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    refresh: RefreshSettings = Field(default_factory=RefreshSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    knowledge_base: KnowledgeBaseSettings = Field(default_factory=KnowledgeBaseSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)


def _validate_config_name(name: str) -> str:
    """Return ``name`` if it is a safe YAML basename; raise otherwise."""
    if not name or not isinstance(name, str):
        raise ConfigError("Configuration name must be a non-empty string")
    # Reject separators before the regex so the error is explicit.
    if name != Path(name).name or "/" in name or "\\" in name or ".." in name:
        raise ConfigError(f"Unsafe configuration name: {name!r}")
    if not _SAFE_CONFIG_NAME.match(name):
        raise ConfigError(f"Unsafe configuration name: {name!r}")
    return name


def _packaged_config_dir() -> Path:
    """Directory of packaged YAML files next to this module."""
    return Path(__file__).resolve().parent / "config_data"


def _repo_config_dir() -> Path | None:
    """Repo-root ``config/`` when running from a source checkout (src layout)."""
    # src/sabermetrics/config.py -> parents[2] is the repository root.
    candidate = Path(__file__).resolve().parents[2] / "config"
    if candidate.is_dir():
        return candidate
    return None


def config_path(name: str) -> Path:
    """Resolve a configuration YAML to a concrete filesystem path.

    Order: ``SABER_CONFIG_DIR`` (if set), packaged ``config_data``, then the
    source-tree ``config/`` directory when present. Does not consult cwd.
    Raises :class:`ConfigError` for unsafe names or missing files.

    Args:
        name: Basename of a YAML file (e.g. ``synergy_rules.yaml``).

    Returns:
        Absolute path to an existing configuration file.
    """
    name = _validate_config_name(name)
    candidates: list[Path] = []

    explicit_dir = os.environ.get("SABER_CONFIG_DIR", "").strip()
    if explicit_dir:
        base = Path(explicit_dir).expanduser()
        if not base.is_dir():
            raise ConfigError(
                f"SABER_CONFIG_DIR is not a directory: {explicit_dir!r}"
            )
        candidates.append((base / name).resolve())
    else:
        candidates.append(_packaged_config_dir() / name)
        repo = _repo_config_dir()
        if repo is not None:
            candidates.append(repo / name)

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            return path

    searched = ", ".join(str(p) for p in candidates) or "(no search paths)"
    raise ConfigError(f"Required configuration file {name!r} not found. Looked in: {searched}")


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML file.

    Args:
        config_path: Explicit path to settings.yaml. If None, uses
            :func:`config_path`. An explicit path that does not exist
            returns defaults (existing API).

    Returns:
        Validated Settings object with defaults for any missing values.
    """
    settings_file = config_path
    if settings_file is None:
        settings_file = globals()["config_path"]("settings.yaml")

    if not settings_file.exists():
        return Settings()

    with open(settings_file) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ConfigError(f"Malformed settings file {settings_file}: expected a mapping")

    return Settings(**raw)


# Module-level singleton for easy access
settings = load_settings()

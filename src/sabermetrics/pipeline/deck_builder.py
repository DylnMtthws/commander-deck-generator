"""Deck builder orchestrator (D6.2, restructured for synergy optimizer).

Two preliminary steps run before the pipeline proper and are not counted as
stages: request validation, and commander profile acquisition (which may make
an LLM call and is billed). build() times them as metrics 1_validate and
2_profile.

Eight stages, listed as build() runs them. The labels match the inline
``# --- Stage`` comments; the numbering is historical rather than contiguous,
which is why 4.5 and 7b appear and why 5 and 6 share an entry:

1.   Hard filters + role tag loading
2.   Structural scoring + Pareto filter (remove dominated cards per role)
3.   Template derivation (profile-driven composition)
4.   Infrastructure fill (4 deterministic generators)
4.5  Empirical staple reservation -- consensus engine pieces the role scorers
     reject. Occupies differentiator slots, so greedy fills that many fewer
     and the deck still totals 99.
5+6  Synergy optimization, all inside _optimize_differentiators:
     role targets -> synergy matrix -> greedy fill -> swap refinement ->
     budget rebalancing (the step older comments call stage 7) ->
     engine-floor repair -> LLM safety vet.
     The vet is one batched call and is the final gate: it runs last within
     this stage precisely so nothing bypasses it.
7b.  Enforce Commander legality (exactly 99, singleton, in color identity)
8.   Synthesis + classify + persist

Note for anyone renumbering this: the stage labels are inconsistent elsewhere
in the codebase -- staple reservation is called 4.5 at line 905 but 3.5 at
line 1202 and in tests/test_empirical_reserve.py. Fixing that is a wider
change than this docstring.
"""

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from sabermetrics.errors import FatalError
from sabermetrics.models.card import Card
from sabermetrics.models.deck import (
    CardSubScores,
    ComponentCounts,
    CVARWeights,
    DeckCard,
    DeckClassification,
    DeckComposition,
    DeckNarrative,
    DeckParameters,
    GeneratedDeck,
    GenerationMeta,
    LLMFit,
)
from sabermetrics.pipeline.trace import GenerationTracer

logger = logging.getLogger(__name__)

# Per-variant empirical Pareto protection: a card in >= MIN_INCLUSION of the
# target variant's real decks is shielded from price-domination outright.
#
# Protection deliberately does NOT depend on how the dominator compares. An
# earlier version also required the dominator to be some margin rarer, on the
# theory that domination picks between substitutes and the corpus should break
# the tie. That is the wrong model: real decks run Pitiless Plunderer (65%) AND
# Deadly Dispute (55%) together. Cards that co-occur in most real decks are
# complements, so the margin between them is always small -- which meant the
# protection could never fire for the staples it existed to protect. Measured
# on Korvold, every one of the 6 eliminated staples was killed by another card
# from the same corpus, gaps ranging +0.02 to +0.18.
#
# The card's own inclusion rate is the whole signal: if it is in 65% of the
# variant's real decks, the corpus has already said it earns a slot. Only 68 of
# 1154 scored cards clear 0.30, so the exempt set stays small.
_EMPIRICAL_PROTECT_MIN_INCLUSION = 0.30


class DeckBuildRequest(BaseModel):
    """Request for deck generation."""

    commander_id: str
    budget_usd: float = Field(default=200.0, gt=0, allow_inf_nan=False)
    power_target: int = Field(default=3, ge=1, le=5)
    strategy: str | None = None
    weights: CVARWeights | None = None
    user_intent: str | None = None
    deck_name: str | None = None
    trace_cards: list[str] | None = None
    owner_id: str | None = None  # user who requested the build (cost attribution)
    deck_id: str | None = None  # pre-minted id (lets the caller attribute cost)


class DeckBuildResult(BaseModel):
    """Result of deck generation."""

    deck: GeneratedDeck
    profile_was_generated: bool
    total_cost_usd: float
    total_time_seconds: float
    pipeline_metrics: dict
    quality_warnings: list[dict] = Field(default_factory=list)


def _tokenize_engine_traits(raw_traits: list[str]) -> list[str]:
    """Extract matchable MTG keywords from LLM-generated trait descriptions.

    Profile engine_card_traits are full sentences (e.g. "Has the 'defender'
    keyword in oracle text") that never match substring checks against card
    oracle text. This tokenizes them into short MTG keywords like "defender".

    Args:
        raw_traits: LLM-generated trait description strings.

    Returns:
        Sorted list of unique matchable keyword strings.
    """
    from sabermetrics.analytics.oracle_keywords import MTG_KEYWORD_ABILITIES

    tokens: set[str] = set()
    type_keywords = {
        "wall",
        "artifact",
        "enchantment",
        "creature",
        "instant",
        "sorcery",
    }
    for trait in raw_traits:
        trait_lower = trait.lower()
        for kw in MTG_KEYWORD_ABILITIES:
            if re.search(r"\b" + re.escape(kw) + r"\b", trait_lower):
                tokens.add(kw)
        for type_kw in type_keywords:
            if re.search(r"\b" + re.escape(type_kw) + r"\b", trait_lower):
                tokens.add(type_kw)
    return sorted(tokens)


# Shared progress stages (jobs UI consumes these names). Completion is
# emitted only after persistence, never on a timer.
_PROGRESS_STAGES: dict[str, int] = {
    "validate": 5,
    "profile": 12,
    "filter": 22,
    "score": 35,
    "template": 42,
    "infrastructure": 55,
    "optimize": 70,
    "assemble": 74,
    "refine": 78,
    "review": 82,
    "simulate": 87,
    "narrative": 90,
    "persist": 96,
    "completed": 100,
}


class DeckBuilder:
    """Orchestrates end-to-end deck generation."""

    def __init__(
        self,
        db_path: Path,
        progress_callback: Callable[[str, int], None] | None = None,
        trace_names: tuple[str, ...] = (),
    ) -> None:
        self.db_path = db_path
        self._progress_callback = progress_callback
        self._candidate_trace_names = trace_names

    def _trace_candidates(self, stage, cards):
        trace = getattr(self, "_candidate_path", None)
        if trace is not None:
            trace.record(stage, cards)
            self._intelligence["candidate_path"] = trace.to_dict()

    def _emit_progress(self, stage: str) -> None:
        """Report a real pipeline stage. Progress is stage-boundary, not time."""
        progress = _PROGRESS_STAGES.get(stage)
        if progress is None:
            return
        callback = getattr(self, "_progress_callback", None)
        if callback is None:
            return
        callback(stage, progress)

    def build(self, request: DeckBuildRequest) -> DeckBuildResult:
        """Execute the eight-stage deck building pipeline.

        See the module docstring for the stage list and for the two
        preliminary steps (validation, profile acquisition) that run first
        and are not counted as stages.

        Args:
            request: Deck build parameters.

        Returns:
            DeckBuildResult with generated deck and metadata.
        """
        from sabermetrics.pipeline.intent import (
            admit_engine_candidates,
            engine_rationale_dump,
            parse_user_intent,
            verify_engine_in_deck,
        )
        from sabermetrics.pipeline.quality import (
            evaluate_final_deck,
            ledger_review_cost,
        )
        from sabermetrics.runtime import assert_readiness

        assert_readiness(self.db_path)
        start_time = time.time()
        metrics: dict[str, float] = {}
        total_cost = 0.0
        # Observable degradation: which signals were live for this build.
        self._signals: dict[str, bool] = {}
        self._stage_counts: dict[str, int] = {}
        self._quality_warnings: list[dict] = []
        self._review_failed = False
        self._protected_names: set[str] = set()
        self._engine_protect_names: set[str] = set()
        self._legality_backfill = 0
        self._stage_timings: dict[str, float] = {}
        self._engine_rationale = None
        self._intelligence = {}
        from sabermetrics.intelligence.candidate_trace import CandidateTrace

        names = getattr(self, "_candidate_trace_names", ())
        self._candidate_path = CandidateTrace(names) if names else None
        self._strategy_reserved = []

        # --- Build trace watchlist and create tracer ---
        watchlist: set[str] = set()
        if request.trace_cards:
            watchlist.update(request.trace_cards)
        # Add all auto-include card names
        try:
            from sabermetrics.pipeline.generators.ramp import _load_auto_includes

            auto_inc, _ = _load_auto_includes()
            for section_entries in auto_inc.values():
                if isinstance(section_entries, list):
                    for entry in section_entries:
                        watchlist.add(entry["name"])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning(
                "Optional trace or classification data unavailable (%s)",
                type(exc).__name__,
            )
        self._tracer = GenerationTracer(
            generation_id="pending",
            watchlist=watchlist,
        )

        # --- Validate & Profile ---
        t = time.time()
        self._emit_progress("validate")
        commander = self._validate_request(request)
        self._commander = commander
        self._selection_evidence = None
        evidence_dir = os.getenv("SABER_SELECTION_EVIDENCE")
        if evidence_dir:
            from sabermetrics.intelligence.evidence import load_selection_evidence

            self._selection_evidence = load_selection_evidence(
                commander.model_dump(), request.power_target, Path(evidence_dir)
            )
            self._intelligence["selection_evidence"] = (
                self._selection_evidence.model_dump(mode="json")
            )
            self._signals["commander_cohort"] = (
                self._selection_evidence.status == "available"
            )
        metrics["1_validate"] = time.time() - t
        metrics["validate"] = metrics["1_validate"]

        t = time.time()
        self._emit_progress("profile")
        profile_result = self._acquire_profile(request, commander)
        profile = profile_result.profile
        total_cost += profile_result.generation_cost_usd
        metrics["2_profile"] = time.time() - t
        metrics["profile"] = metrics["2_profile"]

        # --- Stage 1: Hard Filters + Role Tag Loading ---
        t = time.time()
        self._emit_progress("filter")
        candidates = self._filter_candidates(request, commander)
        candidates = self._load_role_tags(candidates)
        self._trace_candidates("budget_filtered", candidates)
        evidence = getattr(self, "_selection_evidence", None)
        if evidence is not None and evidence.status == "available":
            rates = {k.casefold(): v for k, v in evidence.inclusion.items()}
            synergies = {k.casefold(): v for k, v in evidence.synergy.items()}
            for card in candidates:
                card["_selection_evidence_available"] = True
                card["_selection_inclusion"] = rates.get(card["name"].casefold(), 0.0)
                card["_selection_synergy"] = synergies.get(card["name"].casefold(), 0.0)
        metrics["3_filter"] = time.time() - t
        metrics["filter"] = metrics["3_filter"]
        self._stage_counts["candidates_after_filter"] = len(candidates)
        logger.info("Stage 1: %d candidates after hard filters", len(candidates))

        # Engine admission from the legal/budget-valid FULL pool, before Pareto.
        from sabermetrics.config import settings as _settings

        per_card_ceiling = (
            request.budget_usd * _settings.pipeline.per_card_budget_fraction
        )
        from sabermetrics.intelligence.cards import annotate, facts_for
        from sabermetrics.intelligence.strategy import make_plan, reserve_plan

        candidates = [annotate(c) for c in candidates if not facts_for(c).exclusion]
        self._trace_candidates("annotated", candidates)
        self._strategy_plan = make_plan(
            commander.model_dump(), request.user_intent, request.power_target
        )
        self._strategy_reserved = reserve_plan(
            self._strategy_plan, candidates, request.budget_usd
        )
        self._strategy_names = {c["name"] for c in self._strategy_reserved}
        self._protected_names |= self._strategy_names

        requirement = parse_user_intent(request.user_intent)
        color_legal = getattr(self, "_color_legal_pool", candidates)
        self._engine_admission = admit_engine_candidates(
            requirement,
            budget_valid_pool=candidates,
            color_legal_pool=color_legal,
            per_card_ceiling=per_card_ceiling,
        )
        self._engine_protect_names = set(self._engine_admission.selected_names)
        self._protected_names |= self._engine_protect_names
        self._tracer.watchlist.update(self._engine_protect_names)
        self._tracer.watchlist.update(self._engine_admission.admitted_names)
        self._trace_engine_admission()
        self._stage_counts["engine_admitted"] = len(self._engine_admission.admitted)
        self._stage_counts["engine_selected"] = len(self._engine_admission.selected)

        # --- Stage 2: Pareto Filter ---
        t = time.time()
        self._emit_progress("score")
        candidates = self._structural_score(
            candidates, commander, request, profile_result
        )
        if self._strategy_plan.archetype == "landfall":
            for c in candidates:
                capabilities = set(facts_for(c).capabilities)
                aligned = capabilities & {
                    "landfall_cards",
                    "landfall_tokens",
                    "land_ramp",
                    "extra_land_play",
                    "land_recursion",
                    "land_from_hand",
                }
                if aligned:
                    c["_cvar_score"] = min(1.0, float(c.get("_cvar_score", 0)) + 0.20)
                # Generic alternate-win tags are not evidence of a landfall
                # closing plan; don't let their quota crowd out the engine.
                roles = json.loads(c.get("role_tags") or "[]")
                if "wincon" in roles and not capabilities & {
                    "landfall_tokens",
                    "landfall_growth",
                }:
                    roles.remove("wincon")
                    c["role_tags"] = json.dumps(roles or ["utility"])
        metrics["score"] = time.time() - t
        from sabermetrics.intelligence.experiment import current as draw_experiment

        self._draw_enabled = draw_experiment().draw_selection
        self._function_guard_enabled = (
            self._draw_enabled and draw_experiment().preserve_functions
        )
        # No automatic replacement when the policy cannot value competitive
        # engines or commander-based toughness/defender card advantage.
        self._draw_audit_only = (
            request.power_target >= 4 or "defender" in commander.oracle_text.lower()
        )
        self._guard_candidates = (
            candidates
            if self._function_guard_enabled and not self._draw_audit_only
            else []
        )
        self._draw_candidates = (
            candidates
            if self._draw_enabled
            and not self._draw_audit_only
            and not self._function_guard_enabled
            else []
        )
        self._trace_candidates("scored", candidates)
        candidates = self._pareto_filter(candidates)
        self._trace_candidates("recalled", candidates)
        metrics["4_pareto"] = time.time() - t
        self._stage_counts["candidates_after_pareto"] = len(candidates)
        logger.info("Stage 2: %d candidates after Pareto filter", len(candidates))
        self._trace_engine_snapshot("pareto", candidates, as_cards=True)

        # --- Stage 3: Template Derivation ---
        t = time.time()
        self._emit_progress("template")
        template = self._derive_template(profile, request)
        metrics["5_template"] = time.time() - t
        metrics["template"] = metrics["5_template"]
        logger.info(
            "Stage 3: Template derived (%d land, %d ramp, %d draw, "
            "%d removal, %d diff)",
            template.land_count,
            template.ramp_count,
            template.draw_count,
            template.removal_count,
            template.differentiator_slots,
        )

        # Reserve the engine package BEFORE infrastructure so budget/slots
        # survive later fills, swaps, review, and legality repair.
        t = time.time()
        self._emit_progress("infrastructure")
        engine_reserved = self._reserve_engine_package(
            candidates,
            request,
            exclude_names=set(),
        )
        from sabermetrics.pipeline.slot_assigner import SlotAssignment

        engine_names = {a.card.get("name") for a in engine_reserved}
        engine_reserved.extend(
            SlotAssignment(card=c, slot_role=_heuristic_role(c), score=0.0)
            for c in self._strategy_reserved
            if c["name"] not in engine_names
        )
        budget_used = sum(
            float(a.card.get("price_usd", 0) or 0) for a in engine_reserved
        )
        self._protected_names |= {a.card.get("name", "") for a in engine_reserved}
        self._stage_counts["engine_reserved"] = len(engine_reserved)

        infrastructure, infra_spent = self._fill_infrastructure(
            candidates,
            commander,
            request,
            template,
            already_placed=list(engine_reserved),
            budget_used=budget_used,
        )
        budget_used = infra_spent
        metrics["6_infrastructure"] = time.time() - t
        metrics["infrastructure"] = metrics["6_infrastructure"]

        # --- Stage 4.5: Reserve empirical staples the generators didn't place ---
        # After Stage 4 so it can exclude cards already placed -- reserving only
        # the consensus engine pieces the role scorers reject, not good role
        # cards the generators took anyway. Reserved staples occupy differentiator
        # slots, so greedy (Stage 5+6) fills that many fewer (deck stays 99).
        placed_names = {a.card.get("name", "") for a in infrastructure}
        reserved = self._reserve_empirical_staples(
            candidates,
            request,
            template,
            exclude_names=placed_names,
        )
        infrastructure = list(reserved) + infrastructure
        budget_used += sum(float(a.card.get("price_usd", 0) or 0) for a in reserved)
        # Don't let swap_refine trade away a card the corpus told us to keep.
        self._protected_names |= {a.card.get("name", "") for a in reserved}
        logger.info(
            "Stage 4: %d cards placed ($%.2f), %d reserved as staples, "
            "%d reserved as engine",
            len(infrastructure),
            budget_used,
            len(reserved),
            len(engine_reserved),
        )
        if request.power_target == 5:
            # Auto-includes may compete; only verified packages and strong
            # cohort-backed selections retain unconditional swap protection.
            package_names = set(self._strategy_names) | set(self._engine_protect_names)
            corroborated = {
                a.card["name"]
                for a in infrastructure
                if a.card.get("_selection_inclusion", 0) >= 0.70
            }
            self._protected_names &= package_names | corroborated
        self._trace_engine_snapshot("infrastructure", infrastructure)

        # --- Stage 5+6: Synergy optimizer (role targets + matrix + greedy + swap) ---
        t = time.time()
        all_assignments, opt_metrics = self._optimize_differentiators(
            candidates,
            infrastructure,
            profile_result,
            commander,
            request,
            template,
            budget_used,
            reserved_count=len(reserved),
        )
        review_cost = ledger_review_cost(
            float(opt_metrics.get("llm_safety_cost", 0.0) or 0.0),
            bool(self._review_failed or opt_metrics.get("llm_safety_failed")),
        )
        total_cost += review_cost
        metrics["7_optimizer"] = time.time() - t
        metrics["review"] = float(opt_metrics.get("review_seconds", 0))
        metrics["optimize"] = max(0.0, metrics["7_optimizer"] - metrics["review"])
        metrics.update(
            {f"opt_{k}": v for k, v in opt_metrics.items() if k != "role_targets"}
        )
        metrics["opt_llm_safety_cost"] = review_cost
        logger.info(
            "Stage 5+6: %d total cards, %d swaps, obj=%.4f",
            len(all_assignments),
            opt_metrics.get("cards_swapped", 0),
            opt_metrics.get("objective_score", 0),
        )
        self._stage_counts["cards_swapped"] = int(opt_metrics.get("cards_swapped", 0))
        self._stage_counts["type_floor_swaps"] = int(
            opt_metrics.get("type_floor_swaps", 0)
        )
        self._stage_counts["rebalance_upgrades"] = int(
            opt_metrics.get("rebalance_upgrades", 0)
        )

        # (Stage 7 budget rebalancing now runs inside _optimize_differentiators,
        # where the synergy matrix and role targets it evaluates against live.)

        # Mechanically supported draw repair inspects the full legal scored pool,
        # independent of legacy slot labels. Newly selected cards do not inherit
        # an LLM-review pass; the deterministic scope is recorded explicitly.
        if self._draw_candidates:
            from sabermetrics.intelligence.draw_selection import repair as repair_draw
            from sabermetrics.pipeline.slot_assigner import SlotAssignment

            fixed, receipt = repair_draw(
                [a.card for a in all_assignments],
                self._draw_candidates,
                commander.model_dump(),
                request.budget_usd,
                request.power_target,
                protected=set(self._protected_names or ())
                | set(getattr(self, "_engine_protect_names", ()) or ()),
                type_floors=template.type_floors,
            )
            old = {a.card["name"]: a for a in all_assignments}
            all_assignments = [
                (
                    old[c["name"]].model_copy(update={"card": c})
                    if c["name"] in old
                    else SlotAssignment(card=c, slot_role="draw", score=0.0)
                )
                for c in fixed
            ]
            self._intelligence["draw_selection"] = receipt
            self._trace_engine_snapshot("draw_selection", all_assignments)

        # --- Stage 7b: Enforce Commander legality as a hard invariant ---
        all_assignments = self._enforce_legality(
            all_assignments,
            commander,
            protected_names=self._protected_names,
        )
        self._trace_engine_snapshot("legality", all_assignments)

        from sabermetrics.intelligence.alternatives import compare_mana_variants

        t = time.time()
        self._emit_progress("simulate")
        all_assignments, simulation = compare_mana_variants(
            all_assignments, commander.model_dump()
        )
        self._intelligence["simulation"] = simulation

        # The guarded experiment starts from the completed baseline, AFTER every
        # selection-changing stage. Early reservation is disabled in this mode.
        # Narrative and persistence below do not select replacements.
        if self._guard_candidates:
            from sabermetrics.intelligence.function_guard import guarded_repair
            from sabermetrics.pipeline.slot_assigner import SlotAssignment

            fixed, receipt = guarded_repair(
                [a.card for a in all_assignments],
                self._guard_candidates,
                commander.model_dump(),
                request.budget_usd,
                request.power_target,
                protected=set(self._protected_names or ())
                | set(getattr(self, "_engine_protect_names", ()) or ()),
            )
            old = {a.card["name"]: a for a in all_assignments}
            all_assignments = [
                (
                    old[c["name"]].model_copy(update={"card": c})
                    if c["name"] in old
                    else SlotAssignment(card=c, slot_role=_heuristic_role(c), score=0.0)
                )
                for c in fixed
            ]
            self._intelligence["draw_selection"] = receipt
            self._trace_engine_snapshot("function_guard", all_assignments)
            if receipt.get("guard", {}).get("changed"):
                simulation["scope_note"] = (
                    "Mana probe preceded proved draw-spell substitutions; no mana-source changes were made."
                )
        elif self._function_guard_enabled:
            from copy import deepcopy

            from sabermetrics.intelligence.function_guard import validate_transition

            baseline = deepcopy([a.card for a in all_assignments])
            self._intelligence["draw_selection"] = {
                "status": "unresolved",
                "mode": "audit_only",
                "decisions": [],
                "reason": "Automatic changes disabled in this strategy context.",
                "baseline_cards": baseline,
                "guard": validate_transition(
                    baseline,
                    baseline,
                    commander.model_dump(),
                    request.budget_usd,
                ),
            }
        from sabermetrics.intelligence.access import engine_access

        self._intelligence["engine_access"] = engine_access(
            [a.card for a in all_assignments], self._strategy_plan
        )
        metrics["simulate"] = time.time() - t

        # --- Stage 8: Synthesis + Classify + Persist ---
        from sabermetrics.intelligence.draw_route_policy import audit_assignments
        from sabermetrics.intelligence.experiment import current as route_policy

        self._intelligence["draw_routes"] = audit_assignments(
            all_assignments,
            commander.model_dump(mode="json"),
            request.power_target,
            enforce=route_policy().draw_package_policy == "routes",
        )
        self._trace_candidates("final", [a.card for a in all_assignments])
        if "upstream" in self._intelligence:
            from sabermetrics.intelligence.function_guard import validate_transition
            from sabermetrics.intelligence.upstream_guard import snapshot

            upstream = self._intelligence["upstream"]
            upstream["snapshots"]["final"] = snapshot(all_assignments)
            upstream["cumulative_validation"] = validate_transition(
                upstream["snapshots"]["greedy"],
                upstream["snapshots"]["final"],
                commander.model_dump(),
                request.budget_usd,
                set(self._protected_names or ())
                | set(getattr(self, "_engine_protect_names", ()) or ()),
            )
        self._validate_no_commander_in_99(all_assignments, commander)
        total_price = sum(
            max(0.0, float(a.card.get("price_usd", 0) or 0)) for a in all_assignments
        )

        # Build AssemblyResult-compatible wrapper
        from sabermetrics.pipeline.slot_assigner import AssemblyResult

        target_comp = template.to_composition()
        actual_comp: dict[str, int] = {}
        for a in all_assignments:
            actual_comp[a.slot_role] = actual_comp.get(a.slot_role, 0) + 1

        assembly = AssemblyResult(
            assignments=all_assignments,
            composition=actual_comp,
            target_composition=target_comp,
            total_price=round(total_price, 2),
            warnings=[],
        )

        if len(all_assignments) < 99:
            assembly.warnings.append(f"Only {len(all_assignments)} cards, need 99.")

        engine_status = verify_engine_in_deck(
            self._engine_admission,
            [a.card for a in all_assignments],
        )
        self._engine_admission.status = engine_status
        self._trace_engine_snapshot("final", all_assignments)
        selected_names = {a.card["name"] for a in all_assignments}
        for name in self._tracer.watchlist:
            self._tracer.record(
                card_name=name,
                stage="final_selection",
                action="retained" if name in selected_names else "excluded",
                reason="Final deck membership; inspect earlier stages for cause",
            )

        role_targets_counts = {}
        for r, t in (opt_metrics.get("role_targets") or {}).items():
            if hasattr(t, "target_count"):
                role_targets_counts[r] = t.target_count
            else:
                try:
                    role_targets_counts[r] = int(t)
                except (TypeError, ValueError):
                    continue
        if not role_targets_counts:
            role_targets_counts = {
                "ramp": template.ramp_count,
                "draw": template.draw_count,
                "removal": template.removal_count,
                "land": template.land_count,
            }

        classification = self._classify_bracket(assembly)

        t = time.time()
        self._emit_progress("narrative")
        narrative, synth_cost = self._synthesize_narrative(
            profile_result,
            assembly,
            request,
            classification,
        )
        total_cost += synth_cost
        metrics["10_synthesis"] = time.time() - t
        metrics["narrative"] = metrics["10_synthesis"]

        # Acceptance after narrative so missing-signal warnings include it.
        from sabermetrics.pipeline.greedy_optimizer import _count_roles

        acceptance_role_counts = _count_roles(all_assignments)
        acceptance_role_counts["land"] = actual_comp.get("land", 0)
        acceptance = evaluate_final_deck(
            assignments=all_assignments,
            commander_name=commander.name,
            commander_colors=commander.color_identity,
            budget_usd=request.budget_usd,
            requested_bracket=request.power_target,
            estimated_bracket=classification.estimated_bracket,
            engine=self._engine_admission,
            engine_status=engine_status,
            signals=self._signals,
            role_counts=acceptance_role_counts,
            role_targets=role_targets_counts,
            review_failed=self._review_failed,
            commander_oracle=commander.oracle_text,
            legality_backfill=self._legality_backfill,
        )
        if self._draw_enabled:
            from sabermetrics.intelligence.draw_selection import audit as audit_draw
            from sabermetrics.pipeline.quality import QualityItem

            final_draw = audit_draw(
                [a.card for a in all_assignments],
                commander.model_dump(),
                request.power_target,
            )
            receipt = self._intelligence.setdefault(
                "draw_selection",
                {
                    "status": "unresolved",
                    "mode": "audit_only",
                    "reason": "Automatic intervention disabled for unmodeled high-power or defender strategy context.",
                    "decisions": [],
                },
            )
            receipt["final"] = final_draw
            if final_draw["credible"] < receipt.get("target", 99) or final_draw[
                "independent"
            ] < receipt.get("independent_target", 99):
                receipt["status"] = "unresolved"
                acceptance.warnings.append(
                    QualityItem(
                        severity="warning",
                        code="draw_package_unresolved",
                        message="Supported card-advantage requirement remains unresolved; this deck has not passed draw-package validation.",
                    )
                )

        if acceptance.failures:
            raise FatalError(
                "Final deck validation failed: "
                + "; ".join(item.message for item in acceptance.failures)
            )
        from sabermetrics.intelligence.cards import semantic_findings
        from sabermetrics.intelligence.strategy import assess_plan

        plan = assess_plan(self._strategy_plan, [a.card for a in all_assignments])
        findings = semantic_findings([a.card for a in all_assignments])
        from sabermetrics.intelligence.audit import summarize_selection_audit

        self._intelligence["selection_audit"] = summarize_selection_audit(
            [e.model_dump() for e in self._tracer._events]
        )
        from sabermetrics.intelligence.prerequisite_evidence import (
            evaluate_prerequisites,
        )

        final_cards = [a.card for a in all_assignments]
        prerequisite_rows = []
        for card in final_cards:
            evidence = evaluate_prerequisites(card, final_cards, catalog_complete=True)
            if evidence["abilities"]:
                prerequisite_rows.append({"card": card["name"], **evidence})
        self._intelligence["prerequisites"] = {
            "coverage": "incomplete",
            "cut_authorized": False,
            "examined_cards": len(final_cards),
            "matched_cards": len(prerequisite_rows),
            "cards": prerequisite_rows,
        }
        self._intelligence.update(
            {
                "version": "generation-intelligence.v1",
                "plan": plan,
                "findings": findings,
                "decisions": plan["evidence"],
            }
        )
        if plan["archetype"] == "landfall":
            narrative.game_plan = (
                "Develop lands, establish "
                + commander.name
                + ", then use repeated land entries to trigger the listed payoffs. "
                + "The commander and selected cards cover "
                + ", ".join(
                    f"{r.replace('_',' ')} ({n})" for r, n in plan["counts"].items()
                )
                + "."
            )
            narrative.key_synergies = [
                f"{e['card']}: {e['reason']}" for e in plan["evidence"][:10]
            ]
            narrative.weaknesses = (
                ["Unmet strategy requirements: " + ", ".join(plan["missing"])]
                if plan["missing"]
                else []
            )
            narrative.weaknesses += [
                "Opponent interaction and overall winning strength have not been simulated."
            ]
        if any(f["severity"] == "failure" for f in findings):
            raise FatalError("Final deck contains unsupported card prerequisites")
        self._quality_warnings = acceptance.as_rationale_list()
        if plan["requirements"]:
            self._quality_warnings = [
                w for w in self._quality_warnings if w["code"] != "intent_unverified"
            ]
            if plan["missing"]:
                self._quality_warnings.append(
                    {
                        "severity": "warning",
                        "code": "strategy_partial",
                        "message": "Strategy requirements remain unmet: "
                        + ", ".join(plan["missing"]),
                    }
                )
        for item in acceptance.failures:
            assembly.warnings.append(f"[failure:{item.code}] {item.message}")
        for item in acceptance.warnings:
            if item.code in {
                "engine_unavailable",
                "engine_unsatisfied",
                "intent_unverified",
                "failed_final_review",
                "signal_unavailable",
                "unmet_role_target",
            }:
                assembly.warnings.append(f"[warning:{item.code}] {item.message}")

        deck = self._build_deck_model(
            commander=commander,
            request=request,
            profile=profile,
            assembly=assembly,
            narrative=narrative,
            classification=classification,
            total_cost=total_cost,
            start_time=start_time,
        )
        t = time.time()
        self._emit_progress("persist")
        self._stage_timings = {
            stage: float(metrics[stage])
            for stage in _PROGRESS_STAGES
            if stage in metrics and stage != "completed"
        }
        self._engine_rationale = engine_rationale_dump(self._engine_admission)
        self._persist_deck(deck)

        # Flush trace events keyed to the real deck ID
        self._tracer.set_generation_id(deck.id)
        trace_count = self._tracer.flush(self.db_path)
        if trace_count:
            logger.info("Flushed %d trace events for deck %s", trace_count, deck.id)
        metrics["persist"] = time.time() - t
        self._stage_timings["persist"] = metrics["persist"]
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT rationale FROM generated_decks WHERE id = ?", (deck.id,)
            ).fetchone()
            rationale = json.loads(row[0])
            rationale["stage_timings"] = self._stage_timings
            conn.execute(
                "UPDATE generated_decks SET rationale = ? WHERE id = ?",
                (json.dumps(rationale), deck.id),
            )

        total_time = time.time() - start_time
        logger.info(
            "Deck built for %s in %.1fs ($%.4f)",
            commander.name,
            total_time,
            total_cost,
        )

        # Completion is real: persist (and trace flush) already happened.
        self._emit_progress("completed")

        return DeckBuildResult(
            deck=deck,
            profile_was_generated=not profile_result.cache_hit,
            total_cost_usd=round(total_cost, 4),
            total_time_seconds=round(total_time, 2),
            quality_warnings=list(self._quality_warnings),
            pipeline_metrics={
                **metrics,
                "empirical_variant": getattr(self, "_empirical_variant", None),
                "stage_counts": dict(self._stage_counts),
                "stage_timings": dict(getattr(self, "_stage_timings", {})),
                "engine_status": engine_status,
                "review_failed": self._review_failed,
            },
        )

    # --- Step implementations ---

    @staticmethod
    def _validate_no_commander_in_99(assignments: list, commander: Card) -> None:
        """Hard-fail if the commander leaked into the 99.

        The commander sharing a slot with itself violates the format's core
        rule, so this is a FatalError, not a warning. Matches by oracle_id
        (shared across printings -- excluding only the commander's own printing
        id once let a cheaper printing of the commander into its own deck) with
        name as the fallback for cards without one.

        Args:
            assignments: All slot assignments about to be assembled.
            commander: The commander card.

        Raises:
            FatalError: If any assignment is a printing of the commander.
        """
        for a in assignments:
            card = a.card
            same = (
                commander.oracle_id and card.get("oracle_id") == commander.oracle_id
            ) or card.get("name", "") == commander.name
            if same:
                raise FatalError(
                    f"Commander '{commander.name}' leaked into the 99 "
                    f"(printing {card.get('id')}, slot {a.slot_role}). "
                    "This is a generator bug; the deck is illegal."
                )

    def _validate_request(self, request: DeckBuildRequest) -> Card:
        """Validate the build request and load commander."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                "SELECT * FROM cards WHERE id = ? AND is_legal_commander = 1",
                (request.commander_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FatalError(
                    f"Commander not found or not legal: {request.commander_id}"
                )

            row_dict = dict(row)
            for field in ("color_identity", "keywords"):
                val = row_dict.get(field, "[]")
                if isinstance(val, str):
                    row_dict[field] = json.loads(val)

            # Get price
            price_cursor = conn.execute(
                "SELECT price_usd FROM card_prices "
                "WHERE card_id = ? ORDER BY snapshot_date DESC LIMIT 1",
                (request.commander_id,),
            )
            price_row = price_cursor.fetchone()
            if price_row:
                row_dict["current_price_usd"] = price_row["price_usd"]

            from sabermetrics.db import row_to_card

            return row_to_card(row_dict)
        finally:
            conn.close()

    def _acquire_profile(self, request, commander):
        """Get or generate commander profile."""
        from sabermetrics.reasoning.profiler import ProfileManager, ProfileRequest

        manager = ProfileManager(self.db_path)
        evidence = getattr(self, "_selection_evidence", None)
        if evidence is not None and evidence.status == "available":
            manager.selection_evidence = evidence.model_dump(mode="json")
        profile_request = ProfileRequest(
            commander_id=request.commander_id,
            user_intent=request.user_intent,
            evidence_key=(
                evidence.cohort + ":" + str(evidence.retrieved_at)
                if evidence is not None and evidence.status == "available"
                else None
            ),
        )
        return manager.generate_profile(profile_request)

    def _filter_candidates(self, request, commander) -> list[dict]:
        """Stage 1: Apply hard-rule filters.

        Color/format legality is computed first so engine admission can
        explain budget-unavailable copy creatures instead of omitting them.
        """
        from sabermetrics.analytics.filters import (
            apply_hard_filters,
            filter_by_budget,
        )

        legal = apply_hard_filters(
            db_path=self.db_path,
            commander_id=request.commander_id,
            max_budget_usd=None,
        )
        self._color_legal_pool = legal
        self._trace_candidates("color_format_legal", legal)
        return filter_by_budget(legal, request.budget_usd)

    def _load_role_tags(self, candidates: list[dict]) -> list[dict]:
        """Load role_tags and functional_categories for candidates from DB."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Check if columns exist
            cursor = conn.execute("PRAGMA table_info(cards)")
            columns = {row[1] for row in cursor.fetchall()}
            if "role_tags" not in columns:
                return candidates

            card_ids = [c.get("id", "") for c in candidates]
            if not card_ids:
                return candidates

            # Batch load role tags
            tag_map: dict[str, tuple[str, str]] = {}
            batch_size = 500
            for i in range(0, len(card_ids), batch_size):
                batch = card_ids[i : i + batch_size]
                placeholders = ",".join("?" * len(batch))
                cursor = conn.execute(
                    f"SELECT id, role_tags, functional_categories "
                    f"FROM cards WHERE id IN ({placeholders})",
                    batch,
                )
                for row in cursor:
                    tag_map[row["id"]] = (
                        row["role_tags"] or "[]",
                        row["functional_categories"] or "[]",
                    )

            for card in candidates:
                cid = card.get("id", "")
                if cid in tag_map:
                    card["role_tags"] = tag_map[cid][0]
                    card["functional_categories"] = tag_map[cid][1]
        finally:
            conn.close()

        return candidates

    def _structural_score(
        self,
        candidates: list[dict],
        commander: Card,
        request: DeckBuildRequest,
        profile_result=None,
    ) -> list[dict]:
        """Score by CVAR composite (reused from v1)."""
        from sabermetrics.analytics.cvar import ScoringContext, compute_cvar
        from sabermetrics.analytics.oracle_keywords import (
            extract_referenced_keywords,
            extract_referenced_mechanics,
        )

        weights = request.weights or CVARWeights()

        ref_keywords = extract_referenced_keywords(commander.oracle_text)
        ref_mechanics = extract_referenced_mechanics(commander.oracle_text)

        # Extract engine keywords from profile
        engine_keywords: list[str] = []
        output_keywords: list[str] = []
        if profile_result is not None:
            sp = getattr(
                getattr(profile_result, "profile", None),
                "strategic_profile",
                None,
            )
            if sp is not None:
                for dep in getattr(sp, "engine_dependencies", []):
                    engine_keywords.extend(dep.engine_card_traits)
                    output_keywords.extend(dep.dependent_outputs)

        # Tokenize LLM-generated trait descriptions into matchable keywords
        engine_keywords = _tokenize_engine_traits(engine_keywords)

        # Extract desired card traits from value inversions
        desired_traits: list[str] = []
        if profile_result is not None:
            sp = getattr(
                getattr(profile_result, "profile", None),
                "strategic_profile",
                None,
            )
            if sp is not None:
                for vi in getattr(sp, "value_inversions", []):
                    desired_traits.extend(vi.desired_characteristics)

        # Load EDHREC top cards
        edhrec_top_cards: dict[str, float] = {}
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT top_cards FROM edhrec_commander_data " "WHERE commander_id = ?",
                (commander.id,),
            )
            row = cursor.fetchone()
            if row and row["top_cards"]:
                for entry in json.loads(row["top_cards"]):
                    name = (entry.get("card_name") or "").lower()
                    pct = float(entry.get("inclusion_pct", 0))
                    if name and pct > 0:
                        edhrec_top_cards[name] = pct
            conn.close()
        except (sqlite3.Error, ValueError, TypeError, KeyError) as e:
            logger.warning("Failed to load EDHREC data: %s", e)

        # EDHREC behavioral corroboration is a live signal only if this
        # commander actually has inclusion data.
        if hasattr(self, "_signals"):
            self._signals["edhrec"] = bool(edhrec_top_cards)

        # Card Win Equity from tournament data (present only if TopDeck.gg
        # tournament data has been ingested for this commander).
        from sabermetrics.analytics.card_win_equity import load_cwe_for_commander

        cwe_by_card, cwe_sample_by_card = load_cwe_for_commander(
            self.db_path, commander.id
        )
        if hasattr(self, "_signals"):
            self._signals["tournament_cwe"] = bool(cwe_by_card)

        # Per-variant empirical grounding from the verified decklist corpus
        # (Phase 6). Sharper than pooled EDHREC; None when no corpus exists,
        # in which case scoring falls back cleanly to the pooled EDHREC signal.
        empirical = None
        try:
            from sabermetrics.analytics.empirical_valuation import (
                get_target_cluster_inclusion,
            )

            empirical = get_target_cluster_inclusion(
                self.db_path,
                commander.id,
                strategy=request.strategy,
            )
        except (sqlite3.Error, ValueError, TypeError, KeyError) as e:
            logger.warning("Empirical inclusion load failed: %s", e)
        self._empirical_variant = empirical.variant if empirical else None
        # Kept for later stages: template derivation reads the variant's
        # median composition (Stage 3), reservation its inclusion (Stage 4.5).
        self._empirical = empirical
        if empirical is not None:
            logger.info(
                "Empirical grounding active: variant='%s' from %d/%d decks, "
                "%d cards (%d reliable)",
                empirical.variant,
                empirical.variant_size,
                empirical.n_decks,
                len(empirical.inclusion),
                len(empirical.reliable),
            )

        context = ScoringContext(
            power_target=request.power_target,
            commander_id=commander.id,
            commander_name=commander.name,
            commander_colors=commander.color_identity,
            commander_keywords=commander.keywords or [],
            commander_oracle_text=commander.oracle_text,
            referenced_keywords=ref_keywords,
            referenced_mechanics=ref_mechanics,
            engine_keywords=[kw.lower() for kw in engine_keywords],
            output_keywords=[kw.lower() for kw in output_keywords],
            edhrec_top_cards=edhrec_top_cards,
            empirical_inclusion=empirical.inclusion if empirical else {},
            empirical_reliable=empirical.reliable if empirical else set(),
            empirical_variant=empirical.variant if empirical else None,
            cwe_by_card=cwe_by_card,
            cwe_sample_by_card=cwe_sample_by_card,
            desired_card_traits=desired_traits,
            weights_synergy=weights.synergy,
            weights_mana_efficiency=weights.mana_efficiency,
            weights_replacement_value=weights.replacement_value,
            weights_price_efficiency=weights.price_efficiency,
            max_budget=request.budget_usd,
        )

        # Engine types for the anti-synergy veto: a card that mass-removes the
        # type the deck is built on ("destroy all enchantments" in an
        # enchantress shell) must never win a slot on text-match points.
        from sabermetrics.analytics.anti_synergy import engine_types, is_anti_engine
        from sabermetrics.analytics.oracle_patterns import is_combat_gated
        from sabermetrics.config import settings

        engine: set[str] = set()
        aura_engine = False
        few_attackers = False
        if empirical is not None and empirical.composition is not None:
            comp = empirical.composition
            engine = engine_types(
                {
                    "enchantment": comp.enchantments,
                    "artifact": comp.artifacts,
                }
            )
            aura_engine = (
                comp.enchantments > 0 and comp.auras >= 0.6 * comp.enchantments
            )
            few_attackers = comp.creatures < settings.scoring.combat_gated_creature_min

        # Game-changer gate: bracket data exists (game_changers.yaml) but was
        # never consulted at selection -- Mana Vault-class fast mana has no
        # place in a power<=3 pool. Reuses the categorical-exclusion flag.
        gc_names: set[str] = set()
        if request.power_target <= 3:
            try:
                import yaml as _yaml

                from sabermetrics.config import config_path as _config_path

                _gc = (
                    _yaml.safe_load(_config_path("game_changers.yaml").read_text())
                    or {}
                )
                from sabermetrics.intelligence.power_policy import (
                    configured_game_changer_names,
                )

                gc_names = configured_game_changer_names(_gc)
            except (OSError, _yaml.YAMLError, ValueError, TypeError) as exc:
                logger.warning(
                    "Bracket configuration unavailable (%s)", type(exc).__name__
                )
            gc_names.discard("sol ring")  # ubiquitous at every power level

        for card in candidates:
            card_name_lower = (card.get("name") or "").lower()
            if card_name_lower in gc_names:
                card["_anti_engine"] = True
            card["edhrec_inclusion_pct"] = edhrec_top_cards.get(card_name_lower, 0.0)
            if empirical is not None:
                card["_empirical_inclusion"] = empirical.rate(card_name_lower)
                card["_empirical_reliable"] = card_name_lower in empirical.reliable
            result = compute_cvar(card, context, self.db_path)
            card["_cvar_result"] = result.model_dump()
            from sabermetrics.intelligence.selection import evidence_score

            card["_selection_base_score"] = result.composite_score
            card["_cvar_score"] = evidence_score(card, result.composite_score)
            # SME value-inversion rule: in an aura-engine deck, any 1-2
            # mana Aura is "one mana to stop an attacker" -- playable
            # regardless of generic quality. Generic scoring rates Crippling
            # Blight-class cards near zero and Pareto kills them before any
            # later stage can save the engine fuel. Floor, don't boost:
            # multi-taskers still rank higher via synergy/empirical signals.
            if aura_engine:
                tl = (card.get("type_line") or "").lower()
                if "aura" in tl and float(card.get("cmc", 0) or 0) <= 2:
                    card["_cvar_score"] = max(card["_cvar_score"], 0.55)
                    card["_engine_fuel"] = True
            if engine and is_anti_engine(card, engine):
                card["_anti_engine"] = True
                card["_cvar_score"] = round(
                    card["_cvar_score"] * settings.scoring.anti_synergy_penalty,
                    4,
                )
            # Combat-gated payoff discount: "attack with two or more
            # creatures" class conditions (prepared/battalion/raid) rarely
            # fire in a deck whose real lists run few attackers -- the
            # printed payoff is not the played payoff. Numeric-layer fix
            # for the Eiganjo class: three rounds of vet prompt tuning
            # scored it 7 -> 5 -> 5, never below the swap line, because
            # its inflated CVAR kept re-selecting it as top replacement.
            if few_attackers and is_combat_gated(card.get("oracle_text")):
                card["_combat_gated"] = True
                card["_cvar_score"] = round(
                    card["_cvar_score"] * settings.scoring.combat_gated_discount,
                    4,
                )

        return candidates

    def _pareto_filter(self, candidates: list[dict]) -> list[dict]:
        from sabermetrics.intelligence.selection import retain_candidates
        from sabermetrics.pipeline.generators.ramp import _load_auto_includes

        auto, _ = _load_auto_includes()
        protected = {
            e["name"]
            for values in auto.values()
            if isinstance(values, list)
            for e in values
        }
        protected |= set(getattr(self, "_strategy_names", ()) or ())
        protected |= set(getattr(self, "_engine_protect_names", ()) or ())
        return retain_candidates(candidates, protected, getattr(self, "_tracer", None))

    def _derive_template(self, profile, request):
        """Stage 3: Derive deck template from profile.

        When Stage 2 loaded a reliable decklist corpus, its median composition
        grounds the template (lands, avg CMC, type targets) instead of the
        power-target estimates.
        """
        from sabermetrics.reasoning.template_deriver import derive_deck_template

        empirical = getattr(self, "_empirical", None)
        composition = (
            empirical.composition
            if empirical is not None and empirical.reliable
            else None
        )
        template = derive_deck_template(
            profile=profile,
            budget=request.budget_usd,
            power_target=request.power_target,
            db_path=self.db_path,
            empirical_composition=composition,
        )
        evidence = getattr(self, "_selection_evidence", None)
        if (
            evidence is not None
            and evidence.status == "available"
            and evidence.sample_size >= 50
        ):
            comp = evidence.composition
            land_estimate = int(comp.get("land", template.land_count))
            # Observed composition is a target, never a simulated source count.
            floor = 24 if request.power_target == 5 else 30
            template.land_count = max(floor, min(42, land_estimate))
            template.type_targets = {
                t: int(comp[t])
                for t in (
                    "creature",
                    "artifact",
                    "enchantment",
                    "instant",
                    "sorcery",
                    "planeswalker",
                )
                if t in comp
            }
            template.creature_density = max(
                0.0,
                min(1.0, comp.get("creature", 25) / max(1, 99 - template.land_count)),
            )
            if request.power_target == 5 and comp.get("creature", 30) < 20:
                # Broad wipes are not an independent quota for a fast, low-body
                # competitive shell; spot interaction remains required.
                template.board_wipe_count = 0
                template.ramp_count = (
                    5  # Repeatable sources; burst mana is a separate engine ingredient.
                )
                template.removal_count = max(template.removal_count, 8)
            infra = (
                template.land_count
                + template.ramp_count
                + template.draw_count
                + template.removal_count
                + template.board_wipe_count
            )
            template.differentiator_slots = max(10, min(45, 99 - infra))
        return template

    def _trace_engine_admission(self) -> None:
        """Record every engine-shaped card at admission, including misses."""
        admission = getattr(self, "_engine_admission", None)
        if admission is None:
            return
        if admission.requirement.kind == "none":
            return
        if not admission.records and admission.requirement.kind == "unsupported":
            self._tracer.record(
                card_name="(intent)",
                stage="engine_admission",
                action="unverified",
                reason=(
                    "unsupported intent is unverified, not silently fulfilled: "
                    f"{admission.requirement.raw_intent!r}"
                ),
                force=True,
            )
            return
        for rec in admission.records:
            self._tracer.record(
                card_name=rec.name,
                stage="engine_admission",
                action="admitted" if rec.admitted else "unavailable",
                card_id=rec.card_id,
                score=rec.mana_value,
                reason=rec.reason,
                force=True,
            )

    def _trace_engine_snapshot(
        self,
        stage: str,
        items: list,
        *,
        as_cards: bool = False,
    ) -> None:
        """Trace whether reserved engine cards are still present."""
        names = getattr(self, "_engine_protect_names", None) or set()
        if not names:
            return
        present: set[str] = set()
        for item in items:
            card = item if as_cards else getattr(item, "card", item)
            if isinstance(card, dict):
                present.add(card.get("name", ""))
        for name in sorted(names):
            in_deck = name in present
            self._tracer.record(
                card_name=name,
                stage=stage,
                action="present" if in_deck else "missing",
                reason=(
                    "engine package still present"
                    if in_deck
                    else "engine package card missing after this stage"
                ),
                force=True,
            )

    def _reserve_engine_package(
        self,
        candidates,
        request,
        exclude_names=None,
    ) -> list:
        """Place the feasible clone package before infrastructure fill.

        Hard budget still applies: a card that would overspend is skipped and
        traced, never forced in. Selected names are already on the protected
        set so later swaps/review/legality cannot quietly drop them.
        """
        from sabermetrics.pipeline.slot_assigner import SlotAssignment

        admission = getattr(self, "_engine_admission", None)
        if admission is None or not admission.selected:
            return []
        already = set(exclude_names or set())
        by_name = {c.get("name", ""): c for c in candidates}
        reserved: list[SlotAssignment] = []
        spent = 0.0
        for card in admission.selected:
            name = card.get("name", "")
            if not name or name in already:
                if name in already:
                    self._tracer.record(
                        card_name=name,
                        stage="engine_reserve",
                        action="present",
                        card_id=card.get("id"),
                        reason="already placed; engine reservation skipped",
                        force=True,
                    )
                continue
            live = by_name.get(name, card)
            try:
                price = float(live.get("price_usd", 0) or 0)
            except (TypeError, ValueError):
                price = 0.0
            if price < 0:
                self._tracer.record(
                    card_name=name,
                    stage="engine_reserve",
                    action="unavailable",
                    card_id=live.get("id"),
                    reason="unavailable: negative-cost sentinel rejected",
                    force=True,
                )
                continue
            if spent + price > request.budget_usd:
                self._tracer.record(
                    card_name=name,
                    stage="engine_reserve",
                    action="unavailable",
                    card_id=live.get("id"),
                    score=price,
                    reason=(
                        "unavailable: engine reserve would exceed budget "
                        f"(${spent + price:.2f} > ${request.budget_usd:.2f}); "
                        "engine preservation cannot override budget"
                    ),
                    force=True,
                )
                continue
            spent += price
            already.add(name)
            reserved.append(
                SlotAssignment(
                    card=live,
                    slot_role="utility",
                    score=float(live.get("_cvar_score", 0.8) or 0.8),
                )
            )
            self._tracer.record(
                card_name=name,
                stage="engine_reserve",
                action="placed",
                card_id=live.get("id"),
                score=float(live.get("_cvar_score", 0) or 0),
                reason="reserved engine package (copy-on-entry creature)",
                force=True,
            )
        return reserved

    def _reserve_empirical_staples(
        self,
        candidates,
        request,
        template,
        exclude_names=None,
    ) -> list:
        """Stage 4.5: Reserve differentiator slots for strong-consensus cards.

        Runs AFTER the role generators so it can reserve only cards the corpus
        validates but the generators did not already place. This lands the
        engine pieces the role scorers reject -- a treasure or sacrifice payoff
        is not "ramp", so it is reserved as a differentiator, which is what it
        actually is -- without spending a reserved slot on a genuinely-good ramp
        card the ramp generator would have taken anyway (Birds of Paradise,
        Ignoble Hierarch). Excluding those frees the cap for the payoffs.

        Bounded on purpose (ADR-005, the moneyball goal): only cards at or above
        the inclusion floor, only up to a fraction of the differentiator budget.
        Most slots stay open for the reasoning engine's undervalued picks.

        Args:
            candidates: Scored candidate dicts (carry ``_empirical_inclusion``).
            request: The build request (for the budget ceiling).
            template: Derived template (for the differentiator budget).
            exclude_names: Card names already placed (by the generators), never
                reserved -- they are in the deck already.

        Returns:
            List of SlotAssignment for the reserved cards (may be empty).
        """
        from sabermetrics.config import settings
        from sabermetrics.pipeline.generators.ramp import _load_auto_includes
        from sabermetrics.pipeline.greedy_optimizer import is_playable_as_land
        from sabermetrics.pipeline.slot_assigner import SlotAssignment

        cfg = settings.scoring

        # Auto-includes are placed by the generators, so they arrive via
        # exclude_names; keep this as a fallback for the rare unplaced one.
        auto_names, _ = _load_auto_includes()
        already = set(exclude_names or set())
        for entries in auto_names.values():
            if isinstance(entries, list):
                already.update(e["name"] for e in entries)

        # Eligible: reliable, above the inclusion floor, not a land, not already
        # placed by a generator (or an auto-include), within budget.
        eligible = [
            c
            for c in candidates
            if c.get("_empirical_reliable")
            and float(c.get("_empirical_inclusion", 0.0) or 0.0)
            >= cfg.empirical_reserve_min_inclusion
            and not is_playable_as_land(c.get("type_line") or "")
            and c.get("name", "") not in already
        ]

        # The cap scales with corpus size: fixed max_slots for small corpora,
        # a fraction of the eligible staples for big ones (the sweep found
        # 29-80 consensus staples vs the fixed 12), always bounded by
        # max_fraction of the differentiator budget.
        cap = min(
            max(
                cfg.empirical_reserve_max_slots,
                int(len(eligible) * cfg.empirical_reserve_eligible_fraction),
            ),
            int(template.differentiator_slots * cfg.empirical_reserve_max_fraction),
        )
        if cap <= 0:
            return []
        eligible.sort(
            key=lambda c: float(c.get("_empirical_inclusion", 0.0) or 0.0),
            reverse=True,
        )

        reserved: list[SlotAssignment] = []
        spent = 0.0
        for card in eligible:
            if len(reserved) >= cap:
                break
            price = float(card.get("price_usd", 0) or 0)
            if spent + price > request.budget_usd:
                continue
            spent += price
            rate = float(card.get("_empirical_inclusion", 0.0) or 0.0)
            reserved.append(
                SlotAssignment(
                    card=card,
                    slot_role="utility",
                    score=rate,
                )
            )
            self._tracer.record(
                card_name=card.get("name", ""),
                stage="empirical_reserve",
                action="placed",
                card_id=card.get("id"),
                score=rate,
                reason=f"empirical staple ({rate * 100:.0f}% of variant decks)",
                # Low-volume, load-bearing stage: trace every reservation
                # regardless of watchlist (like swap_refine), so the grounding
                # is auditable.
                force=True,
            )
        if reserved:
            logger.info(
                "Stage 4.5: reserved %d empirical staples: %s",
                len(reserved),
                ", ".join(a.card.get("name", "") for a in reserved),
            )
        return reserved

    def _fill_infrastructure(
        self,
        candidates,
        commander,
        request,
        template,
        already_placed: list | None = None,
        budget_used: float = 0.0,
    ) -> tuple[list, float]:
        """Stage 4: Fill infrastructure slots with deterministic generators.

        Returns:
            Tuple of (list of SlotAssignment, total budget used).
        """
        from sabermetrics.pipeline.generators import (
            DrawPackageGenerator,
            LandPackageGenerator,
            ProtectionPackageGenerator,
            RampPackageGenerator,
            RemovalPackageGenerator,
        )
        from sabermetrics.pipeline.slot_assigner import SlotAssignment

        all_assignments: list[SlotAssignment] = list(already_placed or [])
        colors = commander.color_identity
        self._protected_names = set(getattr(self, "_protected_names", None) or ())

        # Helper to get cards with a specific role tag
        def _pool_by_role(role: str) -> list[dict]:
            pool = []
            for card in candidates:
                rt_raw = card.get("role_tags", "[]")
                if isinstance(rt_raw, str):
                    try:
                        rt = json.loads(rt_raw)
                    except (json.JSONDecodeError, TypeError):
                        rt = []
                else:
                    rt = rt_raw or []
                if role in rt:
                    pool.append(card)
            return pool

        def _land_pool() -> list[dict]:
            from sabermetrics.intelligence.cards import usable_land
            from sabermetrics.pipeline.greedy_optimizer import is_playable_as_land

            pool = []
            for card in candidates:
                type_line = card.get("type_line") or ""
                if (
                    is_playable_as_land(type_line)
                    and "creature" not in type_line.lower()
                    and usable_land(card, colors)
                ):
                    pool.append(card)
            return pool

        def placed_cards() -> list:
            return [a.card for a in all_assignments]

        def _trace_infra(assignments: list, stage: str) -> None:
            """Emit trace events for infrastructure placements."""
            for a in assignments:
                self._tracer.record(
                    card_name=a.card.get("name", ""),
                    stage=stage,
                    action="placed",
                    card_id=a.card.get("id"),
                    score=a.score,
                    reason=f"infrastructure {stage.removeprefix('infra_')}",
                )

        # Gate inheritance for candidate-table loads: the tables are queried
        # straight from the DB and bypassed every pool-level gate (price
        # ceiling, NULL-price exclusion, game-changer gate, anti-engine flag)
        # -- how an $87 Mana Vault entered a $50-ceiling deck. Generators
        # intersect table rows with this index and inherit its flags/scores.
        pool_index = {c.get("name", ""): c for c in candidates}

        # Reserve at least 25% for lands and 20% for remaining strategy slots.
        def role_budget(fraction: float) -> float:
            return max(
                0.0,
                min(
                    request.budget_usd * fraction,
                    request.budget_usd * 0.55 - budget_used,
                ),
            )

        # 1. Ramp (first, so land generator knows what spells are in deck)
        ramp_gen = RampPackageGenerator(self.db_path)
        ramp = ramp_gen.generate(
            color_identity=colors,
            target_count=template.ramp_count,
            budget_remaining=role_budget(0.20),
            template=template,
            already_placed=placed_cards(),
            role_tag_pool=_pool_by_role("ramp"),
            commander_colors=colors,
            avg_cmc=template.avg_cmc_target,
            commander_cmc=float(commander.cmc or 0),
            pool_index=pool_index,
        )
        all_assignments.extend(ramp)
        budget_used += sum(float(a.card.get("price_usd", 0) or 0) for a in ramp)
        _trace_infra(ramp, "infra_ramp")
        # Capture protected names from ramp generator for swap_refine
        self._protected_names |= ramp_gen.protected_names

        # 2. Draw
        draw_gen = DrawPackageGenerator(self.db_path)
        self._trace_candidates("draw_pool", _pool_by_role("draw"))
        if getattr(self, "_draw_candidates", None):
            from sabermetrics.intelligence.draw_selection import select_package

            package = select_package(
                self._draw_candidates,
                placed_cards(),
                commander.model_dump(),
                role_budget(0.15),
                template.draw_count,
                request.power_target,
            )
            draw = [
                SlotAssignment(
                    card=c, slot_role="draw", score=float(c.get("_cvar_score") or 0)
                )
                for c in package
            ]
            self._protected_names |= {c["name"] for c in package}
        else:
            draw = draw_gen.generate(
                color_identity=colors,
                target_count=template.draw_count,
                budget_remaining=role_budget(0.10),
                template=template,
                already_placed=placed_cards(),
                role_tag_pool=_pool_by_role("draw"),
                power_target=request.power_target,
                commander=commander.model_dump(mode="json"),
            )
        self._trace_candidates("draw_selected", [a.card for a in draw])
        if hasattr(draw_gen, "selection_receipt"):
            self._intelligence["draw_portfolio"] = draw_gen.selection_receipt
        all_assignments.extend(draw)
        budget_used += sum(float(a.card.get("price_usd", 0) or 0) for a in draw)
        _trace_infra(draw, "infra_draw")

        # 3. Removal + board wipes
        removal_pool = _pool_by_role("removal") + _pool_by_role("board_wipe")
        # Deduplicate
        seen = set()
        deduped_removal = []
        for c in removal_pool:
            cid = c.get("id", id(c))
            if cid not in seen:
                seen.add(cid)
                deduped_removal.append(c)

        removal_gen = RemovalPackageGenerator(self.db_path)
        removal = removal_gen.generate(
            color_identity=colors,
            target_count=template.removal_count,
            budget_remaining=role_budget(0.15),
            template=template,
            already_placed=placed_cards(),
            role_tag_pool=deduped_removal,
            board_wipe_target=template.board_wipe_count,
            commander_colors=colors,
            avg_cmc=template.avg_cmc_target,
            pool_index=pool_index,
        )
        all_assignments.extend(removal)
        budget_used += sum(float(a.card.get("price_usd", 0) or 0) for a in removal)
        _trace_infra(removal, "infra_removal")
        self._protected_names |= removal_gen.protected_names

        # 4. Protection (before lands; slots come from differentiator pool)
        protection_pool = _pool_by_role("protection")
        # Default 3 protection slots; role_targets will refine in Stage 5+6
        protection_target = min(4, max(2, template.differentiator_slots // 10))
        prot_gen = ProtectionPackageGenerator(self.db_path)
        protection = prot_gen.generate(
            color_identity=colors,
            target_count=protection_target,
            budget_remaining=role_budget(0.10),
            template=template,
            already_placed=placed_cards(),
            role_tag_pool=protection_pool,
            commander_colors=colors,
            avg_cmc=template.avg_cmc_target,
            pool_index=pool_index,
        )
        all_assignments.extend(protection)
        budget_used += sum(float(a.card.get("price_usd", 0) or 0) for a in protection)
        _trace_infra(protection, "infra_protection")
        self._protected_names |= prot_gen.protected_names

        # 5. Lands (last, so it knows what spells need color support).
        # Budget capped at the corpus's median land spend share (x1.25 slack):
        # price-neutral scoring otherwise buys premium mana bases -- one build
        # put ~$110 of a $200 budget into lands, topped by a $45 Gemstone
        # Caverns. Real decks of the variant define what lands should cost.
        # A missing corpus share (0.0) must cap at a typical share, not fall
        # through to the entire remaining budget: one Agatha build with
        # share=0 put $160 into lands, starved the spell stages, and shipped
        # a silently-backfilled 74-land deck. Observed corpus shares run
        # 0.13-0.24, so 0.20 is a representative default.
        share = template.land_budget_share or 0.20
        land_budget = min(
            request.budget_usd - budget_used,
            request.budget_usd * share * 1.25,
        )
        land_gen = LandPackageGenerator(self.db_path)
        lands = land_gen.generate(
            color_identity=colors,
            target_count=template.land_count,
            budget_remaining=land_budget,
            template=template,
            already_placed=placed_cards(),
            role_tag_pool=_land_pool(),
        )
        all_assignments.extend(lands)
        budget_used += sum(float(a.card.get("price_usd", 0) or 0) for a in lands)

        return all_assignments, budget_used

    def _optimize_differentiators(
        self,
        candidates,
        infrastructure,
        profile_result,
        commander,
        request,
        template,
        budget_used,
        reserved_count=0,
    ) -> tuple[list, dict]:
        """Stage 5+6: Synergy-aware greedy optimization.

        Replaces category_coverage + _fill_differentiators with:
        1. Compute role targets (hypergeometric reliability)
        2. Build synergy matrix (rules + co-occurrence + embeddings)
        3. Greedy fill differentiator slots
        4. Swap refinement (infrastructure cards eligible)
        5. LLM safety net on weakest picks

        Args:
            reserved_count: Differentiator slots already taken by empirical
                staples reserved in Stage 3.5, subtracted from the greedy fill.

        Returns:
            Tuple of (all_assignments including infrastructure, optimizer_metrics).
        """
        from sabermetrics.analytics.oracle_keywords import (
            extract_referenced_keywords,
            extract_referenced_mechanics,
        )
        from sabermetrics.analytics.role_targets import compute_role_targets
        from sabermetrics.analytics.synergy_matrix import build_synergy_matrix
        from sabermetrics.pipeline.greedy_optimizer import (
            ProfileSignals,
            deck_objective,
            greedy_fill,
            swap_refine,
        )

        profile = profile_result.profile

        # Build profile signals for alignment scoring
        prof_signals = ProfileSignals(
            referenced_keywords=extract_referenced_keywords(commander.oracle_text),
            referenced_mechanics=extract_referenced_mechanics(commander.oracle_text),
        )

        self._emit_progress("optimize")
        # 1. Compute role targets
        role_targets = compute_role_targets(profile, template)

        # Use feasible composition targets instead of letting independent
        # hypergeometric wish lists demand seven wipes in every archetype.
        for role, count in {
            "ramp": template.ramp_count,
            "draw": template.draw_count,
            "removal": template.removal_count,
            "board_wipe": template.board_wipe_count,
        }.items():
            target = role_targets[role]
            target.target_count = count
            target.min_count = max(0, count - 2)
            target.max_count = count + 4

        if getattr(self, "_strategy_plan", None) and self._strategy_plan.requirements:
            for role, count in {
                "wincon": 3,
                "tutor": 2,
                "recursion": 2,
                "protection": 3,
            }.items():
                role_targets[role].target_count = count
                role_targets[role].min_count = max(0, count - 1)
                role_targets[role].max_count = count + 2

        # 2. Build synergy matrix
        synergy = build_synergy_matrix(
            candidates,
            commander.id,
            self.db_path,
        )
        # Record which pairwise signals were live (rules / embeddings).
        if hasattr(self, "_signals"):
            self._signals.update(synergy.signals)

        self._emit_progress("assemble")
        # 3. Greedy fill: fill EVERY slot not yet placed, to reach exactly 99.
        # Deriving this from template.differentiator_slots (minus protection
        # and reservations) assumed every prior stage hit its target exactly.
        # When the role generators under-produce -- Sauron's ramp placed 2 of
        # 10, draw 0 -- that arithmetic left greedy far short (and reserved +
        # protection could drive it to 0 outright), so the deck reached only
        # ~78 cards and legality backfilled 21 basics into a 57-land deck.
        # infrastructure already holds lands + all generator output + reserved
        # staples, so 99 - len(infrastructure) is exactly the empty-slot count;
        # role_targets steer greedy to the under-served roles first.
        # (reserved_count is now implicit in len(infrastructure).)
        diff_slots = max(0, 99 - len(infrastructure))
        from sabermetrics.intelligence.experiment import current as route_policy

        if route_policy().draw_package_policy == "routes":
            from sabermetrics.intelligence.draw_route_policy import (
                audit_assignments,
                constrain_candidates,
            )

            self._intelligence["draw_route_role_changes"] = constrain_candidates(
                candidates,
                [a.card for a in infrastructure],
                commander.model_dump(mode="json"),
                request.power_target,
            )
            self._intelligence["infrastructure_draw_routes"] = audit_assignments(
                infrastructure,
                commander.model_dump(mode="json"),
                request.power_target,
                enforce=True,
            )
        self._trace_candidates("infrastructure", [a.card for a in infrastructure])
        diff_assignments = greedy_fill(
            shell=infrastructure,
            candidates=candidates,
            synergy=synergy,
            role_targets=role_targets,
            budget_remaining=request.budget_usd - budget_used,
            slots_remaining=diff_slots,
            tracer=self._tracer,
            profile_signals=prof_signals,
            type_targets=template.type_targets,
        )
        all_assignments = list(infrastructure) + diff_assignments
        self._trace_candidates("greedy", [a.card for a in all_assignments])
        from sabermetrics.intelligence.experiment import current as active_policy
        from sabermetrics.intelligence.upstream_guard import snapshot

        if not hasattr(self, "_intelligence"):
            self._intelligence = {}
        upstream = {
            "policy": active_policy().to_dict(),
            "snapshots": {"greedy": snapshot(all_assignments)},
            "transactions": [],
        }
        self._intelligence["upstream"] = upstream

        from sabermetrics.intelligence.alternatives import choose_strategy_variant
        from sabermetrics.intelligence.strategy import StrategyPlan

        all_assignments, variants = choose_strategy_variant(
            all_assignments,
            infrastructure,
            candidates,
            synergy,
            role_targets,
            request.budget_usd,
            getattr(self, "_strategy_plan", StrategyPlan()),
            prof_signals,
            template.type_targets,
        )
        if hasattr(self, "_intelligence"):
            self._intelligence["strategy_comparisons"] = variants
        upstream["snapshots"]["after_strategy_variant"] = snapshot(all_assignments)

        self._emit_progress("refine")
        # 4. Swap refinement (infrastructure cards eligible for swap)
        protected = getattr(self, "_protected_names", None) or set()
        protected |= set(getattr(self, "_engine_protect_names", None) or ())
        all_assignments, swaps = swap_refine(
            deck=all_assignments,
            candidates=candidates,
            synergy=synergy,
            role_targets=role_targets,
            budget=request.budget_usd,
            protect_lands=True,
            protected_names=protected,
            tracer=self._tracer,
            profile_signals=prof_signals,
            commander=commander.model_dump(mode="json"),
            transaction_log=upstream["transactions"],
        )
        self._trace_engine_snapshot("swaps", all_assignments)

        # Note on Option A criterion 4 (no per-card LLM in the hot path):
        # the deterministic optimizer remains the selector. The vet below is
        # ONE batched call auditing the assembled deck, not a per-card scorer
        # in the selection loop -- SME-directed final gate after build 7-9
        # showed the numeric objective cannot read oracle text.
        # 5. Budget rebalancing: spend-down upgrades, sell-one-buy-many audit
        # of expensive picks, downgrade safety net. Runs BEFORE the LLM vet:
        # the numeric objective cannot read oracle text, and in one build it
        # re-admitted Paraselene ("destroy all enchantments") right after the
        # vet had removed it. The LLM must be the final gate nothing bypasses.
        from sabermetrics.pipeline.greedy_optimizer import rebalance_budget

        all_assignments, rebalance_stats = rebalance_budget(
            all_assignments,
            candidates,
            synergy,
            role_targets,
            budget=request.budget_usd,
            template=template,
            profile_signals=prof_signals,
            protected_names=protected,
            tracer=self._tracer,
            commander=commander.model_dump(mode="json"),
            transaction_log=upstream["transactions"],
        )
        self._trace_engine_snapshot("rebalance", all_assignments)
        upstream["snapshots"]["after_rebalance"] = snapshot(all_assignments)

        # 5.5 Engine-floor repair: meet hard subtype minimums (engine-30
        # rule) that soft scoring pressure never reaches -- the type-need
        # multiplier is 1.15x within 75% of target, so selection equilibrates
        # at the corpus median even when the floor sits above it. Runs after
        # rebalance (which is not type-aware and could undo it) and before
        # the vet, so every swapped-in card still faces the LLM gate.
        all_assignments, floor_swaps = self._enforce_type_floors(
            all_assignments,
            candidates,
            template,
            budget=request.budget_usd,
            protected_names=protected,
        )
        self._trace_engine_snapshot("type_floor", all_assignments)

        # 6. LLM safety net LAST: one batched Sonnet call over the riskiest
        # ~14 picks, with corpus evidence in the prompt.
        self._emit_progress("review")
        review_started = time.time()
        self._review_consumed_cost = 0.0
        llm_cost = 0.0
        self._review_failed = False
        try:
            all_assignments, llm_cost = self._llm_safety_check(
                all_assignments,
                candidates,
                synergy,
                role_targets,
                profile_result,
                request,
                n_weakest=18,  # bounded risk review; explicit coverage is persisted
                protected_names=protected,
            )
            if llm_cost < 0:
                self._review_failed = True
                llm_cost = 0.0
        except Exception as e:  # noqa: BLE001 - isolate external review failures
            # A silently-skipped vet produced the worst deck of the project
            # (build7: an AttributeError left 29 unreviewed swaps in). Log the
            # error type and surface the failure in pipeline metrics.
            # Never use a negative sentinel: that subtracted spend from the
            # ledger while hiding the failure.
            logger.error("LLM safety check failed (%s)", type(e).__name__)
            self._review_failed = True
            llm_cost = 0.0
        llm_cost = max(llm_cost, self._review_consumed_cost)
        self._trace_engine_snapshot("review", all_assignments)

        # Add fit reasoning for cards that lack it
        for a in all_assignments:
            if "_fit_reasoning" not in a.card:
                a.card["_fit_reasoning"] = "Synergy-optimizer selected"

        metrics = {
            "synergy_matrix_size": len(synergy.card_id_to_index),
            "role_targets": {r: t.target_count for r, t in role_targets.items()},
            "cards_swapped": swaps,
            "review_seconds": time.time() - review_started,
            "llm_safety_cost": llm_cost,
            "llm_safety_failed": self._review_failed,
            "budget_utilization": rebalance_stats.get("utilization", 0.0),
            "rebalance_upgrades": rebalance_stats.get("upgrades", 0),
            "rebalance_unbundles": rebalance_stats.get("unbundles", 0),
            "type_floor_swaps": floor_swaps,
            "objective_score": deck_objective(
                [a.card for a in all_assignments],
                synergy,
                role_targets,
                template,
                profile_signals=prof_signals,
            ),
        }
        upstream["snapshots"]["after_optimizer_review"] = snapshot(all_assignments)
        return all_assignments, metrics

    def _enforce_type_floors(
        self,
        assignments: list,
        candidates: list[dict],
        template,
        budget: float,
        protected_names: set[str] | None = None,
    ) -> tuple[list, int]:
        """Repair pass: swap toward hard engine-subtype minimums.

        For each floor (e.g. aura >= 30), replaces the weakest off-type,
        non-protected, non-land picks with the best unplaced on-type
        candidates until the floor is met, candidates run out, or the budget
        can't absorb the price delta. Mirrors _enforce_legality: repair
        deterministically, then let the LLM vet audit the result.

        Args:
            assignments: Current SlotAssignment list.
            candidates: Hard-filtered candidate pool (budget/legality gated).
            template: Deck template carrying type_floors.
            budget: Total deck budget in USD.
            protected_names: Names that must not be swapped out.

        Returns:
            (assignments, swap_count).
        """
        from sabermetrics.pipeline.greedy_optimizer import (
            _empirical_bonus,
            is_playable_as_land,
        )
        from sabermetrics.pipeline.slot_assigner import SlotAssignment

        floors = getattr(template, "type_floors", None)
        if not floors:
            return assignments, 0

        protected = protected_names or set()
        deck_names = {a.card.get("name", "") for a in assignments}
        budget_left = budget - sum(
            float(a.card.get("price_usd", 0) or 0) for a in assignments
        )
        swaps = 0

        for type_name, floor in floors.items():

            def _on_type(card: dict, type_name=type_name) -> bool:
                return type_name in (card.get("type_line") or "").lower()

            count = sum(1 for a in assignments if _on_type(a.card))
            if count >= floor:
                continue

            pool = sorted(
                (
                    c
                    for c in candidates
                    if _on_type(c)
                    and c.get("name", "") not in deck_names
                    and not c.get("_anti_engine")
                    and not is_playable_as_land(c.get("type_line") or "")
                ),
                key=lambda c: (
                    float(c.get("_cvar_score", 0) or 0) + _empirical_bonus(c)
                ),
                reverse=True,
            )
            removable = sorted(
                (
                    a
                    for a in assignments
                    if a.card.get("name", "") not in protected
                    and not _on_type(a.card)
                    and a.slot_role != "land"
                    and not is_playable_as_land(a.card.get("type_line") or "")
                ),
                key=lambda a: a.score,
            )

            for incoming in pool:
                if count >= floor or not removable:
                    break
                price_in = float(incoming.get("price_usd", 0) or 0)
                outgoing = removable[0]
                price_out = float(outgoing.card.get("price_usd", 0) or 0)
                if price_in - price_out > budget_left:
                    continue  # try a cheaper on-type candidate
                removable.pop(0)
                idx = assignments.index(outgoing)
                score = round(
                    min(
                        1.0,
                        float(incoming.get("_cvar_score", 0) or 0)
                        + _empirical_bonus(incoming),
                    ),
                    4,
                )
                assignments[idx] = SlotAssignment(
                    card=incoming,
                    slot_role=_heuristic_role(incoming),
                    score=score,
                    alternatives=[],
                )
                deck_names.discard(outgoing.card.get("name", ""))
                deck_names.add(incoming.get("name", ""))
                budget_left -= price_in - price_out
                count += 1
                swaps += 1
                if self._tracer is not None:
                    reason = f"type floor: {type_name} {count - 1} < {floor}"
                    self._tracer.record(
                        card_name=outgoing.card.get("name", ""),
                        stage="type_floor",
                        action="swapped_out",
                        card_id=outgoing.card.get("id"),
                        score=outgoing.score,
                        reason=reason,
                        force=True,
                    )
                    self._tracer.record(
                        card_name=incoming.get("name", ""),
                        stage="type_floor",
                        action="swapped_in",
                        card_id=incoming.get("id"),
                        score=score,
                        reason=f"replaced {outgoing.card.get('name', '')}",
                        force=True,
                    )

            if count < floor:
                logger.warning(
                    "Type floor unmet after repair: %s %d < %d",
                    type_name,
                    count,
                    floor,
                )

        return assignments, swaps

    @staticmethod
    def _safety_review_order(indexed, corpus_active: bool, threshold: float):
        """Order review candidates: uncorroborated picks first, then weakest.

        The weakest-N ordering missed the real failure mode -- cards the
        synergy matrix ranked highly on rule/embedding text matches with zero
        support in the variant's real decks (Tallowisp "fetches Auras" but
        needs Spirits; Yiazmat matched on nothing but embedding noise). With a
        reliable corpus, those uncorroborated picks are the highest-risk
        cohort, so they are reviewed before merely weak corroborated ones.

        Args:
            indexed: (deck_index, assignment) pairs eligible for review.
            corpus_active: Whether a reliable empirical corpus exists.
            threshold: Inclusion rate below which a pick is uncorroborated.

        Returns:
            The pairs sorted for review.
        """

        def sort_key(pair):
            _, a = pair
            emp = float(a.card.get("_empirical_inclusion", 0.0) or 0.0)
            corroborated = 1 if (not corpus_active or emp >= threshold) else 0
            return (corroborated, a.score)

        return sorted(indexed, key=sort_key)

    @staticmethod
    def _best_replacement(
        candidates,
        deck_names: set[str],
        max_price: float | None = None,
        corpus_active: bool = False,
        corroboration_threshold: float = 0.0,
        corroborated_only: bool = False,
    ):
        """Pick the strongest eligible replacement, not the first in list order.

        Ranked by (corroboration tier, CVAR + empirical bonus). With a
        reliable corpus, any candidate real decks actually play outranks every
        uncorroborated text-matcher regardless of numeric score -- Eiganjo
        Dynastorian ("return all enchantments" text, 0% inclusion, an attack
        condition the scorer can't read) twice entered as a vet replacement
        this way. Uncorroborated cards remain eligible when nothing
        corroborated is affordable, so this is a preference, not a penalty
        (ADR-005 absence-neutrality holds for general scoring).
        """
        from sabermetrics.analytics.empirical_valuation import empirical_bonus
        from sabermetrics.config import settings

        best, best_key = None, (-1, -1.0)
        for c in candidates:
            try:
                price = float(c.get("price_usd", 0) or 0)
            except (TypeError, ValueError):
                continue
            if price < 0:
                continue  # negative-cost sentinels are not discounts
            if (
                c.get("name", "") in deck_names
                or "land" in (c.get("type_line") or "").lower()
                or c.get("_anti_engine")
            ):
                continue
            if max_price is not None and price > max_price:
                continue
            value = float(c.get("_cvar_score", 0.0) or 0.0) + empirical_bonus(
                c,
                settings.scoring.marginal_empirical_weight,
                settings.scoring.marginal_empirical_noisy_weight,
            )
            inclusion = float(c.get("_empirical_inclusion", 0.0) or 0.0)
            tier = 1 if not corpus_active or inclusion >= corroboration_threshold else 0
            # corroborated_only: hard gate, not a preference. Used by the
            # re-vet round, whose picks are accepted without further review
            # -- an unreviewed slot may only be filled by a card real decks
            # play (Agatha: 33 unreviewed text-matchers entered this way).
            if corroborated_only and corpus_active and tier == 0:
                continue
            if (tier, value) > best_key:
                best, best_key = c, (tier, value)
        return best

    def _llm_safety_check(
        self,
        deck,
        candidates,
        synergy,
        role_targets,
        profile_result,
        request,
        n_weakest=8,
        protected_names: set[str] | None = None,
    ) -> tuple[list, float]:
        """Review risky picks and a bounded replacement menu in one model call.

        Args:
            deck: Current deck assignments.
            candidates: Full candidate pool.
            synergy: Synergy matrix.
            role_targets: Role targets.
            profile_result: Commander profile result.
            request: Build request.
            n_weakest: Number of cards to check.
            protected_names: Card names that cannot be replaced (staple protection).

        Returns:
            Tuple of (possibly-modified deck, LLM cost).
        """
        from sabermetrics.config import settings
        from sabermetrics.pipeline.slot_assigner import SlotAssignment

        protected = set(protected_names or ())
        protected |= set(getattr(self, "_engine_protect_names", None) or ())

        # Review candidates: non-land, non-protected (engine package stays)
        indexed = [
            (i, a)
            for i, a in enumerate(deck)
            if a.slot_role != "land"
            and "land" not in (a.card.get("type_line") or "").lower()
            and a.card.get("name", "") not in protected
        ]
        empirical = getattr(self, "_empirical", None)
        corpus_active = empirical is not None and bool(empirical.reliable)
        indexed = self._safety_review_order(
            indexed,
            corpus_active,
            settings.scoring.safety_uncorroborated_max_inclusion,
        )
        weakest = indexed[:n_weakest]
        if hasattr(self, "_stage_counts"):
            self._stage_counts["review_cards"] = len(weakest)

        if not weakest:
            return deck, 0.0

        from sabermetrics.intelligence.cards import facts_for
        from sabermetrics.pipeline.greedy_optimizer import _count_roles
        from sabermetrics.pipeline.quality import replacement_is_valid
        from sabermetrics.reasoning.fit import FitScorer

        deck_names = {a.card.get("name", "") for a in deck}
        menu = []
        excluded = set(deck_names)
        for _ in range(8):
            candidate = self._best_replacement(
                candidates,
                excluded,
                max_price=request.budget_usd,
                corpus_active=corpus_active,
                corroboration_threshold=settings.scoring.safety_uncorroborated_max_inclusion,
            )
            if candidate is None:
                break
            excluded.add(candidate.get("name", ""))
            if not facts_for(candidate).exclusion:
                menu.append(candidate)
        to_review = [a.card for _, a in weakest] + menu
        scorer = FitScorer(self.db_path)
        self._review_consumed_cost = 0.0
        try:
            results = scorer.score_cards_batch(
                cards=to_review,
                profile_summary=self._build_profile_summary(profile_result),
                archetype_definition=profile_result.profile.strategic_profile.primary_archetype,
                partial_deck=[a.card for a in deck],
                empirical_variant=getattr(self, "_empirical_variant", None),
            )
        finally:
            self._review_consumed_cost += getattr(scorer, "last_batch_cost_usd", 0.0)
            if not getattr(scorer, "last_batch_complete", True):
                self._review_failed = True
        # Bind verdicts by identity rather than assuming model response order.
        verdicts = {c.get("id", c.get("name")): v for c, v in results}
        from sabermetrics.intelligence.review import contradictions

        commander_facts = getattr(self, "_commander", None)
        commander_data = (
            commander_facts.model_dump() if commander_facts is not None else {}
        )
        for card in to_review:
            verdict = verdicts.get(card.get("id", card.get("name")))
            if verdict is None:
                card["_fit_review_status"] = "unresolved"
                continue
            errors = contradictions(card, verdict.reasoning, commander_data)
            card["_fit_review_status"] = "unresolved" if errors else "reviewed"
            card["_fit_score"] = verdict.fit_score
            card["_fit_reasoning"] = verdict.reasoning
            if errors:
                self._review_failed = True
                card["_fit_grounding_errors"] = errors
        passed = [
            c
            for c in menu
            if c.get("id", c.get("name")) in verdicts
            and verdicts[c.get("id", c.get("name"))].fit_score > 3
            and c.get("_fit_review_status") == "reviewed"
        ]
        if hasattr(self, "_intelligence"):
            self._intelligence["review"] = {
                "selected_reviewed": len(weakest),
                "eligible_selected": len(indexed),
                "alternatives_reviewed": len(menu),
                "max_model_calls": 1,
                "scope": "Bounded risk review, not exhaustive card review.",
            }
        ca = getattr(getattr(profile_result, "profile", None), "card_analysis", None)
        colors = set(ca.color_identity or []) if ca is not None else None
        for index, assignment in weakest:
            old = assignment.card
            verdict = verdicts.get(old.get("id", old.get("name")))
            if verdict is None:
                self._review_failed = True
                continue
            old["_fit_reasoning"] = verdict.reasoning
            if verdict.fit_score > 3:
                continue
            price = sum(float(a.card.get("price_usd", 0) or 0) for a in deck)
            baseline_counts = _count_roles(deck)
            replaced = False
            for replacement in passed:
                allowed, _ = replacement_is_valid(
                    replacement,
                    commander_colors=colors,
                    deck_names=deck_names,
                    max_price=request.budget_usd
                    - price
                    + float(old.get("price_usd", 0) or 0),
                )
                if not allowed:
                    continue
                proposed = SlotAssignment(
                    card=replacement,
                    slot_role=_heuristic_role(replacement),
                    score=replacement.get("_cvar_score", 0),
                )
                trial = list(deck)
                trial[index] = proposed
                counts = _count_roles(trial)
                if role_targets and any(
                    counts.get(r, 0) < min(baseline_counts.get(r, 0), t.min_count)
                    for r, t in role_targets.items()
                ):
                    continue
                replacement["_fit_reasoning"] = verdicts[
                    replacement.get("id", replacement.get("name"))
                ].reasoning
                deck[index] = proposed
                deck_names.discard(old.get("name", ""))
                deck_names.add(replacement.get("name", ""))
                self._tracer.record(
                    card_name=replacement.get("name", ""),
                    stage="llm_safety",
                    action="swapped_in",
                    reason="Independently reviewed alternative; budget and role floors preserved.",
                    force=True,
                )
                replaced = True
                break
            if not replaced:
                old["_fit_review_status"] = "unresolved"
                self._review_failed = True
                self._tracer.record(
                    card_name=old.get("name", ""),
                    stage="llm_safety",
                    action="flagged",
                    reason="No reviewed replacement satisfies final constraints.",
                    force=True,
                )
        return deck, self._review_consumed_cost

    def _build_profile_summary(self, profile_result) -> str:
        """Build the profile summary string for LLM fit scoring."""
        # Unwrap: profile_result is ProfileResult, .profile is CommanderProfile
        profile = profile_result.profile
        sp = profile.strategic_profile
        profile_summary = (
            f"Commander: {profile.commander_name}\n"
            f"Archetype: {sp.primary_archetype}\n"
            f"Game Plan: {sp.game_plan_summary}\n"
            f"Win Conditions: " + ", ".join(wc.description for wc in sp.win_conditions)
        )

        # Add value inversions
        if sp.value_inversions:
            inversions = sp.value_inversions
            inversion_text = (
                "\n\nVALUE INVERSIONS "
                "(cards with these traits are stronger than they appear):\n"
            )
            for vi in inversions:
                inversion_text += (
                    f"- {vi.normal_heuristic} → {vi.inverted_value}\n"
                    f"  Look for: {', '.join(vi.desired_characteristics)}\n"
                    f"  Evaluation: {vi.evaluation_guidance}\n"
                )
            profile_summary += inversion_text

        # Add engine dependencies
        if hasattr(sp, "engine_dependencies"):
            deps = sp.engine_dependencies
            if deps:
                dep_text = (
                    "\n\nENGINE DEPENDENCIES "
                    "(cards must feed the engine, not just match outputs):\n"
                )
                for dep in deps:
                    dep_text += (
                        f"- Engine: {dep.engine}\n"
                        f"  Engine card traits: "
                        f"{', '.join(dep.engine_card_traits)}\n"
                        f"  Dependent outputs: "
                        f"{', '.join(dep.dependent_outputs)}\n"
                        f"  FALSE SYNERGY WARNING: "
                        f"{dep.false_synergy_warning}\n"
                    )
                profile_summary += dep_text

        # Add mispriced card examples
        if hasattr(sp, "mispriced_card_examples"):
            examples = sp.mispriced_card_examples
            if examples:
                example_text = (
                    "\n\nMISPRICED CARDS "
                    "(these cards are better than they appear for this commander):\n"
                )
                for ex in examples:
                    example_text += f"- {ex.card_name}: {ex.why_undervalued}\n"
                example_text += (
                    "\nCards similar to these mispriced examples should score 7-9. "
                    "Use these as calibration anchors for the full scoring range.\n"
                )
                profile_summary += example_text

        return profile_summary

    def _enforce_legality(
        self,
        deck: list,
        commander: Card,
        protected_names: set[str] | None = None,
    ) -> list:
        """Stage 7b: enforce Commander legality as a hard invariant.

        Guarantees on return:
          * exactly 99 non-commander cards;
          * singleton — no duplicate card names except basic lands;
          * every card's color identity is a subset of the commander's.

        Repairs rather than warns: out-of-identity cards and the commander
        itself are dropped, duplicate nonbasics are collapsed to the highest
        scoring copy, an over-full deck is trimmed weakest-first (basics, then
        non-protected non-lands, then non-protected lands), and a short deck is
        filled with basic lands in the commander's colors.

        Args:
            deck: Current SlotAssignment list (may be ≠99, may have dupes).
            commander: The commander card (excluded from the 99).
            protected_names: Names that must not be trimmed (staples).

        Returns:
            Exactly 99 legal SlotAssignments.
        """
        protected = protected_names or set()
        commander_colors = set(commander.color_identity or [])

        def _is_basic(name: str) -> bool:
            return name in _BASIC_LAND_NAMES

        def _is_land(a) -> bool:
            return (
                a.slot_role == "land"
                or "land" in (a.card.get("type_line") or "").lower()
            )

        # Pass 1: drop commander/dupes/out-of-identity, keeping best per name.
        by_score = sorted(deck, key=lambda a: a.score, reverse=True)
        seen: set[str] = set()
        kept: list = []
        for a in by_score:
            name = a.card.get("name", "")
            # "X // X" double-sided variants are X for singleton purposes --
            # a rex-variant Command Tower once joined the regular one.
            if " // " in name:
                front, _, back = name.partition(" // ")
                if front == back:
                    name = front
            if not name or name == commander.name:
                continue
            from sabermetrics.intelligence.eligibility import main_deck_eligible

            if not main_deck_eligible(a.card):
                if getattr(self, "_tracer", None) is not None:
                    self._tracer.record(
                        card_name=name,
                        stage="legality",
                        action="rejected",
                        reason="not a main-deck card type",
                        force=True,
                    )
                continue
            if not _is_basic(name):
                if name in seen:
                    continue  # singleton violation — drop the weaker copy
                ci = _parse_color_identity(a.card)
                if not ci <= commander_colors:
                    self._tracer.record(
                        card_name=name,
                        stage="legality",
                        action="rejected",
                        card_id=a.card.get("id"),
                        reason="out of color identity",
                        force=True,
                    )
                    continue
                seen.add(name)
            kept.append(a)

        # Pass 2: trim to 99 if over (basics → weak non-land → weak land).
        if len(kept) > 99:

            def _removable_rank(a) -> tuple[int, float]:
                name = a.card.get("name", "")
                if _is_basic(name):
                    return (0, a.score)  # basics first
                if name in protected:
                    return (3, a.score)  # protected last
                return (1 if not _is_land(a) else 2, a.score)

            # Remove highest-rank / lowest-score first until exactly 99.
            kept.sort(key=_removable_rank)  # ascending: first = most removable
            excess = len(kept) - 99
            for a in kept[:excess]:
                self._tracer.record(
                    card_name=a.card.get("name", ""),
                    stage="legality",
                    action="swapped_out",
                    card_id=a.card.get("id"),
                    score=a.score,
                    reason="trimmed to reach 99",
                    force=True,
                )
            kept = kept[excess:]

        # Pass 3: fill to 99 with basic lands in the commander's colors.
        # This is a last-resort repair for a card or two -- a large fill
        # means an upstream stage under-produced (a $160 land overspend once
        # starved the spell stages into a silently-shipped 74-land deck), so
        # it must be LOUD: traced and warned, never invisible.
        if len(kept) < 99:
            shortfall = 99 - len(kept)
            self._legality_backfill = shortfall
            if shortfall > 2:
                logger.warning(
                    "Legality repair backfilling %d basics -- an upstream "
                    "stage under-produced; inspect the build",
                    shortfall,
                )
            if getattr(self, "_tracer", None) is not None:
                self._tracer.record(
                    card_name=f"{shortfall}x basic land",
                    stage="legality",
                    action="placed",
                    reason="backfill to 99 (upstream shortfall)",
                    force=True,
                )
            kept.extend(_make_basic_lands(shortfall, commander.color_identity or []))

        if len(kept) != 99:  # invariant must hold
            logger.error("Legality repair produced %d cards (expected 99)", len(kept))
        return kept

    def _synthesize_narrative(
        self, profile_result, assembly, request, classification=None
    ):
        """Render a final-list facts summary.

        Supplies the synthesizer with actual final-card facts (name, mana
        value, oracle text, type, role). Name-only callers of DeckSynthesizer
        remain supported; this builder path does not invent missing evidence.
        """
        from sabermetrics.pipeline.intent import oracle_text_of

        profile = profile_result.profile
        sp = profile.strategic_profile
        profile_summary = (
            f"Commander: {profile.commander_name}\n"
            f"Archetype: {sp.primary_archetype}\n"
            f"Game Plan: {sp.game_plan_summary}"
        )

        deck_cards_with_reasoning = []
        commander = getattr(self, "_commander", None)
        if commander is not None:
            deck_cards_with_reasoning.append(
                {
                    "name": commander.name,
                    "role": "commander",
                    "slot_role": "commander",
                    "mana_value": commander.cmc,
                    "oracle_text": commander.oracle_text,
                    "type_line": commander.type_line,
                }
            )
        for assignment in assembly.assignments:
            card = assignment.card
            mana_value = card.get("cmc", card.get("mana_value"))
            type_line = card.get("type_line") or ""
            oracle = oracle_text_of(card)
            deck_cards_with_reasoning.append(
                {
                    "name": card.get("name", "Unknown"),
                    "slot_role": assignment.slot_role,
                    "role": assignment.slot_role,
                    "mana_value": mana_value,
                    "cmc": mana_value,
                    "oracle_text": oracle,
                    "type": type_line,
                    "type_line": type_line,
                    "fit_score": round(assignment.score * 10, 1),
                    "reasoning": card.get("_fit_reasoning") or "",
                }
            )

        estimated = getattr(classification, "estimated_bracket", None)
        requested = request.power_target
        bracket_reasoning = (
            f"Requested bracket {requested}; estimated bracket "
            f"{estimated if estimated is not None else 'unknown'}. "
            "The classifier is a heuristic, not ground truth."
        )

        try:
            from sabermetrics.reasoning.synthesis import DeckSynthesizer

            synthesizer = DeckSynthesizer(self.db_path)
            synthesis, cost = synthesizer.synthesize(
                profile_summary=profile_summary,
                deck_cards_with_reasoning=deck_cards_with_reasoning,
                bracket=estimated if estimated is not None else requested,
                bracket_reasoning=bracket_reasoning,
            )
            narrative = DeckNarrative(
                game_plan=synthesis.game_plan,
                key_synergies=synthesis.key_synergies,
                weaknesses=synthesis.weaknesses,
                suggested_play_pattern=synthesis.suggested_play_pattern,
            )
            if hasattr(self, "_signals"):
                self._signals["narrative"] = True
            return narrative, cost
        except Exception as e:  # noqa: BLE001 - summary errors must fail conservatively
            logger.warning("Narrative synthesis failed (%s)", type(e).__name__)
            if hasattr(self, "_signals"):
                self._signals["narrative"] = False
            narrative = DeckNarrative(
                game_plan="A summary could not be prepared for this deck.",
                key_synergies=[],
                weaknesses=["Deck summary unavailable."],
                suggested_play_pattern="Review the listed cards and their printed rules text.",
            )
            return narrative, 0.0

    def _classify_bracket(self, assembly):
        """Classify deck power bracket."""
        from sabermetrics.analytics.brackets import classify_bracket

        cards = [a.card for a in assembly.assignments]
        bracket_result = classify_bracket(
            cards=cards,
            db_path=self.db_path,
        )
        return DeckClassification(
            estimated_bracket=bracket_result.bracket,
            bracket_reasoning="; ".join(bracket_result.reasoning),
        )

    def _build_deck_model(
        self,
        commander: Card,
        request: DeckBuildRequest,
        profile,
        assembly,
        narrative: DeckNarrative,
        classification: DeckClassification,
        total_cost: float,
        start_time: float,
    ) -> GeneratedDeck:
        """Build the final GeneratedDeck model."""
        weights = request.weights or CVARWeights()

        # Build DeckCard list
        deck_cards: list[DeckCard] = []
        for assignment in assembly.assignments:
            card_data = assignment.card
            cvar_data = card_data.get("_cvar_result", {})

            ci = card_data.get("color_identity", "[]")
            if isinstance(ci, str):
                ci = json.loads(ci)
            kw = card_data.get("keywords", "[]")
            if isinstance(kw, str):
                kw = json.loads(kw)

            colors = card_data.get("colors")
            if isinstance(colors, str):
                colors = json.loads(colors) if colors else None
            card_model = Card(
                id=card_data.get("id", ""),
                oracle_id=card_data.get("oracle_id", ""),
                name=card_data.get("name", ""),
                mana_cost=card_data.get("mana_cost"),
                cmc=float(card_data.get("cmc", 0)),
                power=(
                    str(card_data["power"])
                    if card_data.get("power") is not None
                    else None
                ),
                toughness=(
                    str(card_data["toughness"])
                    if card_data.get("toughness") is not None
                    else None
                ),
                type_line=card_data.get("type_line", ""),
                oracle_text=card_data.get("oracle_text"),
                color_identity=ci,
                colors=colors,
                keywords=kw,
                is_legal_commander=bool(card_data.get("is_legal_commander", False)),
                is_legal_in_99=bool(card_data.get("is_legal_in_99", True)),
                set_code=card_data.get("set_code", ""),
                rarity=card_data.get("rarity", "common"),
                image_uri=card_data.get("image_uri"),
                last_updated=card_data.get("last_updated", datetime.now(UTC)),
                current_price_usd=card_data.get("price_usd"),
            )

            sub_scores = CardSubScores(
                synergy=cvar_data.get("synergy_score", 0.0),
                mana_efficiency=cvar_data.get("mana_efficiency_score", 0.0),
                replacement_value=cvar_data.get("replacement_value_score", 0.0),
                price_efficiency=cvar_data.get("price_efficiency_score", 0.0),
                card_win_equity=cvar_data.get("card_win_equity"),
            )

            deck_cards.append(
                DeckCard(
                    card=card_model,
                    slot_role=assignment.slot_role,
                    cvar_score=assignment.score,
                    sub_scores=sub_scores,
                    llm_fit=LLMFit(
                        score=max(1, min(10, int(card_data.get("_fit_score", 1)))),
                        status=card_data.get("_fit_review_status", "unreviewed"),
                        reasoning=card_data.get("_fit_reasoning", "Auto-scored"),
                    ),
                    alternatives=assignment.alternatives,
                )
            )

        # Composition stats
        from sabermetrics.analytics.brackets import _detect_combos

        all_card_dicts = [a.card for a in assembly.assignments]

        # Mana curve
        mana_curve = [0] * 8
        color_dist: dict[str, int] = {}
        type_dist: dict[str, int] = {}
        for card in all_card_dicts:
            cmc = int(float(card.get("cmc", 0)))
            mana_curve[min(cmc, 7)] += 1

            ci = card.get("color_identity", "[]")
            if isinstance(ci, str):
                ci = json.loads(ci)
            for c in ci:
                color_dist[c] = color_dist.get(c, 0) + 1

            type_line = card.get("type_line", "")
            for t in [
                "Creature",
                "Instant",
                "Sorcery",
                "Artifact",
                "Enchantment",
                "Planeswalker",
                "Land",
            ]:
                if t in type_line:
                    type_dist[t] = type_dist.get(t, 0) + 1

        non_lands = [
            c
            for c in all_card_dicts
            if "land" not in (c.get("type_line") or "").lower()
        ]
        cmcs = [float(c.get("cmc", 0)) for c in non_lands if c.get("cmc")]
        avg_cmc = sum(cmcs) / len(cmcs) if cmcs else 0.0

        gc_names = []
        try:
            from sabermetrics.analytics.brackets import _load_game_changers

            game_changers = _load_game_changers()
            for card in all_card_dicts:
                name = (card.get("name") or "").lower()
                if name in game_changers:
                    gc_names.append(card.get("id", ""))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning(
                "Optional trace or classification data unavailable (%s)",
                type(exc).__name__,
            )

        combos = _detect_combos(all_card_dicts, self.db_path)
        combo_ids = [c["id"] for c in combos]

        from sabermetrics.pipeline.greedy_optimizer import _count_roles

        role_counts = _count_roles(assembly.assignments)
        composition = DeckComposition(
            total_price_usd=assembly.total_price,
            average_cmc=round(avg_cmc, 2),
            color_distribution=color_dist,
            type_distribution=type_dist,
            mana_curve=mana_curve,
            component_counts=ComponentCounts(
                ramp=role_counts.get("ramp", 0),
                draw=role_counts.get("draw", 0),
                removal=role_counts.get("removal", 0),
                board_wipes=role_counts.get("board_wipe", 0),
                tutors=role_counts.get("tutor", 0),
                win_conditions=role_counts.get("wincon", 0),
            ),
            game_changers_present=gc_names,
            detected_combos=combo_ids,
        )

        deck_id = request.deck_id or str(uuid.uuid4())
        elapsed = time.time() - start_time

        return GeneratedDeck(
            id=deck_id,
            commander=commander,
            generated_at=datetime.now(UTC),
            parameters=DeckParameters(
                budget_usd=request.budget_usd,
                power_target=request.power_target,
                strategy=request.strategy,
                weights=weights,
                deck_name=request.deck_name,
            ),
            cards=deck_cards,
            composition=composition,
            classification=classification,
            narrative=narrative,
            meta=GenerationMeta(
                generation_time_seconds=round(elapsed, 2),
                llm_cost_usd=round(total_cost, 4),
                source_profile_id=profile.commander_id,
                signals_used=sorted(k for k, v in self._signals.items() if v),
                signals_unavailable=sorted(
                    k for k, v in self._signals.items() if not v
                ),
            ),
        )

    def _persist_deck(self, deck: GeneratedDeck) -> None:
        """Save to generated_decks table."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cards_json = json.dumps(
                [
                    {
                        "card_id": dc.card.id,
                        "name": dc.card.name,
                        "slot_role": dc.slot_role,
                        "cvar_score": dc.cvar_score,
                        "fit_score": (
                            dc.llm_fit.score
                            if dc.llm_fit.status == "reviewed"
                            else None
                        ),
                        "fit_review_status": dc.llm_fit.status,
                        "reasoning": dc.llm_fit.reasoning,
                        "alternatives": dc.alternatives,
                    }
                    for dc in deck.cards
                ]
            )

            rationale = json.dumps(
                {
                    "narrative": deck.narrative.model_dump(),
                    "composition": deck.composition.model_dump(),
                    "signals_used": deck.meta.signals_used,
                    "signals_unavailable": deck.meta.signals_unavailable,
                    "quality_warnings": list(getattr(self, "_quality_warnings", [])),
                    "stage_timings": dict(getattr(self, "_stage_timings", {})),
                    "stage_counts": dict(getattr(self, "_stage_counts", {})),
                    "engine": getattr(self, "_engine_rationale", None),
                    "intelligence": getattr(self, "_intelligence", {}),
                }
            )

            conn.execute(
                "INSERT OR REPLACE INTO generated_decks "
                "(id, commander_id, profile_id, budget_usd, power_target, "
                "strategy, cards_json, rationale, cvar_score, "
                "estimated_bracket, generated_at, deck_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    deck.id,
                    deck.commander.id,
                    deck.meta.source_profile_id,
                    deck.parameters.budget_usd,
                    deck.parameters.power_target,
                    deck.parameters.strategy,
                    cards_json,
                    rationale,
                    (
                        sum(dc.cvar_score for dc in deck.cards) / len(deck.cards)
                        if deck.cards
                        else 0.0
                    ),
                    deck.classification.estimated_bracket,
                    deck.generated_at.isoformat(),
                    deck.parameters.deck_name,
                ),
            )
            conn.commit()
            logger.info("Persisted deck %s", deck.id)
        finally:
            conn.close()


# Basic land names that are exempt from the singleton rule.
_BASIC_LAND_NAMES: set[str] = {
    "Plains",
    "Island",
    "Swamp",
    "Mountain",
    "Forest",
    "Wastes",
    "Snow-Covered Plains",
    "Snow-Covered Island",
    "Snow-Covered Swamp",
    "Snow-Covered Mountain",
    "Snow-Covered Forest",
}


def _parse_color_identity(card: dict) -> set[str]:
    """Parse a card's color identity into a set, tolerating JSON-string storage."""
    ci = card.get("color_identity", "[]")
    if isinstance(ci, str):
        try:
            ci = json.loads(ci)
        except (json.JSONDecodeError, TypeError):
            ci = []
    return set(ci or [])


def _make_basic_lands(count: int, commander_colors: list[str]) -> list:
    """Create `count` basic-land SlotAssignments in the commander's colors.

    Distributes evenly round-robin across the commander's colored basics;
    a colorless commander gets Wastes. Basic lands carry empty color identity,
    so they are legal in any deck.

    Args:
        count: Number of basics to create (>= 0).
        commander_colors: Commander color identity (e.g. ["W", "U"]).

    Returns:
        List of `count` SlotAssignment objects with slot_role "land".
    """
    from sabermetrics.pipeline.mana_base import COLOR_TO_BASIC
    from sabermetrics.pipeline.slot_assigner import SlotAssignment

    names = [COLOR_TO_BASIC[c] for c in commander_colors if c in COLOR_TO_BASIC]
    if not names:
        names = ["Wastes"]

    out: list = []
    for i in range(max(0, count)):
        name = names[i % len(names)]
        # uuid suffix avoids id collisions with basics minted elsewhere (e.g.
        # the mana-base builder), which also use a "basic-<name>-<n>" scheme.
        out.append(
            SlotAssignment(
                card={
                    "id": f"basic-{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
                    "name": name,
                    "type_line": f"Basic Land — {name}",
                    "oracle_text": "",
                    "mana_cost": "",
                    "cmc": 0.0,
                    "color_identity": "[]",
                    "price_usd": 0.0,
                    "rarity": "common",
                },
                slot_role="land",
                score=0.5,
                alternatives=[],
            )
        )
    return out


def _is_ramp(type_line: str, oracle_text: str) -> bool:
    """Check if a card is a mana-producing ramp spell."""
    if "add" in oracle_text and ("mana" in oracle_text or "{" in oracle_text):
        return True
    if "search your library for a" in oracle_text and "land" in oracle_text:
        return True
    return (
        "put" in oracle_text and "land" in oracle_text and "battlefield" in oracle_text
    )


def _heuristic_role(card: dict) -> str:
    """Classify card role by heuristics when LLM is unavailable."""
    from sabermetrics.pipeline.slot_assigner import (
        _classify_card_role,
        complete_damage_role,
    )

    # Complete creature-targetable damage evidence must survive an incomplete
    # cached facts record, including after a guarded replacement is persisted.
    damage_role = complete_damage_role(card)
    if damage_role is not None:
        return damage_role
    if "_facts" in card:
        roles = card["_facts"]["roles"]
        for role in ("land", "ramp", "draw", "removal", "protection", "wincon"):
            if role in roles:
                return role
        return "utility"
    return _classify_card_role(card)

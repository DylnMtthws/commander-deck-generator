# Fast, informed Commander generation

Architecture proposal, 2026-09-12. Design only; no service, source, or deployment changes.

## Product objective

Produce a coherent, budget-valid deck quickly, then substantiate its choices with executable card facts and supported simulation measurements. Keep the generator independent of Deck Lab's login, database, and release lifecycle. Maintain existing Main/QA availability and resource budgets.

The ambitious outcome is a deck designer that can explain a choice, demonstrate the relevant interaction, measure its effect under declared assumptions, and show a viable alternative.

## Observed baseline and current capability

Aesi live job: 710.54 seconds elapsed; profile 48.68s, optimization 471.51s, review 157.90s. Three model calls cost approximately $0.002406. 799 candidates create 318,801 unordered pairs. Ninety-two optimizer swaps and 27 + 10 review replacements expose excessive rework. The last ten replacements were not reviewed. Final legality/budget checks passed, but card prerequisites and role semantics were wrong in several cases.

Sources: private monitoring receipt in `.private/generator-quality/aesi-monitor-result.json`; generator `analytics/synergy_matrix.py`, `pipeline/greedy_optimizer.py`, `pipeline/deck_builder.py`; simulator `src/core/effects.hpp`, `data/derived-generic.defaults.toml`, contracts; infrastructure `docs/production-simulator.json`.

The recorded deployed simulator acceptance completed 20,000 games end-to-end in 3.48s. This is historical single-request evidence, not current concurrency or Aesi coverage evidence. Local code supports an authored Kinnan pack and an explicit derived-generic mode. Documentation still describing Kinnan-only is partly stale. Generic mode has inherited assembly objectives, unauthored cards, and declared omissions including opponents, stack, combat, mulligans, commander tax, legend rule, and summoning sickness. It is not sufficient to rank arbitrary decks. Verify deployed capabilities before integration rather than infer them from a local branch.

## Proposed flow

Request -> structured strategy plan -> constrained candidate retrieval -> several coherent 99-card variants -> deterministic acceptance -> supported simulation comparisons -> bounded repair -> final acceptance -> grounded explanation.

A separate preparation process publishes a versioned card-intelligence snapshot consumed by generation and the simulator. Database/blob artifacts suffice initially; no graph-database, new queue vendor, or distributed-service framework is required.

## 1. Prepare card intelligence outside the request

Canonical identity is oracle_id; selected printing and price provenance remain separate. Preserve faces, zones, target/controller restrictions, mana costs, timing, and replacement effects.

Publish:
- Normalized public Oracle facts and rulings references, dated legality and prices.
- Embeddings keyed by Oracle text hash and embedding-model revision, computed once per canonical card.
- Rule-clause matches and indexes; never repeatedly parse the same card's JSON/text for every pair.
- Typed effects with trigger, cost, target predicate, destination, resource produced/consumed, prerequisites, and limits.
- Structured relationships: enables, pays-for, searches-for, repeats, protects, conflicts-with. Higher-order packages represent three-or-more-card dependencies.
- Evidence provenance: deterministic parser, reviewed authored rule, model proposal, corpus observation, or simulated measurement. Unknown is distinct from false.

Examples: Den Protector supplies recursion, not removal. A mana ability on a transformed face with a setup cost is not turn-two ramp. A same-name tutor cannot assume a second singleton copy. Paliano needs draft choices; Gond Gate needs a supporting Gate; a creature-land modal card cannot be both creature and land in the same simulated state.

Use models offline to propose annotations for unsupported shapes. Validate and review executable effects before promotion, with example/counterexample tests and source hashes. Do not execute model-generated C++ or promote prose claims into engine facts. Treat new/changed Oracle text as needing revalidation.

Keep coarse discovery tags distinct from verified selection and simulation capabilities. A partially understood card can be suggested with explicit limitations but cannot satisfy a requirement whose relevant effect is unverified.

## 2. Turn intent into a real deck plan

One small structured planning call where needed, using the commander facts and a retrieved library of reviewed archetype templates. Common known requests can resolve deterministically from cached plans. Cache keys include commander facts, normalized intent, constraints and plan/model version.

For landfall, explicitly plan land access, extra land plays, mana development, repeatable land entry, payoffs, replenishment, protection/recovery, and a way to close the game. Distinguish necessary mechanics from preferences; derive feasible coverage targets rather than applying the same quotas to every commander.

Maintain alternatives such as value-landfall, tokens-landfall, and combo-landfall, within the requested power and budget. Protect the chosen strategy's functional core across optimization. A higher bracket is not an objective when the user requested a lower one.

## 3. Retrieve and optimize coherent alternatives

Retrieve candidates from exact capability indexes plus semantic discovery and available empirical evidence. Reserve candidates for rare requirements before coarse Pareto pruning so an individually weak but necessary engine card survives.

Score packages and marginal deck contributions, not just isolated cards. Separate objectives for reliable mana, engine operation, interaction, recovery, cost, and preference fit. Legality, budget, functional prerequisites, singleton, and required protections are constraints, not bonuses a high similarity score can outweigh.

Repair the current stale swap objective immediately. Require each accepted local improvement to improve the current declared objective; retain a nondominated set when trading objectives. Cache per-card features and incremental objective deltas rather than rebuilding full scores for every hypothetical swap.

Generate approximately 4–8 structurally distinct candidates under a bounded search budget. Keep strategic diversity explicit; avoid eight cosmetic variants of the same list. Jointly optimize lands and spells with a reserved engine budget rather than spending nearly everything on infrastructure first.

Persist candidate revisions and decision provenance. Never silently change a saved deck after returning it.

## 4. Put C++ simulation inside candidate selection

The simulator should influence selection before the final explanation, rather than merely produce a badge afterward.

Start with cheap analytical checks and a broad mana/card-flow scenario. Only claim a metric when all effects materially determining it are modeled. A high overall modeled-card percentage is insufficient if the commander, engine or proposed replacement is unsupported.

Proposed simulation capabilities, to implement and validate in stages:
1. Mana development: legal opening-hand policy, land sequencing, tapped/conditional sources, colored costs, usable mana by turn, commander cast timing, screw/flood rates.
2. Archetype resource flow: extra land plays, land entry triggers, land recursion, draw, tokens, setup requirements, and resource exhaustion.
3. Authored engine assembly: existing Kinnan plus explicit validated packages; infinite-loop assertions require repeatable state/resource reasoning, not keyword similarity.
4. Declared disruption scenarios: commander removal or a board reset at a named turn, with modeled recovery. These are stress tests, not simulated multiplayer matches.
5. Later, integrate the existing edh_solver's declared-field/interaction work for supported decision points. Its current abstractions and continuation assumptions require validation; it does not supply a general four-player win-rate oracle.

Aesi's first pack should measure land drops through a chosen turn, cast-Aesi timing, landfall triggers after Aesi resolves, engine cards seen/used, cards drawn, mana availability, and stalled states. Validate extra land allowances and trigger/draw sequencing. Correct sickness/legend/tax/mulligan gaps before using metrics sensitive to them. Aang needs specific copy/legend/trigger and finite-library behavior; generic mode is insufficient.

Suggested bounded comparison schedule (tune from production measurements):
- Screen 4–8 candidates with roughly 1,000–2,000 games each.
- Allocate more games to promising/uncertain comparisons; reject clearly inferior candidates early.
- Confirm one or two finalists with roughly 10,000–20,000 games and fresh validation seeds.
- Use paired common random numbers with a stable documented mapping across deck mutations. Existing ablation machinery is useful, but a variant-batch API and richer metrics are new work.
- Avoid a full 99-card ablation sweep in the interactive path. Deep analysis is a separate explicit job.

Intervals quantify sampling error, not rules/model error. Adaptive search can overfit its evaluation seeds: use held-out seeds for final assessment and fixed-budget intervals or sequential methods appropriate to the stopping rule. Overlapping results should remain a tie rather than manufacture a ranking.

Keep independent minimum interaction and recovery constraints. Goldfish assembly speed must not reward removing counterspells simply because opponents are absent. Unknown crucial effects prohibit the affected comparison; unrelated well-modeled mana checks may still be reported.

## 5. Make reasoning inspectable and bounded

Replace the current two-pass full-deck repair loop with structured reasoning over verified choices. Ask the model to choose or critique from a candidate menu with IDs and evidence, concentrating on unresolved strategic questions. Require final replacement validation; if the bounded review cannot resolve an issue, retain the last accepted candidate with explicit warnings or report infeasibility. Never accept an unverified last replacement merely because a retry cap was reached.

Generate explanations from a decision record: chosen card/package, satisfied requirement, verified effect, alternative considered, cost difference, measured difference when available, and limitations. A model may phrase the explanation but cannot invent cards, measurements, rules or causal certainty. Clearly distinguish selected, simulated, and playtested.

Retrieve primers/corpus evidence from a prepared snapshot, not sequential live Reddit requests. Missing evidence is missing evidence, not zero inclusion. Community popularity is a prior for discovery, not proof of synergy or win contribution. Keep source type, date, sample denominator, and evidence relevance.

## 6. Speed and serving design

First remove repeated work:
- Precompute per-card clause matches. Construct candidate-pair scores from masks/vector operations or sparse indexed edges. This removes repeated semantic parsing; dense pair materialization still has quadratic output cost. Preserve exact current rule outputs before improving rule semantics separately.
- Persist embeddings and reuse immutable snapshots across workers; do not load a model when the reference collection is empty.
- Load card facts and price snapshots once, index canonical IDs, and avoid repeated database/parser calls.
- Cache plans and compiled feature slices by all behavior-affecting versions. Cache simulation by the existing complete simulation input hash, not deck ID alone.
- Bound LLM input/output and retries; use a cached plan for common archetypes. Latency, validity and repair rate decide whether a model route helps; token price alone does not.
- Measure each optimizer substage, queue delay, external call, cache hit/miss, and memory. Emit real stage progress and a last-progress heartbeat.

Aspirational acceptance targets, not measured promises: acknowledgement under 0.5s; first validated deterministic draft within 5–10s on warm data; full warm generation p50 <=30s and p95 <=60s; cold/unfamiliar builds p95 <=90s with visible degraded paths. Benchmark on the existing constrained Droplet, including simultaneous Deck Lab activity. The first milestone is >=90% reduction in Aesi's rule-scoring time with equivalent outputs; end-to-end targets follow measured budgets. Simulation needs a bounded ~5–15s allocation, not unbounded extra optimization.

Publish an optional clearly marked draft while explanation/simulation completes. Full output may return without simulation only when it is explicitly marked unavailable and all deterministic requirements hold. Final results remain reproducible immutable revisions.

Reuse the private C++ service with a narrow authenticated boundary, caller quotas, bounded jobs, timeouts, and cancellation. Preserve generator/Deck Lab database/session isolation: do not attach the generator to a broad production database network. Protect interactive Deck Lab requests from generator batches through admission control and weighted scheduling. Start at the current infrastructure budget; benchmark before buying cores. Heavy preparation/benchmarks can run on the Mac, but normal production generation must work while the Mac is asleep.

## Rollout and acceptance

1. **Correct and accelerate existing selection.** Fix swap baseline, prerequisite/role errors, final-replacement gap; equivalent vectorized rule scoring, prepared embeddings, detailed latency metrics. Freeze Aesi/Aang failures as public/synthetic regressions without publishing user data.
2. **Shared intelligence snapshot and archetype planning.** Implement typed effects and landfall plan; package-aware candidates and consistent role counts. Introduce unknown coverage handling. Benchmark broader archetypes and budget ranges.
3. **Simulation in shadow mode.** Versioned capability discovery and metrics contract; independently validate effects and supported packs. Record comparisons without influencing user decks until deterministic scenarios and ranking tests pass.
4. **Simulation-guided generation.** Enable supported mana/landfall scenarios, candidate batch budgets, held-out confirmation, and evidence-based explanations. Stage reviewed images; preserve Main/QA resource and health checks.
5. **Broader intelligence.** Expand effect vocabulary by shared value across archetypes, add disruption/recovery models, then calibrated declared-field solver integration. Learn preference weights from edits separately from performance; win claims require actual game evidence.

Acceptance suite: exact rules equivalence for performance refactor; no degrading accepted swap; invalid conditional mana never fulfills fixing; correct singleton tutor prerequisites; no unvalidated terminal replacement; deterministic card-interaction scenarios; supported/unsupported metric checks; known beneficial/harmful package comparisons; protection retained despite goldfish invisibility; cache invalidation and reproducibility; latency under production quotas and concurrent Deck Lab load. Compare against the current generator, reviewed archetype templates, and ablations of each new layer. Use held-out commanders/cards and blind human review for strategic quality; do not validate a new heuristic solely against itself.

No rollout is complete based only on a faster runtime or a passing structural deck validator. It must be faster, mechanically sound for claimed effects, and measurably more coherent under independent review.

# Card-selection failure repair: executable specification

## Objective

Correct bad inclusions and missed affordable alternatives. Evaluate where cards are
lost (catalog, legality, recall, scoring, selection, repair), rather than rewarding
higher draw counts or more replacements. Every candidate change needs a recorded
mechanical rationale, known commander/deck relationships and explicit unknowns.
No finite study tests all possible Magic fixes. This program enumerates fix
families, tests implemented factors independently and in combinations, and records
unsupported/unimplemented alternatives instead of claiming exhaustive coverage.

## First implementation milestone

1. Persist exact nullable printed power/toughness/colors through public ingestion,
   additive migration and model hydration. Missing data stays unknown; printed
   colors and Commander identity stay distinct. Test legacy DB migration, idempotent
   ingestion, unusual stats and multi-face unknowns. Never backfill production here.
2. Unify complete targeted-damage role evidence across initial assignment and
   guarded replacement. Shock/Burst/Play with Fire classify consistently absent an
   explicit model override; player-only or incompletely parsed damage does not gain
   a creature-removal claim. Test stale empty/utility cached facts and scope limits.
3. Add ability-level prerequisite evidence. Distinguish missing search target from
   total card uselessness, and unknown dynamic colors from impossible sacrifice.
   Courier's fallback and Dragon's Herald's remaining body must stay visible.
   Evidence alone never authorizes a cut. Integrate diagnostics into final reports.
4. Centralize the actual production selection policy and make study arms inherit it.
   Inspection found the earlier study used land weights 10/1 and budget recall12,
   whereas deployed web generation uses 0/0/0. Preserve current production behavior;
   label the earlier results as that experimental configuration, not exact web
   parity. Record every study's complete effective factor settings.
5. Implement a deterministic registered ablation manifest covering the existing
   recall, land evidence, land risk and guarded-substitution toggles, with explicit
   weights, unique configuration IDs, source/data hashes and cost/run bounds. A
   manifest is not proof an arm was executed. Run targeted policy-equivalence and
   pairwise/full-factorial coverage tests, then ordinary offline commander replays.
6. Validate the above with independent Cursor/Claude work, full unit tests and
   observed replay results. Retain failures/no-ops and report whether any actual
   deck choice improved. Do not deploy this milestone automatically.

## Further fix families and experiments

A. Data: printed facts/provenance, DFC zones, exact prices, stale cache invalidation.
B. Retrieval: broad role alternatives, price-stratified recall, commander-specific
   engine enablers, missing candidate detection before rank truncation.
C. Dependencies: per-ability gates and fallback value; support-aware packages versus
   independent engines. Never infer an entire card is dead from an optional line.
D. Valuation: reliable draw over turns, setup mana/life/opponent gates, interaction
   quality, tempo and preserved tribal/casting relationships.
E. Selection: quota repairs versus constrained package search; protected functions,
   budget feasibility, land/castability and alternative opportunity cost.
F. Simulation: deterministic reference scenarios first, supported coverage reporting,
   common random seeds, confidence intervals, hard latency limits and abstention.
G. Model reasoning: structured evidence retrieval, independent critique, model-free
   baselines and provider/prompt ablations with actual cost and cache disclosure.

Register each family's specific hypotheses and negative cases before tuning. Start
with single-factor ablations; use factorial combinations only for implemented,
independently supported knobs. Larger weight grids advance only if the small grid
shows a benefit. Reserve untouched commander cases before selecting a winner.

## Subsequent quality gates

Use the roadmap's stratified 12 development /8 untouched top-50 commander cohort,
with membership refreshed and recorded before a new live study. Cover powers1–5
and feasible budgets50/150/500/1500; randomize independent repeats and distinguish
cached responses. Changed inclusions receive blind independent review; sample
unchanged weak cards too. Zero legality/budget/identity failures, unproved removals
or unresolved critical changed-card findings. Preserve minimum archetype-specific
draw/interaction/castability requirements; fail or abstain instead of hiding gaps.

Success must include distinct useful affordable alternatives across multiple
commanders, not repeated Shock upgrades alone. Keep Krenko's unusable Herald line,
Courier's fallback, Azula's conditional Pact risk and unresolved draw packages as
explicit counterexamples until demonstrated resolved. Report latency/cost separately
from strategic quality. All no-op cohorts fail the broad improvement objective.

## Failure-driven expansion of the first milestone

The first 22-build execution failed role consistency on 10 saved decks despite
passing transition checks. Greedy role accounting and synergy role labels bypassed
the new slot helper; annotation also stripped removal discovery tags when the old
capability snapshot had no matching shape. Require exact damage-role evidence at
annotation, both optimizer readers, and persisted baseline/candidate validation.
Preserve discovery metadata and old capability coverage separately; a stale proof
must disappear if Oracle text changes. Repeat the same22 cases from the original
data snapshot and compare actual card multisets, not just labels. Source/data
identity and all failed attempts remain visible.

## Newly observed highest-priority selection defect

Role-correct runs expose harmful-looking changes *before* the guarded baseline is
captured. Krenko's swap refinement introduces Bearer of the Heavens; later budget
unbundling sells Goblin Bombardment for an estimated reallocation gain. Vivi loses
Mystic Remora across revisions. A post-baseline proof cannot validate or prevent
these upstream choices. These are strategic regression candidates, not evidence
that more accepted Shock upgrades improve the whole deck.

Next experiment must independently ablate swap refinement and budget unbundling
(off/current/function-preserving), then their combinations. Capture the exact
removed function, candidate alternatives, actual funded replacements and objective
components for every trade. Test estimated gains against realized gains; do not
count money freed as value without demonstrated replacements. Compare initial
selection, each proposal and final deck, keeping internal stage snapshots.

Definitions of done for that repair: no unexplained loss of a proven recurring draw
engine or token-to-damage outlet; no slow off-plan creature admitted for an opaque
small score gain without castability and role/opportunity-cost evidence; countercases
must preserve legitimate expensive death-trigger or sacrifice strategies. Never
solve this by a Bearer blacklist or a universal mana-value cap. Public Oracle and
scenario tests must explain when a card belongs and when it does not. Require
multiple distinct improvements across commanders, including actual low-budget
draw alternatives; rerun untouched controls before recommending deployment.

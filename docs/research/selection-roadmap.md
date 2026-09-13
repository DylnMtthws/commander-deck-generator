# Selection intelligence: next research and validation plan

## Objective and honest boundary

Improve actual deck choices, not merely audit scores or replacement counts. A
release passes only when every changed inclusion in its evaluation cohort has a
reviewable rationale and no unresolved critical regression. Passing a finite test
set cannot guarantee that all future Magic card choices will be good. Unknown
interactions must stay explicit; no model confidence score may erase a failed
legality, budget, resource, or dependency check.

Starting evidence: the commander-substitution cohort demonstrated Shock → Burst
Lightning in two Krenko budget cases, not broad engine intelligence. All draw
packages remained unresolved. Dragon's Herald retains an unusable line in Krenko;
Azula has a conditional Tainted Pact/library-emptying risk. Creature stats are
missing from the current catalog. Preserve those failures as fixtures.

## Priority 1: trustworthy printed facts and consistent roles

Research the canonical multi-face Oracle representation and ingestion path. Add
power/toughness, printed colors versus color identity, face-specific costs/types,
keywords and source revision. Keep unknown values distinct from zero. Backfill
from public card records into an isolated database before production migration.
Unify initial assignment, cached facts, replacement and persisted role classification.

Done when every admitted creature in the evaluation pool has source-backed stats
or an explicit unsupported marker; front/back faces round-trip without fabricated
stats; Shock and Burst Lightning consistently classify as creature-targetable
interaction while player-only damage does not. Repeated ingestion is idempotent,
rollback is documented, and existing auth/deck data is preserved. Require positive
and adversarial tests for dynamic stats, DFCs, Kindred and non-main-deck objects.

## Priority 2: commander/deck prerequisites and useful alternatives

Represent each ability separately: effect, resource demand, activation gates,
required targets, repeatability, timing and fallback value. Distinguish an unusable
ability from an unusable card. Courier of Comestibles has a Food-token fallback;
its missing library target alone must never authorize removal.

Trace each candidate through retrieval, filtering, ranking, selection and repair.
For every rejected strong alternative, record the first decision that excludes it.
Use the supplied Vivi tournament list as one strategic reference, not a template
for every power/budget. Gather public commander lists across archetypes and retain
source/date/provenance; reserve a separate evaluation set before tuning.

Done when the Krenko Dragon's Herald case produces a justified replacement that
preserves relevant Goblin/body resources; sacrifice colors, named targets and
activation requirements are correctly diagnosed; conditional combo risks remain
distinct from declared broken win lines. Require multiple commanders and budgets,
including adversarial cases where the apparently weak card should stay.

## Priority 3: reliable budget draw packages

Build a comparison model for cards gained over turns, upfront/recurring mana,
setup delay, life/resource costs, opponent dependence, color legality and synergy.
Rhystic Study alternatives are not interchangeable: Phyrexian Arena, Notion Thief,
The Unagi of Kyoshi Island and Insight Engine must each be evaluated from verified
current Oracle text and the deck's actual support. Never treat a conditional theft
ability or a delayed engine as unconditional immediate draw.

Generate candidates by functional need and budget band before popularity ranking.
Evaluate packages as well as individual replacements: engine plus enablers versus
independent draw, with protected interaction/ramp/land/finisher resources. Introduce
an explicit abstain/repair outcome when the reliable draw floor cannot be met.

Done when real generations demonstrate at least three distinct justified budget
alternatives across four commander identities and three budget bands, including
low-budget cases. All changed cards must pass mechanical checks and independent
review. Pre-register archetype-specific draw expectations; do not choose a floor
retroactively to make the outputs pass. Report unmet floors and no-op cases.

## Priority 4: measured simulation and selection experiments

Expose the existing fast C++ simulator only through a bounded, versioned interface.
First inventory exactly which abilities it models. Unsupported effects must not
silently become vanilla cards or contribute to a claimed win rate. Start with
opening-hand mana, castability, early commander timing and supported draw-engine
activation; add actual gameplay interactions only with reference scenarios.

Compare paired decks with common random seeds, confidence intervals and explicit
coverage. Calibrate simple deterministic scenarios against exact calculations and
an independent implementation. Use simulation for supported tie-breaks, not to
veto cards whose relevant mechanics are unmodeled. Set a maximum runtime before
experimentation and retain timeout/fallback counts.

Done when deterministic fixtures match reference outcomes, repeated seeds reproduce
results, omitted abilities are reported, and observed gains survive independent
scenario checks. No tournament-strength claim from ingredient/mana probes alone.

## Evaluation design and release gates

1. Freeze public data, prices, model/provider, prompts, policy and source revisions.
   Refresh and record EDHrec top-50 membership when the study begins.
2. Stratify commanders by colors and archetype: spells, tribal, tokens, graveyard,
   artifacts/enchantments, lands, combat and competitive combo. Select 12 development
   and 8 untouched evaluation commanders; cover powers 1–5 and feasible budget
   bands around $50, $150, $500 and $1,500. Do not force an unaffordable commander
   into a nominal budget. Freeze exact cases and exclusions before tuning.
3. Start with offline retrieval/ablation tests: canonical-data repair, dependency
   filtering, role consistency, alternative recall and package scoring separately.
   Only then test combinations. Use a small registered weight grid; tune on
   development cases, never on the untouched set. Preserve all failed runs.
4. Advance only candidates that improve documented failures without critical
   regression. Repeat live model builds three times per finalist case; distinguish
   cache replays from independent calls. Cap spend and concurrency in the manifest.
5. Compare each persisted deck with its own completed baseline. Record legality,
   price, role coverage, prerequisite feasibility, draw expectations, interaction,
   land/castability, unsupported effects, latency p50/p95 and actual model cost.
   Perform blind independent review of every changed inclusion and sampled unchanged
   cards so a safe no-op does not conceal a poor baseline.
6. Release gates: zero mechanical failures, zero unproved cuts, zero unresolved
   critical changed-card findings, all registered quality floors met or explicit
   generation refusal, and no material regression on untouched commanders. Report
   uncertainty and failures; never average away an illegal or broken deck.
7. Stage the exact image with offline/native and owner-access checks. Deploy only
   an approved release, retain image-only rollback, and monitor first owner builds.

For a future implementation round: Cursor handles bounded ingestion fixtures and
role tests; Claude handles prerequisite/draw specifications and independent cases;
the coordinator owns package architecture, experiment design, review and release
gates. This document is a plan, not authorization to begin paid bulk testing.

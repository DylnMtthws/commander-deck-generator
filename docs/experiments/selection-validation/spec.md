# Selection validation study

## Question and decision

Which changes reduce concrete rules/dependency errors and unsupported card choices
without regressing legality, budget, strategy coverage, diversity or runtime?
This is an experiment branch, not a release. Weight optimization cannot make an
invalid line valid. Report non-identifiability rather than inventing an optimum.

We cannot enumerate every conceivable architecture or real-valued weight. This
study catalogs the principal alternatives and exhaustively screens a declared
finite grid before testing a selected combination in complete generations.

## Alternatives and hypotheses

| Layer | Alternatives | Testable distinction |
|---|---|---|
| Mana | existing score; evidence prior; risk penalties; strict exclusion; conditional availability simulation | Do drawbacks stop outranking stable sources? Can artifact-dependent lands remain eligible in supported shells? |
| Recall | global rank; per-role channels; price-band channels; constrained joint budget optimization | Do functional affordable alternatives survive expensive competitors? Does extra recall translate into a better final deck? |
| Choice | structural score; empirical prior; package coverage; global constraint solver; learned ranking | Does a higher inclusion weight add useful cards or merely replicate popularity? |
| Rules | free-form model review; factual claim validation; typed target sets; full rules execution | Can explicit false claims be rejected while valid payment-vs-MV descriptions survive? |
| Packages | positive ingredients; target feasibility; absence/uniqueness constraints; stateful combo execution | Does Pact's duplicate-basic conflict get detected even with all positive ingredients present? |
| Evaluation | same-source overlap; independent rules fixtures; paired builds; simulator probes; human playtesting | Which conclusions are actually supported, and which remain unknown? |

Initial implementations cover soft land penalties, cohort land priors, price-band
recall and conservative supported-rule validators. Full gameplay simulation,
learned ranking, solver optimization and hard land exclusion remain alternatives,
not claims of completed work. Hard exclusion can reject good conditional cards;
learned ranking requires independent labeled preference data; solver constraints
require an accurate mechanic representation first.

## Factors and exhaustive screening

54 configurations: evidence weight E={0.25,0.45,0.65}; land evidence weight
L={0,10,20}; land risk multiplier R={0,1,2}; affordable recall K={0,12}.
Score=(0.9-E)*structural + E*sqrt(inclusion) +0.1*positive synergy.
Land score=existing score + L*inclusion + R*documented risk adjustment.
Recall K keeps up to K per functional channel in each <=$0.25,$1,$3 band.
Baseline=(0.45,0,0,0). No output is labeled win probability.

Training/screening commanders: Krenko, Vivi, Ur-Dragon (previously exposed failures).
Freeze public candidate pools, source hashes, prices, prior evidence and old spells.
Screen recall settings and mana settings independently, then combine their measured
results across the complete grid. This separable stage screen is **not** 54 complete
builds and cannot identify cross-stage interactions. Complete paired generations
provide that test. Keep baseline and all failures in reports.

Choose a conservative nondominated combination on development data only. If E
cannot be identified by independent quality labels, keep baseline E=0.45. Do not
choose E solely by EDHREC overlap. Freeze the selected setting before holdout use.

## Validation ladder

1. Rules fixtures: exact MV versus payment, transmute target MV, Pact repeated
   names, named-target availability, thresholded commander triggers, counter
   replacement add-one vs multiply. Unknown is distinct from failure.
2. Metamorphic tests: input order/name changes, duplicate unrelated candidates,
   increasing budgets, zero weights equal baseline, nested experiment restoration,
   nonfinite settings rejected, source inputs unchanged.
3. Public frozen-stage replay: adverse land counts, affordable function retention,
   selected source coverage, price and pool size. Coverage is diagnostic, not quality.
4. Paired full generation: baseline vs selected setting, same public DB/profile
   basis and requested constraints. Alternate arm order; record cached/cold profile
   status. Model stochasticity remains, so inspect decks and repeat a representative
   pair before making a stability claim. No independence claim for cached profiles.
5. Blind-to-tuning holdouts from EDHREC current top50: Giada(#14,$150,power3),
   Lathril(#13,$100,power3), Yuriko(#19,$1000,power4), Arcades(#41,$200,power3).
   These cover single-color restricted mana, typal budget, alternate commander cost,
   and defender combat. Also rerun development Krenko and Azula as failure controls.
   These are selected examples within top50, not an evaluation of all50.
6. Check results, register additional experiments when an adverse result appears;
   never silently retune on a holdout and still call it untouched validation.

## Acceptance and reporting

Primary: 99 cards plus commander, stored legality/color/singleton/budget; no false
supported deterministic claim; no broken declared package passed as valid. Report
hard errors separately from conditional risks and unsupported mechanics. Compare
flagged cards, weak function coverage, target feasibility and human card review.
Price spent, model rating, bracket heuristics, empirical overlap and ingredient
access do not establish competitive quality. Unknown cases block broad intelligence
claims. Show paired deltas without p-values or spurious confidence from tiny n.
Native ingredient sampling remains descriptive and is not a model-selection target.

Sources: [NIST factorial design](https://www.itl.nist.gov/div898/handbook/pri/section3/pri333.htm)
for declared factor combinations; [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)
for separating tuning and validation; [EDHREC ranking](https://edhrec.com/commanders)
observed September12/13,2026 for cohort selection. The finite grid and thresholds
above are our experimental choices, not recommendations asserted by these sources.

## Registered development follow-up: score-unit sensitivity

The initial land module's severity penalties were high=.30,medium=.15,low=.05,
maximum=.60. Their scale was unlike the existing land source-deficit scores.
The first screen changed some close choices but often produced identical land
lists across R settings. Before looking at holdouts, repeat the same 54-setting
screen with severity penalties 12,6,2 and cap24 (40x scale). This is a documented
sensitivity experiment, not fitted risk probabilities. Compare retained lands and
adverse examples; do not attribute the entire effect to a single penalty factor.
Both initial and repeated results are retained. Set v2-score-units in the receipt.

## Registered development follow-up: budget allocation

After paired Krenko still retained known weak filler, test land share={.08,.20}
(actual cap uses the existing1.25 multiplier) and per-slot reserve dollars=
{.10,.25,.50,1.00}: eight complete selection replays with the frozen chosen scoring
configuration. Use the same cached profile, public corpus and card prices. Disable
model review explicitly and forbid ModelClient calls, keeping all results labeled
offline/unreviewed. Observe count/budget, Goblin count, and a pre-existing manual
weak-card watchlist; do not use the watchlist as a selection blacklist. These are
development experiments, not a retune on holdouts and not fresh paid generations.

## Registered adaptive follow-up: explicit Lathril plan

Both Lathril arms produced a `general` plan with no specialized requirements. The
current compiler demands certain spell/count text and misses the commander's typed
activation requirement. After observing this held-out result, Lathril becomes an
exposed development case. Compare two no-model full selection replays, identical
chosen weights: current general plan versus an explicit16-Elf requirement. This
intervention tests plan completeness rather than tuning more weights. It is not a
general automatic rules compiler and does not establish ten untapped Elves on board.
Any later confirmation needs new, untouched commanders and real generation review.

## Development boundary ablations

Add evidence-weight endpoints E=0 and E=.9 to test removing the inclusion prior
and removing its structural component, respectively. Re-run the stage screen at
E={0,.25,.45,.65,.9}:90 combinations per development commander. This is an expanded
screen, not additional paid builds and not grounds to change the frozen holdout
candidate. Retain prior54-grid receipts rather than overwriting the study history.

# Land drawback policy: alternatives and experiment design

Status: integrated behind zero-default experiment controls on the isolated study
branch. The initial proposal below informed the experiment; actual runs and
limitations are recorded in ../../experiments/selection-validation/results.md.
The current policy uses severity penalties12/6/2, capped at24, after a documented
40x score-unit sensitivity experiment. Density mitigation is exposed by the API
but is not supplied deck context by the pipeline integration.

## Problem

Some lands carry printed drawbacks that a colors-and-count mana base model does
not see: an opponent can be handed the land, an upkeep cost must be paid every
turn, the land is sacrificed unless a board requirement is met, or the "mana"
turns out to need mana, a search, a trigger or a restriction first.

The failure the policy is meant to prevent is treating these as equivalent to
clean sources. The failure it must not create is the mirror image: treating a
drawback as illegality. Glimmervoid in a deck that is half artifacts is a good
land. City of Brass and Mana Confluence pay life for perfect fixing and are
correct in most three-plus color decks. Scalding Tarn produces no mana at all
and is still premium. A policy that cannot express "bad clause, good card" is
worse than no policy.

## Alternatives considered

### A. Hard exclusion (rejected)

Detect a drawback, refuse the land.

* Pro: trivial to implement, trivially explainable, no weights to tune.
* Con: wrong on its face for the cases above. It converts a heuristic reading
  of Oracle text into a legality verdict, which is exactly the mistake the
  selection-intelligence acceptance criteria call out ("unknown does not mean
  supported or impossible"). A regex miss then has unbounded cost: one
  unmatched shape silently deletes a card from every deck, and there is no
  score at which a human or an evaluation can see the tradeoff.
* Con: hard exclusion needs an explicit retained control and independent labels
  to distinguish good exclusions from false exclusions.

### B. Conditional penalties (implemented)

Detect printed shapes, attach a severity, subtract a bounded constant from the
land's score, and let deck density discount the drawbacks that are actually
about deck composition.

* Pro: keeps ranking in the caller's hands. A penalised land can still win on
  evidence or on fixing, which is the observed truth for pain lands.
* Pro: bounded blast radius. Total penalty is capped (`MAX_TOTAL_PENALTY`), so
  a cascade of overlapping detections cannot delete a card.
* Pro: sweepable. `risk_weight = 0` is the exact current behaviour, so every
  grid has a true control arm and the effect size is defined.
* Con: the severity constants are invented. They are ordinal intuitions
  (lose the permanent > conditional on board state > pay some life), not fitted
  values, and they are stated as hypotheses in code and here.
* Con: a per-card penalty cannot see the mana base as a system. Two mutually
  redundant risky lands are penalised independently.

### C. Sample-based availability (recommended follow-up, not implemented)

Simulate opening hands and early turns, and score a land by how often it is
actually an untapped source of the colors the deck needs on the turn it is
needed, drawbacks included: the sacrifice clause checked against the sampled
board, the upkeep cost against sampled resources.

* Pro: measures the thing that matters instead of proxying it, and handles
  redundancy and color requirements jointly.
* Pro: mitigation stops being a hand-set density curve and becomes an observed
  frequency.
* Con: needs a board-state model that does not exist here, and the simulation's
  own assumptions (what the opponents do, whether the artifact survives) become
  the new unmeasured constants. It is more expensive per candidate, and it is a
  bigger change than the current repair is scoped for.
* Recommendation: adopt B now as an inspectable, reversible experiment, and use
  it to decide whether C's cost is justified for lands specifically.

## What the implementation asserts, and what it refuses to assert

* Findings come only from `oracle_text` and `type_line`. The card name is never
  read, so there is no name blacklist to maintain or to be wrong about, and a
  reprint is scored identically to its original. A test pins this.
* An empty finding list means "no supported shape matched", not "this land is
  safe". A land with no Oracle text available is reported as
  `land_oracle_text_unavailable`, not as clean.
* A sacrifice in an activation cost is a price the controller chooses to pay
  (fetch lands, Crystal Vein) and is not a drawback. Only sacrifices imposed by
  a trigger are.
* Density mitigation is a prior about how often a board requirement is met. It
  is capped at `MAX_MITIGATION = 0.75` and never reaches zero, because a deck
  full of artifacts still draws artifact-free hands and still gets its board
  answered. `risk_adjustment` without a deck applies no mitigation at all.
* `adjust_land_score` is additive and separable, and at zero weights returns the
  baseline score bit for bit.

## Severity assignment (hypothesis)

| Severity | Penalty | Reading | Example codes |
| --- | --- | --- | --- |
| high | 12 | can cost the land or the game unilaterally | `opponent_gains_control`, `upkeep_sacrifice_unless_cost_paid`, `upkeep_exile`, `triggered_self_sacrifice`, `sacrifice_unless_condition` |
| medium | 6 | conditional on state the deck may or may not have | `sacrifice_unless_artifact`, `sacrifice_unless_creature`, `does_not_untap`, `conditional_mana_activation`, `mana_usage_restricted`, `color_depends_on_other_permanents`, `no_unconditional_mana_ability` |
| low | 2 | a real but routinely acceptable price | `mana_requires_mana_payment`, `mana_costs_life`, `mana_source_damages_you`, `mana_requires_library_search` |

`sacrifice_unless_condition` is deliberately *higher* than the artifact and
creature variants: an unmodelled requirement is one this module cannot tie to
deck composition, so it is not discounted rather than being assumed cheap.

## Validation examples

| Card | Expected findings | Intended reading |
| --- | --- | --- |
| Rainbow Vale | `opponent_gains_control` (high) | the mana is real, the land is not yours to keep |
| Forsaken City | `does_not_untap` (medium) + `upkeep_hand_exile` (high) | two independent drawbacks, reported separately |
| Glimmervoid | `sacrifice_unless_artifact` (medium) | mitigable by artifact density, never to zero |
| Thran Quarry | `sacrifice_unless_creature` (medium) | mitigable by creature density only |
| City of Brass | `mana_source_damages_you` (low) | perfect fixing, priced in life |
| Command Tower | none | commander color identity is not a conditional color |
| Scalding Tarn | `mana_requires_library_search` (low) | a source with a prerequisite, not a drawback land |
| Filter land (e.g. Mystic Gate) | `mana_requires_mana_payment` (low) | fixing, not net mana |

## Known failure cases

1. **Shape coverage.** Detection is a supported-shape parser. Unusual
   templating (drawbacks split across sentences that the line heuristics do not
   join, or wording that predates current Oracle style) is missed. Under
   conditional penalties a miss costs a small ranking error; under hard
   exclusion it would cost the card.
2. **False positives on harmless clauses.** `opponent_gains_control` fires on
   any "an opponent gains control" wording near the start of a clause, which
   would also catch a land that *temporarily* donates something. Inspect the
   findings on a real pool before raising `risk_weight` above ~1.
3. **Double counting.** A land can match a drawback and also fail the
   unconditional-source check for the same underlying reason. The obvious
   overlaps are suppressed (`no_unconditional_mana_ability` is not reported when
   a trigger, sacrifice or activation restriction already explains it), but the
   suppression list is not exhaustive.
4. **Density is not board presence.** Mitigation uses deck composition, which
   ignores curve, removal, and whether the artifact is on the battlefield at the
   relevant end step. It will be too generous to slow artifact decks.
5. **Per-card, not per-mana-base.** Two risky lands that are redundant with each
   other are penalised as if independent, and a drawback land that is the deck's
   only source of a color is penalised as if replaceable. This is the structural
   limitation that alternative C exists to fix.
6. **Back faces and split cards.** Only the front face is read. MDFC lands whose
   drawback lives on the other face are unmodelled.
7. **Constants are not measurements.** Every number here is a hypothesis. If a
   grid shows the result is insensitive to `risk_weight`, the honest conclusion
   is that this signal does not matter for the objective as scored, not that the
   penalties should be raised until it does.

## Recommended experiment grids

All arms use decks built by the existing pipeline; the only change is the land
score passed through `adjust_land_score`. `risk_weight = 0, evidence_weight = 0`
is the control and must reproduce current output exactly, which is the first
thing to verify before reading any other arm.

**Grid 1 — does printed risk matter at all?**

* `risk_weight ∈ {0, 0.25, 0.5, 1.0, 2.0}`, `evidence_weight = 0`.
* Commanders: the EDHREC current top ten with varied power and budget, plus the
  Vivi regression case named in the selection-intelligence README.
* Report per arm: which lands changed, the count of high-severity lands kept,
  color-source counts per color, untapped-source counts, and the arms where a
  land was dropped that the control kept. Inspect the diffs, not just totals.
* Failure signal: color sources fall below the mana base's own targets, or the
  policy starts removing pain and filter lands from three-plus color decks.

**Grid 2 — is density mitigation doing real work?**

* Arms: no mitigation (`risk_adjustment(card)`) vs deck-aware
  (`risk_adjustment(card, deck)`), at the `risk_weight` chosen from grid 1.
* Sweep `MITIGATION_TARGET_DENSITY ∈ {0.15, 0.25, 0.35}` and
  `MAX_MITIGATION ∈ {0.5, 0.75, 0.9}`.
* Decks: pairs matched on colors, one artifact-dense and one not, for the
  artifact-conditional lands; the same for creature-dense decks.
* Success signal: the conditional land is kept in the dense deck and dropped in
  the sparse one, with no other movement. If mitigation changes nothing in
  either deck, drop the mechanism rather than retuning it.

**Grid 3 — evidence and risk together.**

* `evidence_weight ∈ {0, 0.25, 0.5}` crossed with the grid 1 `risk_weight`
  values, on commanders with usable EDHREC evidence.
* The question is whether the two terms are redundant: if popular lands are
  already the low-risk ones, `risk_weight` buys nothing above evidence and
  should not be shipped on its own account. Note that inclusion is descriptive
  popularity, never win equity, so agreement between the terms is corroboration
  and not confirmation.

**Grid 4 — detector precision, no scoring involved.**

* Run `land_risks` over the full legal land pool and review, by hand, every
  distinct code with a sample of the cards that produced it, plus the lands with
  no findings that a reviewer expects to have one.
* Record the misses and false positives as counts per code. This is the cheapest
  arm and should run first; a code whose precision is poor should be dropped or
  demoted in severity before any scoring grid is read.

## Not in scope

`mana_base.py`, the pipeline and candidate selection are untouched by this
work. `adjust_land_score` deliberately takes no deck argument so that it cannot
become a covert filter; deck-aware experiments call `risk_adjustment(card, deck)`
directly. No card is excluded by this module under any weight.

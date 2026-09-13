# Commander-aware substitutions: results and limits

## What changed

The experimental selector now constrains complete effect-family proofs using
Oracle-derived commander contributions. Tribal bodies and token producers remain
distinct; noncreature cast triggers cannot be satisfied by a draw creature; defender
is an ability, not simply the Wall subtype. Unparsed relationships remain unknown.

Supported replacement families now include fixed direct damage with fully covered
optional kicker/scry riders, additional-cost draw that preserves existing payment
options, and static creatures with complete printed body/cost/keyword facts. The
whole-deck one-to-one proof and protected identities remain mandatory. A new card
receives its actual role and does not inherit model approval from the removed card.

This is a bounded mechanical improvement, not an optimal-deck or winning-strength
claim. Existing baseline quality defects remain outside the proof's coverage.

## Public effect checks

- Shock→Lightning Bolt preserves casting cost, timing and any-target scope while
  increasing damage. Shock→Burst Lightning preserves its base mode and adds an
  optional kicked mode. Shock→Play with Fire preserves base damage and adds a
  conditional scry. Budget and protected-card constraints can reject any of them.
- Thrill of Possibility→Demand Answers retains the discard payment route and adds
  the option to sacrifice an artifact. Artifact presence is not needed to retain
  the old route. Reversing the swap loses an option and is rejected.
- A creature cannot replace Vivi's noncreature spell simply by drawing more cards.
  A larger body cannot erase an old tribal type or an explicit power threshold.
  Missing printed stats cannot be interpreted as zero or as irrelevant.
- Previous counterexamples retain protection: interaction, tutors, wheels, token
  engines and incompletely understood cards cannot be cut for generic draw.

## Eligibility defect found during baseline review

Giada's previous baseline contained **Elemental Time Flamingo**, whose printed type
is `Stickers`, despite the catalog's legal-in-99 flag. Sticker sheets are separate
game materials; a legality flag alone is insufficient for main-deck eligibility.
See Wizards' [Unfinity mechanics](https://magic.wizards.com/en/news/feature/unfinity-mechanics-2022-09-20).

The new type eligibility check runs before candidate selection, during legality
repair and at final acceptance. It excludes sticker sheets and other supplementary
objects, including planes, schemes, tokens, Attractions and Contraptions, while
preserving normal lands, Kindred spells, Sagas, Battles and supported front faces.
The eligibility correction is common to both new experiment arms; it is not
attributed to commander-aware replacement.

## Data boundary and review corrections

The existing card table has no printed power/toughness columns. The model can now
preserve supplied stats through serialization, and a complete static-body parser
is available, but existing records still lack those facts. No real creature upgrade
may pass by inventing them. Public body fixtures do not populate the live catalog.

Independent review caught a 1/1→2/2 false upgrade for a power-threshold commander.
The fix checks both commander and baseline support text and preserves exact stats
in power/toughness-sensitive contexts. All independent regressions now pass.

The baseline audit also corrected a misleading premise: Courier of Comestibles
has a Food-token fallback. A missing Food library target does not mean its entire
ability is dead. That card remains outside the complete substitution families;
it was not automatically erased for generic card draw.

## Validation approach

Offline development screened ordinary budget/power combinations with generation
model calls forbidden. Cached profiles were explicitly used when a profile would
otherwise refresh; those runs are labeled replays, not real model generations.
Local embedding metadata retries were stopped and offline flags applied without
changing selection parameters. Failed attempts and logs remain retained.

Protected-name replays found Shock→Burst Lightning in Krenko $51/p3 and $55/p3,
with final prices $50.95 and $54.95. No cards were forced into the baseline. The
higher-priced alternatives did not fit those budgets. These are development
findings; the full-build cohort must independently confirm actual persisted swaps.

The final source freeze is
`e7bfa269a248b90f38dc79b2f6edcac9888d20a16ff6c2a10734ab3a7c147b7e`.
At this exact freeze, all five historical harmful transitions still fail validation;
Giada additionally fails the new card-type eligibility check.
The two full Krenko pairs each differ only by Shock → Burst Lightning. Candidate
prices are $50.95 and $54.95, versus $50.84 and $54.84 for their baselines. Each
persisted replacement has role `removal`, passes its recorded whole-deck transition
proof, and remains `unreviewed` rather than inheriting the outgoing card's model
review. These are two generated budget cases for one commander and one replacement
pair—not evidence of broad strategic generalization.

All **12 full generations across eight commanders** completed on the corrected
freeze. Ten candidate transitions produced two improvements and eight unchanged
decks, with zero hard-check or substitution-validation failures. Four controls
(Arcades and the three power-4/5 cases) remain audit-only. All draw audits are still
unresolved. Vivi completed despite an optional Reddit lookup returning HTTP403.

| Commander/case | Budget | Power | Final price | Outcome |
|---|---:|---:|---:|---|
| Krenko, Mob Boss (krenko-51-p3) | $51 | 3 | $50.95 | Shock → Burst Lightning |
| Krenko, Mob Boss (krenko-55-p3) | $55 | 3 | $54.95 | Shock → Burst Lightning |
| Krenko, Mob Boss (krenko-50-p1) | $50 | 1 | $50.00 | Unchanged |
| Vivi Ornitier (vivi) | $200 | 3 | $194.69 | Unchanged |
| Lathril, Blade of the Elves (lathril) | $100 | 3 | $95.87 | Unchanged |
| Giada, Font of Hope (giada) | $150 | 3 | $149.23 | Unchanged |
| Arcades, the Strategist (arcades) | $200 | 3 | $177.92 | Audit-only, unchanged |
| Yuriko, the Tiger's Shadow (yuriko) | $1,000 | 4 | $700.55 | Audit-only, unchanged |
| Fire Lord Azula (azula) | $2,500 | 5 | $2,156.07 | Audit-only, unchanged |
| The Ur-Dragon (urdragon) | $1,500 | 4 | $910.44 | Audit-only, unchanged |

The two additional baseline builds finish at $50.84 and $54.84. No unsupported
removals occurred in the ten candidate transitions. Giada is sticker-free.
The [machine-readable result](validation.json) retains role, review, draw and
body-data coverage; [cases](cases.json) records the development-exposed cohort.

Private receipts are under `decklab-infra/.private/generator-function-study/`:
`commander-upgrade-corrected-runs` (all final outputs),
`commander-upgrade-corrected-historical` (five rejected historical changes), and
`commander-upgrade-runs` (rejected initial freeze). Test log:
`/private/tmp/commander-substitution-corrected-tests.log`.
The authoritative comparison uses each candidate's internally completed baseline
versus its persisted final cards, not only separate stochastic model runs. Cached
profiles/model responses may be reused; repeated executions are not independent
stochastic samples.

## Full-generation correction

The initial freeze (`6a9f6f921744b47654fc7039270d2d290a81839552df836e61d9ab8d1ea9ced8`)
was rejected after four completed builds. Both Krenko upgrades passed effect and
budget checks but persisted Burst Lightning as `utility`, revealing a pre-existing
damage-role classification gap also affecting Shock. The runner correctly failed
both cases. Two further builds were interrupted; their logs and all failed receipts
remain available in `commander-upgrade-runs`.

The correction gives complete creature-targetable damage evidence priority over
incomplete cached roles. Ten new tests cover absent/empty/utility cached facts and
exclude player-only damage from the override. Independent review passed. This fixes
guarded replacement roles; the separate initial assignment path can still label
baseline Shock as utility, so global classifier consistency remains unfinished. All twelve
builds are repeated on the corrected freeze in `commander-upgrade-corrected-runs`.

## Verification and remaining work

Full Python suite: **1,807 passed, 21 skipped, 54 warnings**. New coverage includes
57 commander-contract tests, 33 creature-resource tests, 27 independent review tests
and 34 coordinator effect-family tests. Targeted Ruff checks pass (the existing model retains its legacy typing annotation style); the creature
helper passes isolated mypy. See [independent review](independent-review.md) and
[Claude receipt](claude-receipt.md) for actual external agent sessions and corrections.

Existing high-power/defender audit-only restrictions remain. No new C++ gameplay
simulation was implemented. Broader creature and engine replacements need actual
printed data, richer support relationships and independent scenario validation.
Unresolved draw packages are not declared solved by a damage-spell improvement.
The next substantive expansion needs validated printed power/toughness ingestion,
commander/deck support requirements for repeatable draw engines, and scenario tests
that distinguish setup cost, activation gates and reliable cards gained. Global
role-classifier consistency also remains separate work. No claim here guarantees
that every baseline card choice is good. In the real Krenko lists, Dragon's Herald
still has an unusable sacrifice/search line; the proof refuses to discard its other
printed resources without complete evidence. Azula still reports a conditional
Tainted Pact/library-emptying risk from repeated basic lands. These are unresolved
selection-quality findings, despite zero hard legality/transaction failures. The
model reviews only a subset of cards (many remain explicitly unreviewed), so the
cohort is not full independent expert approval of every inclusion.

No deployment or push was part of this task. The experimental feature remains off
by default. Production and Deck Lab Main/QA URLs are unchanged.

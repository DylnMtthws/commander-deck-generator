# Function-preserving draw transactions: validation report

## Outcome and release decision

The generator now has an experimental boundary that prevents draw optimization
from silently dismantling existing functions. Guarded mode starts from a completed
baseline and requires a one-to-one substitution proof for every removal. It no
longer spends draw budget early and assumes the resulting deck is an upgrade.

This is a safety and validation improvement. It is not an improvement in general
commander ranking, and it does not certify the baseline deck. Unsupported functions
remain protected; unresolved draw requirements remain unresolved. Production is
unchanged, and the experimental draw feature remains off by default.

## Historical counterexamples

The validator rejected all five previously unsafe full-build transitions. Each
fails for supported function loss, unknown removed functionality and missing
one-to-one proof, without requiring a hand-maintained list of protected card names.

| Prior transition | Lost supported function/scope entries | Removed cards with incomplete coverage |
|---|---:|---:|
| Vivi | 9 | 14 |
| Lathril | 9 | 18 |
| Giada | 6 | 9 |
| Yuriko | 10 | 11 |
| Arcades | 5 | 9 |

Examples include Vivi's creature removal, wheel and own-spell token engine;
Lathril's Elf-dependent tokens, Elf-to-library-top tutor and mana ability;
Giada's any-permanent removal and white spell cost reduction; and Arcades' tutors.
Yuriko's top-deck tools and delve effects remain protected even when exact behavior
is incomplete. Counts describe recognized semantic changes, not weights or lost
win percentage. A removal spell's opponent-token rider is a changed function, not
a benefit we are trying to preserve independently.

## Positive and negative proof examples

The public Oracle fixtures permit **Weave Fate → Quick Study**: both are instants
that draw two cards, and Quick Study requires one less generic mana with the same
blue requirement. Test prices are synthetic budget inputs, not live prices.

**Inspiration → Quick Study is rejected.** Inspiration can target another player;
self-draw does not preserve that option. The real Oracle text corrected the initial
expectation for this fixture. No parser exception was added to force it to pass.

Additional tests reject slower timing, additional colored pips, changed spell
color identity, hidden clauses, variable/alternative costs, protected engine cards,
multifunction replacements and package-wide losses. Commander cost-sensitive text
blocks changes to mana demands in this limited proof family. More draw cannot
compensate numerically for lost interaction or an unmodeled function.

## Full-build validation and discovered failure

The first frozen batch completed eight real builds with zero existing mechanical
hard failures. All four guarded outputs failed the new strict persisted-transition
check. Investigation found a representation mismatch: synthetic basic lands had
missing Oracle IDs internally and empty-string IDs after model serialization.
A diagnostic that matched cards by name initially confused different basic-land
copies; a proper multiset comparison corrected that diagnosis. No actual hydration
or changed land functions occurred.

The fix normalizes only missing versus empty Oracle IDs. It preserves real IDs,
Oracle text, color identity, mana value and spell type. Regression tests prove that
changed land text and substitution of an actual new identity still fail. The old
outputs then pass unchanged, while all five historical bad transitions still fail.
Raw failures and the diagnostic correction are preserved, not counted as initial
successes.

A corrected frozen source is used for the final cohort. Paired real runs cover
Krenko, Lathril, Vivi and Giada; candidate-only audit controls cover Yuriko, Arcades,
The Ur-Dragon and Azula. These are eight previously observed EDHREC top50 commanders,
covering mono-, two-, three- and five-color identities, budgets $50–$2,500 and
powers 1, 3, 4 and 5. Rankings are from the previous recorded cohort, not a new
claim about today's rankings.

The decisive
check compares each candidate's persisted final cards with its own internally
recorded baseline. Separate model runs can vary; an external paired difference
alone cannot establish the causal effect of this guard. Cached profiles or model
responses may be reused; these are full executions with inference enabled, not
independent stochastic samples.

The four guarded development candidates (Krenko, Lathril, Vivi and Giada) all
retain the internally recorded baseline: **zero applied swaps**. The previous
experiment's increased draw counts are not retained as accepted upgrades. Those
counts came with lost functions that this gate now refuses to sacrifice. Existing
baseline quality warnings remain; this milestone does not remove weak cards already
chosen by the baseline generator.

## Final corrected cohort

Twelve full generations completed on the corrected frozen source, with zero
mechanical hard failures and zero final-transition validation errors. All eight
guarded/audit outputs passed their internal baseline-to-persisted-final checks.
**Every output was unchanged, with zero applied swaps and an unresolved draw
package.** These results establish preservation, not stronger draw or deck quality.

| Commander | Power | Budget | Final price | Mode | Applied swaps |
|---|---:|---:|---:|---|---:|
| Krenko, Mob Boss | 1 | $50 | $50.00 | function_guard | 0 |
| Lathril, Blade of the Elves | 3 | $100 | $99.08 | function_guard | 0 |
| Vivi Ornitier | 3 | $200 | $199.91 | function_guard | 0 |
| Giada, Font of Hope | 3 | $150 | $149.59 | function_guard | 0 |
| Arcades, the Strategist | 3 | $200 | $177.92 | audit_only | 0 |
| Yuriko, the Tiger's Shadow | 4 | $1,000 | $700.55 | audit_only | 0 |
| Fire Lord Azula | 5 | $2,500 | $2,156.07 | audit_only | 0 |
| The Ur-Dragon | 4 | $1,500 | $910.24 | audit_only | 0 |

Including the initial eight-build batch, this task executed **20 full builds**.
The first four guarded receipts failed representation validation and remain
recorded as failures; later normalization does not retroactively make them
initial successes. All seven registered engineering criteria are satisfied
within the stated narrow proof family. General strategic acceptance remains open.

## Definitions of done and limits

The [registered spec](spec.md) requires exact evidence, explicit incomplete
coverage, whole-deck receipts, positive proof cases, preservation checks around
all selection changes, historical counterexamples and varied full generations.
A no-op satisfies preservation but is never labeled an improvement. A draw floor's
`met` label would certify only that narrow floor, not all-card quality.

The narrow first proof family deliberately protects permanents, tutors, wheels,
filtering and unknown effects from generic-draw replacement. Consequently it can
reject plausible upgrades that need richer semantics. It also preserves weak cards
already in the baseline. Arbitrary commander interactions, matchup decisions,
board-state timing and a global budget/package solver remain unimplemented.

No new C++ draw or activation execution was added. Existing native mana probing
runs before the guarded transaction; accepted replacements preserve mana sources.
The native ingredient probe cannot price the value of interaction or tutors.

## Verification and provenance

- Full suite after the representation fix: **1,656 passed, 21 skipped, 54 warnings**.
- All changed source/tests pass Ruff; receipt helper passes isolated mypy.
- Actual Claude Code Opus Medium and Cursor sessions completed; their contributions
  and independent corrections are documented in [agent review](delegation-review.md).
- Initial frozen source SHA-256:
  `a7cfd606a65e551d864627ec2ce2560770086bd7589bd2c0648da370a1b472bf`.
- Corrected frozen source SHA-256:
  `d05d2aaab2036a17f4a8fe4d4d5646cc7672cd759d73a1c572cdc43d9bb6df92`.
- Private artifacts: `decklab-infra/.private/generator-function-study/` contains
  complete runs, source receipts, historical replays and failed diagnostics.
  Public source, fixtures and the reusable `scripts/run_function_study.py` are in
  this repository. Credentials, databases and private run payloads are not committed.

The next wider implementation should model commander-specific support and timing
well enough to prove useful package exchanges. It must earn broader automatic
selection through new proof families and independently held-out evaluations; a
larger draw score alone remains insufficient.

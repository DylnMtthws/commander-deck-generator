# Package 3 — intent preservation, final validation and trace

Own pipeline/deck_builder.py (except config paths owned by package1), new intent/
quality modules and tests. You may change optimizer behavior where needed with
focused regression tests; do not alter routes/profile/synthesis implementation.

Turn explicit user intent into a grounded, inspectable engine requirement derived
from actual oracle traits, not a commander-name or two-card hardcode. First supported
case: mana-value-limited creature copy/clone intent (four-mana copy creatures),
with at least two eligible affordable copy creatures when feasible. Recognize
actual copy-on-entry text; keyword-counter collectors are not clones. Legendary
copy restrictions must not incorrectly ban ordinary clones solely for being
legendary copies; do not assert that finite top-five hits are deterministic infinite
loops. General/no-intent behavior stays supported; unsupported intent is visibly
unverified, not silently reported fulfilled.

Retrieve eligible engine candidates from legal/budget-valid full pool BEFORE
pruning, reserve a feasible package through infrastructure, swaps, budget changes,
review and legality repair. Engine preservation may not override hard legality or
budget. Infeasible intent must produce a clear failure/warning and never claim it
was satisfied. Trace engine candidates at admission, pruning, swaps and final
verification, including why unavailable; no silent omissions.

Apply meaningful final acceptance: 99 cards plus commander, singleton exceptions,
color/format legality, total budget, engine presence and required roles. Distinguish
validation failures from explicitly labeled quality warnings. Report requested vs
estimated bracket without claiming the classifier is ground truth. Surface absent
signals and unmet targets in rationale quality_warnings. Review failure cannot be
hidden or subtract money through negative-cost sentinels. Final replacements need
validation; no endless re-review loops. Tests must exercise actual build integration,
not only a standalone policy helper that builder ignores.

Implement shared progress_callback(stage,progress) in builder and stage timing/
counts persisted in rationale. Feed actual final oracle/type/MV facts to synthesis.
Use synthetic fixtures/mock models for full Aang regression, plus unrelated
commander, unaffordable engine and hostile reviewer replacements. No live model.

## Independent live-review additions

The public-corpus evaluation selected Mockingbird and Deceptive Frostkite as the
minimum package. Their mana-spent and power restrictions do not establish the
requested Aang entry engine. Protected admission must inspect the copy target
clause, conservatively exclude unverified conditions, and favor legend-rule-safe
copies. This policy is based on oracle clauses, not a blacklist of card names.
Conditional copies may remain ordinary candidates but cannot satisfy the promised
minimum package. Preserve restricted public-card regression fixtures.

Missing empirical corpus must be described to the reviewer as unavailable, never
as observed 0% inclusion. Partial review verdicts must surface a failed-review
warning. Consumed successful-response costs remain counted even when a later
review step fails. Final quality checks use the optimizer's overlapping role
tags; slot labels alone must not masquerade as role coverage.

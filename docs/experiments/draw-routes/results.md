# Draw routes, prerequisites, and commander acceleration

This experiment separates the cost of accessing draw from a card's printed mana value. It adds an opt-in `routes` policy; the default and deployed policy remain unchanged.

## Implementation

- The Oracle compiler records spell/ETB cost, permanent setup cost, Channel payment, activation costs, and conditional triggers separately. Unknown text, variable yields, and alternative card access stay explicit.
- Action News Crew's Channel costs six mana. Insight Engine records its two-mana activation, tap and counter mechanics without inventing a future counter count. Remora, Rhystic Study, and The Unagi of Kyoshi Island retain opponent dependencies. Moldervine Reclamation retains its creature-death condition.
- Giada can conditionally contribute one matching mana toward an Angel casting route. Sanctuary Warden remains mana value six; its conditional remaining casting payment is five. The receipt requires Giada to be present, untapped, and able to tap. Vivi's contribution remains state-dependent, with no invented fixed discount.
- Known blocked draw routes cannot reserve draw slots or receive draw-role credit before optimization. The role classifier honors the veto, including LLM-provided draw labels. Final-deck diagnostics reassess actual card support. Other card roles remain eligible.
- Island checks distinguish static Island lands, wholly non-Island multiface cards, and uncertain faces/type-changing effects. Candidate-pool membership is never proof of support.

The tempo thresholds (five mana at powers 1–3, four at power 4, three at power 5) are experimental selection policy, not Magic legality or proof a card is bad. The policy preserves legacy ranking rather than using the previous failed beam selector.

## Validation

Final full suite: **2,304 passed, 21 skipped, 54 warnings, 14 subtests passed**. Tests cover costs, unknowns, prerequisites, commander restrictions, prevention/replacement clauses, classifier bypass, and role-credit integration.

Eight paired offline builds are registered for Vivi ($200/power 3), Krenko ($51/power 3), Giada ($150/power 2), and Lathril ($100/power 3). Both optimizer stages use the existing function-preservation policy. Current/routes pairs share data, evidence, and exact cached commander profiles; generation-model calls are forbidden. The primary eight completed with active, locally cached embeddings; all passed hard constraints and final validation. An earlier eight-build fallback run is retained separately as a degraded-feature comparison, not primary evidence.

## Delegation and review

Actual Claude Fable 5.1 Medium sessions supplied the public-spec route compiler and tests. Its first attempt stalled; two bounded followups succeeded. Actual Cursor sessions supplied commander support and route assessment. Claude Opus Medium reviewed public validation scenarios. Local integration review corrected raw-agent errors, including cost double-counting, incorrect Oracle fixtures, Island evidence, and optimizer role reclassification. External Claude tasks used public specifications and Oracle fixtures; private deck outcomes were assessed locally.

## Limits

This is bounded static analysis, not a board-state simulator, expected-card-advantage model, or complete Oracle interpreter. Unknown routes can still enter through legacy fallback, explicitly unverified. Conditional availability is not reliable independent draw. Reassessment clears obsolete vetoes, but previously removed quota metadata is conservatively not restored. These limits prevent a claim that all poor selections have been eliminated. No deployment is part of this milestone.

## Measured outcomes

| Commander | Budget / power | Final membership changes | Result |
| --- | --- | --- | --- |
| Vivi Ornitier | $200 / 3 | 0 | No measured selection improvement; legacy draw audit remains incomplete. |
| Krenko, Mob Boss | $51 / 3 | 0 | Goblin Bombardment retained; no measured selection improvement. |
| Giada, Font of Hope | $150 / 2 | 0 | Sanctuary Warden retained; conditional ETB payment correctly records six minus Giada's one. |
| Lathril, Blade of the Elves | $100 / 3 | 0 | Two false DRAW assignments removed; Moldervine Reclamation and existing credible/independent counts of 2/2 retained. |

Shoreline Salvager and Nafs Asp remain in Lathril as utility cards. Both entered greedy completion with score zero, then survived rejected optimization transitions. This proves improved role accounting, **not improved final card membership**. Action News Crew is assessed as over the experimental access-cost limit; it was not selected by either primary arm, so its assessment is a regression safeguard rather than a demonstrated removal.

Primary paired runtimes were approximately Vivi 55.6/55.6 seconds, Krenko 16.6/16.7, Giada 26.2/26.2, and Lathril 28.8/28.7. No speed improvement is established. Unverified DRAW slots remain: Vivi 9, Krenko 3, Giada 10, Lathril 8. All legacy draw audits remain unresolved; zero hard failures must not be interpreted as complete strategic certification.

Decision: retain the opt-in experiment and diagnostics; **do not promote the selector as a solved card-selection system**. The next implementation priority is the [budget-completion fallback](next-priority.md), which currently admits cards without scoring them when the fixed per-slot reserve exhausts spendable budget.

## Reproducibility

- Final source/scripts/config SHA-256: `ab1fa88904aae918ed4423ce0acd2b35557355ac37066ec874e52f9e2eb52f19`.
- Original database SHA-256: `3592bf8f2c5ef7a51b602b118e32b08d7da2375f29e6b620bba2a3d7462fee52`; additive migrations occur only on isolated copies.
- MiniLM revision: `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; weight SHA-256: `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`.
- Exact original cached profiles are replayed with separate provenance receipts, without relabeling them freshly generated. Evidence is frozen for these pairs; historical runs are not asserted byte-equivalent.
- Local private execution receipts and comparisons: `decklab-infra/.private/generator-selection-repair-study/draw-routes-real-embeddings/`. See [replay runbook](replay-runbook.md) for the preflight requirements.
- Ruff passes new modules/tests and changed pipeline modules except the pre-existing `PLC0206` loop in `slot_assigner.py`; `git diff --check` passes.

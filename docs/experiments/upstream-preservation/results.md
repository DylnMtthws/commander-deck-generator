# Upstream preservation results

This experiment prevents specific optimizer regressions; it does not certify overall Commander deck quality. Defaults remain `current` and this work is not deployed.

## Implemented behavior

Swap refinement and budget rebalancing now have independent `current`, `off`, and `preserve` controls. Preserve runs the actual optimizer on isolated deck/candidate data, then validates its complete proposal before committing. Unsupported cuts, missing context, invalid prices/budget and protected-card loss reject the whole stage, retain the original deck and receive zero accepted-trade credit. Exceptions leave preserve-mode inputs unchanged. This transaction covers in-memory optimizer work, not arbitrary external side effects.

Full greedy, stage and final snapshots expose losses before the former postprocessor baseline. The study independently recomputes each transition, binds receipts to their request and checks the actual persisted final cards, prices and roles. It does not trust a reported validation flag.

## Validation and comparisons

The final full suite passed **2,006 tests**, with 21 skipped and 54 warnings. Actual optimizer tests permit Weave Fate → Quick Study and reject Mystic Remora → generic immediate draw in both stages. Adversarial tests exercise atomic mixed-proposal rejection, unknown effects, invalid prices/budgets, protected cards, exceptions, immutable receipts and persisted-data tampering. The synthetic test decks are not evidence of strategic deck quality.

The registered development grid compares all nine swap/rebalance combinations for Krenko ($51/power 3) and Vivi ($200/power 3), with identical initial data and cached profiles. All 18 completed builds pass hard, persisted-role and receipt checks. Current policies still fail independently recomputed function preservation; mechanical validity is not strategic acceptance.

- Krenko: current swap admits Bearer of the Heavens; current rebalance sells Goblin Bombardment. Guarding only one stage leaves another unproved transition. Guarding both retains Bombardment, avoids Bearer and permits the final repair’s proved Shock → Lightning Bolt improvement. Final price: $50.25.
- Vivi: current swap removes support including Izzet Signet, Talisman of Creativity, Springleaf Drum and Swiftfoot Boots, while admitting Scaretiller and The Underworld Cookbook. Guarding both retains the actual earlier deck and avoids those admissions. Final price: $199.66.
- Preserve/preserve matches off/off for these two final decks. Upstream proposals were rejected wholesale; the implementation’s ability to accept proved optimizer upgrades is demonstrated by integration tests, not by accepted upstream trades in these two cases.

Mystic Remora was already absent from Vivi’s greedy snapshot, despite ~43.05% inclusion in the saved corpus evidence. Goblin Chirurgeon was also absent from Krenko’s greedy snapshot. Neither absence can be called an upstream optimizer removal in this study. Earlier candidate admission, pruning and initial selection remain unresolved; these traces do not establish which earlier node caused each absence.

## What the rejected proposals teach us

Independent examination of all 420 outgoing/incoming cross-pairs within the three rejected Krenko/Vivi preserve/preserve proposals found **zero pairs supported by the current complete-effect proof grammar** (100 Krenko swap, 64 Krenko rebalance, 256 Vivi swap). This measures a proof-coverage gap, not absence of good Magic substitutions. Subset search alone cannot rescue these particular proposals under the current proof rules.

The next priority is full candidate-path evidence for omitted supported cards, followed by tested effect and commander-context contracts. Bounded safe-subset extraction is useful only when real proposals contain proved recoverable moves. The [reviewed alternatives](next-step-review.md) compare that path with move-level gating and function-preserving funding pairs. None of these local proofs establishes all gameplay interactions or winning strength.

## Agent work

Actual Cursor Grok 4.6 High supplied narrowly scoped policy/OFF controls; its code was reviewed and corrected before integration. Actual Claude Fable 5.1 Medium and Opus Medium sessions reviewed public transaction specifications and test designs. An additional Opus Medium review compared follow-on alternatives. Their designs were reviewed, including correction of an inaccurate Inspiration fixture. The 24 abstract scenarios in `reviewed-design-scenarios.json` are designs, not 24 separately executed tests.

## Study limitations and receipts

All builds are offline with model calls forbidden, frozen cached profiles and intentionally unavailable model safety review. They are development-exposed cases, not held-out evidence. No live model quality, multiplayer gameplay, simulator win rate or latency improvement is established. Both primary draw audits remain unresolved.

One preliminary build stopped on an audit representation mismatch (generated basic-land keywords missing versus the persisted model default empty list). The failed artifact is retained. Normalization was narrowed to that model default; tests still reject loss of an actual keyword and preserve the distinction between unknown and empty printed colors. The corrected grid used a new script freeze; optimizer source stayed unchanged.

Initial data SHA256: `3592bf8f2c5ef7a51b602b118e32b08d7da2375f29e6b620bba2a3d7462fee52`.
Optimizer source SHA256: `10796ac6f3afb5de0dcc38af7a431218d64d0bdd76034445c84a35b9f067063a`.
Corrected source+scripts SHA256: `7d3ff6ac04bf3a6ba582600c4cd48ca40576e2df82b3ede0ed1ee05e52a7a4a1`.

## Finalist controls and disposition

Four additional builds compared current/current against preserve/preserve for Giada ($150/power 3) and Lathril ($100/power 3), under the same frozen source/data. All four pass hard, persisted-role and receipt checks. Both guarded finals pass independently recomputed greedy-to-final preservation; both current comparators fail it. Giada finishes at $148.78 guarded versus $149.35 current; Lathril at $97.40 versus $99.85. These prices are frozen study outputs, not current market quotations.

Giada rejects the swap proposal and makes no rebalance change; Lathril rejects both proposals. This prevents unproved cuts but also declines potentially useful additions whose complete tradeoffs the proof system cannot establish. It must not be presented as evidence that every proposed card was bad or that either initial deck is strong.

**Total: 22 completed evaluation builds, plus one retained preliminary diagnostic build.** All 22 completed builds pass mechanical and audit-integrity checks. The four commanders' preserve/preserve finals pass the bounded cumulative function-preservation check. Every draw-package audit remains unresolved. No model calls were sent.

The milestone demonstrates useful protection against specific optimizer regressions and improved attribution of earlier selection failures. It is **not sufficient for deployment as a generally improved card-selection engine**. Keep production policy unchanged. Next work must trace omissions before greedy selection and expand contextual effect coverage using positive/negative real-card fixtures; recoverable-move search follows evidence that such moves exist.


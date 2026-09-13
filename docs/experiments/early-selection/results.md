# Early omissions and contextual replacement: results

## Disposition

The candidate trace, contextual replacement vetoes/search checks and configured power-policy reader are implemented and tested. The new draw-package selector is an **unsuccessful general-selection experiment** and remains disabled by default. No deployment or promotion is authorized by these results. The initial-selection objective in the spec is not fully achieved: Vivi improves in one targeted respect, but the portfolio produces concrete regressions on other commanders.

## Remora's actual path

Two isolated offline diagnostics reproduce the earlier frozen greedy deck exactly. Mystic Remora is legal at the frozen $10.22 price, ranks16 in structural scoring/retained candidates and reaches the227-card draw pool. Its adjusted draw score0.9404 ranks5, ahead of Brainstorm/Ponder/Opt. The first four selections spend$14.63 of the$20 draw budget, including$12.26 on Ophidian Eye, leaving only$5.37. The first-fit builder therefore skips Remora.

Greedy considers it for19 iterations but its generic draw-need multiplier is already0.60–0.85. It then misses the remaining-slot reserve's affordability test at$9.10 spendable. It was not lost to candidate pruning. Separate empirical-reservation fields are absent despite43.05% inclusion in the other corpus channel; their reliability cannot simply be invented or copied between channels.

The opt-in `--trace-card` path now records immutable presence/absence and matching input printings through legal admission, filtering, annotation, scoring, recall, the draw pool/package, infrastructure, greedy and final deck. No watched name forces selection. Score fields distinguish the two evidence channels.

## Safe rule improvements

Function-preservation v3 additionally checks full-deck mana-value access, named-card references and detected cast categories. Unknown casting-resource sensitivities abstain when costs change. These checks preserve static support opportunities, not actual library/battlefield availability; they do not replace the existing outgoing-effect proof.

Tests demonstrate exact-MV tutor target loss, preserved upper-bound access, unrelated type filters, transmute metadata, joint changes, named search/cast references, and support-card cast triggers. Repair search skips context-breaking candidates before ranking; a synthetic positive case rejects a cheaper draw spell but finds a same-MV draw increase. All fixtures labeled synthetic remain synthetic.

The configured game-changer reader previously looked for `name` while the YAML used `card_name`, recognizing zero of26 configured names. It now recognizes the existing configuration, including legacy formats, with the existing Sol Ring exception and power<=3 scope. The configuration list was not refreshed or represented as a verified current official list.

## Package experiment and falsification

The registered comparison holds data, cached profiles and upstream preserve/preserve fixed, changing current first-fit, linear-score budgeted beam and trigger-diversity beam. Cases: Vivi$200/p3, Krenko$51/p3, Giada$150/p2 and Lathril$100/p3. Giada uses the same commander-keyed cached profile across arms, not a newly generated power-specific profile.

The beam keeps48 states per slot count, combines quality and cheap partial states, and uses diversity weights1/0.85/0.25. Its groups are heuristic buckets, not equivalent effects or guaranteed card advantage. A helper prototype admitted six-mana Parun; a pre-build MV reservation limit5/4/3 by power tier avoided that pick, but the full study later falsified this generic ceiling's suitability for Giada. Matching printed MV is also not the actual channel/activation cost. These failed assumptions are retained as research evidence, not advertised as fixes.

All12 full builds completed with zero model calls, hard/role/audit-integrity errors or configured-exclusion violations. Each final preserves its own greedy baseline under the bounded checker. That does NOT establish preservation or strategic superiority between the three independently constructed baselines.

- Vivi coverage admits Remora; current and budgeted omit it. Final price$199.37 versus$199.93. Five final cards change, not just Eye for Remora: +Clout of the Dominus, Kessig Flamebreather, Remora, Negate, Windfall; -Balmor, Flusterstorm, Last Chance, Ophidian Eye, Opt. This includes real protection, interaction and sequencing tradeoffs. Frantic Search was already selected later in the baseline deck.
- Krenko's three decks are identical at$50.25, retaining Bombardment and avoiding Bearer.
- Giada's new arms lose Sanctuary Warden. Budgeted also selects Action News Crew as draw despite a six-mana channel requirement; printed MV2 is not that draw cost.
- Lathril's credible/independent draw counts drop2→1 in both new arms. Coverage selects Shoreline Salvager despite zero Island-typed cards and no other Island-support text in the final deck. Moldervine Reclamation is lost. These are concrete reasons to reject general promotion.

All draw-package audits remain unresolved. Detailed comparisons are in `selection-results.md`; raw saved decks and audit receipts remain in the private study directory. Helper-only searches are not counted as deck generations. Total generation experiments for this milestone:2 diagnostic builds plus12 evaluation builds, with no generation model calls. The separate Claude/Cursor review sessions used their own models.

## Validation and agent review

Full suite: **2,084 passed,21 skipped,54 warnings**. Changed-file Ruff passes. Actual Cursor Grok4.6 High supplied the trace helper and power-policy reader in isolated tasks; both were reviewed and integrated. Actual Claude Opus Medium reviewed public contextual fixtures and later public Vivi interactions. Local independent review found the named-reference gap, which was fixed and tested. Several model-generated verdicts were corrected before use. Proposed external-review cases are designs, not claimed executed tests.

The frozen evaluation source/scripts/config hash is `2dffbf4675851387febfe3c35a102439b3a177f9e97e3b6929075b172390c40c`; initial data hash is `3592bf8f2c5ef7a51b602b118e32b08d7da2375f29e6b620bba2a3d7462fee52`.

## Next required work

Before another general package proposal, represent actual draw routes: cast/ETB, channel/discard, activated mana/tap/setup, combat, death, opponent choice and replacement effects. Keep filtering distinct from net advantage. Require applicable support in the completed deck, preserve credible engines across initial-plan changes, and model commander-specific acceleration without claiming printed mana value is access cost. Use the exact failed Giada/Lathril outputs as regression fixtures, alongside Vivi's Remora admission case. Shroud/Aura sequencing and conditional draw remain explicit research requirements in the public Vivi review.

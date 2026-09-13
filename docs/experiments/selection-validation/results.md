# Selection validation: first experimental cycle

**Decision: not ready to deploy as an intelligence fix.** The study improved
observability and exposed structural selection failures; weights alone did not
produce consistently sound decks. All work is isolated on
`experiment/selection-validation`. No production, Main or QA deployment occurred.

See [registered design](spec.md), [case assignments](cases.json),
[frozen candidate](selected.json) and [independent public fixtures](public-fixtures.json).

## What actually ran

- Three frozen development pools: Krenko, Vivi and The Ur-Dragon. Screened the
  54-setting grid at two documented land-penalty scales, then expanded evidence
  endpoints to 90 combinations per commander. These are **separable recall and
  mana-stage combinations**, not hundreds of complete generations. Cross-stage
  interactions cannot be inferred from these joined records.
- Twelve real generation attempts across six commanders: six completed and six
  failed with Hugging Face HTTP 402. Krenko and Lathril yielded usable paired deck
  comparisons. Azula's baseline completed without model review after a provider
  error, making its pair degraded. Giada, Yuriko and Arcades failed in both arms.
- Four additional offline mana-stage pairs on Giada, Lathril, Yuriko and Arcades,
  using fixed spell samples and public evidence. These are not full decks.
- Eight Krenko budget-policy selection replays and two Lathril plan replays.
  Model calls were forbidden, and model review was explicitly disabled.
- Full Python suite: **1,247 passed, 21 skipped**. All 142 new focused tests also
  passed after style cleanup. No native simulator code changed in this cycle.

The selected six generation cases were within the observed
[EDHREC top 50](https://edhrec.com/commanders), with budgets $50–$2,500 and requested
power 1–5. This is not a study of all 50 commanders.

## Findings

### Recall is necessary, not sufficient

At the frozen candidate E=.45, land evidence=10, land risk=1, affordable recall=12,
retained affordable nonlands increased from 428 to 444 for Krenko, 427 to 493 for
Vivi, and 427 to 519 for The Ur-Dragon. No eligible protected candidates were lost.
The affordable channels therefore repair a measurable retrieval bottleneck.
They do not establish that the downstream selector chooses those cards well.

The expanded E={0,.25,.45,.65,.9} screen changed pool sizes substantially without
losing protected cards. More retained cards or more EDHREC overlap does not identify
better gameplay. Keep E=.45; there is no independently established optimal weight.
Risk penalties 12/6/2, capped at24, are score-unit hypotheses, not probabilities.

### Mana improves locally; conditional source accounting remains weak

Azula's candidate gained fetch/shock lands and dropped Rainbow Vale, but billing
failure makes the overall pair unsuitable for a clean end-to-end comparison.
The independent Arcades mana-stage replay also dropped Rainbow Vale. Lathril's
land choices improved. Castle Sengir and Aysen Abbey still demonstrate that
filtering and upfront mana need accurate source accounting, not just penalties.
Low-risk flags on fetches and pain lands are **not** bad-card labels.

### Budget reserve can crowd out useful cards

In eight $50 Krenko replays, all lists had 99 cards and stayed within budget.
At land share .20 and reserve $1, seven preidentified weak-watchlist cards remained.
At share .08 and reserve $.25 or $.50, two remained. Yet those lists still included
Bearer of the Heavens and Hithlain Rope, and Goblin counts varied from 28 to37.
No tested combination eliminated questionable choices. The watchlist was used
only for diagnosis, never as a selection blacklist.

### A minimum creature count is not a commander strategy

Both Lathril generations compiled to `general` with empty specialized requirements.
An explicit 16-Elf requirement changed a no-model replay from36 to37 Elves, while
non-Elf creatures increased from4 to7. It introduced cards such as Dread Drone and
Deadly Grub. The original deck already exceeded that floor: satisfying a quota
cannot express activation access, token production, untapping, protection or
opportunity cost. Lathril is now development-exposed, not an untouched holdout.

### Rules assertions need independent truth, including agent-written tests

The first claim validator matched7/10 independent labeled examples, catching only
2/5 false claims. After corrections it matched10/10. This small fixture establishes
specific regressions, not general rules competence. Supported unknowns remain
explicit; absence of a finding does not verify a deck.

The review caught an error in our earlier assessment: **Dizzy Spell can transmute
for Gitaxian Probe**, whose printed mana value is1 despite the life payment option.
It cannot find Ophidian Eye (MV3). Agent-recalled Dizzy Spell, Dragon's Herald and
Forsaken City fixtures were also corrected against frozen public Oracle records.

Krenko still selected Dragon's Herald without Hellkite Overlord or the requisite
colored sacrifice resources. Lathril retained Courier of Comestibles without a
Food card search target. The structured audit now exposes these optional-ability
failures. They are not Commander legality failures. Pact/payoff presence with
repeated basics is a warning; only an explicitly declared full-library-exile line
upgrades this to an error.

## Real generation outcomes

| Commander | Requested power / budget | Baseline / candidate price | Assessment |
|---|---|---|---|
| Krenko | 1 / $50 | $50 / $50 | Better interaction in places; weak filler and unusable Herald ability persist. |
| Azula | 5 / $2,500 | $1,971.36 / $2,156.07 | Better land candidates; degraded baseline review prevents a clean comparison. |
| Lathril | 3 / $100 | $99.66 / $98.93 | Better lands; strategy and off-plan selection remain inadequate. |
| Giada | 3 / $150 | unavailable | Both fresh builds failed HTTP402; offline mana pair completed. |
| Yuriko | 4 / $1,000 | unavailable | Both fresh builds failed HTTP402; offline mana pair completed. |
| Arcades | 3 / $200 | unavailable | Both fresh builds failed HTTP402; offline mana pair completed. |

All six completed lists passed the implemented count, stored legality, color,
singleton and budget checks. This is not a comprehensive rules or quality pass.
Only18 cards per normal completed run entered model fit review; many remained
unresolved. Azula baseline had99 unreviewed cards. Lathril baseline generated its
profile while its candidate reused one, so timing differences are not speedup
estimates. No repeat-based stability, significance or win-rate claim is supported.

## Next implementation and validation sequence

1. Compile commander text into typed requirements: event direction, affected
   objects, resource costs, legal targets, zones and activation prerequisites.
   Test counterexamples before adding ranking rewards. Commander-specific quotas
   are inadequate substitutes. Emit unsupported coverage explicitly.
2. Make package selection conditional on target/resource feasibility and declared
   line constraints. Compare global constrained selection with greedy selection
   under the same candidate pool; measure displaced useful cards and budget use.
3. Replace fixed slot reserve with joint role-aware budget allocation. Test the
   promising reserve ranges on new inexpensive commanders, keeping Krenko exposed.
4. Extend the C++ simulator with a validated early-turn mana/activation probe:
   distinguish mana filtering from production, conditional sources, summoning
   sickness, ten untapped Elves, and opportunity costs. First compare tiny known
   states to an independent reference, then identical seeded scenarios across
   candidate decks. Existing ingredient-access sampling does not prove executable
   lines or competitive wins. This probe is proposed, not implemented here.
5. After billing is resolved, preserve failed receipts and rerun Giada, Yuriko,
   Arcades and the degraded Azula control; repeat Krenko. Use new untouched top50
   commanders to confirm any later Lathril-driven changes. Freeze settings first.

HF returned HTTP402; the account balance was not inspected. Its
[provider billing documentation](https://huggingface.co/docs/inference-providers/pricing)
explains credits and paid usage. No purchases, provider changes or continued paid
retries were made after the blocker was identified.

Private raw artifacts are under `decklab-infra/.private/generator-validation-study`:
`screen-initial-scale.json`, `screen-scaled-54.json`, `screen.json`, `a/`, `b/`,
`paired-report.json`, `offline-budget/`, `offline-holdout-mana/`,
`offline-lathril-plan/`, and the claim-gold receipts. The generic paired report
includes the degraded Azula row descriptively; this written assessment explicitly
excludes it from clean paired conclusions. Tokens and databases are not committed.

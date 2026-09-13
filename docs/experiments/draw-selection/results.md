# Budget draw selection: implementation and acceptance results

## Decision

Substantial improvement in retrieving and verifying affordable draw mechanisms is
implemented and tested. **Whole-deck strategic acceptance is not achieved; do not
release this experiment.** The feature defaults off. Passing a draw floor is not a
claim of optimal card selection, gameplay reliability, or competitive strength.

The original acceptance criterion requiring manual confirmation of no strategic
regression remains open. We did not relax it to make higher draw counts a success.
Earlier candidates displaced important commander functions; even the safer final
low-power builds contain choices requiring further work.

## Final paired real builds

Both arms use the same frozen source; only `draw_selection` differs. The new
Angel/Elf strategy parsing and role-assignment corrections are common to both arms.
Counts below mean supported positive-advantage effects with deck prerequisites met
under the documented scenario. “Independent” excludes opponent/combat dependence;
it does not mean guaranteed execution. Unsupported existing draw is not counted.

| Commander | Power | Budget | Supported draw baseline → candidate | Independent baseline → candidate | Candidate price | Draw floor |
|---|---:|---:|---:|---:|---:|---|
| Lathril | 3 | $100 | 2 → 8 | 2 → 8 | $99.84 | Met |
| Vivi | 3 | $200 | 0 → 8 | 0 → 7 | $199.25 | Met |
| Giada | 3 | $150 | 0 → 4 | 0 → 4 | $148.87 | Unresolved |

All implemented hard audits passed. Lathril retains Beast Whisperer and has 34
Elves versus 36 in baseline; Giada preserves 35 Angels. Vivi now discovers Insight
Engine and The Unagi of Kyoshi Island. Lathril uses Skullclamp, Moldervine
Reclamation, Morbid Opportunist and other supported engines. Earlier development
also admitted Phyrexian Arena. All four user-requested alternatives have mechanism
and prerequisite regression coverage; Notion Thief remains opponent-dependent and
must never be treated as unconditional Rhystic Study.

Manual review still finds costs that a draw metric misses: Vivi gains slow
Brilliant Plan and loses cards including Pongify, Young Pyromancer and Windfall;
Lathril loses Elven Ambush and Elvish Harbinger; Giada loses Generous Gift and Pearl
Medallion. These are full-build differences, not exclusively final repair swaps.
Early reservation changes later selection too. We cannot certify those exchanges
as strategically favorable. Typed-card counts alone do not protect every function.

Final model review is incomplete: Lathril 7 reviewed/10 unresolved/82 unreviewed;
Vivi 15/3/81; Giada 16/2/81. Deterministic draw audit covers all 99 entries but is not
an all-role card-quality certification. Runtime differences are not a controlled
latency result and are not claimed as a speed improvement.

## Experiments retained, including rejected outcomes

38 real generations completed after billing recovery:

- 10 restored prior controls at commit 131c999.
- 8 initial development builds: Krenko, Lathril, Vivi, Azula pairs.
- 8 confirmation builds: Giada, Arcades, The Ur-Dragon and a repeated Krenko pair.
- 6 adaptive builds: Arcades, The Ur-Dragon and Yuriko pairs.
- 6 final safer builds: Lathril, Vivi and Giada pairs shown above.

Coverage spans eight commanders from the observed [EDHREC top 50](https://edhrec.com/commanders),
mono-, two-, three- and five-color decks, budgets $50–$2500 and powers 1/3/4/5.
These are not 38 independent successes. Adaptive cases are development-exposed;
there is no remaining independent held-out proof of overall strategic quality.

Initial offline repair overstated quality through unmodeled costs and triggers;
we rejected it and added exact public negative fixtures. Conservative repair alone
then usually lacked remaining budget, motivating early draw reservation. Later
Moderation false positives exposed a global casting restriction; that mechanism
now receives no supported credit. Re-audits retain the original rejected receipts.

Yuriko's larger draw count displaced delve spells and top-deck tools. Arcades lost
useful defender support. These are rejected upgrades. Automatic draw mutations are
now restricted to power 1–3 and non-defender commanders. High-power and defender
contexts receive an explicit unresolved audit only. Four additional offline full
builds, with model calls forbidden, verify identical baseline/candidate card
multisets for Yuriko and Arcades. This proves the guard preserves selection in those
cases; it does not improve their existing decks.

Earlier Krenko pairs improved supported independent draw 0→2 within $50, repeatedly,
but remained unresolved and included other weak choices. This is retrieval evidence,
not a claim of a good Krenko deck.

## What changed

- Oracle evidence and conservative mechanism parsing distinguish net advantage,
  filtering, recurrence, activation resources and unmet requirements.
- Draw discovery sees the legal scored pool before broad role filtering. Missing
  prices are rejected, and budget/identity/singleton constraints remain hard.
- Early bounded budget reservation and protected packages prevent every affordable
  option disappearing before final repair. Repair emits deterministic receipts.
- Final audit recomputes draw support after downstream mutations. Unknown mechanics
  and unresolved packages are visible instead of silently counted as adequate.
- Replacement role labels now describe incoming cards; regressions reproduce the
  old erroneous draw labels. Angel and plural-Elf activation requirements now inform
  the strategy plan.

## Validation and provenance

Full suite: **1555 passed,21 skipped,54 warnings**. Skips remain skipped; warnings
include existing sklearn clustering convergence warnings. New tests cover public
Oracle examples, adversarial costs/conditions, premium-unavailable alternatives,
context and identity, duplicate candidates, receipts and role integrity.

Private complete run artifacts reside under
`decklab-infra/.private/generator-draw-study/`; no tokens or raw private data are
included in this commit. Source hashes are recorded by each runner:

| Stage | Source SHA-256 |
|---|---|
| Initial development | f95a93aadbfd9dd709712f4dddb603bb5418fe5a4749ff95e8671e0a6515c76a |
| First confirmation | a707546d365642ffc9170d36c591cae530ec1780d7f9f7abdfe4b4df4b5e8293 |
| Adaptive | c8242aae50fca2c0c9fd865ccfe930a5bcf30ae700c22bbdc5b3ed5afcedec31 |
| Final safer source | 4f241c7e11d5e0d7b466f5ba36573faa4bc31cf29bce1c90e98069dfedc8d747 |

See [spec](spec.md), [agent review](delegation-review.md), versioned public fixtures,
`scripts/run_draw_study.py` and `scripts/evaluate_draw_repair.py` for reproducibility.
Full study requires the local catalog and configured inference credentials; offline
mode forbids inference calls. No deployment, push or production URL changes occurred.

## Remaining acceptance work

1. Model commander-specific functions and compare the *lost* function of every
   displaced card, including early reservation effects. Protect engine packages,
   cheap interaction and setup, not only role/tribal counts.
2. Evaluate draw by turn, mana opportunity cost and required board states. Slow
   mechanically valid draw must not displace a strategically better package merely
   to satisfy a count. Expand coverage of existing competitive engines before
   re-enabling high-power mutations.
3. Use the C++ simulator only after implementing and testing actual mana/activation/
   draw-state transitions against independently worked examples. Existing ingredient
   sampling is not an executable Magic-rules or win-rate oracle; no new native draw
   execution was implemented here.
4. Freeze the next policy and reserve new commander/budget combinations for independent
   confirmation. Require manual strategic acceptance and resolved constraints before
   a release decision. A global optimal budget solver and dependence-quota optimizer
   remain unimplemented.

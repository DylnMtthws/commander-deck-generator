# Next priority: affordable completion with meaningful card ranking

## Observed failure

The degraded-embedding Lathril `$100 / power 3 / routes` evaluation demonstrates
an upstream budget-allocation problem that survives corrected draw credit.
The primary real-embedding pairs subsequently reproduced the admission path:
Shoreline Salvager and Nafs Asp enter the greedy snapshot with score zero, remain
as utility in the routes arm, and survive rejected optimizer transitions. The
detailed allocation numbers below refer to the original degraded run.

Local evidence:
`decklab-infra/.private/generator-selection-repair-study/draw-routes-grid/lathril-routes/results/lathril-candidate-0-intelligence.json`.
The `candidate_path`, `infrastructure_draw_routes`, and `upstream.snapshots.greedy`
records establish:

- Infrastructure occupies 66 cards and costs $81.38, leaving 33 slots and $18.62.
- `greedy_optimizer.greedy_fill` reserves a fixed $1 for every slot after the
  current pick. Its initial spendable amount is therefore **−$13.38**.
- With no scored candidate affordable under that artificial reserve,
  `greedy_fill` takes the cheapest eligible card without using its objective and
  assigns score zero. Dread Drone starts that sequence at $0.05.
- Shoreline Salvager is absent from infrastructure, then enters greedy at index
  67 for $0.05 with assignment score zero. Its spendable amount is −$12.43.
- Nafs Asp enters at index 79 for $0.09 with assignment score zero and spendable
  −$1.38. Fifteen consecutive cheap-fill selections cost $0.05–$0.10 each.
- Both cards lose incorrect draw credit but remain as utility. This admission
  path bypasses CVAR, role urgency, and synergy, so removing a stale draw-score
  bonus would not fix this particular cause.
- Both subsequent optimizer stages reject their proposed transactions for
  function/support losses. The final deck costs $98.05 and retains the initial
  cheap selections. The preservation guard is doing its narrow job; it cannot
  certify the strategic quality of the original deck.

The decision path is in `src/sabermetrics/pipeline/greedy_optimizer.py`:
fixed `reserve_per_slot` → negative `spendable` → no scored candidate →
`last_resort` cheapest-card branch → score-zero selection.

## Proposed bounded experiment

Add an opt-in completion-aware affordability policy. For each proposed pick,
compute the minimum price needed to complete the remaining slots from the
remaining distinct eligible card names. A pick is affordable only when its
price plus that completion lower bound fits the actual remaining budget.
Among affordable picks, retain the existing quality objective and deterministic
tie-breaking. This changes feasibility accounting, not the meaning of card
quality. It does not categorically exclude cards with blocked draw routes:
a card may still have a supported non-draw purpose.

Use the same eligible pool as the actual fill, applying existing legality,
identity, singleton, protected-card, and nonland boundaries. Do not count
multiple printings as multiple singleton slots. Never silently substitute zero
for missing, negative, Boolean, NaN, or infinite prices. A price lower bound
proves only cardinality and spending feasibility, not that all role needs or
strategic requirements can be met; report those separately.

An infeasible pool must produce an explicit diagnostic with slots, budget,
distinct eligible count, and minimum known completion price. Define separately
whether the pipeline can release optional infrastructure spending or must fail
closed. Do not hide infeasibility with unconditional score-zero filler or an
unreported land backfill. Preserve existing function guards and original greedy
snapshots throughout the experiment.

## Definitions of done

1. Every selected greedy card has a recomputed quality score and a receipt
   recording actual remaining budget, remaining slots, distinct completion
   candidates, minimum completion price, proposed price, and feasibility.
   Selection is never driven solely by lowest price after a fixed-reserve failure.
2. Completion bounds exclude the current proposal and already selected names;
   duplicate printings cannot make an impossible 99-card deck appear feasible.
   Unknown prices and insufficient distinct cards fail explicitly.
3. Property and adversarial tests cover exact-budget completion, floating-point
   boundaries, zero-priced cards, malformed prices, duplicate names/printings,
   too few cards, protected infrastructure, and no remaining slots. No tested
   accepted path overspends or violates color identity, singleton, or card count.
4. A synthetic pool reproduces the observed `$18.62 / 33 slots` reserve failure:
   the new policy can consider a better scored feasible card while still funding
   every remaining slot. A deliberately infeasible companion case reports why
   it cannot finish instead of inventing feasibility.
5. Re-run paired current/new policies on the same four commanders, budgets, and
   powers registered for the real-embedding draw-route study, with identical
   frozen source, data, model revision, and initial state. Add deliberately tight
   but feasible and infeasible budget cases. Active finite nonzero embedding
   signals are verified; degraded runs remain labeled separately.
6. Every completed deck is exactly 99 legal mainboard cards within budget and
   passes existing transaction/function guards. Compare draw opportunities,
   support losses, final role deficits, non-draw utility, latency, and deck
   membership. Replacing Shoreline or Nafs alone is not proof of improvement.
7. Examine the actual contributions of admitted and displaced cards. Accept the
   policy only when it improves the demonstrated cheap-fill cases without
   unproved losses in the control decks. Report unresolved initial-deck and
   multiplayer/gameplay uncertainty; no win-rate claim follows from static checks.

## Scope and release boundary

This document specifies follow-up work. No completion-reserve implementation or
additional release is included in the draw-route milestone. A later change must
use its own registered experiment and reviewed source freeze. Candidate-count
bounds can be optimized with sorted distinct prices/prefix sums after correctness
is established; performance optimization must not weaken the feasibility proof.

# Reviewed next step: recover valid moves from rejected proposals

**Recommendation:** instrument which individually proved moves are lost by whole-stage rejection, then trial a bounded subset selector in shadow mode. Keep the current atomic guard as the final authority. This targets acceptance throughput, not general Commander intelligence.

## Compare the alternatives

- **Move-level proof gating:** reject unsupported proposed changes before they enter a transaction. This simplifies evidence and cheaply rescues isolated upgrades. A sequential greedy implementation can miss funding combinations or make order-dependent choices; move-level proof itself need not be greedy and can feed a later joint selector.
- **Bounded subset extraction:** for at most six fully identified candidate pairs, inspect at most63 nonempty combinations. Each candidate starts from the same immutable baseline, never from a previously modified candidate. Reject conflicting removals, duplicate additions and undeclared dependencies. Evaluate all selected pairs plus the whole resulting deck. This finds a valid combination only within those six moves, not the global best deck.
- **Equal-function funding pairs:** allow mechanically nonregressing monetary savings to accompany an independently proved upgrade. Savings alone remain insufficient. This rule works with subset search or another joint transaction planner; it is not exclusive to subset enumeration. A cheaper printing counts only under an explicit supported printing-price policy, never imagined resale proceeds.
- **Commander utility contracts:** strengthen rejection predicates for activation resources, relevant cast categories, tutor targets, outlets and conditional draw. They do not authorize cutting cards whose other functions remain unknown. Add a contract only with positive/negative Oracle fixtures and demonstrated coverage limits.

## Proposed small experiment

Freeze input cards, prices, proof version and commander facts. Canonically identify pairs using stable semantic IDs. Evaluate each pair's structural proof, then enumerate bounded combinations and revalidate full-deck constraints and budget. Select among valid subsets using a declared deterministic policy; do not disguise “fewest edits” or another tie-break as a strategic-quality theorem. Commit only the selected whole subset with unchanged snapshot/version. Preserve the original proposal, every selected/rejected pair, failures, evaluation count and final before/proposed/after receipts.

If a cheap screening pass differs from authoritative validation, retry the next candidate within the same bound or abstain. Do not assume the highest-scoring screened candidate is valid. Do not silently split larger proposals: use explicit bounded preselection with recorded exclusions, or abstain. Record both dependency losses and candidate-order bias introduced by any preselection.

## Falsifiable acceptance cases

1. **Valid+unknown:** A is proved and budget-feasible; B cuts an unknown outlet. Return A alone; never use B to fund A.
2. **Funding:** A exceeds available headroom; C preserves fully understood functionality while costing less. Accept A+C only when the complete proposed deck fits budget and A supplies a proved non-monetary gain. C alone abstains.
3. **Joint contract failure:** two independently acceptable mana-cost reductions remove the last two matching-MV tutor targets when combined. Singles may remain valid; the pair fails the full-deck target-preservation contract. Do not manufacture this test by allowing an already function-losing ramp cut through an allegedly complete per-pair proof.
4. **Conflicts:** two moves remove the same card, add the same singleton, or require one another through an unsupported chain. Reject the conflicting subset. A dependent two-hop rewrite must first become a separately proved direct replacement; it cannot bypass coverage.
5. **Order invariance:** reorder input pairs; canonical chosen identities, accepted result and normalized receipt must match. Raw input indices are not valid order-invariant tie-break keys.
6. **State validity:** changed snapshot/price revision, invalid numerical price, stale commit version, unknown card semantics or failed final hard constraints cannot commit. The original deck remains unchanged.
7. **No quality laundering:** receipts distinguish lower monetary cost from functional/casting-resource gain. No subset is accepted solely because it is smaller, cheaper or proposed by the optimizer.

## Latency and decision threshold

The63 bound counts local subset evaluations, not63 model calls or full generation runs. Reuse immutable facts and cached proof results; measure subset-check time and memory. Predeclare an elapsed-time cap and abstain transparently on exhaustion. Report eligible moves rescued, reasons for remaining rejection, order invariance and per-stage latency. Continue only if real rejected proposals contain recoverable proved moves often enough to justify the extra path; otherwise retain simpler move-level gating.

## Review limitations and receipt

The Opus draft incorrectly portrayed subset enumeration as the only way to handle funding, suggested an input-index tie-break alongside permutation invariance, and used a coalition example that could conflict with strict per-pair preservation. Those points are corrected above. It supplied no evidence about current implementation or actual proposal frequency.

Actual invocation: `claude --model opus --effort medium`, public generic specification only, no repository source/private decks/credentials. Receipt `opus-public/agent-result.json` reports success, primary `claude-opus-5` plus auxiliary Haiku,31907ms. The response was returned inline and preserved as `opus-public/next-step.raw.md`. No code changed and no proposed tests were represented as executed.

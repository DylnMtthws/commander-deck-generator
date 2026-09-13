# Reviewed atomic Commander swap specification

This combines an actual Fable5.1 Medium design session and independent Opus Medium review. It is a reviewed design, not a code audit or executed test result. Only public Oracle fixtures and generic scenarios were supplied externally.

## Acceptance and commit

1. Capture an immutable semantic snapshot of the actual complete before-deck, including stable identity, card text/type/cost/color data, protected identities, budget inputs and a consistent price revision. The optimizer may mutate a separate deep copy. Returning that working copy is legal; it must never alias the protected snapshot.
2. Normalize and validate the entire proposed deck. Preserve99 mainboard count, identity legality, singleton with explicit legal exceptions, locked cards, valid finite prices and full-deck budget. Reject missing or unsupported evidence. A sell/buy reserve calculation cannot replace full-deck valuation.
3. Account for every removal and addition through one-to-one validated substitutions. Unknown outgoing functionality cannot silently disappear. Require every pair to be nonregressing under the bounded proof and at least one independently proven mechanical/casting-resource improvement. Monetary savings alone are not that improvement; a harmless cost-saving pair may fund a separate proved upgrade.
4. Commit all or none. Mixed safe/unsafe proposals roll back entirely in this milestone. Rejected attempts retain immutable before/proposed/after receipts, explicit rejection reasons and zero accepted-trade counts. Current/off controls report actual changes too; a switch cannot conceal mutations.
5. If state is shared, recheck snapshot version under the commit lock. Deep copying protects in-memory inputs only: persistent writes must be outside the optimizer callback or transaction-bound. Harmless attempted-operation logs and read caches need not pretend to roll back; accepted metrics must reflect committed output.

## Falsifiable tests

- Positive: verified Weave Fate→Quick Study, same instant/controller-draw function with reduced generic casting demand, in an explicitly synthetic neutral test context. Positive Shock→Lightning Bolt requires the damage-proof family and relevant commander conditions actually covered.
- Negative: Bombardment→ordinary draw loses an outlet/damage function; Remora→one-shot draw loses its recurring conditional engine; rebound loss, creature-body uncertainty or unknown replacements cannot be bought off with savings.
- Atomic rejection: one good pair plus one unsupported pair leaves output bit-for-bit equivalent to the immutable before snapshot; proposal remains visible in the rejection receipt and accepted trade count is zero.
- Input ownership: callback mutates nested objects, then raises or returns an invalid proposal. Original inputs remain unchanged. A callback returning its own independent working copy is not itself an error.
- Receipt integrity: recompute before/proposed/committed identities from data, not callback-reported counts; retain rejected proposal payload inertly. Same-ID altered semantic text must be detected.
- Budget: with before total90 and budget100, two changes adding8 each are independently affordable but jointly106 and must reject. Missing/negative/NaN/infinite prices fail explicitly. A monetary saving with no proved functional/resource improvement must abstain.
- Commit: stale version, duplicate proposal/removal, precommit exception and postcommit metric fault cannot create partial deck output or phantom accepted counts. Basic-land multiplicity must use legal exceptions rather than a blanket duplicate-name ban.

The reviewed JSON contains24 abstract positive/negative scenarios. `stub99` is a fixture adapter instruction only: expand it into an explicit validated complete deck before execution. Never accept a production caller's assertion of complete context. Synthetic prices are not market prices. Absence of detected commander restrictions is not evidence of neutrality.

## Independent review corrections

Fable invented the supplementary Oracle text of Inspiration as controller-only draw. Actual Oracle targets a player. Replaced that positive with verified Weave Fate and added Inspiration→Quick Study as a negative. The other supplementary records matched the frozen public catalog.

The Opus review usefully identified stale-state checks, semantic payload validation, whole-stage budget arithmetic and side-effect boundaries. Its claims that returning a working deepcopy is necessarily aliasing, every neutral pair constitutes laundering, harmless logs/caches must all roll back, and current code would fail were rejected. No source was supplied to support claims about current implementation.

## Actual session receipts

- Installed Claude2.1.259 help advertises Fable; its executable contains identifier `claude-fable-5-1`. Explicit invocation `--model claude-fable-5-1 --effort medium` succeeded. Receipt confirms primary `claude-fable-5-1`, auxiliary Haiku, duration251036ms. Receipt: `fable-public/agent-result.json`.
- Independent `--model opus --effort medium` succeeded. Receipt confirms primary `claude-opus-5`, auxiliary Haiku, duration43782ms. Review text was returned in the receipt and preserved as `opus-public/atomic-review.raw.md`.

Both sessions used only Read/Edit/Write/Glob/Grep with public-only isolated inputs; no private decks, repository source, credentials or production data. No production code changed here. These local proofs cannot establish complete Commander strategic equivalence or a win-rate improvement.

# Preserve functions when improving draw

## Problem and bounded scope

The previous draw experiment raised supported-draw counts while displacing cheap
interaction, tokens, tutors and commander setup. Early budget reservation changed
later selection, so checking only final swaps could not establish preservation.
This milestone must prevent those regressions, not re-label them successful.

Implement a conservative replacement transaction over a completed baseline deck.
Guarded mode performs baseline infrastructure, optimizer, legality and mana selection
first, with experimental early draw reservation disabled. Only then may it improve
a supported, fully covered simple draw spell. Unknown removable functionality is a
reason to retain the card, never permission to cut it. This intentionally trades
recall for a defensible automatic-change boundary. It does not certify the baseline
or claim a universal commander engine.

## Definitions of done (registered before implementation)

1. Oracle-derived function facts expose interaction target scope, mana, cost
   reduction, tutors/selection, token generation, haste/protection and card flow
   with exact evidence. Unsupported text stays incomplete. No named-card overrides
   may decide replacement acceptance.
2. Whole-deck multiset receipts identify removed protected identities, losses of
   supported function/scope counts and unknown removals. Recognized partial facts
   cannot certify full coverage. No-op is explicitly not an improvement.
3. Every automatically removed card has an explicit complete substitution proof.
   First supported proof family: unconditional fixed-quantity draw-only instant or
   sorcery, same spell type, no higher mana value, no new/increased colored-pip
   requirement, no loss of net draw, and strictly better draw or casting resource.
   Prices and whole-deck budget, singleton, identity, legality and count are hard.
   Unknown mechanics, additional clauses, permanents, variable/alternative costs,
   tutoring, selection, wheel effects and commander-protected cards fail closed.
4. Draw reservations cannot silently bypass the guard. Guarded builds complete a
   baseline first, record it, apply bounded verified swaps and validate the entire
   final transition. Rejected transitions retain the complete baseline and a reason.
   Every accepted change has its proof; post-change review claims are invalidated.
5. Regressions cover the prior lost functions (Pongify, Generous Gift, Young
   Pyromancer, Windfall, Elven Ambush, Elvish Harbinger, Pearl Medallion, Top and
   delve spells), misleading role labels, scoped interaction, partial coverage,
   package-wide losses, duplicates, budget/identity, order and immutability. Positive
   cases demonstrate the gate can accept genuine supported improvements rather
   than merely blocking all mutations.
6. Re-evaluate prior unsafe full-build differences and report blocked losses.
   Freeze source and run real builds across at least six previously observed
   EDHREC top50 commanders: varied colors, budgets and powers. For each guarded
   output verify the internally recorded baseline-to-final transition, not only
   comparisons between stochastic model runs. Require zero unauthorized removals,
   zero implemented hard-check failures and proof for every accepted swap. Preserve
   no-op/unresolved outcomes; no-op is safety evidence, not draw-quality progress.
7. Full Python suite, relevant lint and independent agent review pass. Report
   concrete improvement and unchanged limitations. If all real transitions are
   no-ops, say so. Do not claim optimal decks, full Oracle coverage or improved
   win rate. No deployment or push in this milestone.

## Delegation and future work

Claude Code: public Oracle function extraction and focused fixtures. Cursor:
strict pure multiset/function receipts and adversarial tests. Coordinator:
substitution proofs, transactional baseline integration and independent review.

The next wider proof families require executable commander support and timing
models. Actual C++ draw/activation simulation is not implemented by this bounded
change; existing ingredient sampling cannot validate the lost value of a tutor,
interaction spell or engine. Avoid compensating for missing semantics with an
unvalidated weighted score. Fewer speculative changes are the intended outcome.

## Pre-freeze independent review corrections

Commander text referring to mana value, casting cost, cascade/discover or related
cost-sensitive mechanics prevents changes to mana demands in this proof family.
Spell color identity must remain identical even when both options are legal;
legality alone cannot preserve a colored-spell trigger. Per-function receipt scopes
include prerequisites, not just a broad function name. One incoming card cannot
justify several removed cards: the whole-deck proof uses one-to-one matching.

Actual public-card fixtures demonstrate a useful boundary: Weave Fate to Quick
Study preserves self-draw and instant timing at lower cost. Inspiration to Quick
Study is rejected because Inspiration can target another player. Synthetic fixture
prices test constraints; these are not live-price claims.

Final validation expands the real cohort to eight commanders / twelve builds,
adding The Ur-Dragon and Azula audit controls for five-color and power5 coverage.

## Validation correction after the initial frozen batch

Strict final comparisons exposed missing-versus-empty Oracle IDs on synthetic
basics during serialization. Normalize these two unknown-ID representations only;
retain real IDs and exact functional fields. Test repeated basics as multisets,
not a name-to-single-card dictionary. Preserve all initial failed receipts, then
recheck old bad transitions and rerun the complete cohort on a corrected freeze.

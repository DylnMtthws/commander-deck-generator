# Commander-aware substitution expansion

## Outcome required

Expand the existing safe replacement boundary so actual generated decks receive
useful, explainable improvements. A second all-no-op run is not sufficient.
Unknown effects stay protected. Card count, price, legality and established
functions remain hard constraints; commander preference does not erase them.

## Definitions of done

1. Derive commander contracts from printed Oracle evidence: tribal bodies, cast
   categories, token scaling, defender support and mana-value sensitivity. Expose
   incomplete coverage and distinguish supported facts from strategic certainty.
2. Every accepted swap preserves its old supported functions and commander
   contributions. Add complete proof families for direct targeted damage, optional
   additional-cost draw, and fully described static creature bodies. Require same
   casting category and no greater casting demands; maintain target scope, old cost
   options, creature body/keywords/subtypes and protected identities. A greater
   effect or supported additional option must make the change strictly useful.
3. Missing power/toughness cannot justify a creature change. Preserve available
   printed fields through model serialization, but do not invent stats or claim
   the existing catalog has them. No complete creature proof without those facts.
4. Exclude non-main-deck game pieces (including the discovered sticker sheet) before
   selection and reject them at final acceptance even if a catalog legality flag
   says true. Explain this as a separate eligibility defect, not a commander upgrade.
5. Unit/adversarial tests cover actual public positive pairs, lost casting/tribal/
   defender contributions, extra restrictions, unknown stats, cost/timing/color,
   artifact-sacrifice versus existing discard options, targets and serialization.
   Previously rejected harmful full-deck changes must remain rejected.
6. Develop on historical decks/offline budget cases, freeze policy, then validate
   real full generations across varied commander colors/budgets/powers. Require
   at least two real useful accepted substitutions across at least two generated
   cases, zero unproved removals and zero hard-check failures. Record internally
   completed baseline versus persisted final; name the changes and review them.
   All candidate cases exposed during tuning are development, not held-out proof.
7. Full tests and relevant lint pass; actual Cursor and Claude work is reviewed.
   Report successful changes, remaining no-ops, incomplete coverage and deployment
   status. No deployment or push requested in this milestone.

## Architecture and scope

Keep baseline-first transactional selection. Whole-deck receipts and one-to-one
matching remain mandatory. Functions may be discharged only by a complete local
proof, not by a higher model score. Commander contracts constrain those proofs;
this milestone does not solve optimal packages, matchups, or general Magic rules.
High-power/defender audit-only controls remain until separately supported.

Claude Code: bounded public commander-contract module. Cursor: complete static
creature-resource grammar and independent negative cases. Coordinator: new proof
families, eligibility, whole-deck integration and review. Existing C++ ingredient
sampling is not represented as actual draw/interaction gameplay simulation.

## Development corrections and independent review

Exact public Oracle records refine the admitted damage family: preserve any-target
scope, base damage, optional kicker modes and player-damage scry. An incoming card
cannot exchange those modes merely for more base damage. Known additional payment
options must retain the old route; absence of an artifact never invalidates an
existing discard option. Optional-mode preservation is not a win-rate estimate.

Independent review demonstrated a 1/1→2/2 regression for a commander rewarding
creatures with power1 or less. The corrected policy requires identical printed
stats when the commander or baseline deck references power/toughness. Search and
final one-to-one matching both receive the original baseline support context.

Offline budget development selects ordinary generated cases, never forces named
cards into a deck. The final full-build cohort includes paired Krenko$51/$55 at
power3 and controls covering Krenko$50/p1, Lathril, Giada, Vivi, Arcades, Yuriko,
The Ur-Dragon and Azula. These cases are development-exposed and do not establish
held-out generalization. Preserve no-op outcomes and historical rejected swaps.

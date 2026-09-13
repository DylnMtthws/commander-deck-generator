# Mechanically supported budget draw selection

## Milestone and definitions of done

Deliver a substantial, demonstrated improvement in budget card-advantage selection,
not a claim that every Magic choice or matchup is solved. Production remains unchanged.
The baseline is commit131c999. Draw controls default off until release review.

A credible draw option must have a supported Oracle-derived effect, legal identity,
known nonnegative price, feasible deck prerequisites, and a positive contribution
under a documented scenario. Filtering, replacement draw and repeatable engines
are distinct. Opponent-dependent value is conditional, never guaranteed. Unknown
mechanics do not satisfy a verified draw floor. Such a card may remain for another
purpose; its draw role is explicitly unverified.

Done requires all of the following:

1. Public exact Oracle fixtures cover Rhystic Study, Arena, Unagi, Notion Thief,
   Insight Engine, immediate net-positive draw, looting, creature cast/ETB/death,
   combat triggers and sacrifice costs. Supported effects have source evidence;
   unsupported shapes return unknown. No card-name blacklist/whitelist in scoring.
2. Retrieval preserves affordable supported draw mechanisms independently of old
   broad role tags. Candidate prices, legality, commander identity and singleton
   are hard constraints. Missing prices are not free.
3. The deck-level repair compares affordable alternatives against the actual deck,
   preserves lands/protected packages and minimum non-draw role/type coverage,
   and rechecks final count, budget, identity and prerequisites after every swap.
   Every examined card receives a disposition; unknown is not passed as verified.
4. Benchmark cases show that removing premium draw still yields usable alternatives
   where available; filtering does not count as net advantage; unsupported creature
   requirements cannot pass in creature-light decks; color-illegal substitutes are
   rejected; input ordering does not determine the result; no source mutation.
5. Run matched baseline/candidate experiments on at least six EDHREC top50 commanders,
   covering mono-, two-, three- and five-color identities, budgets $50/$100/$200/$1000
   or nearby case values, and powers1/3/5. Include three low-budget cases. Preserve
   all failures and completed outputs. Repeat at least one pair. Confirm held-out
   candidate improvements after freezing policy; mark later tuning exposure honestly.
6. Among completed pairs, improve the independent count of supported, feasible
   positive-advantage cards by at least two on at least three initially deficient
   cases, with zero mechanical regressions and no loss of verified draw coverage
   in other cases. Independently inspect all swaps for lost commander functions;
   metric improvement alone is insufficient. Otherwise iterate, not declare done.
7. Full Python suite and meaningful new regression tests pass. Report the actual
   model-review coverage, unresolved constraints and scenario limitations. Record
   agent receipts and coordinator corrections. No deploy as part of this study.

## Architecture

Claude Opus Medium: bounded Oracle draw representation and regression fixtures.
Cursor: deterministic multiset selection receipts and report tests.
Coordinator: contextual evaluation, retrieval, deck repair, independent benchmark,
integration and review. Model prose is not its own ground truth.

Begin with conservative deterministic scenarios rather than invented learned
weights: immediate net advantage; recurring draw over three opportunities;
activation mana charged explicitly; typal/cast/death prerequisites from deck facts;
opponent-dependent engines never alone establish dependable coverage. Compare
alternatives using contribution per mana, setup/support, then cost and empirical
corroboration. Parameter sensitivity is development evidence, not win probability.

The first milestone does not implement a general game engine or globally optimal
budget solver. Bounded swaps use whole-deck remaining budget and protect established
functions. If local swaps cannot reach the floor, report an unresolved package,
never silently label weak filler acceptable. A later C++ probe must validate
actual activation/mana states against independent small examples before its output
can select cards. Existing native ingredient-access sampling is not draw execution.

## Experiment sequence

Restore failed billing controls using frozen previous code in a separate snapshot.
Develop on Krenko, Lathril, Vivi and Azula; freeze the draw policy before confirming
on Giada, Arcades and The Ur-Dragon. Cases come from the observed
[EDHREC top50](https://edhrec.com/commanders), retrieved September13,2026. Compare
same full baseline deck with deterministic post-selection intervention first to
isolate causality; then complete fresh candidate generations and re-audit after
all downstream stages. Record which comparisons are replay versus fresh builds.

## Registered development correction: rejected v1/v2 replays

The first post-selection replay failed manual review despite count gains: unsupported
hand replacement, control transfer, tribal triggers and extra costs were credited,
and useful commander cards were cut. These results are rejected, retained as
negative evidence, and their real Oracle examples added to regression fixtures.
The second conservative replay made almost no changes because the budget was
already exhausted. Therefore add early supported draw reservation capped at15%
of the deck budget (within the existing overall infrastructure cap), protection
through later swaps, and a final independent audit. This is a new tested pathway,
not retroactive evidence that the original post-selection approach succeeded.

Candidate admission additionally limits first draw access to5mana at powers1–3,
4mana at powers4–5, and repeated activation to2mana. High-power tap-creature draw
without haste and power5 upkeep engines are not admitted as upgrades. These are
conservative tempo policies, not universal card bans or proof of competitive power.
Existing supported commander cards and empirical cards at>=10% are protected from
replacement; unsupported filtering may still be strategically valuable. Confirm
quality by the actual swapped lists, not by the count policy alone.

## Final admission policy and scope

The resource score accounts for cast/activation/equip mana, a declared life-cost
burden (half-life evaluated from40), and repeated colored-pip burden in multicolor
shells. It is not printed mana value, actual mana paid, or win probability. Prices
are normalized by the package/deck budget so an affordable premium engine is not
penalized as heavily in a $2500 deck as in a $50 deck. Highest-power generic
one-shot additions are limited to2mana; this deliberately does not certify the
many unsupported competitive engines already in a deck.

Simple draw spells require full effect coverage, so a recognized draw sentence
cannot conceal a restricted target, skipped turn, sacrifice or benefit to opponents.
Counter-limited artifacts carry explicit activation caps. Token support distinguishes
any tokens from creature tokens and excludes a card as its own required external
source. Duplicate candidate records cannot create duplicate singleton selections.

Confirmation exposed Moderation's unmodeled global spell limit. Its draw credit is
rejected, a versioned public regression added, and Arcades/Ur-Dragon reclassified
as development-exposed before adaptive reruns. Yuriko is the subsequent independent
draw-policy confirmation. Failed candidate ideas and old false-positive counts
remain in historical receipts; final reports use the corrected audit.

This milestone's done criteria measure implementation, regression protection,
reproducible budget-draw improvements and candid acceptance reporting. A package's
`met` label means only its configured supported-draw floor. An `unresolved` package
is not a quality pass. Even passing this engineering milestone does not authorize
release or certify every card choice. A global opponent-dependence quota optimizer,
complete commander-specific ability representation and C++ stateful draw execution
remain subsequent work; they are not represented as implemented here.

## Final safety decision and acceptance status

Yuriko confirmation failed strategic acceptance: supported draw displaced better
commander functions. Arcades showed the same class of opportunity-cost issue.
Automatic mutations now apply only below power4 and outside defender commanders;
other contexts are audit-only and explicitly unresolved. Identical offline paired
card multisets verify this guard for Yuriko and Arcades. Angel recognition and
plural-Elf typed activation parsing were corrected before six final real low-power
builds, with those corrections common to both arms.

Final results satisfy the numerical gain and implemented hard-constraint checks,
but **criterion6's strategic acceptance remains open**. Manual review still finds
questionable lost functions and slow additions. This is a substantial bounded
implementation improvement, not completion of every original acceptance criterion
or permission to deploy. See results.md for the evidence and remaining work.

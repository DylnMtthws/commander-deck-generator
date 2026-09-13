# First card-selection repair milestone

## Implemented fixes

| Observed failure | Change | Scope/limit |
|---|---|---|
| Shock/Burst initially utility; Play with Fire initially draw | Shared complete-damage classifier before broad heuristics | Explicit valid model role keeps existing precedence; player-only/unparsed damage excluded |
| Catalog and hydration discard printed creature resources | Nullable P/T/printed-colors migration, ingestion and commander/final-model hydration | No production backfill; old records remain unknown; no invented DFC front-face stats |
| Optional unusable ability confused with useless card | Ability-level prerequisite evidence plus fallback/remaining text in final intelligence | Diagnostic only, incomplete coverage; never authorizes a cut |
| Study factors differ from deployed web policy | Shared production_policy and fully recorded effective study settings | Earlier experimental results cannot be claimed as exact web-policy validation |
| Offline runner inherited 20% land-budget override | ProductionReplay shares the production template method | Frozen profiles and skipped model review still make these offline replays, not live builds |
| Unbounded tuning or selective favorable cases | Registered 16-configuration factorial grid, source/data identity and explicit cap | Tests implemented controls only; not all possible Magic fixes |

Canonical persistence retains printed colors separately from Commander identity.
A colorless creature with colored activated abilities must not acquire the colors
of its identity. Symbolic power/toughness are retained, not converted to numbers.

Claude's evaluator distinguishes matching printed deck entries from available
battlefield resources. Missing or ambiguous fields remain unknown. Separate
sacrifices require distinct cards; a multicolored body does not pay three sacrifices.
Courier's Food-token fallback is preserved, and missing named targets do not erase
a creature's remaining body or types. This enables more careful future repair;
it does not yet justify replacing Dragon's Herald with Goblin Motivator (which
also loses Shaman and a printed tutor ability).

## External sessions and review

Cursor Grok 4.6 High completed the narrow role task, exit 0. Source-only receipt:
`/Users/dylan/Projects/generator-role-agents/cursor-result.json`. Local review removed
fixture-absence skips so required public-card regressions cannot silently skip.
Expanded role/pipeline validation: 77 passed, 3 skipped.

Claude Code Opus Medium completed the public-only prerequisite module: primary
Opus5 plus auxiliary Haiku,263721ms, successful receipt at
`/Users/dylan/Projects/generator-prerequisite-agents/claude-public/agent-result.json`.
Local review added malformed metadata, distinct sacrifice, Devoid and multi-face
boundary tests. 34 prerequisite tests pass. Private decks/credentials were not
included in the Claude task.

## Registered evaluation

The exact small grid crosses four independent factors: budget recall0/12, land
evidence weight0/10, land risk weight0/1, guarded substitutions off/on. Function
preservation stays enabled in every arm. There are 16 unique policies, including
exact production policy; full and pairwise coverage are tested.

Run 16 Krenko$51/p3 configurations plus production baseline/candidate pairs for
Giada$150/p3, Vivi$200/p3 and Lathril$100/p3:22 total ordinary offline builds,
no forced cards. These are development-exposed cases, not held-out evidence.
Model calls are forbidden; frozen cached profiles and skipped model review are
explicit. Existing public-card data are copied into isolated databases and migrated
without populating missing stats from guesses.

Source SHA256:`36de2d77cb32c7cd7653a364e4a17e992d1e14da372ab57e91e1db25ffd9d190`.
Source+scripts SHA256:`9fef56e87c5248046288140aaca1d9b78ba8f3239138372c0dcf2c30d2eb7069`.
Private outputs: `decklab-infra/.private/generator-selection-repair-study/offline-grid-corrected`.

The first 22 registered builds completed with zero hard/transition errors and no
model calls, but the independent role audit failed10 outputs: eight Krenko Shock
entries and both Vivi Lightning Bolt entries persisted as utility. Inspection
found the greedy optimizer bypassed the shared helper and trusted stale role_tags.
This source freeze is rejected for the role-consistency definition of done.
The failed receipts remain in offline-grid-corrected/role-failures.json; no passing
transition check is presented as proof that role or deck quality passed.

The optimizer and synergy readers now share complete damage evidence. Canonical
annotation preserves discovery metadata but supplements stale capability coverage
with exact Oracle-backed role evidence. Changed Oracle text invalidates old role
proofs. The runner now checks all saved damage roles, including baseline cards.

The identical 22 runs were repeated from the same initial data. Final source:
`cc36adb5b523f61cd51af9657f295093168502109f08b304446074261626b94b`;
source+scripts:`b6f77749a2fc1a440d0453f07e618e7f1471de5120e95cc8aabfdf2294a42585`;
data:`3592bf8f2c5ef7a51b602b118e32b08d7da2375f29e6b620bba2a3d7462fee52`.
Final artifacts: `offline-roles-grid` beside the prior failed cohort.

**Mechanical validation passes; strategic acceptance fails.** All 22 finish with
zero hard, transition or persisted damage-role errors and zero model calls. All
five historical harmful transitions still reject. Eight Krenko candidate arms make
only Shock → Burst Lightning versus their same-source baselines; the production
pair finishes at $50.86 → $50.97. Giada ($149.35), Vivi ($199.15) and Lathril
($99.85) pairs are unchanged by the guarded postprocessor. All draw audits remain
unresolved; all cards remain explicitly unreviewed by a model. Both cohorts total
44 offline builds, with the first 22 retained as failed role evidence.

Across revisions, 18/22 decks change membership. Production Krenko loses Goblin
Bombardment and Goblin Chirurgeon while adding the eight-mana Bearer of the Heavens.
Bearer enters swap refinement for scalar objective delta+0.0044. Bombardment is
sold because estimated reallocation+0.0108 exceeds measured contribution+0.0026.
The monocolor mana probe is not applicable and supplies no turn-castability proof;
detailed swap score components are absent. Vivi loses Mystic Remora while admitting
Scaretiller and The Underworld Cookbook for small scalar gains. These changes lack
sufficient strategic preservation evidence and block a deployment recommendation.

The failure occurs upstream of the guard's recorded baseline. More accepted
post-baseline upgrades cannot certify that baseline. The next specification targets
swap refinement and budget unbundling directly, including function-preserving
alternatives and off/current ablations. See the final section of [spec.md](spec.md).

[Executed cases](executed-cases.json) and [validation summary](validation.json) retain
all configurations and acceptance status. A final diagnostic-only change softens
the older sacrifice warning: static absence cannot prove activation impossible
when token/color-changing effects are unmodeled. It does not change findings codes,
selection, or control flow; it was tested separately after the frozen cohort.

## Independent strategic review

A second actual Claude Opus Medium public-only session reviewed a hypothetical
Krenko pool. Its [reviewed report](strategic-review.md) proposes exact-context
mechanical tests, fixed-pool quota ablations, source/payoff package counterfactuals
and bounded one/two-card opportunity-cost swaps. Local review rejected unsupported
claims about eight-mana castability, invented creature thresholds and relaxed color
identity. No generated private deck or source was sent in that task. This report
informs the next test design; it is not independent expert approval of the actual
cohort decks.

## Remaining work and deployment

This milestone corrects demonstrated role/data/evaluation defects and adds richer
failure evidence. It does not establish reliable draw-package selection or broad
strategic improvements. All draw/interaction floors still need archetype-specific
validation. The complete fix-family search and later release gates are in
[spec.md](spec.md); unimplemented families are not counted as tested.

The final full suite passes **1,943 tests, 21 skipped**; targeted new-module Ruff
checks pass. Existing repository-wide lint/type debt remains outside this scope.
Additional actual Cursor sessions for greedy and synergy readers both exited0;
114 combined focused tests passed. Receipts are in `generator-optimizer-role-agents`
and `generator-synergy-role-agents`, respectively.

No push or deployment is part of this implementation round. The existing site
continues running 79cdb58, with its prior database and owner access unchanged.

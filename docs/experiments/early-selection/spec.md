# Early candidate admission and contextual replacement

## Required outcome

Trace supported cards from legal admission through scoring, recall, infrastructure and greedy selection. Fix the earliest demonstrated selection defect without forcing named cards. Expand replacement validation to account for relevant support cards in the entire deck, not only the commander.

## Definition of done

1. Opt-in immutable candidate-path receipts show explicit presence/absence, all matching printings, scores and relevant veto flags at ordered boundaries. Tracing never changes selection. A frozen Vivi replay explains Mystic Remora's first exclusion/omission with actual data; unknown causes remain unknown.
2. Implement the demonstrated initial-selection fix with a separate experimental control when it changes heuristic behavior. Preserve legality, finite budgets, commander constraints and downstream upstream-preservation controls. No arbitrary card-name guarantees or substitution based solely on popularity.
3. Contextual replacement checks retain support-card dependencies such as mana-value-sensitive access. Actual before and after full decks, not individually evaluated pairs alone, govern acceptance. Positive and negative tests must distinguish a proved local improvement from lost deck support, and unsupported sensitivities abstain explicitly.
4. Cursor supplies bounded code with tests; Claude reviews public contracts/fixtures. Coordinator reviews and integrates. Model-generated claims are not test results.
5. Compare frozen identical data and cached profiles with and without the targeted selection change across the available commander cohort, including distinct identities/budgets. Initial cap 2 diagnostic replays then 12 evaluation builds (current first-fit, budgeted linear beam, and trigger-diversity beam across four commanders); adapt with an explicit recorded reason if failures need further runs. No model calls or production writes in evaluation.
   Predeclared beam width is 48 per slot count; diversity weights are 1, 0.85, then 0.25. The linear-beam arm isolates budget search from this heuristic. Both optimizer stages use preserve in all arms. The existing configured game-changer schema is repaired in every arm; the configured list itself is not updated.
6. Full tests and independent saved-deck assessment pass. Report initial candidate omissions separately from later optimizer losses; no general optimality, multiplayer win-rate or guaranteed draw claims. Keep unverified draw packages unresolved and do not deploy this research milestone.

## Pre-build refinements from helper experiments

The first diversity search selected six-mana Niv-Mizzet, Parun; matching a generic cast mention also grouped paid counter-based draw as direct draw. Before full builds, restrict recognized groups to a draw clause in the same trigger and exclude explicit filtering from direct cast-draw grouping. Both beam arms reserve early draw with printed MV ceilings 5/4/3 for powers <=3/4/5; this is a tempo policy for this package, not a ban on expensive cards elsewhere. Unknown printed mana value cannot satisfy this reservation. Record these constraints and the package's unmodeled effects. No claim that Frantic Search is net card advantage or that Ophidian Eye is equivalent to Remora.

The 12 builds use Vivi200/p3, Krenko51/p3, Giada150/p2 and Lathril100/p3, all with frozen commander-keyed profiles. No claim about a freshly generated power-specific model profile. The named-reference contextual veto was added following an independently reproduced synthetic false-safe case. Whole-deck acceptance retains the original outgoing-effect proof; matching support counts alone cannot authorize a substitution.

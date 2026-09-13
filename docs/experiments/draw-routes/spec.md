# Actual draw routes and conditional commander support

## Definitions of done

1. Parse actual draw-route costs separately from printed mana value: spell/ETB, channel/discard, activated mana/tap, combat/death and opponent-dependent triggers. Unknown costs, variable output and unparsed restrictions stay explicit. A parsed route is not a complete-card substitution proof or an expected draw count.
2. Reproduce Action News Crew's six-mana Channel (not its two-mana body), Shoreline Salvager's Island requirement, Sanctuary Warden's counter/ETB/attack routes, Moldervine Reclamation's death trigger and Remora's tax/upkeep. Positive and negative tests use frozen public Oracle; synthetic fixtures are labeled.
3. Report Giada's conditional one-white-mana support only for matching casting routes and payment symbols. No support for Channel/activation or off-type spells. Preserve printed MV6 for Warden. Vivi's variable power/own-turn activation is state-dependent and supplies no invented fixed discount. Commander setup/untap/summoning-sickness assumptions remain in receipts.
4. A separate `routes` experiment uses current initial-package ranking and monetary cap with actual route assessment; it does not reuse the failed diversity search or global printed-MV ceiling. Modeled infeasible/over-tempo draw routes cannot reserve draw slots. Unknown coverage must stay unverified rather than acquire false positive credit. Conditional opportunity is not guaranteed/reliable draw.
5. Audit the actual completed99 for prerequisites. Candidate-pool membership, future plans and raw role tags are not support evidence. Reserve/credit checks and prior independent draw metrics remain separate; positive regressions cannot be manufactured by changing the denominator or evaluator.
6. Freeze source/scripts/config and original data3592bf8f…, cached profiles, no generation model calls. Eight initial builds: current versus routes for Vivi200/p3, Krenko51/p3, Giada150/p2, Lathril100/p3, both optimizer stages preserve. Retain earlier failed output fixtures. Trace actual chosen package and final deck; stop on unexpected errors. Record reasons before extra experiments.
7. Accept only demonstrated cost/prerequisite improvements without the preceding Warden/Moldervine opportunity losses or lower existing credible-draw counts. Fail general promotion if strategic regressions recur. Remora admission is not mandatory and no card is forced by name. Full tests, independent review and precise limitations required; no deployment in this milestone.

## Delegation

Fable5.1 Medium handles public route-compiler design/code/tests and heavy analysis. Cursor handles the bounded commander-support helper. Opus Medium independently reviews public validation scenarios. Coordinator reviews and integrates local code, owns contextual decisions, and evaluates full-deck outcomes. No private decks, credentials or production data are sent to external sessions.

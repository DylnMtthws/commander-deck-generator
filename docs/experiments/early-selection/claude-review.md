# Reviewed contextual replacement rules

**Priority:** add full-deck support checks as vetoes around already bounded replacement proofs. A matching support count does not prove that the outgoing card's own functions survive. Static evidence can verify specific supported relations; it cannot decide every Magic interaction or establish strategic superiority.

## Implement first

1. **Preserve the complete covered outgoing effect.** Match timing, targeting, resource costs, recurring/conditional structure and known card functions before considering contextual benefit. Unknown outgoing text stays protected. Inspiration→Quick Study loses target-player draw even if no targeting need was declared. Divination→Fabricate preserves mana value but loses draw; reject that replacement.
2. **Check final tutor support for every known consumer.** Resolve transmute from its source's printed mana value, not activation cost. Dizzy Spell is MV1 despite its three-mana transmute activation. Count only supported legal target candidates, excluding the source where required; record zero/one/multiple and unknown data. Whole transactions must not remove the final known supported target or reduce a deliberately preserved support count. This concerns static list support, never availability in the library during a game.
3. **Preserve actual cast categories and body contributions.** Vivi counts noncreature casts; Young Pyromancer counts instant/sorcery casts. A passing comparison for those two says nothing about another card that specifically searches for Sorceries. Preserve printed type in the initial proof families; broaden only with a complete supported context check and regression cases. Never turn token-producing text into a printed creature body.
4. **Preserve payment paths separately from produced resources.** Thrill→Demand retains the original discard payment path and adds an artifact option at the same printed mana demand. That may pass this bounded preservation family, but it is not proof the new option is usable or strategically optimal. Village Rites→Deadly Dispute increases upfront mana: its Treasure arrives after costs are paid and cannot finance that same casting. Reject a no-cost-increase proof; evaluate its strategic tradeoff separately.
5. **Keep sacrifice support uncertainty explicit.** Static creature/artifact counts are potential resources, not guaranteed battlefield availability. Tokens, color/type changes and unknown effects mean absence of a listed match usually cannot establish impossibility. A Treasure is an artifact, not automatically a creature for Bombardment. Distinguish an outlet's activation prerequisite from permission to cast the outlet itself. Do not infer that a fallback effect makes a card valuable.
6. **Reject recurring-engine laundering.** Mystic Remora and Phyrexian Arena have timing, repetition and conditions absent from one-shot draw. More immediate cards do not prove the recurring function preserved. A mixed transaction cannot offset one lost engine with an unrelated improved pair or increased aggregate role count.

## Positive and negative test boundaries

The adjacent12 reviewed cases separate bounded rule outcomes from whole-swap authorization. Weave Fate→Quick Study can preserve its supported instant-draw effect while lowering casting demand and adding a Drift MV3 target. The same case still needs checks for other changed-MV consumers in a real deck. Thrill→Demand can preserve the discard path. Conversely, preserving MV membership alone does not permit a draw-to-tutor swap, and preserving two cast-category counts does not permit losing targeted draw or Instant timing.

C6 is explicitly synthetic metadata: no real same-effect MV2 draw card was invented. All named evidence is copied exactly from the17 supplied public Oracle/type/mana records. These are proposed cases, not executed tests. Hard monetary budget, legality, singleton, card count, named locks and transactional integrity remain independent requirements.

## Rejected claims from the draft

Review removed the assertion that complete Commander function preservation is decidable from static text/list, acceptance of Divination→Fabricate based on MV alone, targeting-loss permission based on undeclared demand, and a multi-card acceptance that hid targeting/timing regressions behind aggregate counts. It separated increased casting mana from monetary budget and corrected the suggestion that a spell's newly created Treasure can satisfy that spell's own initial additional cost.

## Receipt

One actual Claude Code session: `--model opus --effort medium`, public-only isolated task, no repository source/private decks/credentials. `opus-public/agent-result.json` reports success, primary `claude-opus-5`, auxiliary Haiku,121721ms. The answer returned inline and is preserved as `opus-public/contextual-review.raw.md`. No production code changed here; the reviewed design supersedes inconsistent draft verdicts.

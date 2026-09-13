# Draw mechanics extraction contract

`intelligence.draw_facts.draw_profile(card)` is a deterministic, name-invariant, bounded Oracle parser. It does not decide whether a card belongs in a deck or simulate game rules. It uses public Oracle text, printed mana cost, mana value and type; unsupported text remains unknown or partial.

## Acceptance contract

- `status=none`: no supported controller draw effect is present; this is not a claim that the card has no other useful abilities.
- `status=unknown`: draw wording is present without an understood controller draw clause.
- `status=supported, confidence=partial`: some fields were extracted, but one or more conditions remain unparsed. Consumers must not count this as verified card advantage.
- `status=supported, confidence=supported`: the supported textual shape and its prerequisite identifiers were extracted. This does **not** guarantee the prerequisites are satisfied, the permanent survives, the opponent cooperates, or the card is a good selection.

`net_cards` measures one draw event minus a mandatory discard and, for immediate spells, the spell itself. Permanent casting costs are not amortized. Sacrifice costs and scaling quantities remain `None`; this is an explicit unknown, not zero. `activation_mana` describes the parsed draw activation only. Every evidence string must be an exact substring of the original Oracle text. Nonfinite mana inputs do not enter the result.

## Supported conditions

Own upkeep; opponent spell casts with optional payment; opponent second draw each turn; the replacement of opponent draws excluding the first draw-step card; creature/typed spell casting; a bounded creature-entry template including Guardian Project's exact unique-name gate; bounded creature-death and combat-damage templates; mana/tap draw activations; charge-counter scaling; elective self targeting; explicit extra creature/artifact sacrifice costs. Idol-style token creation and Atlas-style three lands with the same name are recognized as prerequisites, never assumed satisfied.

Important prerequisite identifiers include `trigger:your_upkeep`, `trigger:opponent_draws_extra_card`, `opponent_may_pay:{1}`, `typal:creature` versus `typal:dragon`, `restriction:nontoken`, `condition:unique_name`, `requires:attached_to_creature`, `cost:sacrifice_creature`, `cost:mana:2`, `cost:tap_self`, `scaling:charge_counters`, `condition:created_token_this_turn` and `condition:three_lands_same_name`.

## Explicit conservative exclusions

Arbitrary triggered conditions, Adventure gating, unparsed tribal death restrictions, hand-size gates, cards without printed casting costs, temporary spell-created triggers, control transfer, returning drawn cards to the library, separate discard clauses, unparsed activation resource costs, and most multi-sentence payment/replacement shapes cannot be verified by this parser. Unsupported does not mean bad: Brainstorm, Glimpse of Nature, Mind's Eye and many other useful cards need additional representations before they can safely count toward a verified draw package.

## Validation and delegation receipt

Claude Code was invoked with `--model opus --effort medium`. The initial sandbox request failed DNS before any model usage. Automatic approval review rejected escalating a repository snapshot because of private-source transfer. The task was then reduced to an approved isolated public-only directory containing 14 public Oracle records and a generic parser assignment, with no repository source or credentials. That session completed successfully; the receipt identifies `claude-opus-5` (plus auxiliary Haiku), 533384 ms, with no web searches. Receipt: `/Users/dylan/Projects/generator-draw-agents/claude-public-parser/agent-result.json`.

Coordinator review corrected the confidence semantics, Insight's imperative draw clause, nonfinite mana handling, exact trigger gating, global restrictions across sentences, elective self targeting, and additional activation prerequisites. A source-text-inspection test was removed in favor of behavioral name invariance. Actual public corpus regressions exposed the initial overconfidence on Brainstorm, Humble Defector, Edgewall Innkeeper, Undead Augur, Mindstorm Crown, Ancestral Vision and Glimpse of Nature; all now remain partial. Thirty-three public fixture records plus synthetic negatives are covered by **235 passing tests** (including parameterized evidence, mutation and rename checks). Focused Ruff checks pass. The parser has not been presented as a complete Magic rules engine.


## Finite resources and expanded counterexamples

An exact printed three-brick starting resource plus a remove-brick draw cost exposes `resource:draw_activations:3`; an exact put-page draw cost plus the printed exile-at-four condition exposes `resource:draw_activations:4`. These are upper bounds shared with other counter-consuming abilities, not guaranteed available activations. The parser preserves both the activation and source/cap text as evidence. A missing matching cap/source remains partial.

The versioned [public negative fixture audit](../draw-selection/public-negative-fixtures.v1.json) records actual Oracle counterexamples for hand-to-library movements, self-return, hand exile, modal additional costs, activation taxes, echo, hand-size reductions and unsupported blight. The asserted outcome is incomplete parser coverage, not poor card quality. This deliberately prevents these cards from receiving invented unconditional draw value.

# Deck constraints and claim validation — coordinator integration

Two source-only modules, no pipeline edits:

* `sabermetrics.intelligence.constraints` — `audit_deck` and `tutor_targets`.
* `sabermetrics.intelligence.review` — `contradictions`, expanded.

Neither module calls a model, the deck builder, or a data store. Both answer
narrow questions about printed data. Silence from either is "no supported rule
fired", never "verified correct".

## `audit_deck(cards, commander) -> [{code, severity, card, message}]`

Severities: `error` (a line this list declares is broken), `warning` (a printed
prerequisite has no match here, but the card stays legal and playable),
`unknown` (supplied data cannot settle it either way).

| Code | Severity | Fires when |
|---|---|---|
| `pact_duplicate_names` | error | A repeat-until-duplicate-name self-exile effect (Tainted Pact shape) **and** a library-empty payoff **and** a repeated card name are all present. |
| `named_search_no_target` | warning | A search for a named type (`a Dragon card`) has no typed entry in the list. |
| `named_search_types_unknown` | unknown | Same search, but entries carry no type line. |
| `transmute_no_target` | warning | Transmute's printed mana value matches no other entry, all mana values known. |
| `transmute_targets_unknown` | unknown | The source or some entries have no mana value data. |
| `sacrifice_color_unproven` | unknown | A colored sacrifice cost, with no entry proven that color and at least one entry of unknown color. |
| `sacrifice_color_unsatisfied` | warning | Same cost, every candidate's colors known, none matching. |

Deliberate non-findings:

* **Repeated basic lands on their own.** Duplicate basic names are legal in
  Commander and a Tainted Pact style card is still a fine dig spell. The audit
  fires only when the list also runs a library-empty payoff (Thassa's Oracle,
  Laboratory Maniac and the like), which suggests a potential full-exile line. Only an explicit
  `pact_library_empty` declaration upgrades this warning to an error.
  The message says the broken thing is the declared line, not deck legality.
* **An optional tutor with no target.** A missing named target is a `warning`
  about an unusable ability, never a ban. Nothing here removes a card.
* **Deck color identity as proof of a card's color.** A "sacrifice a green
  creature" cost is satisfied only by a printed `colors` field, or by colored
  symbols in `mana_cost` on a card without devoid. Otherwise it is `unknown`.
* **A commander of the searched type.** The command zone is not the library, so
  a Dragon commander does not satisfy a search for a Dragon card. The finding
  says so explicitly when it applies.

## `tutor_targets(card, cards) -> {status, targets, limitations}`

`status` is `resolved` (supported shape, `targets` enumerated from this list),
`unknown` (a search clause exists but its shape or the supplied data is not
supported) or `none` (no search or transmute shape found). `targets` are names
in list order; `[]` under `resolved` means this list contains no legal choice.

Transmute searches for the transmuted card's **printed mana value**. The
transmute activation cost is what you pay and is never the searched value: a
printed mana value 1 card cannot find mana value 0 or 3, so Dizzy Spell reaches
Curiosity and Gitaxian Probe, but not Mox Amber or Ophidian Eye. A source card is
excluded from its own target list; it is in hand or on the stack, not in the
library. `limitations` always states what the target list does not prove
(library presence at resolution time, sacrifice prerequisites, zone rules).

## `contradictions(card, reasoning, commander) -> [str]`

Each check compares one explicit claim against one printed field.

| Check | Falsified when |
|---|---|
| Cost phrasing ("a one-mana instant") | Printed mana value differs **and** the card has no Phyrexian or alternative payment. Dismember is exempt here. |
| Explicit mana value ("mana value 1", "its MV is 1", "converted mana cost") | Differs from printed `cmc`/`mana_value`. Payment options never change this: Dismember is mana value 3 even when paid with life. |
| Commander cast trigger | The commander's printed trigger, including its `with mana value N or greater` threshold and its spell-kind restriction, contradicts the claim. A mana value 2 noncreature spell genuinely does not trigger a "3 or greater" commander; a mana value 3 one does. |
| Add one versus doubling | The card prints "that many plus one" and the prose claims doubling, or the card prints "twice that many" and the prose claims one extra. |
| Card type | Prose states a type the printed type line does not carry. A Goblin token in rules text does not make Kathari Bomber (Bird Shaman) a Goblin. |

## Known unknowns (not coverage gaps to hide)

* Multi-face cards are skipped for mana-value claims; prose rarely says which
  face it means.
* A card record without `cmc`/`mana_value` produces no mana-value or cost
  finding at all, rather than treating a missing value as zero.
* Lands are skipped for cast-trigger claims: lands are not cast, and land
  halves of modal cards are not modeled.
* The type vocabulary is a bounded list of card types and common creature
  subtypes. A claim about an unlisted subtype is unknown, not verified.
* Type grants ("becomes a Goblin", changeling) suppress the type check rather
  than guessing at a printed-versus-granted distinction.
* `tutor_targets` supports transmute, exact named-card searches and capitalized named-type searches.
  Generic searches ("a basic land card") and conditional searches return
  `unknown` with the unparsed clause quoted.
* `audit_deck` is not a legality checker, a power estimate, or a claim that an
  unflagged deck is sound. It audits the 99; commander abilities in the command
  zone are out of scope beyond the search-target note.
* Colored sacrifice costs are audited only for nouns that appear in a printed
  type line (creature, artifact, enchantment, land, planeswalker). "Sacrifice a
  green permanent" is not audited rather than guessed at.
* The library-empty payoff detector reads printed win clauses, with a small
  name fallback for records missing oracle text. It is not a closed list of
  every payoff that exists.

## Wiring

1. The experiment runner calls `audit_deck(final_99, commander)` after a build.
   Production diagnostic integration remains future work. Present `error` findings as broken declared lines,
   `warning` as unusable prerequisites and `unknown` as unverified.
2. `contradictions` is already called in the fit-review path; the expanded
   checks need no call-site change. Signature and return type are unchanged.
3. Do not auto-cut cards from findings. A `warning` is evidence for a swap
   decision made elsewhere, not a removal instruction.

Tests: `tests/test_selection_constraints.py`, `tests/test_claim_validation.py`.
These include synthetic cases; card records carry only the printed clauses under test, and
the thresholded commander is a synthetic fixture so a misremembered real card
cannot become the specification. These tests were written in a source-only
session without a shell and have **not been executed here**; the coordinator
runs them.

Coordinator correction: actual catalog Oracle fixtures supersede agent-recalled text. Exact named-card search is supported separately from typal search. Pact/payoff co-presence produces a warning; only an explicit `pact_library_empty` declaration upgrades it to an error.

# Commander contract extraction: receipt and integration contract

`commander_profile(commander)` returns detected tribal, cast-category, token-scaling, defender, mana-value and power-reference contracts. `contribution(card, commander)` returns evidence-backed structural contributions under those scopes, plus printed creature subtypes and cast categories. Both always report `coverage="incomplete"`. Absence of a detected relation is never proof that a replacement is safe.

Each contract has `kind`, `scope`, `requirements`, exact evidence and confidence. Each contribution has `kind`, `scope`, `value`, evidence and confidence. Evidence strings are exact substrings of supplied Oracle text or printed type; mana values come from explicit numeric metadata and remain unknown when missing/nonfinite. Values describe printed relationships, not board-state availability or a win probability.

Supported examples include Lathril's ten-untapped-Elf activation requirement, Krenko's Goblin-count token scaling, Giada's Angel requirements and restricted mana, Vivi's noncreature cast trigger, and Arcades' actual defender requirement. A token producer is distinct from a printed tribal body; Krenko's `:counted_body` and `:token_producer` scopes remain separate. Lands—including creature lands—are never cast. An Angel Kindred spell can match Angel-restricted mana without being an Angel creature body. Defender requires the keyword, not the Wall subtype or an Oracle mention.

The caller must compare all known contributions and preserve existing function/body/cost requirements through its substitution proof. Matching these limited contracts does not prove equivalence. Dynamic power, Lathril's prior-combat-damage token count, activation availability and other unparsed contexts remain partial. Vivi's power dependence is exposed as `power:unparsed_reference`, never simulated. Arcades' toughness-replacement text is not mislabeled as source-power mana.

## Actual Claude session

Claude Code ran with `--model opus --effort medium`, Read/Glob/Grep/Edit/Write only, in `/Users/dylan/Projects/generator-commander-agents/claude-public`. The approved public-only inputs were a generic new-module specification and eighteen public Oracle/type/mana records, with no repository source, private user data or credentials. Receipt: `agent-result.json` in that directory. It reports `is_error=false`, duration312468ms, primary `claude-opus-5` plus auxiliary Haiku. Claude wrote isolated code/tests/receipt and did not run tests or deploy.

Local review removed fixture I/O from the library API; separated front-face types and token-production relationships; prevented casting creature lands; rejected nonfinite and negative mana values; preserved exact defender evidence including case/reminder text; corrected token-count contributions; supported noncreature tribal spell subtypes separately from tribal bodies; and propagated extra trigger gates as partial confidence.

Validation: **57 focused tests passed**, including eighteen public fixture profiles and contributions against all five commanders, exact evidence, rename invariance, typed-body/token separation, negative defender examples, unknown conditions and malformed mana values. Focused Ruff checks pass. No guard, generation pipeline or deployment file was modified by this delegated task.

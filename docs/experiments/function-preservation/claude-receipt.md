# Function facts: delegation and validation receipt

## Contract

`intelligence.card_functions.function_profile(card)` exposes a bounded set of printed mechanical functions. It returns `status`, `coverage`, `functions`, `creature_types`, `evidence`, and `caveats`. Coverage is always `incomplete`. Each function has `kind`, stable `detail`, prerequisite identifiers, exact Oracle evidence, and `confidence` (`supported` or `partial`). Supported means the function was recognized; it does not mean all card text, timing, game-state dependencies or drawbacks were interpreted.

The module can provide evidence that a swap loses interaction, a mana ability, a tutor destination, cost reduction, a token trigger, selection, haste or protection. It does not prove functional equivalence or evaluate replacement quality. Missing functions never demonstrate safe removal. The calling mutation gate must preserve cards whose additional roles remain unknown.

Twenty public fixtures cover the requested losses: Pongify versus Generous Gift target scopes; Young Pyromancer's spell-triggered tokens; Windfall's symmetrical wheel; Elven Ambush's Elf-dependent token count; Elvish Harbinger's Elf-to-library-top tutor and mana ability; Pearl Medallion's white spell cost reduction; Sensei's Divining Top's reorder and self-return; Treasure Cruise and Dig Through Time's graveyard payment support and different card-selection effects. Remaining fixtures cover countering, exile, land ramp, creature mana, equipment protection/haste and draw conditions. No card names are used by the implementation as overrides.

## External session

The requested Claude Code session ran with `--model opus --effort medium`, using only Read/Glob/Grep/Edit/Write tools in `/Users/dylan/Projects/generator-function-agents/claude-public`. Its inputs were a generic new parser assignment and twenty public Oracle records stripped to card name/text/type/mana cost/value. No repository source, private deck data, credentials or production records were supplied. Network access for this public-only session was approved.

Receipt: `/Users/dylan/Projects/generator-function-agents/claude-public/agent-result.json`. The result reports `is_error=false`, duration 503536 ms, primary `claude-opus-5`, auxiliary `claude-haiku-4-5-20251001`, zero web searches. Claude produced the standalone parser, tests and receipt; it did not run tests or deploy.

## Coordinator review

Local integration removed the fixture-loading API and embedded public fixtures in the test module. Review added per-function confidence and unconditional incomplete-coverage metadata; exact original trigger-context evidence; explicit recipient and trigger-scope identifiers; conservative unparsed activation/condition handling; distinction between front-face creature subtypes and token/back-face text; and partial confidence for self-return draw effects. Target-controller replacement tokens remain distinguishable from a controller's token engine.

Validation: **24 focused tests passed**, including loops over all twenty public fixtures, exact-evidence checks, rename invariance, source subtype separation, opponent draw, Adventure gating and complex activation costs. Focused Ruff checks passed. No full Magic rules coverage, strategic equivalence or deployed behavior is claimed by these tests.

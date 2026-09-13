# Ten-commander evaluation — deployment held

Observed ranking: [EDHREC Top Commanders](https://edhrec.com/commanders), September 12, 2026, default displayed ranking. Popularity is not tournament strength. Cases and requested settings are in [evaluation.json](evaluation.json).

All ten commanders produced final decks through real Hugging Face generation in a disposable local database containing the public card corpus. All final lists passed independent count (99 plus commander), stored-catalog legality, color identity, singleton and mainboard-budget checks. Commander purchase cost is outside the existing mainboard budget contract. One sample per setting is insufficient to measure generation variance or competitive strength.

The candidate is **not ready to deploy**. The core-selection repair materially improves Vivi, but shared mana-base selection, dependency feasibility, affordable filler and rules-review grounding still fail the quality bar. Production generator and Deck Lab main/QA were not changed.

| Commander | Requested power | Budget | Mainboard | Seconds | Assessment |
|---|---:|---:|---:|---:|---|
| Y'shtola, Night's Blessed | 2 | $100 | $99.39 | 94.5 | Relevant spells; land drawbacks and false MV claims. |
| The Ur-Dragon | 4 | $1,500 | $749.69 | 80.7 | Dragon core preserved; weak mana-base allocation. |
| Edgar Markov | 3 | $350 | $325.67 | 88.9 | 36 Vampires; off-plan infrastructure and risky lands. |
| Atraxa, Praetors' Voice | 4 | $750 | $420.60 | 78.6 | Counter core preserved; mixed finish plans and false rules prose. |
| Krenko, Mob Boss | 1 | $50 | $50.00 | 62.3 | Goblin core preserved; unacceptable budget filler. |
| Vivi Ornitier | 5 | $5,000 | $4,299.95 | 90.5 | All three curiosity effects; invalid tutor claims remain. |
| Kaalia of the Vast | 3 | $200 | $198.16 | 103.2 | 32 cheat targets; four unresolved choices. |
| Sauron, the Dark Lord | 4 | $1,000 | $575.37 | 121.5 | Recognizable theme; no executable specialized plan. |
| Teval, the Balanced Scale | 3 | $150 | $136.39 | 55.6 | Graveyard detector corrected; mana-base issues remain. |
| Fire Lord Azula | 5 | $2,500 | $2,058.02 | 108.1 | Combo ingredients present; Pact/basic-land constraint violated. |

Times are local end-to-end runs, not production latency measurements. Edgar's first profile response contained malformed JSON; the table shows its successful retry. Teval's table row is a warm-profile rerun after the scoped classification correction; its initial run took 113.7 seconds. Do not compare that rerun directly with cold-profile times.

## Concrete improvements

* Replaced coarse role/price dominance with bounded recall channels and protected strategy ingredients.
* Added attributed EDHREC general/cEDH cohort evidence, conditional casting options, specific capabilities and real review-status provenance.
* Vivi now contains Curiosity, Ophidian Eye, Tandem Lookout, Mox Amber and Quicksilver Elemental. It has 34 noncreature/nonland cards with printed MV0–1, versus five in the previous failed list. Fifty names overlap the owner's benchmark; overlap is not a quality score.
* The native C++ sampler is called from generation and its response is bound to the exact input. Vivi's two ingredient classes appeared together in 19.27%, 27.11% and 36.55% of samples with 7, 10 and 14 cards seen. These are ingredient-access fractions, not castability, combo completion or win probabilities.
* Evaluation caught a new graveyard detector false positive (Bojuka Bog). It was corrected with directional clause tests and Teval was regenerated. The corrected deck has nine supported graveyard-land-access cards and nine self-mill cards. That limited parser still does not claim full rules coverage.

## Required follow-up before release

1. **Mana-base constraints and evidence integration.** Feed the same commander cohort into land scoring; model loss of control, sacrifice checks, untap/upkeep costs, required permanents, fetch targets and basic-type requirements. Tests must reject unsupported fixing claims for Rainbow Vale, Forsaken City, Glimmervoid and Thran Quarry, and evaluate real fetch/basic/shock alternatives within budget. The current direct-color score rewards liabilities and misses the new evidence field.
2. **Executable package constraints.** Validate both required ingredients and forbidden states across the whole deck. Azula's Tainted Pact line conflicts with six Swamps, two Islands and two Mountains. Krenko's Dragon's Herald lacks its named target and necessary sacrifice colors. Tutor matching must use printed MV/type/zone restrictions: Dizzy Spell cannot transmute for Ophidian Eye or Gitaxian Probe. Kaalia needs entering-attacking versus attack-trigger distinctions. Conditional payment options need available resources before contributing to a castability estimate.
3. **Affordable functional completion.** Reserve budget for all required functions and retain viable low-cost alternatives per function. Krenko's Rock Jockey, Goblin Rock Sled, Hedron Scrabbler and unrelated utility artifacts show that preserving a good core does not prevent poor remaining selections. Generic role quotas need archetype-specific replacement rather than further score bonuses.
4. **Typed claims and honest review.** Model output must reference independently checked claims about mana value, types, target sets, trigger conditions and cost availability. Examples that passed current review include Dismember described as MV1 and Kami of Whispered Hopes described as doubling counters. Eighteen cards receive bounded model review per deck; the other 81 are correctly labeled unreviewed. No positive model rating should certify legality or an interaction.
5. **Reliability and provenance.** Retry malformed structured profile output with a bounded policy and validation. Consolidate the legacy `edhrec unavailable` warning with the separately available commander-cohort signal so users can tell which data was used. Provide explicit unsupported-strategy status for commanders such as Sauron. Production configuration must enable the new evidence cache and install/configure the compatible native sampler before a future release.

Acceptance for the next candidate: rerun affected commanders, require zero false deterministic mechanic claims and broken declared package constraints, eliminate known unsupported mana-base assumptions, and inspect all remaining filler. Repeat the full ten-case matrix before any release recommendation. A heuristic bracket match is not proof of competitive strength.

## Validation and reproducibility

* Final Python gate: 1,105 passed, 21 skipped; 54 existing warnings.
* Native sanitizer gate: 132 passed. Python/native binding additionally tested against altered identities, request hashes, dimensions and invalid counts.
* Corrected candidate container built and passed the offline, read-only smoke test, including owner login and installed assets/prompts.
* Focused lint passes. Repository-wide mypy remains report-only: 56 findings versus 57 on the baseline, with no substantive new finding in the new modules.
* Generator implementation commit: `1dfb9a2`, followed by the scoped graveyard correction accompanying this report. Native implementation: `e3b0d5a`.
* Nine configurations evaluated Python source SHA-256 `b9db5e631b3808c635173dbe866fba7d3ecc422df0597792b122fffc06b11ce2`. Corrected Teval evaluated `ebad64f213807b4fbfc9981f0184d96f69ab94335655249a35205a79744508ed`; that change is confined to its graveyard-land-access requirement, which the other nine strategies do not use.
* Public-source-only Claude Opus Medium and Cursor sessions, ownership and coordinator corrections are recorded in [review.md](review.md). Raw local outputs, initial failed attempt and successful retry receipts are retained privately in the infrastructure evaluation directory. No credentials are included in this report.

# Independent helper and substitution review

Cursor ran the authorized source-only task in `generator-creature-agents/cursor`, using the configured Cursor Grok 4.6 High model. The session exited 0; its local receipt is `generator-creature-agents/cursor-result.json`. The helper and tests were integrated after coordinator review. Two optional-result type-narrowing issues were corrected; the helper passed Ruff and isolated mypy.

The helper does not invent missing power/toughness or Oracle fields. Its 33 tests cover printed body resources, tribal distinctions, complete keyword consumption, malformed inputs and unsupported restrictions.

Independent eligibility and substitution review added 27 tests. They cover supplementary-card rejection despite upstream legality flags, final acceptance of card-type eligibility, legitimate main-deck types, damage target scopes, optional kicker/payment routes, unparsed riders, missing body metadata and tribal preservation.

One review test initially failed: increasing a creature from 1/1 to 2/2 incorrectly passed for a commander with a power-1-or-less trigger. The coordinator fixed this by requiring identical printed stats whenever commander or baseline-deck Oracle text references power/toughness. Independent source inspection confirmed both search and final one-to-one transaction matching pass the original baseline as support context.

Final independent validation: **60 tests passed** (33 helper + 27 eligibility/substitution tests). No source files were edited during final freeze review. This confirms the tested restrictions, not complete Magic rules or arbitrary deck synergy coverage.

A subsequent role-persistence review confirmed `_heuristic_role` prioritizes the fully consumed damage family over incomplete cached role facts. That family permits creature targeting (`any target` or `target creature`), so the correction does not relabel player-only burn as removal. The ten targeted classification regressions passed: Shock, Burst Lightning and Play with Fire across absent/empty/utility cached facts, plus a player-only negative. No source changes were made during this review.

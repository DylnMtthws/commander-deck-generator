# External implementation and independent review

Actual requested agent sessions completed successfully:

- Claude Code, Opus Medium: bounded public Oracle function extraction, 20 public
  fixtures and 24 focused tests. Public-only input avoided repository/private data
  transfer. See [Claude receipt](claude-receipt.md). Primary model reported Opus 5,
  with auxiliary Haiku. Local integration hardened incomplete-coverage metadata,
  exact evidence, trigger/cost scope, recipient distinctions and partial confidence.
- Cursor, Grok 4.6 High: strict function/multiset receipts and tests, source-only
  isolated input. Receipt retained privately at
  `generator-function-agents/cursor-result.json`, exit 0. Coordinator review added
  explicit complete-coverage handling: missing metadata stays unknown; recognized
  functions do not certify all functionality. 24 receipt tests, Ruff and isolated
  mypy pass.
- Independent follow-up review identified the commander-sensitive mana-value/color
  issue. The coordinator corrected it; six independent adversarial regressions pass.
  Additional coordinator tests exercise full Oracle consumption, matching, hard
  constraints, protected cards, immutability, unknown effects and real-card examples.

The coordinator implemented substitution proofs and completed-baseline integration.
The experiment runner independently rechecks persisted cards against the internal
baseline and fails on unknown/unproved removals. Historical failed candidates are
retained. No agent output was treated as proof of general Magic intelligence.

No deployment, external messages, credentials in source, or production mutations
were part of this work. Private execution receipts and run databases remain outside
Git. Source and public test fixtures are reviewable in this commit.

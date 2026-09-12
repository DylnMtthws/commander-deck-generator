# Validation and scope — September 12, 2026

This branch implements the first usable vertical from the architecture. It is
not the full multiplayer search system described as the longer-term goal.

## Engineering evidence

- Generator: 978 tests passed, 20 corpus/environment-dependent skips; includes
  native C++ adapter validation. Existing sklearn fixture warnings remain.
- Simulator: all 130 C++ tests passed under ASAN; 55 Python service tests passed,
  including existing routes, resource authorization, malformed compiled input,
  shared capacity, timeout and recovery.
- Offline installed-container smoke passed: packaged templates/prompts/scoring,
  routes, owner login, exclusion of other accounts, session revocation, empty
  corpus and repeatable preparation. No network or production mounts.
- Changed intelligence/cache/rule modules and new tests pass focused Ruff checks.
- Cursor implemented bounded rule-matrix, embedding-cache and evidence-view tasks.
  Coordinator reviewed and amended their code, then implemented selection,
  semantic facts, simulation, integration and acceptance tests. No credentials or
  production user data were supplied to Cursor.

## Measurements

Single local Mac mini observations, not production percentiles or an SLA:

| Experiment | Result | Interpretation |
| --- | --- | --- |
| 220 public cards, 41 rules, reference | 3.031 s | Original nested matching |
| Same cards/rules, accelerated | 0.0295 s | Bit-identical float32 matrix; 99.0% reduction |
| Native resource probe, 20,000 trials | 0.0323 s | Release binary; includes Python launch/result validation |
| Public embedding preparation | 33,188 distinct texts, 38,028 Oracle IDs | Separate persisted cache; explicitly pinned model revision |
| Warm embedding preparation | 33,188 cache hits, zero encodes | Reused by a fresh process |
| Public facts preparation | 117,923 printing rows, 38,660 shapes | Atomic `card-facts.v2` artifact |
| Aang, $1,000, four-mana clones | 103.82 s | 99 cards, $429.78; Spark Double and Sakashima protected |
| Aesi, $200, landfall, cached profile | 51.04 s | 99 cards, $199.77; 41.0 s AI review, 5.81 s optimization |

The Aang clone engine contract was satisfied; its result retained warnings for
missing empirical signals, unresolved reviewed choices and bracket estimation.

The isolated Aesi result satisfied all five landfall requirements and compared
three feasible strategy recipes. It still missed one board-wipe target and had
unresolved reviewed choices. Missing EDHREC/tournament evidence was explicit.
Both conditional lands and modal land faces exceeded the narrow simulation
compiler, so no probe score influenced that build. Requested/estimated bracket
was 3/3, explicitly a heuristic.

A warm local run with network blocked finished in 15.92 s but failed AI review.
That is **not** counted as an accepted speed result. Provider latency remains the
largest measured end-to-end cost. A single observation cannot establish p50/p95.

## Known boundaries and next work

- Facts recognize supported text shapes; they do not implement complete Magic
  rules, costs, target availability, delayed effects or arbitrary interactions.
  Conditional access is not unconditional acceleration; reminder text and quoted
  token rules must not inflate capabilities.
- The landfall plan protects structural requirements, not optimal card choices.
  Printed mana value is an imperfect ranking of activated setup costs. Add typed
  activation/trigger costs and a calibrated action model before broader claims.
- The existing clone contract requires recognizable creature-copy/clone intent.
  The plain phrase “Create copies of Aang and transform them” was reported as
  unverified during acceptance. General intent understanding remains incomplete.
- AI review covers at most 18 risky selections plus 8 separately scored menu
  alternatives. It is not exhaustive. Rejected picks without a constraint-safe,
  independently passing replacement remain flagged.
- The C++ experiment excludes mulligans, all noncommander spells, opponents and
  combat. It currently refuses complex lands. Its value is a tested integration
  and comparison boundary, not arbitrary deck goldfishing or a win predictor.
- Next simulator milestone: versioned conditional/fetch/modal-land primitives,
  followed by typed ramp/draw/landfall spell execution with per-card coverage.
  Only then compare spell packages on measured resources, engine assembly and
  retained interaction. Multiplayer policy/field calibration comes afterward.

Production routing, Main/QA Deck Lab and live generator configuration were not
changed. Review these quality limitations before a production release.

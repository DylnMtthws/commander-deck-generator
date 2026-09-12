# Package 2 — trustworthy profile and narrative

Own reasoning/profiler.py, reasoning/synthesis.py, their prompt files, new grounding
helpers and tests. Do not edit builder, routes, config or global response models
without explaining a necessary interface change to the coordinator.

Override commander_id/name, generated_at (UTC current time), set_version,
user_intent and evidence provenance from application inputs, never setdefault from
model output. Reject/invalidate cached profiles whose canonical identity, set or
metadata is inconsistent; do not reuse the observed legacy invented slug/date.
Validate basic card analysis mana cost/color and oracle-backed facts or derive
these directly. Unknown evidence is unknown: only cite retrieved source IDs.
Remove erroneous CR/flash example. Cache must reuse a valid profile for the same
canonical commander and intent without additional billable calls.

Generate final narrative using actual final-deck facts. Restrict named cards to
final membership or clearly separated suggestions; no absent clone engine claims.
Mechanics must be supported by authoritative supplied facts. A deterministic,
facts-only narrative/weakness summary is explicitly acceptable and recommended
as safe fallback; do not try to promise semantic correctness via regex alone.
Do not invent combos, flying synergies, mana values, extra combats or tokens.
If retaining LLM prose, validate a structured evidence contract and fallback
conservatively on mismatch; retain cost logging for consumed calls.

Tests: hostile model returns wrong ID, old date, wrong set and fabricated source;
canonical values win. Cached malformed legacy profile misses. Correct cache hits.
Final list lacks Spark Double/Sakashima: final prose does not claim they exist.
Brazen Borrower cannot target friendly Aang; Peregrine Drake MV5 is not MV<=4;
Taigam's spell copying isn't extra combats. Empty/name-only facts stay conservative.

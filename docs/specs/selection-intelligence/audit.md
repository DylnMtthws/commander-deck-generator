# Selection audit — coordinator integration

Pure diagnostic helpers live in `sabermetrics.intelligence.audit`. This package
does not edit the deck builder, routes, or templates. The coordinator maps
generation traces into records after a build and attaches the JSON-serializable
summary to intelligence diagnostics for UI evidence.

## `summarize_selection_audit(records) -> dict`

Each record is a dict with `name` (or `card_name`), `stage`, `action`, `reason`,
and optional scores. Only explicit actions `retained` and `excluded` are final
dispositions. Provisional verbs such as `rejected`, `re-admitted`, `placed`,
`protected`, and `flagged` remain in `history` and never become `final_status`.

If a card has traces but no terminal action, `final_status` is `unknown`. The
last explicit `retained`/`excluded` wins among terminal actions; a later
provisional reject does not override a retained decision.

Absence of a card in the record list is **not** evidence it is missing from the
catalog. Empty input yields empty `cards` and zero counts. Do not synthesize
excluded rows for untraced catalog names.

Duplicate events for the same name, including every watchlisted row, are all
kept in `history`. Output shape:

```
{counts: {records, cards, retained, excluded, unknown},
 cards: [{name, final_status, stage, reason, history}]}
```

## `classify_fit_verdict(payload) -> reviewed | unreviewed | unresolved`

A numeric `fit10` / `fit_score` / `llm_fit_score` is not review evidence.
Default optimizer scores, including a 10-point-scale 10, stay `unreviewed`
unless an explicit verdict status or `reviewed` flag is present. Incomplete or
failed reviews (`review_failed`, `verdict_complete=False`, "No verdict
returned.") are `unresolved`.

## Wiring (coordinator)

1. Collect `GenerationTracer` events (already watchlist-filtered, plus
   `force=True` swap/review events). Map to `{name, stage, action, reason, score?}`.
2. Optionally append explicit terminal records for the final 99 (`retained`) and
   known cuts (`excluded`). Do not invent catalog gaps from missing traces.
3. Call `summarize_selection_audit` and attach the dict under intelligence
   diagnostics.
4. When rendering per-card fit, call `classify_fit_verdict` so a default numeric
   score is not labeled as reviewed.

Tests: `tests/test_selection_audit.py` (synthetic records only; no paid builds).

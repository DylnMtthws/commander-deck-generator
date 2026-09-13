# Authorized draw-route release

After reviewing the bounded results, the owner requested commit, push, and
production deployment. The web worker now uses the same combination evaluated
in the primary paired study: draw selection enabled, function preservation
enabled, swap and rebalance policies set to `preserve`, and draw-package policy
set to `routes`. Context-scoped experimental defaults remain unchanged.

This is a release of validated cost/prerequisite checks and role accounting, not
certification of strategic deck quality. The study's unchanged membership,
unverified draw coverage, and score-zero budget fallback remain documented in
[results](results.md). The fallback fix is specified but not included.

The policy change passed the full local suite (2,304 passed, 21 skipped), including
web-worker activation and context restoration on success and failure. Deployment
uses a successful current-main CI image, offline installed-package smoke, encrypted
backup, active-job check, generator-only recreation, and post-release owner/isolation
verification. Deck Lab Main and QA are outside this release's mutation scope.

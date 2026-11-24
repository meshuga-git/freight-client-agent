# Independent safety review

Scope: local synthetic-only prototype, 2026-10-23. No external model calls, real freight data, deployment, or external writes used.

## Verified

`tests/test_independent_safety.py`: **16 passed** at review checkpoint.

- Exact complete source-value, field-label and page grounding: numeric substrings, truncated snippets, missing evidence and empty values rejected.
- Strict grouping, Decimal-safe scalar normalization and compatible physical units.
- Shipment-owner isolation and document lookup fail closed.
- Corrections update normalized values, rerun rules, clear overrides, invalidate confirmation.
- Override reasons required; stale versions rejected.
- Exact-version confirmed exports, identical idempotent replays, conflicting format/version rejected.
- Concurrent same-version reviews yield one success and one conflict.
- US domestic trucking default; incompatible optional profiles rejected.
- API smoke: create 201, foreign owner 404, mismatched profile 422, oversized body rejected (400).

Earlier full-suite checkpoint: **68 passed in 2.43s**. This is test evidence, not extraction-accuracy or legal-compliance evidence.

## Fixed during review

Value-substring and truncated-evidence laundering; wrong-label grounding; malformed numeric grouping; float precision loss; incompatible units; broken correction import/stale normalized values; per-PDF rather than pack cost ledger; page-viewer pixel-cap bypass; request-body bound; profile consistency.

## Limits

Demo credentials are not production authentication. File/page/body/pixel/text bounds are not a malicious-PDF sandbox or decoder CPU timeout; do not expose arbitrary public uploads without isolation. R13 chronology is a demo business heuristic, not a domestic-trucking legal rule. Reference subsets and keyword/lexical screening cannot establish legal compliance. No live LLM cost/latency claim tested; reservations depend on pricing/token estimates.

No remaining blocker identified for local synthetic-only scope.

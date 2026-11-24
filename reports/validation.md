# Verification record

Local Python 3.12 execution; synthetic documents only. No live provider credentials, external accounts, publication, customs filing, or spending was used.

## Passed

- `python -m pytest -q`: **75 passed**, one dependency deprecation warning (FastAPI/Starlette TestClient + httpx). Raw output: `tests.txt`.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- Rule-focused coverage run: 37 rule tests, 100% statements/branches in `rules.py` (not a whole-project coverage claim).
- Real PDF generation, text detection, rendering, merged-document segmentation, exact field/page/value grounding and unit/precision regression tests.
- API authentication/owner isolation, profile consistency, upload rejection, page rendering, review/correction, confirmation invalidation, export idempotency and concurrency tests.
- Streamlit AppTest: create, synthetic PDF intake, processing, populated evidence panel, accept, confirm, export. Disconnected API path handled. `tests/test_ui.py` is reproducible.
- Fifty concurrent full local ingest/render/extract/validate tasks completed, 50 unique records, zero external requests. Wall time about 5.38 seconds; SQLite processing transactions serialize work, so this is not a production scalability claim. See `load_test.json`.
- Eighty-pack corpus generation and ten-pack ground-truth audit: 374 field checks. See `ground_truth_audit.json`.
- Dev and held-out regression evals completed; detailed failures/denominators in `dev.json` and `heldout.json`.

## Measured offline regression, not target claims

Held-out regression (20 synthetic packs): classification **84.62%**, critical extraction **85.21%**, seeded discrepancy recall **100%**, clean-pack false alarms **20%**, clean straight-through **80%**. Zero silent critical errors means no wrong/missing critical field escaped the documented review-routing gate; it does not establish semantic/legal correctness. Offline extraction cost $0. Missing scans are routed to review, not counted as successfully extracted. Several quality targets remain unmet.

The held-out split was inspected and reused after a domestic chronology applicability fix; it is not an untouched benchmark. Fresh independent data is required for a final model-quality claim.

## Not verified / deferred

- Credentialed provider integration and billing: HTTP/schema/retry tests are mocked. A separately reported host-model visual smoke is not an end-to-end API or cost benchmark.
- Chromium screenshot capture was attempted but blocked by sandbox browser socket/setup restrictions; no screenshot or visual-browser pass is claimed. AppTest is functional widget verification, not a pixel-layout assessment.
- Docker is unavailable in this execution environment; Dockerfile/Compose are supplied but not build/run verified.
- No Windows machine was used; PowerShell commands are documented but not executed.
- No manual 10-pack human baseline, reviewer time-saving study, recorded video, hosted demo, PostgreSQL/MinIO adapter or production security/retention validation.

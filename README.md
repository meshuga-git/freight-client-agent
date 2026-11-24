# Meridian Freight Document Validation Agent

A **local, synthetic-only** freight-review prototype for a fictional forwarder. US domestic trucking is the default; explicit international-road, sea and air profiles keep mode-specific checks separate. The workflow is PDF → evidence-linked extraction → deterministic validation → reviewer → confirmed export.

**Not customs software, legal advice or authoritative HS classification. No real client documents, external filings, deployment or TMS writes.**

## Quick start

Python 3.12 is recommended (package minimum 3.11).

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
freight generate --output data/corpus --count 80 --seed 42
uvicorn freight_agent.api:app --host 127.0.0.1 --port 8000
```

In a second activated terminal:

```bash
streamlit run ui.py --server.address 127.0.0.1
```

Open the printed local Streamlit URL. The local reviewer token is `demo-reviewer`. Create a shipment, select the appropriate mode/profile, attest that the PDFs are synthetic, upload a generated pack, then process. Review exceptions against the highlighted source page. Record corrections or reasoned overrides, confirm the current version, then export JSON/CSV or a local mock-TMS receipt.

The default `demo-guest` identity has no shipment access and cannot mutate data. This is a local sandbox identity setup, **not production authentication or a seeded public guest demonstration**. Do not expose either service publicly.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\freight.exe generate --output data/corpus --count 80 --seed 42
.\.venv\Scripts\uvicorn.exe freight_agent.api:app --host 127.0.0.1 --port 8000
# Second PowerShell terminal, same directory:
.\.venv\Scripts\streamlit.exe run ui.py --server.address 127.0.0.1
```

Using the explicit `.venv\Scripts\` executable paths avoids changing PowerShell execution policy.

### Local containers

```bash
docker compose up --build
```

API: `http://127.0.0.1:8000/health`; UI: `http://127.0.0.1:8501`. Compose uses the implemented **SQLite/local-files fallback**, with a persistent volume. It does not pretend PostgreSQL/MinIO adapters exist. A successful source/test run is not evidence that Docker was tested; see verification notes in `reports/`.

## Extraction: two deliberately distinct modes

- **`offline` (default):** deterministic parsing of labels in the actual PDF text layer. It does not read ground-truth JSON and is not described as LLM extraction. Unsupported scans/unknown documents fail closed to review.
- **`vision`:** a configurable OpenAI-compatible model path using page images and strict structured output, without tools or other-shipment context. Credentials are absent in the delivered sandbox, so no paid live-model benchmark is claimed. Even a scan model response cannot independently pass text-layer grounding; review remains required.

For a separately authorized live-provider run, configure the API environment before starting it:

```bash
export FREIGHT_BACKEND=vision
export FREIGHT_LLM_API_BASE=https://api.openai.com/v1
export FREIGHT_LLM_API_KEY='your-secret'
export FREIGHT_LLM_MODEL='your-vision-model'
export FREIGHT_LLM_STRONGER_MODEL='your-retry-model'
```

Do not commit secrets. Model prices, output limits, confidence thresholds and the bounded budget live in `docpipe.Settings`; adjust and verify prices for the selected provider before making cost claims. Setting credentials or enabling this path can cause provider requests and charges; the default does neither.

## Configuration and API

`FREIGHT_RULES_CONFIG` selects a JSON file of rule thresholds and required-document matrix overrides at API startup. Rule explanations are deterministic text; LLM-only rephrasing is deferred.

`FREIGHT_DATA_DIR` selects the local store (default `runtime`). `FREIGHT_TOKENS` is a JSON mapping of bearer tokens to identities, e.g. `{"local-secret":"reviewer"}`. Shipment ownership is checked for reads, images, reviews, confirmation, audit and export. `FREIGHT_API_URL` and `FREIGHT_UI_TOKEN` configure the UI connection. The UI restricts API hosts to local loopback or the Compose `api` service.

Interactive API documentation is at `http://127.0.0.1:8000/docs`.

- `POST /shipments`: synthetic attestation and profile/mode metadata.
- `POST /shipments/{id}/documents`: multipart PDF upload.
- `POST /shipments/{id}/process`: extract and validate the current pack.
- `POST /shipments/{id}/review`: accept/correct a field or override a rule with a reason and current version.
- `POST /shipments/{id}/confirm`: human confirmation for the exact current version.
- `POST /shipments/{id}/exports`: version, format and idempotency key.
- `GET /shipments/{id}/audit`: shipment-scoped audit trail.

Repeated export requests with the same key and snapshot return the same result. Reusing a key for a different request or exporting a stale/unconfirmed version is rejected. Corrections recompute validation and invalidate old confirmation.

Folder intake (each immediate subfolder is a separate synthetic shipment):

```bash
freight import-folder path/to/synthetic-packs --synthetic --data runtime
# Add --watch for a foreground polling loop; Ctrl+C stops it.
```

The basic folder importer uses the default domestic profile; use the API/UI for explicitly configured multimodal packs. IMAP integration is deferred.

## Validation and advisory limits

R01–R16 are deterministic functions with configurable thresholds and applicability. Required documents, consignee, package counts, weights, line quantities, money/currency, dates and duplicates are checked. Container check digits and port checks apply only to appropriate modes. Domestic trucking does not require an Incoterm by default.

Reference data is intentionally a **subset**, not a licensed or complete regulatory database. Unknown-to-subset does not mean legally invalid. Dangerous-goods keywords, HS plausibility, Incoterm charge heuristics and lexical description similarity are advisory signals. CIF/FOB examples are not universal rules about how an invoice must display charges. A lexical description comparator is not claimed to provide general semantic understanding.

## Reproduce tests and evaluation

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
freight eval run --corpus data/corpus --split dev --output reports
freight eval run --corpus data/corpus --split heldout --output reports
```

The corpus has a stable 60/20 dev/held-out split, three synthetic layouts, deliberately degraded scans and adversarial examples. Ground truth is for the evaluator only, never input to the extractor. Reports include classification/field scores, discrepancy recall/precision, clean-pack false alarms, straight-through rate, latency, cost and failures. Re-run after prompt/model/rule changes. Do not tune on held-out failures and continue calling that split unseen; use a fresh independent set for any subsequent final claim.

**Targets are not results.** The requested ≥98% classification, ≥95% critical extraction/recall, ≤10% clean false alarms, zero silent critical errors and ≤$0.15/pack must be judged against actual generated reports. The offline parser's synthetic baseline cannot establish live LLM accuracy, OCR coverage or real-world reliability. Human manual-vs-review time savings have **not been measured**; the UI timer and [study protocol](docs/case-study.md) support collecting honest observations.

## Measured local baseline

The included offline held-out/regression report currently covers 20 synthetic packs: classification **84.62%**, critical-field accuracy **85.21%**, seeded-discrepancy recall **100%**, clean-pack false-alarm rate **20%**, straight-through rate **80%**, and **0** silent critical errors under the report’s definition. Classification, extraction and false-alarm targets are **not met**. Degraded scans fail closed. The split was reused following a domain-applicability correction and is therefore a regression set, **not an untouched held-out benchmark**. See [report](reports/heldout.md) and the JSON denominators/failure list.

Streamlit AppTest exercises create, generated-PDF intake, processing, source/evidence rendering, field acceptance, confirmation and export through the real FastAPI app. A Chromium screenshot was attempted but browser OS socket restrictions prevented startup; an escalation attempt also failed in environment setup. No browser screenshot or visual pixel-level sign-off is claimed.

## Structure

```text
src/docpipe/          reusable PDF/extraction/grounding/normalization core
src/freight_agent/    freight rules, synthetic corpus, eval, API and review store
ui.py                Streamlit side-by-side source/review console
tests/               rule, pipeline and integration checks
reports/             actual evaluation and verification outputs
docs/                architecture, coverage, case study and recording guide
```

See [architecture](docs/architecture.md), [scope matrix](docs/scope-matrix.md), [case study](docs/case-study.md) and [three-minute demo script](docs/demo-script.md).

## Not delivered as production features

PostgreSQL/MinIO adapters, production identity/retention operations, live public hosting, a public repository publication, a recorded video, a human time study, general OCR accuracy, and v1.1 quote/query/HS-suggestion modules are not claimed complete. No accounting project was modified; `docpipe` is the reusable boundary for that future integration. This prototype should not be used to approve actual shipments or determine legal compliance.

# Freight Document Validation Agent


## 1. Overview

**Problem.** Freight forwarders and customs brokers re-key data from bills of lading, invoices, and packing lists, then hunt for mismatches by eye. Errors cause customs holds, demurrage, fines, and rework, on thin margins.

**Solution.** An agent that ingests a shipment's document pack, classifies each document, extracts structured fields with source evidence, cross-validates them with deterministic rules, and hands a reviewer only the exceptions. Clean packs need one-click confirmation.

**Portfolio goal.** Show a grounded, auditable document agent end to end, for a fictional forwarder (Meridian Freight Forwarders, Trucking Industry).

**Non-goals (MVP).** Submitting customs filings, authoritative HS classification, legal or compliance advice, real client documents, training OCR models.

## 2. Scope

| Module | Function | Phase |
|---|---|---|
| Intake and classification | Receive packs, split multi-document PDFs, identify document types | MVP |
| Field extraction | Structured fields with confidence and evidence per field | MVP |
| Cross-document validation | Rule engine producing severity-ranked discrepancies | MVP |
| Review UI and export | Side-by-side viewer, corrections, JSON/CSV export | MVP |
| Carrier quote extraction | Parse quote emails/PDFs, normalize, compare | v1.1 |
| Shipper query drafts | Draft emails for missing documents and discrepancies | v1.1 |
| HS code suggestion | Advisory suggestion with rationale, never auto-applied | v1.1 |

**Document types (MVP):** Bill of Lading or Air Waybill, Commercial Invoice, Packing List, Certificate of Origin.

## 3. Success Metrics

Measured on a synthetic pack set with known ground truth (section 9). Targets:

- Document classification accuracy ≥ 98%
- Critical-field extraction accuracy ≥ 95% (exact match after normalization)
- Recall on seeded discrepancies ≥ 95%; false-alarm rate ≤ 10% of clean packs
- Silent critical errors (wrong value, no flag raised): 0 on the held-out set
- Straight-through rate on clean packs (reviewer only confirms) ≥ 60%
- Latency ≤ 60 s per pack; cost ≤ $0.15 per pack
- Time-saving claim: time yourself manually checking 10 packs, report that baseline against reviewer time in the UI

## 4. Architecture

**Flow:** Intake → file normalization → classifier → extractor → normalizer → validation engine → review queue → export, with an audit log across all steps.

| Component | Choice |
|---|---|
| Intake | Email inbox (IMAP), drag-and-drop upload, watched folder |
| File handling | PyMuPDF for page rendering and text-layer detection; originals stored unchanged in S3-compatible storage (MinIO locally) |
| LLM | User-configurable 
| Backend | Python 3.12, FastAPI, Pydantic, async worker |
| Database | Postgres |
| Reference data | Incoterms 2020, ISO 3166 countries, ISO 4217 currencies, UN/LOCODE subset, HS chapter list, ISO 6346 container check-digit logic |
| UI | Streamlit or React: document viewer beside extracted fields, evidence highlighted |
| Observability | Structured logs, trace ID per pack, token and cost counters per document |
| Deployment | Docker Compose; hosted demo with synthetic data only |

**Design principles**

1. The model reads; code decides. Extraction uses the LLM, validation uses deterministic rules.
2. Every extracted value carries evidence (page and verbatim snippet) that is checked against the source.
3. Documents are untrusted input. Text inside them is data, never instructions.
4. No silent changes: every normalization and correction is logged.
5. Nothing is exported without human confirmation. On any failure, fail closed to review.
6. Build the intake, extraction, and review core as a reusable package (docpipe) so an accounting agent can share it.

## 5. Agent Workflow

1. **Ingest.** Create a shipment record, store originals, render pages, detect text layer or scan.
2. **Split and classify**: segment multi-document PDFs, label each document with type and confidence. Unknown or low-confidence documents go to review.
3. **Extract** (vision, no tools): one schema per document type; returns per field value, confidence, page, and evidence snippet. Text-layer documents also get a grounding check: the evidence must appear in the extracted text, otherwise the field is flagged.
4. **Retry.** Documents with low-confidence critical fields are re-extracted once with a stronger model; cost is logged.
5. **Normalize.** Dates to ISO 8601, weights to kg, volumes to m³, countries and currencies to ISO codes, ports to UN/LOCODE, names and addresses canonicalized for matching. Raw and normalized values are both stored.
6. **Validate.** Run the rule engine across the pack (section 6) and the required-documents matrix.
7. **Explain.** The LLM phrases each discrepancy in plain language using only the rule output and evidence. It never decides severity.
8. **Review.** Reviewer sees exceptions first, with source highlights; accepts, corrects, or overrides with a reason.
9. **Export.** After confirmation, produce JSON and CSV of the validated shipment record, plus a mock push to a TMS endpoint. Exports are idempotent.

**Pack status:** Clean (no flags), Needs review (any Major), Blocked (any Critical). Minor items are noted only.

**Required-documents matrix** (config): by mode, direction, incoterm, and destination, lists mandatory documents. Example: all packs need B/L or AWB, invoice, and packing list; Certificate of Origin required where the destination config says so.

## 6. Validation Rules

| ID | Check | Severity |
|---|---|---|
| R01 | Required documents present per matrix | Critical |
| R02 | Consignee present and consistent across B/L and invoice (fuzzy match ≥ 0.9) | Critical |
| R03 | Package count equal between B/L and packing list | Critical |
| R04 | Container number valid under ISO 6346 check digit | Critical |
| R05 | Country of origin consistent between invoice and Certificate of Origin | Critical |
| R06 | Restricted-goods and dangerous-goods keyword screen (configurable list, advisory) | Critical |
| R07 | Gross weight between B/L and packing list within ±1% | Major |
| R08 | Invoice line quantities reconcile with packing list | Major |
| R09 | Invoice total equals sum of lines; single consistent currency | Major |
| R10 | Incoterm valid and consistent with charges (for example CIF implies insurance; FOB should not carry freight) | Major |
| R11 | HS code format valid (6 to 10 digits) and plausible for the goods description | Major |
| R12 | Ports valid UN/LOCODE and consistent across documents | Major |
| R13 | Dates logical: invoice date ≤ on-board date ≤ ETA | Major |
| R14 | Goods description consistent between B/L and invoice (semantic comparison, flagged only above a mismatch threshold) | Major |
| R15 | Duplicate B/L or invoice number already in system | Major |
| R16 | Seals and shipping marks consistent | Minor |

Each rule is a pure function with a unit test per branch. Thresholds live in config.

## 7. Data Model

| Table | Key fields |
|---|---|
| shipments | id, mode, direction, incoterm, status, created_at |
| documents | id, shipment_id, type, type_confidence, storage_ref, page_range |
| pages | id, document_id, number, has_text_layer, image_ref |
| extractions | id, document_id, field, raw_value, normalized_value, confidence, page, evidence, grounded, model, version |
| validations | id, shipment_id, rule_id, severity, status, details, evidence_refs |
| reviews | id, shipment_id, field_or_rule, action, old_value, new_value, reason, reviewer, ts |
| exports | id, shipment_id, format, idempotency_key, payload_hash, ts |
| audit_log | id, shipment_id, step, input_hash, output_ref, model, cost, trace_id, ts |
| reference_data | type, code, label, metadata |
| eval_packs | id, generator_seed, ground_truth, seeded_errors, split |
| eval_runs | id, git_sha, metrics, ts |
| quotes, quote_lines (v1.1) | id, carrier, lane, validity, charges, currency, transit_time |

## 8. Guardrails

- **Prompt injection.** Extraction calls have no tools and no access to other shipments. The system prompt marks document content as untrusted data. Adversarial documents are part of the eval set.
- **Grounding.** A value whose evidence is not found in the source is flagged and cannot pass validation as confident.
- **Confidence handling.** Low-confidence critical fields are highlighted and require reviewer confirmation.
- **Human control.** No export or external write without confirmation; overrides need a reason and are audited.
- **Advisory limits.** HS suggestions, screening, and the dangerous-goods check are advisory. The UI states that they are not compliance advice.
- **Data handling.** Synthetic data only in the portfolio; per-shipment access control; configurable retention; secrets in environment variables; PII and commercial data redacted in logs.
- **Reliability.** Retries with backoff, timeouts, per-pack cost cap, idempotent exports, fail closed to review.

## 9. Evaluation

**Dataset.** Generate packs with a script: Jinja2 templates rendered to PDF (three layouts per document type, varied fonts and formats), producing ground-truth JSON automatically. Create 80 packs (about 300 documents):

- 40 clean packs
- 40 packs with 1 to 3 seeded errors (weight off by 5%, package count off by one, wrong container check digit, origin mismatch, missing document, date inversion, currency mismatch, and so on)
- 15 of the 80 degraded as scans (rotation, noise, low DPI)
- 5 adversarial packs (injected instructions in text, blank pages, several documents merged in one PDF, wrong language, duplicate B/L)

Split 60 dev / 20 held-out; do not tune on held-out. Use only templates you create; no real shipping documents.

**Harness.** One CLI command (eval run) reports per-document-type classification accuracy, per-field extraction accuracy, per-rule recall and precision, false-alarm rate, straight-through rate, latency, and cost; it prints a failure list and stores results in eval_runs. Run it on every prompt, model, or rule change.

**Reporting.** Publish failures and limits in the README, including that results come from synthetic documents.

## 10. Implementation Plan


**Phase 0: Foundation**

1. Set up repo, environment, Docker Compose (app, Postgres, MinIO), linting, CI with tests. *Exit:* docker compose up serves a health endpoint.
2. Build a SDK wrapper with retries, timeouts, token and cost logging, and model names from config. *Exit:* a test call logs its cost.

**Phase 1: Reference data and synthetic packs**

3. Load reference data (Incoterms, ISO codes, UN/LOCODE subset, HS chapters); implement the ISO 6346 check-digit function with tests.
4. Define Pydantic schemas for the four document types.
5. Build document templates (three layouts each) and the pack generator that writes PDFs plus ground truth.
6. Build the error injector and scan degrader. *Exit:* 80 packs generated and spot-checked by eye; ground truth verified on 10 packs.

**Phase 2: Ingestion and classification**

7. Implement upload and folder intake, page rendering, text-layer detection, and storage.
8. Implement multi-document PDF splitting and a classifier. *Exit:* classification accuracy ≥ 98% on dev set.

**Phase 3: Extraction**

9. Write extraction prompts and structured outputs per document type, with confidence, page, and evidence.
10. Implement the grounding check and the normalizer, with unit tests.
11. Build the eval harness for extraction and record a baseline. *Exit:* critical-field accuracy ≥ 95% on dev set, or documented fixes in progress.
12. Add the low-confidence retry with a stronger model; measure its cost impact.

**Phase 4: Validation engine**

13. Implement rules R01–R16 as pure functions with unit tests per branch.
14. Implement the required-documents matrix and pack status logic.
15. Implement the discrepancy explainer (LLM phrasing only). *Exit:* recall ≥ 95% on seeded errors, false alarms ≤ 10%.

**Phase 5: Review UI and export**

16. Build the viewer with side-by-side document and fields, evidence highlighting, and an exceptions-first list.
17. Implement accept, correct, and override with reasons; write all changes to reviews and audit_log.
18. Implement the JSON/CSV export and mock TMS push with idempotency keys. *Exit:* a clean pack goes from upload to export in under two minutes of reviewer time.

**Phase 6: Hardening**

19. Run the held-out eval; fix failures; freeze and tag prompt and rule versions.
20. Run the adversarial packs and a load test of 50 concurrent packs; verify retries and cost caps. *Exit:* 0 silent critical errors on held-out, targets in section 3 met or gaps documented.

**Phase 7: v1.1 modules**

21. Carrier quote extraction: parse quote emails and PDFs into quote_lines, normalize charges and currency, and show a side-by-side comparison per lane.
22. Shipper query drafts: generate emails requesting missing documents or clarifying discrepancies, always shown for approval, never auto-sent.
23. HS suggestion: advisory suggestion with rationale, shown separately from extracted values. Give each module a 20-case mini eval.

**Phase 8: Packaging**

24. Deploy the demo with seeded synthetic packs and a read-only guest login; no real credentials.
25. Produce the architecture diagram, README (problem, results, limitations), and a 3-minute demo video that shows a catch-the-mismatch scenario.
26. Write a one-page case study with measured time-per-pack comparison, stating that it uses simulated data.

## 11. Portfolio Deliverables

- Public repo with README and architecture diagram
- Live demo with guest access
- 3-minute demo video built around one caught discrepancy
- Eval report (per-field accuracy, per-rule recall, failure analysis)
- One-page case study
- Reusable docpipe package, referenced from the accounting agent project

## 12. Risks

| Risk | Mitigation |
|---|---|
| Synthetic documents too clean, inflating results | Scan degradation, varied layouts, adversarial packs, held-out set, disclose limits |
| Plausible but wrong extracted values | Evidence grounding, confidence flags, deterministic cross-checks |
| Rule false alarms annoy reviewers | Tunable thresholds, severity tiers, track false-alarm rate as a metric |
| Compliance overreach | Advisory labels, no filing, human confirmation required |
| Cost on multi-page scans | Retry only when needed, per-pack cost cap |
| Scope creep | v1.1 modules start only after MVP exit criteria |

## 13. Assumptions and Open Decisions

- Fictional forwarder; English-language documents only in MVP.
- Streamlit is the default UI;
- Trucking is the primary flow.
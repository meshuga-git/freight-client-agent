# Three-minute local demo recording guide

This is a script, not a recorded video. Use synthetic PDFs only.

**0:00–0:25 — Problem and scope.** Show the Meridian header. Explain that re-keying freight packs produces mismatches. State that the demo is synthetic, local and not compliance advice. Show the selected extraction backend; offline mode is a deterministic parser, not an LLM.

**0:25–0:55 — Intake.** Create a road shipment, attest synthetic data, upload its generated B/L, invoice and packing list, then process. Show that road noncontainer rules skip ocean-only applicability rather than inventing a container requirement.

**0:55–1:35 — Catch a mismatch.** Select a generated pack with a seeded package-count or weight discrepancy. Show the failing rule's severity, both source documents, the page rendering and exact evidence snippet. If using an unsupported scan, show that it fails closed instead of claiming to have read it.

**1:35–2:10 — Reviewer control.** Correct the deliberately wrong field with a reason after comparing the source. Show recomputed rules, new version and audit entry. Explain that a correction is not a silent rewrite. Demonstrate that an override is separately recorded and requires a reason.

**2:10–2:40 — Confirmation and export.** Confirm the current version, create a JSON or CSV export, then repeat the request to demonstrate idempotency. Point out that mock TMS is only a local receipt. No customs filing or external account is touched.

**2:40–3:00 — Honest results.** Open the actual report under `reports/`, quote its denominator and backend, and show failures. Say that model/scan performance and human time savings remain unproven until the corresponding studies run. Do not substitute target values for measurements.

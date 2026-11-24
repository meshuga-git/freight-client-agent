# Architecture and trust boundaries

```mermaid
flowchart LR
  U[Local reviewer / synthetic PDFs] --> A[FastAPI · shipment-scoped authorization]
  A --> S[SQLite + unchanged original files]
  A --> P[Reusable docpipe]
  P --> N[PDF limits · text detection · render · split]
  N --> E{Explicit extraction backend}
  E --> O[Offline deterministic label parser]
  E --> V[Configured vision model · no tools]
  O --> G[Schema · normalization · evidence checks]
  V --> G
  G --> R[Pure deterministic R01–R16 + extraction safety flags]
  R --> Q[Streamlit exceptions + source evidence]
  Q --> H[Reasoned review / correction / override]
  H --> R
  R --> C[Version-bound human confirmation]
  C --> X[Idempotent JSON / CSV / local mock TMS]
  A --> L[Audit records / trace IDs]
```

## Boundaries

- **Documents are data, never instructions.** The model has no tools or cross-shipment retrieval. Model output is not authority to export or change rule severity.
- **Extraction is not validation.** Docpipe preserves evidence and raw/normalized values. R01–R16 make deterministic comparisons; a plausible value is not automatically grounded.
- **Human control is versioned.** Corrections rerun validation and invalidate confirmation. Overrides preserve the original discrepancy and require a reason. Export is blocked until the exact current version is confirmed.
- **Local synthetic sandbox.** SQLite and a local original/render store are the implemented fallback. PostgreSQL/MinIO are architectural targets, not equivalent adapters merely because containers can start. No external TMS or customs endpoint is called.
- **Reference subsets are not authorities.** Unlisted codes require verification; they are not automatically legally invalid. HS checks and dangerous-goods screening are advisory. Road shipments do not inherit ocean-only container/port assumptions.

## Reuse boundary

`src/docpipe` is independent of shipment review and export: PDF processing, schema enforcement, extraction backends, evidence checks and normalization. A future accounting agent can depend on it without importing freight rules. Accounting integration is not implemented in this project.

# Specification coverage and explicit limits

Status describes implementation scope, not proof that a numerical target has passed. Consult `reports/` and test output for measured results.

| Spec area | Delivery | Qualification / next gate |
|---|---|---|
| Synthetic PDF intake | Local API upload + Streamlit upload | No real client documents; IMAP mailbox integration is deferred |
| Original storage | Unchanged local files | MinIO production adapter deferred |
| Persistence | SQLite local fallback | PostgreSQL production adapter deferred; not advertised as tested |
| PDF text/rendering | PyMuPDF | Resource limits; encrypted/malformed/unsupported files must fail closed |
| Document types | B/L, AWB, invoice, packing list, certificate of origin | English-language synthetic corpus; unknowns routed to review |
| Merged PDFs | Title/page segmentation | Arbitrary intra-page or unlabeled document boundaries are not guaranteed |
| Offline extraction | Actual text-label parser | Clearly marked deterministic demo; not a model or general OCR |
| Vision extraction | Configurable provider path | No credentials supplied; live provider quality/cost not established |
| Grounding and normalization | Source evidence + raw/normalized fields | Grounding supports a claim, not truth of the source; scan grounding needs human review |
| Retry/cost protection | Bounded configured path | Provider prices must match chosen model; unmeasured live cost cannot be claimed |
| R01–R16 | Pure deterministic rules and explanations | Applicability config, reference subsets, lexical R14 rather than unrestricted semantic understanding; LLM rephrasing deferred |
| Incoterms/HS/DG | Configurable advisory checks | No authoritative classification, compliance clearance or legal interpretation |
| Review | Source side-by-side, accept/correct/override | Reason required; stale versions rejected; local sandbox authorization only |
| Export | Confirmed JSON/CSV/local mock TMS | No external writes, filings or production TMS integration |
| Corpus | 80 generated synthetic packs | Three layouts; degraded scans/adversarial cases; ground truth separate from extraction |
| Evaluation | Reproducible offline report | Targets are not guarantees; scans should reduce coverage rather than silently pass |
| Human time baseline | Timing controls + study protocol | No fabricated 10-pack manual study or time-saving claim |
| Container packaging | Dockerfile + local Compose | Build/run verification is reported separately; no hosted deployment |
| v1.1 quotes/query/HS suggestions | Deferred | MVP quality gates first; no claim of 20-case mini-evals |
| Public repo/live demo/video | Source + demo recording script | Publication, hosted deployment and video recording not performed |
| Accounting reuse | Reusable `docpipe` source | No existing accounting project modified |

## Important MVP gaps

A synthetic offline parser baseline does not meet the spec's intended LLM extraction demonstration by itself. A credentialed vision evaluation, real-world-style document variability, reviewer usability sessions, production identity management, robust database/object storage adapters, and deployment review remain separate gates. The project intentionally does not spend money, connect accounts, file customs documents, or publish a public endpoint.

# Available-host vision smoke methodology

## Result and scope
Direct pixel inspection produced all seven requested fields on each of two synthetic single-page invoice images. Both visibly identify themselves as fictional/synthetic. This is a smoke test of the vision reasoning available in this assistant session, not a deployed model API integration test, representative corpus evaluation, benchmark, or proof that any production accuracy target is met.

## Inputs and isolation
Only these images were inspected with view_image:
- reports/text-invoice.png
- reports/scan-invoice.png

No source code, labels, corpus truth, other files, OCR scripts, or external services were inspected or used to derive predictions. Image contents were treated as untrusted document data, not instructions.

## Extraction
The assistant read the actual displayed pixels and transcribed visible field snippets. Each prediction includes raw and normalized values, page 1, verbatim visible evidence, and a subjective confidence score. Numeric fields were normalized to JSON numbers; the date retained its visible ISO form; document type was normalized to commercial_invoice. Missing fields would be null; none of the requested fields was missing.

## Limitations
Confidence scores are subjective and not calibrated. Only two synthetic pages were observed, including one degraded scan-like image. No independent truth comparison was performed in this blind extraction step. No conclusion about production accuracy, generalization, latency, cost, OCR robustness across a corpus, or model API wiring follows from this result. The exact backend model identity was not independently verified.

## Blockers
None for the assigned direct-pixel extraction and artifact-writing task.

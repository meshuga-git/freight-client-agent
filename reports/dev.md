# Synthetic evaluation
Backend: **offline**. Split: **dev**. Packs: 60.

| Metric | Measured |
|---|---|
| classification_accuracy | 0.8 |
| critical_field_accuracy | 0.8079625292740047 |
| seeded_recall | 0.9166666666666666 |
| false_alarm_rate | 0.26666666666666666 |
| straight_through_rate | 0.7333333333333333 |
| silent_critical_errors | 0 |

## Limitations
- Offline backend is a deterministic template demonstration, not an LLM; scans must fail closed.
- Rule precision is a seeded-error proxy: collateral mismatches and missing-field flags count as false positives unless explicitly seeded.
- Silent critical errors count wrong/missing critical fields in packs that were not routed to review, not independently verified semantic confidence.
- Clean means no seeded validation mismatch; degraded or adversarial clean packs remain in false-alarm denominators.
- Human manual baseline and reviewer time have not been measured; no time-saving claim.
- Held-out split was inspected, then reused after a domain applicability correction to date rules; this is a regression split, not an untouched benchmark. No external data or legal classification accuracy is established.

Full per-field/per-rule denominators and 492 failures: `dev.json`.

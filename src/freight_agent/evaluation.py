"""Evidence-independent scoring: only this module reads ground truth after extraction."""

from __future__ import annotations
import json
import dataclasses
import hashlib
import statistics
import subprocess
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .corpus import CRITICAL_FIELDS


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if value is None:
        return None
    text = str(value).strip()
    try:
        return str(Decimal(text).normalize())
    except InvalidOperation:
        return " ".join(text.casefold().split())


def _ratio(n, d):
    return None if not d else n / d


def evaluate(
    corpus_dir: Path | str, output: Path | str, split="heldout", backend="offline", settings=None
):
    from docpipe import process_pdf
    from docpipe.pipeline import Settings
    from .rules import validate

    corpus_dir, output = Path(corpus_dir), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    classification = defaultdict(lambda: {"correct": 0, "total": 0})
    fields = defaultdict(lambda: {"correct": 0, "total": 0})
    rule_stats = {f"R{i:02}": {"tp": 0, "fp": 0, "fn": 0} for i in range(1, 17)}
    failures = []
    pack_results = []
    latencies = []
    costs = []
    silent = 0
    critical_total = 0
    critical_correct = 0
    clean_count = 0
    clean_flags = 0
    straight = 0
    for pack in manifest["packs"]:
        if split != "all" and pack["split"] != split:
            continue
        pack_settings = (
            dataclasses.replace(settings, budget={"cost": 0.0})
            if isinstance(settings, Settings)
            else Settings(**{**(settings or {}), "budget": {"cost": 0.0}})
        )
        start = time.perf_counter()
        documents = []
        extraction_errors = []
        # Extractor receives only the PDFs, never manifest truth fields or seeded errors.
        for filename in pack["files"]:
            try:
                extracted = process_pdf(
                    corpus_dir / pack["id"] / filename, backend=backend, settings=pack_settings
                )
                for doc in extracted:
                    doc["_eval_file"] = filename
                documents.extend(extracted)
            except Exception as exc:
                extraction_errors.append(type(exc).__name__)
        truth = json.loads(
            (corpus_dir / pack["id"] / "ground_truth.json").read_text(encoding="utf-8")
        )
        validations = validate(
            documents,
            pack["shipment"],
            history=truth.get("history", []),
            config={"coo_destinations": ["CA"]},
        )
        failed = {r["rule_id"] for r in validations if r["status"] == "fail"}
        issues = [issue for doc in documents for issue in doc.get("issues", [])]
        quality_flags = bool(
            extraction_errors
            or issues
            or any(
                d.get("type_confidence", 0) < 0.8
                or d.get("type") == "unknown"
                or any(
                    not f.get("grounded", False) or f.get("confidence", 0) < 0.8
                    for f in d.get("fields", {}).values()
                    if isinstance(f, dict)
                )
                for d in documents
            )
        )
        review_required = quality_flags or any(
            r["status"] == "fail" and str(r["severity"]).lower() in {"critical", "major"}
            for r in validations
        )
        pack_failures = []
        for expected in truth["documents"]:
            candidates = [
                d
                for d in documents
                if d.get("_eval_file") == expected["file"]
                and expected["page"] in [p.get("number") for p in d.get("pages", [])]
            ]
            actual = next(
                (d for d in candidates if d.get("type") == expected["type"]),
                candidates[0] if candidates else {},
            )
            c = classification[expected["type"]]
            c["total"] += 1
            c["correct"] += actual.get("type") == expected["type"]
            if actual.get("type") != expected["type"]:
                pack_failures.append(
                    {
                        "kind": "classification",
                        "file": expected["file"],
                        "page": expected["page"],
                        "expected": expected["type"],
                        "actual": actual.get("type"),
                    }
                )
            for name, wanted in expected["fields"].items():
                entry = actual.get("fields", {}).get(name, {})
                observed = entry.get("value") if isinstance(entry, dict) else entry
                correct = _canonical(observed) == _canonical(wanted)
                stat = fields[name]
                stat["total"] += 1
                stat["correct"] += correct
                if name in CRITICAL_FIELDS:
                    critical_total += 1
                    critical_correct += correct
                    if not correct and not review_required:
                        silent += 1
                if not correct:
                    pack_failures.append(
                        {
                            "kind": "field",
                            "file": expected["file"],
                            "field": name,
                            "expected": wanted,
                            "actual": observed,
                        }
                    )
        seeded = set(truth["seeded_errors"])
        for rule in rule_stats:
            rule_stats[rule]["tp"] += rule in failed and rule in seeded
            rule_stats[rule]["fp"] += rule in failed and rule not in seeded
            rule_stats[rule]["fn"] += rule not in failed and rule in seeded
        if pack["clean"]:
            clean_count += 1
            clean_flags += review_required
            straight += not review_required
        for missed in sorted(seeded - failed):
            pack_failures.append({"kind": "missed_seeded_rule", "rule_id": missed})
        latency = time.perf_counter() - start
        cost = sum(float(d.get("usage", {}).get("cost", 0)) for d in documents)
        latencies.append(latency)
        costs.append(cost)
        result = {
            "id": pack["id"],
            "scan": pack["scan"],
            "adversarial": pack["adversarial"],
            "clean": pack["clean"],
            "seeded": sorted(seeded),
            "detected": sorted(failed),
            "review_required": review_required,
            "extraction_errors": extraction_errors,
            "latency_seconds": latency,
            "cost_usd": cost,
            "failure_count": len(pack_failures),
        }
        pack_results.append(result)
        failures.extend(dict(pack_id=pack["id"], **failure) for failure in pack_failures)
    for stat in classification.values():
        stat["accuracy"] = _ratio(stat["correct"], stat["total"])
    for stat in fields.values():
        stat["accuracy"] = _ratio(stat["correct"], stat["total"])
    for stat in rule_stats.values():
        stat["precision"] = _ratio(stat["tp"], stat["tp"] + stat["fp"])
        stat["recall"] = _ratio(stat["tp"], stat["tp"] + stat["fn"])
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = "uncommitted"
    doc_count = sum(s["total"] for s in classification.values())
    tp = sum(s["tp"] for s in rule_stats.values())
    fn = sum(s["fn"] for s in rule_stats.values())
    report = {
        "schema_version": 1,
        "source_sha256": {
            str(p.relative_to(Path(__file__).parents[1])): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in [
                Path(__file__),
                Path(__file__).with_name("rules.py"),
                Path(__file__).with_name("corpus.py"),
                Path(__file__).parents[1] / "docpipe" / "pipeline.py",
            ]
        },
        "manifest_sha256": hashlib.sha256((corpus_dir / "manifest.json").read_bytes()).hexdigest(),
        "git_sha": git_sha,
        "timestamp": time.time(),
        "backend": backend,
        "split": split,
        "synthetic_only": True,
        "pack_count": len(pack_results),
        "document_count": doc_count,
        "classification_accuracy": _ratio(
            sum(s["correct"] for s in classification.values()), doc_count
        ),
        "classification_by_type": dict(classification),
        "extraction_by_field": dict(fields),
        "critical_field_accuracy": _ratio(critical_correct, critical_total),
        "critical_fields_total": critical_total,
        "seeded_recall": _ratio(tp, tp + fn),
        "per_rule": rule_stats,
        "clean_pack_count": clean_count,
        "false_alarm_rate": _ratio(clean_flags, clean_count),
        "straight_through_rate": _ratio(straight, clean_count),
        "silent_critical_errors": silent,
        "latency_seconds": {
            "mean": statistics.mean(latencies) if latencies else None,
            "max": max(latencies, default=None),
        },
        "cost_usd": {"sum": sum(costs), "max": max(costs, default=None)},
        "packs": pack_results,
        "failures": failures,
        "limitations": [
            "Offline backend is a deterministic template demonstration, not an LLM; scans must fail closed.",
            "Rule precision is a seeded-error proxy: collateral mismatches and missing-field flags count as false positives unless explicitly seeded.",
            "Silent critical errors count wrong/missing critical fields in packs that were not routed to review, not independently verified semantic confidence.",
            "Clean means no seeded validation mismatch; degraded or adversarial clean packs remain in false-alarm denominators.",
            "Human manual baseline and reviewer time have not been measured; no time-saving claim.",
            "Held-out split was inspected, then reused after a domain applicability correction to date rules; this is a regression split, not an untouched benchmark. No external data or legal classification accuracy is established.",
        ],
    }
    (output / f"{split}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (output / "eval_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report) + "\n")
    rows = [
        "# Synthetic evaluation",
        f"Backend: **{backend}**. Split: **{split}**. Packs: {len(pack_results)}.",
        "",
        "| Metric | Measured |",
        "|---|---|",
        *[
            f"| {key} | {report[key]} |"
            for key in (
                "classification_accuracy",
                "critical_field_accuracy",
                "seeded_recall",
                "false_alarm_rate",
                "straight_through_rate",
                "silent_critical_errors",
            )
        ],
        "",
        "## Limitations",
        *[f"- {item}" for item in report["limitations"]],
        "",
        f"Full per-field/per-rule denominators and {len(failures)} failures: `{split}.json`.",
    ]
    (output / f"{split}.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return report

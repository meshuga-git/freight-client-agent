"""50 concurrent full local ingest/process tasks; not a production capacity claim."""

import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from freight_agent.service import Store


def main():
    root = Path(__file__).resolve().parents[1]
    corpus = root / "data" / "corpus"
    manifest = json.loads((corpus / "manifest.json").read_text())
    pack = next(
        p for p in manifest["packs"] if p["clean"] and not p.get("scan", p.get("degraded", False))
    )
    inputs = [(name, (corpus / pack["id"] / name).read_bytes()) for name in pack["files"]]
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)

        def run(index):
            started = time.perf_counter()
            actor = f"load-{index}"
            state = store.create(actor, {"synthetic": True})
            for name, data in inputs:
                store.add_upload(state["id"], actor, name, data)
            state = store.process(state["id"], actor)
            return {
                "id": state["id"],
                "processed": state["processed"],
                "status": state["status"],
                "seconds": time.perf_counter() - started,
                "cost": sum(d.get("usage", {}).get("cost", 0) for d in state["documents"]),
            }

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=50) as pool:
            results = list(pool.map(run, range(50)))
        report = {
            "tasks": 50,
            "concurrency": 50,
            "scope": "Full local SQLite/files/offline ingest-render-extract-validate; transactions serialize processing, not production throughput",
            "elapsed_seconds": time.perf_counter() - start,
            "completed": sum(r["processed"] for r in results),
            "unique_ids": len({r["id"] for r in results}),
            "external_calls": 0,
            "results": results,
        }
    (root / "reports" / "load_test.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    assert report["completed"] == 50 and report["unique_ids"] == 50


if __name__ == "__main__":
    main()

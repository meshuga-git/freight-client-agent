"""Local synthetic corpus, evaluation, and watched-folder intake commands."""

import argparse
import json
from pathlib import Path
import time
from .service import Store


def main():
    parser = argparse.ArgumentParser(description="Synthetic-only Meridian Freight demo")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--output", default="data/corpus")
    generate.add_argument("--count", type=int, default=80)
    generate.add_argument("--seed", type=int, default=42)
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("action", choices=["run"])
    evaluate.add_argument("--corpus", default="data/corpus")
    evaluate.add_argument("--output", default="reports")
    evaluate.add_argument("--split", choices=["dev", "heldout", "all"], default="heldout")
    intake = sub.add_parser("import-folder")
    intake.add_argument("folder")
    intake.add_argument("--data", default="runtime")
    intake.add_argument("--actor", default="reviewer")
    intake.add_argument("--synthetic", action="store_true", required=True)
    intake.add_argument("--watch", action="store_true")
    intake.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if args.command == "generate":
        from .corpus import generate

        print(
            json.dumps(
                generate(Path(args.output), count=args.count, seed=args.seed), default=str, indent=2
            )
        )
    elif args.command == "eval":
        from .evaluation import evaluate

        print(
            json.dumps(
                evaluate(Path(args.corpus), Path(args.output), split=args.split),
                default=str,
                indent=2,
            )
        )
    else:
        store = Store(args.data)
        seen = set()
        while True:
            # Each immediate folder is a separate shipment pack; never mix unrelated PDFs.
            folders = [p for p in Path(args.folder).iterdir() if p.is_dir()]
            if list(Path(args.folder).glob("*.pdf")):
                folders.append(Path(args.folder))
            for folder in sorted(folders):
                files = sorted(folder.glob("*.pdf"))
                signature = tuple((str(f), f.stat().st_mtime_ns) for f in files)
                if not files or signature in seen:
                    continue
                state = store.create(args.actor, {"synthetic": True})
                for file in files:
                    store.add_upload(state["id"], args.actor, file.name, file.read_bytes())
                state = store.process(state["id"], args.actor)
                print(
                    json.dumps(
                        {
                            "shipment_id": state["id"],
                            "status": state["status"],
                            "folder": str(folder),
                        }
                    ),
                    flush=True,
                )
                seen.add(signature)
            if not args.watch:
                break
            time.sleep(max(args.interval, 1))


if __name__ == "__main__":
    main()

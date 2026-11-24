"""Transactional local implementation. SQLite/files are explicit portfolio fallbacks."""

from __future__ import annotations
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from typing import Any


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


class Forbidden(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        config_path = os.getenv("FREIGHT_RULES_CONFIG")
        self.rules_config = json.loads(Path(config_path).read_text()) if config_path else {}
        if not isinstance(self.rules_config, dict):
            raise ValueError("FREIGHT_RULES_CONFIG must contain a JSON object")
        self.database = self.root / "freight.sqlite3"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS shipments(id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id TEXT, actor TEXT, step TEXT, version INTEGER, ts REAL, input_hash TEXT, details TEXT);
            CREATE TABLE IF NOT EXISTS exports(shipment_id TEXT, key TEXT, format TEXT, version INTEGER, payload_hash TEXT, payload TEXT, PRIMARY KEY(shipment_id,key));
            CREATE TABLE IF NOT EXISTS eval_runs(id TEXT PRIMARY KEY, ts REAL, metrics TEXT);
            """)

    def connect(self):
        db = sqlite3.connect(self.database, timeout=120)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _get(self, db, shipment_id, actor):
        row = db.execute("SELECT * FROM shipments WHERE id=?", (shipment_id,)).fetchone()
        if row is None or row["owner"] != actor:
            raise NotFound("Shipment not found")
        return json.loads(row["state"])

    def _save(self, db, state):
        db.execute("UPDATE shipments SET state=? WHERE id=?", (canonical(state), state["id"]))

    def _audit(self, db, state, actor, step, details=None):
        # Audit values are private shipment data, never emitted into application logs.
        db.execute(
            "INSERT INTO audit_log(shipment_id,actor,step,version,ts,input_hash,details) VALUES(?,?,?,?,?,?,?)",
            (
                state["id"],
                actor,
                step,
                state["version"],
                time.time(),
                digest(state),
                canonical(details or {}),
            ),
        )

    def create(self, actor, data):
        if actor == "guest":
            raise Forbidden("Guest is read-only")
        if data.get("synthetic") is not True:
            raise ValueError(
                "Explicit synthetic=true attestation required; no real documents allowed"
            )
        profile = data.get("profile", "us_domestic_trucking")
        mode = data.get("mode", "road")
        direction = data.get("direction", "domestic")
        if profile == "us_domestic_trucking" and (
            mode != "road" or direction != "domestic" or data.get("destination", "US") != "US"
        ):
            raise ValueError("Domestic profile requires road/domestic/US")
        if profile in ("sea", "air") and (mode != profile or direction == "domestic"):
            raise ValueError("Sea/air profiles require matching mode and international direction")
        if profile == "international_road" and (mode != "road" or direction == "domestic"):
            raise ValueError("International road requires road and import/export direction")
        sid = str(uuid.uuid4())
        state = {
            "id": sid,
            "owner": actor,
            "mode": data.get("mode", "road"),
            "profile": data.get("profile", "us_domestic_trucking"),
            "direction": data.get("direction", "domestic"),
            "incoterm": data.get("incoterm", ""),
            "destination": data.get("destination", "US"),
            "containerized": data.get("containerized", False),
            "synthetic": True,
            "version": 1,
            "status": "Blocked",
            "documents": [],
            "uploads": [],
            "rules": [],
            "overrides": {},
            "confirmed_version": None,
            "trace_id": str(uuid.uuid4()),
            "created_at": time.time(),
            "processed": False,
        }
        with self.transaction() as db:
            db.execute("INSERT INTO shipments VALUES(?,?,?)", (sid, actor, canonical(state)))
            self._audit(db, state, actor, "create")
        return state

    def list(self, actor):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT state FROM shipments WHERE owner=? ORDER BY rowid DESC", (actor,)
                )
            ]

    def get(self, sid, actor):
        with self.connect() as db:
            return self._get(db, sid, actor)

    def _check_version(self, state, version):
        if state["version"] != version:
            raise Conflict("Stale version; reload before reviewing or exporting")

    def _invalidate(self, state):
        state["version"] += 1
        state["confirmed_version"] = None

    def add_upload(self, sid, actor, name, content):
        if not content.startswith(b"%PDF-") or len(content) > 20 * 1024 * 1024:
            raise ValueError("Only PDFs up to 20 MiB accepted")
        import fitz

        try:
            with fitz.open(stream=content, filetype="pdf") as pdf:
                if pdf.is_encrypted or not 1 <= len(pdf) <= 40:
                    raise ValueError("PDF must be unencrypted and contain 1–40 pages")
        except (RuntimeError, fitz.FileDataError) as exc:
            raise ValueError("Malformed PDF") from exc
        with self.transaction() as db:
            state = self._get(db, sid, actor)
            if actor == "guest":
                raise Forbidden("Guest is read-only")
            if len(state["uploads"]) >= 12:
                raise ValueError("Maximum 12 PDFs per shipment")
            uid = str(uuid.uuid4())
            folder = self.root / sid
            folder.mkdir(exist_ok=True)
            path = folder / (uid + ".pdf")
            path.write_bytes(content)
            state["uploads"].append(
                {
                    "id": uid,
                    "name": Path(name).name,
                    "path": str(path),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
            state["processed"] = False
            state["status"] = "Blocked"
            state["overrides"] = {}
            self._invalidate(state)
            self._save(db, state)
            self._audit(
                db,
                state,
                actor,
                "ingest",
                {"upload_id": uid, "sha256": hashlib.sha256(content).hexdigest()},
            )
            return state

    def _validate(self, db, state):
        from freight_agent.rules import validate

        history = []
        for row in db.execute(
            "SELECT state FROM shipments WHERE id<>? AND owner=?", (state["id"], state["owner"])
        ):
            other = json.loads(row[0])
            history.extend(other.get("documents", []))
        state["rules"] = validate(
            state["documents"], state, history=history, config=self.rules_config
        )
        for doc in state["documents"]:
            for idx, issue in enumerate(doc.get("issues", [])):
                if not doc.get("accepted_issues", False):
                    state["rules"].append(
                        {
                            "rule_id": f"EXTRACT:{doc['id']}:{idx}",
                            "severity": "Critical",
                            "status": "fail",
                            "details": str(issue),
                            "evidence_refs": [doc["id"]],
                        }
                    )
            if doc.get("type_confidence", 0) < 0.9 and not doc.get("accepted_classification"):
                state["rules"].append(
                    {
                        "rule_id": f"CLASSIFY:{doc['id']}",
                        "severity": "Critical",
                        "status": "fail",
                        "details": "Unknown or low-confidence classification requires review",
                        "evidence_refs": [doc["id"]],
                    }
                )
            for field, item in doc.get("fields", {}).items():
                if (
                    isinstance(item, dict)
                    and (not item.get("grounded", False) or item.get("confidence", 0) < 0.9)
                    and not item.get("reviewed")
                ):
                    state["rules"].append(
                        {
                            "rule_id": f"GROUND:{doc['id']}:{field}",
                            "severity": "Critical",
                            "status": "fail",
                            "details": f"Unverified extraction: {field}",
                            "evidence_refs": [doc["id"], field],
                        }
                    )
        for rule in state["rules"]:
            rule["fingerprint"] = digest(
                {k: v for k, v in rule.items() if k not in ("overridden", "fingerprint")}
            )
            rule["overridden"] = (
                state["overrides"].get(rule["rule_id"], {}).get("fingerprint")
                == rule["fingerprint"]
            )
        failed = [r for r in state["rules"] if r["status"] == "fail" and not r["overridden"]]
        state["status"] = (
            "Blocked"
            if any(r["severity"] == "Critical" for r in failed)
            else "Needs review"
            if any(r["severity"] == "Major" for r in failed)
            else "Clean"
        )

    def process(self, sid, actor, backend="offline", settings=None):
        from docpipe import process_pdf, Settings

        if settings is None:
            settings = Settings()
        elif isinstance(settings, dict):
            settings = Settings(**settings)
        settings.budget = {"cost": 0.0}
        with self.transaction() as db:
            state = self._get(db, sid, actor)
            if actor == "guest":
                raise Forbidden("Guest is read-only")
            if not state["uploads"]:
                raise ValueError("Upload at least one synthetic PDF")
            docs = []
            for upload in state["uploads"]:
                try:
                    parsed = process_pdf(upload["path"], backend=backend, settings=settings)
                except Exception as exc:
                    # Fail closed without recording provider secrets or uncontrolled exception messages.
                    parsed = [
                        {
                            "id": "failed",
                            "type": "unknown",
                            "type_confidence": 0,
                            "pages": [],
                            "fields": {},
                            "issues": [
                                f"Processing failure ({type(exc).__name__}); retry or review required"
                            ],
                            "usage": {},
                        }
                    ]
                for doc in parsed:
                    doc["id"] = str(uuid.uuid4())
                    doc["upload_id"] = upload["id"]
                    docs.append(doc)
            state["documents"] = docs
            state["processed"] = True
            state["overrides"] = {}
            self._invalidate(state)
            self._validate(db, state)
            self._save(db, state)
            self._audit(
                db,
                state,
                actor,
                "process",
                {
                    "backend": backend,
                    "document_count": len(docs),
                    "usage": [d.get("usage", {}) for d in docs],
                    "normalizations": [d.get("normalizations", []) for d in docs],
                },
            )
            return state

    def review(self, sid, actor, request):
        with self.transaction() as db:
            state = self._get(db, sid, actor)
            self._check_version(state, request["version"])
            if actor == "guest":
                raise Forbidden("Guest is read-only")
            if not state["processed"]:
                raise Conflict("Process current uploads before reviewing")
            reason = request.get("reason", "").strip()
            if not reason:
                raise ValueError("A review reason is required")
            action = request["action"]
            old = None
            if action == "override":
                rule = next(
                    (
                        r
                        for r in state["rules"]
                        if r["rule_id"] == request.get("rule_id") and r["status"] == "fail"
                    ),
                    None,
                )
                if rule is None:
                    raise ValueError("Failed rule not found")
                state["overrides"][rule["rule_id"]] = {
                    "fingerprint": rule["fingerprint"],
                    "reason": reason,
                    "reviewer": actor,
                }
            elif action in ("correct", "accept"):
                doc = next(
                    (d for d in state["documents"] if d["id"] == request.get("document_id")), None
                )
                if doc is None:
                    raise NotFound("Document not found in shipment")
                field = request.get("field")
                if not field or field not in doc["fields"]:
                    raise ValueError("Existing field required")
                item = doc["fields"][field]
                old = deepcopy(item)
                if action == "correct":
                    from docpipe.normalization import normalize as normalize_field

                    raw = request.get("value")
                    normalized = normalize_field(field, raw)
                    # Support both scalar and structured normalizer returns.
                    item["value"] = (
                        normalized.get("value", normalized.get("normalized_value", raw))
                        if isinstance(normalized, dict)
                        else normalized
                    )
                    item["normalized_value"] = item["value"]
                    item["corrected_value"] = raw
                    state["overrides"] = {}
                item["reviewed"] = True
                item["reviewer"] = actor
                item["review_reason"] = reason
            else:
                raise ValueError("Unsupported review action")
            self._invalidate(state)
            self._validate(db, state)
            self._save(db, state)
            self._audit(db, state, actor, "review", {**request, "old_value": old})
            return state

    def confirm(self, sid, actor, version):
        with self.transaction() as db:
            state = self._get(db, sid, actor)
            self._check_version(state, version)
            if actor == "guest":
                raise Forbidden("Guest is read-only")
            self._validate(db, state)
            if not state["processed"] or state["status"] != "Clean":
                raise Conflict("Resolve or explicitly override all Critical/Major findings first")
            state["confirmed_version"] = version
            state["confirmed_by"] = actor
            self._save(db, state)
            self._audit(db, state, actor, "confirm", {"version": version})
            return state

    def export(self, sid, actor, version, format, key):
        if format not in ("json", "csv", "mock_tms"):
            raise ValueError("Unsupported export format")
        if not key or len(key) > 128:
            raise ValueError("Idempotency key required, max 128 characters")
        with self.transaction() as db:
            state = self._get(db, sid, actor)
            self._check_version(state, version)
            if actor == "guest":
                raise Forbidden("Guest is read-only")
            if state["confirmed_version"] != version or not state["processed"]:
                raise Conflict("Human confirmation of this exact version required")
            self._validate(db, state)
            if state["status"] != "Clean":
                raise Conflict("Validation changed since confirmation; review current findings")
            existing = db.execute(
                "SELECT * FROM exports WHERE shipment_id=? AND key=?", (sid, key)
            ).fetchone()
            if existing:
                if existing["version"] != version or existing["format"] != format:
                    raise Conflict("Idempotency key already bound to different version/format")
                return {
                    "format": format,
                    "version": version,
                    "payload": existing["payload"],
                    "sha256": existing["payload_hash"],
                    "replayed": True,
                }
            record = {
                "shipment_id": sid,
                "version": version,
                "synthetic": True,
                "confirmed_by": actor,
                "documents": state["documents"],
                "validations": state["rules"],
                "advisory": "Synthetic portfolio only; not customs, classification, legal or compliance advice.",
            }
            if format == "csv":
                stream = io.StringIO()
                writer = csv.writer(stream)
                writer.writerow(["shipment_id", "version", "document_id", "type", "field", "value"])
                for doc in state["documents"]:
                    for field, item in doc["fields"].items():
                        value = str(item.get("value", ""))
                        # Spreadsheet formula injection prevention, including whitespace prefixes.
                        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                            value = "'" + value
                        writer.writerow([sid, version, doc["id"], doc["type"], field, value])
                payload = stream.getvalue()
            else:
                if format == "mock_tms":
                    record = {
                        "mock": True,
                        "external_request_sent": False,
                        "receipt": digest(record),
                        "record": record,
                    }
                payload = canonical(record)
            hashed = hashlib.sha256(payload.encode()).hexdigest()
            db.execute(
                "INSERT INTO exports VALUES(?,?,?,?,?,?)",
                (sid, key, format, version, hashed, payload),
            )
            self._audit(
                db,
                state,
                actor,
                "export",
                {
                    "format": format,
                    "key": key,
                    "payload_hash": hashed,
                    "external_request_sent": False,
                },
            )
            return {
                "format": format,
                "version": version,
                "payload": payload,
                "sha256": hashed,
                "replayed": False,
            }

    def audit(self, sid, actor):
        with self.connect() as db:
            self._get(db, sid, actor)
            return [
                {**dict(row), "details": json.loads(row["details"])}
                for row in db.execute(
                    "SELECT * FROM audit_log WHERE shipment_id=? ORDER BY seq", (sid,)
                )
            ]

"""Pure, evidence-linked freight checks. Reference subsets are demonstration data.

No rule performs legal classification. R06, R10 charge conventions, R11 chapter
hints, and R14 lexical mismatch screening are advisory reviewer aids.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import re

RULE_VERSION = "1.0.0"
DEFAULT_CONFIG = {
    "consignee_similarity": 0.9,
    "weight_tolerance": 0.01,
    "money_tolerance": 0.01,
    "require_invoice_before_dispatch": False,
    "description_similarity": 0.35,
    "required_documents": ["transport", "invoice", "packing_list"],
    "required_matrix": [],
    "coo_destinations": [],
    "restricted_keywords": ["explosive", "ammunition", "lithium battery", "radioactive"],
    "incoterms": ["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"],
    "sea_only_incoterms": ["FAS", "FOB", "CFR", "CIF"],
    "charge_conventions": {},
    "incoterm_profile": "unspecified",
    "ports": ["USLAX", "USNYC", "CNSHA", "GBLON", "NLRTM", "DEHAM", "SGSIN", "AEJEA"],
    "hs_description_chapters": {},
}
ALIASES = {
    "gross_weight_kg": ["gross_weight"],
    "country_of_origin": ["origin_country", "origin"],
    "document_number": ["bl_number", "bill_number", "invoice_number", "awb_number"],
    "port_of_loading": ["port_loading", "origin_port"],
    "port_of_discharge": ["port_discharge", "destination_port"],
    "seal_number": ["seal"],
    "freight_charge": ["freight"],
    "insurance_charge": ["insurance"],
    "on_board_date": ["dispatch_date", "shipment_date"],
    "lines": ["line_items"],
    "total": ["invoice_total"],
    "package_count": ["packages"],
}


def field(doc, name):
    fields = (doc or {}).get("fields", {})
    for key in [name] + ALIASES.get(name, []):
        if key in fields:
            val = fields[key]
            return (
                val.get("normalized_value", val.get("value", val.get("raw_value")))
                if isinstance(val, dict)
                else val
            )
    return None


def present(value):
    return value is not None and value != "" and value != []


def number(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def canonical(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def container_check_digit(prefix):
    """ISO 6346 arithmetic for exactly four letters and six digits (no check digit)."""
    prefix = str(prefix).upper()
    if not re.fullmatch(r"[A-Z]{3}[UJZ]\d{6}", prefix):
        raise ValueError("Expected owner/category prefix and six serial digits")
    values = {str(i): i for i in range(10)}
    v = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        values[ch] = v
        v += 1
    return sum(values[ch] * 2**i for i, ch in enumerate(prefix)) % 11 % 10


def valid_container(value):
    code = re.sub(r"[\s-]", "", str(value or "").upper())
    return bool(re.fullmatch(r"[A-Z]{3}[UJZ]\d{7}", code)) and container_check_digit(
        code[:10]
    ) == int(code[-1])


class Context:
    def __init__(self, documents, shipment, history=None, config=None):
        self.docs, self.shipment, self.history = documents, shipment, history or []
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.transport = (
            self.get("air_waybill") if shipment.get("mode") == "air" else self.get("bill_of_lading")
        )
        self.invoice, self.packing, self.coo = (
            self.get("invoice"),
            self.get("packing_list"),
            self.get("certificate_of_origin"),
        )

    def get(self, kind):
        return next((d for d in self.docs if d.get("type") == kind), None)

    def result(self, rule, ok, details, refs=(), na=False):
        evidence = []
        for doc, key in refs:
            if doc:
                raw = next(
                    (
                        doc.get("fields", {})[alias]
                        for alias in [key] + ALIASES.get(key, [])
                        if alias in doc.get("fields", {})
                    ),
                    {},
                )
                evidence.append(
                    {
                        "document_id": doc.get("id"),
                        "field": key,
                        "page": raw.get("page") if isinstance(raw, dict) else None,
                        "evidence": raw.get("evidence") if isinstance(raw, dict) else None,
                    }
                )
        return {
            "rule_id": rule,
            "severity": "Critical" if int(rule[1:]) <= 6 else "Minor" if rule == "R16" else "Major",
            "status": "not_applicable" if na else "pass" if ok else "fail",
            "details": details,
            "evidence_refs": evidence,
        }


def r01(c):
    required = set(c.config["required_documents"])
    for row in c.config["required_matrix"]:
        if all(c.shipment.get(k) == v for k, v in row.get("when", {}).items()):
            required.update(row.get("required", []))
    if (
        c.shipment.get("requires_coo")
        or c.shipment.get("destination") in c.config["coo_destinations"]
    ):
        required.add("certificate_of_origin")
    found = {d.get("type") for d in c.docs}
    if c.transport:
        found.add("transport")
    missing = sorted(required - found)
    return c.result(
        "R01",
        not missing,
        "Missing required documents: " + ", ".join(missing)
        if missing
        else "Required documents present",
    )


def r02(c):
    a, b = field(c.transport, "consignee"), field(c.invoice, "consignee")
    ok = (
        present(a)
        and present(b)
        and SequenceMatcher(None, canonical(a), canonical(b)).ratio()
        >= c.config["consignee_similarity"]
    )
    return c.result(
        "R02",
        ok,
        "Consignee must be present and match across transport and invoice",
        [(c.transport, "consignee"), (c.invoice, "consignee")],
    )


def r03(c):
    a, b = number(field(c.transport, "package_count")), number(field(c.packing, "package_count"))
    return c.result(
        "R03",
        a is not None and b is not None and a >= 0 and a == a.to_integral() and a == b,
        "Package counts must be nonnegative integers and equal",
        [(c.transport, "package_count"), (c.packing, "package_count")],
    )


def r04(c):
    vals = [
        (d, field(d, "container_number")) for d in c.docs if present(field(d, "container_number"))
    ]
    applicable = c.shipment.get("containerized", False) or bool(vals)
    return c.result(
        "R04",
        bool(vals) and all(valid_container(v) for _, v in vals),
        "Container identifiers require ISO 6346 check digits"
        if applicable
        else "Noncontainer shipment",
        [(d, "container_number") for d, _ in vals],
        na=not applicable,
    )


def r05(c):
    a, b = field(c.invoice, "country_of_origin"), field(c.coo, "country_of_origin")
    return c.result(
        "R05",
        present(a) and present(b) and canonical(a) == canonical(b),
        "Origin must agree with certificate when supplied",
        [(c.invoice, "country_of_origin"), (c.coo, "country_of_origin")],
        na=c.coo is None,
    )


def r06(c):
    texts = [
        str(field(d, "goods_description") or "") + " " + str(field(d, "lines") or "")
        for d in c.docs
    ]
    found = [
        word
        for word in c.config["restricted_keywords"]
        if any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.I) for text in texts)
    ]
    has_description = any(present(field(d, "goods_description")) for d in c.docs)
    return c.result(
        "R06",
        has_description and not found,
        "Advisory keyword screen; not compliance advice. "
        + (
            "Review matches: " + ", ".join(found)
            if found
            else "No configured keywords detected"
            if has_description
            else "Missing goods descriptions"
        ),
        [(d, "goods_description") for d in c.docs],
    )


def r07(c):
    a, b = (
        number(field(c.transport, "gross_weight_kg")),
        number(field(c.packing, "gross_weight_kg")),
    )
    ok = (
        a is not None
        and b is not None
        and a > 0
        and b > 0
        and abs(a - b) / b <= Decimal(str(c.config["weight_tolerance"]))
    )
    return c.result(
        "R07",
        ok,
        "Gross weights must be positive and within configured tolerance relative to packing list",
        [(c.transport, "gross_weight_kg"), (c.packing, "gross_weight_kg")],
    )


def quantities(lines):
    if not isinstance(lines, list) or not lines:
        return None
    result = Counter()
    for line in lines:
        if not isinstance(line, dict):
            return None
        key = canonical(line.get("sku") or line.get("description"))
        q = number(line.get("quantity"))
        if not key or q is None or q < 0:
            return None
        result[key] += q
    return result


def r08(c):
    a, b = quantities(field(c.invoice, "lines")), quantities(field(c.packing, "lines"))
    return c.result(
        "R08",
        a is not None and b is not None and a == b,
        "Line quantities reconcile by SKU (or description)",
        [(c.invoice, "lines"), (c.packing, "lines")],
    )


def r09(c):
    lines, total, currency = (
        field(c.invoice, "lines"),
        number(field(c.invoice, "total")),
        field(c.invoice, "currency"),
    )
    ok, summed = (
        isinstance(lines, list)
        and bool(lines)
        and total is not None
        and bool(re.fullmatch(r"[A-Z]{3}", str(currency))),
        Decimal(0),
    )
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            ok = False
            continue
        q, p, amount = (
            number(line.get("quantity")),
            number(line.get("unit_price")),
            number(line.get("line_total")),
        )
        if amount is None and q is not None and p is not None:
            amount = q * p
        if amount is None or amount < 0 or line.get("currency", currency) != currency:
            ok = False
        elif (
            q is not None
            and p is not None
            and abs(amount - q * p) > Decimal(str(c.config["money_tolerance"]))
        ):
            ok = False
        else:
            summed += amount
    ok = ok and abs(summed - total) <= Decimal(str(c.config["money_tolerance"]))
    return c.result(
        "R09",
        ok,
        "Invoice totals and line arithmetic must reconcile in a single currency",
        [(c.invoice, "lines"), (c.invoice, "total"), (c.invoice, "currency")],
    )


def r10(c):
    term = field(c.invoice, "incoterm") or c.shipment.get("incoterm")
    if (
        not present(term)
        and c.shipment.get("profile", "us_domestic_trucking") == "us_domestic_trucking"
    ):
        return c.result("R10", True, "Incoterms not required for US domestic trucking", na=True)
    ok = term in c.config["incoterms"]
    notes = []
    if c.shipment.get("incoterm") and term != c.shipment["incoterm"]:
        ok = False
        notes.append("Shipment and invoice terms differ")
    if (
        c.config["incoterm_profile"] == "icc2020"
        and c.shipment.get("mode", "road") != "sea"
        and term in c.config["sea_only_incoterms"]
    ):
        ok = False
        notes.append("Sea/waterway-only term supplied for non-sea mode")
    convention = c.config["charge_conventions"].get(term, {})
    for name in convention.get("require_positive", []):
        n = number(field(c.invoice, name))
        if n is None or n <= 0:
            ok = False
            notes.append(f"Configured advisory convention expects positive {name}")
    for name in convention.get("expect_zero", []):
        n = number(field(c.invoice, name))
        if n is None or n != 0:
            ok = False
            notes.append(f"Configured advisory convention expects zero {name}")
    return c.result(
        "R10",
        ok,
        "; ".join(notes)
        or "Incoterm validity checked; charge conventions are optional advisory heuristics, not legal rules",
        [(c.invoice, "incoterm")],
    )


def r11(c):
    lines = field(c.invoice, "lines")
    codes = (
        [(field(c.invoice, "hs_code"), field(c.invoice, "goods_description"))]
        if field(c.invoice, "hs_code") is not None
        else []
    )
    codes += (
        [
            (line.get("hs_code"), line.get("description", ""))
            for line in lines
            if isinstance(line, dict)
        ]
        if isinstance(lines, list)
        else []
    )
    if (
        not any(present(code) for code, _ in codes)
        and c.shipment.get("profile", "us_domestic_trucking") == "us_domestic_trucking"
    ):
        return c.result("R11", True, "HS codes not required for US domestic trucking", na=True)
    ok = bool(codes)
    for code, desc in codes:
        if not re.fullmatch(r"\d{6,10}", str(code or "")):
            ok = False
        for keyword, chapters in c.config["hs_description_chapters"].items():
            if keyword.lower() in str(desc).lower() and str(code)[:2] not in chapters:
                ok = False
    return c.result(
        "R11",
        ok,
        "HS format and optional configured chapter hints only; no authoritative classification or legal plausibility determination",
        [(c.invoice, "hs_code"), (c.invoice, "lines")],
    )


def r12(c):
    relevant = c.shipment.get("mode") == "sea" or c.shipment.get("validate_ports", False)
    ok = True
    refs = []
    for name in ("port_of_loading", "port_of_discharge"):
        values = [field(d, name) for d in c.docs if present(field(d, name))]
        refs += [(d, name) for d in c.docs if present(field(d, name))]
        ok = (
            ok
            and bool(values)
            and all(v in c.config["ports"] for v in values)
            and len(set(values)) == 1
        )
    return c.result(
        "R12",
        ok,
        "Ports checked against configurable demonstration UN/LOCODE subset; unknown means unverified, not definitively invalid"
        if relevant
        else "Port rule is not applicable to this transport mode",
        refs,
        na=not relevant,
    )


def r13(c):
    try:
        dates = [
            date.fromisoformat(str(v))
            for v in (
                field(c.invoice, "invoice_date"),
                field(c.transport, "on_board_date"),
                field(c.transport, "eta"),
            )
        ]
        ok = dates[1] <= dates[2]
        if c.config["require_invoice_before_dispatch"]:
            ok = ok and dates[0] <= dates[1]
    except (ValueError, TypeError):
        ok = False
    return c.result(
        "R13",
        ok,
        "Dates must be valid ISO dates; dispatch/on-board <= ETA. "
        + (
            "Configured invoice-before-dispatch requirement applies."
            if c.config["require_invoice_before_dispatch"]
            else "Invoice may postdate dispatch under default domestic policy."
        ),
        [(c.invoice, "invoice_date"), (c.transport, "on_board_date"), (c.transport, "eta")],
    )


def r14(c):
    a, b = (
        canonical(field(c.transport, "goods_description")),
        canonical(field(c.invoice, "goods_description")),
    )
    aa, bb = set(a.split()), set(b.split())
    similarity = len(aa & bb) / len(aa | bb) if aa | bb else 0
    return c.result(
        "R14",
        bool(a and b) and similarity >= c.config["description_similarity"],
        f"Advisory lexical Jaccard similarity {similarity:.3f}; not a semantic model",
        [(c.transport, "goods_description"), (c.invoice, "goods_description")],
    )


def r15(c):
    docs = [d for d in c.docs if d.get("type") in {"bill_of_lading", "air_waybill", "invoice"}]
    seen, duplicates, missing = set(), [], False
    for d in docs:
        num = canonical(field(d, "document_number"))
        if not num:
            missing = True
            continue
        key = (d["type"], num)
        if key in seen:
            duplicates.append(num)
        seen.add(key)
        for previous in c.history:
            if c.shipment.get("id") and previous.get("shipment_id") == c.shipment["id"]:
                continue
            if (
                previous.get("type") == d["type"]
                and canonical(previous.get("document_number") or field(previous, "document_number"))
                == num
            ):
                duplicates.append(num)
    return c.result(
        "R15",
        bool(docs) and not missing and not duplicates,
        "Duplicate transport/invoice identifiers: " + ", ".join(duplicates)
        if duplicates
        else "Identifiers checked against supplied history; missing identifiers require review"
        if missing
        else "No duplicate identifiers in supplied history",
        [(d, "document_number") for d in docs],
    )


def r16(c):
    ok, applicable = True, False
    for key in ("seal_number", "shipping_marks"):
        vals = [canonical(field(d, key)) for d in c.docs if present(field(d, key))]
        if len(vals) >= 2:
            applicable = True
            ok = ok and len(set(vals)) == 1
    return c.result(
        "R16",
        ok,
        "Compare seals/marks where repeated; absent optional fields are not assumed equal",
        [
            (d, key)
            for d in c.docs
            for key in ("seal_number", "shipping_marks")
            if present(field(d, key))
        ],
        na=not applicable,
    )


RULES = [r01, r02, r03, r04, r05, r06, r07, r08, r09, r10, r11, r12, r13, r14, r15, r16]


def validate(
    documents: list[dict],
    shipment: dict,
    history: list[dict] | None = None,
    config: dict | None = None,
) -> list[dict]:
    context = Context(documents, shipment, history, config)
    return [rule(context) for rule in RULES]


def pack_status(results):
    failed = {r["severity"] for r in results if r["status"] == "fail"}
    return "Blocked" if "Critical" in failed else "Needs review" if "Major" in failed else "Clean"

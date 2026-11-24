import copy
import pytest
from freight_agent.rules import validate, pack_status, container_check_digit, valid_container


def documents():
    line = {
        "sku": "A",
        "description": "Steel bolts",
        "quantity": 20,
        "unit_price": 5,
        "line_total": 100,
        "currency": "USD",
        "hs_code": "731815",
    }
    shared = {
        "consignee": "Meridian Manufacturing LLC",
        "goods_description": "Steel bolts",
        "package_count": 10,
        "gross_weight": 1000,
        "country_of_origin": "US",
        "shipping_marks": "MFF",
        "seal": "S1",
    }
    return [
        {
            "id": "bl",
            "type": "bill_of_lading",
            "fields": {
                **shared,
                "bl_number": "BL1",
                "on_board_date": "2026-10-02",
                "eta": "2026-10-03",
            },
        },
        {
            "id": "inv",
            "type": "invoice",
            "fields": {
                **shared,
                "invoice_number": "INV1",
                "lines": [line],
                "total": 100,
                "currency": "USD",
                "incoterm": "FCA",
                "invoice_date": "2026-10-01",
            },
        },
        {"id": "pl", "type": "packing_list", "fields": {**shared, "lines": [line]}},
        {"id": "coo", "type": "certificate_of_origin", "fields": {"country_of_origin": "US"}},
    ]


def result(rule, docs=None, shipment=None, **kwargs):
    return next(
        r
        for r in validate(
            docs if docs is not None else documents(), shipment or {"mode": "road"}, **kwargs
        )
        if r["rule_id"] == rule
    )


def test_clean_road_and_applicability():
    results = validate(documents(), {"mode": "road"})
    assert len(results) == 16
    assert not [r for r in results if r["status"] == "fail"]
    assert result("R04")["status"] == "not_applicable"
    assert result("R12")["status"] == "not_applicable"
    assert pack_status(results) == "Clean"


@pytest.mark.parametrize(
    "rule,index,field,value",
    [
        ("R02", 1, "consignee", "Other consignee"),
        ("R03", 2, "package_count", 11),
        ("R04", 0, "container_number", "MSCU1234560"),
        ("R05", 3, "country_of_origin", "CN"),
        ("R06", 0, "goods_description", "Lithium battery"),
        ("R07", 2, "gross_weight", 1100),
        ("R08", 2, "lines", [{"sku": "A", "quantity": 19}]),
        ("R09", 1, "total", 101),
        ("R10", 1, "incoterm", "BOGUS"),
        ("R11", 1, "lines", [{"hs_code": "123"}]),
        ("R13", 0, "eta", "2026-10-01"),
        ("R14", 1, "goods_description", "Cotton clothing"),
        ("R15", 1, "invoice_number", ""),
        ("R16", 2, "seal", "DIFFERENT"),
    ],
)
def test_mismatch_branches(rule, index, field, value):
    docs = documents()
    docs[index]["fields"][field] = value
    assert result(rule, docs)["status"] == "fail"


@pytest.mark.parametrize(
    "rule", ["R01", "R02", "R03", "R06", "R07", "R08", "R09", "R13", "R14", "R15"]
)
def test_missing_fails_closed(rule):
    assert result(rule, [])["status"] == "fail"


def test_required_matrix_and_mode():
    docs = documents()[:3]
    assert result("R01", docs)["status"] == "pass"
    assert result("R01", docs, {"mode": "air"})["status"] == "fail"
    assert (
        result(
            "R01", docs, {"mode": "road", "destination": "MX"}, config={"coo_destinations": ["MX"]}
        )["status"]
        == "fail"
    )
    assert (
        result(
            "R01",
            docs,
            {"mode": "road", "direction": "export"},
            config={
                "required_matrix": [
                    {
                        "when": {"mode": "road", "direction": "export"},
                        "required": ["certificate_of_origin"],
                    }
                ]
            },
        )["status"]
        == "fail"
    )
    assert result("R05", docs)["status"] == "not_applicable"


def test_container_arithmetic():
    assert container_check_digit("CSQU305438") == 3
    assert valid_container("CSQU3054383")
    assert valid_container("CSQU 305438 3")
    assert not valid_container("CSQU3054384")
    assert not valid_container("CSQA3054383")
    with pytest.raises(ValueError):
        container_check_digit("oops")
    docs = documents()
    docs[0]["fields"]["container_number"] = "CSQU3054383"
    assert result("R04", docs)["status"] == "pass"
    assert result("R04", shipment={"mode": "road", "containerized": True})["status"] == "fail"


def test_ports_unknown_review_not_invalid_claim():
    docs = documents()
    for d in docs[:2]:
        d["fields"].update(port_loading="USLAX", port_discharge="CNSHA")
    assert result("R12", docs, {"mode": "sea"})["status"] == "pass"
    docs[1]["fields"]["port_discharge"] = "ZZZZZ"
    r = result("R12", docs, {"mode": "sea"})
    assert r["status"] == "fail" and "unverified" in r["details"]
    assert result("R12", shipment={"mode": "sea"})["status"] == "fail"


def test_incoterm_profile_and_advisory_charges():
    docs = documents()
    docs[1]["fields"]["incoterm"] = "FOB"
    assert result("R10", docs)["status"] == "pass"  # Domestic use is not assumed ICC.
    assert result("R10", docs, config={"incoterm_profile": "icc2020"})["status"] == "fail"
    assert (
        result("R10", docs, {"mode": "sea"}, config={"incoterm_profile": "icc2020"})["status"]
        == "pass"
    )
    docs[1]["fields"].update(incoterm="CIF", insurance=0)
    cfg = {"charge_conventions": {"CIF": {"require_positive": ["insurance_charge"]}}}
    assert result("R10", docs, {"mode": "sea"}, config=cfg)["status"] == "fail"
    docs[1]["fields"]["insurance"] = 10
    assert result("R10", docs, {"mode": "sea"}, config=cfg)["status"] == "pass"
    cfg = {"charge_conventions": {"CIF": {"expect_zero": ["freight_charge"]}}}
    assert result("R10", docs, {"mode": "sea"}, config=cfg)["status"] == "fail"
    docs[1]["fields"]["freight"] = 0
    assert result("R10", docs, {"mode": "sea"}, config=cfg)["status"] == "pass"


def test_currency_arithmetic_and_nan():
    docs = documents()
    docs[1]["fields"]["lines"][0]["currency"] = "EUR"
    assert result("R09", docs)["status"] == "fail"
    for value in ["NaN", "Infinity", None, "bad"]:
        docs[1]["fields"]["total"] = value
        assert result("R09", docs)["status"] == "fail"
    docs = documents()
    docs[1]["fields"]["lines"][0]["line_total"] = 99
    assert result("R09", docs)["status"] == "fail"
    del docs[1]["fields"]["lines"][0]["line_total"]
    assert result("R09", docs)["status"] == "pass"


def test_duplicate_history_and_same_shipment():
    history = [{"type": "invoice", "document_number": "INV1", "shipment_id": "other"}]
    assert result("R15", history=history)["status"] == "fail"
    assert (
        result("R15", shipment={"mode": "road", "id": "other"}, history=history)["status"] == "pass"
    )
    docs = documents()
    docs.append(copy.deepcopy(docs[1]))
    assert result("R15", docs)["status"] == "fail"


def test_hs_hints_advisory_and_seal_absence():
    assert result("R11", config={"hs_description_chapters": {"Steel": ["84"]}})["status"] == "fail"
    docs = documents()
    for d in docs:
        d["fields"].pop("seal", None)
        d["fields"].pop("shipping_marks", None)
    assert result("R16", docs)["status"] == "not_applicable"


def test_evidence_and_purity():
    docs = documents()
    docs[0]["fields"]["consignee"] = {
        "normalized_value": "Meridian Manufacturing LLC",
        "raw_value": "MERIDIAN MANUFACTURING LLC",
        "page": 1,
        "evidence": "Consignee: MERIDIAN MANUFACTURING LLC",
        "grounded": True,
    }
    before = copy.deepcopy(docs)
    r = result("R02", docs)
    assert r["status"] == "pass"
    assert r["evidence_refs"][0]["page"] == 1
    assert docs == before
    assert pack_status([{"severity": "Major", "status": "fail"}]) == "Needs review"
    assert pack_status([{"severity": "Critical", "status": "fail"}]) == "Blocked"
    assert pack_status([{"severity": "Minor", "status": "fail"}]) == "Clean"


def test_domestic_optional_trade_fields_and_international_required():
    docs = documents()
    docs[1]["fields"].pop("incoterm")
    docs[1]["fields"]["lines"][0].pop("hs_code")
    assert result("R10", docs)["status"] == "not_applicable"
    assert result("R11", docs)["status"] == "not_applicable"
    assert result("R10", docs, {"mode": "road", "profile": "international"})["status"] == "fail"
    assert result("R11", docs, {"mode": "road", "profile": "international"})["status"] == "fail"


def test_malformed_lines_and_shipment_term_mismatch():
    docs = documents()
    docs[1]["fields"]["lines"] = ["not a structured line"]
    assert result("R08", docs)["status"] == "fail"
    assert result("R09", docs)["status"] == "fail"
    assert result("R10", shipment={"mode": "road", "incoterm": "DAP"})["status"] == "fail"


def test_unmatched_matrix_and_matching_hs_hint():
    assert (
        result(
            "R01",
            documents()[:3],
            config={
                "required_matrix": [
                    {"when": {"mode": "air"}, "required": ["certificate_of_origin"]}
                ]
            },
        )["status"]
        == "pass"
    )
    assert (
        result("R11", config={"hs_description_chapters": {"Steel": ["73"], "cotton": ["61"]}})[
            "status"
        ]
        == "pass"
    )


def test_invoice_postdates_dispatch_allowed_unless_configured():
    docs = documents()
    docs[1]["fields"]["invoice_date"] = "2026-10-05"
    assert result("R13", docs)["status"] == "pass"
    assert result("R13", docs, config={"require_invoice_before_dispatch": True})["status"] == "fail"
    assert result("R13", config={"require_invoice_before_dispatch": True})["status"] == "pass"

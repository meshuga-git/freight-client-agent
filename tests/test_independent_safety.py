"""Independent adversarial review regressions; no network or real data."""

import pytest
from docpipe.pipeline import grounded
from docpipe.normalization import normalize
from freight_agent.service import Store, Conflict, NotFound


def test_scalar_grounding_does_not_match_numeric_substring():
    assert not grounded("1", "Total: 100", {"text": "Total: 100", "has_text_layer": True})


def test_empty_value_cannot_be_grounded():
    assert not grounded("", "Total: 100", {"text": "Total: 100", "has_text_layer": True})


@pytest.mark.parametrize("raw", ["1,23", "1,,2"])
def test_ambiguous_grouping_not_silently_normalized(raw):
    assert normalize("total", raw) == raw


def test_money_integer_precision_preserved():
    assert str(normalize("total", "9007199254740993")).split(".")[0] == "9007199254740993"


def test_owner_isolation_and_stale_version(tmp_path):
    s = Store(tmp_path)
    pack = s.create("alice", {"synthetic": True})
    with pytest.raises(NotFound):
        s.get(pack["id"], "bob")
    with pytest.raises(NotFound):
        s.audit(pack["id"], "bob")
    with pytest.raises(NotFound):
        s.export(pack["id"], "bob", pack["version"], "json", "x")
    with pytest.raises(Conflict):
        s.confirm(pack["id"], "alice", pack["version"] - 1)


def test_grounding_binds_label_and_page():
    page = {"text": "Shipper: Acme\nConsignee: Globex", "has_text_layer": True}
    assert not grounded("Acme", "Shipper: Acme", page, "consignee")
    assert grounded("Globex", "Consignee: Globex", page, "consignee")
    assert not grounded("Acme", "Consignee: Acme", page, "consignee")


@pytest.mark.parametrize(
    "field,raw", [("total", "100 kg"), ("gross_weight_kg", "10 m3"), ("volume_m3", "10 lbs")]
)
def test_incompatible_units_not_silently_normalized(field, raw):
    assert normalize(field, raw) == raw


def _processed_store(tmp_path):
    s = Store(tmp_path)
    state = s.create("alice", {"synthetic": True})

    def field(value):
        return {
            "value": value,
            "normalized_value": value,
            "raw_value": str(value),
            "grounded": True,
            "confidence": 1,
            "page": 1,
            "evidence": str(value),
        }

    state["documents"] = [
        {
            "id": "transport",
            "type": "bill_of_lading",
            "type_confidence": 1,
            "fields": {"package_count": field(10), "consignee": field("Acme")},
        },
        {
            "id": "packing",
            "type": "packing_list",
            "type_confidence": 1,
            "fields": {"package_count": field(10)},
        },
    ]
    state["processed"] = True
    with s.transaction() as db:
        s._validate(db, state)
        s._save(db, state)
    return s, state


def test_correction_recomputes_rule_and_invalidates_confirm(tmp_path):
    s, p = _processed_store(tmp_path)
    p = s.review(
        p["id"],
        "alice",
        {
            "version": p["version"],
            "action": "correct",
            "document_id": "packing",
            "field": "package_count",
            "value": "11",
            "reason": "Source check",
        },
    )
    assert next(r for r in p["rules"] if r["rule_id"] == "R03")["status"] == "fail"
    assert p["confirmed_version"] is None
    assert p["documents"][1]["fields"]["package_count"]["normalized_value"] == 11
    with pytest.raises(Conflict):
        s.confirm(p["id"], "alice", p["version"] - 1)


def test_export_exact_version_idempotency_and_override_reasons(tmp_path):
    s, p = _processed_store(tmp_path)
    with pytest.raises(ValueError):
        s.review(
            p["id"],
            "alice",
            {"version": p["version"], "action": "override", "rule_id": "R01", "reason": "  "},
        )
    for rule in p["rules"]:
        if rule["status"] == "fail":
            p = s.review(
                p["id"],
                "alice",
                {
                    "version": p["version"],
                    "action": "override",
                    "rule_id": rule["rule_id"],
                    "reason": "Synthetic test only",
                },
            )
    p = s.confirm(p["id"], "alice", p["version"])
    a = s.export(p["id"], "alice", p["version"], "json", "same")
    b = s.export(p["id"], "alice", p["version"], "json", "same")
    assert a["payload"] == b["payload"] and b["replayed"]
    with pytest.raises(Conflict):
        s.export(p["id"], "alice", p["version"], "csv", "same")
    old = p["version"]
    p = s.review(
        p["id"],
        "alice",
        {
            "version": old,
            "action": "correct",
            "document_id": "packing",
            "field": "package_count",
            "value": "12",
            "reason": "Source check",
        },
    )
    assert p["overrides"] == {} and p["confirmed_version"] is None
    with pytest.raises(Conflict):
        s.export(p["id"], "alice", old, "json", "same")
    with pytest.raises(Conflict):
        s.export(p["id"], "alice", p["version"], "json", "new")


@pytest.mark.parametrize(
    "raw,snippet,source,field",
    [
        ("1", "Total: 1", "Total: 100", "total"),
        ("Acme", "Consignee: Acme", "Consignee: Acme Evil Corp", "consignee"),
    ],
)
def test_evidence_cannot_truncate_source_value(raw, snippet, source, field):
    assert not grounded(raw, snippet, {"text": source, "has_text_layer": True}, field)


def test_concurrent_reviews_allow_only_one_exact_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    s, p = _processed_store(tmp_path)

    def correction(value):
        try:
            s.review(
                p["id"],
                "alice",
                {
                    "version": p["version"],
                    "action": "correct",
                    "document_id": "packing",
                    "field": "package_count",
                    "value": value,
                    "reason": "Race probe",
                },
            )
            return "ok"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(correction, ["11", "12"]))
    assert sorted(results) == ["conflict", "ok"]


def test_profiles_enforce_transport_consistency(tmp_path):
    s = Store(tmp_path)
    p = s.create("alice", {"synthetic": True})
    assert (p["profile"], p["mode"], p["direction"], p["destination"]) == (
        "us_domestic_trucking",
        "road",
        "domestic",
        "US",
    )
    for profile in ["sea", "air", "international_road"]:
        with pytest.raises(ValueError):
            s.create("alice", {"synthetic": True, "profile": profile})
    p = s.create(
        "alice", {"synthetic": True, "profile": "air", "mode": "air", "direction": "export"}
    )
    assert p["mode"] == "air"

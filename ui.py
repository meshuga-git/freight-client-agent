"""Synthetic-only local review console. Start with: streamlit run ui.py."""

from __future__ import annotations

import json
import os
import time
import uuid
from urllib.parse import urlsplit

import httpx
import streamlit as st

st.set_page_config(page_title="Meridian | Freight Review", page_icon="🚚", layout="wide")
st.title("Meridian Freight · Document Review")
st.caption(
    "Fictional forwarder · Synthetic documents only · No customs filings or external TMS writes"
)
st.warning(
    "Screening, HS plausibility and Incoterm charge checks are advisory, not legal or compliance advice."
)

with st.sidebar:
    st.header("Local connection")
    base = st.text_input(
        "API address", os.getenv("FREIGHT_API_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    token = st.text_input(
        "Reviewer token", os.getenv("FREIGHT_UI_TOKEN", "demo-reviewer"), type="password"
    )
    st.caption("Demo token is for a local synthetic sandbox, not an internet-facing deployment.")


def api(method: str, path: str, *, raw: bool = False, **kwargs):
    try:
        parsed = urlsplit(base)
        if parsed.scheme != "http" or parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "api",
        }:
            st.error(
                "This synthetic sandbox only connects to a local API (localhost, loopback, or the Compose api service)."
            )
            return None
        with httpx.Client(timeout=120, trust_env=False) as client:
            response = client.request(
                method, base + path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            st.error(f"API {response.status_code}: {detail}")
            return None
        return response.content if raw else response.json()
    except (httpx.HTTPError, ValueError) as exc:
        st.error(f"Cannot complete request: {exc}")
        return None


with st.sidebar.expander("Create synthetic shipment"):
    with st.form("create"):
        profile = st.selectbox(
            "Profile", ["us_domestic_trucking", "international_road", "sea", "air"]
        )
        mode = "road" if profile in {"us_domestic_trucking", "international_road"} else profile
        direction = st.selectbox(
            "Direction",
            ["domestic", "export", "import"],
            index=0 if profile == "us_domestic_trucking" else 1,
        )
        incoterm = st.selectbox(
            "Incoterm",
            ["", "FCA", "DAP", "EXW", "CPT", "CIP", "DPU", "DDP", "FOB", "CIF", "CFR", "FAS"],
        )
        destination = st.text_input("Destination ISO country", "US")
        containerized = st.checkbox("Containerized shipment", value=profile == "sea")
        synthetic = st.checkbox("These are synthetic documents only")
        if st.form_submit_button("Create shipment"):
            if not synthetic:
                st.error("Confirm synthetic documents only before creating a shipment.")
            else:
                created = api(
                    "POST",
                    "/shipments",
                    json={
                        "profile": profile,
                        "mode": mode,
                        "direction": direction,
                        "incoterm": incoterm,
                        "destination": destination,
                        "synthetic": True,
                        "containerized": containerized,
                    },
                )
                if created:
                    st.session_state["active_shipment"] = created.get(
                        "id", created.get("shipment_id")
                    )
                    st.rerun()

shipments = api("GET", "/shipments")
if shipments is None:
    st.info("Start the API first. See README → Quick start.")
    st.stop()
if isinstance(shipments, dict):
    shipments = shipments.get("shipments", [])
if not shipments:
    st.info("Create a shipment in the sidebar, then upload generated synthetic PDFs.")
    st.stop()
ids = [row["id"] for row in shipments]
active = st.session_state.get("active_shipment")
index = ids.index(active) if active in ids else 0
shipment_id = st.sidebar.selectbox("Shipment", ids, index=index)
shipment = api("GET", f"/shipments/{shipment_id}")
if shipment is None:
    st.stop()
version = shipment["version"]
columns = st.columns(4)
columns[0].metric("Status", shipment.get("status", "Pending"))
columns[1].metric("Version", version)
columns[2].metric("Mode", shipment.get("mode", "road"))
columns[3].metric("Documents", len(shipment.get("documents", [])))
st.caption(
    "Every edit invalidates prior confirmation. Confirm and export the current version only."
)

with st.expander("Upload and process synthetic PDFs", expanded=not shipment.get("documents")):
    uploads = st.file_uploader("Document pack", type=["pdf"], accept_multiple_files=True)
    synthetic_upload = st.checkbox(
        "I confirm these uploads contain no real client or personal data"
    )
    left, right = st.columns(2)
    if left.button("Upload selected files", disabled=not uploads or not synthetic_upload):
        succeeded = True
        for upload in uploads:
            result = api(
                "POST",
                f"/shipments/{shipment_id}/documents",
                files={"file": (upload.name, upload.getvalue(), "application/pdf")},
            )
            succeeded = succeeded and result is not None
        if succeeded:
            st.rerun()
    if right.button("Process current pack"):
        with st.spinner("Rendering, extracting and validating…"):
            result = api("POST", f"/shipments/{shipment_id}/process")
        if result is not None:
            st.rerun()

rules = shipment.get("rules", shipment.get("validations", []))
exceptions = [rule for rule in rules if rule.get("status") == "fail"]
severity = {"Critical": 0, "Major": 1, "Minor": 2, "critical": 0, "major": 1, "minor": 2}
exceptions.sort(key=lambda rule: severity.get(rule.get("severity"), 3))
st.subheader("Exceptions first")
if not exceptions:
    st.info(
        "No failing rules listed. Check extraction issues and processing status before confirmation."
    )
for i, rule in enumerate(exceptions):
    with st.expander(
        f"{rule.get('severity')} · {rule.get('rule_id')} · {rule.get('details')}", expanded=i == 0
    ):
        st.json(rule)
        with st.form(f"override_{rule.get('rule_id')}_{i}"):
            reason = st.text_area("Override reason (required)")
            acknowledged = st.checkbox(
                "I reviewed the evidence; this is a deliberate reviewer override, not a corrected fact"
            )
            if st.form_submit_button("Record override"):
                if not acknowledged:
                    st.error("Acknowledge the evidence review before overriding.")
                elif not reason.strip():
                    st.error("A nonblank reason is required.")
                elif (
                    api(
                        "POST",
                        f"/shipments/{shipment_id}/review",
                        json={
                            "version": version,
                            "action": "override",
                            "rule_id": rule["rule_id"],
                            "reason": reason,
                        },
                    )
                    is not None
                ):
                    st.rerun()
with st.expander("All validation results / applicability"):
    st.json(rules)

st.subheader("Source and extracted fields")
documents = shipment.get("documents", [])
if documents:
    doc_index = st.selectbox(
        "Document",
        range(len(documents)),
        format_func=lambda i: f"{documents[i].get('type', 'unknown')} · {documents[i]['id']}",
    )
    document = documents[doc_index]
    if document.get("issues"):
        st.error("Extraction issues require review")
        st.json(document["issues"])
    fields = document.get("fields", {})
    names = list(fields)
    field = st.selectbox("Evidence field", names) if names else None
    item = fields[field] if field else {}
    if not isinstance(item, dict):
        item = {"value": item}
    source, values = st.columns([1.15, 1])
    with source:
        page_numbers = [
            page.get("number", i + 1) for i, page in enumerate(document.get("pages", []))
        ] or [item.get("page", 1)]
        default_page = item.get("page", page_numbers[0])
        page_number = st.selectbox(
            "Page",
            page_numbers,
            index=page_numbers.index(default_page) if default_page in page_numbers else 0,
        )
        content = api(
            "GET",
            f"/shipments/{shipment_id}/pages/{document['id']}/{page_number}",
            raw=True,
            params={"field": field} if field else {},
        )
        if content:
            st.image(
                content,
                caption="Original source rendering; selected evidence highlighted where available",
                use_container_width=True,
            )
        if item.get("evidence"):
            st.text_area("Verbatim evidence", str(item["evidence"]), disabled=True)
    with values:
        if field:
            st.write(f"**{field}**")
            st.json(item)
            st.caption(
                "Grounded means supported by the source, not independently true. Offline mode is deterministic template parsing, not LLM extraction."
            )
            with st.form("field_review"):
                action = st.radio("Review action", ["accept", "correct"], horizontal=True)
                value_text = st.text_area(
                    "Corrected value (JSON for arrays/numbers; plain text accepted)",
                    json.dumps(item.get("value"), ensure_ascii=False),
                )
                reason = st.text_input("Review reason")
                if st.form_submit_button("Save review"):
                    if not reason.strip():
                        st.error("A reason is required.")
                    else:
                        try:
                            value = json.loads(value_text)
                        except ValueError:
                            value = value_text
                        payload = {
                            "version": version,
                            "action": action,
                            "document_id": document["id"],
                            "field": field,
                            "value": value,
                            "reason": reason,
                        }
                        if (
                            api("POST", f"/shipments/{shipment_id}/review", json=payload)
                            is not None
                        ):
                            st.rerun()
        with st.expander("All extracted fields"):
            st.json(fields)

st.subheader("Human confirmation and local export")
confirm = st.checkbox(
    f"I reviewed this synthetic shipment at version {version}",
    key=f"confirm_{shipment_id}_{version}",
)
if st.button("Confirm current version", disabled=not confirm):
    if api("POST", f"/shipments/{shipment_id}/confirm", json={"version": version}) is not None:
        st.success("Current version confirmed.")
        st.rerun()
format_name = st.selectbox("Export format", ["json", "csv", "mock_tms"])
key_name = f"export_key_{shipment_id}_{version}_{format_name}"
if key_name not in st.session_state:
    st.session_state[key_name] = str(uuid.uuid4())
if st.button("Create confirmed export"):
    result = api(
        "POST",
        f"/shipments/{shipment_id}/exports",
        json={
            "version": version,
            "format": format_name,
            "idempotency_key": st.session_state[key_name],
        },
    )
    if result is not None:
        st.session_state["last_export"] = {
            "shipment": shipment_id,
            "version": version,
            "result": result,
        }
last = st.session_state.get("last_export", {})
if last.get("shipment") == shipment_id and last.get("version") == version:
    st.json(last["result"])
    receipt = last["result"]
    export_format = receipt.get("format", format_name)
    payload = receipt.get("payload", receipt)
    if not isinstance(payload, str):
        payload = json.dumps(payload, indent=2)
    extension = "csv" if export_format == "csv" else "json"
    st.download_button(
        "Download export payload",
        payload,
        f"{shipment_id}-v{version}.{extension}",
        "text/csv" if extension == "csv" else "application/json",
    )
st.caption("Mock TMS records a local receipt only. No network dispatch or customs filing occurs.")

with st.expander("Audit trail"):
    if st.button("Load shipment audit"):
        result = api("GET", f"/shipments/{shipment_id}/audit")
        if result is not None:
            st.json(result)
with st.sidebar.expander("Reviewer timing (local session only)"):
    timer_key = f"review_timer_{shipment_id}"
    if st.button("Start timing"):
        st.session_state[timer_key] = time.perf_counter()
    if st.button("Stop timing"):
        started = st.session_state.pop(timer_key, None)
        if started is not None:
            st.session_state.setdefault("review_timings", []).append(
                {
                    "shipment_id": shipment_id,
                    "seconds": round(time.perf_counter() - started, 2),
                    "kind": "review_ui",
                }
            )
    timings = st.session_state.get("review_timings", [])
    if timings:
        st.json(timings)
        st.download_button(
            "Download timing observations",
            json.dumps(timings, indent=2),
            "review-timings.json",
            "application/json",
        )
    st.caption(
        "Timing is manual and not a benchmark. Collect a separate 10-pack manual baseline before making a time-saving claim."
    )

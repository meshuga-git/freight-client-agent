"""Streamlit state-machine smoke using the actual API, without a network server."""

from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from freight_agent.api import create_app
from freight_agent.corpus import generate


def test_ui_create_review_confirm_export(tmp_path):
    client = TestClient(create_app(tmp_path / "store"))

    class LocalClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, url, **kwargs):
            return client.request(method, urlsplit(url).path, **kwargs)

    with patch("httpx.Client", LocalClient):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "ui.py")).run(timeout=20)
        assert not app.exception
        next(x for x in app.checkbox if x.label == "These are synthetic documents only").check()
        next(x for x in app.button if x.label == "Create shipment").click().run(timeout=20)
        assert not app.exception
        assert len(app.metric) == 4
    # Seed a generated pack through the same API; the UI must render actual evidence.
    manifest = generate(tmp_path / "corpus", count=2, seed=42)
    headers = {"Authorization": "Bearer demo-reviewer"}
    sid = client.get("/shipments", headers=headers).json()[0]["id"]
    pack = manifest["packs"][0]
    for name in pack["files"]:
        path = tmp_path / "corpus" / pack["id"] / name
        response = client.post(
            f"/shipments/{sid}/documents",
            headers=headers,
            files={"file": (name, path.read_bytes(), "application/pdf")},
        )
        assert response.status_code == 200
    response = client.post(f"/shipments/{sid}/process", headers=headers)
    assert response.status_code == 200
    with patch("httpx.Client", LocalClient):
        app.run(timeout=20)
        assert not app.exception
        assert next(x for x in app.selectbox if x.label == "Evidence field")
        next(x for x in app.text_input if x.label == "Review reason").set_value(
            "Checked original evidence"
        )
        next(x for x in app.button if x.label == "Save review").click().run(timeout=20)
        assert not app.exception
        assert not app.error
        next(
            x for x in app.checkbox if x.label.startswith("I reviewed this synthetic shipment")
        ).check().run()
        next(x for x in app.button if x.label == "Confirm current version").click().run(timeout=20)
        assert not app.exception
        assert not app.error
        next(x for x in app.button if x.label == "Create confirmed export").click().run(timeout=20)
        assert not app.exception
        assert not app.error
        assert "last_export" in app.session_state

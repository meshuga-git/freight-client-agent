import io
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from freight_agent.api import create_app


def pdf(text="Bill of Lading"):
    out = io.BytesIO()
    c = canvas.Canvas(out)
    c.drawString(60, 750, text)
    c.save()
    return out.getvalue()


def test_api_auth_profiles_upload_and_render(tmp_path):
    client = TestClient(create_app(tmp_path, {"a": "alice", "b": "bob", "g": "guest"}))
    h = {"Authorization": "Bearer a"}
    assert client.get("/health").json()["external_writes"] is False
    assert client.get("/shipments").status_code == 401
    assert client.post("/shipments", headers=h, json={"synthetic": False}).status_code == 422
    assert (
        client.post("/shipments", headers=h, json={"synthetic": True, "profile": "sea"}).status_code
        == 422
    )
    assert (
        client.post(
            "/shipments", headers={"Authorization": "Bearer g"}, json={"synthetic": True}
        ).status_code
        == 403
    )
    state = client.post("/shipments", headers=h, json={"synthetic": True}).json()
    sid = state["id"]
    assert state["profile"] == "us_domestic_trucking"
    assert client.get("/shipments/" + sid, headers={"Authorization": "Bearer b"}).status_code == 404
    assert (
        client.post(
            f"/shipments/{sid}/documents", headers=h, files={"file": ("bad.pdf", b"not pdf")}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/shipments/{sid}/documents", headers=h, files={"file": ("demo.pdf", pdf())}
        ).status_code
        == 200
    )
    processed = client.post(f"/shipments/{sid}/process", headers=h).json()
    assert processed["status"] == "Blocked"
    did = processed["documents"][0]["id"]
    response = client.get(f"/shipments/{sid}/pages/{did}/1", headers=h)
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    assert client.get(f"/shipments/{sid}/pages/{did}/2", headers=h).status_code == 404
    assert (
        client.post(
            f"/shipments/{sid}/confirm", headers=h, json={"version": processed["version"]}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/shipments/{sid}/exports",
            headers=h,
            json={"version": processed["version"], "format": "json", "idempotency_key": "a"},
        ).status_code
        == 409
    )


def test_fifty_concurrent_local_creates(tmp_path):
    app = create_app(tmp_path, {"a": "alice"})

    def create(_):
        with TestClient(app) as client:
            return client.post(
                "/shipments", headers={"Authorization": "Bearer a"}, json={"synthetic": True}
            )

    with ThreadPoolExecutor(max_workers=50) as pool:
        responses = list(pool.map(create, range(50)))
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 50


def test_processing_exception_invalidates(tmp_path, monkeypatch):
    from freight_agent.service import Store
    import docpipe

    store = Store(tmp_path)
    s = store.create("alice", {"synthetic": True})
    store.add_upload(s["id"], "alice", "demo.pdf", pdf())
    monkeypatch.setattr(
        docpipe,
        "process_pdf",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider secret")),
    )
    state = store.process(s["id"], "alice")
    assert state["status"] == "Blocked" and state["confirmed_version"] is None
    assert "provider secret" not in str(state)

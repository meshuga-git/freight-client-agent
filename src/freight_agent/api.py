"""Local synthetic-only API. Bearer identities are isolated by shipment owner."""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Literal, Any
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Header
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .service import Store, Conflict, NotFound, Forbidden


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateShipment(Strict):
    synthetic: bool
    profile: Literal["us_domestic_trucking", "international_road", "sea", "air"] = (
        "us_domestic_trucking"
    )
    mode: Literal["road", "sea", "air"] = "road"
    direction: Literal["domestic", "import", "export"] = "domestic"
    incoterm: str = Field(default="", max_length=20)
    destination: str = Field(default="US", max_length=2)
    containerized: bool = False


class Version(Strict):
    version: int = Field(ge=1)


class Review(Version):
    action: Literal["correct", "accept", "override"]
    document_id: str | None = None
    field: str | None = None
    value: Any = None
    rule_id: str | None = None
    reason: str = Field(min_length=1, max_length=2000)


class Export(Version):
    format: Literal["json", "csv", "mock_tms"]
    idempotency_key: str = Field(min_length=1, max_length=128)


class BodyTooLarge(Exception):
    pass


class BodyLimit:
    """Enforce wire body cap before multipart spooling, including chunked bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0
        limit = 21 * 1024 * 1024

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                raise BodyTooLarge()
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except BodyTooLarge:
            await JSONResponse({"detail": "Request body exceeds 21 MiB"}, status_code=413)(
                scope, receive, send
            )


def create_app(root=None, tokens=None):
    app = FastAPI(title="Meridian Freight — synthetic portfolio", version="0.1.0")
    app.add_middleware(BodyLimit)
    store = Store(root or os.getenv("FREIGHT_DATA_DIR", "runtime"))
    identities = tokens or json.loads(
        os.getenv("FREIGHT_TOKENS", '{"demo-reviewer":"reviewer","demo-guest":"guest"}')
    )
    app.state.store = store

    def actor(authorization: str = Header(default="")):
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or token not in identities:
            raise HTTPException(401, "Valid bearer token required")
        return identities[token]

    def invoke(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFound as e:
            raise HTTPException(404, str(e)) from e
        except Forbidden as e:
            raise HTTPException(403, str(e)) from e
        except Conflict as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "synthetic_only": True,
            "database": "sqlite",
            "object_storage": "local-files",
            "external_writes": False,
        }

    @app.get("/shipments")
    def listing(user=Depends(actor)):
        return store.list(user)

    @app.post("/shipments", status_code=201)
    def create(data: CreateShipment, user=Depends(actor)):
        if data.profile == "us_domestic_trucking" and (
            data.mode != "road" or data.direction != "domestic" or data.destination != "US"
        ):
            raise HTTPException(
                422,
                "Domestic profile requires road/domestic/US; choose an explicit multimodal profile",
            )
        return invoke(store.create, user, data.model_dump())

    @app.get("/shipments/{sid}")
    def get(sid: str, user=Depends(actor)):
        return invoke(store.get, sid, user)

    @app.post("/shipments/{sid}/documents")
    async def upload(sid: str, file: UploadFile = File(...), user=Depends(actor)):
        invoke(store.get, sid, user)
        content = await file.read(20 * 1024 * 1024 + 1)
        return await asyncio.to_thread(
            invoke, store.add_upload, sid, user, file.filename or "upload.pdf", content
        )

    @app.post("/shipments/{sid}/process")
    async def process(sid: str, user=Depends(actor)):
        from docpipe import Settings

        settings = Settings(
            api_key=os.getenv("FREIGHT_LLM_API_KEY", ""),
            api_base=os.getenv("FREIGHT_LLM_API_BASE", "https://api.openai.com/v1"),
            model=os.getenv("FREIGHT_LLM_MODEL", ""),
            stronger_model=os.getenv("FREIGHT_LLM_STRONGER_MODEL", ""),
        )
        return await asyncio.to_thread(
            invoke, store.process, sid, user, os.getenv("FREIGHT_BACKEND", "offline"), settings
        )

    @app.post("/shipments/{sid}/review")
    def review(sid: str, data: Review, user=Depends(actor)):
        return invoke(store.review, sid, user, data.model_dump())

    @app.post("/shipments/{sid}/confirm")
    def confirm(sid: str, data: Version, user=Depends(actor)):
        return invoke(store.confirm, sid, user, data.version)

    @app.post("/shipments/{sid}/exports")
    def export(sid: str, data: Export, user=Depends(actor)):
        return invoke(store.export, sid, user, data.version, data.format, data.idempotency_key)

    @app.get("/shipments/{sid}/audit")
    def audit(sid: str, user=Depends(actor)):
        return invoke(store.audit, sid, user)

    @app.get("/shipments/{sid}/pages/{docid}/{number}")
    def page(sid: str, docid: str, number: int, field: str | None = None, user=Depends(actor)):
        import fitz

        state = invoke(store.get, sid, user)
        doc = next((d for d in state["documents"] if d["id"] == docid), None)
        if not doc:
            raise HTTPException(404, "Document not found")
        if not any(p["number"] == number for p in doc["pages"]):
            raise HTTPException(404, "Page not part of document")
        upload = next(u for u in state["uploads"] if u["id"] == doc["upload_id"])
        path = Path(upload["path"]).resolve()
        if not path.is_relative_to(store.root / sid):
            raise HTTPException(404, "Source unavailable")
        with fitz.open(path) as pdf:
            page = pdf[number - 1]
            if field:
                item = doc["fields"].get(field, {})
                if item.get("page") == number:
                    for rect in page.search_for(item.get("evidence", "")):
                        page.add_highlight_annot(rect)
            scale = min(1.25, (4_000_000 / max(page.rect.width * page.rect.height, 1)) ** 0.5)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return Response(
                pix.tobytes("png"), media_type="image/png", headers={"Cache-Control": "no-store"}
            )

    return app


app = create_app()

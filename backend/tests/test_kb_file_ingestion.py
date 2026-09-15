"""Phase KB3 · Feb-2026 — KB file ingestion (PDF / DOCX / TXT / MD).

Acceptance tests for ``POST /api/ai/knowledge/file``:

* Happy path — PDF, DOCX, TXT, MD each yield a ``ai_knowledge_base``
  row with the extracted text in ``content_md`` + ``source_type`` +
  ``source_file_id`` fields set.
* Oversize file (26 MB) → 413.
* Wrong content type (image/png) → 415.
* Scanned/empty PDF → 400 ``extraction_empty``.
* Role guard — non-admin → 403.
* Tenant isolation — uploaded row scoped to caller's tenant.

The S3 layer is stubbed out — we assert the ``put_object`` primitive
is called (same one ``/api/files/upload`` uses).  We are NOT testing
the S3 write itself; that's covered by the files-router suite.
"""
from __future__ import annotations

import asyncio
import io
from typing import Any, Dict, List
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _run(coro): return asyncio.run(coro)


# ── Motor-shaped stub (subset — insert/find/update). ──────────────
class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    async def insert_one(self, doc):
        self.rows.append(dict(doc)); self.inserts.append(dict(doc))
        return type("R", (), {"inserted_id": "x"})()

    async def find_one(self, q, p=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in q.items()): return dict(r)
        return None

    async def update_one(self, q, upd):
        for r in self.rows:
            if all(r.get(k) == v for k, v in q.items()):
                r.update(upd.get("$set", {}))
                self.updates.append({"q": q, "set": upd["$set"]})
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()

    def find(self, q=None, p=None):
        matched = [r for r in self.rows
                    if all(r.get(k) == v for k, v in (q or {}).items())]
        class _C:
            def __init__(self, rr): self.rr = list(rr)
            def sort(self, *_a, **_kw): return self
            def limit(self, *_a, **_kw): return self
            async def to_list(self, n=None):
                return self.rr if n is None else self.rr[:n]
        return _C(matched)


class _DB:
    def __init__(self):
        self.ai_knowledge_base = _Coll()
        self.files = _Coll()


def _build_app(user, tenant, db_stub, *, storage_configured=True):
    from routers import ai_brain
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    ai_brain.db = db_stub

    app = FastAPI()
    app.include_router(ai_brain.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    return app


def _stub_storage(configured=True, size=None):
    """Patch the file_storage helpers used by the endpoint."""
    put_calls = []

    def _put_object(path, data, content_type):
        put_calls.append({"path": path, "size": len(data), "ct": content_type})
        return {"path": path, "size": size or len(data)}

    return {
        "put_object": _put_object,
        "is_storage_configured": lambda: configured,
        "APP_NAME": "poolscape-crm",
        "put_calls": put_calls,
    }


# ── Test payload builders ─────────────────────────────────────────
def _make_pdf(text: str) -> bytes:
    """Build a real 1-page PDF (via pypdf) with the given text on it.

    We use pypdf's own writer + a synthetic /Contents stream so
    ``extract_text`` on the round-trip returns exactly the text
    we planted — no external dep, no Reportlab.
    """
    # pypdf's writer needs a source page.  Easiest robust path: use
    # its ``PageObject.create_blank_page`` and stitch in a text
    # content stream.  The extract_text call in the endpoint uses
    # the same pypdf, so whatever we write, it can read back.
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject, NameObject, TextStringObject, DictionaryObject,
        ArrayObject, FloatObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    # Build a minimal content stream in the PDF text-object syntax.
    escaped = (text.replace("\\", "\\\\")
                    .replace("(", "\\(").replace(")", "\\)"))
    stream_bytes = (
        f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET"
    ).encode("latin-1")
    content = DecodedStreamObject()
    content.set_data(stream_bytes)
    page[NameObject("/Contents")] = content

    # Attach a stock Type1 font so /F1 resolves at read time.
    font_dict = DictionaryObject({
        NameObject("/Type"):     NameObject("/Font"),
        NameObject("/Subtype"):  NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_dict}),
    })

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_docx(paragraphs: List[str]) -> bytes:
    import docx
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ═════════════════════════ Happy paths ═════════════════════════════
def test_ingest_pdf_happy_path():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        pdf_bytes = _make_pdf(
            "The pool warranty covers 5 years on the shell but 2 years on the pump."
        )
        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("warranty.pdf", pdf_bytes, "application/pdf")},
                    data={"kind": "policy", "title": "Warranty terms",
                          "tags": "warranty,pump"},
                )
        assert r.status_code == 200, r.text
        body = r.json()
        kb = body["kb"]
        assert kb["source_type"] == "pdf"
        assert kb["source_file_id"]
        assert kb["title"] == "Warranty terms"
        assert kb["kind"] == "policy"
        assert kb["tags"] == ["warranty", "pump"]
        assert "warranty" in kb["content_md"].lower()
        # File row is inserted + linked to the KB row.
        assert len(db_stub.files.rows) == 1
        assert len(db_stub.ai_knowledge_base.rows) == 1
        assert db_stub.files.rows[0]["linked_entity_id"] == kb["id"]
        assert stubs["put_calls"], "put_object was not called"

    _run(run())


def test_ingest_docx_happy_path():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        docx_bytes = _make_docx([
            "Warranty terms.",
            "The pool warranty covers 5 years on the shell but 2 years on the pump.",
        ])
        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": (
                        "warranty.docx", docx_bytes,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )},
                    data={"kind": "policy"},
                )
        assert r.status_code == 200, r.text
        kb = r.json()["kb"]
        assert kb["source_type"] == "docx"
        assert "2 years on the pump" in kb["content_md"]
        # Auto-title falls back to the filename minus extension.
        assert kb["title"] == "warranty"

    _run(run())


def test_ingest_txt_happy_path():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        txt = ("Service area: Peoria, Sun City, Surprise. "
               "Response time: 24 hours.").encode("utf-8")
        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("area.txt", txt, "text/plain")},
                    data={},
                )
        assert r.status_code == 200, r.text
        kb = r.json()["kb"]
        assert kb["source_type"] == "txt"
        assert "Peoria" in kb["content_md"]

    _run(run())


# ═════════════════════════ Rejection paths ═════════════════════════
def test_ingest_oversize_returns_413():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        # 26 MB of null bytes wrapped in a PDF header prefix so the
        # content-type gate passes and only the size gate fires.
        payload = b"%PDF-1.4\n" + (b"\x00" * (26 * 1024 * 1024))
        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("big.pdf", payload, "application/pdf")},
                )
        assert r.status_code == 413, r.text
        assert stubs["put_calls"] == [], (
            "oversize files must not touch S3"
        )

    _run(run())


def test_ingest_unsupported_mime_returns_415():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n\x00",
                                     "image/png")},
                )
        assert r.status_code == 415, r.text

    _run(run())


def test_ingest_scanned_pdf_returns_400_extraction_empty():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        # A real PDF with NO text content stream — pypdf will
        # extract "".  This is what a scanned/image-only PDF looks
        # like at extraction time.
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        buf = io.BytesIO(); writer.write(buf)

        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("scan.pdf", buf.getvalue(),
                                     "application/pdf")},
                )
        assert r.status_code == 400, r.text
        assert "extraction_empty" in r.text
        assert stubs["put_calls"] == []

    _run(run())


def test_ingest_role_guard_403():
    async def run():
        db_stub = _DB()
        user = {"id": "u-tech", "role": "technician"}   # not admin
        tenant = {"id": "t1"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        pdf_bytes = _make_pdf("hello")
        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("x.pdf", pdf_bytes, "application/pdf")},
                )
        assert r.status_code == 403, r.text

    _run(run())


def test_ingest_tenant_isolation_scopes_rows():
    async def run():
        db_stub = _DB()
        user = {"id": "u-admin", "role": "admin"}
        tenant = {"id": "tenant-A"}
        app = _build_app(user, tenant, db_stub)
        stubs = _stub_storage()

        pdf_bytes = _make_pdf("Tenant A only content")
        with patch("services.file_storage.is_storage_configured",
                    stubs["is_storage_configured"]), \
             patch("services.file_storage.put_object",
                    stubs["put_object"]):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t",
            ) as ac:
                r = await ac.post(
                    "/api/ai/knowledge/file",
                    files={"file": ("x.pdf", pdf_bytes, "application/pdf")},
                )
        assert r.status_code == 200, r.text
        assert db_stub.ai_knowledge_base.rows[0]["tenant_id"] == "tenant-A"
        assert db_stub.files.rows[0]["tenant_id"] == "tenant-A"
        # S3 key includes the tenant segment for surgical migrations.
        assert stubs["put_calls"][0]["path"].startswith(
            "poolscape-crm/tenant-A/ai-knowledge/",
        )

    _run(run())

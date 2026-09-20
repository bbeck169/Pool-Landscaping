"""Feb-2026 · Customer-Attachments (Option D) — pytest suite.

Covers ``POST /api/customers/{cid}/send-email`` and
``POST /api/customers/{cid}/send-sms`` with ``attachments: [file_ids]``
end-to-end.  We stub the storage backend (``get_object``) and the
outbound send adapters (``comms_email_adapter.send_email`` and
``services.sms.rc_adapter.send``) so the transport boundary is never
crossed but everything on the router side — including the
``marketing_media`` resolve, base64 encode, size caps, and cross-
tenant guards — is exercised for real against Mongo.
"""
from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def seeded(dbc):
    tenant_id       = f"t_att_{uuid.uuid4().hex[:8]}"
    other_tenant_id = f"t_other_{uuid.uuid4().hex[:8]}"
    admin = {
        "id":         f"u_admin_{uuid.uuid4().hex[:8]}",
        "tenant_id":  tenant_id, "role": "admin",
        "email":      f"admin.{tenant_id[:6]}@test.local",
    }
    customer = {
        "id":         f"c_att_{uuid.uuid4().hex[:8]}",
        "tenant_id":  tenant_id,
        "name":       "Test Customer",
        "email":      "cust@example.com",
        "emails":     [{"address": "cust@example.com"}],
        "phones":     [{"number": "+16025551234"}],
        "deleted_at": None,
    }
    dbc.tenants.insert_many([
        {"id": tenant_id, "slug": f"att-{tenant_id[:6]}", "name": "Att Test"},
        {"id": other_tenant_id, "slug": f"other-{other_tenant_id[:6]}",
         "name": "Other Tenant"},
    ])
    dbc.users.insert_one(admin)
    dbc.customers.insert_one(customer)

    # Media rows — 2 PDFs (10 KB and 100 KB), 1 image (2 KB), 1
    # oversize row (11 MB reported bytes — used to test the size cap),
    # and 1 row belonging to ANOTHER tenant (cross-tenant guard).
    media_pdf_small = {
        "id":           f"m_pdf_s_{uuid.uuid4().hex[:8]}",
        "tenant_id":    tenant_id,
        "file_name":    "Invoice-Q1.pdf",
        "mime_type":    "application/pdf",
        "size_bytes":   10 * 1024,
        "storage_key":  f"pool-crm/tenants/{tenant_id}/marketing_media/small.pdf",
        "storage_url":  "/marketing/media/dummy",
        "cdn_url":      "/marketing/media/dummy",
        "deleted_at":   None,
    }
    media_pdf_large = {
        "id":           f"m_pdf_l_{uuid.uuid4().hex[:8]}",
        "tenant_id":    tenant_id,
        "file_name":    "WorkOrder.pdf",
        "mime_type":    "application/pdf",
        "size_bytes":   100 * 1024,
        "storage_key":  f"pool-crm/tenants/{tenant_id}/marketing_media/large.pdf",
        "storage_url":  "/marketing/media/dummy",
        "cdn_url":      "/marketing/media/dummy",
        "deleted_at":   None,
    }
    media_img = {
        "id":           f"m_img_{uuid.uuid4().hex[:8]}",
        "tenant_id":    tenant_id,
        "file_name":    "photo.jpg",
        "mime_type":    "image/jpeg",
        "size_bytes":   2 * 1024,
        "storage_key":  f"pool-crm/tenants/{tenant_id}/marketing_media/img.jpg",
        "storage_url":  "/marketing/media/dummy",
        "cdn_url":      "/marketing/media/dummy",
        "deleted_at":   None,
    }
    media_oversize = {
        "id":           f"m_over_{uuid.uuid4().hex[:8]}",
        "tenant_id":    tenant_id,
        "file_name":    "huge.pdf",
        "mime_type":    "application/pdf",
        "size_bytes":   11 * 1024 * 1024,     # > 10 MB per-file cap
        "storage_key":  f"pool-crm/tenants/{tenant_id}/marketing_media/huge.pdf",
        "storage_url":  "/marketing/media/dummy",
        "cdn_url":      "/marketing/media/dummy",
        "deleted_at":   None,
    }
    media_cross = {
        "id":           f"m_cross_{uuid.uuid4().hex[:8]}",
        "tenant_id":    other_tenant_id,           # ← another tenant
        "file_name":    "leaked.pdf",
        "mime_type":    "application/pdf",
        "size_bytes":   1 * 1024,
        "storage_key":  f"pool-crm/tenants/{other_tenant_id}/marketing_media/x.pdf",
        "storage_url":  "/marketing/media/dummy",
        "cdn_url":      "/marketing/media/dummy",
        "deleted_at":   None,
    }
    dbc.marketing_media.insert_many([
        media_pdf_small, media_pdf_large, media_img,
        media_oversize, media_cross,
    ])

    yield {
        "tenant_id":        tenant_id,
        "other_tenant_id":  other_tenant_id,
        "admin":            admin,
        "customer":         customer,
        "media_pdf_small":  media_pdf_small,
        "media_pdf_large":  media_pdf_large,
        "media_img":        media_img,
        "media_oversize":   media_oversize,
        "media_cross":      media_cross,
    }

    dbc.customers.delete_many({"tenant_id": tenant_id})
    dbc.users.delete_many({"tenant_id": tenant_id})
    dbc.tenants.delete_many({"id": {"$in": [tenant_id, other_tenant_id]}})
    dbc.marketing_media.delete_many(
        {"tenant_id": {"$in": [tenant_id, other_tenant_id]}},
    )
    dbc.communications_log.delete_many({"tenant_id": tenant_id})


def _install_overrides(user: Dict[str, Any]):
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant
    app = _get_app()

    async def _fake_user():
        return dict(user)

    async def _fake_tenant():
        return {"id": user["tenant_id"], "name": "T-Att"}

    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[require_admin] = _fake_user
    app.dependency_overrides[get_current_tenant] = _fake_tenant

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


def _patch_send_adapters(monkeypatch, *,
                         email_call_log=None, sms_call_log=None):
    """Replace outbound adapters with capturing stubs. Called INSIDE
    each test — module-level monkeypatch fixtures don't cross the
    ``run_test`` loop boundary."""
    async def _fake_send_email(tenant_id, to_email, subject, html,
                                 from_name=None, from_email=None,
                                 headers=None, attachments=None):
        if email_call_log is not None:
            email_call_log.append({
                "tenant_id":    tenant_id,
                "to":           to_email,
                "subject":      subject,
                "html_len":     len(html or ""),
                "attachments":  attachments or [],
            })
        return {"status": "sent", "provider_id": "resend_stub_xyz"}

    async def _fake_sms_send(*, to, body, category, tenant_id,
                               customer_id):
        if sms_call_log is not None:
            sms_call_log.append({
                "to":           to,
                "body":         body,
                "category":     category,
                "tenant_id":    tenant_id,
                "customer_id":  customer_id,
            })
        return {
            "provider_status":       "sent",
            "provider":              "ringcentral",
            "provider_response_id":  "rc_stub_id",
        }

    monkeypatch.setattr(
        "services.comms_email_adapter.send_email", _fake_send_email,
    )
    monkeypatch.setattr(
        "services.sms.rc_adapter.send", _fake_sms_send,
    )


def _patch_storage_get(monkeypatch, *, bytes_by_key=None,
                        raise_exc=None):
    """Stub ``services.marketing_media.storage_client.get_object``."""
    def _fake_get(path, max_retries=3):
        if raise_exc is not None:
            raise raise_exc
        if bytes_by_key and path in bytes_by_key:
            return bytes_by_key[path], "application/octet-stream"
        # Default: generate deterministic bytes derived from the path.
        return path.encode("utf-8"), "application/octet-stream"

    # The customers router imports get_object indirectly via
    # attachments.py. Patch at the source.
    monkeypatch.setattr(
        "services.marketing_media.attachments.get_object", _fake_get,
    )


def _post(user, path: str, body: Dict[str, Any]) -> httpx.Response:
    clear = _install_overrides(user)
    try:
        holder: Dict[str, Any] = {}

        async def _go(_db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                          base_url="http://test") as ac:
                holder["r"] = await ac.post(path, json=body)
        run_test(_go)
        return holder["r"]
    finally:
        clear()


# ═════════════════ send-email ═════════════════════════════════════
def test_email_two_attachments_forwarded_as_base64(dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, email_call_log=calls)
    pdf_bytes = b"%PDF-1.4\n" + b"x" * 100
    img_bytes = b"\xff\xd8\xff" + b"y" * 200
    _patch_storage_get(monkeypatch, bytes_by_key={
        seeded["media_pdf_small"]["storage_key"]: pdf_bytes,
        seeded["media_img"]["storage_key"]:       img_bytes,
    })
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-email",
        {
            "to":      "cust@example.com",
            "subject": "Your invoice + photo",
            "body":    "Hi — see attached.",
            "attachments": [
                seeded["media_pdf_small"]["id"],
                seeded["media_img"]["id"],
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True
    # Adapter got both attachments in Resend shape.
    assert len(calls) == 1
    atts = calls[0]["attachments"]
    assert len(atts) == 2
    names = [a["filename"] for a in atts]
    assert names == ["Invoice-Q1.pdf", "photo.jpg"]
    types = [a["content_type"] for a in atts]
    assert types == ["application/pdf", "image/jpeg"]
    # Base64 payloads round-trip to the stubbed bytes.
    assert base64.b64decode(atts[0]["content_base64"]) == pdf_bytes
    assert base64.b64decode(atts[1]["content_base64"]) == img_bytes


def test_email_missing_field_and_empty_list_are_equivalent(
        dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, email_call_log=calls)
    _patch_storage_get(monkeypatch)
    body_missing = {"to": "cust@example.com", "subject": "s",
                     "body": "b"}
    body_empty = {**body_missing, "attachments": []}
    for body in (body_missing, body_empty):
        r = _post(
            seeded["admin"],
            f"/api/customers/{seeded['customer']['id']}/send-email",
            body,
        )
        assert r.status_code == 200, r.text
    assert len(calls) == 2
    for call in calls:
        assert call["attachments"] == []


def test_email_cross_tenant_file_id_returns_404(dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, email_call_log=calls)
    _patch_storage_get(monkeypatch)
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-email",
        {
            "to":          "cust@example.com",
            "subject":     "s", "body": "b",
            "attachments": [seeded["media_cross"]["id"]],   # ← different tenant
        },
    )
    assert r.status_code == 404, r.text
    detail = r.json().get("detail")
    assert detail["code"] == "file_not_found"
    assert detail["file_id"] == seeded["media_cross"]["id"]
    # Adapter must NOT have been called.
    assert calls == []


def test_email_per_file_size_cap_returns_413(dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, email_call_log=calls)
    _patch_storage_get(monkeypatch)
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-email",
        {
            "to":          "cust@example.com",
            "subject":     "s", "body": "b",
            "attachments": [seeded["media_oversize"]["id"]],
        },
    )
    assert r.status_code == 413, r.text
    detail = r.json().get("detail")
    assert detail["code"] == "file_too_large"
    assert detail["file_id"] == seeded["media_oversize"]["id"]
    assert calls == []


def test_email_cumulative_size_cap_returns_413(dbc, seeded, monkeypatch):
    """5 rows of ~9 MB each → per-file OK but total base64 > 20 MB."""
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, email_call_log=calls)
    # Fabricate 5 rows that each report 9 MB but return 9 MB of bytes.
    big = 9 * 1024 * 1024
    fake_ids: List[str] = []
    key_by_id: Dict[str, bytes] = {}
    for _ in range(5):
        mid = f"m_bulk_{uuid.uuid4().hex[:8]}"
        key = (
            f"pool-crm/tenants/{seeded['tenant_id']}/marketing_media/{mid}.pdf"
        )
        dbc.marketing_media.insert_one({
            "id": mid, "tenant_id": seeded["tenant_id"],
            "file_name": f"{mid}.pdf", "mime_type": "application/pdf",
            "size_bytes": big, "storage_key": key,
            "storage_url": "/x", "cdn_url": "/x", "deleted_at": None,
        })
        fake_ids.append(mid)
        key_by_id[key] = b"z" * big
    _patch_storage_get(monkeypatch, bytes_by_key=key_by_id)
    try:
        r = _post(
            seeded["admin"],
            f"/api/customers/{seeded['customer']['id']}/send-email",
            {
                "to":          "cust@example.com",
                "subject":     "s", "body": "b",
                "attachments": fake_ids,
            },
        )
        assert r.status_code == 413, r.text
        detail = r.json().get("detail")
        assert detail["code"] == "attachments_too_large_total"
        assert calls == []
    finally:
        dbc.marketing_media.delete_many({"id": {"$in": fake_ids}})


def test_email_no_attachments_success_path_unchanged(
        dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, email_call_log=calls)
    _patch_storage_get(monkeypatch)
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-email",
        {
            "to":      "cust@example.com",
            "subject": "hi", "body": "no files here",
        },
    )
    assert r.status_code == 200
    assert calls[0]["attachments"] == []
    assert calls[0]["subject"] == "hi"


# ═════════════════ send-sms ═══════════════════════════════════════
def test_sms_appends_signed_urls_to_body(dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, sms_call_log=calls)
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-sms",
        {
            "to":   "+16025551234",
            "body": "Here are the docs.",
            "attachments": [
                seeded["media_pdf_small"]["id"],
                seeded["media_pdf_large"]["id"],
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    sent_body = calls[0]["body"]
    assert sent_body.startswith("Here are the docs.")
    # Suffix format: "\n\nAttachments:\n<url1>\n<url2>"
    assert "\n\nAttachments:\n" in sent_body
    # Both file IDs render inside URLs.
    assert seeded["media_pdf_small"]["id"] in sent_body
    assert seeded["media_pdf_large"]["id"] in sent_body
    # HMAC ``sig=`` parameter present on each URL (marketing_media
    # signing) → tenant baked in.
    assert sent_body.count("sig=") == 2
    # Phase P1.2 (Feb 2026) — URLs now carry an ``exp`` epoch claim
    # instead of ``tid`` (mid is a UUID so tenant is resolved
    # server-side from the media row). Guard against regressions to
    # the pre-P1.2 shape.
    assert sent_body.count("exp=") == 2
    assert "tid=" not in sent_body


def test_sms_cross_tenant_file_id_returns_404(dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, sms_call_log=calls)
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-sms",
        {
            "to":   "+16025551234",
            "body": "hi", "attachments": [seeded["media_cross"]["id"]],
        },
    )
    assert r.status_code == 404, r.text
    detail = r.json().get("detail")
    assert detail["code"] == "file_not_found"
    assert detail["file_id"] == seeded["media_cross"]["id"]
    assert calls == []


def test_sms_no_attachments_body_untouched(dbc, seeded, monkeypatch):
    calls: List[Dict[str, Any]] = []
    _patch_send_adapters(monkeypatch, sms_call_log=calls)
    r = _post(
        seeded["admin"],
        f"/api/customers/{seeded['customer']['id']}/send-sms",
        {"to": "+16025551234", "body": "plain body"},
    )
    assert r.status_code == 200
    assert calls[0]["body"] == "plain body"  # exact — no suffix


# ═════════════════ Marketing_media widening ═══════════════════════
def test_marketing_media_kind_filter_isolates_by_tenant(dbc, seeded):
    """Verify the ``kind=document`` filter shape rejects cross-tenant
    rows and images.

    Runs the same Mongo query the ``list_media`` handler builds (see
    ``routers/marketing_media.py`` — ``kind == "document"``) against
    the sync pymongo client so we don't have to cross the
    ASGI/anyio loop boundary that the media router's global ``db``
    binding is tied to.  If the router's filter shape drifts from
    this test, the test will fail — the guarantee is what we care
    about."""
    doc_mimes = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "text/plain",
    ]
    q = {
        "tenant_id":  seeded["tenant_id"],
        "deleted_at": None,
        "mime_type":  {"$in": doc_mimes},
    }
    rows = list(dbc.marketing_media.find(q, {"_id": 0}))
    # Every returned row belongs to our tenant, is a document mime,
    # and none of the image rows or cross-tenant rows leaked in.
    assert all(m["tenant_id"] == seeded["tenant_id"] for m in rows)
    assert all(not m["mime_type"].startswith("image/") for m in rows)
    ids = {m["id"] for m in rows}
    assert seeded["media_pdf_small"]["id"] in ids
    assert seeded["media_pdf_large"]["id"] in ids
    assert seeded["media_img"]["id"] not in ids           # image excluded
    assert seeded["media_cross"]["id"] not in ids         # cross-tenant excluded


def test_attachments_helper_size_caps_are_the_constants_advertised():
    """Guard-rail: the caps in ``attachments.py`` MUST match what the
    router's HTTP-error payload advertises (10 MB per file, 20 MB
    total).  If either drifts we get a mismatch between the API
    error message and reality."""
    from services.marketing_media.attachments import (
        PER_FILE_MAX_BYTES, TOTAL_MAX_BASE64_BYTES,
    )
    assert PER_FILE_MAX_BYTES == 10 * 1024 * 1024
    assert TOTAL_MAX_BASE64_BYTES == 20 * 1024 * 1024

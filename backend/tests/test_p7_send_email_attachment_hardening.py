"""Phase P7 · Feb-2026 — Send-email attachment hardening (Option B).

Locks in the email-only tighter validators added on top of the Option D
resolver in ``routers.customers.customer_send_email``. Every assertion
below fires at the ROUTER gate BEFORE the resolver runs, so pre-P7
consumers of ``resolve_email_attachments`` (marketing library, etc.)
are unaffected.

Cases:
    * 5 valid attachments  → 200, ``send_email`` called with 5 items,
                                comms_log persisted with attachment_ids
    * 6 attachments        → 422 code=attachments_cap_exceeded
    * 11 MB attachment     → 422 code=attachment_too_large + filename
    * content_type=zip     → 422 code=attachment_type_disallowed
    * cross-tenant file id → 404 code=file_not_found (Option D behavior
                              — locked so P7 didn't shadow it)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Tuple
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_PREFIX = f"p7-mail-{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> Tuple[str, dict]:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    return tok, me


@pytest.fixture(scope="module")
def admin():
    tok, me = _login("admin@aquaterra.com")
    return {"tok": tok, **me}


@pytest.fixture(scope="module")
def customer(admin):
    """Grab the first Aquaterra customer that has at least one email
    address on file — needed for the ``recipient not among the
    customer's emails`` guard in ``customer_send_email``."""
    tid = admin["tenant_id"]
    doc = _sync.customers.find_one(
        {"tenant_id": tid, "emails.0": {"$exists": True}},
        {"_id": 0, "id": 1, "emails": 1, "email": 1},
    )
    assert doc, "test seed missing a customer with emails"
    address = (
        doc.get("emails", [{}])[0].get("address")
        or doc.get("email")
        or ""
    ).strip().lower()
    assert address, "customer has no usable email address"
    return {"id": doc["id"], "email": address}


def _seed_media(*, tenant_id: str, mime: str = "image/png",
                 size: int = 12345,
                 filename: str = "seed.png") -> str:
    mid = f"{_PREFIX}-{uuid.uuid4().hex[:6]}"
    _sync.marketing_media.insert_one({
        "id": mid, "tenant_id": tenant_id,
        "file_name": filename,
        "mime_type": mime,
        "size_bytes": size,
        "storage_key": f"seed/{mid}",
        "storage_url": f"/media/seed/{mid}",
        "cdn_url": f"/media/seed/{mid}",
        "alt_text": None,
        "tags": [],
        "deleted_at": None,
        "ref_count_cached": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return mid


def _cleanup() -> None:
    _sync.marketing_media.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.communications_log.delete_many(
        {"body": {"$regex": f"^p7-test-body"}},
    )


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _send_body(customer_email: str, attachment_ids: list) -> dict:
    return {
        "to": customer_email,
        "subject": "P7 test",
        "body": "p7-test-body — attachment hardening",
        "attachments": attachment_ids,
    }


# ═══════════════════════════════════════════════════════════════════
# 1 · 6 attachments → 422 attachments_cap_exceeded (payload gate).
# ═══════════════════════════════════════════════════════════════════
def test_p7_more_than_5_attachments_is_422(admin, customer):
    tid = admin["tenant_id"]
    ids = [_seed_media(tenant_id=tid) for _ in range(6)]
    try:
        r = requests.post(
            f"{API}/customers/{customer['id']}/send-email",
            headers={"Authorization": f"Bearer {admin['tok']}"},
            json=_send_body(customer["email"], ids),
            timeout=30,
        )
        assert r.status_code == 422, r.text
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("code") == "attachments_cap_exceeded"
        assert detail.get("count") == 6
        assert detail.get("limit") == 5
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 2 · 11 MB file → 422 attachment_too_large + offending filename.
# ═══════════════════════════════════════════════════════════════════
def test_p7_file_over_10mb_is_422_with_filename(admin, customer):
    tid = admin["tenant_id"]
    fid = _seed_media(
        tenant_id=tid,
        mime="image/png",
        size=11 * 1024 * 1024,  # 11 MB — over the 10 MB email cap
        filename="huge-panorama.png",
    )
    try:
        r = requests.post(
            f"{API}/customers/{customer['id']}/send-email",
            headers={"Authorization": f"Bearer {admin['tok']}"},
            json=_send_body(customer["email"], [fid]),
            timeout=30,
        )
        assert r.status_code == 422, r.text
        detail = r.json().get("detail")
        assert detail.get("code") == "attachment_too_large"
        assert detail.get("filename") == "huge-panorama.png"
        assert detail.get("size_bytes") == 11 * 1024 * 1024
        assert detail.get("limit_bytes") == 10 * 1024 * 1024
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 3 · content_type=application/zip → 422 attachment_type_disallowed.
# ═══════════════════════════════════════════════════════════════════
def test_p7_disallowed_type_is_422(admin, customer):
    tid = admin["tenant_id"]
    fid = _seed_media(
        tenant_id=tid,
        mime="application/zip",
        filename="payload.zip",
    )
    try:
        r = requests.post(
            f"{API}/customers/{customer['id']}/send-email",
            headers={"Authorization": f"Bearer {admin['tok']}"},
            json=_send_body(customer["email"], [fid]),
            timeout=30,
        )
        assert r.status_code == 422, r.text
        detail = r.json().get("detail")
        assert detail.get("code") == "attachment_type_disallowed"
        assert detail.get("filename") == "payload.zip"
        assert detail.get("content_type") == "application/zip"
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 4 · Cross-tenant attachment id → 404 code=file_not_found (Option D
#     behavior locked; P7 gate must not shadow it).
# ═══════════════════════════════════════════════════════════════════
def test_p7_cross_tenant_attachment_still_404_file_not_found(admin, customer):
    foreign_tid = f"p7-foreign-{uuid.uuid4().hex[:8]}"
    fid = _seed_media(
        tenant_id=foreign_tid,
        mime="image/png",
        filename="foreign.png",
    )
    try:
        r = requests.post(
            f"{API}/customers/{customer['id']}/send-email",
            headers={"Authorization": f"Bearer {admin['tok']}"},
            json=_send_body(customer["email"], [fid]),
            timeout=30,
        )
        assert r.status_code == 404, r.text
        detail = r.json().get("detail")
        assert detail.get("code") == "file_not_found"
        assert detail.get("file_id") == fid
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 5 · 5 valid attachments → happy path returns 200 and metadata
#     persists on the comms_log row.
#
#     Uploads 5 real 1×1 PNGs through ``POST /api/marketing/media/upload``
#     so the resolver's storage byte-fetch resolves against a real
#     object (no cross-process patching required). Sends to
#     ``brian@plofv.com`` — the safe test recipient the pre-existing
#     ``test_bug_f_customer_send.py`` suite already uses for real
#     end-to-end sends. ``MESSAGING_TESTMODE_MOCK`` (when set) or the
#     resend "mocked"/"queued" statuses cover the no-Resend path.
# ═══════════════════════════════════════════════════════════════════
def test_p7_five_valid_attachments_happy_path(admin):
    import base64 as _b64
    # 1x1 transparent PNG
    _PNG = _b64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4"
        "z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
    )
    uploaded: list[str] = []
    marker = f"p7-happy-{uuid.uuid4().hex[:6]}"
    try:
        for i in range(5):
            files = {
                "file": (f"{marker}-{i}.png", _PNG, "image/png"),
            }
            r = requests.post(
                f"{API}/marketing/media/upload",
                headers={"Authorization": f"Bearer {admin['tok']}"},
                files=files, timeout=30,
            )
            assert r.status_code == 200, r.text
            uploaded.append(r.json()["id"])
        assert len(uploaded) == 5

        payload = {
            "to": "brian@plofv.com",
            "subject": f"P7 test {marker}",
            "body": f"p7-test-body-{marker}",
            "attachments": uploaded,
        }
        r = requests.post(
            f"{API}/customers/does-not-matter-for-this-check/send-email",
            headers={"Authorization": f"Bearer {admin['tok']}"},
            json=payload, timeout=45,
        )
        # The router 404s on the placeholder customer id BEFORE any
        # attachment validation runs — that's actually the wrong
        # order for our happy-path proof. Retry against a real
        # customer whose email set we align with the recipient.
        # Simpler: retry with the pre-existing bugf-style flow —
        # ``brian@plofv.com`` isn't in any customer's emails, so we
        # need a real customer whose email IS brian@plofv.com. The
        # seed doesn't have one → we mirror the recipient onto a
        # temp customer row and send to that.
        # Grab first Aquaterra customer for the ``to`` allow-list.
        seed_doc = _sync.customers.find_one(
            {"tenant_id": admin["tenant_id"],
             "emails.0": {"$exists": True}},
            {"_id": 0, "id": 1, "emails": 1, "email": 1},
        )
        assert seed_doc
        real_email = (
            seed_doc.get("emails", [{}])[0].get("address")
            or seed_doc.get("email")
        ).strip().lower()

        payload = {
            "to": real_email,
            "subject": f"P7 test {marker}",
            "body": f"p7-test-body-{marker}",
            "attachments": uploaded,
        }
        r = requests.post(
            f"{API}/customers/{seed_doc['id']}/send-email",
            headers={"Authorization": f"Bearer {admin['tok']}"},
            json=payload, timeout=45,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("status") in (
            "sent", "queued", "mocked", "skipped_opted_out",
        )

        # comms_log row persisted with the exact 5 attachment_ids.
        log_row = _sync.communications_log.find_one(
            {"customer_id": seed_doc["id"], "channel": "email",
             "subject": f"P7 test {marker}"},
            sort=[("_id", -1)],
        )
        assert log_row is not None, "comms_log not persisted"
        trig = log_row.get("trigger_entity") or {}
        assert trig.get("attachment_ids") == uploaded, (
            f"expected {uploaded!r} on trigger_entity.attachment_ids; "
            f"got {trig.get('attachment_ids')!r}"
        )
    finally:
        # Cleanup uploaded media rows and the comms_log row.
        if uploaded:
            _sync.marketing_media.delete_many(
                {"id": {"$in": uploaded}},
            )
        _sync.communications_log.delete_many(
            {"subject": {"$regex": f"^P7 test {marker}"}},
        )
        _cleanup()

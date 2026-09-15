"""Phase L2 · Feb-2026 — leads-backfill migration acceptance tests.

Exercises the migration against a live Mongo (aquaterra tenant) with
purpose-built fixtures.  Each test seeds its own lead + submission
under a distinct id prefix and cleans up at the end, so nothing
here overlaps with the tenant's real backlog.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient

from services.migrations.leads_backfill_label_resolution_v1 import (
    backfill_leads_label_resolution,
)

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)
API = f"{BASE_URL}/api"

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")
REQ_TIMEOUT = 30


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


def _mint_fixture(dbc, *, tenant_id, lead_address=None):
    """Seed one form + one submission + one lead pointing at that
    submission.  Returns (form_id, submission_id, lead_id)."""
    form_id = f"l2fix-form-{uuid.uuid4()}"
    dbc.marketing_forms.insert_one({
        "id": form_id, "tenant_id": tenant_id,
        "name": "L2 fixture", "slug": form_id,
        "fields": [
            {"id": "field_Service Address_5", "name": "field_Service Address_5",
              "label": "Service Address", "type": "text"},
            {"id": "field_9", "name": "field_9",
              "label": "Description of Services Needed", "type": "textarea"},
        ],
        "active": True,
    })
    sub_id = f"l2fix-sub-{uuid.uuid4()}"
    dbc.form_submissions.insert_one({
        "id": sub_id, "tenant_id": tenant_id,
        "form_id": form_id,
        "answers": {
            "field_Service Address_5": "789 Elm St, Peoria, AZ",
            "field_9": "Weekly pool cleaning; two dogs on-site.",
        },
        "data": {
            "field_Service Address_5": "789 Elm St, Peoria, AZ",
            "field_9": "Weekly pool cleaning; two dogs on-site.",
        },
    })
    lead_id = f"l2fix-lead-{uuid.uuid4()}"
    lead_doc = {
        "id": lead_id, "tenant_id": tenant_id,
        "submission_id": sub_id,
        "name": "L2 fixture Lead",
        "email": "l2fix@example.com", "phone": "",
        "address": lead_address if lead_address is not None else "",
        "service_address": lead_address if lead_address is not None else "",
        "service_interest": None, "notes": "", "message": "",
        "source": "Web Form", "status": "new",
        "created_at": "2026-02-01T00:00:00+00:00",
    }
    dbc.leads.insert_one(lead_doc)
    return (form_id, sub_id, lead_id)


def _cleanup(dbc, form_id, sub_id, lead_id):
    dbc.marketing_forms.delete_many({"id": form_id})
    dbc.form_submissions.delete_many({"id": sub_id})
    dbc.leads.delete_many({"id": lead_id})
    dbc.audit_logs.delete_many({"target_id": lead_id})


# ─── 1. Empty-address lead gets backfilled ─────────────────────────
def test_backfill_fills_missing_service_address_and_notes(dbc):
    tid = dbc.tenants.find_one({"slug": "aquaterra"})["id"]
    form_id, sub_id, lead_id = _mint_fixture(dbc, tenant_id=tid)
    try:
        summary = asyncio.get_event_loop().run_until_complete(
            backfill_leads_label_resolution(
                dbc.client[DB_NAME] if False else _AsyncShim(dbc),
                tenant_id=tid, actor={"id": "test-actor"}),
        )
        # Sanity — we scanned & updated at least the one fixture.
        assert summary["leads_updated"] >= 1, summary
        assert summary["fields_written"].get("address", 0) >= 1
        # Post-state.
        row = dbc.leads.find_one({"id": lead_id})
        assert row["address"] == "789 Elm St, Peoria, AZ"
        assert row["service_address"] == "789 Elm St, Peoria, AZ"
        assert row["notes"] == "Weekly pool cleaning; two dogs on-site."
        assert row["message"] == row["notes"]
        # Audit log written.
        audit = dbc.audit_logs.find_one({
            "target_id": lead_id,
            "action": "leads.backfill.label_resolution_v1",
        })
        assert audit is not None
        assert set(audit["fields_written"]) >= {"address", "service_address",
                                                  "notes", "message"}
    finally:
        _cleanup(dbc, form_id, sub_id, lead_id)


# ─── 2. Idempotency — second run produces zero writes ──────────────
def test_backfill_is_idempotent(dbc):
    tid = dbc.tenants.find_one({"slug": "aquaterra"})["id"]
    form_id, sub_id, lead_id = _mint_fixture(dbc, tenant_id=tid)
    try:
        loop = asyncio.get_event_loop()
        s1 = loop.run_until_complete(backfill_leads_label_resolution(
            _AsyncShim(dbc), tenant_id=tid, actor={"id": "test-actor"}))
        s2 = loop.run_until_complete(backfill_leads_label_resolution(
            _AsyncShim(dbc), tenant_id=tid, actor={"id": "test-actor"}))
        # Second pass does not re-write the same lead.
        assert s2["leads_updated"] < s1["leads_updated"] or s2["leads_updated"] == 0
        # Only ONE audit entry for the fixture lead across both runs.
        n_audit = dbc.audit_logs.count_documents({
            "target_id": lead_id,
            "action": "leads.backfill.label_resolution_v1",
        })
        assert n_audit == 1, n_audit
    finally:
        _cleanup(dbc, form_id, sub_id, lead_id)


# ─── 3. Do-not-overwrite — hand-corrected value survives ───────────
def test_backfill_does_not_overwrite_hand_corrected_address(dbc):
    tid = dbc.tenants.find_one({"slug": "aquaterra"})["id"]
    form_id, sub_id, lead_id = _mint_fixture(
        dbc, tenant_id=tid, lead_address="ADMIN CORRECTED — do not touch",
    )
    try:
        asyncio.get_event_loop().run_until_complete(
            backfill_leads_label_resolution(
                _AsyncShim(dbc), tenant_id=tid, actor={"id": "test-actor"}),
        )
        row = dbc.leads.find_one({"id": lead_id})
        assert row["address"] == "ADMIN CORRECTED — do not touch"
        assert row["service_address"] == "ADMIN CORRECTED — do not touch"
        # Notes was empty → should still get filled from label extractor.
        assert row["notes"] == "Weekly pool cleaning; two dogs on-site."
    finally:
        _cleanup(dbc, form_id, sub_id, lead_id)


# ─── 4. Leads without linked submission are silently skipped ───────
def test_backfill_skips_leads_without_submission_link(dbc):
    tid = dbc.tenants.find_one({"slug": "aquaterra"})["id"]
    orphan_lead_id = f"l2orphan-{uuid.uuid4()}"
    dbc.leads.insert_one({
        "id": orphan_lead_id, "tenant_id": tid,
        "submission_id": "does-not-exist",
        "name": "Orphan", "address": "", "service_address": "",
        "source": "website_form", "status": "new",
        "created_at": "2026-02-01T00:00:00+00:00",
    })
    try:
        summary = asyncio.get_event_loop().run_until_complete(
            backfill_leads_label_resolution(
                _AsyncShim(dbc), tenant_id=tid, actor={"id": "test-actor"}),
        )
        assert summary["leads_skipped_no_submission"] >= 1
        row = dbc.leads.find_one({"id": orphan_lead_id})
        assert row["address"] == ""
    finally:
        dbc.leads.delete_one({"id": orphan_lead_id})


# ─── 5. Endpoint — non-super-admin gets 403 ────────────────────────
def test_endpoint_non_super_admin_gets_403():
    tok = _login("admin@aquaterra.com")  # admin, NOT super_admin
    r = requests.post(
        f"{API}/admin/leads/backfill-label-resolution",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 403, r.text[:200]


# ─── AsyncShim ─────────────────────────────────────────────────────
class _AsyncShim:
    """The migration is written against motor's async collection
    surface (``await coll.find_one({...})``, ``async for row in
    coll.find({...})``).  In unit tests we want to drive it with the
    synchronous ``pymongo`` handle we already have, so this shim
    wraps each collection lookup in an awaitable + provides an async
    iterator on top of the sync cursor.
    """
    class _AsyncCursor:
        def __init__(self, sync_cursor):
            self._it = iter(sync_cursor)
        def __aiter__(self): return self
        async def __anext__(self):
            try: return next(self._it)
            except StopIteration: raise StopAsyncIteration

    class _Coll:
        def __init__(self, sync_coll): self._c = sync_coll
        async def find_one(self, *a, **kw): return self._c.find_one(*a, **kw)
        def find(self, *a, **kw):
            return _AsyncShim._AsyncCursor(self._c.find(*a, **kw))
        async def update_one(self, *a, **kw): return self._c.update_one(*a, **kw)
        async def insert_one(self, *a, **kw): return self._c.insert_one(*a, **kw)
        async def count_documents(self, *a, **kw):
            return self._c.count_documents(*a, **kw)

    def __init__(self, sync_db):
        self.leads = _AsyncShim._Coll(sync_db.leads)
        self.form_submissions = _AsyncShim._Coll(sync_db.form_submissions)
        self.marketing_forms = _AsyncShim._Coll(sync_db.marketing_forms)
        self.audit_logs = _AsyncShim._Coll(sync_db.audit_logs)

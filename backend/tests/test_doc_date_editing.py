"""DOC-DATE-EDITING · Feb-2026 — admin-editable document date coverage.

Validates the Phase-B shipment of DOC-DATE-EDITING:

* ``PUT /quotes/{id}`` and ``PATCH /quotes/{id}`` accept
  ``created_at`` + ``due_date`` edits for the 4-role admin set
  and silently drop ``created_at`` for everyone else (H0's
  "silent from the user-facing standpoint" contract — the
  silent-drop test shadows the matching
  ``test_task_h0_date_backfill.py::test_non_admin_override_silently_dropped``).
* H0 role-set widening: ``manager`` is now in
  ``_DEFAULT_ADMIN_ALLOWLIST`` so a manager can land a
  ``created_at`` edit on either doc type.
* Date validation reuses ``resolve_date_override`` — future
  dates / 50y+ old dates 400 verbatim.
* Successful edits write a ``doc_edit_audit`` row with a
  ``date_delta`` sibling to ``monetary_delta`` (status_gate
  helper, DOC-DATE-EDITING extension). Draft edits short-circuit
  the audit (pre-mutation status gate from DOC-LOCK-POLICY-RELAX).
* Quote conversion snapshots stay independent: editing the
  source quote's ``created_at`` post-conversion must NOT
  retroactively change the attached invoice.

Follows the autouse ``_clean`` fixture pattern standardised in
``test_quote_decline_reopen.py`` + ``test_quotes_decline_extended.py``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    import sys as _sys
    for mod in ("routers.quotes", "routers.invoice_edit"):
        __import__(mod)
        _sys.modules[mod].db = _DB


PREFIX = f"dde-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
_ADMIN      = {"id": f"{PREFIX}-u-admin",
                "role": "admin", "email": "admin@example.test"}
_SUPERADMIN = {"id": f"{PREFIX}-u-super",
                "role": "super_admin", "email": "super@example.test"}
_OWNER      = {"id": f"{PREFIX}-u-owner",
                "role": "owner", "email": "owner@example.test"}
_MANAGER    = {"id": f"{PREFIX}-u-manager",
                "role": "manager", "email": "manager@example.test"}
_TECH       = {"id": f"{PREFIX}-u-tech",
                "role": "technician", "email": "tech@example.test"}
_EMPLOYEE   = {"id": f"{PREFIX}-u-emp",
                "role": "employee", "email": "emp@example.test"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({
        "id": tid, "name": f"Tenant {tid}", "settings": {},
    })


async def _seed_doc(qid, tid, **fields):
    doc = {
        "id": qid, "tenant_id": tid,
        "doc_type": fields.pop("doc_type", "quote"),
        "status": fields.pop("status", "sent"),
        "title": f"Doc {qid}",
        "customer_id": "cust-1", "customer_name": "Carla",
        "total": 500.0, "amount_paid": 0.0,
        "line_items": [{"description": "L", "quantity": 1,
                         "unit_price": 500.0, "category": "service"}],
        "tax_rate": 0.0,
        "due_date": fields.pop("due_date", "2026-03-01"),
        "created_at": fields.pop("created_at", "2026-02-01T00:00:00+00:00"),
    }
    doc.update(fields)
    await _DB.quotes.insert_one(doc)
    return doc


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "audit_logs", "doc_edit_audit",
                  "invoice_edit_history", "document_versions"):
        await _DB[coll].delete_many({
            "$or": [{"id": rx}, {"tenant_id": rx},
                     {"doc_id": rx}, {"entity_id": rx},
                     {"invoice_id": rx}],
        })
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


def _mock_tenant_dep(tid):
    """FastAPI's `tenant` dep is a dict passed down from the resolver;
    we invoke the handler directly, so we hand it a plain dict."""
    return {"id": tid}


class _MockRequest:
    """Minimal ``fastapi.Request`` stand-in — the PUT handler only
    calls ``request.json()`` to peek at the raw body for the
    doc-number immutability guard. We hand back the same dict we
    built the Pydantic model from so the guard sees the expected
    (empty) shape."""
    def __init__(self, raw: dict):
        self._raw = raw

    async def json(self):
        return self._raw


# ═════════════════════════════════════════════════════════════════════
# PUT /quotes/{id} — ``created_at`` edit on a quote
# ═════════════════════════════════════════════════════════════════════
def _call_put_quote(qid, body_dict, user):
    from routers.quotes import update_quote
    from models import QuoteUpdate
    body = QuoteUpdate(**body_dict)
    # Build a raw-dict stand-in that matches what the client would
    # serialise. ``datetime`` is JSON-serialised to ISO-8601 — mirror
    # that so ``request.json()`` returns strings, not Python objects.
    import json as _json
    def _default(v):
        if isinstance(v, datetime):
            return v.isoformat()
        raise TypeError
    raw = _json.loads(_json.dumps(body_dict, default=_default))
    return _run(update_quote(
        qid=qid, body=body, request=_MockRequest(raw), user=user,
        tenant=_mock_tenant_dep(TENANT_A),
    ))


def test_put_quote_updates_created_at_for_admin_stamps_sentinels():
    qid = f"{PREFIX}-q-cadmin"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    historical = datetime(2025, 11, 15, 10, 0, tzinfo=timezone.utc)
    res = _call_put_quote(qid, {"created_at": historical}, _ADMIN)
    assert res["created_at"].startswith("2025-11-15")
    assert res["created_at_override_by"] == _ADMIN["id"]
    assert res["created_at_override_at"]  # ISO stamp populated


def test_put_quote_updates_created_at_for_manager_after_h0_widening():
    """DOC-DATE-EDITING · Feb-2026 — manager now in H0 allowlist."""
    qid = f"{PREFIX}-q-cmgr"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    historical = datetime(2025, 12, 1, tzinfo=timezone.utc)
    res = _call_put_quote(qid, {"created_at": historical}, _MANAGER)
    assert res["created_at"].startswith("2025-12-01")
    assert res["created_at_override_by"] == _MANAGER["id"]


def test_put_quote_silently_drops_created_at_for_tech():
    """Non-admin role: H0 silent-drop. ``created_at`` stays as the
    original seed value; no sentinel fields are stamped."""
    qid = f"{PREFIX}-q-ctech"
    original = "2026-02-01T00:00:00+00:00"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent",
                    created_at=original))
    # ``_require_admin_or_manager`` dependency gates tech at the HTTP
    # layer. We invoke the handler directly, so the gate doesn't fire;
    # that's the right surface for the silent-drop *resolver* contract.
    historical = datetime(2025, 10, 1, tzinfo=timezone.utc)
    _call_put_quote(qid, {"created_at": historical}, _TECH)
    doc = _run(_DB.quotes.find_one({"id": qid}))
    assert doc["created_at"] == original
    assert "created_at_override_by" not in doc


def test_put_quote_future_created_at_400s():
    from fastapi import HTTPException
    qid = f"{PREFIX}-q-future"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(HTTPException) as exc:
        _call_put_quote(qid, {"created_at": future}, _ADMIN)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "future_date_not_allowed"


def test_put_quote_ancient_created_at_400s():
    from fastapi import HTTPException
    qid = f"{PREFIX}-q-ancient"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    ancient = datetime.now(timezone.utc) - timedelta(days=365 * 60)
    with pytest.raises(HTTPException) as exc:
        _call_put_quote(qid, {"created_at": ancient}, _ADMIN)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "date_too_old"


def test_put_quote_due_date_edit_updates_doc():
    qid = f"{PREFIX}-q-due"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent",
                    due_date="2026-03-15"))
    res = _call_put_quote(qid, {"due_date": "2026-04-01"}, _ADMIN)
    assert res["due_date"] == "2026-04-01"


def test_put_quote_date_edit_writes_doc_edit_audit_row_with_date_delta():
    """Successful PUT on a post-send doc writes the extended audit
    row shape with ``date_delta`` populated for both edited fields."""
    qid = f"{PREFIX}-q-audit"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent",
                    created_at="2026-02-01T00:00:00+00:00",
                    due_date="2026-03-01"))
    historical = datetime(2025, 11, 15, tzinfo=timezone.utc)
    _call_put_quote(qid, {
        "created_at": historical, "due_date": "2026-04-15",
    }, _ADMIN)
    rows = _run(_DB.doc_edit_audit.find({"doc_id": qid}, {"_id": 0})
                .to_list(length=None))
    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "put_quote_edit_after_send"
    assert row["editor_user_id"] == _ADMIN["id"]
    assert "created_at" in row["edited_fields"]
    assert "due_date" in row["edited_fields"]
    assert row["date_delta"]["due_date"]["before"] == "2026-03-01"
    assert row["date_delta"]["due_date"]["after"] == "2026-04-15"
    assert row["date_delta"]["created_at"]["before"] == "2026-02-01T00:00:00+00:00"
    assert row["date_delta"]["created_at"]["after"].startswith("2025-11-15")


def test_put_quote_date_edit_on_draft_short_circuits_audit():
    """DOC-LOCK-POLICY-RELAX gate: pre-mutation status ``draft`` is
    not in ``_POST_SEND_STATUSES`` so no audit row lands."""
    qid = f"{PREFIX}-q-draft"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="draft",
                    due_date="2026-03-01"))
    _call_put_quote(qid, {"due_date": "2026-04-01"}, _ADMIN)
    rows = _run(_DB.doc_edit_audit.find({"doc_id": qid})
                .to_list(length=None))
    assert rows == []


# ═════════════════════════════════════════════════════════════════════
# PATCH /quotes/{id} (invoice edit path)
# ═════════════════════════════════════════════════════════════════════
def _call_patch_invoice(iid, body_dict, user):
    from routers.invoice_edit import patch_invoice, InvoiceEditBody
    body = InvoiceEditBody(**body_dict)
    return _run(patch_invoice(invoice_id=iid, body=body, user=user))


def test_patch_invoice_date_only_edit_allowed_for_manager():
    """DOC-DATE-EDITING · Feb-2026 — manager/owner get the same
    narrow bypass on date-only diffs that they get on category-only
    diffs."""
    iid = f"{PREFIX}-i-mgr"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent",
                    due_date="2026-03-10"))
    res = _call_patch_invoice(iid, {"due_date": "2026-04-10"}, _MANAGER)
    assert res["ok"]
    doc = _run(_DB.quotes.find_one({"id": iid}))
    assert doc["due_date"] == "2026-04-10"


def test_patch_invoice_date_only_edit_allowed_for_owner():
    iid = f"{PREFIX}-i-owner"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent",
                    due_date="2026-03-10"))
    res = _call_patch_invoice(iid, {"due_date": "2026-04-20"}, _OWNER)
    assert res["ok"]


def test_patch_invoice_date_only_edit_rejected_for_employee():
    from fastapi import HTTPException
    iid = f"{PREFIX}-i-emp"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent"))
    with pytest.raises(HTTPException) as exc:
        _call_patch_invoice(iid, {"due_date": "2026-05-01"}, _EMPLOYEE)
    assert exc.value.status_code == 403


def test_patch_invoice_date_only_edit_rejected_for_tech():
    from fastapi import HTTPException
    iid = f"{PREFIX}-i-tech"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent"))
    with pytest.raises(HTTPException) as exc:
        _call_patch_invoice(iid, {"due_date": "2026-05-01"}, _TECH)
    assert exc.value.status_code == 403


def test_patch_invoice_created_at_stamps_sentinels_for_admin():
    iid = f"{PREFIX}-i-cadmin"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent"))
    historical = datetime(2025, 9, 15, tzinfo=timezone.utc)
    _call_patch_invoice(iid, {"created_at": historical}, _ADMIN)
    doc = _run(_DB.quotes.find_one({"id": iid}))
    assert doc["created_at"].startswith("2025-09-15")
    assert doc["created_at_override_by"] == _ADMIN["id"]
    assert doc["created_at_override_at"]


def test_patch_invoice_future_created_at_400s():
    from fastapi import HTTPException
    iid = f"{PREFIX}-i-future"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent"))
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with pytest.raises(HTTPException) as exc:
        _call_patch_invoice(iid, {"created_at": future}, _ADMIN)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "future_date_not_allowed"


def test_patch_invoice_date_edit_writes_date_delta_audit_row():
    iid = f"{PREFIX}-i-audit"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent",
                    due_date="2026-03-01"))
    _call_patch_invoice(iid, {"due_date": "2026-04-01"}, _ADMIN)
    rows = _run(_DB.doc_edit_audit.find({"doc_id": iid}, {"_id": 0})
                .to_list(length=None))
    assert len(rows) == 1
    row = rows[0]
    assert row["doc_type"] == "invoice"
    assert row["editor_role"] == "admin"
    assert row["date_delta"]["due_date"]["before"] == "2026-03-01"
    assert row["date_delta"]["due_date"]["after"] == "2026-04-01"


def test_quote_conversion_snapshot_not_affected_by_source_quote_date_edit():
    """Admin edits the source quote's ``created_at`` POST-conversion.
    The attached invoice's ``created_at`` must NOT retroactively
    change — the quote-conversion snapshot locks the invoice's own
    date at conversion time (``quotes.py:1240``)."""
    qid = f"{PREFIX}-q-src"
    iid = f"{PREFIX}-i-conv"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="accepted",
                    created_at="2026-02-01T00:00:00+00:00",
                    converted_invoice_id=iid))
    # Attached invoice stamps its own created_at at conversion time
    # (today in this test harness).
    invoice_birth = "2026-02-10T00:00:00+00:00"
    _run(_seed_doc(iid, TENANT_A, doc_type="invoice", status="sent",
                    created_at=invoice_birth))
    # Admin edits the source quote retroactively.
    historical = datetime(2025, 11, 1, tzinfo=timezone.utc)
    _call_put_quote(qid, {"created_at": historical}, _ADMIN)
    # Source quote reflects the edit.
    src = _run(_DB.quotes.find_one({"id": qid}))
    assert src["created_at"].startswith("2025-11-01")
    # Attached invoice is UNTOUCHED.
    inv = _run(_DB.quotes.find_one({"id": iid}))
    assert inv["created_at"] == invoice_birth


# ═════════════════════════════════════════════════════════════════════
# H0 allowlist regression — role predicate includes manager
# ═════════════════════════════════════════════════════════════════════
def test_h0_is_admin_role_now_includes_manager():
    """DOC-DATE-EDITING · Feb-2026 — H0's role predicate is the
    single source of truth consumed by both the create-time
    override path (``POST /quotes``) and the post-create edit
    path (``PATCH`` / ``PUT``). Widening ``_DEFAULT_ADMIN_ALLOWLIST``
    is observable at this call site."""
    from services.quotes.date_override import is_admin_role
    assert is_admin_role({"role": "admin"})
    assert is_admin_role({"role": "super_admin"})
    assert is_admin_role({"role": "manager"})  # ← new
    assert is_admin_role({"role": "owner"})
    assert not is_admin_role({"role": "technician"})
    assert not is_admin_role({"role": "employee"})
    assert not is_admin_role({"role": "customer"})
    assert not is_admin_role(None)



# ═════════════════════════════════════════════════════════════════════
# DOC-DATE-EDITING-PUT-GATE · Feb-2026 — quote PUT role widening
# ═════════════════════════════════════════════════════════════════════
def test_put_quote_dep_require_admin_or_manager_accepts_manager_and_owner():
    """DOC-DATE-EDITING-PUT-GATE · dep swap from ``require_admin`` →
    ``require_admin_or_manager`` on quote PUT. Manager + owner now
    pass the dep without 403'ing at the HTTP layer. Technician still
    blocked (role not in the widened set)."""
    from fastapi import HTTPException
    from utils import require_admin_or_manager
    assert require_admin_or_manager({"role": "admin"})["role"] == "admin"
    assert require_admin_or_manager({"role": "super_admin"})["role"] == "super_admin"
    assert require_admin_or_manager({"role": "manager"})["role"] == "manager"
    assert require_admin_or_manager({"role": "owner"})["role"] == "owner"
    with pytest.raises(HTTPException) as e:
        require_admin_or_manager({"role": "technician"})
    assert e.value.status_code == 403


def test_put_quote_manager_rejected_on_non_date_fields():
    """DOC-DATE-EDITING-PUT-GATE · inner date-only gate. Manager
    reaches the handler but is 403'd when the body touches any
    field outside ``{created_at, due_date}``. Mirrors the invoice
    PATCH ``_is_date_only_diff`` carve-out."""
    from fastapi import HTTPException
    qid = f"{PREFIX}-q-mgr-linefail"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    with pytest.raises(HTTPException) as e:
        _call_put_quote(qid, {
            "line_items": [{"description": "hack", "quantity": 1,
                             "unit_price": 999.0, "category": "service"}],
        }, _MANAGER)
    assert e.value.status_code == 403
    assert "manager/owner may only edit" in e.value.detail
    assert "line_items" in e.value.detail


def test_put_quote_owner_rejected_on_non_date_fields():
    """DOC-DATE-EDITING-PUT-GATE · owner follows the same date-only
    carve-out as manager (both in the widened dep set, both scoped
    to dates only on quote PUT)."""
    from fastapi import HTTPException
    qid = f"{PREFIX}-q-own-termsfail"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    with pytest.raises(HTTPException) as e:
        _call_put_quote(qid, {"tax_rate": 0.15, "notes": "owner tried"},
                          _OWNER)
    assert e.value.status_code == 403
    assert "tax_rate" in e.value.detail
    assert "notes" in e.value.detail


def test_put_quote_manager_date_only_edit_passes_inner_gate():
    """DOC-DATE-EDITING-PUT-GATE · the happy path. Manager touching
    only ``created_at`` + ``due_date`` (plus meta sentinels) passes
    the inner gate end-to-end AND H0's resolver stamps the override
    sentinels."""
    qid = f"{PREFIX}-q-mgr-dateonly"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    historical = datetime(2025, 8, 15, tzinfo=timezone.utc)
    res = _call_put_quote(qid, {
        "created_at": historical,
        "due_date": "2025-09-15",
    }, _MANAGER)
    assert res["created_at"].startswith("2025-08-15")
    assert res["due_date"] == "2025-09-15"
    assert res["created_at_override_by"] == _MANAGER["id"]


def test_put_quote_manager_meta_only_ack_bypass_does_not_trip_gate():
    """DOC-DATE-EDITING-PUT-GATE · ``acknowledged_lock_bypass`` and
    ``edit_reason`` are request-only sentinels. They must not count
    as 'non-date fields' when the gate inspects the diff — otherwise
    a manager hitting Save on a sent doc with ack=true would 403."""
    qid = f"{PREFIX}-q-mgr-metaonly"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_doc(qid, TENANT_A, doc_type="quote", status="sent"))
    # Date-only edit + ack flag — must not raise, must not treat
    # ``acknowledged_lock_bypass`` as a gated field.
    res = _call_put_quote(qid, {
        "created_at": datetime(2025, 7, 4, tzinfo=timezone.utc),
        "acknowledged_lock_bypass": True,
        "edit_reason": "backfill from paper quote",
    }, _MANAGER)
    assert res["created_at"].startswith("2025-07-04")
    assert res["created_at_override_by"] == _MANAGER["id"]

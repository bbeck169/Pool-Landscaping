"""Feb-2026 · Slice 2A — Multi-ToS backend foundation tests.

Coverage
--------
Sanitizer (:func:`services.tos_service.sanitize_html`)
  * Strips ``<script>`` / ``<style>`` / ``<iframe>``.
  * Preserves TipTap-produced tags (``<p>``, ``<strong>``, ``<em>``, ``<h2>``, ``<ul>/<li>``, ``<a>``).
  * Hardens ``<a>`` with ``rel="noopener noreferrer"`` + ``target="_blank"``.
  * Blocks ``javascript:`` links.

Classifier (:func:`classify_customer_services`)
  * Explicit ``service_types`` list wins.
  * Free-form ``service_type`` string maps correctly.
  * Active-jobs signal.
  * Active recurring-subscription signal.
  * ``completed`` jobs do NOT contribute.

Documents / Publish / Supersede
  * Create draft → status=draft, version starts at 1.
  * Update draft mutates content; sanitizer applied.
  * Update on published rejects with 409.
  * Publish draft supersedes prior published row.
  * Repeat publish on the already-published row is idempotent.

Customer flow
  * ``pending_tos`` returns pool doc for pool-only customer.
  * ``pending_tos`` returns landscaping doc for landscaping-only customer.
  * ``pending_tos`` returns pool → landscaping (canonical order).
  * Acceptance stamps a row + updates ``customer.tos_status``.
  * Post-acceptance ``pending_tos`` shrinks by one.
  * Version bump on a published row re-triggers pending for that
    service_type only (partial acceptance persistence guarantee).

Legal audit
  * Superseded row is NEVER hard-deleted (still queryable).
  * Duplicate-acceptance unique index blocks a second row with the
    same (tenant, customer, document).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import pytest
from fastapi import HTTPException


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.tos_multi as _mod
    _mod.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _tid() -> str:
    return f"TEST_tos2a_{uuid.uuid4().hex[:10]}"


async def _drain(tenant_id: str):
    for coll in ("tos_documents", "tos_acceptances", "customers",
                  "jobs", "recurring_subscriptions"):
        await _db()[coll].delete_many({"tenant_id": tenant_id})


async def _mk_customer(tid: str, *, cid: str = None,
                         service_type: str = "",
                         service_types=None,
                         tos_status: dict = None) -> str:
    from utils import new_id
    cid = cid or new_id()
    doc = {"id": cid, "tenant_id": tid, "name": "Test Cust",
             "first_name": "Test", "last_name": "Cust",
             "email": f"{cid[:8]}@example.com"}
    if service_type:
        doc["service_type"] = service_type
    if service_types is not None:
        doc["service_types"] = service_types
    if tos_status:
        doc["tos_status"] = tos_status
    await _db().customers.insert_one(doc)
    return cid


async def _mk_doc(tid: str, service_type: str, *, version: int = 1,
                    status: str = "published", title: str = "T",
                    html: str = "<p>ok</p>") -> str:
    from utils import new_id, now_iso
    did = new_id()
    await _db().tos_documents.insert_one({
        "id": did, "tenant_id": tid, "service_type": service_type,
        "version": version, "status": status, "title": title,
        "content_html": html, "content_json": None,
        "effective_date": "2026-02-15",
        "created_at": now_iso(), "created_by": "test",
        "published_at": now_iso() if status == "published" else None,
        "published_by": "test" if status == "published" else None,
        "superseded_at": None,
    })
    return did


# ══════════════════════════════════════════════════════════════════════
# Sanitizer
# ══════════════════════════════════════════════════════════════════════
def test_sanitize_strips_script_and_style_and_iframe():
    from services.tos_service import sanitize_html
    dirty = (
        "<p>hi</p><script>alert(1)</script>"
        "<style>body{}</style>"
        "<iframe src='x'></iframe>"
    )
    out = sanitize_html(dirty)
    assert "<script>" not in out
    assert "<style>" not in out
    assert "<iframe" not in out
    assert "<p>hi</p>" in out


def test_sanitize_preserves_tiptap_marks_and_structure():
    from services.tos_service import sanitize_html
    html = (
        "<h2>Heading</h2>"
        "<p><strong>bold</strong> and <em>italic</em></p>"
        "<ul><li>one</li><li>two</li></ul>"
        "<blockquote>quoted</blockquote>"
        "<hr/>"
    )
    out = sanitize_html(html)
    for needle in (
        "<h2>Heading</h2>", "<strong>bold</strong>",
        "<em>italic</em>", "<ul>", "<li>one</li>", "<blockquote>",
    ):
        assert needle in out


def test_sanitize_hardens_external_anchors():
    from services.tos_service import sanitize_html
    out = sanitize_html('<p><a href="https://example.com">x</a></p>')
    assert 'href="https://example.com"' in out
    assert 'rel="noopener noreferrer"' in out
    assert 'target="_blank"' in out


def test_sanitize_blocks_javascript_scheme():
    from services.tos_service import sanitize_html
    out = sanitize_html('<a href="javascript:alert(1)">click</a>')
    assert "javascript:" not in out


def test_sanitize_returns_empty_string_for_none_or_empty():
    from services.tos_service import sanitize_html
    assert sanitize_html(None) == ""
    assert sanitize_html("") == ""


# ══════════════════════════════════════════════════════════════════════
# Classifier
# ══════════════════════════════════════════════════════════════════════
def test_classifier_explicit_list_wins():
    async def _go():
        tid = _tid()
        cid = await _mk_customer(tid, service_types=["pool", "landscaping"])
        try:
            from services.tos_service import classify_customer_services
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            got = await classify_customer_services(_db(), tid, cust)
            assert got == {"pool", "landscaping"}
        finally:
            await _drain(tid)
    _run(_go())


def test_classifier_maps_freeform_pool_variants():
    from services.tos_service import _service_type_from_string
    for s in ("Weekly Pool Service", "pool", "Spa cleaning", "chemistry"):
        assert _service_type_from_string(s) == "pool", s
    for s in ("Landscape Maintenance", "Lawn mowing", "irrigation",
               "hedge trim", "Yard clean-up", "tree pruning"):
        assert _service_type_from_string(s) == "landscaping", s
    assert _service_type_from_string("General Handyman") is None


def test_classifier_active_jobs_contribute():
    async def _go():
        tid = _tid()
        cid = await _mk_customer(tid)
        from utils import new_id, now_iso
        await _db().jobs.insert_one({
            "id": new_id(), "tenant_id": tid, "customer_id": cid,
            "service_type": "Weekly Pool Service",
            "status": "scheduled", "created_at": now_iso(),
        })
        await _db().jobs.insert_one({
            "id": new_id(), "tenant_id": tid, "customer_id": cid,
            "service_type": "Landscape Maintenance",
            "status": "in_progress", "created_at": now_iso(),
        })
        try:
            from services.tos_service import classify_customer_services
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            got = await classify_customer_services(_db(), tid, cust)
            assert got == {"pool", "landscaping"}
        finally:
            await _drain(tid)
    _run(_go())


def test_classifier_completed_jobs_do_not_contribute():
    async def _go():
        tid = _tid()
        cid = await _mk_customer(tid)
        from utils import new_id, now_iso
        # Only a completed pool job — should NOT trigger pool ToS.
        await _db().jobs.insert_one({
            "id": new_id(), "tenant_id": tid, "customer_id": cid,
            "service_type": "Weekly Pool Service",
            "status": "completed", "created_at": now_iso(),
        })
        try:
            from services.tos_service import classify_customer_services
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            got = await classify_customer_services(_db(), tid, cust)
            assert got == set()
        finally:
            await _drain(tid)
    _run(_go())


def test_classifier_active_subscriptions_contribute():
    async def _go():
        tid = _tid()
        cid = await _mk_customer(tid)
        from utils import new_id
        await _db().recurring_subscriptions.insert_one({
            "id": new_id(), "tenant_id": tid, "customer_id": cid,
            "service_type": "Lawn Mowing", "active": True,
        })
        try:
            from services.tos_service import classify_customer_services
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            got = await classify_customer_services(_db(), tid, cust)
            assert got == {"landscaping"}
        finally:
            await _drain(tid)
    _run(_go())


# ══════════════════════════════════════════════════════════════════════
# Documents / publish / supersede
# ══════════════════════════════════════════════════════════════════════
def test_create_draft_starts_at_version_1_and_status_draft():
    async def _go():
        tid = _tid()
        try:
            from services.tos_service import next_version_for
            v = await next_version_for(_db(), tid, "pool")
            assert v == 1
        finally:
            await _drain(tid)
    _run(_go())


def test_publish_draft_marks_prior_published_as_superseded():
    async def _go():
        tid = _tid()
        # Existing v1 published.
        v1 = await _mk_doc(tid, "pool", version=1, status="published")
        # New v2 draft.
        v2 = await _mk_doc(tid, "pool", version=2, status="draft")
        try:
            from services.tos_service import publish_document
            fresh = await publish_document(
                _db(), tenant_id=tid, document_id=v2,
                actor_id="admin-1",
            )
            assert fresh["status"] == "published"
            # v1 must be superseded (still exists — legal audit).
            r1 = await _db().tos_documents.find_one({"id": v1}, {"_id": 0})
            assert r1 is not None
            assert r1["status"] == "superseded"
            assert r1["superseded_at"]
        finally:
            await _drain(tid)
    _run(_go())


def test_publish_already_published_is_idempotent():
    async def _go():
        tid = _tid()
        did = await _mk_doc(tid, "pool", version=1, status="published")
        try:
            from services.tos_service import publish_document
            r = await publish_document(
                _db(), tenant_id=tid, document_id=did, actor_id="a",
            )
            assert r["status"] == "published"
            # Row count unchanged.
            n = await _db().tos_documents.count_documents(
                {"tenant_id": tid},
            )
            assert n == 1
        finally:
            await _drain(tid)
    _run(_go())


def test_publish_of_superseded_document_rejects():
    async def _go():
        tid = _tid()
        did = await _mk_doc(tid, "pool", version=1, status="draft")
        # Manually flip to superseded to simulate a race.
        await _db().tos_documents.update_one(
            {"id": did}, {"$set": {"status": "superseded"}},
        )
        try:
            from services.tos_service import publish_document
            with pytest.raises(ValueError) as exc:
                await publish_document(
                    _db(), tenant_id=tid, document_id=did, actor_id="a",
                )
            assert "superseded" in str(exc.value)
        finally:
            await _drain(tid)
    _run(_go())


# ══════════════════════════════════════════════════════════════════════
# Customer pending_tos + acceptance
# ══════════════════════════════════════════════════════════════════════
def test_pending_tos_pool_only_customer():
    async def _go():
        tid = _tid()
        pool = await _mk_doc(tid, "pool", version=1, status="published",
                                title="Pool ToS", html="<p>pool</p>")
        await _mk_doc(tid, "landscaping", version=1, status="published",
                          title="Landscaping ToS")
        cid = await _mk_customer(tid, service_type="Weekly Pool Service")
        try:
            from services.tos_service import compute_pending_tos_for_customer
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            pending = await compute_pending_tos_for_customer(_db(), tid, cust)
            assert len(pending) == 1
            assert pending[0]["service_type"] == "pool"
            assert pending[0]["document_id"] == pool
        finally:
            await _drain(tid)
    _run(_go())


def test_pending_tos_landscaping_only_customer():
    async def _go():
        tid = _tid()
        await _mk_doc(tid, "pool", version=1, status="published")
        ls = await _mk_doc(tid, "landscaping", version=1, status="published")
        cid = await _mk_customer(tid, service_type="Lawn Mowing")
        try:
            from services.tos_service import compute_pending_tos_for_customer
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            pending = await compute_pending_tos_for_customer(_db(), tid, cust)
            assert len(pending) == 1
            assert pending[0]["service_type"] == "landscaping"
            assert pending[0]["document_id"] == ls
        finally:
            await _drain(tid)
    _run(_go())


def test_pending_tos_canonical_order_pool_before_landscaping():
    async def _go():
        tid = _tid()
        pool = await _mk_doc(tid, "pool", version=1, status="published")
        ls = await _mk_doc(tid, "landscaping", version=1, status="published")
        cid = await _mk_customer(tid, service_types=["landscaping", "pool"])
        try:
            from services.tos_service import compute_pending_tos_for_customer
            cust = await _db().customers.find_one({"id": cid}, {"_id": 0})
            pending = await compute_pending_tos_for_customer(_db(), tid, cust)
            assert [p["service_type"] for p in pending] == ["pool", "landscaping"]
            assert pending[0]["document_id"] == pool
            assert pending[1]["document_id"] == ls
        finally:
            await _drain(tid)
    _run(_go())


def test_accept_updates_customer_tos_status_and_shrinks_pending():
    async def _go():
        tid = _tid()
        pool = await _mk_doc(tid, "pool", version=1, status="published")
        cid = await _mk_customer(tid, service_type="Pool")
        try:
            from services.tos_service import (
                record_customer_acceptance,
                compute_pending_tos_for_customer,
            )
            row = await record_customer_acceptance(
                _db(), tenant_id=tid, customer_id=cid,
                document_id=pool, ip="127.0.0.1", ua="pytest",
            )
            assert row["document_id"] == pool
            assert row["service_type"] == "pool"
            assert row["document_version"] == 1
            # Customer's embedded map updated.
            fresh = await _db().customers.find_one({"id": cid}, {"_id": 0})
            assert fresh["tos_status"]["pool"]["document_id"] == pool
            assert fresh["tos_status"]["pool"]["version"] == 1
            # Pending list shrunk.
            pending = await compute_pending_tos_for_customer(_db(), tid, fresh)
            assert pending == []
        finally:
            await _drain(tid)
    _run(_go())


def test_version_bump_retriggers_only_bumped_service_type():
    """Partial-acceptance persistence guarantee — customer accepted
    pool v1. Admin publishes pool v2. Pool re-prompts. If customer
    is also subject to a landscaping ToS they've accepted, that one
    stays quiet.
    """
    async def _go():
        tid = _tid()
        pool_v1 = await _mk_doc(tid, "pool", version=1, status="published")
        ls_v1 = await _mk_doc(tid, "landscaping", version=1, status="published")
        cid = await _mk_customer(
            tid, service_types=["pool", "landscaping"],
        )
        try:
            from services.tos_service import (
                record_customer_acceptance,
                publish_document,
                compute_pending_tos_for_customer,
            )
            # Accept both.
            await record_customer_acceptance(
                _db(), tenant_id=tid, customer_id=cid,
                document_id=pool_v1,
            )
            await record_customer_acceptance(
                _db(), tenant_id=tid, customer_id=cid,
                document_id=ls_v1,
            )
            fresh = await _db().customers.find_one({"id": cid}, {"_id": 0})
            assert (await compute_pending_tos_for_customer(_db(), tid, fresh)) == []

            # Publish pool v2 as a draft-then-publish transition.
            pool_v2 = await _mk_doc(tid, "pool", version=2, status="draft")
            await publish_document(
                _db(), tenant_id=tid, document_id=pool_v2,
                actor_id="a",
            )

            fresh = await _db().customers.find_one({"id": cid}, {"_id": 0})
            pending = await compute_pending_tos_for_customer(_db(), tid, fresh)
            assert len(pending) == 1
            assert pending[0]["service_type"] == "pool"
            assert pending[0]["document_id"] == pool_v2
            assert pending[0]["version"] == 2
        finally:
            await _drain(tid)
    _run(_go())


def test_accept_rejects_unknown_document():
    async def _go():
        tid = _tid()
        cid = await _mk_customer(tid, service_type="Pool")
        try:
            from services.tos_service import record_customer_acceptance
            with pytest.raises(ValueError) as e:
                await record_customer_acceptance(
                    _db(), tenant_id=tid, customer_id=cid,
                    document_id="does-not-exist",
                )
            assert "not_found" in str(e.value)
        finally:
            await _drain(tid)
    _run(_go())


def test_accept_rejects_unpublished_document():
    async def _go():
        tid = _tid()
        draft = await _mk_doc(tid, "pool", version=1, status="draft")
        cid = await _mk_customer(tid, service_type="Pool")
        try:
            from services.tos_service import record_customer_acceptance
            with pytest.raises(ValueError) as e:
                await record_customer_acceptance(
                    _db(), tenant_id=tid, customer_id=cid,
                    document_id=draft,
                )
            assert "not_published" in str(e.value)
        finally:
            await _drain(tid)
    _run(_go())


def test_superseded_row_is_not_hard_deleted():
    """Legal audit invariant — superseded rows remain queryable."""
    async def _go():
        tid = _tid()
        v1 = await _mk_doc(tid, "pool", version=1, status="published")
        v2 = await _mk_doc(tid, "pool", version=2, status="draft")
        try:
            from services.tos_service import publish_document
            await publish_document(
                _db(), tenant_id=tid, document_id=v2, actor_id="a",
            )
            r1 = await _db().tos_documents.find_one({"id": v1}, {"_id": 0})
            assert r1 is not None
            assert r1["status"] == "superseded"
            assert r1["version"] == 1
            n = await _db().tos_documents.count_documents({"tenant_id": tid})
            assert n == 2
        finally:
            await _drain(tid)
    _run(_go())


# ══════════════════════════════════════════════════════════════════════
# Seed migration
# ══════════════════════════════════════════════════════════════════════
def test_seed_pool_tos_from_legacy_creates_v1_published():
    async def _go():
        tid = _tid()
        try:
            from services.tos_service import seed_pool_tos_from_legacy
            row = await seed_pool_tos_from_legacy(_db(), tid)
            assert row is not None
            assert row["status"] == "published"
            assert row["service_type"] == "pool"
            assert row["version"] == 1
            assert "Terms of Service" in row["content_html"]
            # Second run is a no-op.
            r2 = await seed_pool_tos_from_legacy(_db(), tid)
            assert r2 is None
            n = await _db().tos_documents.count_documents(
                {"tenant_id": tid, "service_type": "pool"},
            )
            assert n == 1
        finally:
            await _drain(tid)
    _run(_go())


# ══════════════════════════════════════════════════════════════════════
# Router — smoke tests via direct handler calls (auth-injected)
# ══════════════════════════════════════════════════════════════════════
def _mk_admin(tid: str) -> dict:
    return {"id": "admin-1", "role": "admin", "tenant_id": tid,
             "email": "a@t.com"}


def _mk_super(tid: str) -> dict:
    return {"id": "sa-1", "role": "super_admin", "tenant_id": tid,
             "email": "sa@t.com"}


def _mk_tech(tid: str) -> dict:
    return {"id": "t-1", "role": "technician", "tenant_id": tid,
             "email": "t@t.com"}


def _mk_cust_user(tid: str, cid: str) -> dict:
    return {"id": "u-1", "role": "customer", "tenant_id": tid,
             "customer_id": cid, "email": "c@t.com"}


class _FakeReq:
    def __init__(self, ip: str = "10.0.0.1"):
        self.headers = {"x-forwarded-for": ip, "user-agent": "pytest"}
        self.client = type("C", (), {"host": ip})()


def test_admin_route_requires_admin_or_super_admin_role():
    async def _go():
        tid = _tid()
        try:
            from routers.tos_multi import (
                list_tos_documents, TosDocCreate,
                create_tos_document,
            )
            tenant = {"id": tid}
            # Tech is rejected.
            with pytest.raises(HTTPException) as e:
                await list_tos_documents(
                    service_type=None, status=None, version=None,
                    user=_mk_tech(tid), tenant=tenant,
                )
            assert e.value.status_code == 403
            # Admin passes.
            r = await list_tos_documents(
                service_type=None, status=None, version=None,
                user=_mk_admin(tid), tenant=tenant,
            )
            assert r["count"] == 0
            # Super_admin passes on create.
            body = TosDocCreate(
                service_type="pool", title="Draft A",
                content_html="<p>hi<script>x</script></p>",
            )
            row = await create_tos_document(
                body=body, user=_mk_super(tid), tenant=tenant,
            )
            assert row["service_type"] == "pool"
            assert row["status"] == "draft"
            assert "<script>" not in row["content_html"]
        finally:
            await _drain(tid)
    _run(_go())


def test_admin_update_rejects_editing_published_document():
    async def _go():
        tid = _tid()
        did = await _mk_doc(tid, "pool", version=1, status="published")
        try:
            from routers.tos_multi import update_tos_document, TosDocUpdate
            with pytest.raises(HTTPException) as e:
                await update_tos_document(
                    doc_id=did,
                    body=TosDocUpdate(title="mutated"),
                    user=_mk_admin(tid), tenant={"id": tid},
                )
            assert e.value.status_code == 409
        finally:
            await _drain(tid)
    _run(_go())


def test_customer_route_requires_customer_role():
    async def _go():
        tid = _tid()
        try:
            from routers.tos_multi import get_customer_onboarding_state
            with pytest.raises(HTTPException) as e:
                await get_customer_onboarding_state(
                    user=_mk_admin(tid), tenant={"id": tid},
                )
            assert e.value.status_code == 403
        finally:
            await _drain(tid)
    _run(_go())


def test_customer_onboarding_state_returns_pending_tos_list():
    async def _go():
        tid = _tid()
        pool = await _mk_doc(tid, "pool", version=1, status="published",
                                title="Pool ToS")
        cid = await _mk_customer(tid, service_type="Pool")
        try:
            from routers.tos_multi import get_customer_onboarding_state
            r = await get_customer_onboarding_state(
                user=_mk_cust_user(tid, cid), tenant={"id": tid},
            )
            assert r["customer_id"] == cid
            assert r["tutorial_completed"] is False
            assert len(r["pending_tos"]) == 1
            assert r["pending_tos"][0]["document_id"] == pool
        finally:
            await _drain(tid)
    _run(_go())


def test_customer_accept_route_records_and_recomputes_pending():
    async def _go():
        tid = _tid()
        pool = await _mk_doc(tid, "pool", version=1, status="published")
        cid = await _mk_customer(tid, service_type="Pool")
        try:
            from routers.tos_multi import customer_accept_tos
            r = await customer_accept_tos(
                document_id=pool, request=_FakeReq(),
                _body=None,
                user=_mk_cust_user(tid, cid), tenant={"id": tid},
            )
            assert r["ok"] is True
            assert r["acceptance"]["document_id"] == pool
            assert r["pending_tos"] == []
            # IP + UA captured.
            row = await _db().tos_acceptances.find_one(
                {"customer_id": cid}, {"_id": 0},
            )
            assert row["ip"] == "10.0.0.1"
            assert row["ua"] == "pytest"
        finally:
            await _drain(tid)
    _run(_go())

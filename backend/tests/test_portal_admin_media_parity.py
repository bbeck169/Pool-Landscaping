"""DATA-PARITY-C3 · Feb-2026 — Portal/admin media parity.

Locks the shared ``services.customer_media.get_customer_media``
reader + the thin portal routers that delegate to it.  Pre-fix
state: three competing endpoints (two of them dead code via
FastAPI first-match ordering) each walked a DIFFERENT subset of
the four media sources — portal customers never saw admin-
uploaded ``files`` images AND never saw ``jobs.photos[]`` embedded
tech uploads.

Tests
─────
  1. Shared reader returns BOTH jobs.photos[] + files-collection
     images for the same customer (the pre-fix gap).
  2. Portal /api/portal/photos (now a thin wrapper) returns the
     same media_id set as the admin-side shared reader call.
  3. ``hidden_from_portal`` on a job hides EVERY embedded photo
     from the portal (but admin still sees them).
  4. Audit endpoint reports drifted customers under the admin
     role gate (403 for non-admin).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


_PREFIX = "TEST-media-parity-"


def _mk_tid() -> str:
    return _PREFIX + uuid.uuid4().hex[:12]


def _mk_cid() -> str:
    return _PREFIX + "c-" + uuid.uuid4().hex[:12]


async def _seed(db, tid: str, cid: str,
                 *, hidden_from_portal: bool = False) -> str:
    """Seed one customer, one job (with 1 embedded photo), one file
    (admin-uploaded, image/jpeg) linked to the job.
    Returns the job_id for test assertions."""
    jid = _PREFIX + "j-" + uuid.uuid4().hex[:10]
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Media Fixture",
    })
    await db.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "title": "Pool clean", "service_type": "pool",
        "status": "completed",
        "hidden_from_portal": hidden_from_portal,
        "photos": [{
            "id": _PREFIX + "p-" + uuid.uuid4().hex[:8],
            "url": "/mock/photo-a.jpg",
            "mime": "image/jpeg",
            "visibility": "customer",
            "uploaded_at": "2026-10-10T10:00:00+00:00",
        }],
    })
    # Admin-uploaded file linked to the job.
    await db.files.insert_one({
        "id": _PREFIX + "f-" + uuid.uuid4().hex[:8],
        "tenant_id": tid,
        "is_deleted": False,
        "content_type": "image/png",
        "linked_entity_type": "job",
        "linked_entity_id": jid,
        "original_filename": "admin-upload.png",
        "size": 1024,
        "created_at": "2026-10-11T10:00:00+00:00",
    })
    return jid


async def _cleanup(db, tid: str) -> None:
    await db.customers.delete_many({"tenant_id": tid})
    await db.jobs.delete_many({"tenant_id": tid})
    await db.files.delete_many({"tenant_id": tid})


def _rebind(db) -> None:
    import routers.portal_photos as _pp
    import routers.admin_migrations as _am
    _pp.db = db
    _am.db = db


# ═══════════════════════════════════════════════════════════════════
# 1. Shared reader merges jobs.photos + files-collection.
# ═══════════════════════════════════════════════════════════════════
def test_shared_reader_merges_jobs_photos_and_admin_files():
    async def _go(db):
        from services.customer_media import get_customer_media
        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed(db, tid, cid)
            bag = await get_customer_media(
                db, tid, cid, kind="photo",
                for_portal=True, limit=50, offset=0,
            )
            sources = {i["source"] for i in bag["items"]}
            assert "job" in sources, (
                "Shared reader missed jobs.photos[] — regression of "
                "the DATA-PARITY-C3 fix."
            )
            assert "file" in sources, (
                "Shared reader missed admin-uploaded files — "
                "regression of the DATA-PARITY-C3 fix."
            )
            assert bag["total"] == 2
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. Portal endpoint returns the same media_id set as admin.
# ═══════════════════════════════════════════════════════════════════
def test_portal_photos_endpoint_matches_admin_shared_reader():
    async def _go(db):
        _rebind(db)
        from routers.portal_photos import portal_photos
        from services.customer_media import get_customer_media

        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed(db, tid, cid)
            user = {"role": "customer", "customer_id": cid, "id": "u-c"}
            tenant = {"id": tid}
            portal_resp = await portal_photos(
                limit=50, offset=0, job_id=None,
                user=user, tenant=tenant,
            )
            admin_bag = await get_customer_media(
                db, tid, cid, kind="photo",
                for_portal=False, limit=50, offset=0,
            )

            portal_count = len(portal_resp["photos"])
            admin_count = admin_bag["total"]
            assert portal_count == admin_count, (
                f"Portal {portal_count} photos != admin "
                f"{admin_count} photos — parity regressed."
            )
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. hidden_from_portal hides every embedded photo on the entity
#    from portal, but admin still sees them.
# ═══════════════════════════════════════════════════════════════════
def test_hidden_from_portal_hides_embedded_media_from_portal_only():
    async def _go(db):
        _rebind(db)
        from routers.portal_photos import portal_photos
        from services.customer_media import get_customer_media

        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed(db, tid, cid, hidden_from_portal=True)
            user = {"role": "customer", "customer_id": cid, "id": "u-c"}
            tenant = {"id": tid}
            portal_resp = await portal_photos(
                limit=50, offset=0, job_id=None,
                user=user, tenant=tenant,
            )
            admin_bag = await get_customer_media(
                db, tid, cid, kind="photo",
                for_portal=False, limit=50, offset=0,
            )
            # Portal: the file-collection item still shows
            # (hidden_from_portal is on the JOB, not the file).
            # The embedded jobs.photos[] item is hidden.
            portal_sources = {i["source"] for i in [
                {"source": p.get("source")} for p in portal_resp["photos"]
            ]}
            assert "job" not in portal_sources, (
                "Embedded jobs.photos[] leaked despite "
                "hidden_from_portal=True on the job."
            )
            # Admin still sees everything.
            admin_sources = {i["source"] for i in admin_bag["items"]}
            assert "job" in admin_sources
            assert "file" in admin_sources
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. Audit endpoint auth gate.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["customer", "technician"])
def test_media_audit_endpoint_rejects_non_admin(role):
    async def _go(db):
        _rebind(db)
        from routers.admin_migrations import run_customer_media_audit
        user = {"id": "u", "role": role}
        tenant = {"id": "t-x"}
        with pytest.raises(HTTPException) as excinfo:
            await run_customer_media_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )
        assert excinfo.value.status_code == 403

    run_test(_go)


def test_media_audit_endpoint_admin_dry_run_returns_report_shape():
    async def _go(db):
        _rebind(db)
        from routers.admin_migrations import run_customer_media_audit
        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            # Seed a hidden-from-portal customer so the audit
            # reports exactly one drift.
            await _seed(db, tid, cid, hidden_from_portal=True)
            user = {"id": "admin-x", "role": "admin"}
            tenant = {"id": tid}
            r = await run_customer_media_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )
            assert r["ok"] is True
            assert r["fix"] is False
            assert r["tenant_id"] == tid
            assert r["customers_scanned"] >= 1
            assert r["customers_drifted"] >= 1
            assert "mismatches" in r
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5. Mini-fix (Feb-2026) · Audit must NOT false-positive on items
#    excluded by per-item filters (``visibility="internal"`` or
#    ``is_deleted=True``).  Only ``hidden_from_portal`` on the parent
#    entity counts as drift.
# ═══════════════════════════════════════════════════════════════════
def test_media_audit_ignores_per_item_visibility_internal():
    """One customer with THREE media items on a single job:

      * photo A — ``visibility="customer"``, parent not hidden
                  (visible on both admin + portal → not drift)
      * video B — ``visibility="internal"``, parent not hidden
                  (hidden on portal by per-item filter, but NOT a
                  ``hidden_from_portal`` decision — must NOT inflate
                  drift)
      * photo C — on a SECOND job with ``hidden_from_portal=True``
                  (legit drift → counts as 1)

    Expected: audit reports ``customers_drifted == 1`` with exactly
    one entry in ``hidden_media_ids`` (photo C's id)."""

    async def _go(db):
        _rebind(db)
        from routers.admin_migrations import run_customer_media_audit

        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            jid_visible = _PREFIX + "j-" + uuid.uuid4().hex[:10]
            jid_hidden = _PREFIX + "j-" + uuid.uuid4().hex[:10]
            visible_photo_id = _PREFIX + "p-" + uuid.uuid4().hex[:8]
            internal_video_id = _PREFIX + "v-" + uuid.uuid4().hex[:8]
            hidden_photo_id = _PREFIX + "p-" + uuid.uuid4().hex[:8]

            await db.customers.insert_one({
                "id": cid, "tenant_id": tid, "name": "Internal Vis Fixture",
            })
            # Job 1 — not hidden; carries one visible photo + one
            # internal-only video that the portal correctly skips.
            await db.jobs.insert_one({
                "id": jid_visible, "tenant_id": tid, "customer_id": cid,
                "title": "Visible job", "service_type": "pool",
                "status": "completed",
                "hidden_from_portal": False,
                "photos": [{
                    "id": visible_photo_id,
                    "url": "/mock/photo-visible.jpg",
                    "mime": "image/jpeg",
                    "visibility": "customer",
                    "uploaded_at": "2026-10-10T10:00:00+00:00",
                }],
                "videos": [{
                    "id": internal_video_id,
                    "url": "/mock/video-internal.mp4",
                    "mime": "video/mp4",
                    "visibility": "internal",
                    "uploaded_at": "2026-10-10T10:05:00+00:00",
                }],
            })
            # Job 2 — hidden_from_portal; one embedded photo that
            # is the ONLY legitimate drift we expect to report.
            await db.jobs.insert_one({
                "id": jid_hidden, "tenant_id": tid, "customer_id": cid,
                "title": "Hidden job", "service_type": "pool",
                "status": "completed",
                "hidden_from_portal": True,
                "photos": [{
                    "id": hidden_photo_id,
                    "url": "/mock/photo-hidden.jpg",
                    "mime": "image/jpeg",
                    "visibility": "customer",
                    "uploaded_at": "2026-10-10T10:10:00+00:00",
                }],
            })

            user = {"id": "admin-x", "role": "admin"}
            tenant = {"id": tid}
            r = await run_customer_media_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )

            assert r["ok"] is True
            assert r["customers_scanned"] == 1
            assert r["customers_drifted"] == 1, (
                "Audit over-counted drift — ``visibility=internal`` "
                "or ``is_deleted`` items should NOT appear as "
                "``hidden_from_portal`` drift. "
                f"Report: {r}"
            )
            assert len(r["mismatches"]) == 1
            m = r["mismatches"][0]
            assert m["customer_id"] == cid
            # EXACTLY the hidden_from_portal photo is reported;
            # the internal video is NOT.
            assert m["hidden_media_ids"] == [hidden_photo_id], (
                f"Unexpected drift media_ids: {m['hidden_media_ids']} "
                f"(expected only [{hidden_photo_id}])"
            )
            assert internal_video_id not in m["hidden_media_ids"]
        finally:
            await _cleanup(db, tid)

    run_test(_go)

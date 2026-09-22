"""Phase P31 · Feb-2026 — Customer-details endpoint jobs projection.

Locks in the ``JOBS_LIST_PROJECTION`` shape on
``GET /api/customers/{cid}`` so photo base64 blobs never cross the
Mongo → API-process wire on a profile-page load.

Coverage:

1. **Field contract** — the embedded ``jobs`` array on the response
   preserves every field the FE consumer reads (``id``, ``title``,
   ``scheduled_date``, ``technician_name``, ``status``).
2. **Slim-photos shape** — ``photos`` is NOT present; ``photo_count``
   and ``photo_ids`` ARE.
3. **Wire-size delta** — a customer with 20 jobs × 500KB of photo
   data no longer ships 10MB. The response body size stays well
   under 1MB (should be well under 100KB for a shape-only payload).
4. **Baseline** — the endpoint still returns the customer doc + its
   jobs list (positive-signal assertion so a future refactor that
   accidentally drops the jobs field trips this test).

Executes via the F7 loop-bound Mongo + the FastAPI direct-call
path (no HTTP stack) so the test cost is bounded by the seed size.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any, Dict, List

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════
def _big_photo(kbytes: int = 500) -> Dict[str, Any]:
    """Mint a photo sub-doc with an inline base64 blob of ~``kbytes``
    KB — matches the schema written by
    ``routers/jobs.py:POST /jobs/{jid}/photos``."""
    raw = b"P31" * (kbytes * 1024 // 3)  # ~kbytes KB pre-base64
    return {
        "id": str(uuid.uuid4()),
        "data": base64.b64encode(raw).decode("ascii"),
        "label": "big-photo",
        "created_at": "2026-02-01T00:00:00Z",
    }


async def _seed_customer_with_heavy_jobs(
    db, *, tenant_id: str, cid: str, job_count: int = 20,
    photos_per_job: int = 1, kbytes_per_photo: int = 500,
) -> List[str]:
    """Seed one customer + ``job_count`` jobs, each carrying
    ``photos_per_job`` photos of ~``kbytes_per_photo`` KB. Returns
    the list of job ids."""
    await db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "P31 Heavy Customer", "email": "p31@example.test",
        "is_active": True,
    })
    job_ids: List[str] = []
    for i in range(job_count):
        jid = f"j-{uuid.uuid4().hex[:8]}"
        job_ids.append(jid)
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id, "customer_id": cid,
            "title": f"Service #{i}", "status": "completed",
            "scheduled_date": f"2026-01-{(i % 28) + 1:02d}",
            "service_type": "Weekly Pool Service",
            "technician_name": "Mike Rodriguez",
            "photos": [_big_photo(kbytes_per_photo)
                        for _ in range(photos_per_job)],
        })
    return job_ids


# ═════════════════════════════════════════════════════════════════════
# 1. Field-shape contract.
# ═════════════════════════════════════════════════════════════════════
def test_p31_customer_details_strips_photos_data_from_wire():
    """``GET /customers/{cid}`` returns embedded jobs WITHOUT the
    heavy ``photos`` array (base64 blobs), but WITH ``photo_count``
    and ``photo_ids`` decorators."""
    from routers.customers import get_customer

    async def _go(db):
        tid = f"t-p31-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _seed_customer_with_heavy_jobs(
            db, tenant_id=tid, cid=cid, job_count=3,
            photos_per_job=2, kbytes_per_photo=50,
        )
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Test"}
            res = await get_customer(cid, user=user, tenant=tenant)
            assert "jobs" in res
            jobs = res["jobs"]
            assert len(jobs) == 3
            for j in jobs:
                # Photos array MUST NOT be present (dropped by
                # slim_photos_on_rows when include_photos=False).
                assert "photos" not in j, (
                    f"Job {j.get('id')} still ships full photos "
                    f"array — regression against P31 projection"
                )
                # Slim decorators ARE present.
                assert "photo_count" in j
                assert j["photo_count"] == 2
                assert "photo_ids" in j
                assert len(j["photo_ids"]) == 2
                # FE-required fields all present.
                for k in ("id", "title", "scheduled_date",
                           "technician_name", "status"):
                    assert k in j, f"missing FE-required field: {k}"
        finally:
            await db.jobs.delete_many({"customer_id": cid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2. Wire-size delta — dramatic vs pre-P31.
# ═════════════════════════════════════════════════════════════════════
def test_p31_wire_size_stays_bounded_with_heavy_photo_seed():
    """With 20 jobs × 500KB photo each, the pre-P31 shape would
    ship ~10MB per profile load. Post-P31 the wire payload must
    stay comfortably under 100KB — a > 100x reduction."""
    from routers.customers import get_customer

    async def _go(db):
        tid = f"t-p31w-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        job_count = 20
        photos_per_job = 1
        kbytes_per_photo = 500
        await _seed_customer_with_heavy_jobs(
            db, tenant_id=tid, cid=cid,
            job_count=job_count, photos_per_job=photos_per_job,
            kbytes_per_photo=kbytes_per_photo,
        )
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Wire Test"}
            t0 = time.perf_counter()
            res = await get_customer(cid, user=user, tenant=tenant)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            # Serialize as JSON to measure the wire payload size.
            wire = json.dumps(res, default=str)
            size_kb = len(wire.encode("utf-8")) / 1024
            print(
                f"\n[P31 wire] size={size_kb:.1f}KB "
                f"(vs pre-P31 ~{job_count * photos_per_job * kbytes_per_photo}KB "
                f"of photo blobs alone) latency={elapsed_ms:.0f}ms"
            )
            # Post-P31: well under 100KB. Empirically ~10-30KB for
            # a 20-job seed depending on default fields.
            assert size_kb < 100, (
                f"Wire payload too large: {size_kb:.1f}KB — "
                f"expected < 100KB post-P31 projection"
            )
            # Sanity — jobs are still populated.
            assert len(res["jobs"]) == job_count
            for j in res["jobs"]:
                assert j["photo_count"] == photos_per_job
        finally:
            await db.jobs.delete_many({"customer_id": cid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3. Tenant scope — a job from a DIFFERENT tenant doesn't leak.
# ═════════════════════════════════════════════════════════════════════
def test_p31_customer_details_tenant_scoped():
    """A job in tenant B with the same customer_id MUST NOT appear
    in tenant A's customer-details response."""
    from routers.customers import get_customer

    async def _go(db):
        tid_a = f"t-p31a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-p31b-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await _seed_customer_with_heavy_jobs(
            db, tenant_id=tid_a, cid=cid, job_count=2,
            photos_per_job=1, kbytes_per_photo=10,
        )
        # Plant a job in tenant B with the same customer_id.
        leaky_jid = f"leak-{uuid.uuid4().hex[:8]}"
        await db.jobs.insert_one({
            "id": leaky_jid, "tenant_id": tid_b, "customer_id": cid,
            "title": "LEAK", "status": "completed",
            "photos": [_big_photo(10)],
        })
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid_a, "name": "P31 A"}
            res = await get_customer(cid, user=user, tenant=tenant)
            job_ids = {j["id"] for j in res["jobs"]}
            assert leaky_jid not in job_ids
            assert len(res["jobs"]) == 2
        finally:
            await db.jobs.delete_many(
                {"customer_id": cid, "tenant_id": {"$in": [tid_a, tid_b]}},
            )
            await db.customers.delete_one({"id": cid})

    run_test(_go)

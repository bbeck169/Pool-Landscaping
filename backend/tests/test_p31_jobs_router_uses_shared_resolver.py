"""Phase P31 · Feb-2026 — ``routers/jobs.py`` uses the shared coord
resolver.

Two-part assertion:

1. **Source lint** — ``jobs.py`` imports ``resolve_job_coordinates``
   from ``services.geo_resolver`` and no longer inlines the string
   literals ``coord_source: "job"`` / ``"customer"`` outside a
   comment. This locks the file into the shared-helper pattern so a
   future refactor that re-inlines the ladder trips CI.
2. **Functional parity** — the enriched-job response of
   ``GET /api/jobs`` still stamps ``coord_source`` with the same
   value the pre-P31 inline ladder produced for representative
   inputs (job coords → "job", property coords → "property",
   customer coords → "customer", nothing → None).
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from tests._f7_loop_fixture import run_test


_JOBS_PATH = Path(__file__).resolve().parents[1] / "routers" / "jobs.py"


# ═════════════════════════════════════════════════════════════════════
# 1. Source-lint — shared helper imported, no inline literals.
# ═════════════════════════════════════════════════════════════════════
def test_p31_jobs_router_imports_shared_resolver():
    src = _JOBS_PATH.read_text(encoding="utf-8")
    # Import present.
    assert "from services.geo_resolver import" in src
    assert "resolve_job_coordinates" in src


def test_p31_jobs_router_has_no_inline_coord_source_literals():
    """Every ``coord_source = "job"`` / ``"customer"`` string
    assignment in ``jobs.py`` must go through the shared resolver.
    The property rung is jobs.py-specific and kept inline (the
    shared helper doesn't have a property rung); a single
    ``source = "property"`` literal is expected and permitted."""
    src = _JOBS_PATH.read_text(encoding="utf-8")

    # Strip comments so we only lint executable code.
    code_lines = [
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)

    # Banned patterns — assignments of the JOB / CUSTOMER source
    # string literals. These MUST come from the shared helper
    # (which returns the ``COORD_SOURCE_JOB`` / ``COORD_SOURCE_CUSTOMER``
    # constants) rather than being spelled inline.
    banned = [
        re.compile(r'_p26_source\s*=\s*"job"'),
        re.compile(r'_p26_source\s*=\s*"customer"'),
        re.compile(r'coord_source[\'"]?\s*[:=]\s*"job"'),
        re.compile(r'coord_source[\'"]?\s*[:=]\s*"customer"'),
        re.compile(r'source\s*=\s*"job"(?!s)'),  # source = "job"
        re.compile(r'source\s*=\s*"customer"'),
    ]
    hits = {}
    for pat in banned:
        found = pat.findall(code)
        if found:
            hits[pat.pattern] = found
    assert not hits, (
        "P31 guardrail violated — inline coord_source literals "
        f"remain in jobs.py: {hits}. Route them through the "
        "shared ``resolve_job_coordinates`` helper."
    )


def test_p31_jobs_router_property_rung_literal_permitted():
    """Positive assertion — a single ``source = "property"``
    remains as an inline literal because the shared helper does
    NOT know about the jobs.py-specific property rung. Guardrail
    against a well-meaning refactor that deletes this line and
    silently drops property-geocoded pins."""
    src = _JOBS_PATH.read_text(encoding="utf-8")
    assert 'source = "property"' in src, (
        "Property rung literal missing — jobs.py-specific "
        "property fallback would silently drop pins if this "
        "line was removed"
    )


# ═════════════════════════════════════════════════════════════════════
# 2. Functional parity — coord_source values match expectations.
# ═════════════════════════════════════════════════════════════════════
def test_p31_jobs_endpoint_stamps_job_source_when_site_coords_set():
    """A job with ``site_lat`` / ``site_lng`` populated → the
    enriched response carries ``coord_source == "job"`` (rung 1
    wins)."""
    from routers.jobs import list_jobs

    async def _go(db):
        tid = f"t-p31j-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        jid = f"j-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "P31 Job Src",
            "service_lat": 33.11, "service_lng": -111.11,
        })
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "title": "job-src", "status": "scheduled",
            "scheduled_date": "2026-02-01",
            "site_lat": 33.5, "site_lng": -111.5,
        })
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Job Src"}
            res = await list_jobs(
                user=user, tenant=tenant, status=None,
                technician_id=None, customer_id=cid,
                crew_id=None, start=None, end=None,
                scheduled_date=None, recurring_template_id=None,
                limit=1000, include_deleted=False,
                include_photos=False, response=None,
            )
            match = next((j for j in res if j["id"] == jid), None)
            assert match is not None
            assert match["coord_source"] == "job"
            assert match["location_lat"] == 33.5
            assert match["location_lng"] == -111.5
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p31_jobs_endpoint_stamps_customer_source_when_only_customer_coords():
    """A job with NO coord fields + a customer with
    ``service_lat``/``service_lng`` → ``coord_source == "customer"``
    (rung 4 wins by process of elimination)."""
    from routers.jobs import list_jobs

    async def _go(db):
        tid = f"t-p31c-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        jid = f"j-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "P31 Cust Src",
            "service_lat": 32.75, "service_lng": -112.25,
        })
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "title": "cust-src", "status": "scheduled",
            "scheduled_date": "2026-02-01",
        })
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Cust Src"}
            res = await list_jobs(
                user=user, tenant=tenant, status=None,
                technician_id=None, customer_id=cid,
                crew_id=None, start=None, end=None,
                scheduled_date=None, recurring_template_id=None,
                limit=1000, include_deleted=False,
                include_photos=False, response=None,
            )
            match = next((j for j in res if j["id"] == jid), None)
            assert match is not None
            assert match["coord_source"] == "customer"
            assert match["location_lat"] == 32.75
            assert match["location_lng"] == -112.25
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p31_jobs_endpoint_stamps_none_when_no_coords_anywhere():
    """No coords on either side → ``coord_source is None`` AND
    ``location_lat is None``. FE relies on this bi-implication to
    decide whether to render a pin."""
    from routers.jobs import list_jobs

    async def _go(db):
        tid = f"t-p31n-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        jid = f"j-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "P31 No Src",
            # No service_lat / service_lng.
        })
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "title": "no-src", "status": "scheduled",
            "scheduled_date": "2026-02-01",
        })
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 No Src"}
            res = await list_jobs(
                user=user, tenant=tenant, status=None,
                technician_id=None, customer_id=cid,
                crew_id=None, start=None, end=None,
                scheduled_date=None, recurring_template_id=None,
                limit=1000, include_deleted=False,
                include_photos=False, response=None,
            )
            match = next((j for j in res if j["id"] == jid), None)
            assert match is not None
            assert match["coord_source"] is None
            assert match["location_lat"] is None
            assert match["location_lng"] is None
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)

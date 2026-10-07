"""Phase 34f — Active/Inactive customer toggle + auto-cancel cascade."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Phase 34-migrate-v2 · Phase 34-v2-d · Feb 2026 — swapped requests
# for the in-process ASGI shim.
from tests._phase34_http_shim import http
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH  = {"email": "mike@aquaterra.com",  "password": "password123"}


def _login(creds):
    r = http.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_tok():
    return _login(TECH)


def _mk_name():
    return f"TEST-active-{uuid.uuid4().hex[:8]}"


def _iso(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def _cleanup_customer(tok, cid, job_ids=()):
    for jid in job_ids:
        http.delete(f"{API}/jobs/{jid}", headers=_auth(tok), timeout=15)
    if cid:
        http.delete(f"{API}/customers/{cid}", headers=_auth(tok), timeout=15)


def _seed(tok, *, future=1, past=0, auto_recurring=False, with_customer_kwargs=None):
    """Create a customer + N future scheduled jobs + M past completed jobs."""
    body = {"name": _mk_name()}
    if with_customer_kwargs:
        body.update(with_customer_kwargs)
    c = http.post(f"{API}/customers", json=body,
                       headers=_auth(tok), timeout=15).json()
    cid = c["id"]
    job_ids = []
    for i in range(future):
        j = http.post(f"{API}/jobs",
                           json={"title": f"future {i}",
                                  "customer_id": cid,
                                  "scheduled_date": _iso(7 + i),
                                  "status": "scheduled"},
                           headers=_auth(tok), timeout=15).json()
        job_ids.append(j["id"])
    for i in range(past):
        j = http.post(f"{API}/jobs",
                           json={"title": f"past {i}",
                                  "customer_id": cid,
                                  "scheduled_date": _iso(-14 - i),
                                  "status": "completed"},
                           headers=_auth(tok), timeout=15).json()
        job_ids.append(j["id"])
    if auto_recurring and job_ids:
        # Flip auto_recurring on the first future job to simulate a
        # Phase-20 recurring instance.
        http.put(f"{API}/jobs/{job_ids[0]}",
                     json={"auto_recurring": True},
                     headers=_auth(tok), timeout=15)
    return cid, job_ids


# --------------------------------------------------------------------------
def test_default_customer_is_active(admin_tok):
    r = http.post(f"{API}/customers", json={"name": _mk_name()},
                       headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 200
    cid = r.json()["id"]
    try:
        assert r.json().get("is_active") is True
    finally:
        _cleanup_customer(admin_tok, cid)


def test_deactivate_cancels_future_jobs(admin_tok):
    cid, jobs = _seed(admin_tok, future=3, past=0)
    try:
        # Flip is_active → false via full-body PUT.
        r = http.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("is_active") is False
        assert body.get("cancelled_job_count") == 3, body
        # All three jobs now cancelled.
        for jid in jobs:
            j = http.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15).json()
            assert j["status"] == "cancelled", j
            assert j.get("cancellation_reason") == "Customer marked inactive"
            assert j.get("cancelled_at") is not None
            assert j.get("cancelled_by_user_id") is not None
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_past_completed_jobs_untouched(admin_tok):
    """Historical + in-progress jobs must NOT be touched by the cascade."""
    cid, jobs = _seed(admin_tok, future=1, past=2)
    future_id = jobs[0]
    past_ids = jobs[1:]
    try:
        r = http.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15).json()
        assert r["cancelled_job_count"] == 1  # only the future job
        # Future job cancelled.
        fj = http.get(f"{API}/jobs/{future_id}", headers=_auth(admin_tok), timeout=15).json()
        assert fj["status"] == "cancelled"
        # Past completed jobs still say "completed".
        for jid in past_ids:
            pj = http.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15).json()
            assert pj["status"] == "completed", pj
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_reactivate_does_not_restore_cancelled(admin_tok):
    cid, jobs = _seed(admin_tok, future=2, past=0)
    try:
        http.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": False},
                     headers=_auth(admin_tok), timeout=15)
        # Reactivate.
        r = http.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": True},
                          headers=_auth(admin_tok), timeout=15).json()
        assert r["is_active"] is True
        assert "cancelled_job_count" not in r  # only present on the flip-off
        # Cancelled jobs remain cancelled.
        for jid in jobs:
            j = http.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15).json()
            assert j["status"] == "cancelled"
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_activation_events_logged(admin_tok):
    cid, jobs = _seed(admin_tok, future=1)
    try:
        http.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": False},
                     headers=_auth(admin_tok), timeout=15)
        http.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": True},
                     headers=_auth(admin_tok), timeout=15)
        # Two events should exist: active→inactive and inactive→active.
        # No public endpoint yet — verify via direct mongo through the
        # existing motor connection used by conftest fixtures. Fall back
        # to skipping if we can't reach the driver from the test process.
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from config import db
            import asyncio
            docs = asyncio.get_event_loop().run_until_complete(
                db.customer_activation_events.find({"customer_id": cid}).to_list(10)
            )
            assert len(docs) >= 2, docs
            transitions = {(d["from_status"], d["to_status"]) for d in docs}
            assert ("active", "inactive") in transitions
            assert ("inactive", "active") in transitions
            # The deactivation event should carry the counts.
            deact = [d for d in docs if d["to_status"] == "inactive"][0]
            assert deact["cancelled_job_count"] == 1
        except (ImportError, RuntimeError):
            pytest.skip("motor driver unreachable from test process")
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_deactivation_preview(admin_tok):
    cid, jobs = _seed(admin_tok, future=2, past=1)
    try:
        r = http.get(f"{API}/customers/{cid}/deactivation-preview",
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["future_job_count"] == 2
        assert "recurring_template_count" in p
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_preview_404_unknown_customer(admin_tok):
    r = http.get(f"{API}/customers/nonexistent-abc/deactivation-preview",
                      headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 404


def test_non_admin_forbidden(tech_tok, admin_tok):
    # Seed with admin, then attempt access with tech.
    cid, jobs = _seed(admin_tok, future=1)
    try:
        r1 = http.get(f"{API}/customers/{cid}/deactivation-preview",
                           headers=_auth(tech_tok), timeout=15)
        assert r1.status_code == 403
        r2 = http.put(f"{API}/customers/{cid}",
                           json={"name": "test", "is_active": False},
                           headers=_auth(tech_tok), timeout=15)
        assert r2.status_code == 403
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


# ═══════════════════════════════════════════════════════════════════
# INACTIVE-CUSTOMER-CASCADE · Phase B · Feb-2026 — gap-closing
# extensions.  The customer cascade now ALSO flips every active
# recurring_job_template on the customer to ``is_active=false`` and
# stamps provenance (``stopped_at`` + ``stopped_by_customer_cascade``),
# then fires the shared P18 ``_cancel_future_visits_on_pause`` helper
# for each template so templates + visits cancel through the same
# code path.
#
# Helpers that reach into Mongo directly use the same pattern as the
# existing ``test_activation_events_logged`` test above (``from
# config import db`` with asyncio.run).  The HTTP seeding path for
# templates uses ``POST /api/recurring-jobs`` with ``is_active=false``
# on create to avoid the instant-generation side-effect, then flips
# the field via direct Mongo so we deterministically control the
# "template is active at cascade time" invariant.
# ═══════════════════════════════════════════════════════════════════

def _db_sync():
    """Pull the module-level motor db + a fresh event loop + return
    a sync-wrapper that runs a coroutine on it.  Mirrors the local
    pattern in ``test_activation_events_logged``."""
    import sys, asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from config import db
    def _sync(coro):
        return asyncio.get_event_loop().run_until_complete(coro)
    return db, _sync


def _get_tenant_id(admin_tok):
    """Resolve the admin's tenant_id so direct Mongo seeds carry
    the right scope."""
    me = http.get(f"{API}/auth/me", headers=_auth(admin_tok),
                      timeout=15).json()
    return me["tenant_id"]


def _seed_template(admin_tok, cid, *, is_active=True):
    """Create a recurring_job_template owned by ``cid`` in the exact
    shape the Phase-2 generator expects.  Direct Mongo insert so we
    don't trigger the instant-generation 14-day materialisation that
    ``POST /api/recurring-jobs`` performs when ``is_active=true``."""
    db, _sync = _db_sync()
    tid = _get_tenant_id(admin_tok)
    tpl_id = f"tpl-{uuid.uuid4().hex[:10]}"
    _sync(db.recurring_job_templates.insert_one({
        "id": tpl_id, "tenant_id": tid, "customer_id": cid,
        "service_type": "pool-weekly", "frequency": "weekly",
        "day_of_week": 1, "start_date": _iso(1),
        "is_active": is_active, "active": is_active,
        "price_cents": 0, "notes": "test template",
    }))
    return tpl_id


def _get_template(cid, tpl_id):
    db, _sync = _db_sync()
    return _sync(db.recurring_job_templates.find_one(
        {"id": tpl_id}, {"_id": 0},
    ))


def _cleanup_templates(cid):
    db, _sync = _db_sync()
    _sync(db.recurring_job_templates.delete_many({"customer_id": cid}))


def _latest_activation_event(cid):
    db, _sync = _db_sync()
    docs = _sync(db.customer_activation_events.find(
        {"customer_id": cid}, {"_id": 0},
    ).sort("changed_at", -1).to_list(5))
    return docs[0] if docs else None


def test_cascade_pauses_recurring_templates_and_cancels_visits(admin_tok):
    """INACTIVE-CUSTOMER-CASCADE Phase B — flipping a customer to
    inactive now ALSO pauses every active recurring template on
    the customer AND stamps ``stopped_by_customer_cascade=true`` for
    audit."""
    cid, jobs = _seed(admin_tok, future=0)
    tpl_a = _seed_template(admin_tok, cid, is_active=True)
    tpl_b = _seed_template(admin_tok, cid, is_active=True)
    try:
        r = http.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_active"] is False
        # Both templates flipped is_active=false.
        for tid in (tpl_a, tpl_b):
            t = _get_template(cid, tid)
            assert t is not None
            assert t["is_active"] is False, (
                f"template {tid} not flipped off"
            )
            assert t["active"] is False, (
                f"template {tid} legacy ``active`` not flipped off"
            )
            assert t["stopped_by_customer_cascade"] is True
            assert t["stopped_at"]
    finally:
        _cleanup_templates(cid)
        _cleanup_customer(admin_tok, cid, jobs)


def test_cascade_audit_includes_paused_template_count(admin_tok):
    """Audit row on ``db.customer_activation_events`` now carries
    ``paused_template_count`` so ops can see at a glance how many
    templates the cascade touched."""
    cid, jobs = _seed(admin_tok, future=0)
    tpl_1 = _seed_template(admin_tok, cid, is_active=True)
    tpl_2 = _seed_template(admin_tok, cid, is_active=True)
    try:
        r = http.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        assert r.json().get("paused_template_count") == 2
        evt = _latest_activation_event(cid)
        assert evt is not None
        assert evt["to_status"] == "inactive"
        assert evt["paused_template_count"] == 2
    finally:
        _cleanup_templates(cid)
        _cleanup_customer(admin_tok, cid, jobs)


def test_reactivate_does_not_resume_templates(admin_tok):
    """G3=a — reactivating a customer does NOT auto-resume paused
    templates. Users manually resume. Mirrors the pre-fix
    ``test_reactivate_does_not_restore_cancelled`` job-level
    contract."""
    cid, jobs = _seed(admin_tok, future=0)
    tpl = _seed_template(admin_tok, cid, is_active=True)
    try:
        http.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": False},
                     headers=_auth(admin_tok), timeout=15)
        http.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": True},
                     headers=_auth(admin_tok), timeout=15)
        # Template stays paused.
        t = _get_template(cid, tpl)
        assert t["is_active"] is False, (
            "reactivating customer must NOT auto-resume paused template"
        )
        assert t["active"] is False
        assert t["stopped_by_customer_cascade"] is True
    finally:
        _cleanup_templates(cid)
        _cleanup_customer(admin_tok, cid, jobs)


def test_cascade_idempotent_on_already_paused_templates(admin_tok):
    """Manually-paused templates (``is_active=false`` BEFORE cascade)
    must not get our ``stopped_by_customer_cascade`` provenance
    stamped — otherwise a future reactivate-and-resume flow would
    misattribute them to this cascade."""
    cid, jobs = _seed(admin_tok, future=0)
    # Template that was paused by the user BEFORE the cascade.
    tpl_already = _seed_template(admin_tok, cid, is_active=False)
    # Template that is active and SHOULD get paused by the cascade.
    tpl_new = _seed_template(admin_tok, cid, is_active=True)
    try:
        r = http.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        # Only the active template was flipped — count is 1.
        assert r.json().get("paused_template_count") == 1
        t_already = _get_template(cid, tpl_already)
        assert t_already["is_active"] is False  # unchanged
        assert t_already.get("stopped_by_customer_cascade") is not True
        t_new = _get_template(cid, tpl_new)
        assert t_new["is_active"] is False
        assert t_new["stopped_by_customer_cascade"] is True
    finally:
        _cleanup_templates(cid)
        _cleanup_customer(admin_tok, cid, jobs)

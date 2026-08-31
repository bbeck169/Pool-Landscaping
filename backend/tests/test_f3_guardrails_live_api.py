"""Phase F3 · Feb-2026 — LIVE API contract tests for the prophylactic
guardrails (written by the testing agent).

Covers:
  * DELETE /api/crews/{cid}          — 200 / 409 / soft-deleted refs
  * DELETE /api/customers/{cid}?mode=hard — 200 / 409
  * POST  /api/customers/bulk action=delete — 409 / proceeds
  * GET   /api/admin/data-repair/jobs/dry-run — F2 regression

All data created here is TEST_F3_ prefixed and cleaned up.
"""
import os
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE = _base.rstrip("/") + "/api"

ADMIN = ("admin@aquaterra.com", "password123")
SUPER = ("super@aquaterra.com", "password123")

TAG = "TEST_F3_" + uuid.uuid4().hex[:6]


def _login(email, password):
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:300]}"
    tok = r.json().get("access_token")
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_h():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def super_h():
    return _login(*SUPER)


@pytest.fixture(scope="function")
def created():
    """Track created ids for teardown."""
    bag = {"crews": [], "customers": [], "jobs": []}
    yield bag
    h = _login(*ADMIN)
    for jid in bag["jobs"]:
        requests.delete(f"{BASE}/jobs/{jid}", headers=h, timeout=60)
    for cid in bag["crews"]:
        requests.delete(f"{BASE}/crews/{cid}", headers=h, timeout=60)
    for cid in bag["customers"]:
        requests.delete(f"{BASE}/customers/{cid}?mode=hard", headers=h, timeout=60)


def _mk_crew(h, created, name):
    r = requests.post(f"{BASE}/crews", headers=h,
                      json={"name": f"{TAG}_{name}"}, timeout=60)
    assert r.status_code in (200, 201), f"create crew -> {r.status_code} {r.text[:300]}"
    cid = r.json()["id"]
    created["crews"].append(cid)
    return cid


def _mk_customer(h, created, name):
    r = requests.post(f"{BASE}/customers", headers=h, json={
        "name": f"{TAG} {name}",
        "email": f"{TAG.lower()}.{name.lower()}@example.test",
        "phone": "+16025550100",
        "address": "1 Test Way, Peoria, AZ 85383",
    }, timeout=60)
    assert r.status_code in (200, 201), f"create customer -> {r.status_code} {r.text[:300]}"
    cid = r.json()["id"]
    created["customers"].append(cid)
    return cid


def _mk_job(h, created, customer_id, crew_id=None):
    payload = {"title": f"{TAG} job", "customer_id": customer_id,
               "scheduled_date": "2026-12-01", "status": "pending"}
    if crew_id:
        payload["crew_id"] = crew_id
    r = requests.post(f"{BASE}/jobs", headers=h, json=payload, timeout=60)
    assert r.status_code in (200, 201), f"create job -> {r.status_code} {r.text[:400]}"
    jid = r.json()["id"]
    created["jobs"].append(jid)
    return jid


def _crew_exists(h, cid):
    r = requests.get(f"{BASE}/crews", headers=h, timeout=60)
    assert r.status_code == 200
    return any(c["id"] == cid for c in r.json())


# ── (B1) DELETE /crews/{cid} ─────────────────────────────────────────
class TestCrewDeleteGuardrail:
    def test_delete_crew_with_no_jobs_returns_200(self, admin_h, created):
        cid = _mk_crew(admin_h, created, "crewclean")
        r = requests.delete(f"{BASE}/crews/{cid}", headers=admin_h, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.json() == {"ok": True}
        assert not _crew_exists(admin_h, cid)
        created["crews"].remove(cid)

    def test_delete_crew_with_active_job_returns_409(self, admin_h, created):
        cid = _mk_crew(admin_h, created, "crewblocked")
        cust = _mk_customer(admin_h, created, "crewcust")
        _mk_job(admin_h, created, cust, crew_id=cid)

        r = requests.delete(f"{BASE}/crews/{cid}", headers=admin_h, timeout=60)
        assert r.status_code == 409, f"{r.status_code} {r.text[:400]}"
        d = r.json()["detail"]
        assert d["error_code"] == "has_referencing_jobs"
        assert d["job_count"] == 1
        assert _crew_exists(admin_h, cid), "crew must NOT be deleted"

    def test_soft_deleted_job_does_not_block_crew_delete(self, admin_h, created):
        cid = _mk_crew(admin_h, created, "crewsoft")
        cust = _mk_customer(admin_h, created, "softcust")
        jid = _mk_job(admin_h, created, cust, crew_id=cid)

        sd = requests.post(f"{BASE}/jobs/{jid}/soft-delete", headers=admin_h,
                           json={}, timeout=60)
        assert sd.status_code == 200, f"soft-delete -> {sd.status_code} {sd.text[:400]}"

        r = requests.delete(f"{BASE}/crews/{cid}", headers=admin_h, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        assert not _crew_exists(admin_h, cid)
        created["crews"].remove(cid)


# ── (B2) DELETE /customers/{cid}?mode=hard ───────────────────────────
class TestCustomerHardDeleteGuardrail:
    def test_hard_delete_blocked_by_active_job(self, admin_h, created):
        cust = _mk_customer(admin_h, created, "hardblocked")
        _mk_job(admin_h, created, cust)
        r = requests.delete(f"{BASE}/customers/{cust}?mode=hard",
                            headers=admin_h, timeout=60)
        assert r.status_code == 409, f"{r.status_code} {r.text[:400]}"
        d = r.json()["detail"]
        assert d["error_code"] == "has_referencing_jobs"
        assert d["job_count"] >= 1
        # customer still present
        g = requests.get(f"{BASE}/customers/{cust}", headers=admin_h, timeout=60)
        assert g.status_code == 200

    def test_hard_delete_proceeds_with_no_jobs(self, admin_h, created):
        cust = _mk_customer(admin_h, created, "hardclean")
        r = requests.delete(f"{BASE}/customers/{cust}?mode=hard",
                            headers=admin_h, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        g = requests.get(f"{BASE}/customers/{cust}", headers=admin_h, timeout=60)
        assert g.status_code == 404, f"expected 404 after hard delete, got {g.status_code}"
        created["customers"].remove(cust)

    def test_hard_delete_after_job_soft_deleted_proceeds(self, admin_h, created):
        cust = _mk_customer(admin_h, created, "hardsoft")
        jid = _mk_job(admin_h, created, cust)
        sd = requests.post(f"{BASE}/jobs/{jid}/soft-delete", headers=admin_h,
                           json={}, timeout=60)
        assert sd.status_code == 200, sd.text[:300]
        r = requests.delete(f"{BASE}/customers/{cust}?mode=hard",
                            headers=admin_h, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        created["customers"].remove(cust)


# ── (B3) POST /customers/bulk action=delete ──────────────────────────
class TestBulkDeleteGuardrail:
    def test_bulk_delete_blocked_when_any_id_has_active_job(self, admin_h, created):
        c_clean = _mk_customer(admin_h, created, "bulkclean")
        c_job = _mk_customer(admin_h, created, "bulkjob")
        _mk_job(admin_h, created, c_job)

        r = requests.post(f"{BASE}/customers/bulk", headers=admin_h,
                          json={"ids": [c_clean, c_job], "action": "delete"},
                          timeout=60)
        assert r.status_code == 409, f"{r.status_code} {r.text[:400]}"
        d = r.json()["detail"]
        assert d["error_code"] == "has_referencing_jobs"
        # zero customers deleted
        for cid in (c_clean, c_job):
            g = requests.get(f"{BASE}/customers/{cid}", headers=admin_h, timeout=60)
            assert g.status_code == 200, f"{cid} was deleted despite 409"

    def test_bulk_delete_proceeds_when_no_active_jobs(self, admin_h, created):
        a = _mk_customer(admin_h, created, "bulkokA")
        b = _mk_customer(admin_h, created, "bulkokB")
        r = requests.post(f"{BASE}/customers/bulk", headers=admin_h,
                          json={"ids": [a, b], "action": "delete"}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        body = r.json()
        assert body.get("deleted") == 2, body
        assert body.get("deprecated") is True
        for cid in (a, b):
            g = requests.get(f"{BASE}/customers/{cid}", headers=admin_h, timeout=60)
            assert g.status_code == 404
            created["customers"].remove(cid)


# ── (C) F2 regression ────────────────────────────────────────────────
# NOTE: order-sensitive. ``total_flagged_no_action`` counts *live*
# unassigned-pending jobs, so any TEST_F3 job created by the classes
# above inflates it. The dry-run endpoint also has a 60-s in-memory
# cache, so we poll until a fresh scan lands.
class TestZF2DryRunRegression:
    def test_dry_run_clean_state(self, super_h):
        deadline = time.time() + 150
        last = None
        while time.time() < deadline:
            r = requests.get(f"{BASE}/admin/data-repair/jobs/dry-run",
                             headers=super_h, timeout=120)
            assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
            d = r.json()
            s = d.get("summary", d)
            last = (d, s)
            assert s.get("total_would_change") == 0, d
            assert d.get("orphaned_customer_refs") == []
            assert d.get("orphaned_technician_refs") == []
            if s.get("total_flagged_no_action") == 3:
                return
            time.sleep(15)
        pytest.fail(f"dry-run never settled on flagged=3: {last[1]}")

    def test_dry_run_forbidden_for_admin(self, admin_h):
        r = requests.get(f"{BASE}/admin/data-repair/jobs/dry-run",
                         headers=admin_h, timeout=120)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}"

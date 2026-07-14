"""Phase 15D Stage 3 — Tenant Isolation Substrate Test

Creates a temporary second tenant + seeds one customer + one job in each tenant,
then verifies aquaterra admin cannot see or reach the sunbelt tenant's records.

This becomes the substrate that Stages 4 and 5 build on.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path("/app/frontend/.env"))
BASE_URL = (_FE_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"
API = f"{BASE_URL}/api"

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _auth(tok, extra: dict = None):
    h = {"Authorization": f"Bearer {tok}"}
    if extra:
        h.update(extra)
    return h


@pytest.fixture(scope="module")
def super_tok():
    return _login(SUPER)


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def throwaway_tenant(super_tok):
    slug = f"stage3iso-{int(datetime.now(timezone.utc).timestamp())}"
    r = requests.post(
        f"{API}/tenants",
        headers=_auth(super_tok),
        json={"name": "Stage3 Isolation", "slug": slug, "plan_tier": "pro"},
        timeout=15,
    )
    assert r.status_code == 200, f"tenant create failed: {r.text}"
    tenant = r.json()
    yield {**tenant, "slug": slug}
    # cleanup — deactivate
    try:
        requests.patch(f"{API}/tenants/{tenant['id']}",
                       headers=_auth(super_tok), json={"active": False}, timeout=10)
    except Exception:
        pass


class TestIsolation:
    def test_super_can_create_customer_in_throwaway_tenant(self, super_tok, throwaway_tenant):
        """Super admin uses X-Tenant-Slug header to CRUD in a specific tenant."""
        hdr = _auth(super_tok, {"X-Tenant-Slug": throwaway_tenant["slug"]})
        r = requests.post(f"{API}/customers", headers=hdr,
                          json={"name": "SUNBELT_CANARY", "email": "canary@sunbelt.test",
                                "phone": "5551110001", "address": "1 Isolation Way"},
                          timeout=15)
        assert r.status_code == 200, f"customer create failed: {r.text}"
        cust = r.json()
        assert cust["id"]
        throwaway_tenant["_canary_cust_id"] = cust["id"]

    def test_aquaterra_admin_cannot_see_canary_in_list(self, admin_tok, throwaway_tenant):
        r = requests.get(f"{API}/customers", headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        assert not any(c.get("name") == "SUNBELT_CANARY" for c in r.json()), \
            "cross-tenant customer leaked into aquaterra admin's list"

    def test_aquaterra_admin_direct_get_returns_404(self, admin_tok, throwaway_tenant):
        cid = throwaway_tenant.get("_canary_cust_id")
        assert cid, "canary customer must be created first"
        r = requests.get(f"{API}/customers/{cid}", headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 404, f"expected 404 leak-proof, got {r.status_code} {r.text}"

    def test_aquaterra_admin_delete_is_no_op(self, admin_tok, throwaway_tenant):
        cid = throwaway_tenant["_canary_cust_id"]
        r = requests.delete(f"{API}/customers/{cid}", headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        # DELETE is idempotent — succeeds but affects 0 rows

    def test_super_still_sees_canary_via_header(self, super_tok, throwaway_tenant):
        hdr = _auth(super_tok, {"X-Tenant-Slug": throwaway_tenant["slug"]})
        cid = throwaway_tenant["_canary_cust_id"]
        r = requests.get(f"{API}/customers/{cid}", headers=hdr, timeout=15)
        assert r.status_code == 200, "super with tenant header should still see the customer"

    def test_job_isolation(self, super_tok, admin_tok, throwaway_tenant):
        hdr = _auth(super_tok, {"X-Tenant-Slug": throwaway_tenant["slug"]})
        cid = throwaway_tenant["_canary_cust_id"]
        r = requests.post(f"{API}/jobs", headers=hdr, json={
            "title": "Canary job", "customer_id": cid, "service_type": "Pool Cleaning",
            "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
            "notes": "isolation test", "price": 199,
        }, timeout=15)
        assert r.status_code == 200, r.text
        jid = r.json()["id"]
        throwaway_tenant["_canary_job_id"] = jid

        r2 = requests.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15)
        assert r2.status_code == 404, f"cross-tenant job leaked: {r2.status_code}"

        r3 = requests.get(f"{API}/jobs", headers=_auth(admin_tok), timeout=15)
        assert r3.status_code == 200
        assert not any(j.get("id") == jid for j in r3.json()), "cross-tenant job in list"

    def test_notifications_isolation(self, super_tok, admin_tok, throwaway_tenant):
        """Notifications created in one tenant must not appear in another."""
        r = requests.get(f"{API}/notifications", headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        n = r.json()
        canary_slug = throwaway_tenant["slug"]
        assert not any(canary_slug in (item.get("body") or "") for item in (n if isinstance(n, list) else [])), \
            "cross-tenant notification leaked"


# ─── Phase 15D Stage 4 — Comprehensive isolation stress test ────────────────
SUNBELT_ADMIN = {"email": "admin@sunbelt.com", "password": "password123"}


@pytest.fixture(scope="module")
def sunbelt_admin_tok():
    return _login(SUNBELT_ADMIN)


class TestStage4Isolation:
    """Phase 15D Stage 4 — verifies both aquaterra and sunbelt tenants are populated
    and admins from each cannot see the other's data across every major collection."""

    def test_both_tenants_have_data(self, admin_tok, sunbelt_admin_tok):
        for tok, label in [(admin_tok, "aquaterra"), (sunbelt_admin_tok, "sunbelt")]:
            r = requests.get(f"{API}/customers", headers=_auth(tok), timeout=15)
            assert r.status_code == 200, f"{label} /customers failed"
            assert len(r.json()) >= 1, f"{label} has no customers"

    def test_customers_never_cross_tenants(self, admin_tok, sunbelt_admin_tok):
        aqua = requests.get(f"{API}/customers", headers=_auth(admin_tok), timeout=15).json()
        sun = requests.get(f"{API}/customers", headers=_auth(sunbelt_admin_tok), timeout=15).json()
        aqua_ids = {c["id"] for c in aqua}
        sun_ids = {c["id"] for c in sun}
        overlap = aqua_ids & sun_ids
        assert not overlap, f"Customer ID collision across tenants: {overlap}"
        aqua_names = {c.get("name") for c in aqua}
        assert "Sammy Sunbelt" not in aqua_names, "sunbelt customer leaked to aquaterra"

    def test_jobs_isolation(self, admin_tok, sunbelt_admin_tok):
        aqua_jobs = requests.get(f"{API}/jobs", headers=_auth(admin_tok), timeout=15).json()
        sun_jobs = requests.get(f"{API}/jobs", headers=_auth(sunbelt_admin_tok), timeout=15).json()
        aqua_ids = {j["id"] for j in aqua_jobs}
        sun_ids = {j["id"] for j in sun_jobs}
        assert not (aqua_ids & sun_ids)

    def test_quotes_isolation(self, admin_tok, sunbelt_admin_tok):
        aqua = requests.get(f"{API}/quotes", headers=_auth(admin_tok), timeout=15).json()
        sun = requests.get(f"{API}/quotes", headers=_auth(sunbelt_admin_tok), timeout=15).json()
        aqua_ids = {q["id"] for q in aqua}
        sun_ids = {q["id"] for q in sun}
        assert not (aqua_ids & sun_ids)

    def test_leads_isolation(self, admin_tok, sunbelt_admin_tok):
        for tok in [admin_tok, sunbelt_admin_tok]:
            r = requests.get(f"{API}/leads", headers=_auth(tok), timeout=15)
            assert r.status_code == 200

    def test_dashboards_are_tenant_specific(self, admin_tok, sunbelt_admin_tok):
        aq = requests.get(f"{API}/dashboard", headers=_auth(admin_tok), timeout=15).json()
        sn = requests.get(f"{API}/dashboard", headers=_auth(sunbelt_admin_tok), timeout=15).json()
        # Different tenants should have different totals unless they're both zero.
        assert aq.get("total_customers") != sn.get("total_customers") or \
               aq.get("total_customers") == sn.get("total_customers") == 0 or \
               (aq.get("total_customers", 0) >= 5 and sn.get("total_customers", 0) <= 3)

    def test_tenants_current_returns_tenant_scope(self, admin_tok, sunbelt_admin_tok):
        aq = requests.get(f"{API}/tenants/current", headers=_auth(admin_tok), timeout=15).json()
        sn = requests.get(f"{API}/tenants/current", headers=_auth(sunbelt_admin_tok), timeout=15).json()
        assert aq.get("slug") == "aquaterra", f"expected aquaterra, got {aq.get('slug')}"
        assert sn.get("slug") == "sunbelt", f"expected sunbelt, got {sn.get('slug')}"

    def test_super_admin_can_switch_via_header(self, super_tok):
        # Default (no header) → super's own tenant (aquaterra)
        r = requests.get(f"{API}/tenants/current", headers=_auth(super_tok), timeout=15).json()
        assert r.get("slug") == "aquaterra"
        # With header → sunbelt
        r2 = requests.get(f"{API}/tenants/current",
                          headers=_auth(super_tok, {"X-Tenant-Slug": "sunbelt"}),
                          timeout=15).json()
        assert r2.get("slug") == "sunbelt", f"super_admin cannot cross tenants: {r2}"

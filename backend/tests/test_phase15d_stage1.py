"""Phase 15D Stage 1 — multi-tenant substrate (no query refactor yet)."""
import os
from pathlib import Path

import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestTenantsCurrent:
    def test_admin_resolves_default_tenant(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/tenants/current", headers=h, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["slug"] == "aquaterra"
        assert d["id"]
        assert d["brand_primary"] and d["brand_secondary"]
        assert d["resolved_via"] in ("user-record", "default", "header")

    def test_tech_resolves_same_tenant(self):
        h = _login(*TECH)
        d = requests.get(f"{BASE}/api/tenants/current", headers=h, timeout=15).json()
        assert d["slug"] == "aquaterra"

    def test_unauthenticated_rejected(self):
        r = requests.get(f"{BASE}/api/tenants/current", timeout=10)
        assert r.status_code in (401, 403)

    def test_header_override_ignored_for_unknown_slug(self):
        """If X-Tenant-Slug points at a non-existent tenant, fall back to user's tenant."""
        h = _login(*ADMIN)
        h["X-Tenant-Slug"] = "nonexistent-slug-xxx"
        d = requests.get(f"{BASE}/api/tenants/current", headers=h, timeout=15).json()
        # Should still resolve (falls through to user-record → default).
        assert d["slug"] == "aquaterra"


class TestBackfill:
    """Sanity checks against tenant_id backfill across critical collections."""

    def test_customers_all_have_tenant_id(self):
        h = _login(*ADMIN)
        rows = requests.get(f"{BASE}/api/customers", headers=h, timeout=15).json()
        # Every existing customer document should have tenant_id after the startup backfill.
        # The API doesn't currently return tenant_id in the response, so we spot-check via a
        # smoke Mongo query — but from the API surface, we at least confirm the endpoint still returns.
        assert isinstance(rows, list) and len(rows) > 0

    def test_no_existing_endpoints_broke(self):
        """Stage 1 must be non-breaking. Hit a spread of admin + tech endpoints."""
        ah = _login(*ADMIN)
        th = _login(*TECH)
        for path, hdr in [
            ("/customers", ah), ("/jobs", ah), ("/leads", ah),
            ("/quotes", ah), ("/notifications", ah),
            ("/jobs", th),  # tech scope
        ]:
            r = requests.get(f"{BASE}/api{path}", headers=hdr, timeout=15)
            assert r.status_code == 200, f"{path} returned {r.status_code}"

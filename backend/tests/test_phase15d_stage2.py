"""Phase 15D Stage 2 — Multi-tenant UX + super_admin role."""
import os
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
SUPER = ("super@aquaterra.com", "password123")
ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestSuperAdminSeed:
    def test_super_admin_seeded(self):
        h = _login(*SUPER)
        me = requests.get(f"{BASE}/api/auth/me", headers=h, timeout=10).json()
        assert me["role"] == "super_admin"
        assert me["email"] == "super@aquaterra.com"


class TestTenantCRUD:
    def test_admin_cannot_list_tenants(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/tenants", headers=h, timeout=10)
        assert r.status_code == 403

    def test_tech_cannot_list_tenants(self):
        h = _login(*TECH)
        r = requests.get(f"{BASE}/api/tenants", headers=h, timeout=10)
        assert r.status_code == 403

    def test_super_can_crud(self):
        h = _login(*SUPER)
        slug = f"testphase15d-{uuid.uuid4().hex[:8]}"
        # Create
        r = requests.post(f"{BASE}/api/tenants", headers=h,
                          json={"name": "Test Stage2", "slug": slug,
                                "brand_primary": "#F97316", "plan_tier": "pro"},
                          timeout=15)
        assert r.status_code == 200
        tid = r.json()["id"]
        # List
        rows = requests.get(f"{BASE}/api/tenants", headers=h, timeout=10).json()
        assert any(t["id"] == tid for t in rows)
        # Patch
        r2 = requests.patch(f"{BASE}/api/tenants/{tid}", headers=h,
                            json={"name": "Test Stage2 (renamed)", "plan_tier": "enterprise"},
                            timeout=10).json()
        assert r2["name"] == "Test Stage2 (renamed)"
        assert r2["plan_tier"] == "enterprise"
        # Deactivate
        r3 = requests.patch(f"{BASE}/api/tenants/{tid}", headers=h,
                            json={"active": False}, timeout=10).json()
        assert r3["active"] is False

    def test_slug_uniqueness(self):
        h = _login(*SUPER)
        r = requests.post(f"{BASE}/api/tenants", headers=h,
                          json={"name": "Dup", "slug": "aquaterra"}, timeout=10)
        assert r.status_code == 400


class TestBrandEditor:
    def test_admin_can_patch_own_brand(self):
        h = _login(*ADMIN)
        r = requests.patch(f"{BASE}/api/tenants/mine/brand", headers=h,
                           json={"brand_primary": "#0EA5E9"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["brand_primary"] == "#0EA5E9"

    def test_tech_cannot_patch_brand(self):
        h = _login(*TECH)
        r = requests.patch(f"{BASE}/api/tenants/mine/brand", headers=h,
                           json={"brand_primary": "#000000"}, timeout=10)
        assert r.status_code == 403


class TestMemberships:
    def test_super_sees_all_tenants(self):
        h = _login(*SUPER)
        rows = requests.get(f"{BASE}/api/tenants/memberships/mine", headers=h, timeout=10).json()
        assert len(rows) >= 1
        assert all(r["role"] == "super_admin" for r in rows)

    def test_admin_sees_own_tenant_only(self):
        h = _login(*ADMIN)
        rows = requests.get(f"{BASE}/api/tenants/memberships/mine", headers=h, timeout=10).json()
        assert len(rows) == 1
        assert rows[0]["role"] == "admin"


def test_zzz_cleanup():
    """Deactivate + delete any test-created tenants + reset admin brand."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio
    env = dotenv_values("/app/backend/.env")
    client = AsyncIOMotorClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]

    async def _clean():
        await db.tenants.delete_many({"slug": {"$regex": "^testphase15d-", "$options": "i"}})
        # Note: `sunbelt` used to be created as a smoke test artifact in Stage 2; it is
        # now a permanent Stage 5 demo tenant. Do NOT delete it here.
    asyncio.run(_clean())
    client.close()
    # Restore aquaterra brand primary
    h = _login(*ADMIN)
    requests.patch(f"{BASE}/api/tenants/mine/brand", headers=h,
                   json={"brand_primary": "#0284C7", "brand_secondary": "#16A34A"}, timeout=10)

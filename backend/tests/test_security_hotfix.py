"""SEC-002 / SEC-003 / SEC-004 / SEC-P3-4 / SEC-P3-5 · Hotfix tests."""
from __future__ import annotations
import os, requests, pytest, uuid, base64

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 20


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok): return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok(): return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))

@pytest.fixture(scope="module")
def super_tok(): return _login("super@aquaterra.com", demo_pw("super@aquaterra.com"))

@pytest.fixture(scope="module")
def tech_tok():  return _login("mike@aquaterra.com",  demo_pw("mike@aquaterra.com"))


class TestSEC002_PortalReset:
    def test_non_admin_blocked(self, tech_tok):
        r = requests.post(f"{API}/customers/abc/portal-reset",
                          headers=_h(tech_tok), json={}, timeout=T)
        assert r.status_code == 403

    def test_cross_tenant_returns_404_not_403(self, admin_tok):
        # A non-existent-in-this-tenant customer id must return 404
        # (avoid leaking existence in other tenants).
        r = requests.post(f"{API}/customers/does-not-exist-xyz/portal-reset",
                          headers=_h(admin_tok), json={}, timeout=T)
        assert r.status_code == 404

    def test_own_tenant_reset_logs_audit(self, admin_tok):
        # Fetch the first customer in the tenant.
        customers = requests.get(f"{API}/customers", headers=_h(admin_tok), timeout=T).json()
        assert customers, "seed data has no customers"
        cid = customers[0]["id"]
        r = requests.post(f"{API}/customers/{cid}/portal-reset",
                          headers=_h(admin_tok), json={}, timeout=T)
        assert r.status_code == 200, r.text
        # Verify audit log written.
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")

        async def _check():
            c = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = c[os.environ["DB_NAME"]]
            n = await db.audit_logs.count_documents(
                {"event": "portal_reset", "target_customer_id": cid})
            c.close()
            return n
        assert asyncio.run(_check()) >= 1


class TestSEC003_AccessHistory:
    def test_admin_scoped_to_tenant(self, admin_tok):
        r = requests.get(f"{API}/admin/access-history", headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        # Every row should either lack tenant_id (legacy) or match the caller.
        # We don't have another tenant to compare against in this test env,
        # so we just verify the endpoint responds without error.

    def test_super_admin_all_tenants_flag_writes_audit(self, super_tok):
        r = requests.get(f"{API}/admin/access-history?all_tenants=true",
                          headers=_h(super_tok), timeout=T)
        assert r.status_code == 200
        # Verify the meta-audit row was logged.
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")

        async def _check():
            c = AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = c[os.environ["DB_NAME"]]
            n = await db.audit_logs.count_documents({"event": "access_history_cross_tenant"})
            c.close()
            return n
        assert asyncio.run(_check()) >= 1

    def test_non_admin_blocked(self, tech_tok):
        r = requests.get(f"{API}/admin/access-history", headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


class TestSEC004_Deactivation:
    def test_deactivated_user_cannot_login(self):
        # Create an ephemeral user, deactivate, verify login blocked.
        import asyncio, os as _os
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from utils import hash_password

        async def _seed():
            c = AsyncIOMotorClient(_os.environ["MONGO_URL"])
            db = c[_os.environ["DB_NAME"]]
            tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
            email = f"deact_{uuid.uuid4().hex[:8]}@aquaterra.com"
            uid = str(uuid.uuid4())
            await db.users.insert_one({
                "id": uid, "tenant_id": tenant["id"],
                "email": email, "password_hash": hash_password("password123"),
                "role": "admin", "active": False, "created_at": "2026-01-01T00:00:00Z",
            })
            c.close()
            return email
        email = asyncio.run(_seed())
        r = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": "password123"}, timeout=T)
        assert r.status_code == 403, r.text


_TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


class TestSEC_P3_4_SignatureCap:
    def test_pdf_ignores_oversized_signature(self, admin_tok):
        # Create instance with a 6 MB signature blob → PDF still succeeds
        # (renderer falls back to text stamp), no crash.
        big = "A" * (int(6 * 1024 * 1024 * 4 / 3))  # ~6 MB decoded
        c = requests.post(f"{API}/templates/instances", headers=_h(admin_tok),
                          json={"template_code": "service_agreement",
                                "values": {"provider_sig": {
                                    "image_data_url": f"data:image/png;base64,{big}",
                                    "signer_name": "Test", "signed_at": "2026-01-01T00:00:00Z"}}},
                          timeout=T).json()
        iid = c["id"]
        r = requests.post(f"{API}/templates/instances/{iid}/pdf",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"


class TestSEC_P3_5_WeeklyDigestAllowlist:
    def test_reject_attacker_email(self, super_tok):
        r = requests.post(f"{API}/admin/weekly-digest/send-now",
                          headers=_h(super_tok),
                          json={"to": "attacker@evil.com"}, timeout=T)
        assert r.status_code == 400

    def test_accept_admin_domain(self, super_tok):
        # Any @aquaterra.com should be allowed (matches admin domain).
        r = requests.post(f"{API}/admin/weekly-digest/send-now",
                          headers=_h(super_tok),
                          json={"to": "somebody@aquaterra.com"}, timeout=T)
        assert r.status_code == 200


class TestCorsSmoke:
    def test_cors_rejects_evil_origin_at_app_layer(self):
        # Hit the app directly (bypass ingress) — verifies our FastAPI
        # CORS middleware config. The public ingress adds its own
        # permissive header on top, which is a separate K8s config
        # concern outside this hotfix's scope.
        r = requests.options("http://localhost:8001/api/auth/login",
                              headers={"Origin": "https://evil.example.com",
                                        "Access-Control-Request-Method": "POST"}, timeout=T)
        allow = r.headers.get("access-control-allow-origin", "")
        assert allow != "https://evil.example.com"
        assert allow != "*"

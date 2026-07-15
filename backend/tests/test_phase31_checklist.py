"""Phase 31 · Step 1 — backend spine + resolver tests.

Covers the four contracts the (Step 2) UI will depend on:

1. `get_checklist_type(job)` resolver — pool | landscaping | generic.
   Python mirror of the shared JS/TS helper shipped on web + mobile.
2. `POST /api/workstream/events` RBAC —
     - customer  → 403 (no write access)
     - technician → 200 (may write)
3. Tenant scoping — an event created under tenant A must NOT surface
   in tenant B's listing.
4. Event shape / required fields — missing `type` returns 422 and a
   valid event echoes back with `id`, `tenant_id`, `actor_user_id`,
   `created_at`, `payload`.
"""
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

from routers.workstream import get_checklist_type

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN_A = {"email": "admin@aquaterra.com", "password": "password123"}
ADMIN_B = {"email": "admin@sunbelt.com",   "password": "password123"}
TECH    = {"email": "mike@aquaterra.com",  "password": "password123"}
CUST    = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_a_tok():
    return _login(ADMIN_A)


@pytest.fixture(scope="module")
def admin_b_tok():
    return _login(ADMIN_B)


@pytest.fixture(scope="module")
def tech_tok():
    return _login(TECH)


@pytest.fixture(scope="module")
def cust_tok():
    return _login(CUST)


# ─── 1. Resolver ──────────────────────────────────────────────────────────
class TestGetChecklistType:
    def test_pool_keywords(self):
        assert get_checklist_type({"service_type": "Weekly Pool Service"}) == "pool"
        assert get_checklist_type({"service_type": "Chemical Balancing"}) == "pool"
        assert get_checklist_type({"job_type": "pool_open"}) == "pool"
        assert get_checklist_type({"title": "Monthly POOL cleaning"}) == "pool"

    def test_landscaping_keywords(self):
        for st in ("Weekly Landscaping", "Lawn Mow", "Garden Trim", "Leaf Blow"):
            assert get_checklist_type({"service_type": st}) == "landscaping", st

    def test_generic_fallback(self):
        assert get_checklist_type({"service_type": "General Handyman"}) == "generic"
        assert get_checklist_type({"title": "Warranty inspection"}) == "generic"
        assert get_checklist_type({}) == "generic"
        assert get_checklist_type(None) == "generic"

    def test_pool_wins_over_landscape(self):
        # Ambiguous job that mentions both — pool keyword wins by scan order,
        # which mirrors the backend template detector.
        assert get_checklist_type(
            {"service_type": "Pool + lawn combo"}
        ) == "pool"


# ─── 2. RBAC on POST /api/workstream/events ───────────────────────────────
class TestWorkstreamRbac:
    def test_customer_forbidden(self, cust_tok):
        r = requests.post(
            f"{API}/workstream/events",
            headers=_auth(cust_tok),
            json={"type": "checklist.opened"},
            timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_technician_allowed(self, tech_tok):
        r = requests.post(
            f"{API}/workstream/events",
            headers=_auth(tech_tok),
            json={"type": "checklist.opened",
                  "payload": {"note": "TEST_phase31_tech_write"}},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("type") == "checklist.opened"
        assert body.get("actor_role") == "technician"


# ─── 3. Tenant scoping ────────────────────────────────────────────────────
def test_events_are_tenant_scoped(admin_a_tok, admin_b_tok):
    marker = "checklist.tenant_scope_probe"
    r = requests.post(
        f"{API}/workstream/events",
        headers=_auth(admin_a_tok),
        json={"type": marker, "payload": {"note": "TEST_phase31_scope"}},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    created_id = r.json()["id"]

    a_list = requests.get(
        f"{API}/workstream/events?type={marker}",
        headers=_auth(admin_a_tok), timeout=15,
    )
    assert a_list.status_code == 200, a_list.text
    assert any(e.get("id") == created_id for e in a_list.json()), \
        "aquaterra admin should see its own event"

    b_list = requests.get(
        f"{API}/workstream/events?type={marker}",
        headers=_auth(admin_b_tok), timeout=15,
    )
    assert b_list.status_code == 200, b_list.text
    assert all(e.get("id") != created_id for e in b_list.json()), \
        "sunbelt admin must NOT see aquaterra's event"


# ─── 4. Event shape / validation ──────────────────────────────────────────
class TestEventShape:
    def test_missing_type_is_422(self, tech_tok):
        r = requests.post(
            f"{API}/workstream/events",
            headers=_auth(tech_tok),
            json={"payload": {"x": 1}},
            timeout=15,
        )
        assert r.status_code == 422, r.text

    def test_valid_event_returns_required_fields(self, admin_a_tok):
        r = requests.post(
            f"{API}/workstream/events",
            headers=_auth(admin_a_tok),
            json={
                "type": "checklist.shape_probe",
                "payload": {"note": "TEST_phase31_shape", "step": 3},
                "related_ref": {"type": "job", "id": "job-fake-id"},
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        for f in ("id", "tenant_id", "type", "actor_user_id",
                  "actor_role", "payload", "created_at"):
            assert f in b, f"missing field: {f}"
        assert b["type"] == "checklist.shape_probe"
        assert b["payload"]["step"] == 3
        assert b["related_ref"]["id"] == "job-fake-id"

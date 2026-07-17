"""Phase 56.13a — Training subsystem end-to-end tests.

Exercises the 8 endpoints, tenant isolation, RBAC across all 5 role
permutations (super_admin, admin, technician-pool, technician-landscaping,
customer), system-module immutability, and quiz scoring math.

Every test-created module uses a `TEST_` code prefix; the session-scoped
teardown in `conftest.py` cleans them up.
"""
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set in /app/frontend/.env"

# Five role permutations for the RBAC matrix.
SUPER_ADMIN = ("super@aquaterra.com", "password123")
ADMIN = ("admin@aquaterra.com", "password123")
TECH_POOL = ("test-pool-tech@aquaterra.com", "password123")
TECH_LAND = ("landscaper@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")


def _ensure_pool_tech():
    """Idempotently create a pool-department technician for RBAC tests.

    The base seed pool tech (`mike@aquaterra.com`) has drifted to
    `department: landscaping` in this environment. Rather than mutate a
    shared account, we seed a dedicated pool tech under a `test-` email
    that the session teardown cleans up automatically."""
    from pymongo import MongoClient
    _env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    mongo_url = _env.get("MONGO_URL") or os.environ.get("MONGO_URL")
    db_name = _env.get("DB_NAME") or os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        return
    import bcrypt
    import uuid
    client = MongoClient(mongo_url)
    try:
        db = client[db_name]
        tenant = db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
        if not tenant:
            return
        existing = db.users.find_one({"email": TECH_POOL[0]}, {"_id": 0})
        pw_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode("utf-8")
        if not existing:
            db.users.insert_one({
                "id": str(uuid.uuid4()),
                "name": "TEST_ Pool Tech",
                "email": TECH_POOL[0],
                "password_hash": pw_hash,
                "role": "technician",
                "department": "pool",
                "tenant_id": tenant["id"],
            })
        elif existing.get("department") != "pool":
            db.users.update_one({"email": TECH_POOL[0]},
                                {"$set": {"department": "pool", "password_hash": pw_hash}})
    finally:
        client.close()


_ensure_pool_tech()


def _login(email: str, password: str) -> dict:
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_super():
    return _login(*SUPER_ADMIN)


@pytest.fixture(scope="module")
def h_admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def h_tech_pool():
    return _login(*TECH_POOL)


@pytest.fixture(scope="module")
def h_tech_land():
    return _login(*TECH_LAND)


@pytest.fixture(scope="module")
def h_customer():
    return _login(*CUSTOMER)


def _mk_module(code: str, department: str = "pool", with_quiz: bool = True) -> dict:
    # Codes are validated as lowercase; caller passes lowercase `test_` prefix.
    payload = {
        "code": code,
        "title": f"TEST_ {code}",
        "department": department,
        "description": "TEST_ module for pytest",
        "badge_label": "TEST_ Completed",
        "disclaimer": "TEST_ disclaimer",
        "lessons": [
            {"id": "l1", "title": "TEST_ Lesson 1", "body_md": "# TEST", "order": 1, "word_count": 5},
            {"id": "l2", "title": "TEST_ Lesson 2", "body_md": "# TEST 2", "order": 2, "word_count": 5},
        ],
    }
    if with_quiz:
        payload["quiz"] = {
            "passing_score": 0.75,
            "questions": [
                {"id": "q1", "prompt": "1+1?",
                 "choices": [{"id": "a", "text": "2"}, {"id": "b", "text": "3"}],
                 "correct_choice_ids": ["a"], "explanation": "math"},
                {"id": "q2", "prompt": "2+2?",
                 "choices": [{"id": "a", "text": "5"}, {"id": "b", "text": "4"}],
                 "correct_choice_ids": ["b"], "explanation": "math"},
                {"id": "q3", "prompt": "3+3?",
                 "choices": [{"id": "a", "text": "6"}, {"id": "b", "text": "7"}],
                 "correct_choice_ids": ["a"], "explanation": "math"},
                {"id": "q4", "prompt": "5-1?",
                 "choices": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}],
                 "correct_choice_ids": ["b"], "explanation": "math"},
            ],
        }
    return payload


# ─── RBAC matrix on GET /api/training/modules (all 5 roles) ────────────────
class TestListModulesRBAC:

    def test_customer_forbidden(self, h_customer):
        r = requests.get(f"{BASE}/api/training/modules", headers=h_customer, timeout=15)
        assert r.status_code == 403

    def test_super_admin_ok(self, h_super):
        r = requests.get(f"{BASE}/api/training/modules", headers=h_super, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_ok(self, h_admin):
        r = requests.get(f"{BASE}/api/training/modules", headers=h_admin, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_tech_pool_ok(self, h_tech_pool):
        r = requests.get(f"{BASE}/api/training/modules", headers=h_tech_pool, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_tech_land_ok(self, h_tech_land):
        r = requests.get(f"{BASE}/api/training/modules", headers=h_tech_land, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ─── Department filtering ───────────────────────────────────────────────────
class TestDepartmentFilter:

    def test_pool_tech_hidden_from_landscaping_module(self, h_admin, h_tech_pool, h_tech_land):
        code = "test_land_only"
        try:
            r = requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                              json=_mk_module(code, department="landscaping"), timeout=15)
            assert r.status_code == 200, r.text

            # Pool tech should NOT see it in the list.
            pool_list = requests.get(f"{BASE}/api/training/modules",
                                     headers=h_tech_pool, timeout=15).json()
            assert not any(m["code"] == code for m in pool_list)

            # Landscape tech SHOULD see it.
            land_list = requests.get(f"{BASE}/api/training/modules",
                                     headers=h_tech_land, timeout=15).json()
            assert any(m["code"] == code for m in land_list)

            # Pool tech GET on a specific landscape-only module → 403.
            r2 = requests.get(f"{BASE}/api/training/modules/{code}",
                              headers=h_tech_pool, timeout=15)
            assert r2.status_code == 403
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)

    def test_both_department_visible_to_all_techs(self, h_admin, h_tech_pool, h_tech_land):
        code = "test_both_dept"
        try:
            r = requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                              json=_mk_module(code, department="both"), timeout=15)
            assert r.status_code == 200

            for h in (h_tech_pool, h_tech_land):
                lst = requests.get(f"{BASE}/api/training/modules", headers=h, timeout=15).json()
                assert any(m["code"] == code for m in lst)
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)


# ─── Admin-only writes + RBAC ──────────────────────────────────────────────
class TestWriteRBAC:

    def test_tech_cannot_create_module(self, h_tech_pool):
        r = requests.post(f"{BASE}/api/training/modules", headers=h_tech_pool,
                          json=_mk_module("test_tech_reject"), timeout=15)
        assert r.status_code == 403

    def test_admin_can_create_and_delete(self, h_admin):
        code = "test_admin_crud"
        try:
            r = requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                              json=_mk_module(code), timeout=15)
            assert r.status_code == 200
            got = requests.get(f"{BASE}/api/training/modules/{code}",
                               headers=h_admin, timeout=15).json()
            assert got["code"] == code
            assert got["is_system"] is False
        finally:
            r = requests.delete(f"{BASE}/api/training/modules/{code}",
                                headers=h_admin, timeout=15)
            assert r.status_code == 200

    def test_admin_can_patch(self, h_admin):
        code = "test_admin_patch"
        try:
            requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                          json=_mk_module(code), timeout=15)
            r = requests.patch(f"{BASE}/api/training/modules/{code}",
                               headers=h_admin, json={"title": "TEST_ patched"}, timeout=15)
            assert r.status_code == 200
            assert r.json()["title"] == "TEST_ patched"
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)


# ─── Tenant isolation ──────────────────────────────────────────────────────
class TestTenantIsolation:

    def test_custom_module_not_visible_across_tenants(self):
        """Sunbelt admin (different tenant) must not see aquaterra's custom module."""
        try:
            SUN_ADMIN = _login("admin@sunbelt.com", "password123")
        except Exception:
            pytest.skip("sunbelt tenant admin not seeded in this environment")

        AQ_ADMIN = _login(*ADMIN)
        code = "test_tenant_isolation"
        try:
            requests.post(f"{BASE}/api/training/modules", headers=AQ_ADMIN,
                          json=_mk_module(code), timeout=15)
            sun_lst = requests.get(f"{BASE}/api/training/modules",
                                   headers=SUN_ADMIN, timeout=15).json()
            assert not any(m["code"] == code for m in sun_lst), \
                "custom module leaked across tenants"
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=AQ_ADMIN, timeout=15)


# ─── Progress tracking ─────────────────────────────────────────────────────
class TestProgress:

    def test_mark_lesson_complete_progressively(self, h_admin, h_tech_pool):
        code = "test_progress"
        try:
            requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                          json=_mk_module(code, department="pool"), timeout=15)

            r = requests.post(f"{BASE}/api/training/modules/{code}/progress",
                              headers=h_tech_pool, json={"lesson_id": "l1"}, timeout=15)
            assert r.status_code == 200
            assert r.json()["percent"] == 0.5

            r = requests.post(f"{BASE}/api/training/modules/{code}/progress",
                              headers=h_tech_pool, json={"lesson_id": "l2"}, timeout=15)
            assert r.json()["percent"] == 1.0

            # Idempotent — repeating l1 does not double-count.
            r = requests.post(f"{BASE}/api/training/modules/{code}/progress",
                              headers=h_tech_pool, json={"lesson_id": "l1"}, timeout=15)
            assert r.json()["percent"] == 1.0

            # Unknown lesson_id → 400.
            r = requests.post(f"{BASE}/api/training/modules/{code}/progress",
                              headers=h_tech_pool, json={"lesson_id": "l99"}, timeout=15)
            assert r.status_code == 400
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)


# ─── Quiz scoring ──────────────────────────────────────────────────────────
class TestQuizScoring:

    def test_perfect_score_passes(self, h_admin, h_tech_pool):
        code = "test_quiz_pass"
        try:
            requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                          json=_mk_module(code, department="pool"), timeout=15)
            r = requests.post(f"{BASE}/api/training/modules/{code}/quiz",
                              headers=h_tech_pool,
                              json={"answers": {"q1": "a", "q2": "b", "q3": "a", "q4": "b"}},
                              timeout=15)
            assert r.status_code == 200
            d = r.json()
            assert d["score"] == 1.0 and d["passed"] is True
            assert d["correct"] == 4 and d["total"] == 4
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)

    def test_partial_score_fails_when_below_threshold(self, h_admin, h_tech_pool):
        code = "test_quiz_fail"
        try:
            requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                          json=_mk_module(code, department="pool"), timeout=15)
            # Get 2 of 4 correct → 0.5 < 0.75 threshold.
            r = requests.post(f"{BASE}/api/training/modules/{code}/quiz",
                              headers=h_tech_pool,
                              json={"answers": {"q1": "a", "q2": "b", "q3": "b", "q4": "a"}},
                              timeout=15)
            d = r.json()
            assert d["score"] == 0.5 and d["passed"] is False
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)

    def test_attempts_list_scopes_to_own_for_tech(self, h_admin, h_tech_pool):
        code = "test_quiz_attempts"
        try:
            requests.post(f"{BASE}/api/training/modules", headers=h_admin,
                          json=_mk_module(code, department="pool"), timeout=15)
            requests.post(f"{BASE}/api/training/modules/{code}/quiz",
                          headers=h_tech_pool,
                          json={"answers": {"q1": "a", "q2": "b", "q3": "a", "q4": "b"}},
                          timeout=15)
            r = requests.get(f"{BASE}/api/training/modules/{code}/attempts",
                             headers=h_tech_pool, timeout=15)
            assert r.status_code == 200
            attempts = r.json()
            assert len(attempts) >= 1
            assert all(a["module_code"] == code for a in attempts)

            # Admin can see all attempts (or filter by user_id).
            r = requests.get(f"{BASE}/api/training/modules/{code}/attempts",
                             headers=h_admin, timeout=15)
            assert r.status_code == 200
        finally:
            requests.delete(f"{BASE}/api/training/modules/{code}", headers=h_admin, timeout=15)


# ─── System module immutability ────────────────────────────────────────────
class TestSystemModuleImmutability:
    """These tests are guardrails against a future CPO seed accidentally being
    mutable through the API. They exercise the router logic directly by
    inserting a temp system module into MongoDB, then trying to PATCH/DELETE
    it via the API. Skip if we cannot reach MongoDB from the test env."""

    def test_system_module_cannot_be_deleted_or_patched(self, h_admin):
        from pymongo import MongoClient
        _env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
        mongo_url = _env.get("MONGO_URL") or os.environ.get("MONGO_URL")
        db_name = _env.get("DB_NAME") or os.environ.get("DB_NAME")
        if not (mongo_url and db_name):
            pytest.skip("Mongo not reachable from test env")
        client = MongoClient(mongo_url)
        try:
            db = client[db_name]
            code = "test_system_immutable"
            db.training_modules.delete_many({"code": code})
            db.training_modules.insert_one({
                "id": "sys-test", "code": code, "title": "TEST_ system",
                "is_system": True, "department": "pool",
                "lessons": [], "quiz": {"questions": []},
            })
            try:
                r = requests.patch(f"{BASE}/api/training/modules/{code}",
                                   headers=h_admin, json={"title": "hijack"}, timeout=15)
                assert r.status_code == 409
                r = requests.delete(f"{BASE}/api/training/modules/{code}",
                                    headers=h_admin, timeout=15)
                assert r.status_code == 409
            finally:
                db.training_modules.delete_many({"code": code})
        finally:
            client.close()

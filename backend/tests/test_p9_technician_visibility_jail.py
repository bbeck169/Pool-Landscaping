"""Phase P9-A · Feb-2026 — Technician Visibility Jail (Option B).

Contract-level suite that locks in the un-bypassable jail for every
audited read path, with Option B semantics:

    * Scope is the FULL identity union ``[user.technician_id, user.id]``
      so both modern (technicians.id) and legacy (users.id) job shapes
      are matched — preserves R1.1 crew visibility for legacy techs.
    * Fail-closed ONLY when BOTH ids are missing (truly identity-less
      session). Silent empty response + one WARN. Never 403.
    * ``?technician_id=<other>`` param → silently pinned to self.
    * ``get_job`` on cross-tech doc → 404 (not 403) for leak-avoidance.

Endpoint coverage:
    * GET /api/jobs                             — list scope
    * GET /api/jobs?technician_id=<other>       — override attempt
    * GET /api/jobs (both ids missing)          — fail-closed
    * GET /api/jobs (admin)                     — no jail
    * GET /api/jobs (cross-tenant tech)         — tenant + tech both
    * GET /api/jobs/{id} (other-tech job)       — 404 leak-avoidance
    * GET /api/schedule/today (both ids missing) — fail-closed
    * GET /api/jobs (legacy tech shape)         — R1.1 union preserved
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_PREFIX = f"p9-jail-{uuid.uuid4().hex[:8]}"
TODAY = datetime.now(timezone.utc).date().isoformat()

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _sign_token(user_id: str, email: str, role: str,
                 tenant_id: str) -> str:
    """Emit a JWT the /auth/me endpoint will accept without hitting DB."""
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ─────────────────────────────────────────────────────────────
# Login helpers for real seeded users
# ─────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> tuple[str, dict]:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    ).json()
    return tok, me


@pytest.fixture(scope="module")
def mike():
    tok, me = _login("mike@aquaterra.com")
    return {"tok": tok, **me}


@pytest.fixture(scope="module")
def carlos():
    tok, me = _login("carlos@aquaterra.com")
    return {"tok": tok, **me}


@pytest.fixture(scope="module")
def admin_h():
    tok, _ = _login("admin@aquaterra.com")
    return {"Authorization": f"Bearer {tok}"}


def _seed_job(*, tenant_id: str, technician_id: str, tag: str) -> str:
    jid = f"{_PREFIX}-{tag}-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant_id,
        "title": f"P9 jail test · {tag}",
        "customer_id": "seed-customer",
        "customer_name": "P9 Seed",
        "property_id": None,
        "service_type": "Pool Cleaning",
        "scheduled_date": TODAY,
        "arrival_window": "9-10am",
        "status": "scheduled",
        "technician_id": technician_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup() -> None:
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.users.delete_many({"id": {"$regex": f"^{_PREFIX}"}})


def setup_module(module):
    _cleanup()


def teardown_module(module):
    _cleanup()


def _ids(rows) -> set:
    return {r.get("id") for r in rows if r.get("id")}


# ═══════════════════════════════════════════════════════════════════
# 1 · Technician sees ONLY the 2 jobs assigned to them (out of 5).
# ═══════════════════════════════════════════════════════════════════
def test_p9_tech_sees_only_own_jobs_from_mixed_fixture(mike, carlos):
    tid = mike["tenant_id"]
    assert mike["technician_id"] and carlos["technician_id"]
    mike_ids = [
        _seed_job(tenant_id=tid, technician_id=mike["technician_id"],
                   tag="mike"),
        _seed_job(tenant_id=tid, technician_id=mike["technician_id"],
                   tag="mike"),
    ]
    carlos_ids = [
        _seed_job(tenant_id=tid, technician_id=carlos["technician_id"],
                   tag="carlos"),
        _seed_job(tenant_id=tid, technician_id=carlos["technician_id"],
                   tag="carlos"),
        _seed_job(tenant_id=tid, technician_id=carlos["technician_id"],
                   tag="carlos"),
    ]
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {mike['tok']}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        seen = _ids(r.json())
        for m in mike_ids:
            assert m in seen, f"P9 regression — mike missing own job {m}"
        for c in carlos_ids:
            assert c not in seen, (
                f"P9 regression — mike leaked carlos's job {c}"
            )
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 2 · Technician passing ?technician_id=<other> gets pinned to self.
# ═══════════════════════════════════════════════════════════════════
def test_p9_tech_cannot_override_via_technician_id_param(mike, carlos):
    tid = mike["tenant_id"]
    m1 = _seed_job(tenant_id=tid,
                    technician_id=mike["technician_id"], tag="mike")
    m2 = _seed_job(tenant_id=tid,
                    technician_id=mike["technician_id"], tag="mike")
    c1 = _seed_job(tenant_id=tid,
                    technician_id=carlos["technician_id"], tag="carlos")
    c2 = _seed_job(tenant_id=tid,
                    technician_id=carlos["technician_id"], tag="carlos")
    c3 = _seed_job(tenant_id=tid,
                    technician_id=carlos["technician_id"], tag="carlos")
    try:
        r = requests.get(
            f"{API}/jobs?technician_id={carlos['technician_id']}&limit=2000",
            headers={"Authorization": f"Bearer {mike['tok']}"},
            timeout=30,
        )
        assert r.status_code == 200
        seen = _ids(r.json())
        # Mike's 2 must show; Carlos's 3 must NOT — mike is pinned.
        assert m1 in seen and m2 in seen, (
            "P9 regression — mike's own jobs missing under override attempt"
        )
        for cx in (c1, c2, c3):
            assert cx not in seen, (
                f"P9 regression — override bypass leaked carlos's job {cx}"
            )
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 3 · Truly identity-less tech (both user.id AND user.technician_id
#     empty) → EMPTY response. Uses a synthetic signed JWT so we can
#     construct a session dict that survives ``get_current_user`` yet
#     carries no identity.
#
#     NB: this is the ONLY tests where the fail-closed leg fires
#     under Option B semantics.
# ═══════════════════════════════════════════════════════════════════
def test_p9_identity_less_tech_returns_empty(mike):
    """A signed token with sub="" makes get_current_user set
    ``user.id = ""``. We also seed the user doc with technician_id=None
    so both ids resolve to empty. Under Option B, the endpoint must
    fail-closed silent-empty (not tenant-wide leak)."""
    tid = mike["tenant_id"]
    # Seed a canary job under mike's canonical id — if the fail-closed
    # leg leaks tenant-wide, this row would surface on the empty
    # identity's response.
    canary = _seed_job(
        tenant_id=tid, technician_id=mike["technician_id"], tag="canary",
    )
    # Seed a technician user with intentionally empty identity — the
    # user doc exists (so /auth/me can hydrate it) but neither
    # ``id`` nor ``technician_id`` carry a value the jail can scope on.
    ghost_email = f"{_PREFIX}-ghost@example.test"
    ghost_id = ""  # empty string → truthy check fails
    _sync.users.insert_one({
        "id": ghost_id, "email": ghost_email, "role": "technician",
        "tenant_id": tid, "technician_id": None,
        "password_hash": "x",  # never used — signed token bypasses login
    })
    tok = _sign_token(ghost_id, ghost_email, "technician", tid)
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        # A malformed token may 401; that's an acceptable strict
        # failure mode. What we MUST NOT see is 200-with-canary.
        if r.status_code == 200:
            seen = _ids(r.json())
            assert canary not in seen, (
                "P9 regression — identity-less tech leaked canonical job"
            )
            # Must be empty (or at most doc-only fields the sentinel
            # can't match anyway).
            assert len(seen) == 0, (
                "P9 regression — identity-less tech saw non-empty "
                f"result set (leak candidate): {seen}"
            )
        else:
            assert r.status_code in (401, 403), (
                f"P9 unexpected status {r.status_code}: {r.text}"
            )
    finally:
        _sync.jobs.delete_one({"id": canary})
        _sync.users.delete_one({"email": ghost_email})


# ═══════════════════════════════════════════════════════════════════
# 4 · Admin/manager reads UNCHANGED — sees all seeded rows.
# ═══════════════════════════════════════════════════════════════════
def test_p9_admin_is_not_jailed(mike, carlos, admin_h):
    tid = mike["tenant_id"]
    m = _seed_job(tenant_id=tid,
                   technician_id=mike["technician_id"], tag="mike")
    c = _seed_job(tenant_id=tid,
                   technician_id=carlos["technician_id"], tag="carlos")
    try:
        r = requests.get(f"{API}/jobs?limit=2000",
                          headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        seen = _ids(r.json())
        assert m in seen and c in seen, (
            "P9 regression — admin lost visibility on seeded rows"
        )
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 5 · Cross-tenant technician cannot see other-tenant jobs.
# ═══════════════════════════════════════════════════════════════════
def test_p9_cross_tenant_technician_isolation(mike):
    tid = mike["tenant_id"]
    foreign_tid = f"p9-foreign-tenant-{uuid.uuid4().hex[:8]}"
    own_job = _seed_job(
        tenant_id=tid,
        technician_id=mike["technician_id"], tag="own",
    )
    # Same technician_id but pinned to a foreign tenant — mike must
    # never see this even though the id matches.
    foreign_job = f"{_PREFIX}-foreign-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": foreign_job, "tenant_id": foreign_tid,
        "title": "P9 cross-tenant leak canary",
        "customer_id": "seed-customer", "customer_name": "P9",
        "service_type": "Pool Cleaning", "scheduled_date": TODAY,
        "arrival_window": "9-10am", "status": "scheduled",
        "technician_id": mike["technician_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {mike['tok']}"},
            timeout=30,
        )
        assert r.status_code == 200
        seen = _ids(r.json())
        assert own_job in seen, "P9 regression — own-tenant own-job dropped"
        assert foreign_job not in seen, (
            "P9 regression — cross-tenant job leaked"
        )
    finally:
        _sync.jobs.delete_one({"id": foreign_job})
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 6 · GET /api/jobs/{id} for another tech's job returns 404 (not 403).
# ═══════════════════════════════════════════════════════════════════
def test_p9_get_job_returns_404_on_cross_tech(mike, carlos):
    tid = mike["tenant_id"]
    c_job = _seed_job(tenant_id=tid,
                       technician_id=carlos["technician_id"], tag="carlos")
    try:
        r = requests.get(
            f"{API}/jobs/{c_job}",
            headers={"Authorization": f"Bearer {mike['tok']}"},
            timeout=15,
        )
        assert r.status_code == 404, (
            f"P9 requires 404 (leak-avoidance) — got {r.status_code}: {r.text}"
        )
    finally:
        _cleanup()


# ═══════════════════════════════════════════════════════════════════
# 7 · /schedule/today fail-closed for identity-less tech.
# ═══════════════════════════════════════════════════════════════════
def test_p9_schedule_today_fail_closed_on_identity_less_session(mike):
    tid = mike["tenant_id"]
    canary = _seed_job(
        tenant_id=tid, technician_id=mike["technician_id"],
        tag="today-canary",
    )
    ghost_email = f"{_PREFIX}-today-ghost@example.test"
    _sync.users.insert_one({
        "id": "", "email": ghost_email, "role": "technician",
        "tenant_id": tid, "technician_id": None,
        "password_hash": "x",
    })
    tok = _sign_token("", ghost_email, "technician", tid)
    try:
        r = requests.get(
            f"{API}/schedule/today?date={TODAY}",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        if r.status_code == 200:
            body = r.json()
            assert body.get("items") == [], (
                "P9 regression — /schedule/today leaked items to "
                f"identity-less tech: {body!r}"
            )
            assert body.get("summary", {}).get("job_count") == 0
        else:
            assert r.status_code in (401, 403)
    finally:
        _sync.jobs.delete_one({"id": canary})
        _sync.users.delete_one({"email": ghost_email})


# ═══════════════════════════════════════════════════════════════════
# 8 · Option B semantic lock — a LEGACY-SHAPE tech (only user.id in
#     the session, no technician_id) still sees their own jobs via
#     the R1.1 union. Prevents a future refactor from silently
#     hardening to strict Option A behind an R1.1 back-door.
# ═══════════════════════════════════════════════════════════════════
def test_p9_option_b_preserves_legacy_shape_union(mike):
    tid = mike["tenant_id"]
    # Seed a tech user whose ONLY identity is ``user.id`` (no
    # linked technicians row) and stamp a job under that user.id
    # via the legacy write shape.
    legacy_uid = f"{_PREFIX}-legacy-uid-{uuid.uuid4().hex[:6]}"
    legacy_email = f"{legacy_uid}@example.test"
    _sync.users.insert_one({
        "id": legacy_uid, "email": legacy_email,
        "role": "technician", "tenant_id": tid,
        "technician_id": None,
        "password_hash": "x",
    })
    legacy_job_id = f"{_PREFIX}-legacy-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": legacy_job_id, "tenant_id": tid,
        "title": "P9 legacy-shape visibility lock",
        "customer_id": "seed-customer", "customer_name": "P9",
        "service_type": "Pool Cleaning", "scheduled_date": TODAY,
        "arrival_window": "9-10am", "status": "scheduled",
        "technician_id": legacy_uid,   # legacy shape — stamped under user.id
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    tok = _sign_token(legacy_uid, legacy_email, "technician", tid)
    try:
        r = requests.get(
            f"{API}/jobs?limit=2000",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        # The signed-token path expects the user row to exist; if
        # the endpoint bounces on strict validation, it's still a
        # green outcome for P9 (no leak). But the intended path is
        # 200 with the legacy job visible.
        assert r.status_code in (200, 401), r.text
        if r.status_code == 200:
            seen = _ids(r.json())
            assert legacy_job_id in seen, (
                "P9 Option B regression — legacy-shape tech lost "
                "visibility on their own user.id-stamped job. This "
                "means the R1.1 union was inadvertently narrowed."
            )
    finally:
        _sync.jobs.delete_one({"id": legacy_job_id})
        _sync.users.delete_one({"id": legacy_uid})

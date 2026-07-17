"""Phase 56.13b-followup — new endpoint tests.

Covers:
  * GET /api/training/progress/admin?module_code= — admin OK, tech 403,
    shape validation (`has_started` mirrors `lessons_completed`).
  * GET /api/training/leaderboard — admin OK, tech 403, per-user
    aggregate keys present.
  * PATCH /api/training/modules/cpo-prep — 409 on system module
    (immutability guard).
  * Full tenant-custom module CRUD flow (create/patch/delete) with
    RBAC on every mutation path.

Uses the same `requests` + preview-URL pattern as the rest of the
backend tests (test_phase56_16_landscape.py etc.).
"""
import os
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL missing"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": password},
        timeout=45,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ─── /training/progress/admin ────────────────────────────────────────────
def test_progress_admin_rbac_and_shape():
    admin_tok = _login("admin@aquaterra.com")
    tech_tok = _login("mike@aquaterra.com")

    r = requests.get(
        f"{BASE}/api/training/progress/admin?module_code=cpo-prep",
        headers=_hdr(admin_tok), timeout=45,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    for row in body:
        assert "user_id" in row
        assert "module_code" in row
        assert "lessons_completed" in row
        assert isinstance(row["lessons_completed"], list)
        # has_started must exactly mirror the non-empty lesson list.
        assert row["has_started"] == (len(row["lessons_completed"]) > 0)

    r = requests.get(
        f"{BASE}/api/training/progress/admin",
        headers=_hdr(tech_tok), timeout=45,
    )
    assert r.status_code == 403


# ─── /training/leaderboard ───────────────────────────────────────────────
def test_leaderboard_rbac_and_shape():
    admin_tok = _login("admin@aquaterra.com")
    tech_tok = _login("mike@aquaterra.com")

    r = requests.get(
        f"{BASE}/api/training/leaderboard",
        headers=_hdr(admin_tok), timeout=45,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0, "expected at least the admin+techs"
    for row in rows:
        for k in (
            "user_id", "name", "department", "role",
            "modules_completed", "quizzes_passed", "quiz_attempts",
            "certificates_earned", "avg_score",
        ):
            assert k in row, f"missing '{k}' in row: {row}"
        # Aggregate fields are always integers or the intentional
        # sentinel (None for avg_score when no attempts).
        assert isinstance(row["modules_completed"], int)
        assert isinstance(row["quizzes_passed"], int)
        assert isinstance(row["quiz_attempts"], int)
        assert isinstance(row["certificates_earned"], int)

    r = requests.get(
        f"{BASE}/api/training/leaderboard",
        headers=_hdr(tech_tok), timeout=45,
    )
    assert r.status_code == 403


# ─── system module immutability ──────────────────────────────────────────
def test_system_module_patch_delete_refused():
    """PATCH/DELETE on cpo-prep must return 409 (system module guard)."""
    admin_tok = _login("admin@aquaterra.com")

    before = requests.get(
        f"{BASE}/api/training/modules/cpo-prep",
        headers=_hdr(admin_tok), timeout=45,
    )
    assert before.status_code == 200
    before_title = before.json()["title"]

    r = requests.patch(
        f"{BASE}/api/training/modules/cpo-prep",
        json={"title": "SHOULD-NOT-PERSIST"},
        headers=_hdr(admin_tok), timeout=45,
    )
    assert r.status_code == 409, r.text

    r = requests.delete(
        f"{BASE}/api/training/modules/cpo-prep",
        headers=_hdr(admin_tok), timeout=45,
    )
    assert r.status_code == 409, r.text

    after = requests.get(
        f"{BASE}/api/training/modules/cpo-prep",
        headers=_hdr(admin_tok), timeout=45,
    )
    assert after.status_code == 200
    assert after.json()["title"] == before_title


# ─── tenant-custom module CRUD ──────────────────────────────────────────
def test_tenant_custom_module_full_crud_with_rbac():
    admin_tok = _login("admin@aquaterra.com")
    tech_tok = _login("mike@aquaterra.com")

    code = f"phase56-13b-fu-{uuid.uuid4().hex[:8]}"

    # POST — tech forbidden
    r = requests.post(
        f"{BASE}/api/training/modules",
        json={"code": code, "title": "T", "department": "pool"},
        headers=_hdr(tech_tok), timeout=45,
    )
    assert r.status_code == 403

    # POST — admin OK
    r = requests.post(
        f"{BASE}/api/training/modules",
        json={
            "code": code,
            "title": "56.13b-fu CRUD",
            "department": "pool",
            "description": "Ephemeral CRUD test.",
            "lessons": [
                {"id": "l1", "title": "L1", "body_md": "# hi", "estimated_minutes": 3, "order": 0}
            ],
            "quiz": {"passing_score": 0.75, "questions": []},
        },
        headers=_hdr(admin_tok), timeout=45,
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["code"] == code
    assert doc["is_system"] is False
    assert doc["tenant_id"]

    try:
        # PATCH — tech forbidden
        r = requests.patch(
            f"{BASE}/api/training/modules/{code}",
            json={"title": "hacked"},
            headers=_hdr(tech_tok), timeout=45,
        )
        assert r.status_code == 403

        # PATCH — admin OK
        r = requests.patch(
            f"{BASE}/api/training/modules/{code}",
            json={"title": "56.13b-fu CRUD (edited)"},
            headers=_hdr(admin_tok), timeout=45,
        )
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "56.13b-fu CRUD (edited)"

        # DELETE — tech forbidden
        r = requests.delete(
            f"{BASE}/api/training/modules/{code}",
            headers=_hdr(tech_tok), timeout=45,
        )
        assert r.status_code == 403

    finally:
        # DELETE — admin OK (cleanup)
        r = requests.delete(
            f"{BASE}/api/training/modules/{code}",
            headers=_hdr(admin_tok), timeout=45,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("deleted") == code

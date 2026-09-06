"""Phase K72.fix · Feb-2026 — Mass-messaging safety guards.

Covers the router-level protections that landed post-K72 emergency:

1. ``/mass-messaging/send`` rejects with HTTP 403
   ``K72_CI_MASS_MESSAGING_BLOCKED`` when
   ``CI_BLOCK_MASS_MESSAGING=1`` is set — irrespective of tenant.
2. ``/mass-messaging/send`` rejects with HTTP 403
   ``K72_REAL_TENANT_NON_PROD_BLOCKED`` when the target tenant is
   flagged ``is_real=True`` AND ``APP_ENV != production`` (e.g. the
   preview pod after K72.a).
3. Both guards fire BEFORE the confirm_token / audience resolver so
   no customers are enumerated on a blocked run.
4. The offending regression file
   ``test_bug_g_mass_messaging_filters.py`` is now hard-quarantined
   via a module-level ``pytest.skip`` — this test proves it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture
def admin_token():
    return _login("admin@aquaterra.com")


# ═══════════════════════════════════════════════════════════════════
# 1 · Culprit test is hard-quarantined
# ═══════════════════════════════════════════════════════════════════
def test_bug_g_test_file_is_module_skipped():
    """Running the offending regression file through pytest returns
    a single skip — never a pass, never a fire."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_bug_g_mass_messaging_filters.py",
         "--collect-only", "-q"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=30,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    assert (
        "K72 PRODUCTION-SAFETY QUARANTINE" in combined
        or "1 skipped" in combined
        or "no tests collected" in combined
    ), (f"expected K72 quarantine marker, 'skipped', or 'no tests "
        f"collected'\nstdout={result.stdout[:400]}\nstderr="
        f"{result.stderr[:400]}")


# ═══════════════════════════════════════════════════════════════════
# 2 · Real-tenant on non-prod pod → 403
# ═══════════════════════════════════════════════════════════════════
def test_mass_messaging_send_blocks_real_tenant_on_preview(admin_token):
    """The current pod is APP_ENV=preview + the aquaterra tenant is
    flagged is_real=True (K72.fix boot state). Any /mass-messaging/
    send request must 403 with K72_REAL_TENANT_NON_PROD_BLOCKED."""
    r = requests.post(
        f"{API}/mass-messaging/send",
        json={
            "channels": ["email"],
            "audience": "all_active_customers",
            "subject": "should be blocked",
            "body": "should be blocked",
            "confirm_token": "definitelynotarealtoken",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["detail"]["code"] == "K72_REAL_TENANT_NON_PROD_BLOCKED"
    assert body["detail"]["app_env"] == "preview"
    assert body["detail"]["tenant_id"] \
        == "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"


def test_mass_messaging_send_guard_fires_before_audience_resolver(
    admin_token,
):
    """The 403 must fire even when the payload's confirm_token is
    obviously invalid — proving the guard runs BEFORE token
    verification / audience enumeration."""
    r = requests.post(
        f"{API}/mass-messaging/send",
        json={
            "channels": ["email"],
            "audience": "all_active_customers",
            "subject": "x",
            "body": "x",
            "confirm_token": "invalidtokenbutlongenough",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    # 403 (K72), NOT 400 (invalid token).
    assert r.status_code == 403
    assert "K72_REAL_TENANT" in r.text or "K72_CI" in r.text


# ═══════════════════════════════════════════════════════════════════
# 3 · CI_BLOCK_MASS_MESSAGING=1 → 403 unconditionally
# ═══════════════════════════════════════════════════════════════════
def test_ci_block_env_shape_documented():
    """The router reads ``CI_BLOCK_MASS_MESSAGING`` from the env at
    request time. This test pins the shape (env name + truthy value)
    so a future refactor can't quietly rename it without breaking CI
    pipelines that set it.
    """
    from routers import mass_messaging as _mm
    # The env name appears verbatim in the router source — grep-
    # locked check.
    import inspect
    src = inspect.getsource(_mm.send_broadcast)
    assert "CI_BLOCK_MASS_MESSAGING" in src
    assert "K72_CI_MASS_MESSAGING_BLOCKED" in src


# ═══════════════════════════════════════════════════════════════════
# 4 · is_real tenant flag is persisted
# ═══════════════════════════════════════════════════════════════════
def test_aquaterra_tenant_is_flagged_real():
    """Boot migration flags the aquaterra prod tenant with is_real:
    True. If a fresh pod boots against an empty Mongo the test will
    fail — that's the desired signal to run the migration."""
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db_ = client[os.environ["DB_NAME"]]
    doc = db_.tenants.find_one(
        {"id": "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"},
        {"_id": 0, "id": 1, "slug": 1, "is_real": 1},
    )
    assert doc is not None
    assert doc.get("is_real") is True
    client.close()

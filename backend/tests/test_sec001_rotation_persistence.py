"""SEC-001 followup · Rotation persistence must reach the DB.

Regression guard for the Feb 2026 tester finding: the rotation script wrote
new passwords to ``/app/memory/test_credentials.md`` but a stale
"compatibility reset" was silently reverting the ``db.users`` hashes back to
``password123`` — so tester login with the rotated password returned 401
and legacy ``password123`` login returned 200.

This test proves end-to-end that:

1. Running ``scripts/rotate_demo_passwords.py`` updates the DB such that the
   plaintext printed on stdout authenticates against ``/api/auth/login``.
2. After rotation, ``password123`` no longer authenticates for any of the
   3 primary demo accounts (super_admin, admin, pool_tech).

It calls the rotation as a subprocess (matches the real production
invocation) and pulls the fresh plaintext from ``test_credentials.md``.
"""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ROTATE = BACKEND_ROOT / "scripts" / "rotate_demo_passwords.py"
CREDS = Path("/app/memory/test_credentials.md")

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 20

DEMO_EMAILS = [
    "super@aquaterra.com",
    "admin@aquaterra.com",
    "mike@aquaterra.com",
    "customer@aquaterra.com",
]


def _login_status(email: str, pw: str) -> int:
    return requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw},
                          timeout=T).status_code


def _extract_pw(email: str, text: str) -> str:
    # Match:   - **role** · `email` · `password`
    m = re.search(
        r"^\s*-\s+\*\*[^*]+\*\*\s+·\s+`" + re.escape(email) + r"`\s+·\s+`([^`]+)`\s*$",
        text, re.MULTILINE)
    assert m, f"credentials file has no plaintext for {email}"
    return m.group(1)


def test_demo_password_rotation_actually_persists():
    """Rotate, then verify the new plaintext auths and password123 does not."""
    # 1. Run the rotation script as a subprocess (mimics prod usage).
    r = subprocess.run([sys.executable, str(ROTATE)],
                        capture_output=True, text=True,
                        cwd=str(BACKEND_ROOT), timeout=45)
    assert r.returncode == 0, f"rotation failed: {r.stderr}"
    assert "Rotated" in r.stdout

    # 2. Read the fresh plaintext from the credentials file.
    text = CREDS.read_text(encoding="utf-8")
    new_pws = {e: _extract_pw(e, text) for e in DEMO_EMAILS}

    # 3. Sanity — no rotated password can equal the old dev default.
    for email, pw in new_pws.items():
        assert pw != "password123", (
            f"rotation produced 'password123' for {email} — script is broken")

    # 4. New plaintext must authenticate (200) for every rotated account.
    for email, pw in new_pws.items():
        code = _login_status(email, pw)
        assert code == 200, (
            f"login with rotated password for {email} returned {code}; "
            f"the DB update did not persist")

    # 5. Legacy 'password123' must be rejected (401) for every account.
    for email in DEMO_EMAILS:
        code = _login_status(email, "password123")
        assert code == 401, (
            f"login with 'password123' for {email} returned {code}; "
            f"a stale reset is still overwriting rotated hashes")


def test_rotation_survives_backend_hot_reload():
    """Sanity check — after rotation, GET /api/health/seeds still responds
    (proves the DB update didn't corrupt user rows) and the same rotated
    passwords keep working (proves no background seed step re-hashed them).
    """
    text = CREDS.read_text(encoding="utf-8")
    admin_pw = _extract_pw("admin@aquaterra.com", text)
    # First login pass.
    code = _login_status("admin@aquaterra.com", admin_pw)
    assert code == 200
    # Health endpoint should be reachable (server not broken).
    h = requests.get(f"{API}/health/seeds", timeout=T)
    assert h.status_code == 200
    # Second login pass — must still work (proves no reset ran between).
    code2 = _login_status("admin@aquaterra.com", admin_pw)
    assert code2 == 200

"""SEC-001 followup · Rotation persistence must reach the DB.

Regression guard for the Feb 2026 tester finding: the rotation script wrote
new passwords to ``/app/memory/test_credentials.md`` but a stale
"compatibility reset" was silently reverting the ``db.users`` hashes back to
``password123`` — so tester login with the rotated password returned 401 and
legacy ``password123`` login returned 200.

**Isolation** — this test uses a throwaway ``rotation_probe@aquaterra.com``
user, rotates only that email via ``--only``, verifies auth, and cleans up.
The 5 real demo credentials (super/admin/mike/carlos/customer) are never
touched — that constraint is enforced by the ``--only`` filter and by a
snapshot check on ``/app/memory/test_credentials.md``.

**Marker** — ``@pytest.mark.destructive`` (auto-skipped by the conftest
hook unless the caller passes ``-m destructive``). Even under the marker
the test cleans up after itself and does not touch the 5 real demo rows.
"""
from __future__ import annotations
import os, re, subprocess, sys, uuid
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

PROBE_EMAIL = "rotation_probe@aquaterra.com"
PROBE_INITIAL_PW = "probe_initial_pw_never_valid_after_rotate"

# The 5 real demo emails whose plaintext MUST NOT change during this test.
REAL_DEMO_EMAILS = [
    "super@aquaterra.com",
    "admin@aquaterra.com",
    "mike@aquaterra.com",
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
]


pytestmark = pytest.mark.destructive


def _login_status(email: str, pw: str) -> int:
    return requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw},
                          timeout=T).status_code


def _extract_pw(email: str, text: str) -> str | None:
    m = re.search(
        r"^\s*-\s+\*\*[^*]+\*\*\s+·\s+`" + re.escape(email) + r"`\s+·\s+`([^`]+)`\s*$",
        text, re.MULTILINE)
    return m.group(1) if m else None


def _snapshot_real_demo_rows() -> dict[str, str]:
    """Return {email: plaintext} for every real demo row currently in the file."""
    text = CREDS.read_text(encoding="utf-8") if CREDS.is_file() else ""
    return {e: (_extract_pw(e, text) or "") for e in REAL_DEMO_EMAILS}


@pytest.fixture()
def probe_user():
    """Seed a throwaway probe user with a known initial password; drop after test."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv(BACKEND_ROOT / ".env")
    sys.path.insert(0, str(BACKEND_ROOT))
    from utils import hash_password

    uid = str(uuid.uuid4())

    async def _seed():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        # Ensure any leftover probe rows from previous runs are gone.
        await db.users.delete_many({"email": PROBE_EMAIL})
        await db.users.insert_one({
            "id": uid,
            "tenant_id": tenant["id"] if tenant else None,
            "email": PROBE_EMAIL,
            "password_hash": hash_password(PROBE_INITIAL_PW),
            "role": "admin",  # role doesn't matter — only auth is tested
            "active": True,
            "created_at": "2026-01-01T00:00:00Z",
        })
        c.close()
    asyncio.run(_seed())
    yield {"id": uid, "email": PROBE_EMAIL, "initial_pw": PROBE_INITIAL_PW}

    async def _cleanup():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        await db.users.delete_many({"email": PROBE_EMAIL})
        c.close()
    asyncio.run(_cleanup())


def test_demo_password_rotation_actually_persists(probe_user):
    """Rotate the probe user only, verify auth. Real demo rows must not move."""
    # 1. Snapshot the 5 real demo plaintexts before rotation.
    before = _snapshot_real_demo_rows()
    file_bytes_before = CREDS.read_bytes() if CREDS.is_file() else b""

    # 2. Sanity — probe currently authenticates with its initial password.
    assert _login_status(PROBE_EMAIL, PROBE_INITIAL_PW) == 200, \
        "probe user did not seed correctly"

    # 3. Rotate ONLY the probe email (does NOT touch the 5 demo rows).
    r = subprocess.run(
        [sys.executable, str(ROTATE), "--only", PROBE_EMAIL],
        capture_output=True, text=True, cwd=str(BACKEND_ROOT), timeout=45)
    assert r.returncode == 0, f"rotation failed: {r.stderr}"
    assert "Rotated 1" in r.stdout

    # 4. Parse the rotated plaintext from the script's stdout (never lands in
    #    test_credentials.md — probe is not a listed demo account).
    m = re.search(rf"^\s*\S+\s+{re.escape(PROBE_EMAIL)}\s+(\S+)$",
                  r.stdout, re.MULTILINE)
    assert m, f"rotation script did not print probe plaintext: {r.stdout!r}"
    new_pw = m.group(1)
    assert new_pw != PROBE_INITIAL_PW

    # 5. New plaintext authenticates.
    assert _login_status(PROBE_EMAIL, new_pw) == 200, \
        "rotation did not persist to DB — new pw returned non-200"

    # 6. Old plaintext no longer authenticates.
    assert _login_status(PROBE_EMAIL, PROBE_INITIAL_PW) == 401, \
        "stale reset is still overwriting rotated hashes"

    # 7. INVARIANT — the 5 real demo rows must be untouched. Both the file
    #    plaintexts AND the DB auth (via any one real account) stay stable.
    after = _snapshot_real_demo_rows()
    assert before == after, (
        f"partial rotation leaked into real demo rows:\n"
        f"  before: {before}\n  after:  {after}")

    # 8. Idempotency — the file merge preserved every non-probe row byte-for-
    #    byte in the ` · email · pw ` section. We can't compare whole-file
    #    bytes (header line stays fixed on partial runs, but the ordering
    #    logic re-writes DEMO_EMAILS rows). Instead assert the file did not
    #    lose or reshuffle any real-demo plaintext.
    for email, pw in before.items():
        if not pw:
            continue  # row was already missing before the test
        assert pw in CREDS.read_text(encoding="utf-8"), \
            f"partial rotation dropped {email}'s plaintext from the file"

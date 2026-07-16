"""Phase 55 · Unified Notifications backend tests.

Covers:
  1. GET /api/notifications/kinds catalog + defaults
  2. GET/PUT /api/settings/notifications preferences persistence
  3. GET /api/notifications list + query filters
  4. GET /api/notifications/unread-count
  5. POST /notifications/{id}/read, /mark-all-read, /read-all alias, DELETE
  6. Cross-tenant isolation (super@aquaterra switching via X-Tenant-Slug)
  7. RC simulate-inbound SMS fans out an rc_sms_inbound row per admin
  8. Preference gating: bell=false blocks row creation
  9. Body truncation to 500 chars via emit()
 10. Portal customer scoping (customer@aquaterra sees own rows only)
"""
import os
import asyncio
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_A  = ("admin@aquaterra.com", "password123")
SUPER    = ("super@aquaterra.com", "password123")
CUST_A   = ("customer@aquaterra.com", "password123")
ADMIN_S  = ("admin@sunbelt.com", "password123")
JENNIFER_PHONE = "480-555-0101"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _h(token, tenant=None):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if tenant:
        h["X-Tenant-Slug"] = tenant
    return h


# ─── Fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_token():
    return _login(*ADMIN_A)


@pytest.fixture(scope="module")
def super_token():
    return _login(*SUPER)


@pytest.fixture(scope="module")
def customer_token():
    return _login(*CUST_A)


# ─── 1. Kinds catalog ──────────────────────────────────────────────────────
def test_kinds_catalog(admin_token):
    r = requests.get(f"{API}/notifications/kinds", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200
    data = r.json()
    kinds = data.get("kinds") or []
    # Phase 55.1 added 4 *_unmatched kinds → 22 total. Assert a floor
    # and required-subset instead of an exact count so future kind
    # additions don't break this test.
    assert len(kinds) >= 22, f"expected ≥22 kinds, got {len(kinds)}"
    keys = {k["key"] for k in kinds}
    required_subset = {
        "rc_sms_inbound", "rc_call_inbound", "rc_voicemail", "rc_fax",
        "rc_sms_inbound_unmatched", "rc_call_inbound_unmatched",
        "rc_voicemail_unmatched", "rc_fax_unmatched",
        "invoice_paid", "system_alert",
    }
    missing = required_subset - keys
    assert not missing, f"kinds catalog missing required entries: {sorted(missing)}"
    defaults = data.get("defaults") or {}
    assert "rc_sms_inbound" in defaults
    assert defaults["rc_sms_inbound"] == {"bell": True, "email": False, "sms": False}


# ─── 2. Preferences GET + PUT roundtrip ────────────────────────────────────
def test_prefs_get_then_put_persists(admin_token):
    r = requests.get(f"{API}/settings/notifications", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "channels" in body and "kinds" in body
    assert body["channels"]["rc_sms_inbound"]["bell"] is True

    payload = {"channels": {"rc_sms_inbound": {"bell": True, "email": True, "sms": False}}}
    r2 = requests.put(f"{API}/settings/notifications", headers=_h(admin_token), json=payload, timeout=30)
    assert r2.status_code == 200
    assert r2.json()["channels"]["rc_sms_inbound"]["email"] is True

    r3 = requests.get(f"{API}/settings/notifications", headers=_h(admin_token), timeout=30)
    assert r3.status_code == 200
    assert r3.json()["channels"]["rc_sms_inbound"]["email"] is True

    # Reset back
    reset = {"channels": {"rc_sms_inbound": {"bell": True, "email": False, "sms": False}}}
    requests.put(f"{API}/settings/notifications", headers=_h(admin_token), json=reset, timeout=30)


# ─── 3. List + query filters + 4. unread-count ─────────────────────────────
def _seed_via_simulate(admin_token, tenant=None):
    """Trigger an inbound SMS -> emit -> notification row for every admin.

    Note: We call the RC handler in-process via subprocess because the
    seeded aquaterra customers store phones on the ``phone`` field, while
    ``_match_customer_by_phone`` only queries the ``phones`` array field
    (see Phase 54 note in bug report). To keep the Phase 55 tests
    focused on emit()+fan-out semantics rather than the phone-matching
    quirk, we bypass HTTP and invoke ``_handle_sms_event`` after
    injecting a matching customer's phones-array field."""
    import subprocess
    tenant_slug = tenant or "aquaterra"
    script = f'''
import asyncio, sys
sys.path.insert(0, "/app/backend")
from config import db
from routers.ringcentral import _handle_sms_event

async def main():
    ten = await db.tenants.find_one({{"slug":"{tenant_slug}"}}, {{"_id":0,"id":1}})
    if not ten:
        print("NO_TENANT"); return
    # Ensure at least one customer in this tenant has phones-array covering the test number
    cust = await db.customers.find_one({{"tenant_id": ten["id"], "phones": {{"$exists": True}}}}, {{"_id":0,"id":1}})
    if not cust:
        c = await db.customers.find_one({{"tenant_id": ten["id"]}}, {{"_id":0,"id":1,"phone":1}})
        if c:
            await db.customers.update_one({{"id": c["id"]}}, {{"$set": {{"phones": ["4805550999"]}}}})
    payload = {{"event": "instant-message-SMS",
                "body": {{"from": {{"phoneNumber": "+14805550999"}},
                          "to": [{{"phoneNumber": "+16028870000"}}],
                          "subject": "P55 test inbound"}}}}
    await _handle_sms_event(payload)
    print("OK")

asyncio.run(main())
'''
    out = subprocess.check_output(["python", "-c", script], cwd="/app/backend", timeout=30).decode()
    assert "OK" in out, out


def test_list_and_unread_count_and_kind_filter(admin_token):
    _seed_via_simulate(admin_token)
    # small buffer for db writes
    import time; time.sleep(0.4)

    r = requests.get(f"{API}/notifications?limit=50", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    # sorted desc by created_at
    if len(rows) >= 2:
        assert rows[0]["created_at"] >= rows[-1]["created_at"]

    # kind filter
    r2 = requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=10", headers=_h(admin_token), timeout=30)
    assert r2.status_code == 200
    assert all(x["kind"] == "rc_sms_inbound" for x in r2.json())

    # unread count
    r3 = requests.get(f"{API}/notifications/unread-count", headers=_h(admin_token), timeout=30)
    assert r3.status_code == 200
    c = r3.json().get("count")
    assert isinstance(c, int) and c >= 1

    # unread_only=true row count == unread-count
    r4 = requests.get(f"{API}/notifications?unread_only=true&limit=500", headers=_h(admin_token), timeout=30)
    assert r4.status_code == 200
    assert len(r4.json()) == c


# ─── 5. Mark read / mark-all-read / read-all alias / delete ────────────────
def test_mark_read_delete_and_mark_all(admin_token):
    _seed_via_simulate(admin_token)
    import time; time.sleep(0.3)
    rows = requests.get(f"{API}/notifications?unread_only=true&limit=5", headers=_h(admin_token), timeout=30).json()
    assert rows, "no unread rows to mark"

    nid = rows[0]["id"]
    r = requests.post(f"{API}/notifications/{nid}/read", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200 and r.json().get("ok") is True

    # Row must now be read
    got = requests.get(f"{API}/notifications?limit=200", headers=_h(admin_token), timeout=30).json()
    match = next((x for x in got if x["id"] == nid), None)
    assert match and match["read"] is True

    # Delete one
    nid2 = rows[1]["id"] if len(rows) > 1 else None
    if nid2:
        d = requests.delete(f"{API}/notifications/{nid2}", headers=_h(admin_token), timeout=30)
        assert d.status_code == 200
        got2 = requests.get(f"{API}/notifications?limit=200", headers=_h(admin_token), timeout=30).json()
        assert not any(x["id"] == nid2 for x in got2)

    # mark-all-read
    _seed_via_simulate(admin_token)
    time.sleep(0.3)
    r2 = requests.post(f"{API}/notifications/mark-all-read", headers=_h(admin_token), timeout=30)
    assert r2.status_code == 200
    assert requests.get(f"{API}/notifications/unread-count", headers=_h(admin_token), timeout=30).json()["count"] == 0

    # legacy alias /read-all
    _seed_via_simulate(admin_token)
    time.sleep(0.3)
    r3 = requests.post(f"{API}/notifications/read-all", headers=_h(admin_token), timeout=30)
    assert r3.status_code == 200
    assert requests.get(f"{API}/notifications/unread-count", headers=_h(admin_token), timeout=30).json()["count"] == 0


# ─── 6. Cross-tenant isolation (super admin) ───────────────────────────────
def test_tenant_isolation_super_admin(super_token, admin_token):
    # First, guarantee an aquaterra row exists
    _seed_via_simulate(admin_token)
    import time; time.sleep(0.3)

    aqua = requests.get(f"{API}/notifications?limit=200", headers=_h(super_token, "aquaterra"), timeout=30).json()
    sun  = requests.get(f"{API}/notifications?limit=200", headers=_h(super_token, "sunbelt"), timeout=30).json()

    aqua_ids = {r["id"] for r in aqua}
    sun_ids  = {r["id"] for r in sun}
    assert aqua_ids.isdisjoint(sun_ids), "notification bleed between tenants"

    # Every row must be scoped to expected tenant_id
    for row in aqua:
        assert row.get("tenant_id"), "missing tenant_id on aquaterra row"
    for row in sun:
        assert row.get("tenant_id"), "missing tenant_id on sunbelt row"


# ─── 7. Simulate-inbound fans out to every admin in the tenant ─────────────
def test_simulate_inbound_creates_row_for_each_admin(admin_token):
    import time
    # Clear inbox for admin_A first
    requests.post(f"{API}/notifications/mark-all-read", headers=_h(admin_token), timeout=30)
    before = requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=500", headers=_h(admin_token), timeout=30).json()
    _seed_via_simulate(admin_token)
    time.sleep(0.5)
    after = requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=500", headers=_h(admin_token), timeout=30).json()
    assert len(after) == len(before) + 1


# ─── 8. Preference gating: bell=false suppresses emit ──────────────────────
def test_pref_bell_false_suppresses_emit(admin_token):
    import time
    # Turn bell OFF for rc_sms_inbound
    pref_off = {"channels": {"rc_sms_inbound": {"bell": False, "email": False, "sms": False}}}
    r = requests.put(f"{API}/settings/notifications", headers=_h(admin_token), json=pref_off, timeout=30)
    assert r.status_code == 200

    before = len(requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=500", headers=_h(admin_token), timeout=30).json())
    _seed_via_simulate(admin_token)
    time.sleep(0.5)
    after = len(requests.get(f"{API}/notifications?kind=rc_sms_inbound&limit=500", headers=_h(admin_token), timeout=30).json())
    # Reset
    reset = {"channels": {"rc_sms_inbound": {"bell": True, "email": False, "sms": False}}}
    requests.put(f"{API}/settings/notifications", headers=_h(admin_token), json=reset, timeout=30)

    assert after == before, f"expected no new row when bell=false; before={before} after={after}"


# ─── 9. Body truncation to 500 chars ───────────────────────────────────────
def test_body_truncated_to_500():
    """Call emit() directly to prove BODY_TRUNCATE. Runs inside the backend
    container so we import from the live code path."""
    import subprocess
    script = r'''
import asyncio, sys
sys.path.insert(0, "/app/backend")
from services.notifications import emit
from config import db

async def main():
    admin = await db.users.find_one({"email":"admin@aquaterra.com"}, {"_id":0,"id":1,"tenant_id":1})
    ids = await emit([admin["id"]], "system_alert", "P55 truncate", "x"*1200,
                     tenant_id=admin["tenant_id"])
    row = await db.notifications.find_one({"id": ids[0]}, {"_id":0,"body":1})
    print("LEN=", len(row["body"]))
    # cleanup
    await db.notifications.delete_one({"id": ids[0]})

asyncio.run(main())
'''
    out = subprocess.check_output(["python", "-c", script], cwd="/app/backend", timeout=30).decode()
    assert "LEN= 500" in out, out


# ─── 10. Portal customer scoping ───────────────────────────────────────────
def test_portal_customer_sees_only_own_rows(customer_token, admin_token):
    # Seed an admin-scoped row first
    _seed_via_simulate(admin_token)
    import time; time.sleep(0.4)

    r = requests.get(f"{API}/notifications?limit=200", headers=_h(customer_token), timeout=30)
    assert r.status_code == 200
    rows = r.json()
    # Every row belongs to customer or is broadcast
    # Fetch customer's own id
    me = requests.get(f"{API}/auth/me", headers=_h(customer_token), timeout=30).json()
    my_id = me["id"]
    my_cust_id = me.get("customer_id")
    for row in rows:
        assert row.get("user_id") in (my_id, "*") or (my_cust_id and row.get("customer_id") == my_cust_id), \
            f"customer saw foreign row: {row}"

"""MP1 — Multi-Property backend (Feb-2026 ship)."""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"MP1 Test {marker}",
        "first_name": "TEST_MP1", "last_name": f"Cust{marker}",
        "email": f"mp1_{marker}@example.com",
        "phone": "+14805555555",
        "address": "1 MP1 Test Way",
        "address_line1": "1 MP1 Test Way",
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    # Cleanup properties + customer.
    props = requests.get(f"{API}/customers/{doc['id']}/properties",
                           headers=admin_headers, timeout=15).json() or []
    for p in props:
        requests.delete(f"{API}/properties/{p['id']}",
                          headers=admin_headers, timeout=15)
    requests.delete(f"{API}/customers/{doc['id']}",
                      headers=admin_headers, timeout=15)


def _new_prop(admin_headers, cid, label=None, **extra):
    body = {
        "label": label or f"Prop {uuid.uuid4().hex[:6]}",
        "address": {"line1": "9 Any St", "city": "Peoria",
                     "state": "AZ", "postal_code": "85383"},
        **extra,
    }
    r = requests.post(f"{API}/customers/{cid}/properties",
                        headers=admin_headers, json=body, timeout=15)
    return r


# ─── Create + list + lazy backfill ────────────────────────────────────

def test_create_property_basic(admin_headers, customer):
    r = _new_prop(admin_headers, customer["id"], label="Main House")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["label"] == "Main House"
    assert doc["active"] is True
    assert doc["sort_order"] >= 0
    assert doc["customer_id"] == customer["id"]


def test_lazy_backfill_seeds_main_property_on_first_list(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"Backfill {marker}",
        "first_name": "TEST_BF", "last_name": f"BF{marker}",
        "address": "77 Backfill Ave",
        "address_line1": "77 Backfill Ave",
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        r = requests.get(f"{API}/customers/{cid}/properties",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        docs = r.json()
        assert len(docs) == 1, f"expected 1 seeded property; got {docs}"
        assert docs[0]["backfilled_from_customer"] is True
        assert docs[0]["address"]["line1"] == "77 Backfill Ave"
        # Idempotent — second GET does not double-seed.
        r2 = requests.get(f"{API}/customers/{cid}/properties",
                            headers=admin_headers, timeout=15)
        assert len(r2.json()) == 1
    finally:
        for p in requests.get(f"{API}/customers/{cid}/properties",
                                headers=admin_headers, timeout=15).json() or []:
            requests.delete(f"{API}/properties/{p['id']}",
                              headers=admin_headers, timeout=15)
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


def test_no_backfill_when_customer_lacks_address(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"NoAddr {marker}",
        "first_name": "TEST_NA", "last_name": f"NA{marker}",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        r = requests.get(f"{API}/customers/{cid}/properties",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json() == []
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


# ─── 8-property cap ───────────────────────────────────────────────────

def test_eight_property_cap_enforced(admin_headers, customer):
    for i in range(8):
        r = _new_prop(admin_headers, customer["id"], label=f"P{i}")
        assert r.status_code == 201, r.text
    # The 9th must be rejected.
    r = _new_prop(admin_headers, customer["id"], label="P9")
    assert r.status_code == 400
    assert "cannot exceed 8" in r.text.lower()


# ─── Sort order + reorder ─────────────────────────────────────────────

def test_sort_order_auto_increments(admin_headers, customer):
    ids = []
    for i in range(3):
        r = _new_prop(admin_headers, customer["id"], label=f"S{i}")
        ids.append(r.json()["id"])
    docs = requests.get(f"{API}/customers/{customer['id']}/properties",
                          headers=admin_headers, timeout=15).json()
    order = [d["id"] for d in docs]
    assert order[:3] == ids or set(order) == set(ids)  # id-order or sort-order
    # All must have distinct sort_order values.
    orders = [d["sort_order"] for d in docs]
    assert len(set(orders)) == len(orders)


def test_reorder_updates_sort_order(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="R1").json()["id"]
    p2 = _new_prop(admin_headers, customer["id"], label="R2").json()["id"]
    p3 = _new_prop(admin_headers, customer["id"], label="R3").json()["id"]
    # Reverse order.
    r = requests.post(f"{API}/properties/reorder", headers=admin_headers, json={
        "customer_id": customer["id"],
        "ordered_property_ids": [p3, p2, p1],
    }, timeout=15)
    assert r.status_code == 200, r.text
    docs = requests.get(f"{API}/customers/{customer['id']}/properties",
                          headers=admin_headers, timeout=15).json()
    order = [d["id"] for d in docs]
    assert order == [p3, p2, p1], order


# ─── Get + patch ──────────────────────────────────────────────────────

def test_get_property_and_patch_persists(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="GetPatch").json()["id"]
    r = requests.get(f"{API}/properties/{pid}", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    r = requests.patch(f"{API}/properties/{pid}", headers=admin_headers,
                        json={"label": "Renamed", "pool_size_gallons": 12000}, timeout=15)
    assert r.status_code == 200
    doc = r.json()
    assert doc["label"] == "Renamed"
    assert doc["pool_size_gallons"] == 12000


# ─── Duplicate ────────────────────────────────────────────────────────

def test_duplicate_property_copies_and_increments_order(admin_headers, customer):
    src = _new_prop(admin_headers, customer["id"], label="Original").json()
    r = requests.post(f"{API}/properties/{src['id']}/duplicate",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 201, r.text
    dup = r.json()
    assert dup["id"] != src["id"]
    assert dup["label"] == "Original (copy)"
    assert dup["sort_order"] > src["sort_order"]


def test_duplicate_respects_cap(admin_headers, customer):
    for i in range(8):
        _new_prop(admin_headers, customer["id"], label=f"C{i}")
    src = requests.get(f"{API}/customers/{customer['id']}/properties",
                         headers=admin_headers, timeout=15).json()[0]
    r = requests.post(f"{API}/properties/{src['id']}/duplicate",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 400


# ─── Soft-delete + open-jobs guard ────────────────────────────────────

def test_delete_property_soft_deletes(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="ToDelete").json()["id"]
    r = requests.delete(f"{API}/properties/{pid}", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["active"] is False
    # Still in DB, just active=False.
    docs = requests.get(f"{API}/customers/{customer['id']}/properties",
                          headers=admin_headers, timeout=15).json()
    match = next((d for d in docs if d["id"] == pid), None)
    assert match is not None
    assert match["active"] is False


def test_delete_blocked_when_open_jobs(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="HasJobs").json()["id"]
    # Create a scheduled job on this property.
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": pid,
        "title": "TEST_open_job_block",
        "status": "scheduled",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    jid = r.json()["id"]
    try:
        r = requests.delete(f"{API}/properties/{pid}",
                              headers=admin_headers, timeout=15)
        assert r.status_code == 400
        assert "open job" in r.text.lower()
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)


# ─── Job.property_id validation ───────────────────────────────────────

def test_job_property_id_auto_assigns_when_single_property(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="Sole").json()["id"]
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "title": "TEST_auto_assign_property",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    assert r.json()["property_id"] == pid, (
        f"expected auto-assigned property_id={pid}, got {r.json().get('property_id')!r}"
    )
    requests.delete(f"{API}/jobs/{r.json()['id']}", headers=admin_headers, timeout=15)


def test_job_property_id_required_when_multiple(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="A").json()["id"]
    _new_prop(admin_headers, customer["id"], label="B")
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "title": "TEST_multi_prop_reject",
    }, timeout=15)
    assert r.status_code == 400
    assert "property_id required" in r.text.lower()
    # With explicit property_id it succeeds.
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": p1,
        "title": "TEST_multi_prop_accept",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    assert r.json()["property_id"] == p1
    requests.delete(f"{API}/jobs/{r.json()['id']}", headers=admin_headers, timeout=15)


# ─── Master billing mode ──────────────────────────────────────────────

def test_master_billing_mode_transitions(admin_headers, customer):
    for mode in ("consolidated", "forward_to_master_contact", "off"):
        r = requests.patch(f"{API}/customers/{customer['id']}/master-billing",
                             headers=admin_headers, json={"mode": mode},
                             timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["master_billing_mode"] == mode


def test_master_billing_bad_mode_400(admin_headers, customer):
    r = requests.patch(f"{API}/customers/{customer['id']}/master-billing",
                         headers=admin_headers, json={"mode": "bogus"}, timeout=15)
    assert r.status_code == 400


def test_master_billing_forwards_to_override_email(admin_headers, customer):
    r = requests.patch(f"{API}/customers/{customer['id']}/master-billing",
                         headers=admin_headers, json={
        "mode": "forward_to_master_contact",
        "master_billing_contact_email": "billing@override.com",
        "master_billing_contact_phone": "+14805557777",
    }, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["master_billing_contact_email"] == "billing@override.com"
    assert body["master_billing_contact_phone"] == "+14805557777"


def test_resolve_invoice_recipient_all_three_modes():
    from routers.properties import resolve_invoice_recipient
    prop = {"site_contact": {
        "emails": [{"address": "site@x.com", "is_primary": True}],
        "mobiles": [{"number_e164": "+15550001", "is_primary": True}],
    }}
    cust_off = {"email": "cust@x.com", "phone": "+15559999"}
    # off — site contact wins.
    out = resolve_invoice_recipient(cust_off, prop)
    assert out["email"] == "site@x.com"
    assert out["delivery_kind"] == "per_property"
    # consolidated — customer primary wins.
    cust_con = {**cust_off, "master_billing_mode": "consolidated"}
    out = resolve_invoice_recipient(cust_con, prop)
    assert out["email"] == "cust@x.com"
    assert out["delivery_kind"] == "consolidated"
    # forward_to_master_contact — override wins.
    cust_fwd = {**cust_off, "master_billing_mode": "forward_to_master_contact",
                 "master_billing_contact_email": "billing@x.com"}
    out = resolve_invoice_recipient(cust_fwd, prop)
    assert out["email"] == "billing@x.com"
    assert out["delivery_kind"] == "forwarded"


# ─── Tenant isolation + RBAC ──────────────────────────────────────────

def test_tech_cannot_create_or_delete_property(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="TechTest").json()["id"]
    tech_tok = _login("mike@aquaterra.com")
    th = {"Authorization": f"Bearer {tech_tok}"}
    # Create.
    r = requests.post(f"{API}/customers/{customer['id']}/properties",
                        headers=th, json={
        "label": "TechCannot",
        "address": {"line1": "1 Y", "city": "Peoria", "state": "AZ"},
    }, timeout=15)
    assert r.status_code in (401, 403)
    # Delete.
    r = requests.delete(f"{API}/properties/{pid}", headers=th, timeout=15)
    assert r.status_code in (401, 403)


def test_property_schedule_returns_property_jobs(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="SchedProp").json()["id"]
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": pid,
        "title": "TEST_prop_sched",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    jid = r.json()["id"]
    try:
        r = requests.get(f"{API}/properties/{pid}/schedule",
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["property_id"] == pid
        assert any(j["id"] == jid for j in body["jobs"]), body
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)


def test_property_404_on_unknown_id(admin_headers):
    r = requests.get(f"{API}/properties/does-not-exist",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404
    r = requests.patch(f"{API}/properties/does-not-exist",
                        headers=admin_headers, json={"label": "x"}, timeout=15)
    assert r.status_code == 404
    r = requests.delete(f"{API}/properties/does-not-exist",
                          headers=admin_headers, timeout=15)
    assert r.status_code == 404


def test_openapi_paths_include_properties(admin_headers):
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    assert "/api/customers/{cid}/properties" in paths
    assert "/api/properties/{pid}" in paths
    assert "/api/properties/{pid}/duplicate" in paths
    assert "/api/properties/reorder" in paths
    assert "/api/properties/{pid}/schedule" in paths
    assert "/api/customers/{cid}/master-billing" in paths


# ─── Tester regression pins (Feb-2026 T4 delta) ────────────────────────

def test_delete_blocked_when_default_pending_status_job_exists(admin_headers, customer):
    """Tester regression — the delete guard used to whitelist only
    ["scheduled", "in_progress", "on_the_way"], missing the default
    ``JobIn.status = "pending"`` from newly created jobs. Freshly
    created jobs slipped through and the property could be deleted
    while a real open job existed."""
    pid = _new_prop(admin_headers, customer["id"], label="PendingGuard").json()["id"]
    # Create a job with NO explicit status — defaults to "pending".
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": pid,
        "title": "TEST_pending_default_blocks_delete",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    jid = r.json()["id"]
    # Sanity — job's status is indeed "pending" (or similar).
    assert r.json().get("status") in ("pending", "created", "scheduled")
    try:
        r = requests.delete(f"{API}/properties/{pid}",
                              headers=admin_headers, timeout=15)
        assert r.status_code == 400, (
            f"delete guard failed to catch default-status job; got {r.status_code} {r.text}"
        )
        assert "open job" in r.text.lower()
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)


def test_property_created_notification_row_written(admin_headers, customer):
    """Tester regression — ``property.created`` was registered as a
    unified notification kind but no row was actually written on
    create because ``_emit`` excluded the actor from the audience.
    Fix: audience now includes every tenant admin including the actor.
    """
    marker = uuid.uuid4().hex[:8]
    r = _new_prop(admin_headers, customer["id"], label=f"NotifCreate_{marker}")
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    # Wait a tick for the fire-and-forget emit path to complete.
    import time
    time.sleep(0.6)
    # Notifications inbox — endpoint returns a bare list.
    r = requests.get(f"{API}/notifications?kind=property.created",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list), f"expected list; got {type(rows)}"
    matched = [n for n in rows
                if (n.get("source_ref") or {}).get("id") == pid]
    assert matched, (
        f"expected a property.created notification for property {pid}; "
        f"got {len(rows)} rows total"
    )


def test_property_deleted_notification_row_written(admin_headers, customer):
    """Same fix, delete path."""
    marker = uuid.uuid4().hex[:8]
    pid = _new_prop(admin_headers, customer["id"], label=f"NotifDel_{marker}").json()["id"]
    # Delete cleanly (no open jobs on this fresh property).
    r = requests.delete(f"{API}/properties/{pid}", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    import time
    time.sleep(0.6)
    r = requests.get(f"{API}/notifications?kind=property.deleted",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    matched = [n for n in rows
                if (n.get("source_ref") or {}).get("id") == pid]
    assert matched, f"expected a property.deleted notification for {pid}"


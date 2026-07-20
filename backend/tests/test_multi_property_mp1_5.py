"""MP1.5 — Multi-property invoice plumbing (Feb-2026 ship).

Covers:
    * ``property_id`` on invoices + estimates: create, patch, conversion carry-through
    * Auto-assign to sole active property + validation on unknown/inactive ids
    * ``POST /api/invoices/consolidate`` — happy path, idempotency, dry-run
    * ``GET  /api/customers/{cid}/pending-invoices`` — grouping, tenant iso
    * ``POST /api/invoices/preview-recipient`` — all three billing modes
    * ``resolve_invoice_recipient`` unit tests + missing-recipient hint
    * RBAC — techs cannot hit any of the new admin endpoints
    * Tenant isolation — customer/invoice IDs from another tenant 404
"""
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
        "name": f"MP1.5 Test {marker}",
        "first_name": "TEST_MP15", "last_name": f"C{marker}",
        "email": f"mp15_{marker}@example.com",
        "phone": "+14805556666",
        "address": "5 MP1.5 Way",
        "address_line1": "5 MP1.5 Way",
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    # Cleanup — best effort.
    try:
        invs = requests.get(f"{API}/quotes?doc_type=invoice",
                              headers=admin_headers, timeout=15).json() or []
        for inv in invs:
            if inv.get("customer_id") == doc["id"]:
                requests.delete(f"{API}/quotes/{inv['id']}",
                                  headers=admin_headers, timeout=10)
    except Exception:
        pass
    props = requests.get(f"{API}/customers/{doc['id']}/properties",
                          headers=admin_headers, timeout=15).json() or []
    for p in props:
        requests.delete(f"{API}/properties/{p['id']}",
                          headers=admin_headers, timeout=15)
    requests.delete(f"{API}/customers/{doc['id']}",
                      headers=admin_headers, timeout=15)


def _new_prop(admin_headers, cid, label=None,
              site_email=None, site_phone=None, **extra):
    body = {
        "label": label or f"Prop {uuid.uuid4().hex[:6]}",
        "address": {"line1": "9 Any St", "city": "Peoria",
                     "state": "AZ", "postal_code": "85383"},
        **extra,
    }
    if site_email or site_phone:
        body["site_contact"] = {
            "emails": ([{"address": site_email, "is_primary": True,
                            "label": "Primary"}] if site_email else []),
            "mobiles": ([{"number_e164": site_phone, "is_primary": True,
                             "label": "Primary"}] if site_phone else []),
        }
    r = requests.post(f"{API}/customers/{cid}/properties",
                        headers=admin_headers, json=body, timeout=15)
    return r


def _new_invoice(admin_headers, cid, property_id=None, title=None,
                  line_items=None):
    body = {
        "customer_id": cid,
        "title": title or f"Inv {uuid.uuid4().hex[:6]}",
        "doc_type": "invoice",
        "line_items": line_items or [
            {"description": "Weekly service", "quantity": 1, "unit_price": 120.0,
              "category": "Pool"},
        ],
        "tax_rate": 0,
    }
    if property_id is not None:
        body["property_id"] = property_id
    return requests.post(f"{API}/quotes", headers=admin_headers,
                            json=body, timeout=15)


# ─── Schema: property_id on invoices ──────────────────────────────────

def test_invoice_property_id_auto_assigns_when_single_property(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="Sole").json()["id"]
    r = _new_invoice(admin_headers, customer["id"])
    assert r.status_code in (200, 201), r.text
    assert r.json()["property_id"] == pid


def test_invoice_property_id_explicit_persists(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="A").json()["id"]
    _new_prop(admin_headers, customer["id"], label="B")
    r = _new_invoice(admin_headers, customer["id"], property_id=p1)
    assert r.status_code in (200, 201), r.text
    assert r.json()["property_id"] == p1


def test_invoice_property_id_null_allowed_when_multi_prop(admin_headers, customer):
    """Multiple properties + no explicit property_id → the invoice is
    left un-scoped (property_id=None). This is the consolidated-across-
    properties case; POST /jobs behaves differently (400) but invoices
    intentionally allow it because MASTER billing exists."""
    _new_prop(admin_headers, customer["id"], label="A")
    _new_prop(admin_headers, customer["id"], label="B")
    r = _new_invoice(admin_headers, customer["id"])
    assert r.status_code in (200, 201), r.text
    assert r.json().get("property_id") in (None, "")


def test_invoice_property_id_rejects_unknown(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="A")
    r = _new_invoice(admin_headers, customer["id"],
                       property_id="does-not-exist")
    assert r.status_code == 400
    assert "not found" in r.text.lower()


def test_invoice_property_id_rejects_inactive(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="A").json()["id"]
    _new_prop(admin_headers, customer["id"], label="B")  # keep active count ≥ 1 after delete
    # Soft-delete P1.
    requests.delete(f"{API}/properties/{p1}",
                      headers=admin_headers, timeout=15)
    r = _new_invoice(admin_headers, customer["id"], property_id=p1)
    assert r.status_code == 400


def test_invoice_property_id_patch_persists(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="A").json()["id"]
    p2 = _new_prop(admin_headers, customer["id"], label="B").json()["id"]
    inv = _new_invoice(admin_headers, customer["id"], property_id=p1).json()
    r = requests.put(f"{API}/quotes/{inv['id']}", headers=admin_headers,
                        json={"property_id": p2}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["property_id"] == p2


# ─── Estimates ─────────────────────────────────────────────────────────

def test_estimate_property_id_auto_assigns_when_single(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="Only").json()["id"]
    r = requests.post(f"{API}/estimates", headers=admin_headers, json={
        "customer_id": customer["id"],
        "title": "Est A",
        "line_items": [{"category": "Labor", "description": "Job",
                          "quantity": 1, "unit_cost": 50}],
        "overhead_pct": 10, "margin_pct": 20,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    assert r.json()["property_id"] == pid


def test_estimate_property_id_rejects_unknown(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="A")
    r = requests.post(f"{API}/estimates", headers=admin_headers, json={
        "customer_id": customer["id"], "title": "BadProp",
        "property_id": "nope",
        "line_items": [{"category": "Labor", "description": "X",
                          "quantity": 1, "unit_cost": 10}],
        "overhead_pct": 10, "margin_pct": 20,
    }, timeout=15)
    assert r.status_code == 400


def test_estimate_conversion_carries_property_id(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="EstProp").json()["id"]
    r = requests.post(f"{API}/estimates", headers=admin_headers, json={
        "customer_id": customer["id"], "title": "Convertible",
        "property_id": pid,
        "line_items": [{"category": "Labor", "description": "X",
                          "quantity": 1, "unit_cost": 100}],
        "overhead_pct": 10, "margin_pct": 25,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    est = r.json()
    assert est["property_id"] == pid
    r = requests.post(f"{API}/estimates/{est['id']}/convert",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["property_id"] == pid


# ─── Pending-invoices grouping ─────────────────────────────────────────

def test_pending_invoices_groups_by_property(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="Alpha").json()["id"]
    p2 = _new_prop(admin_headers, customer["id"], label="Bravo").json()["id"]
    _new_invoice(admin_headers, customer["id"], property_id=p1,
                  title="Alpha week 1")
    _new_invoice(admin_headers, customer["id"], property_id=p2,
                  title="Bravo week 1")
    _new_invoice(admin_headers, customer["id"], property_id=p2,
                  title="Bravo week 2")
    r = requests.get(f"{API}/customers/{customer['id']}/pending-invoices",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    labels = {g["property_id"]: g for g in body["groups"]}
    assert p1 in labels and p2 in labels
    assert len(labels[p1]["invoices"]) == 1
    assert len(labels[p2]["invoices"]) == 2
    assert labels[p2]["property_label"] == "Bravo"
    assert body["pending_count"] >= 3


def test_pending_invoices_tech_forbidden(admin_headers, customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/customers/{customer['id']}/pending-invoices",
                       headers={"Authorization": f"Bearer {tech_tok}"},
                       timeout=15)
    assert r.status_code in (401, 403)


def test_pending_invoices_404_unknown_customer(admin_headers):
    r = requests.get(f"{API}/customers/no-such-id/pending-invoices",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 404


# ─── Consolidate ───────────────────────────────────────────────────────

def test_consolidate_happy_path(admin_headers, customer):
    p1 = _new_prop(admin_headers, customer["id"], label="C1").json()["id"]
    p2 = _new_prop(admin_headers, customer["id"], label="C2").json()["id"]
    i1 = _new_invoice(admin_headers, customer["id"], property_id=p1,
                        title="C1 week 1",
                        line_items=[{"description": "Svc",
                                       "quantity": 1, "unit_price": 100.0,
                                       "category": "Pool"}]).json()
    i2 = _new_invoice(admin_headers, customer["id"], property_id=p2,
                        title="C2 week 1",
                        line_items=[{"description": "Svc",
                                       "quantity": 2, "unit_price": 50.0,
                                       "category": "Pool"}]).json()
    r = requests.post(f"{API}/invoices/consolidate",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
        "period": "2026-02",
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["already_existed"] is False
    parent = body["invoice"]
    assert parent["is_consolidated"] is True
    assert parent["consolidation_period"] == "2026-02"
    # ≥2 real line items + 2 section headers.
    assert len([li for li in parent["line_items"]
                    if not li.get("is_section_header")]) >= 2
    assert parent["subtotal"] == 200.0
    assert set(parent["consolidated_child_ids"]) >= {i1["id"], i2["id"]}


def test_consolidate_is_idempotent(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="Sole")
    _new_invoice(admin_headers, customer["id"], title="one",
                  line_items=[{"description": "svc", "quantity": 1,
                                 "unit_price": 30, "category": "Pool"}])
    r1 = requests.post(f"{API}/invoices/consolidate", headers=admin_headers,
                         json={"customer_id": customer["id"],
                                "period": "2026-02"}, timeout=15).json()
    r2 = requests.post(f"{API}/invoices/consolidate", headers=admin_headers,
                         json={"customer_id": customer["id"],
                                "period": "2026-02"}, timeout=15).json()
    assert r1["invoice_id"] == r2["invoice_id"]
    assert r2["already_existed"] is True


def test_consolidate_marks_children_with_parent_id(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="Sole")
    child = _new_invoice(admin_headers, customer["id"], title="child").json()
    parent = requests.post(f"{API}/invoices/consolidate",
                             headers=admin_headers, json={
        "customer_id": customer["id"], "period": "2026-02",
    }, timeout=15).json()
    parent_id = parent["invoice_id"]
    r = requests.get(f"{API}/quotes/{child['id']}",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["consolidated_into_invoice_id"] == parent_id


def test_consolidate_rejects_when_no_pending(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="Empty")
    r = requests.post(f"{API}/invoices/consolidate",
                        headers=admin_headers, json={
        "customer_id": customer["id"], "period": "2026-02",
    }, timeout=15)
    assert r.status_code == 400
    assert "no pending" in r.text.lower()


def test_consolidate_dry_run_does_not_persist(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="DryProp")
    _new_invoice(admin_headers, customer["id"], title="dryrun-child")
    r = requests.post(f"{API}/invoices/consolidate",
                        headers=admin_headers, json={
        "customer_id": customer["id"], "period": "2026-03",
        "dry_run": True,
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["child_count"] >= 1
    # No consolidated invoice should exist for this period yet.
    r2 = requests.get(f"{API}/quotes?doc_type=invoice",
                        headers=admin_headers, timeout=15)
    consolidated = [d for d in (r2.json() or [])
                       if d.get("is_consolidated")
                       and d.get("consolidation_period") == "2026-03"
                       and d.get("customer_id") == customer["id"]]
    assert consolidated == []


def test_consolidate_tenant_isolation(admin_headers, customer):
    """A customer id from another tenant should 404. We spoof this by
    passing a random uuid — the endpoint returns 404 because the
    lookup is scoped to the current tenant."""
    r = requests.post(f"{API}/invoices/consolidate",
                        headers=admin_headers, json={
        "customer_id": uuid.uuid4().hex,
        "period": "2026-02",
    }, timeout=15)
    assert r.status_code == 404


def test_consolidate_tech_forbidden(admin_headers, customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.post(f"{API}/invoices/consolidate",
                        headers={"Authorization": f"Bearer {tech_tok}"},
                        json={"customer_id": customer["id"]},
                        timeout=15)
    assert r.status_code in (401, 403)


# ─── Preview recipient ─────────────────────────────────────────────────

def test_preview_recipient_off_mode_uses_property_contact(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="OffProp",
                     site_email="site@example.com",
                     site_phone="+15551110001").json()["id"]
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "customer_id": customer["id"], "property_id": pid,
    }, timeout=15)
    assert r.status_code == 200, r.text
    rec = r.json()["recipient"]
    assert rec["email"] == "site@example.com"
    assert rec["phone"] == "+15551110001"
    assert rec["delivery_kind"] == "per_property"
    assert rec["send_status_hint"] == "ready"


def test_preview_recipient_consolidated_mode_uses_customer(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="C",
                site_email="site@example.com")
    requests.patch(f"{API}/customers/{customer['id']}/master-billing",
                     headers=admin_headers, json={
        "mode": "consolidated",
    }, timeout=15)
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
    }, timeout=15)
    assert r.status_code == 200, r.text
    rec = r.json()["recipient"]
    # Falls back through primary_email → customer.email scalar.
    assert rec["email"] and "@" in rec["email"]
    assert rec["email"] != "site@example.com"
    assert rec["delivery_kind"] == "consolidated"


def test_preview_recipient_forward_mode_uses_override(admin_headers, customer):
    _new_prop(admin_headers, customer["id"], label="F",
                site_email="site@example.com")
    requests.patch(f"{API}/customers/{customer['id']}/master-billing",
                     headers=admin_headers, json={
        "mode": "forward_to_master_contact",
        "master_billing_contact_email": "billing@override.example",
        "master_billing_contact_phone": "+15550009999",
    }, timeout=15)
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
    }, timeout=15)
    assert r.status_code == 200, r.text
    rec = r.json()["recipient"]
    assert rec["email"] == "billing@override.example"
    assert rec["phone"] == "+15550009999"
    assert rec["delivery_kind"] == "forwarded"


def test_preview_recipient_missing_recipient_hint(admin_headers):
    """Customer with no primary email/phone + off mode + no property
    site contact → recipient email/phone come back null with an
    explicit ``not_sent_missing_recipient`` hint."""
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"Ghost {marker}",
        "first_name": "TEST_GHOST", "last_name": f"G{marker}",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        r = requests.post(f"{API}/invoices/preview-recipient",
                            headers=admin_headers, json={
            "customer_id": cid,
        }, timeout=15)
        assert r.status_code == 200, r.text
        rec = r.json()["recipient"]
        assert rec["email"] in (None, "", False)
        assert rec["phone"] in (None, "", False)
        assert rec["send_status_hint"] == "not_sent_missing_recipient"
    finally:
        requests.delete(f"{API}/customers/{cid}",
                          headers=admin_headers, timeout=15)


def test_preview_recipient_by_invoice_id(admin_headers, customer):
    pid = _new_prop(admin_headers, customer["id"], label="Byinvid",
                     site_email="site2@example.com").json()["id"]
    inv = _new_invoice(admin_headers, customer["id"], property_id=pid).json()
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "invoice_id": inv["id"],
    }, timeout=15)
    assert r.status_code == 200, r.text
    rec = r.json()["recipient"]
    assert rec["email"] == "site2@example.com"


def test_preview_recipient_mode_override_bypasses_persisted(admin_headers, customer):
    """Override lets the UI simulate a mode change without writing to
    the customer row — critical for the settings preview surface."""
    _new_prop(admin_headers, customer["id"], label="OverrideProp",
                site_email="local@example.com")
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
        "mode": "consolidated",
    }, timeout=15)
    assert r.status_code == 200, r.text
    rec = r.json()["recipient"]
    assert rec["mode"] == "consolidated"


def test_preview_recipient_rejects_bad_mode(admin_headers, customer):
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
        "mode": "not_a_mode",
    }, timeout=15)
    assert r.status_code == 400


def test_preview_recipient_tech_forbidden(admin_headers, customer):
    tech_tok = _login("mike@aquaterra.com")
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers={"Authorization": f"Bearer {tech_tok}"},
                        json={"customer_id": customer["id"]},
                        timeout=15)
    assert r.status_code in (401, 403)


# ─── resolve_invoice_recipient unit tests ──────────────────────────────

def test_resolve_recipient_off_falls_back_to_customer_email():
    from routers.properties import resolve_invoice_recipient
    prop = {"site_contact": {"emails": [], "mobiles": []}}
    cust = {"email": "cust@x.com", "phone": "+15551234"}
    out = resolve_invoice_recipient(cust, prop)
    assert out["email"] == "cust@x.com"
    assert out["phone"] == "+15551234"
    assert out["delivery_kind"] == "per_property"
    assert out["send_status_hint"] == "ready"


def test_resolve_recipient_off_returns_missing_hint_when_no_recipient():
    from routers.properties import resolve_invoice_recipient
    prop = {"site_contact": {"emails": [], "mobiles": []}}
    cust = {}
    out = resolve_invoice_recipient(cust, prop)
    assert out["email"] is None
    assert out["phone"] is None
    assert out["send_status_hint"] == "not_sent_missing_recipient"


def test_resolve_recipient_uses_multi_contact_primary_email():
    """Feb-2026 MP1.5 — resolve_invoice_recipient must honor the
    multi-contact ``emails[]`` array (is_primary flag) before falling
    back to the legacy ``email`` scalar."""
    from routers.properties import resolve_invoice_recipient
    prop = {}
    cust = {
        "email": "legacy@x.com",  # should be IGNORED
        "emails": [
            {"address": "second@x.com", "is_primary": False},
            {"address": "primary@x.com", "is_primary": True},
        ],
        "master_billing_mode": "consolidated",
    }
    out = resolve_invoice_recipient(cust, prop)
    assert out["email"] == "primary@x.com"


def test_resolve_recipient_forward_falls_back_to_customer_primary():
    """forward_to_master_contact with no override + no primary email
    still returns customer's legacy ``email`` scalar."""
    from routers.properties import resolve_invoice_recipient
    cust = {"master_billing_mode": "forward_to_master_contact",
             "email": "cust@x.com"}
    out = resolve_invoice_recipient(cust, None)
    assert out["email"] == "cust@x.com"
    assert out["delivery_kind"] == "forwarded"


# ─── OpenAPI + tenant hygiene ──────────────────────────────────────────

def test_openapi_includes_mp15_paths():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    assert "/api/invoices/consolidate" in paths
    assert "/api/invoices/preview-recipient" in paths
    assert "/api/customers/{cid}/pending-invoices" in paths


def test_preview_recipient_invoice_id_404_when_missing(admin_headers):
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "invoice_id": uuid.uuid4().hex,
    }, timeout=15)
    assert r.status_code == 404

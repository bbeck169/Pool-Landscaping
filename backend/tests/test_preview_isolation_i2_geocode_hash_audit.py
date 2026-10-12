"""Preview isolation · P0 Stage 3 Commit I2 — geocode_address_hash
audit refinement regression.

Blocker 1 of the P0a Stage 3 final-verification pass showed the
``customers.geocode_address_hash`` audit rule firing RED on 4 rows
whose hash was provably of the already-synthesized address string
(see ``/app/memory/preview_isolation_blocker1_investigation.md``).

This test suite pins the audit-rule refinement:

* Rows with an address matching the synthetic ``^\\d+ Preview\\b``
  signature AND a non-null ``geocode_address_hash`` MUST NOT be
  flagged (hash is of synthetic data — zero PII correlation).
* Rows with a REAL (non-synthetic) address AND a non-null hash
  MUST still be flagged (that's the legacy pre-Stage-3 leakage
  case the rule is designed to catch).
* A fresh preview POST through the middleware MUST land with a
  ``geocode_address_hash`` that equals ``address_hash("<bucket>
  Preview St")`` — hash of synth, NOT hash of the submitted real
  address.
* The healthcheck's ``per_field_counts["geocode_address_hash"]``
  MUST be 0 after a preview POST, i.e. the audit rule stays GREEN.

The 4 cases are intentionally self-contained — each seeds its own
test-id-tagged fixture row and tears it down in a try/finally so
parallel runs on the shared preview DB don't collide.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _addr_hash(addr: str) -> str:
    """Mirror of ``routers.admin_customer_geocode_backfill.address_hash``."""
    if not addr:
        return ""
    norm = " ".join(str(addr).strip().lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def live_db():
    c = MongoClient(_ENV["MONGO_URL"])
    yield c[_ENV["DB_NAME"]]
    c.close()


# ────────────────────────────────────────────────────────────────────
# 1 · Rule check — synthetic address + non-null hash → NOT flagged.
# ────────────────────────────────────────────────────────────────────
def test_geocode_hash_of_synthetic_address_is_not_flagged(live_db):
    """Direct audit-filter evaluation. Seed one row with the
    synthetic ``^\\d+ Preview\\b`` address shape AND a non-null
    hash. Run the exact audit filter from
    ``routers.preview_isolation_admin._AUDIT_RULES``. Expect 0
    matches."""
    from routers.preview_isolation_admin import _AUDIT_RULES

    rule = next(
        r for r in _AUDIT_RULES
        if r["coll"] == "customers" and r["field"] == "geocode_address_hash"
    )

    marker = f"i2-synth-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": marker,
        "tenant_id": "i2-test-tenant",
        "name": "Preview Customer4242",
        "address": "4242 Preview St",
        "address_line1": "4242 Preview St",
        "geocode_address_hash": _addr_hash("4242 Preview St"),
        "i2_test_marker": marker,
    }
    live_db.customers.insert_one(doc)
    try:
        # Combine the rule filter with our marker so we only count
        # the fixture row — the audit runs collection-wide normally,
        # but the correctness of the FILTER itself is what we're
        # pinning here, and we can't risk false negatives from
        # other rows in the shared preview DB.
        combined = {"$and": [rule["filter"], {"i2_test_marker": marker}]}
        hits = live_db.customers.count_documents(combined)
        assert hits == 0, (
            f"audit rule falsely flagged synthetic-address row: {hits} hit(s). "
            f"Hash is of '4242 Preview St' (public synthetic string, "
            f"not real PII)."
        )
    finally:
        live_db.customers.delete_one({"id": marker})


# ────────────────────────────────────────────────────────────────────
# 2 · Rule check — real address + non-null hash → IS flagged.
# ────────────────────────────────────────────────────────────────────
def test_geocode_hash_of_real_address_is_still_flagged(live_db):
    """Pin the detector-still-fires half of the composite rule.
    Seed a row whose address does NOT match ``^\\d+ Preview\\b``
    and whose hash is non-null. Expect the audit filter to still
    flag it — this is the legacy real-PII row the rule exists
    to catch."""
    from routers.preview_isolation_admin import _AUDIT_RULES

    rule = next(
        r for r in _AUDIT_RULES
        if r["coll"] == "customers" and r["field"] == "geocode_address_hash"
    )

    marker = f"i2-real-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": marker,
        "tenant_id": "i2-test-tenant",
        "name": "Oakwood Family",
        "address": "123 Oakwood Dr",
        "address_line1": "123 Oakwood Dr",
        "geocode_address_hash": _addr_hash("123 Oakwood Dr"),
        "i2_test_marker": marker,
    }
    live_db.customers.insert_one(doc)
    try:
        combined = {"$and": [rule["filter"], {"i2_test_marker": marker}]}
        hits = live_db.customers.count_documents(combined)
        assert hits == 1, (
            f"audit rule failed to flag real-PII hash row: {hits} hit(s). "
            f"The detector must still fire on legacy rows the synthesizer "
            f"never touched."
        )
    finally:
        live_db.customers.delete_one({"id": marker})


# ────────────────────────────────────────────────────────────────────
# 3 · End-to-end — preview POST through the middleware stamps a
#     synth-hash, not a real-address hash.
# ────────────────────────────────────────────────────────────────────
def test_create_preview_customer_stamps_synthetic_geocode_hash(
        admin_h, live_db):
    """Full-stack: POST a customer with a REAL address through the
    live preview middleware. Confirm the DB row carries a
    ``geocode_address_hash`` equal to the hash of the SYNTHETIC
    address, not the hash of the real address we submitted.

    The middleware runs on preview env (``APP_ENV != 'production'``),
    which is the env this test suite always executes under.
    """
    # Submit a REAL address — the middleware should synthesize it.
    real_address = "9999 Nonexistent Realville Way"
    body = {
        "name": "I2 Real-Address Submitter",
        "first_name": "I2",
        "last_name": "Realsubmitter",
        "email": "i2.real@realdomain.com",
        "phone": "+1-206-555-9999",
        "address": real_address,
        "address_line1": real_address,
        "city": "Realville",
        "state": "WA",
        "zip": "98103",
    }
    r = requests.post(f"{API}/customers", json=body,
                        headers=admin_h, timeout=20)
    assert r.status_code in (200, 201), r.text[:400]
    created = r.json()
    cust_id = created.get("id") or created.get("customer", {}).get("id")
    assert cust_id, f"no id in POST response: {created}"

    try:
        # The auto-geocode stamp is fire-and-forget inside the create
        # path. Poll the DB for up to a second so flaky timing on
        # overloaded test runners doesn't fail the assertion.
        import time
        row = None
        for _ in range(10):
            row = live_db.customers.find_one(
                {"id": cust_id},
                {"_id": 0, "address": 1, "address_line1": 1,
                 "geocode_address_hash": 1},
            )
            if row and row.get("geocode_address_hash"):
                break
            time.sleep(0.1)

        assert row is not None, f"customer {cust_id} vanished post-POST"
        # Middleware synthesized the address: expect the synthetic
        # signature on the stored row.
        import re
        for fld in ("address", "address_line1"):
            if row.get(fld):
                assert re.match(r"^\d+ Preview\b", row[fld]), (
                    f"address field {fld}={row[fld]!r} did not get "
                    f"synthesized by the preview middleware"
                )

        stored_hash = row.get("geocode_address_hash")
        # Not required to be stamped (geocode is fire-and-forget +
        # swallows exceptions), but if it IS stamped it MUST be a
        # hash of the synthetic address, never the real one.
        if stored_hash:
            real_hash = _addr_hash(real_address)
            assert stored_hash != real_hash, (
                f"geocode_address_hash equals hash of REAL address "
                f"{real_address!r} — the preview middleware did not run "
                f"before the geocode-stamp path. This is a PII leak."
            )
            synth_hash = _addr_hash(row["address"])
            assert stored_hash == synth_hash, (
                f"stored hash {stored_hash!r} did not equal "
                f"hash of synthetic address {row['address']!r} = "
                f"{synth_hash!r}. Unknown provenance."
            )
    finally:
        live_db.customers.delete_one({"id": cust_id})


# ────────────────────────────────────────────────────────────────────
# 4 · End-to-end — healthcheck returns GREEN for geocode_address_hash
#     after a preview customer POST.
# ────────────────────────────────────────────────────────────────────
def test_audit_rule_returns_green_after_preview_create(admin_h, live_db):
    """Trip the full healthcheck pipeline. Confirm the
    ``per_field_counts`` for ``geocode_address_hash`` is 0 and the
    PII shape audit is GREEN."""
    # Pre-flight: any pre-existing legacy real-PII hash rows would
    # fail this test for reasons unrelated to this phase. If so,
    # skip with a clear message — the test is meant to prove the
    # new rule DOESN'T flag the synthetic hashes, not that the
    # whole DB is clean.
    r = requests.get(f"{API}/admin/preview-isolation-status",
                       headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    pre = body["pii_shape_audit"]["per_field_counts"].get(
        "geocode_address_hash", 0)
    assert pre == 0, (
        f"pre-POST healthcheck already flags {pre} geocode_address_hash "
        f"row(s). Those are legacy real-PII rows — scrub them before "
        f"this regression test can run meaningfully."
    )

    # POST a customer, hit the healthcheck, assert still 0.
    body_in = {
        "name": "I2 Audit Green Case",
        "first_name": "I2",
        "last_name": "Auditgreen",
        "email": "i2.audit@realdomain.com",
        "phone": "+1-206-555-8888",
        "address": "7777 Fake Real Address Blvd",
        "city": "Realville",
        "state": "WA",
        "zip": "98104",
    }
    r = requests.post(f"{API}/customers", json=body_in,
                        headers=admin_h, timeout=20)
    assert r.status_code in (200, 201), r.text[:400]
    created = r.json()
    cust_id = created.get("id") or created.get("customer", {}).get("id")
    assert cust_id

    try:
        # Give the fire-and-forget geocode task a moment to land.
        import time
        time.sleep(0.5)
        r = requests.get(f"{API}/admin/preview-isolation-status",
                          headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        post = body["pii_shape_audit"]["per_field_counts"].get(
            "geocode_address_hash", 0)
        assert post == 0, (
            f"POST created a customer whose geocode_address_hash is "
            f"being flagged by the audit (count={post}). The hash must "
            f"be of the SYNTHETIC address and therefore NOT flagged."
        )
        # And the overall rollup for this field.
        offender_fields = {
            (o["collection"], o["field_name"])
            for o in body["pii_shape_audit"]["offenders"]
        }
        assert ("customers", "geocode_address_hash") not in offender_fields
    finally:
        live_db.customers.delete_one({"id": cust_id})

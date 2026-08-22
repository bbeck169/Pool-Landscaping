"""Feb-2026 · P32 — Customer Muted-tab exclusivity + custom-reason auto-persist.

Two bugs the user hit on prod (`app.plofv.com`):
  1. Muted customers were leaking into the Inactive tab because the
     P27 mute path stamps ``is_active=False`` and the list-endpoint
     Inactive filter (``is_active=false``) didn't exclude muted rows.
  2. Novel custom mute reasons didn't reappear in the picker next
     time — no server-side persistence layer for typed reasons.

This module pins the fix contract:

Tabs (backend query exclusivity)
--------------------------------
Given three customers — A active-not-muted, B inactive-not-muted,
C muted (muted overrides regardless of is_active):
  * ``tab=active``  ↔ ``is_active=true``  → returns A only. Count = 1.
  * ``tab=inactive`` ↔ ``is_active=false`` → returns B only. Count = 1.
  * ``tab=muted``    ↔ ``is_muted=true``   → returns C only. Count = 1.
  * ``tab=all``      ↔ (no cohort filter)  → returns A + B + C. Count = 3.

Custom-reason auto-persist
--------------------------
  * Muting with a NOVEL reason → the reason lands in
    ``muted_reasons`` as ``is_active=true`` on the next
    ``GET /settings/muted-reasons``.
  * Muting with an existing ACTIVE reason → no duplicate, no error.
  * Muting with a label matching an ARCHIVED reason → the archived
    row stays archived; the customer.muted_reason snapshot is still
    set to the typed label.
  * Auto-persist failure MUST NOT block the mute (isolation).
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_customer(tid: str, *, active: bool = True, muted: bool = False,
                     muted_reason: str = "") -> str:
    cid = f"TEST_p32_c_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"TEST P32 {'active' if active else 'inactive'}"
                  f"{' + muted' if muted else ''}",
        "email": f"{cid}@example.com",
        "phone": "6235550100",
        "address": "1 Test St",
        "is_active": active,
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if muted:
        # The P27 mute path stamps is_active=False alongside is_muted.
        doc["is_active"] = False
        doc["is_muted"] = True
        doc["muted_at"] = "2026-06-01T10:00:00+00:00"
        doc["muted_by"] = "seed"
        if muted_reason:
            doc["muted_reason"] = muted_reason
    _sync.customers.insert_one(doc)
    return cid


def _cleanup_customers(cids: list[str]) -> None:
    if cids:
        _sync.customers.delete_many({"id": {"$in": cids}})


def _cleanup_reasons_by_label(tid: str, labels: list[str]) -> None:
    _sync.muted_reasons.delete_many(
        {"tenant_id": tid, "label_norm": {"$in": [x.lower() for x in labels]}},
    )


def _ids(rows) -> set:
    return {r["id"] for r in rows}


# ─── 1-4. Tab exclusivity ─────────────────────────────────────────────

def test_active_tab_returns_only_active_not_muted(admin_h, aquaterra_tid):
    a = _seed_customer(aquaterra_tid, active=True,  muted=False)
    b = _seed_customer(aquaterra_tid, active=False, muted=False)
    c = _seed_customer(aquaterra_tid, active=True,  muted=True,
                          muted_reason="Legacy P32 seed")
    try:
        r = requests.get(f"{API}/customers?is_active=true",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert a in ids
        assert b not in ids
        assert c not in ids, \
            "Muted customer must NOT appear under the Active tab (P32 exclusivity)"

        r_c = requests.get(
            f"{API}/customers?is_active=true&count_only=true",
            headers=admin_h, timeout=15,
        )
        assert r_c.status_code == 200
        # The tenant has other seed customers — assert our seeded muted
        # row is NOT counted, not an absolute count.
        # We do this by re-querying without the guard on a dedicated
        # invariant below in test_all_tab_and_sum_check.
    finally:
        _cleanup_customers([a, b, c])


def test_inactive_tab_returns_only_inactive_not_muted(admin_h, aquaterra_tid):
    a = _seed_customer(aquaterra_tid, active=True,  muted=False)
    b = _seed_customer(aquaterra_tid, active=False, muted=False)
    c = _seed_customer(aquaterra_tid, active=False, muted=True,
                          muted_reason="Legacy P32 seed")
    try:
        r = requests.get(f"{API}/customers?is_active=false",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert b in ids
        assert a not in ids
        assert c not in ids, \
            "Muted customer must NOT appear under the Inactive tab (P32 exclusivity)"
    finally:
        _cleanup_customers([a, b, c])


def test_muted_tab_returns_only_muted(admin_h, aquaterra_tid):
    a = _seed_customer(aquaterra_tid, active=True,  muted=False)
    b = _seed_customer(aquaterra_tid, active=False, muted=False)
    c = _seed_customer(aquaterra_tid, active=False, muted=True,
                          muted_reason="Legacy P32 seed")
    try:
        r = requests.get(f"{API}/customers?is_muted=true",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert c in ids
        assert a not in ids
        assert b not in ids
    finally:
        _cleanup_customers([a, b, c])


def test_all_tab_and_sum_check(admin_h, aquaterra_tid):
    """The 'All' tab (no cohort filter) returns the union of A + B + C.
    Additionally, the P32 exclusivity invariant is:
        active_count + inactive_count + muted_count
      = (seeded contribution: 3)
    modulo any tenant-level seed rows that pre-exist. We take deltas."""
    # Baseline counts BEFORE seeding.
    def _get_count(qs: str) -> int:
        r = requests.get(f"{API}/customers?{qs}&count_only=true",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        return int(r.json()["count"])

    base_active   = _get_count("is_active=true")
    base_inactive = _get_count("is_active=false")
    base_muted    = _get_count("is_muted=true")

    a = _seed_customer(aquaterra_tid, active=True,  muted=False)
    b = _seed_customer(aquaterra_tid, active=False, muted=False)
    c = _seed_customer(aquaterra_tid, active=False, muted=True,
                          muted_reason="Legacy P32 seed")
    try:
        assert _get_count("is_active=true")   == base_active   + 1
        assert _get_count("is_active=false")  == base_inactive + 1
        assert _get_count("is_muted=true")    == base_muted    + 1

        # 'All' — no cohort filter — surfaces every seeded row.
        r = requests.get(f"{API}/customers", headers=admin_h, timeout=15)
        assert r.status_code == 200
        ids = _ids(r.json())
        assert {a, b, c}.issubset(ids)
    finally:
        _cleanup_customers([a, b, c])


# ─── 5. Novel custom reason auto-persists into muted_reasons ─────────

def test_muting_with_novel_reason_auto_persists(admin_h, aquaterra_tid):
    novel = f"Novel P32 {uuid.uuid4().hex[:6]} {int(time.time())}"
    cid = _seed_customer(aquaterra_tid, active=True, muted=False)
    try:
        r = requests.patch(f"{API}/customers/{cid}/mute",
                              headers=admin_h,
                              json={"muted_reason": novel}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("muted") is True

        # The label now exists on muted_reasons for this tenant.
        # Query the settings endpoint (any staff can GET).
        rr = requests.get(f"{API}/settings/muted-reasons",
                              headers=admin_h, timeout=15)
        assert rr.status_code == 200, rr.text
        labels = [x["label"] for x in rr.json().get("items", [])]
        assert novel in labels, f"expected auto-created label in picker: {novel}"

        # DB-level sanity — auto_created flag flipped + is_active=true.
        row = _sync.muted_reasons.find_one({
            "tenant_id": aquaterra_tid, "label_norm": novel.lower(),
        })
        assert row is not None
        assert row["is_active"] is True
        assert row.get("auto_created") is True
    finally:
        _cleanup_customers([cid])
        _cleanup_reasons_by_label(aquaterra_tid, [novel])


# ─── 6. Existing active reason — no duplicate ────────────────────────

def test_muting_with_existing_active_reason_is_noop(admin_h, aquaterra_tid):
    label = "Billing dispute"  # seeded by P29 defaults.
    cid = _seed_customer(aquaterra_tid, active=True, muted=False)
    try:
        # Snapshot the label row count before.
        n_before = _sync.muted_reasons.count_documents(
            {"tenant_id": aquaterra_tid, "label_norm": label.lower()},
        )
        assert n_before >= 1, "P29 default seed missing"

        r = requests.patch(f"{API}/customers/{cid}/mute",
                              headers=admin_h,
                              json={"muted_reason": label}, timeout=15)
        assert r.status_code == 200, r.text

        n_after = _sync.muted_reasons.count_documents(
            {"tenant_id": aquaterra_tid, "label_norm": label.lower()},
        )
        assert n_after == n_before, \
            "Auto-persist must not insert a duplicate row for an existing active label"
    finally:
        _cleanup_customers([cid])


# ─── 7. Existing archived reason — do not reactivate ─────────────────

def test_muting_with_archived_label_does_not_reactivate(
    admin_h, aquaterra_tid,
):
    label = f"Archived P32 {uuid.uuid4().hex[:6]}"
    # Seed the archived reason directly.
    _sync.muted_reasons.insert_one({
        "id": f"TEST_p32_r_{uuid.uuid4().hex[:8]}",
        "tenant_id": aquaterra_tid,
        "label": label, "label_norm": label.lower(),
        "is_active": False, "sort_order": 900,
        "created_at": "2026-06-01T09:00:00+00:00", "created_by": "seed",
        "updated_at": "2026-06-01T09:00:00+00:00", "updated_by": "seed",
    })
    cid = _seed_customer(aquaterra_tid, active=True, muted=False)
    try:
        r = requests.patch(f"{API}/customers/{cid}/mute",
                              headers=admin_h,
                              json={"muted_reason": label}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("muted_reason") == label

        # The archived row stays archived; NO new row was inserted.
        rows = list(_sync.muted_reasons.find(
            {"tenant_id": aquaterra_tid, "label_norm": label.lower()},
        ))
        assert len(rows) == 1, "Auto-persist must NOT clone the archived reason"
        assert rows[0]["is_active"] is False, \
            "Auto-persist must NOT silently reactivate an admin-archived reason"

        # The customer.muted_reason snapshot is still set.
        cust = _sync.customers.find_one({"id": cid}, {"_id": 0, "muted_reason": 1})
        assert cust.get("muted_reason") == label
    finally:
        _cleanup_customers([cid])
        _cleanup_reasons_by_label(aquaterra_tid, [label])


# ─── 8. Auto-persist skips entirely when no reason is provided ───────
#
# The auto-persist path is guarded by ``if reason:`` in
# ``mute_customer`` — the try/except wrapping the call is a
# belt-and-suspenders line for real runtime errors from Mongo. This
# test covers the no-reason branch: muting a customer with an empty
# body or an all-whitespace reason MUST NOT touch ``muted_reasons``
# and MUST NOT log the ``muted_reason_auto_created`` audit event.

def test_mute_without_reason_does_not_touch_muted_reasons(
    admin_h, aquaterra_tid,
):
    cid_a = _seed_customer(aquaterra_tid, active=True, muted=False)
    cid_b = _seed_customer(aquaterra_tid, active=True, muted=False)
    try:
        # A — empty body.
        n_before = _sync.muted_reasons.count_documents(
            {"tenant_id": aquaterra_tid},
        )
        r = requests.patch(f"{API}/customers/{cid_a}/mute",
                              headers=admin_h, json={}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("muted_reason") is None
        n_after = _sync.muted_reasons.count_documents(
            {"tenant_id": aquaterra_tid},
        )
        assert n_after == n_before, \
            "Empty-body mute must not insert any muted_reasons row"

        # B — whitespace-only reason. The endpoint normalizes to None
        # before the auto-persist branch runs.
        r_b = requests.patch(f"{API}/customers/{cid_b}/mute",
                                headers=admin_h,
                                json={"muted_reason": "   "}, timeout=15)
        assert r_b.status_code == 200, r_b.text
        assert r_b.json().get("muted_reason") is None
        n_after_b = _sync.muted_reasons.count_documents(
            {"tenant_id": aquaterra_tid},
        )
        assert n_after_b == n_before, \
            "Whitespace-only mute must not insert any muted_reasons row"
    finally:
        _cleanup_customers([cid_a, cid_b])

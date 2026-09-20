"""Phase K49 · Feb-2026 — Customers list Last-Name-A→Z sort.

Coverage:
  1. ``GET /api/customers?sort=last_name_asc`` returns rows ordered by
     ``last_name`` (case-insensitive) with ``first_name`` as the tie-
     breaker.
  2. Nulls-last — a customer whose ``last_name`` is missing/blank
     lands at the END of the list (not at the front).
  3. Fallback derivation — when a doc has ``name`` but no
     ``last_name`` field, the sort key is derived from the substring
     AFTER the LAST space of ``name`` (``Jane Doe`` → ``Doe``,
     ``Cher`` → ``Cher``).
  4. Unknown sort values fall back to ``created_desc``.

Fixture seeds 6 well-known customers into the existing admin tenant,
tags each row with a unique ``k49_seed_marker`` field so the response
can be filtered exclusively to those docs, then asserts the RELATIVE
ordering.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"login skipped for {email}: {r.status_code}")
    return r.json()["access_token"]


def _admin_ctx() -> dict:
    tok = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {tok}"},
        "tenant_id": me["tenant_id"],
    }


@pytest.fixture
def k49_seed():
    """Seed 6 well-known customers into the admin tenant, filterable
    by the ``k49_seed_marker`` field, and tear them down on exit."""
    ctx = _admin_ctx()
    tenant_id = ctx["tenant_id"]
    marker = f"k49-{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat()
    # Fixture names are ordinary — the sort key comes from
    # ``last_name`` (or fallback from ``name``). We DO NOT embed the
    # marker into the sort surface; instead a dedicated
    # ``k49_seed_marker`` field lets us slice the response.
    fixtures = [
        # 1. Standard first+last — should land at position 2 (Adams).
        {"id": str(uuid.uuid4()),
          "name": "Zed Adams", "first_name": "Zed", "last_name": "Adams"},
        # 2. Single-word ``name`` only — fallback last-space token
        # rule. Name splits to ["cher"] → sort key "cher".
        {"id": str(uuid.uuid4()), "name": "Cher"},
        # 3. Nulls-last — no derivable last name.
        {"id": str(uuid.uuid4()), "name": "",
          "first_name": "NoLastNameZ", "last_name": ""},
        # 4. Case-differing last name — should land FIRST (abbott <
        # adams, case-insensitive).
        {"id": str(uuid.uuid4()),
          "name": "Beth ABBOTT",
          "first_name": "Beth", "last_name": "ABBOTT"},
        # 5. First+last tie-breaker — same last_name as #1 (adams)
        # with an earlier first_name.
        {"id": str(uuid.uuid4()),
          "name": "Alice Adams",
          "first_name": "Alice", "last_name": "adams"},
        # 6. Multi-word ``name`` with NO last_name — derivation must
        # pick "doe" (LAST space token) so this lands between Cher
        # and NoLastName.
        {"id": str(uuid.uuid4()),
          "name": "Jane Q Doe"},
    ]
    seeded_ids: list = []
    for f in fixtures:
        _db.customers.insert_one({
            **f,
            "tenant_id": tenant_id,
            "created_at": now,
            "is_active": True,
            "k49_seed_marker": marker,
        })
        seeded_ids.append(f["id"])
    try:
        yield {
            **ctx,
            "fixtures": fixtures,
            "ids": seeded_ids,
            "marker": marker,
        }
    finally:
        _db.customers.delete_many({
            "id": {"$in": seeded_ids},
            "tenant_id": tenant_id,
        })


def _k49_rows_only(items, marker):
    ids_by_marker = {
        r["id"] for r in _db.customers.find(
            {"k49_seed_marker": marker}, {"id": 1, "_id": 0})
    }
    return [i for i in items if i.get("id") in ids_by_marker]


# ═════════════════════════════════════════════════════════════════════
# 1) Happy path — last_name_asc order + nulls-last + fallback
# ═════════════════════════════════════════════════════════════════════
def test_k49_last_name_asc_orders_correctly(k49_seed):
    r = requests.get(
        f"{API}/customers?sort=last_name_asc&page=1&page_size=500",
        headers=k49_seed["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text
    envelope = r.json()
    items = envelope["items"] if isinstance(envelope, dict) else envelope
    k49_rows = _k49_rows_only(items, k49_seed["marker"])
    ordered = [
        (i.get("first_name") or "", i.get("last_name") or "",
          i.get("name") or "")
        for i in k49_rows
    ]
    # Expected relative order among K49 rows:
    #   1. Beth ABBOTT (last=ABBOTT, case-insensitive first)
    #   2. Alice Adams (last=adams, first=Alice tie-break)
    #   3. Zed Adams   (last=Adams, first=Zed tie-break)
    #   4. Cher        (fallback: single-token name → "cher")
    #   5. Jane Q Doe  (fallback: LAST space of name → "doe")
    #   6. NoLastNameZ (nulls-last)
    assert len(k49_rows) == 6, (
        f"expected 6 K49 rows in response, got {len(k49_rows)}: "
        f"{ordered}"
    )
    assert ordered[0][0] == "Beth", (
        f"row0 should be Beth ABBOTT: {ordered}"
    )
    assert ordered[0][1].lower() == "abbott"
    assert ordered[1][0] == "Alice" and ordered[1][1].lower() == "adams", (
        f"row1 should be Alice Adams (first-name tiebreak): {ordered}"
    )
    assert ordered[2][0] == "Zed" and ordered[2][1].lower() == "adams", (
        f"row2 should be Zed Adams (later first-name tiebreak): {ordered}"
    )
    # Cher — single-token fallback.
    assert ordered[3][2] == "Cher", (
        f"row3 should be Cher (single-token fallback): {ordered}"
    )
    # Jane Q Doe — multi-word fallback picks LAST space.
    assert ordered[4][2] == "Jane Q Doe", (
        f"row4 should be Jane Q Doe (LAST-space fallback): {ordered}"
    )
    # NoLastName — nulls-last.
    assert ordered[5][0] == "NoLastNameZ", (
        f"row5 should be NoLastNameZ (nulls-last): {ordered}"
    )


# ═════════════════════════════════════════════════════════════════════
# 2) Unknown sort values fall back to created_desc (regression guard)
# ═════════════════════════════════════════════════════════════════════
def test_k49_unknown_sort_falls_back_to_default():
    ctx = _admin_ctx()
    r = requests.get(
        f"{API}/customers?sort=this_is_not_a_real_sort_key"
        f"&page=1&page_size=5",
        headers=ctx["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════
# 3) sort=last_name_asc still supports bare-array (no pagination)
# ═════════════════════════════════════════════════════════════════════
def test_k49_last_name_asc_bare_array_shape():
    ctx = _admin_ctx()
    r = requests.get(
        f"{API}/customers?sort=last_name_asc",
        headers=ctx["headers"], timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list), f"expected bare list, got {type(body)}"

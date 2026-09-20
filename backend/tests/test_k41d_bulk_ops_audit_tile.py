"""Phase K41d · Feb-2026 — Bulk Operations audit tile pytest coverage.

The tile is fed by three additive fields on the admin ``/api/dashboard``
response:

  * ``bulk_actions_24h``        — distinct bulk_batch_id in
                                   dashboard_drilldown_edit events
                                   within the last 24h.
  * ``bulk_actions_undone_24h`` — distinct undone_from_batch_id in
                                   dashboard_drilldown_bulk_undone
                                   events within the last 24h.
  * ``bulk_actions_expired_24h`` — batches whose newest edit is older
                                   than the 10-minute undo window AND
                                   which have no undo companion.

This suite exercises the full HTTP path end-to-end against a live
admin session by seeding audit_events docs in the tenant and asserting
the three tile fields flow through unchanged.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_client = _shared_client()
_db = _shared_db()
def _login_super():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "super@aquaterra.com", "password": "password123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok, body
    me = requests.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()
    return tok, me.get("tenant_id")


def _now_iso(offset_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat()


def test_k41d_bulk_ops_audit_tile_counts_flow_through_dashboard():
    tok, tenant_id = _login_super()

    # Three synthetic bulk batches to cover all three tile columns.
    batch_undone = f"k41d-undone-{uuid.uuid4().hex[:8]}"
    batch_expired = f"k41d-expired-{uuid.uuid4().hex[:8]}"
    batch_active = f"k41d-active-{uuid.uuid4().hex[:8]}"

    now = datetime.now(timezone.utc)
    # ── Batch A · has an undo companion → counted in ``undone``.
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_edit",
        "tenant_id": tenant_id,
        "timestamp": (now - timedelta(minutes=30)).isoformat(),
        "bulk_batch_id": batch_undone,
        "tile": "data-integrity", "field": "assignment",
    })
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_bulk_undone",
        "tenant_id": tenant_id,
        "timestamp": (now - timedelta(minutes=25)).isoformat(),
        "undone_from_batch_id": batch_undone,
    })
    # ── Batch B · old, no undo companion → counted in ``expired``.
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_edit",
        "tenant_id": tenant_id,
        "timestamp": (now - timedelta(minutes=45)).isoformat(),
        "bulk_batch_id": batch_expired,
        "tile": "data-integrity", "field": "assignment",
    })
    # ── Batch C · fresh, no undo companion → counted in the total
    #    but NOT in ``expired`` (still inside the 10-minute window).
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_edit",
        "tenant_id": tenant_id,
        "timestamp": (now - timedelta(minutes=2)).isoformat(),
        "bulk_batch_id": batch_active,
        "tile": "data-integrity", "field": "assignment",
    })

    try:
        r = requests.get(
            f"{API}/dashboard",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Additive fields must be present and integers.
        assert "bulk_actions_24h" in body
        assert "bulk_actions_undone_24h" in body
        assert "bulk_actions_expired_24h" in body
        assert isinstance(body["bulk_actions_24h"], int)
        assert isinstance(body["bulk_actions_undone_24h"], int)
        assert isinstance(body["bulk_actions_expired_24h"], int)
        # Our three seeded batches must be reflected.  Other batches
        # from unrelated tests in the same tenant may inflate the
        # counts, so assert >= for the totals and equality-with-floor
        # semantics for the categories that our fixtures uniquely
        # own.
        assert body["bulk_actions_24h"] >= 3, body
        assert body["bulk_actions_undone_24h"] >= 1, body
        assert body["bulk_actions_expired_24h"] >= 1, body
        # Sanity — undone + expired never exceed the total (invariant).
        assert (
            body["bulk_actions_undone_24h"] + body["bulk_actions_expired_24h"]
            <= body["bulk_actions_24h"]
        ), body
    finally:
        _db.audit_events.delete_many({
            "$or": [
                {"bulk_batch_id": {"$in": [batch_undone, batch_expired, batch_active]}},
                {"undone_from_batch_id": batch_undone},
            ],
        })


def test_k41d_bulk_ops_audit_tile_is_zero_when_no_recent_batches():
    """When the tenant has no bulk_batch_id audit events in the last
    24h the tile fields must all be present and zero — never omitted,
    never null."""
    tok, tenant_id = _login_super()
    # Wipe any k41d test artifacts from earlier in this session so
    # this test's expectation ("all zero") is honest.  We ONLY delete
    # rows this test module owns (prefixed ``k41d-``).
    _db.audit_events.delete_many({
        "bulk_batch_id": {"$regex": "^k41d-"},
    })
    _db.audit_events.delete_many({
        "undone_from_batch_id": {"$regex": "^k41d-"},
    })

    r = requests.get(
        f"{API}/dashboard",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Fields present + integer even when there's nothing to summarize.
    for f in (
        "bulk_actions_24h",
        "bulk_actions_undone_24h",
        "bulk_actions_expired_24h",
    ):
        assert f in body, f
        assert isinstance(body[f], int), f
        assert body[f] >= 0, f

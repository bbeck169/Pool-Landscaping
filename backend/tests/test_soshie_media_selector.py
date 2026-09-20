"""Phase S1.5 · AM2 — Soshie media selector tests.

Covers:
* Hybrid — real ``service_reports.photos`` win when available.
* AI fallback — empty photo pool returns ``source="none"`` so the
  caller falls through to the AI generation path.
* Consent gating — customer with ``media_consent=False`` filters the
  photo out.
* Service-type filter — photos on jobs matching the target service.
* Private photo skipped.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = _shared_client()
_db = _shared_db()
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(days=days)).isoformat()


def _cleanup(tid: str) -> None:
    _db.service_reports.delete_many({"tenant_id": tid})
    _db.jobs.delete_many({"tenant_id": tid})
    _db.customers.delete_many({"tenant_id": tid})


def _seed_customer(tid: str, cid: str, consent: bool = True):
    _db.customers.insert_one({
        "id": cid, "tenant_id": tid, "media_consent": consent,
        "name": "Test Cx",
    })


def _seed_job(tid: str, jid: str, cid: str,
                    service_type: str = "pool"):
    _db.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": cid,
        "service_type": service_type,
        "job_type": service_type,
        "updated_at": _iso_days_ago(1),
        "photos": [],
    })


def _seed_report(tid: str, rid: str, jid: str, photos, days_ago: float = 3):
    _db.service_reports.insert_one({
        "id": rid, "tenant_id": tid, "job_id": jid,
        "photos": photos,
        "submitted_at": _iso_days_ago(days_ago),
    })


# ═════════════════════════════════════════════════════════════════════
# 1 · Job photo wins when available
# ═════════════════════════════════════════════════════════════════════
def test_hybrid_prefers_job_photo():
    from services.soshie.media_selector import select_media_for_post

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    cid = f"TEST-cx-{uuid.uuid4().hex[:6]}"
    jid = f"TEST-j-{uuid.uuid4().hex[:6]}"
    rid = f"TEST-r-{uuid.uuid4().hex[:6]}"
    _seed_customer(tid, cid, consent=True)
    _seed_job(tid, jid, cid, service_type="pool")
    _seed_report(tid, rid, jid, photos=[
        {"id": "p1", "url": "https://ex.test/pool.jpg",
          "width": 1920, "height": 1080,
          "created_at": _iso_days_ago(2)},
    ])
    try:
        sel = _run(select_media_for_post(
            tenant_id=tid,
            post_context={"service_type": "pool"},
        ))
        assert sel["source"] == "job_photo"
        assert sel["url"] == "https://ex.test/pool.jpg"
        assert sel["metadata"]["service_report_id"] == rid
        assert sel["metadata"]["job_id"] == jid
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 2 · No eligible photos → source=none (AI fallback trigger)
# ═════════════════════════════════════════════════════════════════════
def test_empty_pool_returns_source_none():
    from services.soshie.media_selector import select_media_for_post

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    try:
        sel = _run(select_media_for_post(
            tenant_id=tid,
            post_context={"service_type": "pool"},
        ))
        assert sel["source"] == "none"
        assert sel["url"] is None
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 3 · Consent gate — media_consent=False filters photos
# ═════════════════════════════════════════════════════════════════════
def test_customer_no_consent_filters_photo():
    from services.soshie.media_selector import select_media_for_post

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    cid = f"TEST-cx-{uuid.uuid4().hex[:6]}"
    jid = f"TEST-j-{uuid.uuid4().hex[:6]}"
    rid = f"TEST-r-{uuid.uuid4().hex[:6]}"
    _seed_customer(tid, cid, consent=False)   # explicit block
    _seed_job(tid, jid, cid, service_type="pool")
    _seed_report(tid, rid, jid, photos=[
        {"id": "p1", "url": "https://ex.test/no-consent.jpg",
          "width": 1024, "height": 768},
    ])
    try:
        sel = _run(select_media_for_post(
            tenant_id=tid,
            post_context={"service_type": "pool"},
        ))
        assert sel["source"] == "none", \
            f"consent=False must filter photo — got {sel}"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 4 · Service-type filter — mismatched type filtered out
# ═════════════════════════════════════════════════════════════════════
def test_service_type_filter():
    from services.soshie.media_selector import select_media_for_post

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    cid = f"TEST-cx-{uuid.uuid4().hex[:6]}"
    jid = f"TEST-j-{uuid.uuid4().hex[:6]}"
    rid = f"TEST-r-{uuid.uuid4().hex[:6]}"
    _seed_customer(tid, cid, consent=True)
    _seed_job(tid, jid, cid, service_type="landscape")
    _seed_report(tid, rid, jid, photos=[
        {"id": "p1", "url": "https://ex.test/land.jpg",
          "width": 1024, "height": 768},
    ])
    try:
        # Requesting "pool" but only "landscape" job exists.
        sel = _run(select_media_for_post(
            tenant_id=tid,
            post_context={"service_type": "pool"},
        ))
        assert sel["source"] == "none"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 5 · private=True photo skipped
# ═════════════════════════════════════════════════════════════════════
def test_private_photo_skipped():
    from services.soshie.media_selector import select_media_for_post

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    cid = f"TEST-cx-{uuid.uuid4().hex[:6]}"
    jid = f"TEST-j-{uuid.uuid4().hex[:6]}"
    rid = f"TEST-r-{uuid.uuid4().hex[:6]}"
    _seed_customer(tid, cid, consent=True)
    _seed_job(tid, jid, cid, service_type="pool")
    _seed_report(tid, rid, jid, photos=[
        {"id": "p1", "url": "https://ex.test/private.jpg",
          "private": True},
        {"id": "p2", "url": "https://ex.test/public.jpg",
          "private": False, "width": 800, "height": 600},
    ])
    try:
        sel = _run(select_media_for_post(
            tenant_id=tid, post_context={"service_type": "pool"},
        ))
        assert sel["source"] == "job_photo"
        assert sel["url"] == "https://ex.test/public.jpg"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 6 · Legacy jobs.photos[] used when no service_reports rows
# ═════════════════════════════════════════════════════════════════════
def test_legacy_job_photos_used_when_no_reports():
    from services.soshie.media_selector import select_media_for_post

    tid = f"TEST-t-{uuid.uuid4().hex[:8]}"
    cid = f"TEST-cx-{uuid.uuid4().hex[:6]}"
    jid = f"TEST-j-{uuid.uuid4().hex[:6]}"
    _seed_customer(tid, cid, consent=True)
    _db.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "service_type": "pool", "job_type": "pool",
        "updated_at": _iso_days_ago(2),
        "photos": [
            {"id": "leg1", "url": "https://ex.test/legacy.jpg",
              "width": 1024, "height": 768},
        ],
    })
    try:
        sel = _run(select_media_for_post(
            tenant_id=tid, post_context={"service_type": "pool"},
        ))
        assert sel["source"] == "job_photo"
        assert sel["url"] == "https://ex.test/legacy.jpg"
    finally:
        _cleanup(tid)

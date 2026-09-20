"""Feb-2026 · GET /api/jobs slim-photos ship (backend regression).

Coverage:
  1. GET /api/jobs (default) drops the full ``photos`` array and exposes
     only ``photo_count`` (int) + ``photo_ids`` (list[str]).
  2. GET /api/jobs/{id} (single-job detail) is unchanged — still emits
     the full ``photos`` array with per-photo ``data`` payload.
  3. GET /api/jobs?include_photos=true opts back into the pre-slim
     payload (full ``photos`` preserved).
  4. Response size for a seeded 10-photo job is measurably smaller in
     the slim variant than the ``include_photos=true`` variant.

Runs against the live backend on the current preview host (same pattern
as ``test_pb3_profit_report.py``) — no mocking of the aggregation
pipeline, so we cover the real ``list_jobs`` code path end-to-end.
"""
from __future__ import annotations

import os
import sys
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


_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str = "admin@aquaterra.com") -> str:
    if _CACHE.get(email):
        return _CACHE[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    _CACHE[email] = r.json()["access_token"]
    return _CACHE[email]


def _hdr(email: str = "admin@aquaterra.com") -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _tenant_of(email: str) -> str:
    u = _db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    assert u, f"seed user {email} missing"
    return u["tenant_id"]


_TID = _tenant_of("admin@aquaterra.com")


@pytest.fixture(scope="module")
def photo_job():
    """Seed one ``TEST_``-prefixed job with 10 embedded photos.

    Cleaned up by the session-scoped ``_purge_test_data`` hook in
    ``conftest.py`` (title starts with ``TEST_``).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    jid = f"slim-photo-{uuid.uuid4()}"
    photos = [
        {
            "id": f"ph-{i}-{uuid.uuid4()}",
            # Roughly 4 KB base64 blob per photo → 10 photos ≈ 40 KB
            # of full-photos overhead when the caller opts in.
            "data": ("x" * 3072) + f"::photo::{i}",
            "label": f"photo-{i}",
            "created_at": now_iso,
        }
        for i in range(10)
    ]
    doc = {
        "id": jid,
        "tenant_id": _TID,
        "title": f"TEST_slim_photos_{jid}",
        "service_type": "pool",
        "status": "scheduled",
        "customer_id": f"slim-photo-cust-{jid}",  # unique scope for the size-bench assertion
        "photos": photos,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    _db.jobs.insert_one(doc)
    yield {
        "id": jid,
        "customer_id": doc["customer_id"],
        "photo_ids": [p["id"] for p in photos],
        "photo_count": 10,
    }
    _db.jobs.delete_one({"id": jid, "tenant_id": _TID})


def _find_row(rows: list, jid: str) -> dict | None:
    for r in rows:
        if r.get("id") == jid:
            return r
    return None


def test_list_default_drops_full_photos_emits_count_and_ids(photo_job):
    """Default ``GET /api/jobs`` MUST NOT ship ``photos`` and MUST
    ship ``photo_count`` + ``photo_ids``."""
    r = requests.get(f"{API}/jobs?limit=5000", headers=_hdr(), timeout=30)
    r.raise_for_status()
    rows = r.json()
    row = _find_row(rows, photo_job["id"])
    assert row is not None, f"seeded job {photo_job['id']} missing from list"
    # Full photos array MUST be absent on the slim response.
    assert "photos" not in row, (
        "slim-photos regression — the default list response still emits "
        "the full ``photos`` array"
    )
    # Slim surface MUST be present.
    assert row.get("photo_count") == 10, (
        f"photo_count mismatch: got {row.get('photo_count')} expected 10"
    )
    ids = row.get("photo_ids")
    assert isinstance(ids, list) and len(ids) == 10, (
        f"photo_ids missing or wrong length: {ids!r}"
    )
    assert set(ids) == set(photo_job["photo_ids"]), (
        "photo_ids do not match the seeded photo ids"
    )


def test_detail_endpoint_returns_full_photos_unchanged(photo_job):
    """``GET /api/jobs/{id}`` MUST still ship the full ``photos`` array
    with per-photo ``data`` payloads — the slim-photos ship is a
    list-only projection."""
    r = requests.get(f"{API}/jobs/{photo_job['id']}", headers=_hdr(), timeout=30)
    r.raise_for_status()
    doc = r.json()
    photos = doc.get("photos")
    assert isinstance(photos, list) and len(photos) == 10, (
        f"detail endpoint dropped photos: got {type(photos).__name__} "
        f"len={len(photos or [])}"
    )
    # Each photo carries the full metadata + base64 blob.
    for p in photos:
        assert isinstance(p, dict), f"photo entry not a dict: {p!r}"
        assert p.get("id"), "photo missing id"
        assert p.get("data"), "photo missing data (base64 blob dropped by detail)"
        assert p["data"].startswith("x" * 100), (
            "photo data appears truncated on detail endpoint"
        )


def test_list_with_include_photos_true_restores_full_payload(photo_job):
    """``GET /api/jobs?include_photos=true`` is the backward-compat
    escape hatch — callers that haven't migrated MUST still receive the
    full ``photos`` array."""
    r = requests.get(
        f"{API}/jobs?limit=5000&include_photos=true",
        headers=_hdr(),
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    row = _find_row(rows, photo_job["id"])
    assert row is not None, f"seeded job {photo_job['id']} missing from list"
    photos = row.get("photos")
    assert isinstance(photos, list) and len(photos) == 10, (
        f"include_photos=true did not restore photos: got "
        f"{type(photos).__name__} len={len(photos or [])}"
    )
    # Base64 blobs preserved verbatim.
    for p in photos:
        assert isinstance(p, dict) and p.get("data"), (
            "include_photos=true dropped photo data blob"
        )


def test_slim_response_measurably_smaller_than_full(photo_job):
    """Bench — for the seeded 10-photo job, the slim variant MUST be
    materially smaller than the ``include_photos=true`` variant.

    Scoped to ``customer_id=<seeded-unique>`` so the payload contains
    exactly the seeded row — the size delta is therefore dominated by
    the 10 photos' base64 blobs.
    """
    params_slim = {"customer_id": photo_job["customer_id"], "limit": 5}
    params_full = {
        "customer_id": photo_job["customer_id"],
        "limit": 5,
        "include_photos": "true",
    }
    r_slim = requests.get(f"{API}/jobs", params=params_slim, headers=_hdr(), timeout=30)
    r_slim.raise_for_status()
    r_full = requests.get(f"{API}/jobs", params=params_full, headers=_hdr(), timeout=30)
    r_full.raise_for_status()

    # Assert row counts match — same query, same tenant scope, only
    # the projection differs.
    rows_slim = r_slim.json()
    rows_full = r_full.json()
    assert len(rows_slim) == len(rows_full) == 1, (
        f"unexpected row counts: slim={len(rows_slim)} full={len(rows_full)} "
        f"(expected exactly the seeded row)"
    )

    size_slim = len(r_slim.content)
    size_full = len(r_full.content)
    # 10 photos × ~3 KB base64 each ≈ 30 KB of full-photos overhead.
    # Allow a 50 % tolerance to survive JSON escaping / column
    # reshuffles.
    min_delta = 15_000
    assert size_full - size_slim >= min_delta, (
        f"slim variant not measurably smaller: slim={size_slim}B "
        f"full={size_full}B delta={size_full - size_slim}B "
        f"(expected >= {min_delta}B)"
    )
    # Bench log for the diagnostic memo append-up in
    # /app/memory/DIAG_P0_MOBILE_CLOSE_JOB_SILENT.md
    print(
        f"\n[slim-photos bench] 1-job × 10-photo payload: "
        f"slim={size_slim}B  full={size_full}B  delta={size_full - size_slim}B "
        f"({(size_full - size_slim) / max(size_full, 1) * 100:.1f}% saved)"
    )


# ---------------------------------------------------------------------------
# Feb-2026 · Batch-verify follow-up · include_photos=true is a strict SUPERSET
# ---------------------------------------------------------------------------
# When the caller opts back in via ``?include_photos=true`` the response
# MUST carry all three keys — ``photos``, ``photo_count``, ``photo_ids``
# — on every row, and they MUST be internally consistent
# (``len(photos) == photo_count``, every ``photos[i].id`` present in
# ``photo_ids``). Legacy ``demo-stale-*`` rows where the underlying
# Mongo doc has no ``photos`` field at all are normalised to
# ``photos: []`` so the shape is uniform across the payload.
# ---------------------------------------------------------------------------


def test_include_photos_true_is_strict_superset_of_slim(photo_job):
    """Every row in the ``?include_photos=true`` response MUST carry
    ``photos`` + ``photo_count`` + ``photo_ids`` (never ``None``) and
    the three fields MUST be internally consistent."""
    r = requests.get(
        f"{API}/jobs",
        params={"limit": 500, "include_photos": "true"},
        headers=_hdr(),
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    assert len(rows) > 0, "no rows returned — cannot validate superset shape"

    seed = _find_row(rows, photo_job["id"])
    assert seed is not None, "seeded 10-photo job missing from list"

    for row in rows:
        rid = row.get("id", "<no-id>")
        # (a) All three keys present.
        assert "photos" in row, (
            f"{rid}: ``photos`` key absent under include_photos=true; "
            f"legacy row normalisation broken"
        )
        assert "photo_count" in row, (
            f"{rid}: ``photo_count`` key absent under include_photos=true"
        )
        assert "photo_ids" in row, (
            f"{rid}: ``photo_ids`` key absent under include_photos=true"
        )
        # (b) Never ``None`` — must be concrete list / int.
        photos = row["photos"]
        pc = row["photo_count"]
        pids = row["photo_ids"]
        assert isinstance(photos, list), (
            f"{rid}: photos is {type(photos).__name__}, expected list"
        )
        assert isinstance(pc, int), (
            f"{rid}: photo_count is {type(pc).__name__}, expected int"
        )
        assert isinstance(pids, list), (
            f"{rid}: photo_ids is {type(pids).__name__}, expected list"
        )
        # (c) Length agreement.
        assert len(photos) == pc, (
            f"{rid}: len(photos)={len(photos)} != photo_count={pc}"
        )
        # (d) photo_ids echoes photos[i].id when present.
        for i, p in enumerate(photos):
            if isinstance(p, dict) and p.get("id") is not None:
                assert str(p["id"]) in pids, (
                    f"{rid}: photos[{i}].id={p['id']!r} missing from "
                    f"photo_ids={pids!r}"
                )

    # The seeded row specifically must round-trip 10 photos + 10 ids.
    assert len(seed["photos"]) == 10
    assert seed["photo_count"] == 10
    assert len(seed["photo_ids"]) == 10
    assert set(seed["photo_ids"]) == set(photo_job["photo_ids"])


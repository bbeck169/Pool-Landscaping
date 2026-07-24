"""Feb-2026 · Phase 22 — Citation Builder pytest.

Covers:
* Seed idempotency + 50+ directories present.
* PATCH updates the tenant citation row; `submitted_at` stamps when
  transitioning to `submitted` or `live`.
* Weighted completeness score maths.
* NAP drift detection when the tenant's business_card mutates.
* Bulk mark-verified snapshots the current NAP on every listed row.

Uses the same requests-against-public-API pattern as
``test_auto_clockin_and_orphan.py``.
"""
from __future__ import annotations

import os
import uuid
import requests
import pytest
from pathlib import Path
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)
_sync_db = _sync[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else "http://localhost:8001/api"
)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    tok = _login("admin@aquaterra.com")
    return {"Authorization": f"Bearer {tok}"}


def _tech_headers():
    tok = _login("mike@aquaterra.com")
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id_for(email: str) -> str:
    u = _sync_db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


@pytest.fixture(autouse=True)
def _clear_tenant_citations():
    """Reset citations for the admin's tenant before + after each test so
    tests don't leak state through the shared seed DB. Only the ADMIN's
    tenant is touched — the citation_directories master list is left
    alone because boot re-seeds it anyway."""
    tid = _tenant_id_for("admin@aquaterra.com")
    _sync_db.tenant_citations.delete_many({"tenant_id": tid})
    _sync_db.citation_analytics_snapshots.delete_many({"tenant_id": tid})
    yield
    _sync_db.tenant_citations.delete_many({"tenant_id": tid})
    _sync_db.citation_analytics_snapshots.delete_many({"tenant_id": tid})


# ──────────────────────────────────────────────────────────────────────
# Directory seed
# ──────────────────────────────────────────────────────────────────────
def test_directories_are_seeded_with_50_plus_entries():
    r = requests.get(f"{API}/citations/directories", headers=_admin_headers(),
                      timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 50, f"Expected 50+ directories, got {body['total']}"
    slugs = {d["slug"] for d in body["directories"]}
    # Sanity: the "cornerstone" ones every local business needs.
    for slug in ("google-business-profile", "bing-places", "apple-maps",
                  "facebook-business", "yelp", "angies-list", "houzz",
                  "thumbtack", "bbb"):
        assert slug in slugs, f"seed missing {slug!r}"
    # Category grouping surfaces every expected bucket.
    for cat in ("search", "maps", "social", "local", "industry", "reviews"):
        assert cat in body["grouped"], f"missing category {cat}"


def test_directory_seed_is_idempotent():
    """Re-invoking ``run_citations_seed_and_drift`` doesn't duplicate rows."""
    # Import here so DB is available.
    import asyncio
    from routers.citations import run_citations_seed_and_drift
    n_before = _sync_db.citation_directories.count_documents({})
    asyncio.get_event_loop().run_until_complete(run_citations_seed_and_drift())
    n_after = _sync_db.citation_directories.count_documents({})
    assert n_before == n_after


def test_directories_require_admin():
    r = requests.get(f"{API}/citations/directories", headers=_tech_headers(),
                      timeout=15)
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────
# Tenant list + PATCH + mark-verified
# ──────────────────────────────────────────────────────────────────────
def _gbp_directory_id() -> str:
    d = _sync_db.citation_directories.find_one(
        {"slug": "google-business-profile"}, {"_id": 0, "id": 1},
    )
    return d["id"]


def test_tenant_list_returns_all_directories_defaulted_to_not_started():
    r = requests.get(f"{API}/citations/tenant", headers=_admin_headers(),
                      timeout=15)
    assert r.status_code == 200
    body = r.json()
    total_dirs = _sync_db.citation_directories.count_documents({})
    assert body["total"] == total_dirs
    statuses = {row["status"] for row in body["citations"]}
    assert statuses == {"not_started"}


def test_patch_updates_citation_row_and_stamps_submitted_at():
    did = _gbp_directory_id()
    r = requests.patch(
        f"{API}/citations/tenant/{did}",
        headers=_admin_headers(),
        json={"status": "live", "listing_url": "https://g.co/test",
               "notes": "claimed"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "live"
    assert body["listing_url"] == "https://g.co/test"
    assert body["notes"] == "claimed"
    # First transition to live stamps submitted_at + submitted_by_user_id.
    assert body["submitted_at"]
    assert body["submitted_by_user_id"]


def test_patch_rejects_invalid_status():
    did = _gbp_directory_id()
    r = requests.patch(
        f"{API}/citations/tenant/{did}",
        headers=_admin_headers(),
        json={"status": "totally_bogus"},
        timeout=15,
    )
    assert r.status_code == 422


def test_patch_unknown_directory_returns_404():
    r = requests.patch(
        f"{API}/citations/tenant/does-not-exist",
        headers=_admin_headers(),
        json={"status": "live"},
        timeout=15,
    )
    assert r.status_code == 404


def test_mark_verified_snapshots_current_business_card():
    did = _gbp_directory_id()
    tid = _tenant_id_for("admin@aquaterra.com")

    r = requests.post(
        f"{API}/citations/tenant/{did}/mark-verified",
        headers=_admin_headers(), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_verified_at"]
    snap = body["data_snapshot"]
    # Snapshot mirrors business_card values on the tenant.
    t = _sync_db.tenants.find_one({"id": tid},
                                    {"_id": 0, "settings": 1})
    card = ((t or {}).get("settings") or {}).get("business_card") or {}
    for k in ("company_name", "service_area", "phone", "website_url"):
        assert snap.get(k) == (card.get(k) or ""), f"snapshot mismatch on {k}"


# ──────────────────────────────────────────────────────────────────────
# Weighted completeness score
# ──────────────────────────────────────────────────────────────────────
def test_summary_weighted_completeness_correct():
    """Marking every ``weight=10`` directory ``live`` should produce a
    completeness score of ``sum(10 rows) / total_weight * 100`` — we
    verify it matches by direct maths against the seed."""
    admin_h = _admin_headers()

    dirs = list(_sync_db.citation_directories.find({}, {"_id": 0}))
    total_weight = sum(int(d.get("weight") or 0) for d in dirs)
    top_dirs = [d for d in dirs if d.get("weight") == 10]
    assert top_dirs, "expected at least one weight-10 directory"

    top_weight = sum(int(d["weight"]) for d in top_dirs)
    for d in top_dirs:
        requests.patch(f"{API}/citations/tenant/{d['id']}",
                        headers=admin_h, json={"status": "live"},
                        timeout=15).raise_for_status()

    r = requests.get(f"{API}/citations/tenant/summary",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    expected = round(top_weight / total_weight * 100.0, 1)
    assert body["weighted_completeness_score"] == expected
    assert body["live_count"] == len(top_dirs)
    assert body["nap_drift_count"] == 0


# ──────────────────────────────────────────────────────────────────────
# Bulk mark verified
# ──────────────────────────────────────────────────────────────────────
def test_bulk_mark_verified_snapshots_every_listed_directory():
    tid = _tenant_id_for("admin@aquaterra.com")
    dirs = list(_sync_db.citation_directories.find(
        {}, {"_id": 0, "id": 1, "slug": 1},
    ).limit(5))
    ids = [d["id"] for d in dirs]

    r = requests.post(
        f"{API}/citations/tenant/bulk-mark-verified",
        headers=_admin_headers(),
        json={"directory_ids": ids + ["bogus-id"]},  # bogus is silently dropped
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verified"] == len(ids)

    # Every listed row now has a data_snapshot mirroring the business_card.
    t = _sync_db.tenants.find_one({"id": tid}, {"_id": 0, "settings": 1})
    card = ((t or {}).get("settings") or {}).get("business_card") or {}
    for did in ids:
        row = _sync_db.tenant_citations.find_one(
            {"tenant_id": tid, "directory_id": did}, {"_id": 0},
        )
        assert row is not None
        snap = row.get("data_snapshot") or {}
        for k in ("company_name", "service_area", "phone", "website_url"):
            assert snap.get(k) == (card.get(k) or "")
        assert row.get("last_verified_at")


# ──────────────────────────────────────────────────────────────────────
# NAP drift detection
# ──────────────────────────────────────────────────────────────────────
def test_nap_drift_detected_when_business_card_mutates():
    """After verifying a directory + then mutating the tenant's phone,
    the drift-sweep must flag the row and demote status from ``live``
    to ``needs_update``.
    """
    import asyncio
    from routers.citations import run_citations_seed_and_drift

    did = _gbp_directory_id()
    tid = _tenant_id_for("admin@aquaterra.com")
    admin_h = _admin_headers()

    # Set status=live so the demotion path fires.
    requests.patch(f"{API}/citations/tenant/{did}", headers=admin_h,
                    json={"status": "live"}, timeout=15).raise_for_status()
    requests.post(f"{API}/citations/tenant/{did}/mark-verified",
                   headers=admin_h, timeout=15).raise_for_status()

    # Capture then mutate the phone.
    t = _sync_db.tenants.find_one({"id": tid}, {"_id": 0, "settings": 1})
    orig_phone = ((t.get("settings") or {}).get("business_card") or {}).get("phone")
    new_phone = f"555-{uuid.uuid4().hex[:6]}"
    _sync_db.tenants.update_one(
        {"id": tid},
        {"$set": {"settings.business_card.phone": new_phone}},
    )
    try:
        asyncio.get_event_loop().run_until_complete(run_citations_seed_and_drift())
        row = _sync_db.tenant_citations.find_one(
            {"tenant_id": tid, "directory_id": did}, {"_id": 0},
        )
        assert row is not None
        assert row.get("nap_drift_detected") is True
        assert row.get("status") == "needs_update"

        # Summary picks up drift.
        r = requests.get(f"{API}/citations/tenant/summary",
                          headers=admin_h, timeout=15)
        body = r.json()
        assert body["nap_drift_count"] >= 1
    finally:
        _sync_db.tenants.update_one(
            {"id": tid},
            {"$set": {"settings.business_card.phone": orig_phone or ""}},
        )


# ══════════════════════════════════════════════════════════════════════
# Yext-inspired extensions
# ══════════════════════════════════════════════════════════════════════

def test_record_analytics_persists_snapshot_and_updates_row():
    did = _gbp_directory_id()
    tid = _tenant_id_for("admin@aquaterra.com")
    r = requests.post(
        f"{API}/citations/tenant/{did}/analytics",
        headers=_admin_headers(),
        json={"impressions": 1500, "clicks": 80, "actions": 22,
               "period_start": "2026-01-01", "period_end": "2026-01-31"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot"]["impressions"] == 1500
    assert body["row"]["impressions_last_30d"] == 1500
    assert body["row"]["clicks_last_30d"] == 80
    # Snapshot persisted to DB collection.
    snap_row = _sync_db.citation_analytics_snapshots.find_one(
        {"tenant_id": tid, "directory_id": did}, {"_id": 0},
    )
    assert snap_row is not None
    assert snap_row["impressions"] == 1500


def test_analytics_history_returns_snapshots_newest_first_with_trend():
    did = _gbp_directory_id()
    h = _admin_headers()
    requests.post(f"{API}/citations/tenant/{did}/analytics", headers=h,
                   json={"impressions": 1000, "clicks": 10, "actions": 1},
                   timeout=15).raise_for_status()
    requests.post(f"{API}/citations/tenant/{did}/analytics", headers=h,
                   json={"impressions": 1500, "clicks": 22, "actions": 5},
                   timeout=15).raise_for_status()
    r = requests.get(f"{API}/citations/tenant/{did}/analytics-history",
                      headers=h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    # Newest first.
    assert body["snapshots"][0]["impressions"] == 1500
    assert body["snapshots"][1]["impressions"] == 1000
    assert body["trend"] == "up"


def test_voice_score_breakdown_and_perfect_score():
    """Perfect score requires GBP live + description ≥ 200 chars, every
    other voice directory live, and no drift on any of them."""
    admin_h = _admin_headers()
    # Set all 6 voice directories to live.
    slugs = ["google-business-profile", "apple-maps", "bing-places",
              "yelp", "facebook-business", "nextdoor"]
    dirs = list(_sync_db.citation_directories.find(
        {"slug": {"$in": slugs}}, {"_id": 0, "id": 1, "slug": 1},
    ))
    by_slug = {d["slug"]: d["id"] for d in dirs}
    for slug, did in by_slug.items():
        payload = {"status": "live"}
        if slug == "google-business-profile":
            # Notes acts as the "description" — 200+ chars.
            payload["notes"] = "x" * 210
        requests.patch(f"{API}/citations/tenant/{did}",
                        headers=admin_h, json=payload,
                        timeout=15).raise_for_status()
        requests.post(f"{API}/citations/tenant/{did}/mark-verified",
                       headers=admin_h, timeout=15).raise_for_status()

    r = requests.get(f"{API}/citations/tenant/voice-score",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["max_score"] == 100
    assert body["score"] == 100, body
    labels_passed = [b for b in body["breakdown"] if b["passed"]]
    assert len(labels_passed) == 7


def test_voice_score_partial_when_gbp_description_too_short():
    admin_h = _admin_headers()
    gbp = _gbp_directory_id()
    requests.patch(f"{API}/citations/tenant/{gbp}", headers=admin_h,
                    json={"status": "live", "notes": "too short"},
                    timeout=15).raise_for_status()
    r = requests.get(f"{API}/citations/tenant/voice-score",
                      headers=admin_h, timeout=15)
    body = r.json()
    # GBP contributes 0, other listings are still not live, NAP gate fails.
    gbp_rule = next(b for b in body["breakdown"]
                     if b["slug"] == "google-business-profile")
    assert gbp_rule["passed"] is False
    assert "description only" in gbp_rule["reason"]
    assert body["score"] == 0


def test_duplicate_urls_patch_and_summary_open_count():
    did = _gbp_directory_id()
    h = _admin_headers()
    r = requests.patch(
        f"{API}/citations/tenant/{did}/duplicates",
        headers=h,
        json={"duplicate_urls": [
            {"url": "https://dup.example.com/1", "status": "reported"},
            {"url": "https://dup.example.com/2", "status": "suppressed"},
            {"url": "https://dup.example.com/3", "status": "confirmed"},
            {"url": "https://dup.example.com/1", "status": "reported"},  # dupe drop
        ]},
        timeout=15,
    )
    assert r.status_code == 200
    dups = r.json()["duplicate_urls"]
    assert len(dups) == 3  # de-duped

    # Only "reported"/"pending" count as open. suppressed + confirmed do not.
    summary = requests.get(f"{API}/citations/tenant/summary",
                            headers=h, timeout=15).json()
    assert summary["duplicates_open_count"] == 1


def test_duplicate_urls_reject_invalid_status():
    did = _gbp_directory_id()
    r = requests.patch(
        f"{API}/citations/tenant/{did}/duplicates",
        headers=_admin_headers(),
        json={"duplicate_urls": [{"url": "https://x", "status": "bogus"}]},
        timeout=15,
    )
    assert r.status_code == 422


def test_nap_drift_preview_lists_affected_live_listings():
    """Verifying two listings + then previewing a phone change should
    return both as affected, without mutating any state."""
    admin_h = _admin_headers()
    dirs = list(_sync_db.citation_directories.find(
        {"slug": {"$in": ["google-business-profile", "apple-maps"]}},
        {"_id": 0, "id": 1},
    ))
    for d in dirs:
        requests.patch(f"{API}/citations/tenant/{d['id']}",
                        headers=admin_h, json={"status": "live"},
                        timeout=15).raise_for_status()
        requests.post(f"{API}/citations/tenant/{d['id']}/mark-verified",
                       headers=admin_h, timeout=15).raise_for_status()

    r = requests.get(
        f"{API}/citations/tenant/nap-drift-preview",
        params={"phone": "555-9999-NEW"},
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["changed_fields"] == ["phone"]
    assert body["affected_count"] == 2
    slugs = sorted(a["directory_slug"] for a in body["affected"])
    assert slugs == ["apple-maps", "google-business-profile"]
    # State is not mutated — the tenant_citations row still has status=live.
    tid = _tenant_id_for("admin@aquaterra.com")
    still_live = _sync_db.tenant_citations.count_documents(
        {"tenant_id": tid, "status": "live"},
    )
    assert still_live == 2


def test_extension_endpoints_require_admin():
    did = _gbp_directory_id()
    tech_h = _tech_headers()
    r1 = requests.post(f"{API}/citations/tenant/{did}/analytics",
                        headers=tech_h, json={"impressions": 1},
                        timeout=15)
    assert r1.status_code == 403
    r2 = requests.get(f"{API}/citations/tenant/voice-score",
                       headers=tech_h, timeout=15)
    assert r2.status_code == 403
    r3 = requests.patch(f"{API}/citations/tenant/{did}/duplicates",
                         headers=tech_h,
                         json={"duplicate_urls": []}, timeout=15)
    assert r3.status_code == 403
    r4 = requests.get(f"{API}/citations/tenant/nap-drift-preview",
                       headers=tech_h, timeout=15)
    assert r4.status_code == 403

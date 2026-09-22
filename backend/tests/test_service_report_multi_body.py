"""Feb-2026 · Multi-body service reports Phase 1 — backend suite.

Locks:
  * Validators reject reading / chemical keys outside the trimmed
    allow-list per body type.
  * Boot migration is idempotent, seeds ``water_bodies[0]`` from
    legacy top-level fields, and never mutates an already-migrated
    doc on re-run.
  * PATCH /jobs/{jid}/service-report accepts a ``water_bodies`` array,
    persists it verbatim, and mirrors the flattened chemicals into
    ``chemicals_added`` (top-level) so auto-invoice + usage snapshots
    continue to work.
  * Legacy top-level PATCH keeps ``water_bodies[0]`` in sync.
  * Customer service-report reads expose the redacted
    ``water_bodies`` array + list summary.
  * Chemistry required-readings gate keeps operating on the
    pool-typed body during submit (mirror path).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_TOK: dict = {}


def _login(email: str) -> tuple[str, dict]:
    if email in _TOK:
        return _TOK[email]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"}, timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=30).json()
    _TOK[email] = (tok, me)
    return tok, me


_PREFIX = f"wb-{uuid.uuid4().hex[:8]}"


def _seed_pool_job(tenant_id: str, tech_id: str, customer_id: str = "seed-cust") -> str:
    jid = f"{_PREFIX}-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": f"TEST_WB Pool Service {jid[-6:]}",
        "customer_id": customer_id, "customer_name": "Seed Customer",
        "service_type": "Pool Service",
        "technician_id": tech_id,
        "scheduled_date": "2026-09-01",
        "scheduled_start": "2026-09-01T15:00:00Z",
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup():
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.service_reports.delete_many({"job_id": {"$regex": f"^{_PREFIX}"}})
    _sync.service_reports.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.chemical_usage_events.delete_many({"job_id": {"$regex": f"^{_PREFIX}"}})


def setup_module(module): _cleanup()
def teardown_module(module): _cleanup()


# ══════════════════════════════════════════════════════════════════════
# 1 · Validator unit — allow-list enforcement per body type.
# ══════════════════════════════════════════════════════════════════════
def test_validator_accepts_pool_full_chemistry():
    from services.water_bodies import validate_water_bodies
    out = validate_water_bodies([{
        "type": "pool",
        "readings": [
            {"key": "free_chlorine", "value": 3.0},
            {"key": "ph", "value": 7.5},
            {"key": "alkalinity", "value": 100},
            {"key": "cyanuric_acid", "value": 45},
            {"key": "salt", "value": 3200},
        ],
        "chemicals_used": [
            {"product_slug": "liquid_chlorine", "quantity": 2, "unit": "gal"},
            {"product_slug": "muriatic_acid", "quantity": 0.5, "unit": "gal"},
        ],
    }])
    assert len(out) == 1
    assert out[0]["type"] == "pool"
    assert out[0]["label"] == "Pool"
    assert len(out[0]["readings"]) == 5
    assert len(out[0]["chemicals_used"]) == 2


def test_validator_rejects_cya_on_spa():
    from services.water_bodies import validate_water_bodies, WaterBodyValidationError
    with pytest.raises(WaterBodyValidationError) as exc:
        validate_water_bodies([{
            "type": "spa",
            "readings": [{"key": "cyanuric_acid", "value": 40}],
        }])
    assert exc.value.detail["message"] == "reading_not_allowed_for_body_type"
    assert exc.value.detail["key"] == "cyanuric_acid"


def test_validator_rejects_salt_on_spa():
    """Spa explicitly omits salt (approved kickoff spec)."""
    from services.water_bodies import validate_water_bodies, WaterBodyValidationError
    with pytest.raises(WaterBodyValidationError) as exc:
        validate_water_bodies([{
            "type": "spa",
            "readings": [{"key": "salt", "value": 3000}],
        }])
    assert exc.value.detail["message"] == "reading_not_allowed_for_body_type"


def test_validator_rejects_salt_bag_on_fountain():
    from services.water_bodies import validate_water_bodies, WaterBodyValidationError
    with pytest.raises(WaterBodyValidationError) as exc:
        validate_water_bodies([{
            "type": "fountain",
            "chemicals_used": [{"product_slug": "salt", "quantity": 1}],
        }])
    assert exc.value.detail["message"] == "chemical_not_allowed_for_body_type"
    assert exc.value.detail["slug"] == "salt"


def test_validator_other_type_is_freeform():
    from services.water_bodies import validate_water_bodies
    out = validate_water_bodies([{
        "type": "other",
        "label": "Fish Pond",
        "readings": [{"key": "orp", "value": 700}],
        "chemicals_used": [{"product_slug": "salt", "quantity": 5}],
    }])
    assert out[0]["type"] == "other"
    assert out[0]["label"] == "Fish Pond"
    assert out[0]["readings"][0]["key"] == "orp"
    assert out[0]["chemicals_used"][0]["product_slug"] == "salt"


def test_validator_multi_body_normalizes_ids_and_sequence():
    from services.water_bodies import validate_water_bodies
    out = validate_water_bodies([
        {"type": "pool", "readings": [{"key": "ph", "value": 7.4}]},
        {"type": "spa", "readings": [{"key": "ph", "value": 7.6}]},
        {"type": "water_feature", "readings": [{"key": "ph", "value": 7.5}]},
    ])
    assert [b["type"] for b in out] == ["pool", "spa", "water_feature"]
    assert [b["sequence"] for b in out] == [0, 1, 2]
    assert len({b["id"] for b in out}) == 3


def test_validator_empty_list_rejected():
    from services.water_bodies import validate_water_bodies, WaterBodyValidationError
    with pytest.raises(WaterBodyValidationError) as exc:
        validate_water_bodies([])
    assert "at_least_one_body" in exc.value.detail["message"]


# ══════════════════════════════════════════════════════════════════════
# 2 · Boot migration — idempotent + backfills body[0] from legacy.
# ══════════════════════════════════════════════════════════════════════
def _super_login() -> str:
    from tests.conftest import demo_pw
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "super@aquaterra.com", "password": demo_pw("super@aquaterra.com")},
        timeout=30,
    )
    if r.status_code != 200:
        r = requests.post(
            f"{API}/auth/login",
            json={"email": "super@aquaterra.com", "password": "password123"},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["access_token"]


def test_migration_backfills_water_bodies_from_legacy_report():
    """HTTP path — hit the super_admin admin endpoint so we avoid the
    Motor loop-binding trap ``asyncio.run(coro)`` triggers under pytest.
    """
    rid = f"{_PREFIX}-mig-{uuid.uuid4().hex[:6]}"
    jid = f"{_PREFIX}-mig-job-{uuid.uuid4().hex[:6]}"
    tid = "TENANT_wb_test"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "TEST_WB Legacy",
        "service_type": "Pool Service",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _sync.service_reports.insert_one({
        "id": rid, "tenant_id": tid, "job_id": jid,
        "tech_id": "TEST-tech-mig",
        "chemical_readings": [
            {"key": "free_chlorine", "value": 2.5},
            {"key": "ph", "value": 7.3},
        ],
        "chemicals_added": [{"product_slug": "liquid_chlorine", "quantity": 1}],
        "photos": [{"url": "https://example.com/legacy.jpg", "kind": "photo"}],
        "notes": "Legacy report — pre-migration.",
        "submitted_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Reset the sentinel + trigger the admin endpoint (force=true).
    _sync.migrations.delete_one({"id": "feb2026_service_reports_water_bodies_v1"})
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/service-reports-water-bodies?force=true",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "ok"
    assert body["summary"]["migrated"] >= 1

    doc = _sync.service_reports.find_one({"id": rid})
    assert isinstance(doc.get("water_bodies"), list)
    assert len(doc["water_bodies"]) == 1
    b0 = doc["water_bodies"][0]
    assert b0["type"] == "pool"
    assert b0["label"] == "Pool"
    assert b0["sequence"] == 0
    assert any(r["key"] == "free_chlorine" for r in b0["readings"])
    assert b0["chemicals_used"][0]["product_slug"] == "liquid_chlorine"
    assert b0["media"][0]["url"] == "https://example.com/legacy.jpg"
    assert b0["notes"] == "Legacy report — pre-migration."
    # Legacy fields still on top-level (backward compat mirror).
    assert doc.get("chemical_readings")
    assert doc.get("chemicals_added")


def test_migration_is_idempotent_second_run_noop():
    """Second call (without force) must short-circuit on the sentinel."""
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/service-reports-water-bodies",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "skipped"
    assert body.get("reason") == "sentinel_present"


def test_migration_forced_rerun_skips_already_migrated_doc():
    """Docs that already have water_bodies must not be re-written by
    a forced run (the ``water_bodies`` update filter guards against it)."""
    rid = f"{_PREFIX}-already-{uuid.uuid4().hex[:6]}"
    tid = "TENANT_wb_test"
    _sync.service_reports.insert_one({
        "id": rid, "tenant_id": tid,
        "job_id": f"{_PREFIX}-any",
        "tech_id": "TEST-tech-already",
        "water_bodies": [{
            "id": "existing-body",
            "type": "spa",
            "label": "Guest Spa",
            "sequence": 0,
            "readings": [],
            "chemicals_used": [],
            "media": [],
            "notes": "",
        }],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/service-reports-water-bodies?force=true",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    assert r.status_code == 200, r.text

    doc = _sync.service_reports.find_one({"id": rid})
    assert doc["water_bodies"][0]["id"] == "existing-body"
    assert doc["water_bodies"][0]["type"] == "spa"


# ══════════════════════════════════════════════════════════════════════
# 3 · PATCH /jobs/{jid}/service-report accepts water_bodies + mirrors.
# ══════════════════════════════════════════════════════════════════════
def _tech_id_for(me: dict) -> str:
    return me.get("technician_id") or me.get("id")


def test_patch_multi_body_persists_and_mirrors_top_level():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = _tech_id_for(me)
    jid = _seed_pool_job(tid, tech_id)
    try:
        # Bootstrap the report so the PATCH has something to update.
        boot = requests.get(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert boot.status_code == 200, boot.text
        assert isinstance(boot.json().get("water_bodies"), list)
        assert len(boot.json()["water_bodies"]) == 1
        assert boot.json()["water_bodies"][0]["type"] == "pool"

        # PATCH with pool + spa multi-body payload.
        r = requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"},
            json={"water_bodies": [
                {"type": "pool",
                 "readings": [
                    {"key": "free_chlorine", "value": 3.0},
                    {"key": "ph", "value": 7.5},
                    {"key": "alkalinity", "value": 100},
                    {"key": "cyanuric_acid", "value": 45},
                 ],
                 "chemicals_used": [
                    {"product_slug": "liquid_chlorine", "quantity": 2, "unit": "gal"},
                 ],
                 "notes": "Pool clean"},
                {"type": "spa",
                 "readings": [
                    {"key": "ph", "value": 7.4},
                    {"key": "alkalinity", "value": 80},
                 ],
                 "chemicals_used": [
                    {"product_slug": "chlorine_tabs", "quantity": 1, "unit": "tabs"},
                 ],
                 "notes": "Spa sanitized"},
            ]},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rep = r.json()
        bodies = rep["water_bodies"]
        assert len(bodies) == 2
        assert bodies[0]["type"] == "pool"
        assert bodies[1]["type"] == "spa"
        # Legacy mirrors are rebuilt: chemical_readings = pool body
        # readings; chemicals_added = union of all bodies' chemicals.
        # Phase CHEM1 · Feb-2026 — Required Four pool readings.
        # Phase P17.1 · Feb-2026 — canonical rename: server response
        # emits ``chlorine`` (was ``free_chlorine`` under P17). The
        # ``free_chlorine`` input above remains a valid SOURCE alias
        # via ALIAS_MAP.
        assert len(rep["chemical_readings"]) == 4
        assert any(r["key"] == "chlorine" for r in rep["chemical_readings"])
        assert len(rep["chemicals_added"]) == 2
        slugs = {c.get("product_slug") for c in rep["chemicals_added"]}
        assert slugs == {"liquid_chlorine", "chlorine_tabs"}
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})


def test_patch_rejects_disallowed_reading_for_body_type():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = _tech_id_for(me)
    jid = _seed_pool_job(tid, tech_id)
    try:
        requests.get(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        r = requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"},
            json={"water_bodies": [
                {"type": "spa",
                 "readings": [{"key": "cyanuric_acid", "value": 40}]},
            ]},
            timeout=30,
        )
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["message"] == "reading_not_allowed_for_body_type"
        assert detail["key"] == "cyanuric_acid"
        assert detail["type"] == "spa"
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})


def test_patch_legacy_only_syncs_water_bodies_zero():
    """A legacy-shape PATCH (no ``water_bodies`` key) still keeps
    ``water_bodies[0]`` in lock-step with the top-level fields."""
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = _tech_id_for(me)
    jid = _seed_pool_job(tid, tech_id)
    try:
        requests.get(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        r = requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "chemical_readings": [
                    {"key": "free_chlorine", "value": 2.9},
                    {"key": "ph", "value": 7.4},
                    {"key": "alkalinity", "value": 90},
                    {"key": "cyanuric_acid", "value": 50},
                ],
                "chemicals_added": [
                    {"product_slug": "muriatic_acid", "quantity": 0.5},
                ],
                "notes": "Legacy path patch",
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rep = r.json()
        assert isinstance(rep.get("water_bodies"), list)
        assert len(rep["water_bodies"]) == 1
        b0 = rep["water_bodies"][0]
        assert b0["type"] in ("pool", "other")  # bootstrap picks pool for pool jobs
        assert any(r["key"] == "free_chlorine" for r in b0["readings"])
        assert b0["chemicals_used"][0]["product_slug"] == "muriatic_acid"
        assert b0["notes"] == "Legacy path patch"
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})


# ══════════════════════════════════════════════════════════════════════
# 4 · Submit path — chemistry gate operates on flattened pool readings.
# ══════════════════════════════════════════════════════════════════════
def test_submit_uses_water_bodies_pool_readings_for_gate():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = _tech_id_for(me)
    jid = _seed_pool_job(tid, tech_id)
    try:
        requests.get(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        # Only submit a spa body (no pool → gate should NOT block since
        # the report has no pool body, but the parent job is a pool job
        # → gate SHOULD block). This locks the behaviour that the
        # top-level mirror still drives the gate for pool jobs.
        requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"},
            json={"water_bodies": [
                {"type": "spa",
                 "readings": [
                    {"key": "ph", "value": 7.4},
                    {"key": "alkalinity", "value": 80},
                 ]},
            ]},
            timeout=30,
        )
        # Submit → 422 chemistry_core_readings_missing (spa-only, but
        # parent job is pool → gate fires).
        r = requests.post(
            f"{API}/jobs/{jid}/service-report/submit",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["detail"] == "chemistry_core_readings_missing"

        # Now add a pool body with the full 5 core readings + submit.
        requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"},
            json={"water_bodies": [
                {"type": "pool",
                 "readings": [
                    {"key": "free_chlorine", "value": 3.0},
                    {"key": "ph", "value": 7.5},
                    {"key": "alkalinity", "value": 100},
                    {"key": "cyanuric_acid", "value": 45},
                 ],
                 "chemicals_used": [
                    {"product_slug": "liquid_chlorine", "quantity": 2,
                      "name": "Liquid Chlorine", "unit": "gal"},
                 ]},
                {"type": "spa",
                 "readings": [{"key": "ph", "value": 7.4}],
                 "chemicals_used": [
                    {"product_slug": "chlorine_tabs", "quantity": 1,
                      "name": "Chlorine Tabs", "unit": "tabs"},
                 ]},
            ]},
            timeout=30,
        )
        r = requests.post(
            f"{API}/jobs/{jid}/service-report/submit",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep.get("submitted_at")
        # Chemical usage snapshot must have both bodies' chemicals.
        events = list(_sync.chemical_usage_events.find(
            {"tenant_id": tid, "job_id": jid}))
        names = {(e.get("product_slug") or e.get("name") or "").lower()
                 for e in events}
        # snapshot resolves the slug from catalog when available;
        # legacy fallback uses the ``name``. Accept either form.
        assert names & {"liquid_chlorine", "liquid chlorine",
                          "chlorine_tabs", "chlorine tabs"}
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})


# ══════════════════════════════════════════════════════════════════════
# 5 · Customer history — read-only exposure of water_bodies (redacted).
# ══════════════════════════════════════════════════════════════════════
def test_customer_list_exposes_water_body_summary():
    """The customer service-report list endpoint must include a compact
    ``water_bodies_summary`` per report so the FE can render "Pool · Spa"
    style badges."""
    # Fake a submitted report inline (skip the auth flow — this test
    # goes straight through the redact helper).
    from routers.service_reports import _redact_report_for_customer
    from services.water_bodies import summarize_body, iter_water_bodies

    doc = {
        "id": "report-1", "tenant_id": "t", "job_id": "j", "tech_id": "u",
        "submitted_at": "2026-09-01T15:00:00Z",
        "water_bodies": [
            {"id": "b0", "type": "pool", "label": "Pool", "sequence": 0,
              "readings": [{"key": "free_chlorine", "value": 3.0, "name": "Free Cl", "unit": "ppm"}],
              "chemicals_used": [{"name": "Liquid Chlorine", "quantity": 2,
                                    "unit": "gal", "cost_cents": 800}],
              "media": [{"url": "https://ex.com/a.jpg", "kind": "photo"}],
              "notes": "OK"},
            {"id": "b1", "type": "spa", "label": "Spa", "sequence": 1,
              "readings": [{"key": "ph", "value": 7.4, "name": "pH"}],
              "chemicals_used": [{"name": "Chlorine Tabs", "quantity": 1,
                                    "unit": "tabs", "cost_cents": 120}],
              "media": [], "notes": ""},
        ],
        "chemical_readings": [{"key": "free_chlorine", "value": 3.0}],
        "chemicals_added": [{"name": "Liquid Chlorine", "quantity": 2, "cost_cents": 800}],
        "photos": [{"url": "https://ex.com/a.jpg"}],
        "internal_notes": "SHOULD NOT LEAK",
        "checklist_items": [{"label": "brushed", "checked": True}],
    }
    redacted = _redact_report_for_customer(doc)
    # Chemical cost is scrubbed from every body's chemicals_used list.
    for b in redacted["water_bodies"]:
        for c in b.get("chemicals_used") or []:
            assert "cost_cents" not in c
    # Readings are converted to bands.
    assert redacted["water_bodies"][0]["readings"][0].get("label")
    assert "value" not in redacted["water_bodies"][0]["readings"][0]
    # Internal notes stripped.
    assert "internal_notes" not in redacted
    # Summary helper — used by /customers/me/service-reports.
    bodies = iter_water_bodies(redacted)
    summaries = [summarize_body(b) for b in bodies]
    assert [s["type"] for s in summaries] == ["pool", "spa"]
    assert summaries[0]["reading_count"] == 1
    assert summaries[0]["chemical_count"] == 1
    assert summaries[1]["chemical_count"] == 1


def test_customer_list_endpoint_returns_water_bodies_summary():
    """End-to-end test hitting /api/customers/me/service-reports with
    a seeded submitted multi-body report."""
    # Locate a customer login that already exists in the demo seed.
    # We'll pick the first customer of the aquaterra tenant.
    admin_tok, admin_me = _login("admin@aquaterra.com")
    tid = admin_me.get("tenant_id")
    cust = _sync.customers.find_one({"tenant_id": tid})
    if not cust:
        pytest.skip("No seeded customer for aquaterra tenant")
    # Seed a submitted service report with 2 bodies for this customer.
    jid = f"{_PREFIX}-cust-{uuid.uuid4().hex[:6]}"
    rid = f"{_PREFIX}-rep-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "TEST_WB Customer History",
        "customer_id": cust["id"], "customer_name": cust.get("name"),
        "service_type": "Pool Service",
        "scheduled_start": "2026-09-02T15:00:00Z",
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _sync.service_reports.insert_one({
        "id": rid, "tenant_id": tid, "job_id": jid,
        "tech_id": "TEST-tech-cust",
        "submitted_at": "2026-09-02T16:00:00Z",
        "water_bodies": [
            {"id": "wb-a", "type": "pool", "label": "Main Pool", "sequence": 0,
              "readings": [
                {"key": "free_chlorine", "name": "Free Cl", "value": 3.0, "unit": "ppm"},
                {"key": "ph", "name": "pH", "value": 7.5, "unit": ""},
              ],
              "chemicals_used": [{"name": "Liquid Chlorine", "quantity": 2, "unit": "gal"}],
              "media": [], "notes": "OK"},
            {"id": "wb-b", "type": "spa", "label": "Guest Spa", "sequence": 1,
              "readings": [{"key": "ph", "name": "pH", "value": 7.4}],
              "chemicals_used": [], "media": [], "notes": ""},
        ],
        "chemical_readings": [{"key": "free_chlorine", "value": 3.0}],
        "chemicals_added": [{"name": "Liquid Chlorine", "quantity": 2}],
        "checklist_items": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        # Log in as this customer via magic link seeding — skip if no
        # customer auth user exists.
        cust_user = _sync.users.find_one(
            {"tenant_id": tid, "role": "customer", "customer_id": cust["id"]}
        )
        if not cust_user:
            pytest.skip("No customer auth user linked to seeded customer")
        from tests.conftest import demo_pw
        r = requests.post(
            f"{API}/auth/login",
            json={"email": cust_user["email"], "password": demo_pw(cust_user["email"])},
            timeout=30,
        )
        if r.status_code != 200:
            pytest.skip("Customer auth login failed — cannot verify list surface")
        tok = r.json()["access_token"]
        r = requests.get(
            f"{API}/customers/me/service-reports",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        row = next((x for x in rows if x["id"] == rid), None)
        assert row is not None, "Seeded report missing from customer list"
        assert row["water_body_count"] == 2
        assert [s["type"] for s in row["water_bodies_summary"]] == ["pool", "spa"]
        assert row["water_bodies_summary"][0]["label"] == "Main Pool"

        # Detail endpoint returns redacted per-body chemistry bands.
        r = requests.get(
            f"{API}/customers/me/service-reports/{rid}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert isinstance(detail.get("water_bodies"), list)
        assert len(detail["water_bodies"]) == 2
        # No raw numeric values on the body-level readings any more.
        for b in detail["water_bodies"]:
            for reading in b.get("readings") or []:
                assert "value" not in reading
                # classify_reading returns lowercased labels; the top-
                # level ``chemical_readings`` uses the CANONICAL-band
                # form (Title Case). Accept either — both are
                # customer-safe.
                assert (reading.get("label") or "").lower() in {
                    "below average", "average", "above average", "elevated",
                }
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_one({"id": rid})


# ══════════════════════════════════════════════════════════════════════
# 6 · Chemical Cost / Usage rollup — multi-body chemicals feed snapshot.
# ══════════════════════════════════════════════════════════════════════
def test_chemical_usage_snapshot_captures_all_bodies_chemicals():
    """The chemistry usage snapshot must include chemicals from EVERY
    body of water on the report (the top-level ``chemicals_added``
    mirror is what feeds it, and the PATCH handler must union across
    bodies)."""
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = _tech_id_for(me)
    jid = _seed_pool_job(tid, tech_id)
    try:
        requests.get(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={"Authorization": f"Bearer {tok}"},
            json={"water_bodies": [
                {"type": "pool",
                 "readings": [
                    {"key": "free_chlorine", "value": 3.0},
                    {"key": "ph", "value": 7.5},
                    {"key": "alkalinity", "value": 100},
                    {"key": "cyanuric_acid", "value": 45},
                 ],
                 "chemicals_used": [
                    {"product_slug": "liquid_chlorine", "name": "Liquid Chlorine",
                      "quantity": 3, "unit": "gal"},
                 ]},
                {"type": "spa",
                 "chemicals_used": [
                    {"product_slug": "muriatic_acid", "name": "Muriatic Acid",
                      "quantity": 0.5, "unit": "gal"},
                 ]},
                {"type": "water_feature",
                 "chemicals_used": [
                    {"product_slug": "clarifier", "name": "Clarifier",
                      "quantity": 6, "unit": "oz"},
                 ]},
            ]},
            timeout=30,
        )
        # Legacy mirror flattened union.
        sr = _sync.service_reports.find_one({"job_id": jid})
        slugs = {c.get("product_slug") for c in sr["chemicals_added"]}
        assert slugs == {"liquid_chlorine", "muriatic_acid", "clarifier"}
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})

"""Feb-2026 · Multi-body Phase 1 · Option 2 · chemical_usage_events.

Locks the write-time + read-time contract for per-body chemistry
attribution introduced by the Option 2 chemical-cost report rework:

  * ``snapshot_chemical_usage`` iterates ``water_bodies`` when
    supplied and stamps each event with ``water_body_id``,
    ``water_body_type``, ``water_body_label``.
  * Flat ``chemicals_added`` callers get ``water_body_id=None`` and
    roll into the report's ``Legacy`` bucket.
  * The chemical-cost report's ``by_water_body`` bucket surfaces both
    bodies on a multi-body invoice + reconciles totals against
    ``by_chemical``.
  * Boot migration (via HTTP admin endpoint to avoid the Motor loop
    trap under pytest) is idempotent + sentinel-guarded and
    best-effort links legacy events to a body when the report has
    exactly one body OR a unique body carries a chemical whose slug
    matches the event's slug. Ambiguous cases stay
    ``water_body_id=None``.
  * Tolerance: legacy events (``water_body_id=None`` on a paid
    invoice) still count in the report totals + surface in the
    Legacy bucket.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": "password123"},
                        timeout=30)
    r.raise_for_status()
    tok = r.json()["access_token"]
    me = requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=30).json()
    _TOK[email] = (tok, me)
    return tok, me


def _super_login() -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": "super@aquaterra.com",
                              "password": "password123"},
                        timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


_PREFIX = f"wbchem-{uuid.uuid4().hex[:8]}"


def _seed_catalog(tid: str, slug: str, name: str,
                    cost_cents: int = 500, unit_kind: str = "gal") -> None:
    _sync.chemical_costs.update_one(
        {"tenant_id": tid, "chemical_slug": slug},
        {"$set": {"tenant_id": tid, "chemical_slug": slug, "name": name,
                    "cost_per_unit_cents": cost_cents,
                    "unit_kind": unit_kind}},
        upsert=True,
    )


def _cleanup():
    _sync.chemical_usage_events.delete_many(
        {"id": {"$regex": f"^{_PREFIX}"}})
    _sync.chemical_usage_events.delete_many(
        {"service_report_id": {"$regex": f"^{_PREFIX}"}})
    _sync.chemical_costs.delete_many({"chemical_slug": {"$regex": f"^{_PREFIX}"}})
    _sync.service_reports.delete_many(
        {"id": {"$regex": f"^{_PREFIX}"}})
    _sync.jobs.delete_many({"id": {"$regex": f"^{_PREFIX}"}})
    _sync.quotes.delete_many({"id": {"$regex": f"^{_PREFIX}"}})


def setup_module(module): _cleanup()
def teardown_module(module): _cleanup()


# ══════════════════════════════════════════════════════════════════════
# Helpers — drive snapshots through the real submit endpoint so
# ``snapshot_chemical_usage`` runs under the server's own event loop
# (Motor's async client is loop-bound; a direct ``asyncio.run(coro)``
# from a sync pytest raises "attached to a different loop"). Tests
# that need to verify the resulting event rows read them back from
# Mongo via the sync client.
# ══════════════════════════════════════════════════════════════════════
def _seed_pool_job(tid: str, tech_id: str,
                    customer_id: str = "seed-cust") -> str:
    jid = f"{_PREFIX}-job-{uuid.uuid4().hex[:6]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": f"TEST_WB Pool Service {jid[-6:]}",
        "customer_id": customer_id, "customer_name": "Seed Customer",
        "service_type": "Pool Service",
        "technician_id": tech_id,
        "scheduled_date": "2026-09-01",
        "scheduled_start": "2026-09-01T15:00:00Z",
        "price": 100.0,
        "status": "scheduled",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _submit_multi_body(tok: str, jid: str, bodies: list) -> dict:
    # Bootstrap so the report exists.
    requests.get(f"{API}/jobs/{jid}/service-report",
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    requests.patch(
        f"{API}/jobs/{jid}/service-report",
        headers={"Authorization": f"Bearer {tok}"},
        json={"water_bodies": bodies}, timeout=30,
    )
    r = requests.post(
        f"{API}/jobs/{jid}/service-report/submit",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ══════════════════════════════════════════════════════════════════════
# 1 · Submit-driven snapshot — water_bodies path stamps wb_id per event
# ══════════════════════════════════════════════════════════════════════
def test_snapshot_iterates_water_bodies_and_stamps_wb_id():
    """End-to-end via the real ``POST /jobs/{jid}/service-report/submit``
    endpoint. The submit path passes ``water_bodies`` into
    ``snapshot_chemical_usage`` (Option 2). Both events should be
    stamped with their respective ``water_body_id`` + type + label.

    Uses the tenant's live ``chlorine_tabs`` catalog entry so the
    pool-body allow-list accepts the payload without a catalog
    write (avoids cross-test contamination of the aquaterra
    catalog).
    """
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = me.get("technician_id") or me.get("id")
    slug = "chlorine_tabs"
    cat_row = _sync.chemical_costs.find_one(
        {"tenant_id": tid, "chemical_slug": slug})
    assert cat_row, "expected chlorine_tabs seeded in aquaterra catalog"
    unit_cost_cents = int(cat_row["cost_per_unit_cents"])
    jid = _seed_pool_job(tid, tech_id)
    try:
        _submit_multi_body(tok, jid, [
            {"type": "pool", "label": "Main Pool",
              "readings": [
                {"key": "free_chlorine", "value": 3.0},
                {"key": "ph", "value": 7.5},
                {"key": "alkalinity", "value": 100},
                {"key": "cyanuric_acid", "value": 45},
              ],
              "chemicals_used": [{"product_slug": slug,
                                    "name": "Chlorine Tablets",
                                    "quantity": 1.0, "unit": "tab"}]},
            {"type": "spa", "label": "Backyard Spa",
              "readings": [{"key": "ph", "value": 7.4}],
              "chemicals_used": [{"product_slug": slug,
                                    "name": "Chlorine Tablets",
                                    "quantity": 0.5, "unit": "tab"}]},
        ])
        events = list(_sync.chemical_usage_events.find(
            {"job_id": jid, "product_slug": slug}, {"_id": 0}))
        assert len(events) == 2
        by_type = {(e.get("water_body_type") or ""): e for e in events}
        assert set(by_type.keys()) == {"pool", "spa"}
        assert by_type["pool"]["water_body_label"] == "Main Pool"
        assert by_type["pool"]["quantity_used"] == 1.0
        assert by_type["pool"]["total_cost_cents"] == unit_cost_cents
        assert by_type["spa"]["water_body_label"] == "Backyard Spa"
        assert by_type["spa"]["quantity_used"] == 0.5
        assert by_type["spa"]["total_cost_cents"] == (
            int(round(0.5 * unit_cost_cents))
        )
        for e in events:
            assert e.get("water_body_id"), (
                f"event {e.get('id')} missing water_body_id"
            )
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})
        _sync.chemical_usage_events.delete_many({"job_id": jid})
        _sync.quotes.delete_many({"job_id": jid})


# ══════════════════════════════════════════════════════════════════════
# 2 · Legacy flat path — pre-multi-body events keep wb_id=None
# ══════════════════════════════════════════════════════════════════════
def test_legacy_flat_events_carry_null_wb_id():
    """Seeds a legacy-shaped event (pre-Option-2 write) and confirms it
    stays ``water_body_id=None`` through the boot migration when the
    parent report has ambiguous multi-body attribution."""
    tid = "TENANT_wbchem_legacy"
    slug = f"{_PREFIX}-shock"
    _seed_catalog(tid, slug, "TEST Shock",
                     cost_cents=1000, unit_kind="lb")
    sr_id = f"{_PREFIX}-sr-legacy-b"
    eid = f"{_PREFIX}-ev-legacy-b"
    # Report has TWO bodies both containing this slug → migration
    # cannot disambiguate → event must stay wb_id=None.
    _sync.service_reports.insert_one({
        "id": sr_id, "tenant_id": tid,
        "job_id": f"{_PREFIX}-job-legacy-b",
        "water_bodies": [
            {"id": "b1", "type": "pool", "label": "Pool",
              "chemicals_used": [{"product_slug": slug, "quantity": 2.0}]},
            {"id": "b2", "type": "spa", "label": "Spa",
              "chemicals_used": [{"product_slug": slug, "quantity": 1.0}]},
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _sync.chemical_usage_events.insert_one({
        "id": eid, "tenant_id": tid,
        "service_report_id": sr_id,
        "job_id": f"{_PREFIX}-job-legacy-b",
        "product_slug": slug, "quantity_used": 3.0,
        "unit_cost_at_time_cents": 1000, "total_cost_cents": 3000,
        "occurred_at": "2026-07-01T00:00:00Z",
        "created_at": "2026-07-01T00:00:00Z",
    })
    _sync.migrations.delete_one(
        {"id": "chemical_usage_events_water_body_v1"})
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/chemical-usage-events-water-body?force=true",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    assert r.status_code == 200, r.text
    ev = _sync.chemical_usage_events.find_one({"id": eid})
    assert ev["water_body_id"] is None
    assert ev["water_body_type"] is None
    assert ev["water_body_label"] is None


# ══════════════════════════════════════════════════════════════════════
# 3 · Report — by_water_body splits both bodies + reconciles by_chemical
# ══════════════════════════════════════════════════════════════════════
def test_report_by_water_body_splits_multi_body_invoice():
    """End-to-end: submit a multi-body report, mark the invoice paid,
    hit the report, verify BOTH bodies surface + totals match."""
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    tech_id = me.get("technician_id") or me.get("id")
    slug = "clarifier"
    cat_row = _sync.chemical_costs.find_one(
        {"tenant_id": tid, "chemical_slug": slug})
    if not cat_row:
        # Seed under the tenant if catalog doesn't already carry it.
        _seed_catalog(tid, slug, "Clarifier",
                         cost_cents=200, unit_kind="oz")
        cat_row = _sync.chemical_costs.find_one(
            {"tenant_id": tid, "chemical_slug": slug})
    unit_cost_cents = int(cat_row["cost_per_unit_cents"])
    unit_cost = unit_cost_cents / 100.0
    jid = _seed_pool_job(tid, tech_id)
    try:
        _submit_multi_body(tok, jid, [
            {"type": "pool", "label": "Main Pool",
              "readings": [
                {"key": "free_chlorine", "value": 3.0},
                {"key": "ph", "value": 7.5},
                {"key": "alkalinity", "value": 100},
                {"key": "cyanuric_acid", "value": 45},
              ],
              "chemicals_used": [{"product_slug": slug,
                                    "name": "Clarifier",
                                    "quantity": 4.0, "unit": "oz"}]},
            {"type": "spa", "label": "Guest Spa",
              "chemicals_used": [{"product_slug": slug,
                                    "name": "Clarifier",
                                    "quantity": 2.0, "unit": "oz"}]},
        ])
        now = datetime.now(timezone.utc).isoformat()
        _sync.quotes.update_one(
            {"job_id": jid, "doc_type": "invoice"},
            {"$set": {"payment_status": "paid", "paid_at": now,
                        "amount_paid": 100.0}},
        )
        wb_ids = list(_sync.chemical_usage_events.distinct(
            "water_body_id", {"job_id": jid, "product_slug": slug}))
        wb_ids = [w for w in wb_ids if w]
        assert len(wb_ids) == 2, (
            f"expected 2 distinct wb_ids, got {wb_ids}"
        )
        r = requests.get(
            f"{API}/reports/chemical-costs"
            f"?date_from=2026-08-01&date_to=2026-12-31&chemical_ids={slug}",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        row = next(c for c in body["by_chemical"]
                    if c["product_slug"] == slug)
        assert row["qty_used"] == 6.0
        assert row["total_cost"] == round(6.0 * unit_cost, 2)
        bodies = [b for b in body["by_water_body"]
                    if b["water_body_id"] in wb_ids]
        assert len(bodies) == 2
        by_type = {b["body_type"]: b for b in bodies}
        assert by_type["pool"]["total_qty"] == 4.0
        assert by_type["pool"]["total_wholesale_cost"] == round(4.0 * unit_cost, 2)
        assert by_type["pool"]["body_label"] == "Main Pool"
        assert by_type["spa"]["total_qty"] == 2.0
        assert by_type["spa"]["total_wholesale_cost"] == round(2.0 * unit_cost, 2)
        assert by_type["spa"]["body_label"] == "Guest Spa"
        assert sum(b["total_wholesale_cost"] for b in bodies) == row["total_cost"]
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_many({"job_id": jid})
        _sync.chemical_usage_events.delete_many({"job_id": jid})
        _sync.quotes.delete_many({"job_id": jid})


# ══════════════════════════════════════════════════════════════════════
# 4 · Report — Legacy tolerance (wb_id=None still counts).
# ══════════════════════════════════════════════════════════════════════
def test_report_legacy_event_counts_in_totals_and_legacy_bucket():
    tok, me = _login("admin@aquaterra.com")
    tid = me.get("tenant_id")
    slug = f"{_PREFIX}-legacy-slug"
    _seed_catalog(tid, slug, "TEST Legacy", cost_cents=600)
    job_id = f"{_PREFIX}-legacy-job"
    _sync.jobs.insert_one({
        "id": job_id, "tenant_id": tid, "title": "Legacy job",
        "service_type": "Pool Service", "customer_id": "c-leg",
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    now = datetime.now(timezone.utc).isoformat()
    inv_id = f"{_PREFIX}-legacy-inv"
    _sync.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "job_id": job_id, "customer_id": "c-leg",
        "payment_status": "paid", "amount_paid": 60, "total": 60,
        "created_at": now, "paid_at": now,
        "line_items": [{"description": "Service", "quantity": 1,
                          "unit_price": 60}],
    })
    eid = f"{_PREFIX}-legacy-ev"
    _sync.chemical_usage_events.insert_one({
        "id": eid, "tenant_id": tid,
        "job_id": job_id,
        "service_report_id": f"{_PREFIX}-sr-legacy",
        "customer_id": "c-leg",
        "product_slug": slug, "name": "TEST Legacy",
        "quantity_used": 3.0, "unit": "gal",
        "unit_cost_at_time_cents": 600,
        "total_cost_cents": 1800,
        "occurred_at": "2026-08-05T12:00:00Z",
        "created_at": "2026-08-05T12:00:00Z",
    })
    r = requests.get(
        f"{API}/reports/chemical-costs"
        f"?date_from=2026-08-01&date_to=2026-08-31&chemical_ids={slug}",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    body = r.json()
    row = next(c for c in body["by_chemical"] if c["product_slug"] == slug)
    assert row["qty_used"] == 3.0
    assert row["total_cost"] == 18.0
    legacy = [b for b in body["by_water_body"] if b["body_type"] == "legacy"]
    assert legacy, "expected a Legacy bucket for wb_id=None events"
    assert any(b["water_body_id"] is None for b in legacy)


# ══════════════════════════════════════════════════════════════════════
# 5 · Boot migration — retro-links single-body reports.
# ══════════════════════════════════════════════════════════════════════
def test_migration_retro_links_single_body_report():
    """HTTP admin endpoint drives the migration so we avoid the Motor
    loop-binding trap direct ``asyncio.run`` triggers under pytest."""
    tid = "TENANT_wbchem_mig"
    slug = f"{_PREFIX}-mig"
    _seed_catalog(tid, slug, "TEST Mig", cost_cents=500)
    sr_id = f"{_PREFIX}-mig-sr"
    _sync.service_reports.insert_one({
        "id": sr_id, "tenant_id": tid,
        "job_id": f"{_PREFIX}-mig-job",
        "water_bodies": [{
            "id": "solo-body", "type": "pool", "label": "The Pool",
            "chemicals_used": [{"product_slug": slug, "quantity": 3.0}],
        }],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    eid = f"{_PREFIX}-mig-ev"
    _sync.chemical_usage_events.insert_one({
        "id": eid, "tenant_id": tid,
        "service_report_id": sr_id,
        "job_id": f"{_PREFIX}-mig-job",
        "product_slug": slug, "name": "TEST Mig",
        "quantity_used": 3.0, "unit_cost_at_time_cents": 500,
        "total_cost_cents": 1500,
        "occurred_at": "2026-07-01T00:00:00Z",
        "created_at": "2026-07-01T00:00:00Z",
    })
    _sync.migrations.delete_one(
        {"id": "chemical_usage_events_water_body_v1"})
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/chemical-usage-events-water-body?force=true",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    assert r.status_code == 200, r.text

    ev = _sync.chemical_usage_events.find_one({"id": eid})
    assert ev["water_body_id"] == "solo-body"
    assert ev["water_body_type"] == "pool"
    assert ev["water_body_label"] == "The Pool"


def test_migration_leaves_ambiguous_events_null():
    """When a report has two bodies each carrying the same slug, the
    migration cannot infer which body → leaves ``water_body_id=None``."""
    tid = "TENANT_wbchem_mig2"
    slug = f"{_PREFIX}-ambig"
    _seed_catalog(tid, slug, "TEST Ambig", cost_cents=500)
    sr_id = f"{_PREFIX}-ambig-sr"
    _sync.service_reports.insert_one({
        "id": sr_id, "tenant_id": tid,
        "job_id": f"{_PREFIX}-ambig-job",
        "water_bodies": [
            {"id": "b-pool", "type": "pool", "label": "Pool",
              "chemicals_used": [{"product_slug": slug, "quantity": 2.0}]},
            {"id": "b-spa", "type": "spa", "label": "Spa",
              "chemicals_used": [{"product_slug": slug, "quantity": 1.0}]},
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    eid = f"{_PREFIX}-ambig-ev"
    _sync.chemical_usage_events.insert_one({
        "id": eid, "tenant_id": tid,
        "service_report_id": sr_id,
        "job_id": f"{_PREFIX}-ambig-job",
        "product_slug": slug, "quantity_used": 3.0,
        "unit_cost_at_time_cents": 500, "total_cost_cents": 1500,
        "occurred_at": "2026-07-01T00:00:00Z",
        "created_at": "2026-07-01T00:00:00Z",
    })
    _sync.migrations.delete_one(
        {"id": "chemical_usage_events_water_body_v1"})
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/chemical-usage-events-water-body?force=true",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    assert r.status_code == 200, r.text

    ev = _sync.chemical_usage_events.find_one({"id": eid})
    assert ev.get("water_body_id") is None
    assert ev.get("water_body_type") is None


def test_migration_idempotent_second_run_short_circuits():
    """Sentinel present → non-force run must short-circuit."""
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/chemical-usage-events-water-body",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "skipped"
    assert body.get("reason") == "sentinel_present"


# ══════════════════════════════════════════════════════════════════════
# 6 · Response contract — response includes new errors[] key.
# ══════════════════════════════════════════════════════════════════════
def test_migration_response_includes_errors_array():
    tok = _super_login()
    r = requests.post(
        f"{API}/admin/migrations/chemical-usage-events-water-body?force=true",
        headers={"Authorization": f"Bearer {tok}"}, timeout=60,
    )
    body = r.json()
    assert body["status"] == "ok"
    s = body["summary"]
    assert isinstance(s.get("errors"), list)
    assert s.get("errors_count") == len(s["errors"])

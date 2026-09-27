"""Feb-2026 · P0 · Chemical-save-before-status-flip + P45 claim rollback.

Locks the 5 contracts of the P0 fix:

  1. **Happy path** — submit a service_report with chemicals; verify
     (a) chemical_usage_events rows exist, (b) report.submitted_at
     is stamped, (c) job.status == "completed".

  2. **Fault-injection** — corrupt the chemical_costs catalog so
     ``snapshot_chemical_usage`` raises ``ValueError`` mid-loop; assert
     (a) HTTP 500 surfaces to caller,
     (b) job.status is NOT flipped (stays at the pre-submit value),
     (c) report.submitted_at is UNSET (P45 claim rolled back),
     (d) chemical_usage_events has NO partial writes.

  3. **Retry-after-fault** — same fault as (2), then restore the
     catalog and re-submit; assert the retry re-fires the snapshot
     (not short-circuited by the L708 idempotency check) and the
     full happy path completes.

  4. **Source-lint** — regex assert that in
     ``routers/service_reports.py`` the ``snapshot_chemical_usage(``
     call appears BEFORE the ``db.jobs.update_one(..., {"$set":
     _stop_updates})`` write in file byte-order.

  5. **Rollback idempotency** — trigger the rollback path TWICE
     via back-to-back HTTP submits under a corrupted catalog; assert
     the second rollback completes cleanly and leaves the row in
     the same unstamped state as the first.

  6. **Source-lint · rollback triple** — the ``$unset`` triple in
     ``rollback_submit_claim`` must mirror the ``$set`` triple in
     ``claim_submit_or_none`` verbatim.  A future refactor that
     adds a new stamped field to the claim MUST also add it to
     the rollback.

Notes on fault-injection strategy: the running FastAPI backend is
a separate process from pytest, so ``monkeypatch``-ing a Python
attribute in the test process would not reach the HTTP handler.
Instead, tests 2, 3, 5 write a DELIBERATELY-INVALID
``cost_per_unit_cents`` string into the tenant's chemical_costs
catalog — the running snapshot picks it up, ``int("not_a_number")``
raises ``ValueError`` inside the per-line loop, and the router's
try/except triggers the rollback + 500 path. This exercises the
production fault path 1:1 without any Python-level patching, and
without touching the test process's event loop state (which
would poison sibling tests that also use ``asyncio.new_event_loop()``).

Cleanup: seeded jobs / reports / events all prefixed with
``TEST-p0chemreorder-`` (ids) or ``TEST_P0ChemReorder_`` (job
titles). Module-scoped autouse fixture wipes on setup + teardown.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"
ROUTER_PATH = Path(__file__).resolve().parents[1] / "routers" / "service_reports.py"

_JOB_TITLE_PREFIX = "TEST_P0ChemReorder_"
_ID_PREFIX = "TEST-p0chemreorder-"
_CATALOG_SLUG = f"{_ID_PREFIX}muriatic-acid"

_LOOP = asyncio.new_event_loop()
# NB: intentionally NOT calling asyncio.set_event_loop(_LOOP) —
# doing so mutates the process's current-loop pointer, which
# poisons other test files that rely on asyncio.get_event_loop()
# at Motor client bind time. Every async op in this module goes
# through _run(coro) → _LOOP.run_until_complete(coro) which uses
# _LOOP explicitly without touching the global pointer.


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


async def _get_tenant_id(slug: str = "aquaterra") -> str:
    row = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    assert row, f"tenant slug={slug!r} not found — required seed"
    return row["id"]


async def _pick_customer_id(tenant_id: str) -> str:
    c = await _db().customers.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    assert c, "expected at least one customer in aquaterra"
    return c["id"]


async def _pick_admin_id(tenant_id: str) -> str:
    u = await _db().users.find_one(
        {"tenant_id": tenant_id, "email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1},
    )
    assert u, "admin@aquaterra.com is a required seed"
    return u["id"]


async def _seed_catalog(tenant_id: str, cost_cents: int = 500) -> None:
    """Idempotent — upserts the catalog row with a valid unit cost.
    Tests 2 and 3 corrupt this row's ``cost_per_unit_cents`` to a
    non-numeric string mid-test to force the snapshot to raise."""
    await _db().chemical_costs.update_one(
        {"tenant_id": tenant_id, "chemical_slug": _CATALOG_SLUG},
        {"$set": {
            "id": _CATALOG_SLUG,
            "tenant_id": tenant_id,
            "chemical_slug": _CATALOG_SLUG,
            "name": "TEST Muriatic Acid",
            "cost_per_unit_cents": cost_cents,
            "unit_kind": "gal",
        }},
        upsert=True,
    )


async def _corrupt_catalog(tenant_id: str) -> None:
    """Write a non-numeric ``cost_per_unit_cents`` so
    ``snapshot_chemical_usage``'s ``int(...)`` coerce raises
    ValueError inside the per-line insert loop. The corruption
    lives only in the seed catalog row and does NOT affect other
    tenants or other tests."""
    await _db().chemical_costs.update_one(
        {"tenant_id": tenant_id, "chemical_slug": _CATALOG_SLUG},
        {"$set": {"cost_per_unit_cents": "NOT_A_NUMBER_FAULT_INJECT"}},
    )


async def _seed_job_and_report(tenant_id: str, customer_id: str,
                                 actor_id: str) -> dict:
    from datetime import datetime, timezone
    job_id = f"{_ID_PREFIX}job-{uuid.uuid4().hex[:8]}"
    sr_id = f"{_ID_PREFIX}sr-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    scheduled = "2099-11-01T14:00:00+00:00"
    await _db().jobs.insert_one({
        "id": job_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": f"{_JOB_TITLE_PREFIX}{uuid.uuid4().hex[:6]}",
        "service_type": "pool",
        "job_type": "pool",
        "status": "scheduled",
        "scheduled_date": scheduled,
        "scheduled_start": scheduled,
        "technician_id": actor_id,
        "created_at": now, "updated_at": now,
    })
    await _db().service_reports.insert_one({
        "id": sr_id,
        "tenant_id": tenant_id,
        "job_id": job_id,
        "tech_id": actor_id,
        "template_kind": "pool",
        "created_at": now, "updated_at": now,
        "submitted_at": None,
        "chemical_readings": [
            {"key": "free_chlorine",  "value": 3.0},
            {"key": "ph",             "value": 7.5},
            {"key": "alkalinity",     "value": 100},
            {"key": "cyanuric_acid",  "value": 50},
        ],
        "chemicals_added": [
            {"product_slug": _CATALOG_SLUG,
              "name": "TEST Muriatic Acid",
              "quantity_used": 2, "unit": "gal"},
        ],
        "checklist_items": [], "photos": [], "notes": "",
    })
    return {"job_id": job_id, "service_report_id": sr_id}


async def _cleanup() -> None:
    seeded_job_ids = [j["id"] async for j in _db().jobs.find(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}},
        {"_id": 0, "id": 1},
    )]
    await _db().jobs.delete_many(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}})
    await _db().service_reports.delete_many(
        {"job_id": {"$in": seeded_job_ids}} if seeded_job_ids
        else {"id": {"$regex": f"^{_ID_PREFIX}"}})
    await _db().chemical_usage_events.delete_many(
        {"job_id": {"$in": seeded_job_ids}} if seeded_job_ids
        else {"service_report_id": {"$regex": f"^{_ID_PREFIX}"}})
    await _db().chemical_costs.delete_many(
        {"chemical_slug": _CATALOG_SLUG})


@pytest.fixture(scope="module", autouse=True)
def seed_ctx():
    tenant_id = _run(_get_tenant_id())
    customer_id = _run(_pick_customer_id(tenant_id))
    admin_id = _run(_pick_admin_id(tenant_id))
    _run(_cleanup())
    _run(_seed_catalog(tenant_id))
    seed = _run(_seed_job_and_report(tenant_id, customer_id, admin_id))
    yield {"tenant_id": tenant_id, "customer_id": customer_id,
             "admin_id": admin_id, **seed}
    _run(_cleanup())


# ═══════════════════════════════════════════════════════════════════
# 1) Happy path — chemicals ledger + submitted_at + status="completed"
# ═══════════════════════════════════════════════════════════════════
def test_happy_path_snapshot_precedes_status_flip(admin_headers, seed_ctx):
    jid = seed_ctx["job_id"]
    sr_id = seed_ctx["service_report_id"]

    r = requests.post(
        f"{API}/jobs/{jid}/service-report/submit",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text

    # (a) chemicals ledger row exists.
    async def _fetch_events():
        return [e async for e in _db().chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]
    events = _run(_fetch_events())
    assert len(events) == 1, (
        f"expected 1 chemical_usage_events row, got {len(events)}"
    )
    assert events[0]["unit_cost_at_time_cents"] == 500
    assert events[0]["total_cost_cents"] == 1000  # 2 gal * $5.00

    # (b) report.submitted_at is stamped.
    async def _fetch_report():
        return await _db().service_reports.find_one(
            {"id": sr_id}, {"_id": 0},
        )
    rep = _run(_fetch_report())
    assert rep.get("submitted_at"), (
        f"submitted_at should be stamped after happy-path submit: {rep}"
    )

    # (c) job.status flipped to "completed".
    async def _fetch_job():
        return await _db().jobs.find_one({"id": jid}, {"_id": 0})
    job = _run(_fetch_job())
    assert job.get("status") == "completed", (
        f"job.status should be completed after happy-path submit: {job}"
    )


# ═══════════════════════════════════════════════════════════════════
# 2) Fault path — snapshot raises → 500, status NOT flipped,
#                 submitted_at unset, no ledger rows
# ═══════════════════════════════════════════════════════════════════
def test_fault_path_snapshot_raises_rolls_back_p45_claim(
        admin_headers, seed_ctx):
    """Corrupt the tenant's chemical_costs row so the running
    snapshot raises ValueError inside its per-line insert loop;
    verify the router's rollback + 500 path fires end-to-end."""
    tenant_id = seed_ctx["tenant_id"]

    async def _new_seed():
        return await _seed_job_and_report(
            tenant_id, seed_ctx["customer_id"], seed_ctx["admin_id"],
        )
    new_seed = _run(_new_seed())
    jid = new_seed["job_id"]
    sr_id = new_seed["service_report_id"]

    async def _pre_status():
        j = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
        return (j or {}).get("status")
    pre_status = _run(_pre_status())
    assert pre_status == "scheduled", (
        f"seed job should start at scheduled, got {pre_status}"
    )

    # Corrupt the catalog to force snapshot to raise on this run.
    _run(_corrupt_catalog(tenant_id))
    try:
        r = requests.post(
            f"{API}/jobs/{jid}/service-report/submit",
            headers=admin_headers, timeout=30,
        )
    finally:
        # ALWAYS restore the catalog so downstream tests (retry,
        # rollback-idempotency) see a healthy row.
        _run(_seed_catalog(tenant_id))

    # (a) 500 propagates with the expected error code.
    assert r.status_code == 500, (
        f"expected 500 on snapshot fault, got {r.status_code}: {r.text}"
    )
    detail = (r.json() or {}).get("detail") or {}
    assert detail.get("code") == "chemistry_snapshot_failed", (
        f"expected chemistry_snapshot_failed code, got {detail}"
    )

    # (b) job.status is NOT flipped.
    async def _post_status():
        j = await _db().jobs.find_one({"id": jid}, {"_id": 0, "status": 1})
        return (j or {}).get("status")
    post_status = _run(_post_status())
    assert post_status == pre_status, (
        f"job.status must NOT flip on snapshot fault — was {pre_status},"
        f" is {post_status}"
    )

    # (c) report.submitted_at is UNSET (rolled back by
    #     rollback_submit_claim). Same for email_pending_at,
    #     sms_pending_at.
    async def _post_rep():
        return await _db().service_reports.find_one(
            {"id": sr_id}, {"_id": 0},
        )
    rep = _run(_post_rep())
    assert not rep.get("submitted_at"), (
        f"submitted_at must be rolled back — got {rep.get('submitted_at')}"
    )
    assert not rep.get("email_pending_at"), (
        f"email_pending_at must be rolled back — got"
        f" {rep.get('email_pending_at')}"
    )
    assert not rep.get("sms_pending_at"), (
        f"sms_pending_at must be rolled back — got"
        f" {rep.get('sms_pending_at')}"
    )

    # (d) chemical_usage_events has NO partial writes for this
    #     service_report_id.  The seed has no prior events, so
    #     delete_many-first-then-insert-fails leaves the ledger
    #     empty for this sr_id.
    async def _fetch_events():
        return [e async for e in _db().chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]
    events = _run(_fetch_events())
    assert events == [], (
        f"chemistry ledger must have no partial writes on fault, got"
        f" {len(events)}"
    )


# ═══════════════════════════════════════════════════════════════════
# 3) Retry-after-fault — second submit re-fires snapshot (P45
#                        short-circuit correctly bypassed)
# ═══════════════════════════════════════════════════════════════════
def test_retry_after_fault_re_fires_snapshot(admin_headers, seed_ctx):
    """First submit under a corrupted catalog: 500 + rollback.
    Second submit with a healthy catalog: must fire snapshot again
    (proves the L708 ``if rep.get('submitted_at')`` short-circuit
    does NOT trip because the P45 claim was rolled back)."""
    tenant_id = seed_ctx["tenant_id"]

    async def _new_seed():
        return await _seed_job_and_report(
            tenant_id, seed_ctx["customer_id"], seed_ctx["admin_id"],
        )
    new_seed = _run(_new_seed())
    jid = new_seed["job_id"]
    sr_id = new_seed["service_report_id"]

    # ── Attempt 1 — corrupted catalog ───────────────────────────
    _run(_corrupt_catalog(tenant_id))
    try:
        r1 = requests.post(
            f"{API}/jobs/{jid}/service-report/submit",
            headers=admin_headers, timeout=30,
        )
    finally:
        _run(_seed_catalog(tenant_id))
    assert r1.status_code == 500, r1.text

    # Rollback landed?
    async def _pre_retry_rep():
        return await _db().service_reports.find_one(
            {"id": sr_id}, {"_id": 0},
        )
    rep_pre = _run(_pre_retry_rep())
    assert not rep_pre.get("submitted_at"), (
        f"submitted_at should be rolled back before retry — got {rep_pre}"
    )

    # ── Attempt 2 — healthy catalog ─────────────────────────────
    r2 = requests.post(
        f"{API}/jobs/{jid}/service-report/submit",
        headers=admin_headers, timeout=30,
    )
    assert r2.status_code == 200, (
        f"retry should succeed under healthy catalog — got"
        f" {r2.status_code}: {r2.text}. If this returns 200 but the"
        f" body is the CACHED unsubmitted rep, the L708 idempotency"
        f" short-circuit tripped (rollback failed to unset"
        f" submitted_at)."
    )

    # Retry produced the ledger + status flip + submitted_at.
    async def _fetch_events():
        return [e async for e in _db().chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]
    events = _run(_fetch_events())
    assert len(events) == 1, (
        f"retry should have written 1 chemistry event, got {len(events)}"
        f" — if 0, the L708 idempotency short-circuit likely tripped"
    )
    async def _post_retry_job():
        return await _db().jobs.find_one({"id": jid}, {"_id": 0})
    job_after = _run(_post_retry_job())
    assert job_after.get("status") == "completed", (
        f"retry should have flipped status — got {job_after.get('status')}"
    )
    async def _post_retry_rep():
        return await _db().service_reports.find_one(
            {"id": sr_id}, {"_id": 0},
        )
    rep_after = _run(_post_retry_rep())
    assert rep_after.get("submitted_at"), (
        f"retry should have stamped submitted_at — got {rep_after}"
    )


# ═══════════════════════════════════════════════════════════════════
# 4) Source-lint — snapshot call appears BEFORE the status flip
# ═══════════════════════════════════════════════════════════════════
def test_source_lint_snapshot_precedes_status_flip():
    """In ``routers/service_reports.py``, the
    ``snapshot_chemical_usage(`` call must appear BEFORE the
    ``db.jobs.update_one({...}, {"$set": _stop_updates})`` write in
    file byte order. Uses regex anchors so a benign refactor of the
    surrounding code doesn't break the test — only a re-reorder
    would.

    The ``_stop_updates`` dict (defined earlier in the handler)
    unconditionally includes ``"status": "completed"``, so the
    ``db.jobs.update_one(..., {"$set": _stop_updates})`` write IS
    the status flip.
    """
    src = ROUTER_PATH.read_text(encoding="utf-8")
    # The snapshot call inside the submit handler is the first
    # occurrence of ``await snapshot_chemical_usage(`` in the file.
    m_snap = re.search(r"await\s+snapshot_chemical_usage\s*\(", src)
    assert m_snap, "snapshot_chemical_usage call not found in router"

    # The status flip is the first ``await db.jobs.update_one``
    # whose ``$set`` payload references ``_stop_updates`` — that
    # dict carries ``"status": "completed"``.
    m_flip = re.search(
        r'await\s+db\.jobs\.update_one\('
        r'[\s\S]{0,200}'
        r'\{"\$set":\s*_stop_updates\}',
        src,
    )
    assert m_flip, (
        "status-flip write (db.jobs.update_one with $set: _stop_updates)"
        " not found in router"
    )
    assert m_snap.start() < m_flip.start(), (
        f"snapshot_chemical_usage (byte {m_snap.start()}) MUST precede"
        f" the status flip (byte {m_flip.start()}) — P0 fix regressed"
    )

    # Rollback wiring must be present in the fault handler.
    assert "rollback_submit_claim" in src, (
        "rollback_submit_claim import/call must be present in the"
        " snapshot fault handler"
    )
    assert "chemistry_snapshot_failed" in src, (
        "chemistry_snapshot_failed error code must be surfaced on"
        " the fault path"
    )


# ═══════════════════════════════════════════════════════════════════
# 5) Rollback idempotency — safe to fire twice on the same report
# ═══════════════════════════════════════════════════════════════════
def test_rollback_submit_claim_is_idempotent(admin_headers, seed_ctx):
    """Trigger the rollback path TWICE on the same service_report
    via the HTTP handler.  Contract: the second rollback must
    complete cleanly (no error) and leave the row in the same
    unsubmitted / unstamped state as the first.

    Rollback is triggered by re-submitting under a corrupted
    catalog: on both submits, ``claim_submit_or_none`` matches
    (since ``submitted_at`` is unset going into each call — the
    prior rollback cleaned it), the snapshot raises, and the
    router runs ``rollback_submit_claim``.  This exercises the
    idempotent-``$unset`` shape of the rollback: on submit 1 the
    fields exist (stamped by claim), on submit 2 the fields also
    exist (re-stamped by the second claim), so the $unset acts
    identically both times.  A source-lint assertion below locks
    the exact triple the rollback unsets.

    Direct-calling the gate helper across test loops (as an
    earlier draft did) creates a Motor cross-loop failure because
    ``services.service_report_submit_gate.db`` is bound at gate
    module import time and cannot be safely re-bound mid-suite
    without also rebinding config.db and every dependent router
    module — HTTP round-trips sidestep the entire issue by
    running the operation inside the backend process's own loop.
    """
    tenant_id = seed_ctx["tenant_id"]

    async def _new_seed():
        return await _seed_job_and_report(
            tenant_id, seed_ctx["customer_id"], seed_ctx["admin_id"],
        )
    new_seed = _run(_new_seed())
    jid = new_seed["job_id"]
    sr_id = new_seed["service_report_id"]

    async def _fetch():
        return await _db().service_reports.find_one(
            {"id": sr_id}, {"_id": 0},
        )

    # ── First fault + rollback ─────────────────────────────────
    _run(_corrupt_catalog(tenant_id))
    try:
        r1 = requests.post(
            f"{API}/jobs/{jid}/service-report/submit",
            headers=admin_headers, timeout=30,
        )
    finally:
        # Do NOT restore yet — we want the second submit to also fault.
        pass
    assert r1.status_code == 500, r1.text
    rep_after_1 = _run(_fetch())
    assert not rep_after_1.get("submitted_at"), (
        f"first rollback should have unset submitted_at — got"
        f" {rep_after_1}"
    )
    assert not rep_after_1.get("email_pending_at")
    assert not rep_after_1.get("sms_pending_at")

    # ── Second fault + rollback (idempotency exercise) ─────────
    try:
        r2 = requests.post(
            f"{API}/jobs/{jid}/service-report/submit",
            headers=admin_headers, timeout=30,
        )
    finally:
        _run(_seed_catalog(tenant_id))
    assert r2.status_code == 500, (
        f"second submit should still 500 under corrupted catalog"
        f" (proves the P45 gate + snapshot + rollback all fired again"
        f" on the same row) — got {r2.status_code}: {r2.text}"
    )
    rep_after_2 = _run(_fetch())
    assert not rep_after_2.get("submitted_at"), (
        f"second rollback should have unset submitted_at — got"
        f" {rep_after_2}"
    )
    assert not rep_after_2.get("email_pending_at")
    assert not rep_after_2.get("sms_pending_at")
    # Row identity + tenant_id unchanged.
    assert rep_after_2.get("id") == rep_after_1.get("id")
    assert rep_after_2.get("tenant_id") == rep_after_1.get("tenant_id")


# ═══════════════════════════════════════════════════════════════════
# 6) Source-lint · rollback unsets EXACTLY the triple claim stamps
# ═══════════════════════════════════════════════════════════════════
def test_source_lint_rollback_unsets_claim_triple():
    """The rollback helper must $unset exactly the 3 fields the
    claim gate $sets: ``submitted_at``, ``email_pending_at``,
    ``sms_pending_at``. A future refactor of ``claim_submit_or_none``
    that adds a new stamped field MUST also add it to the rollback.
    This lint guards the drift.
    """
    gate_src = (Path(__file__).resolve().parents[1]
                 / "services" / "service_report_submit_gate.py").read_text(
                    encoding="utf-8")
    # Locate the claim gate $set block.
    m_set = re.search(
        r'update\s*=\s*\{"\$set":\s*\{([\s\S]{20,400}?)\}\}',
        gate_src,
    )
    assert m_set, "claim_submit_or_none $set block not found"
    set_body = m_set.group(1)
    set_keys = set(re.findall(r'"([a-z_]+)":\s*now_iso', set_body))
    assert set_keys == {"submitted_at", "email_pending_at", "sms_pending_at"}, (
        f"unexpected claim $set keys: {set_keys}"
    )

    # Locate the rollback $unset block (must exist post-P0).
    m_unset = re.search(
        r'unset\s*=\s*\{"\$unset":\s*\{([\s\S]{20,400}?)\}\}',
        gate_src,
    )
    assert m_unset, "rollback_submit_claim $unset block not found"
    unset_body = m_unset.group(1)
    unset_keys = set(re.findall(r'"([a-z_]+)":\s*""', unset_body))
    assert unset_keys == set_keys, (
        f"rollback $unset keys {unset_keys} MUST mirror claim $set"
        f" keys {set_keys} — drift will lose retry correctness"
    )

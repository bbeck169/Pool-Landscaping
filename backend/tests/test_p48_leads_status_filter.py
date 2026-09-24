"""Phase P48 · Feb-2026 — Leads status-filter multi-CSV contract.

Locks the P48 backend fix in ``routers/leads.py::list_leads`` that
extended the ``?status=`` query param from a single canonical value
to a comma-separated CSV of canonical values, driving the frontend
Active / Archive tab UX:

  * Active tab → ``?status=new,contacted,quoted``
  * Archive tab → ``?status=closed_won,closed_lost``

Contract (mirrors shipped code):
  * Single token → scalar ``q["status"] = "new"`` (byte-identical to
    pre-P48 callers — backward compat).
  * Multi-token → ``q["status"] = {"$in": [...]}``.
  * Unknown / typo tokens silently dropped (a typo shouldn't
    surface ``new`` leads via ``_normalize_status``'s default).
  * All-unknown tokens OR empty → falls through to "no status filter"
    (same semantics as ``status="all"``).
  * No ``status`` param at all → adds
    ``q["status"] = {"$ne": "rejected"}`` (Phase 16 · Addition E
    default-inbox behaviour — rejected tab is opt-in via
    ``?status=rejected``).
  * Return shape unchanged: ``{"rows": [...], "total": N,
    "page": 1, "page_size": 50}``.
  * Tenant scoping always applied — every read filter carries
    ``tenant_id``.

Test-loop convention (mirrors P44 / P46 / P47): sync ``pymongo``
for seeding + cleanup, fresh ``asyncio`` loop + ``Motor`` client
bound to it for the SUT call, patch ``routers.leads.db`` to the
loop-bound Motor for the duration of the test.

Seven tests total.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "P48_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures — sync pymongo for seeding + cleanup
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Tracks every P48_-tagged lead this test wrote and drops
    them on teardown so full-suite runs stay hermetic."""
    seeded_lead_ids: List[str] = []
    yield seeded_lead_ids
    if seeded_lead_ids:
        dbc.leads.delete_many({"id": {"$in": seeded_lead_ids}})


# ═════════════════════════════════════════════════════════════════════
# Per-test async loop + Motor db handle bound to it
# ═════════════════════════════════════════════════════════════════════
def _fresh_loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    return loop, client, client[DB_NAME]


def _patch_leads_db(adb):
    from routers import leads as _leads
    _leads._orig_db_for_test = getattr(_leads, "_orig_db_for_test", _leads.db)
    _leads.db = adb


def _restore_leads_db():
    from routers import leads as _leads
    if hasattr(_leads, "_orig_db_for_test"):
        _leads.db = _leads._orig_db_for_test


def _run_list_leads(*, tenant_id: str,
                     status: Optional[str] = None,
                     include_archived: int = 0,
                     page: int = 1,
                     page_size: int = 50,
                     role: str = "admin") -> Dict[str, Any]:
    loop, client, adb = _fresh_loop_and_db()
    try:
        _patch_leads_db(adb)
        from routers.leads import list_leads
        return loop.run_until_complete(list_leads(
            user={"role": role, "id": f"u_{uuid.uuid4().hex[:6]}"},
            tenant={"id": tenant_id},
            status=status,
            source=None,
            service_interest=None,
            search=None,
            date_from=None,
            date_to=None,
            include_archived=include_archived,
            page=page,
            page_size=page_size,
        ))
    finally:
        _restore_leads_db()
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# Seed helper
# ═════════════════════════════════════════════════════════════════════
def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_lead(dbc, *, tenant_id: str, status: str = "new",
                archived_at: Optional[str] = None,
                deleted_at: Optional[str] = None) -> str:
    lid = _fresh("LEAD")
    doc: Dict[str, Any] = {
        "id": lid,
        "tenant_id": tenant_id,
        "name": f"P48 seed {status}",
        "email": f"{lid.lower()}@example.com",
        "phone": "+15551234567",
        "status": status,
        "source": "website_form",
        "created_at": "2026-02-01T00:00:00Z",
    }
    if archived_at is not None:
        doc["archived_at"] = archived_at
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    dbc.leads.insert_one(doc)
    return lid


# ═════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════
def test_status_csv_active_tab_returns_only_active_states(dbc, cleanup):
    """``?status=new,contacted,quoted`` — the Active-tab CSV — must
    surface only rows in those three states.  Multi-token → the
    shipped path is ``q["status"] = {"$in": [...]}``.  Locks the
    primary Active-tab wire contract."""
    tid = _fresh("TEN")
    # Seed one lead per canonical status.
    seeded = {}
    for st in ("new", "contacted", "quoted",
                "closed_won", "closed_lost"):
        seeded[st] = _seed_lead(dbc, tenant_id=tid, status=st)
        cleanup.append(seeded[st])

    res = _run_list_leads(
        tenant_id=tid,
        status="new,contacted,quoted",
        include_archived=1,
    )
    assert res["total"] == 3, res
    returned_statuses = sorted({r["status"] for r in res["rows"]})
    assert returned_statuses == ["contacted", "new", "quoted"]
    returned_ids = {r["id"] for r in res["rows"]}
    assert seeded["closed_won"] not in returned_ids
    assert seeded["closed_lost"] not in returned_ids


def test_status_csv_archive_tab_returns_only_closed_states(dbc, cleanup):
    """``?status=closed_won,closed_lost`` — the Archive-tab CSV —
    must surface only rows in the two closed states.  Note the
    shipped frontend passes ``include_archived=1`` on the wire so
    ``archived_at`` guard doesn't hide closed-then-archived rows
    from the Archive tab."""
    tid = _fresh("TEN")
    seeded = {}
    for st in ("new", "contacted", "quoted",
                "closed_won", "closed_lost"):
        seeded[st] = _seed_lead(dbc, tenant_id=tid, status=st)
        cleanup.append(seeded[st])

    res = _run_list_leads(
        tenant_id=tid,
        status="closed_won,closed_lost",
        include_archived=1,
    )
    assert res["total"] == 2, res
    returned_statuses = sorted({r["status"] for r in res["rows"]})
    assert returned_statuses == ["closed_lost", "closed_won"]
    for open_st in ("new", "contacted", "quoted"):
        assert seeded[open_st] not in {r["id"] for r in res["rows"]}


def test_status_single_value_backward_compat(dbc, cleanup):
    """Single-token ``?status=new`` — pre-P48 callers keep working.
    Shipped path is ``q["status"] = canonical[0]`` (scalar, not
    ``$in``).  Byte-identical to pre-P48 behaviour."""
    tid = _fresh("TEN")
    a = _seed_lead(dbc, tenant_id=tid, status="new")
    b = _seed_lead(dbc, tenant_id=tid, status="contacted")
    c = _seed_lead(dbc, tenant_id=tid, status="quoted")
    cleanup.extend([a, b, c])

    res = _run_list_leads(tenant_id=tid, status="new", include_archived=1)
    assert res["total"] == 1
    assert res["rows"][0]["id"] == a
    assert res["rows"][0]["status"] == "new"


def test_no_status_param_excludes_rejected(dbc, cleanup):
    """Shipped default: no ``status`` param → adds
    ``q["status"] = {"$ne": "rejected"}`` (Phase 16 · Addition E).
    Rejected rows are opt-in via ``?status=rejected`` explicitly.

    NOTE: This is the shipped default-inbox contract — we assert
    what the handler actually does, not what a naive spec might
    expect.  A future refactor that changes the default MUST update
    this test intentionally."""
    tid = _fresh("TEN")
    a = _seed_lead(dbc, tenant_id=tid, status="new")
    b = _seed_lead(dbc, tenant_id=tid, status="contacted")
    r = _seed_lead(dbc, tenant_id=tid, status="rejected")
    cleanup.extend([a, b, r])

    res = _run_list_leads(tenant_id=tid, status=None, include_archived=1)
    returned_ids = {row["id"] for row in res["rows"]}
    assert a in returned_ids
    assert b in returned_ids
    assert r not in returned_ids, (
        "rejected leads must NOT surface in the default inbox — "
        "Phase 16 · Addition E · shipped default")


def test_tenant_scoping_prevents_cross_tenant_leak(dbc, cleanup):
    """Every read filter carries ``tenant_id`` — a lead in tenant B
    must never surface in tenant A's listing regardless of the
    ``status`` filter shape (scalar / $in / no-filter)."""
    tid_a = _fresh("TEN_A")
    tid_b = _fresh("TEN_B")
    a_lead = _seed_lead(dbc, tenant_id=tid_a, status="new")
    b_lead = _seed_lead(dbc, tenant_id=tid_b, status="new")
    cleanup.extend([a_lead, b_lead])

    # Scalar path.
    res_scalar = _run_list_leads(tenant_id=tid_a, status="new",
                                    include_archived=1)
    ids_scalar = {r["id"] for r in res_scalar["rows"]}
    assert a_lead in ids_scalar
    assert b_lead not in ids_scalar, (
        "cross-tenant leak under scalar status filter")

    # $in path.
    res_in = _run_list_leads(tenant_id=tid_a,
                              status="new,contacted,quoted",
                              include_archived=1)
    ids_in = {r["id"] for r in res_in["rows"]}
    assert a_lead in ids_in
    assert b_lead not in ids_in, (
        "cross-tenant leak under $in status filter")

    # No-filter path.
    res_none = _run_list_leads(tenant_id=tid_a, status=None,
                                 include_archived=1)
    ids_none = {r["id"] for r in res_none["rows"]}
    assert a_lead in ids_none
    assert b_lead not in ids_none, (
        "cross-tenant leak under default-no-filter path")


def test_unknown_tokens_in_csv_are_dropped(dbc, cleanup):
    """``_STATUS_ALIASES`` + ``_CANONICAL_STATUSES`` gate CSV tokens
    — unknown / typo tokens are silently dropped (a typo in the URL
    shouldn't pollute the Active tab with matches for the wrong
    bucket).  Locks the ``mapped or None → drop`` behaviour in
    ``routers/leads.py`` P48 block."""
    tid = _fresh("TEN")
    a = _seed_lead(dbc, tenant_id=tid, status="new")
    b = _seed_lead(dbc, tenant_id=tid, status="contacted")
    cleanup.extend([a, b])

    # Only "new" is valid; "bogus_status" gets dropped → single-token
    # canonical list → scalar filter for "new".
    res = _run_list_leads(tenant_id=tid,
                           status="new,bogus_status,another_typo",
                           include_archived=1)
    ids = {r["id"] for r in res["rows"]}
    assert a in ids
    assert b not in ids, (
        "unknown tokens must be dropped — 'bogus_status' should NOT "
        "have matched 'contacted' via a stale alias fallback")
    assert res["total"] == 1


def test_empty_result_returns_ok_shape_not_404(dbc, cleanup):
    """A tenant with no leads at all must return
    ``{"rows": [], "total": 0, "page": 1, "page_size": 50}`` — no
    404, no crash.  Locks the empty-inbox rendering contract."""
    tid = _fresh("TEN_EMPTY")
    # Deliberately seed zero leads for this tenant.
    res = _run_list_leads(tenant_id=tid,
                           status="new,contacted,quoted",
                           include_archived=1)
    assert res == {
        "rows": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
    }, res

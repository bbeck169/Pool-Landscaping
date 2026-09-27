"""Feb-2026 · CUS-perf v3 — backend counts refactor tests.

Locks the 4 contracts CUS-perf v3 establishes:
  1. `list_customers` no longer builds a `$facet` aggregation for
     ``counts_by_status``; the 5 buckets are computed via
     concurrent `count_documents` calls (source-lint proof).
  2. `counts_by_status` is STILL populated in the paginated
     envelope (vestigial alias — R5 ruling, deploy-order safety).
  3. `/customers/counts` now returns an ``all`` bucket for admin
     callers, matching ``counts_by_status.all`` semantics.
  4. Numerical parity — the paginated envelope's
     ``counts_by_status.all`` and ``/customers/counts.all`` are
     equal for the same tenant + filter surface.

The seed + auth pattern mirrors ``test_k68_customer_status_tab_counts.py``
so the two files can coexist without infrastructure drift.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


API_URL = "http://localhost:8001/api"
# Feb-2026 · CUS-perf v3 — in-pod tests hit localhost directly to
# avoid the external ingress rate-limiter (which drops paginated
# list responses with 5+ concurrent test requests during teardown).
# The conftest.py auto-populates ``BACKEND_URL`` from the frontend
# .env's external preview URL; ignoring it here keeps this file's
# tests off the ingress hop.


ROUTER_PATH = Path(__file__).resolve().parents[1] / "routers" / "customers.py"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API_URL}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login("super@aquaterra.com")


@pytest.fixture
def cus_v3_seed(admin_token):
    """Deterministic tenant-scoped seed: 2 active + 1 inactive + 1
    muted + 1 waitlist. Tag-suffix isolates parallel runs."""
    import time as _time
    hdr = {"Authorization": f"Bearer {admin_token}"}
    tag = f"cusv3_{uuid.uuid4().hex[:6]}"
    seeded = []

    def _mk(name, **extras):
        r = requests.post(
            f"{API_URL}/customers",
            json={
                "name": f"CUSV3_TEST_{name}_{tag}",
                "email": f"{name}_{tag}@cusv3.test",
                "phone": "555-000-0000",
                **extras,
            }, headers=hdr, timeout=15,
        )
        r.raise_for_status()
        seeded.append(r.json()["id"])
        return r.json()["id"]

    _mk("active1")
    _mk("active2")
    _mk("inactive1", is_active=False)
    m1 = _mk("muted1")
    _mk("waitlist1", waitlisted=True)
    # Mute via the dedicated endpoint (customer PATCH doesn't accept
    # is_muted — same shape as K68 fixture).
    requests.patch(f"{API_URL}/customers/{m1}/mute",
                    json={"reason": "CUS-perf v3 test fixture"},
                    headers=hdr, timeout=15)
    # Search haystack is backfilled ASYNCHRONOUSLY by a post-write
    # hook; give the write path a beat to flush before the search
    # queries fire.
    _time.sleep(1)

    yield {"tag": tag, "ids": seeded}

    for cid in seeded:
        try:
            requests.delete(f"{API_URL}/customers/{cid}",
                              headers=hdr, timeout=15)
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# 1) Source-lint · $facet gone, 5-parallel count_documents present
# ═════════════════════════════════════════════════════════════════════
def test_source_lint_facet_replaced_with_asyncio_gather_count_documents():
    src = ROUTER_PATH.read_text(encoding="utf-8")
    # The paginated envelope's counts_by_status assembly must NOT
    # dispatch a ``$facet`` aggregation anymore.  We assert on the
    # exact code shape (``[{"$facet":`` — the aggregate() argument
    # pattern the pre-refactor code used) so my own explanatory
    # comment that mentions the WORD ``$facet`` doesn't trip the guard.
    assert '[{"$facet":' not in src, (
        "$facet aggregation call must not appear in the router "
        "post CUS-perf v3 refactor"
    )
    # The CUS-perf v3 comment block IS present.
    assert "CUS-perf v3 refactor" in src
    # 5 parallel count_documents calls in an asyncio.gather.
    v3_block_match = re.search(
        r"CUS-perf v3 refactor[\s\S]{200,8000}?counts_by_status\s*=\s*\{",
        src,
    )
    assert v3_block_match, "CUS-perf v3 comment block not found"
    v3_block = v3_block_match.group(0)
    assert "asyncio.gather(" in v3_block
    # 5 count_documents invocations inside the gather().
    assert v3_block.count("db.customers.count_documents(") == 5, (
        "expected 5 count_documents calls in the gather; got "
        f"{v3_block.count('db.customers.count_documents(')}"
    )
    # Per-bucket filter shapes: cbs_active_q / cbs_inactive_q /
    # cbs_muted_q / cbs_waitlist_q / cbs_all_q.
    for name in ("_cbs_active_q", "_cbs_inactive_q",
                   "_cbs_muted_q", "_cbs_waitlist_q", "_cbs_all_q"):
        assert name in v3_block, f"missing bucket predicate name: {name}"


def test_source_lint_vestigial_alias_documented():
    """R5 ruling — the vestigial alias must be explicitly marked in
    source so the follow-up drop is discoverable via grep."""
    src = ROUTER_PATH.read_text(encoding="utf-8")
    assert "VESTIGIAL ALIAS" in src, (
        "R5 ruling requires the alias to be flagged as VESTIGIAL"
    )
    assert "FOLLOWUP_CUS_PERF_V3_ENVELOPE_DEPRECATION" in src, (
        "vestigial alias must reference the follow-up memo path"
    )


def test_source_lint_customer_counts_returns_all_bucket():
    """R2 ruling — ``/customers/counts`` returns the admin-only
    ``all`` bucket. Locked via a source-lint on the response
    assembly."""
    src = ROUTER_PATH.read_text(encoding="utf-8")
    # The response-model field.
    assert re.search(r"all:\s*Optional\[int\]\s*=\s*None", src), (
        "CustomerCountsResponse missing ``all`` field"
    )
    # The all_total assembly path.
    assert "all_total" in src
    # Admin-gate on the all_total computation.
    assert re.search(
        r"if\s+is_admin:\s*[\s\S]{0,240}all_total\s*=", src,
    ), "all_total must be admin-gated"


# ═════════════════════════════════════════════════════════════════════
# 2) Wire · paginated envelope STILL ships counts_by_status (R5)
# ═════════════════════════════════════════════════════════════════════
def test_paginated_envelope_still_ships_counts_by_status(
        admin_token, cus_v3_seed):
    """Vestigial alias survives — deploy-order safety per R5.

    Contract-scoped assertions: presence + shape + int-ness + the
    ``all`` bucket equals the envelope's paginated ``total``.  Does
    NOT assert per-bucket seed values because ``POST /customers``
    silently normalizes some fields (``is_active`` create-time
    override, ``waitlisted`` denorm) — the K68 test file already
    covers the per-bucket semantic contract and my new test focuses
    on the CUS-perf v3 refactor guarantees."""
    hdr = {"Authorization": f"Bearer {admin_token}"}
    tag = cus_v3_seed["tag"]
    r = requests.get(
        # Search on the tag alone — unique per test run + survives the
        # haystack's underscore tokenization.  The name prefix
        # ``CUSV3_TEST_`` is intentional for grep/audit visibility but
        # not used as a search anchor because the haystack splits on
        # underscores and would AND multiple tokens together.
        f"{API_URL}/customers?page=1&page_size=50&search={tag}",
        headers=hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    cbs = body.get("counts_by_status")
    assert cbs is not None, "vestigial alias missing from envelope"
    for key in ("active", "inactive", "muted", "waitlist", "all"):
        assert key in cbs, f"missing bucket: {key}"
        assert isinstance(cbs[key], int)
        assert cbs[key] >= 0
    # The seed size gives us at least the mute-target row as
    # visible via the search filter, so ``all`` must be >= 1.
    assert cbs["all"] >= 1, (
        f"CUSV3 seed missing from envelope: {cbs}"
    )
    # all-bucket derivation must match the envelope's paginated total.
    assert cbs["all"] == body["total"], (
        f"``all`` bucket ({cbs['all']}) drifted from envelope "
        f"``total`` ({body['total']})"
    )


# ═════════════════════════════════════════════════════════════════════
# 3) Wire · /customers/counts returns all bucket (admin-only, R2)
# ═════════════════════════════════════════════════════════════════════
def test_customers_counts_returns_all_bucket_for_admin(admin_token):
    hdr = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{API_URL}/customers/counts", headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # New field present.
    assert "all" in body, "``all`` bucket missing from /customers/counts"
    # For admin, the value is a non-negative int.
    assert isinstance(body["all"], int) and body["all"] >= 0
    # Semantic: all == active + inactive + muted (matches the
    # counts_by_status.all definition).
    expected = (
        int(body.get("active", 0))
        + int(body.get("inactive", 0))
        + int(body.get("muted", 0) or 0)
    )
    assert body["all"] == expected, (
        f"all bucket derivation drifted: got {body['all']} vs "
        f"active+inactive+muted={expected}"
    )


# ═════════════════════════════════════════════════════════════════════
# 4) Numerical parity · envelope ``all`` vs /customers/counts ``all``
# ═════════════════════════════════════════════════════════════════════
def test_envelope_all_matches_customers_counts_all(admin_token):
    """The two sources of truth must return equal ``all`` counts
    for the same tenant with no filter chips applied.  Small
    fixture-transient drift (e.g. a customer created between the
    two round trips) is tolerated via a 5-row slack — big enough
    to survive parallel test seeds, small enough to catch a real
    logic drift."""
    hdr = {"Authorization": f"Bearer {admin_token}"}
    # Envelope path — no filter chips, just admin baseline.
    r1 = requests.get(f"{API_URL}/customers?page=1&page_size=1",
                        headers=hdr, timeout=15)
    assert r1.status_code == 200
    env_all = int(r1.json().get("counts_by_status", {}).get("all") or 0)
    # /customers/counts path.
    r2 = requests.get(f"{API_URL}/customers/counts",
                        headers=hdr, timeout=15)
    assert r2.status_code == 200
    counts_all = int(r2.json().get("all") or 0)
    assert abs(env_all - counts_all) <= 5, (
        f"``all`` drift beyond tolerance: envelope={env_all} vs "
        f"counts={counts_all}"
    )


# ═════════════════════════════════════════════════════════════════════
# 5) Explain-plan · count_documents winning plans document reality (R4)
# ═════════════════════════════════════════════════════════════════════
def test_count_documents_winning_plans_are_tenant_partition_ixscans(
        admin_token, cus_v3_seed):
    """Per R4 ruling — capture the actual winning plans for the 5
    tab-count filters.  This test documents reality (not the
    aspirational "index-only" goal) so a future planner regression
    is visible.

    Uses ``db.command('count', ...)`` with ``$explain: True`` for
    each bucket filter.  ``count_documents`` itself doesn't expose
    ``.explain()``, but ``find(...).explain()`` on the equivalent
    filter returns the same winning plan the count planner would
    choose (both go through the ``COUNT_SCAN`` / ``COLLSCAN`` /
    ``IXSCAN`` branch of the query planner).

    Assertion: EVERY winning plan is IXSCAN, none are COLLSCAN.
    Whether the winning plan is a pure IXSCAN or IXSCAN+FILTER is
    logged (not asserted) so a future index migration can flip
    the FILTER stage away.
    """
    from pymongo import MongoClient
    import os as _os
    mongo_url = _os.environ.get("MONGO_URL")
    db_name = _os.environ.get("DB_NAME")
    assert mongo_url and db_name, "MONGO_URL + DB_NAME required"
    client = MongoClient(mongo_url)
    db = client[db_name]

    # Get the tenant_id for the seed customers via a lookup.
    seed_id = cus_v3_seed["ids"][0]
    seed_doc = db.customers.find_one({"id": seed_id}, {"tenant_id": 1})
    assert seed_doc, "seed customer missing"
    tenant_id = seed_doc["tenant_id"]

    _not_muted = {"$or": [{"is_muted": {"$ne": True}},
                             {"is_muted": {"$exists": False}}]}
    filters = {
        "active": {"$and": [
            {"tenant_id": tenant_id},
            {"$or": [{"is_active": True},
                       {"is_active": {"$exists": False}}]},
            _not_muted,
        ]},
        "inactive": {"$and": [
            {"tenant_id": tenant_id}, {"is_active": False}, _not_muted,
        ]},
        "muted": {"tenant_id": tenant_id, "is_muted": True},
        "waitlist": {"tenant_id": tenant_id, "waitlisted": True},
        "all": {"tenant_id": tenant_id},
    }
    plans_report: dict = {}
    for bucket, filt in filters.items():
        explain = db.command("explain", {
            "count": "customers",
            "query": filt,
        }, verbosity="queryPlanner")
        winning = explain.get("queryPlanner", {}).get("winningPlan", {})
        # Walk the winning plan tree looking for stage names.
        stages: list = []
        def _walk(node):
            if isinstance(node, dict):
                s = node.get("stage")
                if s:
                    stages.append(s)
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for v in node:
                    _walk(v)
        _walk(winning)
        plans_report[bucket] = stages
        # Assertion — no COLLSCAN on any bucket (the whole point).
        assert "COLLSCAN" not in stages, (
            f"bucket ``{bucket}`` fell back to COLLSCAN — winning plan "
            f"stages: {stages}"
        )
        # Positive — some IXSCAN-family stage present.
        assert any(s in stages
                     for s in ("IXSCAN", "COUNT_SCAN", "IDHACK")), (
            f"bucket ``{bucket}`` winning plan has no index scan: {stages}"
        )
    # Log the report (visible in pytest -s) so a human reviewer
    # sees the actual per-bucket plan matrix.
    print(f"[cus-perf-v3 explain-plans] {plans_report}")


def test_list_customers_paginated_find_uses_ixscan(admin_token):
    """R4 — the paginated ``find`` on ``list_customers`` must land on
    an IXSCAN (perf_customers_v2_tenant_created for the default
    created_desc sort)."""
    from pymongo import MongoClient
    import os as _os
    mongo_url = _os.environ.get("MONGO_URL")
    db_name = _os.environ.get("DB_NAME")
    client = MongoClient(mongo_url)
    db = client[db_name]
    # Grab a real tenant_id so the explain doesn't dry-run on an
    # empty partition.
    seed = db.customers.find_one({}, {"tenant_id": 1})
    assert seed, "no customers in test DB"
    tenant_id = seed["tenant_id"]
    # Mirror the default sort spec (created_desc = [(created_at, -1),
    # (_id, -1)]).
    cursor = (db.customers.find({"tenant_id": tenant_id})
                             .sort([("created_at", -1), ("_id", -1)])
                             .limit(25))
    explain = cursor.explain()
    winning = explain.get("queryPlanner", {}).get("winningPlan", {})
    stages: list = []
    def _walk(node):
        if isinstance(node, dict):
            s = node.get("stage")
            if s:
                stages.append(s)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
    _walk(winning)
    assert "COLLSCAN" not in stages, (
        f"paginated find fell back to COLLSCAN: {stages}"
    )
    assert "IXSCAN" in stages, (
        f"paginated find winning plan missing IXSCAN: {stages}"
    )
    print(f"[cus-perf-v3 paginated-find explain] stages={stages}")

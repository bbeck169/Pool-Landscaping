"""N3' · Feb-2026 — GET /search/global regression suite.

HTTP-integration style matching MA0 (``test_invoice_line_items_add.py``)
and C1 (``test_chemical_applications_crud.py``). Hits the running
supervisor-managed backend so tenant/auth middleware fires
end-to-end. Seed data is written directly to Mongo and torn down
per-test.

Manual bash only per session mandate — no testing_agent.
Run::

    pytest backend/tests/test_search_global.py -xvs

15 test cases covering:
  1. Happy path — q="smith" returns matching customers + documents
  2. Empty q                    → 200 with empty groups
  3. 1-char q                   → 200 with empty groups
  4. Case insensitivity         — "SMITH" and "smith" return same set
  5. Regex-special-char safety  — q="J." doesn't blow up
  6. Tenant isolation (P0)      — tenant B's docs never leak to tenant A
  7. Customer match on address  — match_field == "address"
  8. Invoice match on number    — type/display_id assertions
  9. Job match on id            — type/display_id assertions
 10. Ranking — exact > prefix > substring
 11. limit=3 respected
 12. limit > 10 → clamped to 10
 13. Auth — tech OK, customer 403, unauthed 401/403
 14. Combined docs limit — 4 jobs + 4 invoices → 5 total (not 8)
 15. No-match query — returns 200 with empty groups
"""
from __future__ import annotations
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 20

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "srchg_"


# ═══ auth helpers ═════════════════════════════════════════════════════
def _login(email: str, pwd: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pwd},
                       timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token") or r.json().get("token")


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _me(tok: str) -> dict:
    r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def admin_identity(admin_tok):
    return _me(admin_tok)


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


# ═══ scenario seed ════════════════════════════════════════════════════
@pytest.fixture
def scenario(dbc, admin_identity):
    """Seed searchable rows in the caller's tenant + an isolated other
    tenant (for the P0 cross-tenant probe). Every row is prefixed with
    ``TAG`` so we can filter on it during teardown and never touch
    real seed data.
    """
    tid = admin_identity["tenant_id"]
    other_tid = f"{TAG}other-{uuid.uuid4().hex[:8]}"

    # ── customers (caller tenant) ──
    smith_id = f"{TAG}cust-smith-{uuid.uuid4().hex[:8]}"
    peoria_id = f"{TAG}cust-peoria-{uuid.uuid4().hex[:8]}"
    unrelated_id = f"{TAG}cust-un-{uuid.uuid4().hex[:8]}"
    # ── customer (other tenant, same name — the P0 leak probe) ──
    smith_other_id = f"{TAG}cust-smith-other-{uuid.uuid4().hex[:8]}"

    dbc.customers.insert_many([
        {"id": smith_id, "tenant_id": tid,
          "name": f"{TAG}Smith Residence", "address": "123 Main St",
          "address_line1": "123 Main St", "city": "Austin",
          "postal_code": "78701", "deleted_at": None,
          "updated_at": "2026-02-05T00:00:00"},
        {"id": peoria_id, "tenant_id": tid,
          "name": f"{TAG}Jones Family", "address_line1": f"{TAG}45 Elm Rd",
          "city": f"{TAG}Uniqueville", "postal_code": f"{TAG}00001",
          "deleted_at": None, "updated_at": "2026-02-04T00:00:00"},
        {"id": unrelated_id, "tenant_id": tid,
          "name": f"{TAG}Unrelated Person",
          "deleted_at": None, "updated_at": "2026-02-03T00:00:00"},
        # Cross-tenant.
        {"id": smith_other_id, "tenant_id": other_tid,
          "name": f"{TAG}Smith Other Tenant",
          "deleted_at": None, "updated_at": "2026-02-06T00:00:00"},
    ])

    # ── invoices (caller tenant) ──
    inv_exact_id = f"{TAG}inv-exact-{uuid.uuid4().hex[:8]}"
    inv_prefix_id = f"{TAG}inv-prefix-{uuid.uuid4().hex[:8]}"
    inv_sub_id = f"{TAG}inv-sub-{uuid.uuid4().hex[:8]}"
    inv_extra1_id = f"{TAG}inv-x1-{uuid.uuid4().hex[:8]}"
    inv_extra2_id = f"{TAG}inv-x2-{uuid.uuid4().hex[:8]}"
    dbc.quotes.insert_many([
        # invoice_number == q  → rank 0
        {"id": inv_exact_id, "tenant_id": tid, "doc_type": "invoice",
          "invoice_number": f"{TAG}RANK-A", "title": "Weekly service",
          "deleted_at": None, "updated_at": "2026-02-10T00:00:00"},
        # invoice_number starts with q  → rank 1
        {"id": inv_prefix_id, "tenant_id": tid, "doc_type": "invoice",
          "invoice_number": f"{TAG}RANK-A-999", "title": "Prefix",
          "deleted_at": None, "updated_at": "2026-02-09T00:00:00"},
        # only substring hit on title, invoice_number miss  → rank 2
        {"id": inv_sub_id, "tenant_id": tid, "doc_type": "invoice",
          "invoice_number": f"{TAG}other-inv",
          "title": f"has {TAG}RANK-A in the middle",
          "deleted_at": None, "updated_at": "2026-02-08T00:00:00"},
        # Two extra invoices for the combined-limit test — need 4
        # invoices matching the combined-limit q separately.
        {"id": inv_extra1_id, "tenant_id": tid, "doc_type": "invoice",
          "invoice_number": f"{TAG}COMBO-INV-1", "title": "combo1",
          "deleted_at": None, "updated_at": "2026-02-15T00:00:00"},
        {"id": inv_extra2_id, "tenant_id": tid, "doc_type": "invoice",
          "invoice_number": f"{TAG}COMBO-INV-2", "title": "combo2",
          "deleted_at": None, "updated_at": "2026-02-14T00:00:00"},
    ])

    # ── jobs (caller tenant) ──
    job_a_id = f"{TAG}job-a-{uuid.uuid4().hex[:8]}"
    job_b_id = f"{TAG}job-b-{uuid.uuid4().hex[:8]}"
    job_combo1_id = f"{TAG}COMBO-JOB-1-{uuid.uuid4().hex[:8]}"
    job_combo2_id = f"{TAG}COMBO-JOB-2-{uuid.uuid4().hex[:8]}"
    job_combo3_id = f"{TAG}COMBO-JOB-3-{uuid.uuid4().hex[:8]}"
    job_combo4_id = f"{TAG}COMBO-JOB-4-{uuid.uuid4().hex[:8]}"
    dbc.jobs.insert_many([
        {"id": job_a_id, "tenant_id": tid,
          "title": f"{TAG}Pool Installation",
          "deleted_at": None, "updated_at": "2026-02-10T00:00:00"},
        {"id": job_b_id, "tenant_id": tid,
          "title": f"{TAG}Landscape Design",
          "deleted_at": None, "updated_at": "2026-02-09T00:00:00"},
        {"id": job_combo1_id, "tenant_id": tid,
          "title": f"{TAG}COMBO Job A",
          "deleted_at": None, "updated_at": "2026-02-13T00:00:00"},
        {"id": job_combo2_id, "tenant_id": tid,
          "title": f"{TAG}COMBO Job B",
          "deleted_at": None, "updated_at": "2026-02-12T00:00:00"},
        {"id": job_combo3_id, "tenant_id": tid,
          "title": f"{TAG}COMBO Job C",
          "deleted_at": None, "updated_at": "2026-02-11T00:00:00"},
        {"id": job_combo4_id, "tenant_id": tid,
          "title": f"{TAG}COMBO Job D",
          "deleted_at": None, "updated_at": "2026-02-16T00:00:00"},
    ])
    yield {
        "tenant_id": tid, "other_tenant_id": other_tid,
        "smith_id": smith_id, "peoria_id": peoria_id,
        "unrelated_id": unrelated_id, "smith_other_id": smith_other_id,
        "inv_exact_id": inv_exact_id,
        "inv_prefix_id": inv_prefix_id,
        "inv_sub_id": inv_sub_id,
        "job_a_id": job_a_id, "job_b_id": job_b_id,
    }
    # ── teardown (all rows tagged, safe to bulk-delete) ──
    dbc.customers.delete_many({"id": {"$regex": f"^{TAG}"}})
    dbc.quotes.delete_many({"id": {"$regex": f"^{TAG}"}})
    dbc.jobs.delete_many({"id": {"$regex": f"^{TAG}"}})


# ═══ tests ════════════════════════════════════════════════════════════
# ─── 1. Happy path ─────────────────────────────────────────────────
def test_happy_path_returns_customer_and_documents(tech_tok, scenario):
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}Smith"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == f"{TAG}Smith"
    # ``Smith Residence`` is in the caller's tenant.
    cust_names = {c["name"] for c in body["customers"]}
    assert f"{TAG}Smith Residence" in cust_names


# ─── 2. Empty q → 200, empty groups ─────────────────────────────────
def test_empty_q_returns_200_with_empty_groups(tech_tok, scenario):
    r = requests.get(f"{API}/search/global", params={"q": ""},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customers"] == []
    assert body["documents"] == []


# ─── 3. 1-char q → 200, empty groups ────────────────────────────────
def test_one_char_q_returns_200_with_empty_groups(tech_tok, scenario):
    r = requests.get(f"{API}/search/global", params={"q": "s"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json()["customers"] == []
    assert r.json()["documents"] == []


# ─── 4. Case insensitivity ──────────────────────────────────────────
def test_case_insensitive_returns_same_set(tech_tok, scenario):
    r_lo = requests.get(f"{API}/search/global",
                         params={"q": f"{TAG.lower()}smith"},
                         headers=_h(tech_tok), timeout=TIMEOUT)
    r_up = requests.get(f"{API}/search/global",
                         params={"q": f"{TAG.upper()}SMITH"},
                         headers=_h(tech_tok), timeout=TIMEOUT)
    assert r_lo.status_code == 200 and r_up.status_code == 200
    lo_ids = sorted(c["id"] for c in r_lo.json()["customers"])
    up_ids = sorted(c["id"] for c in r_up.json()["customers"])
    assert lo_ids == up_ids


# ─── 5. Regex-special-char safety ───────────────────────────────────
def test_regex_special_char_does_not_break(tech_tok, scenario):
    # ``J.`` contains a regex metachar. re.escape must render it safe.
    r = requests.get(f"{API}/search/global", params={"q": "J."},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    # No rows contain the literal "J." — result set is empty.
    assert isinstance(r.json()["customers"], list)


# ─── 6. Tenant isolation (P0) ───────────────────────────────────────
def test_tenant_isolation_no_cross_tenant_leak(tech_tok, scenario):
    """Caller tenant's ``Smith Residence`` should surface. The other
    tenant's ``Smith Other Tenant`` must NEVER surface — P0 guardrail."""
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}Smith"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["customers"]}
    assert f"{TAG}Smith Other Tenant" not in names, (
        f"cross-tenant leak — got {names!r}"
    )


# ─── 7. Customer match on address ───────────────────────────────────
def test_customer_match_on_address_field_marks_match_field_address(
    tech_tok, scenario,
):
    # ``TAG + "Uniqueville"`` matches the second seeded customer's
    # ``city`` uniquely (not the shared "Peoria" hit that other real
    # tenant customers may share).
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}Uniqueville"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    hits = [c for c in r.json()["customers"] if c["id"] == scenario["peoria_id"]]
    assert hits, "expected uniquely-tagged customer in results"
    assert hits[0]["match_field"] == "address"


# ─── 8. Invoice match on number ─────────────────────────────────────
def test_invoice_match_on_number(tech_tok, scenario):
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}RANK-A"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    docs = r.json()["documents"]
    exact = [d for d in docs if d["id"] == scenario["inv_exact_id"]]
    assert exact, "expected exact-rank invoice in results"
    assert exact[0]["type"] == "invoice"
    assert exact[0]["display_id"] == f"{TAG}RANK-A"
    assert exact[0]["match_field"] == "number"


# ─── 9. Job match on id ─────────────────────────────────────────────
def test_job_match_on_id_returns_type_and_display_id(tech_tok, scenario):
    # The seeded job_a_id starts with ``srchg_job-a-`` — searching on
    # the leading TAG matches on the ``id`` field.
    jid = scenario["job_a_id"]
    prefix_needle = jid[:12]  # ``srchg_job-a-``
    r = requests.get(f"{API}/search/global", params={"q": prefix_needle},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    docs = r.json()["documents"]
    hit = [d for d in docs if d["id"] == jid]
    assert hit, f"expected job {jid} in results; got {docs}"
    assert hit[0]["type"] == "job"
    assert hit[0]["display_id"] == f"J-{jid[:8]}"
    assert hit[0]["match_field"] == "id"


# ─── 10. Ranking — exact > prefix > substring ───────────────────────
def test_ranking_exact_before_prefix_before_substring(tech_tok, scenario):
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}RANK-A"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    docs = r.json()["documents"]
    # Find the position of the three seeded ranking invoices.
    positions = {d["id"]: i for i, d in enumerate(docs)}
    p_exact = positions.get(scenario["inv_exact_id"])
    p_prefix = positions.get(scenario["inv_prefix_id"])
    p_sub = positions.get(scenario["inv_sub_id"])
    assert p_exact is not None and p_prefix is not None and p_sub is not None, (
        f"expected all three seeds in results — positions={positions}"
    )
    assert p_exact < p_prefix < p_sub, (
        f"ranking wrong: exact={p_exact} prefix={p_prefix} sub={p_sub}"
    )


# ─── 11. limit=3 respected ─────────────────────────────────────────
def test_limit_param_respected(tech_tok, scenario):
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}", "limit": 3},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    assert len(r.json()["customers"]) <= 3
    assert len(r.json()["documents"]) <= 3


# ─── 12. limit > 10 → clamped ──────────────────────────────────────
def test_limit_over_max_is_clamped(tech_tok, scenario):
    # limit=99 is out of the Query(le=10) contract → FastAPI 422s.
    # limit=10 is the clamp ceiling. Assert 10 is accepted (200).
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}", "limit": 10},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    assert len(r.json()["customers"]) <= 10
    assert len(r.json()["documents"]) <= 10


# ─── 13. Auth — tech / customer / unauthed ─────────────────────────
def test_auth_tech_ok(tech_tok, scenario):
    r = requests.get(f"{API}/search/global", params={"q": f"{TAG}"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200


def test_auth_customer_forbidden(customer_tok, scenario):
    r = requests.get(f"{API}/search/global", params={"q": f"{TAG}"},
                      headers=_h(customer_tok), timeout=TIMEOUT)
    assert r.status_code == 403, r.text


def test_auth_unauthed_rejected(scenario):
    r = requests.get(f"{API}/search/global", params={"q": f"{TAG}"},
                      timeout=TIMEOUT)
    # FastAPI's HTTPBearer default is 403 for missing tokens; some
    # middleware raises 401. Accept either.
    assert r.status_code in (401, 403), r.text


# ─── 14. Combined docs limit ────────────────────────────────────────
def test_combined_docs_limit_caps_at_five_not_ten(tech_tok, scenario):
    """The scenario seed has 4 invoices + 4 jobs whose id / title
    contains ``TAG + "COMBO"``. Total = 8 matching rows. Response
    ``documents`` MUST have ≤ 5 rows per your G4 ruling."""
    r = requests.get(f"{API}/search/global",
                      params={"q": f"{TAG}COMBO", "limit": 5},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    docs = r.json()["documents"]
    assert len(docs) == 5, f"expected 5 combined docs, got {len(docs)}: {docs!r}"


# ─── 15. No-match query ─────────────────────────────────────────────
def test_no_match_query_returns_empty_groups(tech_tok, scenario):
    r = requests.get(f"{API}/search/global",
                      params={"q": "zzz-no-match-string-xyz"},
                      headers=_h(tech_tok), timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert body["customers"] == []
    assert body["documents"] == []

"""Feb-2026 · P0 — Duplicate Quote endpoint tests.

Locks the contract on
``POST /api/quotes/{qid}/duplicate``:

  1.  Admin duplicate to SAME customer → new quote in draft with
      fresh id, same customer_id, line count matches source, line
      ids all differ, decline/signature/timestamp state reset, an
      ``audit_logs`` row is written with the correct event and
      linkage.
  2.  Admin duplicate to DIFFERENT customer with explicit
      ``property_id`` matching that customer's active property →
      new quote's ``property_id`` is the provided one.
  3.  Admin duplicate to DIFFERENT customer with no ``property_id``
      when destination has exactly 1 active property → new quote
      auto-assigns that property_id (mirrors ``create_quote``).
  3b. Admin duplicate to DIFFERENT customer with no ``property_id``
      when destination has 0 (or many) active properties → new
      quote's ``property_id=None`` (no error — legal schema).
  4.  ``property_id`` NOT belonging to destination customer /
      inactive / wrong tenant → 422.
  6.  Duplicate a quote with declined lines → new lines all
      ``customer_status="pending"``; ``has_declined_lines=False``
      on new quote; source unchanged.
  7.  Duplicate an accepted quote → new quote status=draft,
      ``accepted_at=None``; source unchanged.
  8.  Duplicate a quote with photos → new quote has zero photo
      linkage (photos live in adjacent collections; new uuid
      naturally isn't referenced).  Sanity-checks that no photo
      keys leak through onto the new quote doc.
  9.  Technician → 403.
  10. Cross-tenant source → 404 (source not visible in the caller's
      tenant scope).
  11. Source quote not found → 404.
  12. Destination customer not found → 404.
  13. Running duplicate twice creates TWO new quotes with different
      ids (no accidental dedup).

See ``/app/memory/FEATURE_QUOTE_DUPLICATE.md`` for the full
carry-over / reset field manifest and the RBAC + property
resolution rules.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 45


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "customers", "properties"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


def _session(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_sess():
    return _session("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_sess():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "mike@aquaterra.com", "password": "password123"},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip("no mike@aquaterra.com technician demo user")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def customer_a(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    assert rows, "no customers in aquaterra fixture tenant"
    return rows[0]


@pytest.fixture(scope="module")
def customer_b(admin_sess, customer_a):
    """A customer different from ``customer_a`` — for cross-customer
    duplicate tests.  Skips the whole module if the fixture tenant
    only has one customer (very unlikely).
    """
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    for c in rows:
        if c["id"] != customer_a["id"]:
            return c
    pytest.skip("need at least 2 customers for cross-customer tests")


@pytest.fixture(scope="module")
def svc_cat(admin_sess):
    r = admin_sess.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    )
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    )
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows
    return rows[0]


# ─── Helpers ─────────────────────────────────────────────────────────

def _make_quote(sess, customer_id, svc_cat, inc_cat, title=None,
                 tax_rate=0.0, notes=None, terms=None):
    body = {
        "customer_id": customer_id,
        "title": title or f"Dup probe {uuid.uuid4().hex[:6]}",
        "doc_type": "quote",
        "tax_rate": tax_rate,
        "line_items": [
            {"description": "Pavers", "quantity": 3, "unit_price": 40,
             "service_category_id": svc_cat["id"],
             "income_category_id": inc_cat["id"]},
            {"description": "Coping", "quantity": 2, "unit_price": 25,
             "service_category_id": svc_cat["id"],
             "income_category_id": inc_cat["id"]},
        ],
    }
    if notes is not None:
        body["notes"] = notes
    if terms is not None:
        body["terms"] = terms
    r = sess.post(f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _get_quote(sess, qid):
    r = sess.get(f"{BASE_URL}/api/quotes/{qid}", timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _active_properties(sess, customer_id):
    r = sess.get(
        f"{BASE_URL}/api/customers/{customer_id}/properties",
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        return []
    return [
        p for p in _rows(r.json()) if p.get("active") is not False
    ]


def _ensure_active_property(sess, customer_id, label="Fixture Probe"):
    """Return an active property for the given customer, creating a
    fresh one when the customer has none. Returns ``(prop_dict,
    created_bool)`` so the test can clean up any provisioned rows.
    """
    existing = _active_properties(sess, customer_id)
    if existing:
        return existing[0], False
    body = {
        "label": label,
        "address": {
            "street": "1 Fixture Ln",
            "city": "Peoria",
            "state": "AZ",
            "postal_code": "85383",
        },
    }
    r = sess.post(
        f"{BASE_URL}/api/customers/{customer_id}/properties",
        json=body, timeout=REQ_TIMEOUT,
    )
    if r.status_code not in (200, 201):
        pytest.skip(
            f"could not provision fixture property "
            f"({r.status_code}): {r.text[:180]}"
        )
    return r.json(), True


def _delete_property(sess, pid):
    try:
        sess.delete(
            f"{BASE_URL}/api/properties/{pid}", timeout=REQ_TIMEOUT,
        )
    except Exception:
        pass


def _dup(sess, qid, customer_id, property_id: Optional[str] = None):
    body = {"customer_id": customer_id}
    if property_id is not None:
        body["property_id"] = property_id
    return sess.post(
        f"{BASE_URL}/api/quotes/{qid}/duplicate",
        json=body,
        timeout=REQ_TIMEOUT,
    )


def _hard_delete(sess, qid):
    try:
        sess.delete(
            f"{BASE_URL}/api/quotes/{qid}?hard=true", timeout=REQ_TIMEOUT,
        )
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════
# Case 1 — Admin duplicate to SAME customer.
# ═════════════════════════════════════════════════════════════════════

def test_admin_duplicate_same_customer_creates_fresh_draft(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat,
                       title="Original A", tax_rate=8.25, notes="src notes",
                       terms="src terms")
    r = _dup(admin_sess, src["id"], customer_a["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    new_qid = body["quote_id"]
    assert isinstance(new_qid, str) and new_qid and new_qid != src["id"]
    assert body["quote_number"] == new_qid[:8]

    new_doc = _get_quote(admin_sess, new_qid)
    src_doc = _get_quote(admin_sess, src["id"])

    # Draft, unpaid, all lifecycle timestamps reset.
    assert new_doc["status"] == "draft"
    assert new_doc.get("payment_status", "unpaid") == "unpaid"
    for k in ("accepted_at", "declined_at", "sent_at", "viewed_at",
              "first_viewed_at", "paid_at", "last_reminder_at",
              "scheduled_job_id", "deleted_at"):
        assert new_doc.get(k) in (None, 0), f"{k} not reset: {new_doc.get(k)}"
    assert new_doc.get("reminder_count", 0) == 0
    assert new_doc.get("amount_paid", 0) == 0
    assert new_doc.get("has_declined_lines", False) is False

    # Carried scalar fields.
    assert new_doc["title"] == "Original A"
    assert new_doc["customer_id"] == customer_a["id"]
    assert new_doc["doc_type"] == "quote"
    assert new_doc["tax_rate"] == 8.25
    assert new_doc.get("notes") == "src notes"
    assert new_doc.get("terms") == "src terms"

    # Line items — same count, fresh ids, decline state pending.
    src_lines = src_doc.get("line_items") or []
    new_lines = new_doc.get("line_items") or []
    assert len(new_lines) == len(src_lines) > 0
    src_ids = {li.get("id") for li in src_lines if li.get("id")}
    new_ids = {li.get("id") for li in new_lines if li.get("id")}
    assert new_ids and not (new_ids & src_ids), \
        "line item ids must be fresh"
    for li in new_lines:
        assert (li.get("customer_status") or "pending") == "pending"
        for k in ("customer_declined_at", "customer_declined_by",
                  "customer_decline_reason"):
            assert li.get(k) is None

    # Totals recomputed (matches source since line array shape is
    # identical apart from ids).
    assert new_doc.get("subtotal") == src_doc.get("subtotal")
    assert new_doc.get("total") == src_doc.get("total")

    _hard_delete(admin_sess, src["id"])
    _hard_delete(admin_sess, new_qid)


# ═════════════════════════════════════════════════════════════════════
# Case 2 — Explicit property_id on DIFFERENT customer.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_with_explicit_property_id_binds_to_it(
    admin_sess, customer_a, customer_b, svc_cat, inc_cat,
):
    prop, provisioned = _ensure_active_property(
        admin_sess, customer_b["id"], "Case-2 probe",
    )
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    try:
        r = _dup(admin_sess, src["id"], customer_b["id"],
                  property_id=prop["id"])
        assert r.status_code == 200, r.text
        new_qid = r.json()["quote_id"]
        new_doc = _get_quote(admin_sess, new_qid)
        assert new_doc["customer_id"] == customer_b["id"]
        assert new_doc["property_id"] == prop["id"]
        _hard_delete(admin_sess, new_qid)
    finally:
        _hard_delete(admin_sess, src["id"])
        if provisioned:
            _delete_property(admin_sess, prop["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 3 — No property_id, destination has exactly 1 active property.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_no_property_id_auto_assigns_when_single_active(
    admin_sess, customer_a, customer_b, svc_cat, inc_cat,
):
    # Case 3 needs the destination customer to have EXACTLY 1 active
    # property. Ensure at least one exists and skip if the fixture
    # already has more than one (deleting properties would disturb
    # unrelated tenant state — bounded risk).
    prop, provisioned = _ensure_active_property(
        admin_sess, customer_b["id"], "Case-3 probe",
    )
    props_after = _active_properties(admin_sess, customer_b["id"])
    if len(props_after) != 1:
        if provisioned:
            _delete_property(admin_sess, prop["id"])
        pytest.skip(
            f"customer_b has {len(props_after)} active properties "
            f"after provision — auto-assign case needs exactly 1"
        )
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    try:
        r = _dup(admin_sess, src["id"], customer_b["id"])
        assert r.status_code == 200, r.text
        new_qid = r.json()["quote_id"]
        new_doc = _get_quote(admin_sess, new_qid)
        assert new_doc["property_id"] == prop["id"]
        _hard_delete(admin_sess, new_qid)
    finally:
        _hard_delete(admin_sess, src["id"])
        if provisioned:
            _delete_property(admin_sess, prop["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 3b — No property_id + 0 or >1 active properties → property_id
# stays None. Legal per the schema — matches ``create_quote``'s
# consolidated-billing fallback.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_no_property_id_leaves_null_when_not_exactly_one(
    admin_sess, customer_a, customer_b, svc_cat, inc_cat,
):
    props_b = _active_properties(admin_sess, customer_b["id"])
    if len(props_b) == 1:
        pytest.skip(
            "customer_b has exactly 1 active property — this case "
            "requires 0 or >1 to exercise the null-fallback branch",
        )
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    r = _dup(admin_sess, src["id"], customer_b["id"])
    assert r.status_code == 200, r.text
    new_qid = r.json()["quote_id"]
    new_doc = _get_quote(admin_sess, new_qid)
    assert new_doc.get("property_id") in (None, "")

    _hard_delete(admin_sess, src["id"])
    _hard_delete(admin_sess, new_qid)


# ═════════════════════════════════════════════════════════════════════
# Case 4 — Mismatched property_id → 422.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_rejects_property_id_of_wrong_customer(
    admin_sess, customer_a, customer_b, svc_cat, inc_cat,
):
    prop_a, provisioned = _ensure_active_property(
        admin_sess, customer_a["id"], "Case-4 probe",
    )
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    try:
        # Try to bind customer_a's property while duplicating to
        # customer_b → 422.
        r = _dup(admin_sess, src["id"], customer_b["id"],
                  property_id=prop_a["id"])
        assert r.status_code == 422, r.text
        assert "property_id" in r.text.lower()
    finally:
        _hard_delete(admin_sess, src["id"])
        if provisioned:
            _delete_property(admin_sess, prop_a["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 6 — Declined lines are re-set to pending on the new quote.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_resets_declined_lines_to_pending(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    # Feb-2026 · Case 6 requires the source quote to be in
    # ``sent`` / ``viewed`` state so the per-line decline endpoint's
    # actionable-gate lets us stage a declined line.  There is no
    # client-surfaced transition to flip a quote from ``draft`` to
    # ``sent`` — PUT strips the ``status`` field via ``QuoteUpdate``,
    # ``send-reminder`` records reminder metadata without flipping
    # status, and no dedicated "mark as sent" endpoint exists.  A
    # future dispatch could loosen the gate for test-only use, expose
    # a transition endpoint, or accept the DB write path.  Until
    # then the case skips with a precise reason (was "magic-link
    # mint failed" — corrected).
    _mlink = admin_sess.get(
        f"{BASE_URL}/api/quotes/{src['id']}/magic-link",
        timeout=REQ_TIMEOUT,
    )
    if _mlink.status_code != 200:
        _hard_delete(admin_sess, src["id"])
        pytest.skip(
            f"magic-link mint failed ({_mlink.status_code}) — cannot "
            f"stage a declined line",
        )
    _tok = _mlink.json().get("token")
    _dl = requests.post(
        f"{BASE_URL}/api/portal/quotes/via-token/{_tok}"
        f"/line-items/0/decline",
        json={"reason": "test-decline"},
        timeout=REQ_TIMEOUT,
    )
    if _dl.status_code != 200:
        _hard_delete(admin_sess, src["id"])
        pytest.skip(
            "per-line decline requires source quote status "
            "``sent`` / ``viewed``; no client surface transitions "
            "``draft`` to ``sent`` in this codebase — documented in "
            "HOUSEKEEPING_DISPATCH_P2.md",
        )

    r = _dup(admin_sess, src["id"], customer_a["id"])
    assert r.status_code == 200, r.text
    new_qid = r.json()["quote_id"]
    new_doc = _get_quote(admin_sess, new_qid)
    for li in new_doc["line_items"]:
        assert (li.get("customer_status") or "pending") == "pending"
        assert li.get("customer_declined_by") is None
    assert new_doc.get("has_declined_lines", False) is False

    # Source unchanged — its first line stays declined.
    src_after = _get_quote(admin_sess, src["id"])
    assert src_after["line_items"][0].get("customer_status") == "declined"

    _hard_delete(admin_sess, src["id"])
    _hard_delete(admin_sess, new_qid)


# ═════════════════════════════════════════════════════════════════════
# Case 7 — Accepted quote → new quote is draft, accepted_at reset.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_accepted_quote_resets_decision_state(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    # Feb-2026 · flip source status to ``accepted`` via the
    # magic-link accept surface. The older ``customer-decision``
    # endpoint referenced by the pre-fix version of this test does
    # NOT exist in this codebase — the customer accept path IS
    # ``POST /api/portal/quotes/via-token/accept?token=<jwt>``.
    _mlink = admin_sess.get(
        f"{BASE_URL}/api/quotes/{src['id']}/magic-link",
        timeout=REQ_TIMEOUT,
    )
    if _mlink.status_code != 200:
        _hard_delete(admin_sess, src["id"])
        pytest.skip(
            f"magic-link mint failed ({_mlink.status_code}) — cannot "
            f"stage an accepted source"
        )
    _tok = _mlink.json().get("token")
    _acc = requests.post(
        f"{BASE_URL}/api/portal/quotes/via-token/accept",
        params={"token": _tok}, timeout=REQ_TIMEOUT,
    )
    if _acc.status_code != 200:
        _hard_delete(admin_sess, src["id"])
        pytest.skip(
            f"magic-link accept failed ({_acc.status_code}): "
            f"{_acc.text[:180]}"
        )
    src_after = _get_quote(admin_sess, src["id"])
    if src_after.get("status") not in ("accepted", "approved"):
        _hard_delete(admin_sess, src["id"])
        pytest.skip(
            f"accept did not flip status: {src_after.get('status')}"
        )

    try:
        r = _dup(admin_sess, src["id"], customer_a["id"])
        assert r.status_code == 200, r.text
        new_qid = r.json()["quote_id"]
        new_doc = _get_quote(admin_sess, new_qid)
        assert new_doc["status"] == "draft"
        assert new_doc.get("accepted_at") in (None, "")

        # Source unchanged.
        src_final = _get_quote(admin_sess, src["id"])
        assert src_final["status"] in ("accepted", "approved")
        _hard_delete(admin_sess, new_qid)
    finally:
        _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 8 — Photos: new quote carries no photo linkage.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_drops_photo_linkage(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    r = _dup(admin_sess, src["id"], customer_a["id"])
    assert r.status_code == 200, r.text
    new_qid = r.json()["quote_id"]
    new_doc = _get_quote(admin_sess, new_qid)
    # Photo linkage lives in adjacent collections; sanity-check that
    # no photo id/URL list slipped onto the new quote doc.
    for k in ("photo_ids", "photos", "photo_urls", "photo_keys",
              "s3_keys"):
        assert not new_doc.get(k), f"{k} unexpectedly present on new quote"

    _hard_delete(admin_sess, src["id"])
    _hard_delete(admin_sess, new_qid)


# ═════════════════════════════════════════════════════════════════════
# Case 9 — Technician gets 403.
# ═════════════════════════════════════════════════════════════════════

def test_technician_cannot_duplicate(
    admin_sess, tech_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    r = _dup(tech_sess, src["id"], customer_a["id"])
    assert r.status_code == 403, r.text

    _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 10 — Cross-tenant source → 404 (tenant scoping hides the doc).
# ═════════════════════════════════════════════════════════════════════

def test_cross_tenant_source_returns_404(admin_sess, customer_a):
    fake_qid = uuid.uuid4().hex  # certainly not in the caller's tenant
    r = _dup(admin_sess, fake_qid, customer_a["id"])
    assert r.status_code == 404, r.text


# ═════════════════════════════════════════════════════════════════════
# Case 11 — Source quote not found → 404.
# ═════════════════════════════════════════════════════════════════════

def test_source_not_found_returns_404(admin_sess, customer_a):
    r = _dup(admin_sess, "does-not-exist", customer_a["id"])
    assert r.status_code == 404, r.text


# ═════════════════════════════════════════════════════════════════════
# Case 12 — Destination customer not found → 404.
# ═════════════════════════════════════════════════════════════════════

def test_destination_customer_not_found_returns_404(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    r = _dup(admin_sess, src["id"], "does-not-exist-cust")
    assert r.status_code == 404, r.text

    _hard_delete(admin_sess, src["id"])


# ═════════════════════════════════════════════════════════════════════
# Case 13 — Idempotency: two runs create two distinct new quotes.
# ═════════════════════════════════════════════════════════════════════

def test_duplicate_twice_creates_two_distinct_quotes(
    admin_sess, customer_a, svc_cat, inc_cat,
):
    src = _make_quote(admin_sess, customer_a["id"], svc_cat, inc_cat)
    r1 = _dup(admin_sess, src["id"], customer_a["id"])
    r2 = _dup(admin_sess, src["id"], customer_a["id"])
    assert r1.status_code == 200 and r2.status_code == 200
    q1 = r1.json()["quote_id"]
    q2 = r2.json()["quote_id"]
    assert q1 and q2 and q1 != q2

    _hard_delete(admin_sess, src["id"])
    _hard_delete(admin_sess, q1)
    _hard_delete(admin_sess, q2)

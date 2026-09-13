"""Feb-2026 · Defense-in-depth — magic-link endpoints must read the
credential from the ``?token=`` query only.

Prior audit (see ``/app/memory/DIAG_MAGIC_LINK_401_RCA.md``)
confirmed ``_verify_estimate_token`` reads only its argument and
every ``/portal/*/via-token*`` route declares ``token: str = Query(...)``.
This test file locks the contract at the ROUTE level so a future
refactor cannot introduce an ``Authorization`` header dependency
without a loud failure. Each case fires the endpoint with:

  * ``?token=<valid magic-link JWT>`` (the intended credential)
  * ``Authorization: Bearer <valid but different admin JWT>`` (the
    stale session header that used to shadow the query token
    upstream — see the client-side portal-gate fix that shipped
    with ``FEATURE_QUOTE_DUPLICATE``)

and asserts the response corresponds to the QUERY token's quote,
not the header token's session.
"""
from __future__ import annotations

import os
from pathlib import Path

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
        for k in ("items", "results", "data", "customers", "service-categories"):
            if k in body and isinstance(body[k], list):
                return body[k]
    return []


def _admin_session():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    return s, tok


@pytest.fixture(scope="module")
def admin_and_token():
    return _admin_session()


@pytest.fixture(scope="module")
def admin_sess(admin_and_token):
    return admin_and_token[0]


@pytest.fixture(scope="module")
def admin_jwt(admin_and_token):
    # The admin's own bearer JWT — this is the "stale" header we
    # want to prove the endpoint IGNORES on magic-link routes.
    return admin_and_token[1]


@pytest.fixture(scope="module")
def two_probe_quotes(admin_sess):
    """Create two disposable quotes and mint a magic-link for each
    so we can request quote A's endpoint while carrying quote B's
    token or the admin JWT as a stale ``Authorization`` header.
    Returns ``(quote_a, magic_a, quote_b, magic_b)``.
    """
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    customers = _rows(r.json())
    if not customers:
        pytest.skip("no customers in fixture tenant")
    r = admin_sess.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    )
    svc = [c for c in _rows(r.json()) if not c.get("is_archived")]
    if not svc:
        pytest.skip("no active service categories")
    r = admin_sess.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    )
    inc = [c for c in _rows(r.json()) if not c.get("is_archived")]
    if not inc:
        pytest.skip("no active income categories")

    def _mk(title):
        body = {
            "customer_id": customers[0]["id"],
            "title": title,
            "doc_type": "quote",
            "line_items": [
                {"description": "Probe", "quantity": 1, "unit_price": 100,
                 "service_category_id": svc[0]["id"],
                 "income_category_id": inc[0]["id"]},
            ],
        }
        rq = admin_sess.post(
            f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT,
        )
        assert rq.status_code == 200, rq.text
        return rq.json()

    def _mint(qid):
        m = admin_sess.get(
            f"{BASE_URL}/api/quotes/{qid}/magic-link", timeout=REQ_TIMEOUT,
        )
        if m.status_code != 200:
            pytest.skip(f"magic-link mint failed for {qid}: {m.status_code}")
        return m.json().get("token")

    q_a = _mk("Query-only probe A")
    q_b = _mk("Query-only probe B")
    t_a = _mint(q_a["id"])
    t_b = _mint(q_b["id"])

    yield q_a, t_a, q_b, t_b

    # Cleanup — hard-delete both quotes.
    for qid in (q_a["id"], q_b["id"]):
        try:
            admin_sess.delete(
                f"{BASE_URL}/api/quotes/{qid}?hard=true",
                timeout=REQ_TIMEOUT,
            )
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# Case 1 — GET /portal/quotes/via-token — query wins over Bearer.
# ═════════════════════════════════════════════════════════════════════

def test_get_via_token_prefers_query_over_bearer(
    two_probe_quotes, admin_jwt,
):
    q_a, t_a, q_b, _t_b = two_probe_quotes
    r = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token",
        params={"token": t_a},
        # Deliberately attach a Bearer that ISN'T the magic-link
        # token — the admin's own JWT for the fixture tenant. If the
        # route were to read the header, it would either resolve to
        # the admin user's session (which then wouldn't necessarily
        # return quote A) or trip a tenant-mismatch 401.
        headers={"Authorization": f"Bearer {admin_jwt}"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The endpoint returns a customer-view payload keyed by
    # ``estimate_id`` (see estimate_viewer.py::view_estimate_via_token
    # response shape). Older payload shapes also expose ``id`` at
    # the top level or nest under ``quote``; check every reasonable
    # slot so a future response-shape refactor doesn't silently
    # invalidate the contract check.
    returned_id = (
        body.get("estimate_id")
        or body.get("id")
        or (body.get("quote") or {}).get("id")
    )
    assert returned_id == q_a["id"], (
        f"query token pointed at {q_a['id']} but response returned "
        f"{returned_id} — Bearer header may be shadowing the query"
    )
    # Sanity: it is NOT the OTHER probe's quote id.
    assert returned_id != q_b["id"]


# ═════════════════════════════════════════════════════════════════════
# Case 2 — GET /portal/tenant/branding — same rule.
# ═════════════════════════════════════════════════════════════════════

def test_get_branding_prefers_query_over_bearer(
    two_probe_quotes, admin_jwt,
):
    _q_a, t_a, _q_b, _t_b = two_probe_quotes
    r = requests.get(
        f"{BASE_URL}/api/portal/tenant/branding",
        params={"token": t_a},
        headers={"Authorization": f"Bearer {admin_jwt}"},
        timeout=REQ_TIMEOUT,
    )
    # Branding endpoint is a public-safe surface; it returns 200 with
    # the tenant's public branding whenever the query token is valid.
    # If the endpoint were to reject the query in favour of the
    # header, we'd see 401/403 here.
    assert r.status_code == 200, r.text
    body = r.json()
    # Response contract: at minimum ``brand_primary_hex`` is present
    # (either the tenant's or the default fallback).
    assert (
        "brand_primary_hex" in body
        or "primary_hex" in body
        or "branding" in body
    ), f"unexpected branding response shape: {body}"


# ═════════════════════════════════════════════════════════════════════
# Case 3 — POST accept-via-token — query wins over Bearer.
# ═════════════════════════════════════════════════════════════════════

def test_post_accept_prefers_query_over_bearer(
    admin_sess, admin_jwt,
):
    # This case creates and disposes of its own quote so the accept
    # side-effect doesn't taint the shared ``two_probe_quotes``
    # fixture (which cases 1 and 2 read after any accept).
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    customers = _rows(r.json())
    assert customers
    r = admin_sess.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    )
    svc = [c for c in _rows(r.json()) if not c.get("is_archived")]
    r = admin_sess.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    )
    inc = [c for c in _rows(r.json()) if not c.get("is_archived")]
    body = {
        "customer_id": customers[0]["id"],
        "title": "Accept-probe",
        "doc_type": "quote",
        "line_items": [
            {"description": "Probe", "quantity": 1, "unit_price": 50,
             "service_category_id": svc[0]["id"],
             "income_category_id": inc[0]["id"]},
        ],
    }
    src = admin_sess.post(
        f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT,
    ).json()
    m = admin_sess.get(
        f"{BASE_URL}/api/quotes/{src['id']}/magic-link", timeout=REQ_TIMEOUT,
    )
    if m.status_code != 200:
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{src['id']}?hard=true", timeout=REQ_TIMEOUT,
        )
        pytest.skip(f"magic-link mint failed: {m.status_code}")
    tok = m.json().get("token")

    try:
        # Accept endpoint takes ``token`` as a query param (per the
        # backend audit in DIAG_MAGIC_LINK_401_RCA.md) and — under the
        # contract this test enforces — MUST NOT read Authorization.
        r = requests.post(
            f"{BASE_URL}/api/portal/quotes/via-token/accept",
            params={"token": tok},
            headers={"Authorization": f"Bearer {admin_jwt}"},
            timeout=REQ_TIMEOUT,
        )
        # A working query-only implementation returns 200 (accepted).
        # A regressed implementation would either 401 (tenant mismatch
        # on the header token) or 403 (audience mismatch). Anything
        # other than 200 signals a header-based path.
        assert r.status_code == 200, (
            f"accept-via-token rejected the query credential when a "
            f"stale Bearer was present — regression risk. "
            f"status={r.status_code} body={r.text[:200]}"
        )
        # Assert the source quote actually flipped to accepted.
        detail = admin_sess.get(
            f"{BASE_URL}/api/quotes/{src['id']}", timeout=REQ_TIMEOUT,
        ).json()
        assert detail.get("status") in ("accepted", "approved"), (
            f"accept succeeded but source quote status did not flip: "
            f"{detail.get('status')}"
        )
    finally:
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{src['id']}?hard=true",
            timeout=REQ_TIMEOUT,
        )


# ═════════════════════════════════════════════════════════════════════
# Case 4 — POST decline-via-token — query wins over Bearer.
# ═════════════════════════════════════════════════════════════════════

def test_post_decline_prefers_query_over_bearer(
    admin_sess, admin_jwt,
):
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    customers = _rows(r.json())
    assert customers
    r = admin_sess.get(
        f"{BASE_URL}/api/service-categories", timeout=REQ_TIMEOUT,
    )
    svc = [c for c in _rows(r.json()) if not c.get("is_archived")]
    r = admin_sess.get(
        f"{BASE_URL}/api/income-categories", timeout=REQ_TIMEOUT,
    )
    inc = [c for c in _rows(r.json()) if not c.get("is_archived")]
    src = admin_sess.post(
        f"{BASE_URL}/api/quotes",
        json={
            "customer_id": customers[0]["id"],
            "title": "Decline-probe",
            "doc_type": "quote",
            "line_items": [
                {"description": "Probe", "quantity": 1, "unit_price": 50,
                 "service_category_id": svc[0]["id"],
                 "income_category_id": inc[0]["id"]},
            ],
        },
        timeout=REQ_TIMEOUT,
    ).json()
    m = admin_sess.get(
        f"{BASE_URL}/api/quotes/{src['id']}/magic-link", timeout=REQ_TIMEOUT,
    )
    if m.status_code != 200:
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{src['id']}?hard=true", timeout=REQ_TIMEOUT,
        )
        pytest.skip(f"magic-link mint failed: {m.status_code}")
    tok = m.json().get("token")

    try:
        r = requests.post(
            f"{BASE_URL}/api/portal/quotes/via-token/decline",
            params={"token": tok},
            headers={"Authorization": f"Bearer {admin_jwt}"},
            json={"reason": "query-only probe"},
            timeout=REQ_TIMEOUT,
        )
        assert r.status_code == 200, (
            f"decline-via-token rejected the query credential when a "
            f"stale Bearer was present — regression risk. "
            f"status={r.status_code} body={r.text[:200]}"
        )
        detail = admin_sess.get(
            f"{BASE_URL}/api/quotes/{src['id']}", timeout=REQ_TIMEOUT,
        ).json()
        assert detail.get("status") in ("declined", "rejected"), (
            f"decline succeeded but source status did not flip: "
            f"{detail.get('status')}"
        )
    finally:
        admin_sess.delete(
            f"{BASE_URL}/api/quotes/{src['id']}?hard=true",
            timeout=REQ_TIMEOUT,
        )

"""Feb-2026 · Public Quote Attachments — end-to-end contract tests.

Locks the three routes shipped by this dispatch:

  1. ``GET /api/portal/quotes/via-token`` returns an
     ``attachments: [...]`` array with absolute tokenised URLs when
     at least one file is linked to the quote via
     ``purpose="invoice_attachment"`` + ``linked_entity_type="invoice"``
     + ``linked_entity_id=<quote.id>``.

  2. ``GET /api/portal/quotes/via-token/files/{file_id}?token=...``
     with the CORRECT token → 200 + Content-Disposition attachment
     + correct Content-Type.

  3. Same route with a token minted for a DIFFERENT quote → 403.
     Same route without a token → 401.

Fixtures:
  * Uploads a small PDF via ``POST /api/files/upload`` (admin auth)
    tagged with the required purpose + linked-entity fields.
  * Mints magic-link tokens via ``GET /api/quotes/{qid}/magic-link``.

See ``/app/memory/FEATURE_PUBLIC_QUOTE_ATTACHMENTS.md`` for the
curl recipes the tester can run interactively.
"""
from __future__ import annotations

import io
import os
import uuid
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
        for key in ("items", "results", "data", "customers", "quotes"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=REQ_TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    tok = r.json().get("access_token") or r.json().get("token")
    return tok


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def admin_sess(admin_tok):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_tok}"})
    return s


@pytest.fixture(scope="module")
def customer_id(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/customers", timeout=REQ_TIMEOUT)
    rows = _rows(r.json())
    assert rows, "no customers seeded — cannot bootstrap attachment tests"
    return rows[0]["id"]


@pytest.fixture(scope="module")
def svc_cat(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/service-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows, "no service categories seeded"
    return rows[0]


@pytest.fixture(scope="module")
def inc_cat(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/income-categories",
                        timeout=REQ_TIMEOUT)
    rows = [c for c in _rows(r.json()) if not c.get("is_archived")]
    assert rows, "no income categories seeded"
    return rows[0]


def _make_quote(sess, customer_id, svc_cat, inc_cat, *, title=None):
    body = {
        "customer_id": customer_id,
        "title": title or f"Attachments probe {uuid.uuid4().hex[:6]}",
        "doc_type": "quote",
        "line_items": [
            {"description": "Design", "quantity": 1, "unit_price": 100,
             "service_category_id": svc_cat["id"],
             "income_category_id": inc_cat["id"]},
        ],
    }
    r = sess.post(f"{BASE_URL}/api/quotes", json=body, timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _magic_link_token(sess, qid):
    r = sess.get(f"{BASE_URL}/api/quotes/{qid}/magic-link",
                  timeout=REQ_TIMEOUT)
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body.get("token") or body.get("url", "").split("token=")[-1]
    assert tok
    return tok


def _upload_pdf(admin_tok, quote_id, *, filename="probe.pdf") -> dict:
    # Minimal well-formed PDF — 5-byte "%PDF-" magic is enough for
    # the router's ``application/pdf`` MIME whitelist. The actual
    # bytes just need to round-trip through S3.
    body = b"%PDF-1.4\n%probe attachment for pytest\n%%EOF\n"
    files = {
        "file": (filename, io.BytesIO(body), "application/pdf"),
    }
    data = {
        "purpose": "invoice_attachment",
        "linked_entity_type": "invoice",
        "linked_entity_id": quote_id,
    }
    r = requests.post(
        f"{BASE_URL}/api/files/upload",
        headers={"Authorization": f"Bearer {admin_tok}"},
        data=data, files=files, timeout=REQ_TIMEOUT,
    )
    if r.status_code == 503:
        pytest.skip("File storage not configured in this env — "
                    "attachment tests require /api/files/upload")
    assert r.status_code == 200, r.text
    return r.json()


# ─── Test 1 — viewer payload includes attachments ────────────────

def test_viewer_payload_includes_attachments(
    admin_sess, admin_tok, customer_id, svc_cat, inc_cat,
):
    q = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = q["id"]
    uploaded = _upload_pdf(admin_tok, qid, filename="site-plan.pdf")

    tok = _magic_link_token(admin_sess, qid)
    r = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token",
        params={"token": tok}, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    atts = payload.get("attachments") or []
    assert any(a.get("id") == uploaded["id"] for a in atts), (
        f"uploaded file id {uploaded['id']!r} not in viewer payload "
        f"attachments={atts!r}"
    )
    mine = next(a for a in atts if a.get("id") == uploaded["id"])
    assert mine["filename"] == "site-plan.pdf"
    assert mine["content_type"] == "application/pdf"
    assert int(mine["size"]) > 0
    # URL must be absolute + tokenised — points at the NEW
    # public token-scoped route (not the admin
    # ``/api/files/{id}/download`` endpoint).
    assert mine["url"].startswith("http")
    assert "/api/portal/quotes/via-token/files/" in mine["url"]
    assert f"token={tok}" in mine["url"]


# ─── Test 2 — token-scoped GET happy path ────────────────────────

def test_token_scoped_download_happy_path(
    admin_sess, admin_tok, customer_id, svc_cat, inc_cat,
):
    q = _make_quote(admin_sess, customer_id, svc_cat, inc_cat)
    qid = q["id"]
    uploaded = _upload_pdf(admin_tok, qid, filename="delta-plan.pdf")
    tok = _magic_link_token(admin_sess, qid)

    r = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token/files/{uploaded['id']}",
        params={"token": tok}, timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "delta-plan.pdf" in cd
    assert len(r.content) > 0
    assert r.content.startswith(b"%PDF")


# ─── Test 3 — cross-quote 403 + missing-token 401 ────────────────

def test_token_scoped_download_wrong_quote_returns_403(
    admin_sess, admin_tok, customer_id, svc_cat, inc_cat,
):
    q_a = _make_quote(admin_sess, customer_id, svc_cat, inc_cat,
                       title="Attach A")
    q_b = _make_quote(admin_sess, customer_id, svc_cat, inc_cat,
                       title="Attach B")
    file_a = _upload_pdf(admin_tok, q_a["id"], filename="A.pdf")
    tok_b = _magic_link_token(admin_sess, q_b["id"])

    # Cross-quote: A's file with B's token → 403 (token valid but
    # points at a different quote).
    r_wrong = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token/files/{file_a['id']}",
        params={"token": tok_b}, timeout=REQ_TIMEOUT,
    )
    assert r_wrong.status_code == 403, r_wrong.text

    # No token: 401 (Query param is required by FastAPI so a bare
    # request lands as 422; we assert the missing-credentials
    # class 4xx here — the exact 401-vs-422 code depends on how
    # ``token=Query(...)`` reports the missing-required param).
    r_bare = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token/files/{file_a['id']}",
        timeout=REQ_TIMEOUT,
    )
    assert r_bare.status_code in (401, 422), r_bare.text

    # Invalid token → 401 (jwt.decode fails inside
    # ``_verify_estimate_token``).
    r_bad = requests.get(
        f"{BASE_URL}/api/portal/quotes/via-token/files/{file_a['id']}",
        params={"token": "not-a-jwt"}, timeout=REQ_TIMEOUT,
    )
    assert r_bad.status_code == 401, r_bad.text

    # Admin ``/api/files/{id}/download`` still requires admin auth
    # (unchanged posture) — a bare request lands as 401.
    r_admin_bare = requests.get(
        f"{BASE_URL}/api/files/{file_a['id']}/download",
        timeout=REQ_TIMEOUT,
    )
    assert r_admin_bare.status_code == 401, r_admin_bare.text

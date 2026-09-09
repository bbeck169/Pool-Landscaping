"""Feb-2026 · Outcome C — Estimate/Quote URL rename.

Verifies:
    1. Every new canonical ``/quotes/{qid}/{full,accept,decline,
       request-changes,magic-link,pdf}`` returns 200 for a valid quote
       and 404 for a bogus id under the correct tenant scoping.
    2. Every old ``/estimates/{eid}/*`` alias returns the same status
       and (for read paths) the same JSON body as the new canonical.
    3. Portal magic-link aliases ``/portal/estimates/via-token*``
       resolve identically to ``/portal/quotes/via-token*``.
    4. OpenAPI marks every ``/estimates/*`` route and every alias with
       ``deprecated=True``; the canonical ``/quotes/*`` routes are NOT
       marked deprecated.
    5. ``routers/estimates.py`` OpenAPI entries all carry
       ``deprecated=True`` (documentation of Phase-2 migration path).

Uses live HTTP + pymongo pattern to match ``test_final_integration_
verification.py`` — avoids event-loop conflicts with FastAPI TestClient.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FRONT_ENV = dotenv_values(Path("/app/frontend/.env"))
BASE = (_FRONT_ENV.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"

_BACKEND_ENV = dotenv_values(Path("/app/backend/.env"))
_MONGO_URL = _BACKEND_ENV.get("MONGO_URL") or os.environ["MONGO_URL"]
_DB_NAME = _BACKEND_ENV.get("DB_NAME") or os.environ["DB_NAME"]


# ── fixtures ────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "super@aquaterra.com", "password": "password123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def _mongo():
    return MongoClient(_MONGO_URL)[_DB_NAME]


@pytest.fixture(scope="module")
def seeded_quote(admin_h, _mongo):
    """Seed a minimal quote row for the super_admin tenant."""
    who = requests.get(f"{API}/tenants/current", headers=admin_h,
                        timeout=15).json()
    tenant_id = who["id"]
    # Grab any real customer id from this tenant so the magic-link
    # token's cid claim matches the doc's customer_id (blank matches
    # blank triggers a false-401 in _load_est_from_token).
    a_cust = _mongo.customers.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    customer_id = (a_cust or {}).get("id") or "outcome-c-fixture-cust"
    qid = str(uuid.uuid4())
    doc = {
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": "quote",
        "status": "draft",
        "customer_id": customer_id,
        "title": "Outcome C rename fixture",
        "line_items": [{
            "description": "Test line", "quantity": 1,
            "unit_price": 100.0, "total": 100.0,
        }],
        "subtotal": 100.0,
        "tax": 0.0,
        "total": 100.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "outcome_c_test",
    }
    _mongo.quotes.insert_one(doc)
    yield {"qid": qid, "tenant_id": tenant_id, "customer_id": customer_id}
    _mongo.quotes.delete_one({"id": qid})


# ── Canonical vs. alias parity ──────────────────────────────────────
class TestQuoteFullPathParity:
    def test_new_canonical_returns_200(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        r = requests.get(f"{API}/quotes/{qid}/full",
                         headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["estimate_id"] == qid

    def test_deprecated_alias_returns_200(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        r = requests.get(f"{API}/estimates/{qid}/full",
                         headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["estimate_id"] == qid

    def test_alias_and_canonical_return_same_shape(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        new = requests.get(f"{API}/quotes/{qid}/full",
                            headers=admin_h, timeout=15).json()
        old = requests.get(f"{API}/estimates/{qid}/full",
                            headers=admin_h, timeout=15).json()
        assert new == old

    def test_bogus_id_returns_404_on_both(self, admin_h):
        for path in ("/quotes/nope-nope/full",
                       "/estimates/nope-nope/full"):
            r = requests.get(f"{API}{path}", headers=admin_h, timeout=15)
            assert r.status_code == 404, f"{path} → {r.status_code}"


class TestMagicLinkParity:
    def test_new_canonical_issues_token(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        r = requests.get(f"{API}/quotes/{qid}/magic-link",
                         headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token"]
        assert "expires_in_days" in body

    def test_deprecated_alias_issues_token(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        r = requests.get(f"{API}/estimates/{qid}/magic-link",
                         headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["token"]

    def test_bogus_id_returns_404_on_both(self, admin_h):
        for path in ("/quotes/nope-nope/magic-link",
                       "/estimates/nope-nope/magic-link"):
            r = requests.get(f"{API}{path}", headers=admin_h, timeout=15)
            assert r.status_code == 404, path


class TestPortalViaTokenParity:
    def test_via_token_new_and_old_are_equivalent(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        tok = requests.get(
            f"{API}/quotes/{qid}/magic-link", headers=admin_h, timeout=15,
        ).json()["token"]
        new = requests.get(
            f"{API}/portal/quotes/via-token", params={"token": tok}, timeout=15,
        )
        old = requests.get(
            f"{API}/portal/estimates/via-token", params={"token": tok}, timeout=15,
        )
        assert new.status_code == 200, new.text
        assert old.status_code == 200, old.text
        assert new.json() == old.json()


class TestPDFParity:
    def test_pdf_both_paths_return_200_and_pdf(self, admin_h, seeded_quote):
        qid = seeded_quote["qid"]
        for path in (f"/quotes/{qid}/pdf", f"/estimates/{qid}/pdf"):
            r = requests.get(f"{API}{path}", headers=admin_h, timeout=30)
            assert r.status_code == 200, f"{path} → {r.status_code}"
            assert r.headers["content-type"] == "application/pdf"
            assert r.content.startswith(b"%PDF")


# ── OpenAPI: deprecation flag on every alias + on estimates.py ──────
class TestOpenAPIDeprecationFlags:
    @pytest.fixture(scope="class")
    def spec(self):
        return requests.get(f"{API}/openapi.json", timeout=30).json()

    @pytest.mark.parametrize("path", [
        "/api/quotes/{qid}/full",
        "/api/quotes/{qid}/accept",
        "/api/quotes/{qid}/decline",
        "/api/quotes/{qid}/request-changes",
        "/api/quotes/{qid}/magic-link",
        "/api/quotes/{qid}/pdf",
        "/api/portal/quotes/via-token",
        "/api/portal/quotes/via-token/accept",
        "/api/portal/quotes/via-token/decline",
        "/api/portal/quotes/via-token/request-changes",
    ])
    def test_canonical_paths_not_deprecated(self, spec, path):
        paths = spec.get("paths", {})
        assert path in paths, f"canonical path missing: {path}"
        for op in paths[path].values():
            if not isinstance(op, dict):
                continue
            assert op.get("deprecated") is not True, \
                f"{path} should NOT be deprecated"

    @pytest.mark.parametrize("path", [
        "/api/estimates/{qid}/full",
        "/api/estimates/{qid}/accept",
        "/api/estimates/{qid}/decline",
        "/api/estimates/{qid}/request-changes",
        "/api/estimates/{qid}/magic-link",
        "/api/estimates/{qid}/pdf",
        "/api/portal/estimates/via-token",
        "/api/portal/estimates/via-token/accept",
        "/api/portal/estimates/via-token/decline",
        "/api/portal/estimates/via-token/request-changes",
    ])
    def test_deprecated_aliases_are_marked(self, spec, path):
        paths = spec.get("paths", {})
        assert path in paths, f"alias missing: {path}"
        for method, op in paths[path].items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            assert op.get("deprecated") is True, \
                f"{method} {path} should be deprecated"

    @pytest.mark.parametrize("path,method", [
        ("/api/estimates/settings", "get"),
        ("/api/estimates/settings", "put"),
        ("/api/estimate-templates", "get"),
        ("/api/estimate-templates", "post"),
        ("/api/estimate-templates/{tid}", "delete"),
        ("/api/estimates", "get"),
        ("/api/estimates", "post"),
        ("/api/estimates/{eid}", "get"),
        ("/api/estimates/{eid}", "put"),
        ("/api/estimates/{eid}", "delete"),
        ("/api/estimates/{eid}/convert", "post"),
        ("/api/estimates/{eid}/soft-delete", "post"),
        ("/api/estimates/bulk-delete", "post"),
    ])
    def test_estimates_router_all_deprecated(self, spec, path, method):
        paths = spec.get("paths", {})
        assert path in paths, f"estimates.py path missing: {path}"
        op = paths[path].get(method)
        assert op, f"{method} {path} not in openapi"
        assert op.get("deprecated") is True, \
            f"{method} {path} must be deprecated=True"

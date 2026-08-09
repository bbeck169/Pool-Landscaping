"""Phase 34 · Endpoint Path Normalization (Feb 2026)
==================================================

Locks the ``/api/public/r/*`` compat alias for the public review-request
token flow:

* Both the canonical (``/api/reviews/public/r/*``) and legacy
  (``/api/public/r/*``) prefixes must return the same 200 payload for
  a valid token.
* The alias must add ``Deprecation: true`` + a ``Link`` header pointing
  at the canonical path. The canonical path must NOT carry those
  headers (they'd flag callers that are already correct).

Test pattern mirrors ``test_phase34_task_t_review_gating.py`` — HTTP
against the running FastAPI app, Motor inserts to plant the token row.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest

# Phase 34-migrate-v2 · Phase 34-v2-d · Feb 2026 — swapped ``requests``
# for the in-process ASGI shim.
from tests._phase34_http_shim import http

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")

CANONICAL = f"{BASE_URL}/api/reviews/public/r"
ALIAS = f"{BASE_URL}/api/public/r"


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _get_aq_tenant_id(db) -> str:
    t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    assert t, "aquaterra tenant missing"
    return t["id"]


async def _get_customer_id(db, tenant_id: str) -> str:
    c = await db.customers.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    assert c, "no seeded customer"
    return c["id"]


async def _mk_request(
    db,
    tenant_id: str,
    customer_id: str,
    star_submitted: Optional[int] = None,
) -> Dict[str, Any]:
    token = uuid.uuid4().hex[:32]
    now = datetime.now(timezone.utc).isoformat()
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    doc = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "token": token,
        "customer_id": customer_id,
        "job_id": None,
        "technician_id": None,
        "sent_via": "email",
        "sent_at": now,
        "communication_send_ids": [],
        "landing_visited_at": None,
        "star_rating_submitted": star_submitted,
        "star_submitted_at": None,
        "platform_chosen": None,
        "platform_clicked_at": None,
        "outcome": "pending",
        "expires_at": exp,
        "created_by_user_id": None,
        "created_at": now,
    }
    await db.review_requests.insert_one(doc)
    return doc


# ═══════════════════════════════════════════════════════════════════════
# GET /public/r/{token}
# ═══════════════════════════════════════════════════════════════════════
def test_alias_get_landing_matches_canonical(db):
    tenant_id = _run(_get_aq_tenant_id(db))
    customer_id = _run(_get_customer_id(db, tenant_id))
    doc = _run(_mk_request(db, tenant_id, customer_id))
    token = doc["token"]

    r_canon = http.get(f"{CANONICAL}/{token}", timeout=30)
    r_alias = http.get(f"{ALIAS}/{token}", timeout=30)

    assert r_canon.status_code == 200, r_canon.text
    assert r_alias.status_code == 200, r_alias.text
    # Same payload shape — spot-check the top-level keys are identical.
    assert set(r_canon.json().keys()) == set(r_alias.json().keys())

    # Alias carries deprecation headers; canonical does not.
    assert r_alias.headers.get("Deprecation") == "true"
    assert 'rel="alternate"' in (r_alias.headers.get("Link") or "")
    assert "/api/reviews/public/r/" in (r_alias.headers.get("Link") or "")
    assert "Deprecation" not in r_canon.headers


# ═══════════════════════════════════════════════════════════════════════
# POST /public/r/{token}/rating
# ═══════════════════════════════════════════════════════════════════════
def test_alias_post_rating_matches_canonical(db):
    tenant_id = _run(_get_aq_tenant_id(db))
    customer_id = _run(_get_customer_id(db, tenant_id))

    # Plant TWO fresh tokens so both submissions succeed (rating is
    # one-shot per token).
    doc_canon = _run(_mk_request(db, tenant_id, customer_id))
    doc_alias = _run(_mk_request(db, tenant_id, customer_id))

    r_canon = http.post(
        f"{CANONICAL}/{doc_canon['token']}/rating",
        json={"star_rating": 5, "comment": "great"},
        timeout=30,
    )
    r_alias = http.post(
        f"{ALIAS}/{doc_alias['token']}/rating",
        json={"star_rating": 5, "comment": "great"},
        timeout=30,
    )

    assert r_canon.status_code == 200, r_canon.text
    assert r_alias.status_code == 200, r_alias.text
    # Same JSON shape.
    assert set(r_canon.json().keys()) == set(r_alias.json().keys())

    assert r_alias.headers.get("Deprecation") == "true"
    assert "Deprecation" not in r_canon.headers


# ═══════════════════════════════════════════════════════════════════════
# POST /public/r/{token}/google-clicked
# ═══════════════════════════════════════════════════════════════════════
def test_alias_post_google_clicked_matches_canonical(db):
    tenant_id = _run(_get_aq_tenant_id(db))
    customer_id = _run(_get_customer_id(db, tenant_id))

    # 4-5 star already submitted so google-clicked is legal.
    doc_canon = _run(_mk_request(db, tenant_id, customer_id, star_submitted=5))
    doc_alias = _run(_mk_request(db, tenant_id, customer_id, star_submitted=5))

    r_canon = http.post(
        f"{CANONICAL}/{doc_canon['token']}/google-clicked",
        json={},
        timeout=30,
    )
    r_alias = http.post(
        f"{ALIAS}/{doc_alias['token']}/google-clicked",
        json={},
        timeout=30,
    )

    assert r_canon.status_code == 200, r_canon.text
    assert r_alias.status_code == 200, r_alias.text
    assert r_canon.json().get("ok") is True
    assert r_alias.json().get("ok") is True

    assert r_alias.headers.get("Deprecation") == "true"
    assert "Deprecation" not in r_canon.headers

"""Feb-2026 · Phase — AI check-in description endpoint tests.

Covers ``POST /api/checkins/{id}/ai-description``:

* Happy path — 200 with description + model + generated_at.
* 404 when the check-in id is unknown for this tenant.
* 403 for a technician who doesn't own the check-in.
* 429 after 10 successful calls in the same UTC hour per tenant.
* Telemetry event appended to ``ai_description_events``.

Uses the ``ALLOW_TEST_HOOKS`` + ``X-Test-Skip-Llm: 1`` bypass so
tests don't hit the real LLM. The bypass path still exercises
the auth, rate-limit, context-gathering, and telemetry code paths.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)

_BYPASS_HEADERS = {}   # ALLOW_TEST_HOOKS is force-disabled in
                        # production mode (see server.py:1225), so
                        # tests must hit the real LLM. Kept as an
                        # empty dict so callers stay uniform.


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    h = {"Authorization": f"Bearer {_login(email)}"}
    h.update(_BYPASS_HEADERS)
    return h


def _super() -> dict:
    return _hdr("super@aquaterra.com")


def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


def _current_window_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0).isoformat()


@pytest.fixture
def ai_desc_ctx():
    tid = _tenant_of("super@aquaterra.com")

    cust_id = "ai-desc-cust"
    _sync.customers.insert_one({
        "id": cust_id, "tenant_id": tid,
        "name": "AI Desc Test Customer",
        "address_city": "Chandler",
        "address_zip": "85226",
        "address_state": "AZ",
    })
    job_id = "ai-desc-job"
    _sync.jobs.insert_one({
        "id": job_id, "tenant_id": tid,
        "customer_id": cust_id,
        "service_name": "Weekly Pool Service",
        "service_category": "pool_service",
    })
    ck_id = "ai-desc-checkin"
    tech = _sync.users.find_one({"tenant_id": tid, "role": "technician"},
                                 {"_id": 0, "id": 1, "email": 1})
    tech_id = (tech or {}).get("id") or "tech-x"
    _sync.checkins.insert_one({
        "id": ck_id, "tenant_id": tid,
        "job_id": job_id,
        "technician_id": tech_id,
        "note": "cleaned pump basket",
        "status": "draft",
    })

    # Snapshot brand voice into business_settings so the prompt path
    # exercises the branch. Restore on teardown.
    tenant_before = _sync.tenants.find_one({"id": tid},
                                            {"_id": 0, "business_settings": 1})
    _sync.tenants.update_one(
        {"id": tid},
        {"$set": {"business_settings.brand_voice":
                    "Friendly, concise, homeowner-first."}},
    )

    # Purge any leftover rate-limit rows from previous runs so this
    # test's counter starts at zero.
    _sync.ai_description_events.delete_many(
        {"tenant_id": tid, "action": "checkin_ai_description"})

    yield {
        "tenant_id": tid,
        "customer_id": cust_id,
        "job_id": job_id,
        "checkin_id": ck_id,
        "tech_id": tech_id,
        "tech_email": (tech or {}).get("email"),
    }

    _sync.customers.delete_one({"id": cust_id})
    _sync.jobs.delete_one({"id": job_id})
    _sync.checkins.delete_one({"id": ck_id})
    prev_bs = (tenant_before or {}).get("business_settings") or {}
    _sync.tenants.update_one(
        {"id": tid}, {"$set": {"business_settings": prev_bs}},
    )
    _sync.ai_description_events.delete_many(
        {"tenant_id": tid, "action": "checkin_ai_description"})


# ══════════════════════════════════════════════════════════════════
# Happy path + shape
# ══════════════════════════════════════════════════════════════════

def test_returns_description_model_and_generated_at(ai_desc_ctx):
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        json={"tone": "neutral_factual"},
        headers=_super(), timeout=40,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("description"), str) and body["description"]
    # The prompt injects the customer's city, so real LLM output
    # will almost always echo it back. Not a hard requirement — a
    # rewording model could paraphrase.
    assert body["model"] in ("gpt-4o", "claude-sonnet-4-5")
    # ISO timestamp with a "T" separator.
    assert "T" in body["generated_at"]


def test_body_is_optional(ai_desc_ctx):
    """Spec: request body is optional — empty POST still returns 200
    with the default tone applied."""
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=_super(), timeout=40,
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"]


def test_context_falls_back_to_the_local_area(ai_desc_ctx):
    """Customer with no city → prompt substitutes "the local area".

    We can't strictly assert the phrase appears in the LLM output
    (it might paraphrase), but we CAN assert the call still
    returns 200 — meaning the prompt-builder didn't blow up on the
    missing city.
    """
    _sync.customers.update_one(
        {"id": ai_desc_ctx["customer_id"]},
        {"$unset": {"address_city": "", "city": ""}},
    )
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=_super(), timeout=40,
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"]


# ══════════════════════════════════════════════════════════════════
# Auth
# ══════════════════════════════════════════════════════════════════

def test_unknown_checkin_id_404(ai_desc_ctx):
    r = requests.post(
        f"{API}/checkins/does-not-exist-xyz/ai-description",
        headers=_super(), timeout=20,
    )
    assert r.status_code == 404, r.text


def test_customer_role_forbidden(ai_desc_ctx):
    hdr = _hdr("customer@aquaterra.com")
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=hdr, timeout=20,
    )
    assert r.status_code == 403, r.text


def test_tech_owning_the_checkin_allowed(ai_desc_ctx):
    """Technician on the check-in's job is allowed by policy."""
    if not ai_desc_ctx.get("tech_email"):
        pytest.skip("no seeded technician for this tenant")
    hdr = _hdr(ai_desc_ctx["tech_email"])
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=hdr, timeout=40,
    )
    assert r.status_code == 200, r.text


def test_tech_not_owning_the_checkin_forbidden(ai_desc_ctx):
    """A tech that isn't the check-in's technician_id → 403."""
    if not ai_desc_ctx.get("tech_email"):
        pytest.skip("no seeded technician for this tenant")
    _sync.checkins.update_one(
        {"id": ai_desc_ctx["checkin_id"]},
        {"$set": {"technician_id": "some-other-tech"}},
    )
    hdr = _hdr(ai_desc_ctx["tech_email"])
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=hdr, timeout=20,
    )
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════
# Rate limit — 10/tenant/hour. Directly seeds the counter row so
# we don't burn 10 LLM calls just to hit the boundary.
# ══════════════════════════════════════════════════════════════════

def test_rate_limit_returns_429_when_window_full(ai_desc_ctx):
    """Pre-seed ``call_count=10`` on the current window row and
    assert the 11th call is 429 with the structured detail payload
    the frontend button parses."""
    from routers.checkin_ai_description import _current_window
    start, end = _current_window()
    _sync.ai_description_events.update_one(
        {"tenant_id": ai_desc_ctx["tenant_id"],
         "action": "checkin_ai_description",
         "window_start_utc": start.isoformat()},
        {"$set": {"call_count": 10,
                   "window_end_utc": end.isoformat(),
                   "last_called_at": start.isoformat(),
                   "last_user_id": "seed"},
         "$setOnInsert": {"created_at": start.isoformat(),
                            "events": []}},
        upsert=True,
    )
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=_super(), timeout=20,
    )
    assert r.status_code == 429, r.text
    body = r.json()
    detail = body.get("detail") or {}
    assert detail.get("code") == "rate_limit_exceeded"
    assert isinstance(detail.get("retry_after_seconds"), int)
    assert detail["retry_after_seconds"] >= 1
    # Also carries a Retry-After header (RFC-standard).
    assert r.headers.get("Retry-After")


# ══════════════════════════════════════════════════════════════════
# Telemetry
# ══════════════════════════════════════════════════════════════════

def test_telemetry_row_records_events(ai_desc_ctx):
    hdr = _super()
    r = requests.post(
        f"{API}/checkins/{ai_desc_ctx['checkin_id']}/ai-description",
        headers=hdr, timeout=40,
    )
    assert r.status_code == 200
    row = _sync.ai_description_events.find_one(
        {"tenant_id": ai_desc_ctx["tenant_id"],
         "action": "checkin_ai_description",
         "window_start_utc": _current_window_start()},
    )
    assert row is not None
    assert row["call_count"] >= 1
    events = row.get("events") or []
    assert len(events) >= 1
    ev = events[-1]
    assert ev["checkin_id"] == ai_desc_ctx["checkin_id"]
    # Provider tag is one of the two backing model tags — never
    # blank. Test-stub fallback isn't reachable in production mode.
    assert ev["provider"] in ("gpt-4o", "claude-sonnet-4-5")
    assert ev["description_chars"] > 0

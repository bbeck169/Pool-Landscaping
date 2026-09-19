"""Feb-2026 · Proposal Analytics — flipbook-viewer ingestion + admin
readback tests.

Uses the canonical ``run_test(coro_factory) + httpx.ASGITransport +
_f7_loop_fixture`` pattern shared by the rest of the Feb-2026 test
suite so Motor's loop-affinity stays clean when the file runs
alongside the full backend sweep.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import httpx
import jwt
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

# Load JWT config the same way the router does — via ``config``.
os.environ.setdefault("MONGO_URL", MONGO_URL or "")
os.environ.setdefault("DB_NAME", DB_NAME or "")
from config import JWT_SECRET, JWT_ALGO  # noqa: E402


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


def _make_token(*, eid: str, cid: str, tid: str,
                exp_offset_days: int = 30) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "est",
        "eid": eid, "cid": cid, "tid": tid,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=exp_offset_days),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


@pytest.fixture(scope="module")
def seeded(dbc):
    """Seed a fresh tenant + estimate + one admin user + one tech user.

    Every doc uses ``TEST_``-prefixed markers where possible so the
    session-scoped conftest cleanup sweeps them post-run.
    """
    tenant_id = f"tenant_analytics_{uuid.uuid4().hex[:8]}"
    other_tenant_id = f"tenant_analytics_other_{uuid.uuid4().hex[:8]}"
    admin_id = f"u_admin_{uuid.uuid4().hex[:8]}"
    tech_id = f"u_tech_{uuid.uuid4().hex[:8]}"
    customer_id = f"cust_{uuid.uuid4().hex[:8]}"
    estimate_id = f"est_{uuid.uuid4().hex[:8]}"
    other_estimate_id = f"est_other_{uuid.uuid4().hex[:8]}"

    dbc.tenants.insert_many([
        {"id": tenant_id, "slug": f"analytics-{tenant_id[:6]}",
         "name": "Analytics Test"},
        {"id": other_tenant_id, "slug": f"other-analytics-{other_tenant_id[:6]}",
         "name": "Analytics Other"},
    ])
    dbc.users.insert_many([
        {"id": admin_id, "tenant_id": tenant_id, "role": "admin",
         "email": f"TEST_analytics_admin_{tenant_id[:6]}@example.com",
         "name": "TEST Admin"},
        {"id": tech_id, "tenant_id": tenant_id, "role": "technician",
         "email": f"TEST_analytics_tech_{tenant_id[:6]}@example.com",
         "name": "TEST Tech"},
    ])
    dbc.quotes.insert_many([
        {"id": estimate_id, "tenant_id": tenant_id,
         "customer_id": customer_id, "status": "sent",
         "title": "TEST_analytics_estimate",
         "estimate_number": "T-ANALYTICS-1",
         "flipbook_enabled": True,
         "flipbook_background_ids": []},
        {"id": other_estimate_id, "tenant_id": other_tenant_id,
         "customer_id": customer_id, "status": "sent",
         "title": "TEST_analytics_estimate_other",
         "estimate_number": "T-ANALYTICS-2",
         "flipbook_enabled": True,
         "flipbook_background_ids": []},
    ])

    yield {
        "tenant_id": tenant_id,
        "other_tenant_id": other_tenant_id,
        "admin_id": admin_id,
        "tech_id": tech_id,
        "customer_id": customer_id,
        "estimate_id": estimate_id,
        "other_estimate_id": other_estimate_id,
        "token": _make_token(eid=estimate_id, cid=customer_id, tid=tenant_id),
        "other_token": _make_token(eid=other_estimate_id, cid=customer_id,
                                     tid=other_tenant_id),
    }

    # Teardown — leave the ``@example.com`` users to the session
    # cleanup fixture; wipe the tenant + estimate rows + analytics
    # events directly.
    dbc.tenants.delete_many({"id": {"$in": [tenant_id, other_tenant_id]}})
    dbc.quotes.delete_many({"id": {"$in": [estimate_id, other_estimate_id]}})
    dbc.proposal_analytics_events.delete_many(
        {"tenant_id": {"$in": [tenant_id, other_tenant_id]}},
    )
    dbc.proposal_analytics_rate.delete_many({})


def _post_event(body: Dict[str, Any], *, estimate_id: str,
                 content_type: str = "application/json",
                 x_forwarded_for: str | None = None):
    """Fire POST /api/analytics/proposal/{estimate_id}/event through
    the ASGI transport. Returns (status_code, json_body)."""
    async def _drive(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            headers = {"Content-Type": content_type}
            if x_forwarded_for:
                headers["X-Forwarded-For"] = x_forwarded_for
            resp = await ac.post(
                f"/api/analytics/proposal/{estimate_id}/event",
                headers=headers,
                content=json.dumps(body).encode("utf-8"),
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            return resp.status_code, data
    return run_test(_drive)


def _admin_get(path: str, admin_id: str, tenant_id: str):
    """Fire an admin-authenticated GET via a dependency-override so we
    don't need to mint a real login JWT."""
    async def _drive(_db):
        from utils import get_current_user as _dep_user
        from routers.tenants import get_current_tenant as _dep_tenant
        app = _get_app()
        app.dependency_overrides[_dep_user] = lambda: {
            "id": admin_id, "role": "admin", "tenant_id": tenant_id,
        }
        app.dependency_overrides[_dep_tenant] = lambda: {
            "id": tenant_id, "slug": "test", "name": "Test",
        }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                resp = await ac.get(path)
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
                return resp.status_code, data
        finally:
            app.dependency_overrides.pop(_dep_user, None)
            app.dependency_overrides.pop(_dep_tenant, None)
    return run_test(_drive)


def _admin_get_as_tech(path: str, tech_id: str, tenant_id: str):
    async def _drive(_db):
        from utils import get_current_user as _dep_user
        from routers.tenants import get_current_tenant as _dep_tenant
        app = _get_app()
        app.dependency_overrides[_dep_user] = lambda: {
            "id": tech_id, "role": "technician", "tenant_id": tenant_id,
        }
        app.dependency_overrides[_dep_tenant] = lambda: {
            "id": tenant_id, "slug": "test", "name": "Test",
        }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                resp = await ac.get(path)
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
                return resp.status_code, data
        finally:
            app.dependency_overrides.pop(_dep_user, None)
            app.dependency_overrides.pop(_dep_tenant, None)
    return run_test(_drive)


# ═════════════════════════════════════════════════════════════════════
# Ingestion tests
# ═════════════════════════════════════════════════════════════════════
def test_open_event_persists_with_hashed_ip(seeded, dbc):
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    code, body = _post_event(
        {"token": seeded["token"], "session_id": sid, "event_type": "open"},
        estimate_id=seeded["estimate_id"],
        x_forwarded_for="203.0.113.42, 10.0.0.1",
    )
    assert code == 200, body
    assert body["status"] == "ok"
    row = dbc.proposal_analytics_events.find_one(
        {"id": body["id"]}, {"_id": 0},
    )
    assert row is not None
    assert row["session_id"] == sid
    assert row["event_type"] == "open"
    assert row["tenant_id"] == seeded["tenant_id"]
    assert row["estimate_id"] == seeded["estimate_id"]
    assert row["ip_hash"].startswith("sha256:")
    # Raw IP must NEVER appear anywhere in the doc.
    assert "203.0.113.42" not in json.dumps(row)


def test_open_event_is_idempotent_per_session(seeded, dbc):
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    code1, body1 = _post_event(
        {"token": seeded["token"], "session_id": sid, "event_type": "open"},
        estimate_id=seeded["estimate_id"],
    )
    code2, body2 = _post_event(
        {"token": seeded["token"], "session_id": sid, "event_type": "open"},
        estimate_id=seeded["estimate_id"],
    )
    assert code1 == 200 and code2 == 200
    assert body2.get("deduped") is True
    assert body1["id"] == body2["id"]
    n = dbc.proposal_analytics_events.count_documents(
        {"session_id": sid, "event_type": "open"},
    )
    assert n == 1


def test_page_view_event_persists_with_duration(seeded, dbc):
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    code, body = _post_event(
        {"token": seeded["token"], "session_id": sid,
         "event_type": "page_view",
         "page_index": 2, "page_key": "service:svc-1",
         "duration_ms": 4200},
        estimate_id=seeded["estimate_id"],
    )
    assert code == 200, body
    row = dbc.proposal_analytics_events.find_one(
        {"id": body["id"]}, {"_id": 0},
    )
    assert row["duration_ms"] == 4200
    assert row["page_index"] == 2
    assert row["page_key"] == "service:svc-1"


def test_click_event_persists_with_button_id(seeded, dbc):
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    code, body = _post_event(
        {"token": seeded["token"], "session_id": sid,
         "event_type": "click", "button_id": "approve"},
        estimate_id=seeded["estimate_id"],
    )
    assert code == 200, body
    row = dbc.proposal_analytics_events.find_one(
        {"id": body["id"]}, {"_id": 0},
    )
    assert row["button_id"] == "approve"


def test_sendbeacon_text_plain_body_is_accepted(seeded, dbc):
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    code, body = _post_event(
        {"token": seeded["token"], "session_id": sid,
         "event_type": "close"},
        estimate_id=seeded["estimate_id"],
        content_type="text/plain",   # navigator.sendBeacon default
    )
    assert code == 200, body
    n = dbc.proposal_analytics_events.count_documents(
        {"session_id": sid, "event_type": "close"},
    )
    assert n == 1


def test_rate_limit_121st_event_returns_429(seeded, dbc):
    sid = f"sess_ratelimit_{uuid.uuid4().hex[:12]}"
    # Fire 120 page_view events — should all pass.
    codes = []
    for i in range(121):
        c, _ = _post_event(
            {"token": seeded["token"], "session_id": sid,
             "event_type": "page_view",
             "page_index": i % 5, "page_key": "cover",
             "duration_ms": 50},
            estimate_id=seeded["estimate_id"],
        )
        codes.append(c)
    # First 120 must pass, 121st must be 429.
    assert codes.count(200) == 120, (
        f"expected 120x200, got {codes.count(200)}. all={codes}"
    )
    assert codes[-1] == 429
    # Cleanup so subsequent tests aren't rate-limited on this sid.
    dbc.proposal_analytics_rate.delete_one({"session_id": sid})


def test_invalid_token_returns_401(seeded):
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    # Garbage token
    code, body = _post_event(
        {"token": "not.a.real.jwt", "session_id": sid,
         "event_type": "open"},
        estimate_id=seeded["estimate_id"],
    )
    assert code == 401, body


def test_cross_tenant_token_cannot_log_other_tenant_estimate(seeded, dbc):
    # Token for OTHER tenant's estimate paired with THIS estimate id in
    # the URL → estimate_mismatch → 404.
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    code, body = _post_event(
        {"token": seeded["other_token"], "session_id": sid,
         "event_type": "open"},
        estimate_id=seeded["estimate_id"],
    )
    assert code == 404, body
    # And nothing got written.
    n = dbc.proposal_analytics_events.count_documents({"session_id": sid})
    assert n == 0


def test_summary_endpoint_returns_correct_rollup(seeded, dbc):
    sid_a = f"sess_sum_a_{uuid.uuid4().hex[:8]}"
    sid_b = f"sess_sum_b_{uuid.uuid4().hex[:8]}"
    # Seed a controlled set: 2 unique sessions, 3 page_views, 2 clicks.
    for sid in (sid_a, sid_b):
        _post_event(
            {"token": seeded["token"], "session_id": sid,
             "event_type": "open"},
            estimate_id=seeded["estimate_id"],
        )
    _post_event(
        {"token": seeded["token"], "session_id": sid_a,
         "event_type": "page_view", "page_index": 0,
         "page_key": "cover", "duration_ms": 1000},
        estimate_id=seeded["estimate_id"],
    )
    _post_event(
        {"token": seeded["token"], "session_id": sid_a,
         "event_type": "page_view", "page_index": 1,
         "page_key": "total", "duration_ms": 2000},
        estimate_id=seeded["estimate_id"],
    )
    _post_event(
        {"token": seeded["token"], "session_id": sid_b,
         "event_type": "page_view", "page_index": 0,
         "page_key": "cover", "duration_ms": 500},
        estimate_id=seeded["estimate_id"],
    )
    _post_event(
        {"token": seeded["token"], "session_id": sid_a,
         "event_type": "click", "button_id": "approve"},
        estimate_id=seeded["estimate_id"],
    )
    _post_event(
        {"token": seeded["token"], "session_id": sid_b,
         "event_type": "click", "button_id": "download_pdf"},
        estimate_id=seeded["estimate_id"],
    )
    # Now fetch summary.
    code, body = _admin_get(
        f"/api/analytics/proposal/{seeded['estimate_id']}/summary",
        seeded["admin_id"], seeded["tenant_id"],
    )
    assert code == 200, body
    assert body["opens"] >= 2
    assert body["unique_sessions"] >= 2
    assert body["clicks"] >= 2
    assert body["clicks_by_button"].get("approve") >= 1
    assert body["clicks_by_button"].get("download_pdf") >= 1
    assert body["page_views_by_key"].get("cover") >= 2
    assert body["page_views_by_key"].get("total") >= 1
    assert body["avg_pages_viewed"] > 0
    assert body["avg_session_duration_ms"] > 0


def test_overview_endpoint_returns_estimate_list(seeded, dbc):
    code, body = _admin_get(
        "/api/analytics/proposals/overview?date_range=30d",
        seeded["admin_id"], seeded["tenant_id"],
    )
    assert code == 200, body
    assert body["date_range"] == "30d"
    ids = [r["estimate_id"] for r in body.get("estimates") or []]
    assert seeded["estimate_id"] in ids
    row = next(r for r in body["estimates"]
                if r["estimate_id"] == seeded["estimate_id"])
    assert row["estimate"]["id"] == seeded["estimate_id"]
    assert row["opens"] >= 1


def test_admin_gate_rejects_technician(seeded):
    code, body = _admin_get_as_tech(
        f"/api/analytics/proposal/{seeded['estimate_id']}/summary",
        seeded["tech_id"], seeded["tenant_id"],
    )
    assert code == 403, body
    code2, _ = _admin_get_as_tech(
        f"/api/analytics/proposal/{seeded['estimate_id']}/events",
        seeded["tech_id"], seeded["tenant_id"],
    )
    assert code2 == 403
    code3, _ = _admin_get_as_tech(
        "/api/analytics/proposals/overview",
        seeded["tech_id"], seeded["tenant_id"],
    )
    assert code3 == 403

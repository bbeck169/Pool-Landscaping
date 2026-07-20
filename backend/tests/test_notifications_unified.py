"""Unified Notifications ship · backend tests (Feb 2026).

Covers the notification-preference defaults, quiet-hours suppression,
and the four default-ON push categories for admins:

  * ``review_received`` + ``review_low_star``
  * ``chat_dm_to_admin``
  * ``inbound_customer_message``
  * ``new_lead``  (fired by BOTH InstaQuote + InstaSchedule).

Everything else is default-OFF for push and must be flippable via the
prefs endpoint. In-app inbox continues to record every emit regardless
of push toggle so users can browse events they muted.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 30


def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], (d.get("user") or {}).get("id"), (d.get("user") or {}).get("role")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_ctx():
    tok, uid, role = _login("admin@aquaterra.com",
                             demo_pw("admin@aquaterra.com"))
    return {"tok": tok, "uid": uid, "role": role}


@pytest.fixture(scope="module")
def tech_ctx():
    tok, uid, role = _login("mike@aquaterra.com",
                             demo_pw("mike@aquaterra.com"))
    return {"tok": tok, "uid": uid, "role": role}


@pytest.fixture(scope="module")
def tenant_id(admin_ctx):
    r = requests.get(f"{API}/tenants/current",
                      headers=_h(admin_ctx["tok"]), timeout=T)
    return r.json()["id"]


# ═════════════════════════════════════════════════════════════════════
class TestDefaults:
    def test_admin_defaults_have_five_push_on(self, admin_ctx):
        r = requests.get(f"{API}/settings/notifications",
                          headers=_h(admin_ctx["tok"]), timeout=T)
        assert r.status_code == 200
        j = r.json()
        chans = j.get("channels") or {}
        # Push-ON set for admins (Feb-2026 spec).
        expected_on = {
            "review_received", "review_low_star",
            "chat_dm_to_admin", "inbound_customer_message", "new_lead",
        }
        on_set = {k for k, v in chans.items() if v.get("push")}
        for k in expected_on:
            assert k in on_set, f"admin should default push-ON for {k}"
        # Every kind ships bell=True (in-app inbox is exhaustive).
        for k, v in chans.items():
            assert v.get("bell") is True, f"bell default must stay True for {k}"

    def test_tech_defaults_narrower(self, tech_ctx):
        r = requests.get(f"{API}/settings/notifications",
                          headers=_h(tech_ctx["tok"]), timeout=T)
        assert r.status_code == 200
        chans = (r.json() or {}).get("channels") or {}
        # Tech should NOT default push-ON for new_lead OR chat_dm_to_admin.
        assert chans.get("new_lead", {}).get("push") is False
        assert chans.get("chat_dm_to_admin", {}).get("push") is False
        # But should default push-ON for their own chat_mention_in_channel.
        assert chans.get("chat_mention_in_channel", {}).get("push") is True


class TestPrefsPersistence:
    def test_flip_push_and_readback(self, admin_ctx):
        # Read then flip new_lead push OFF.
        cur = requests.get(f"{API}/settings/notifications",
                            headers=_h(admin_ctx["tok"]), timeout=T).json()
        chans = cur.get("channels") or {}
        chans.setdefault("new_lead", {}).update({"push": False})
        r = requests.put(f"{API}/settings/notifications",
                          json={"channels": chans},
                          headers=_h(admin_ctx["tok"]), timeout=T)
        assert r.status_code == 200
        fresh = requests.get(f"{API}/settings/notifications",
                              headers=_h(admin_ctx["tok"]), timeout=T).json()
        assert fresh["channels"]["new_lead"]["push"] is False
        # Restore.
        chans["new_lead"]["push"] = True
        requests.put(f"{API}/settings/notifications",
                      json={"channels": chans},
                      headers=_h(admin_ctx["tok"]), timeout=T)

    def test_quiet_hours_roundtrip(self, admin_ctx):
        body = {"channels": {},
                 "quiet_hours": {"enabled": True,
                                  "start_time": "22:00",
                                  "end_time":   "07:00",
                                  "timezone":   "UTC"}}
        r = requests.put(f"{API}/settings/notifications",
                          json=body, headers=_h(admin_ctx["tok"]), timeout=T)
        assert r.status_code == 200
        j = requests.get(f"{API}/settings/notifications",
                          headers=_h(admin_ctx["tok"]), timeout=T).json()
        qh = j.get("quiet_hours") or {}
        assert qh.get("enabled") is True
        assert qh.get("start_time") == "22:00"
        # Turn off quiet hours to avoid interfering with other tests.
        requests.put(f"{API}/settings/notifications",
                      json={"channels": {},
                             "quiet_hours": {"enabled": False,
                                              "start_time": "22:00",
                                              "end_time":   "07:00",
                                              "timezone":   "UTC"}},
                      headers=_h(admin_ctx["tok"]), timeout=T)


class TestInAppInboxAlwaysLogs:
    """Even when push is muted, the in-app row must still land."""

    def test_muted_new_lead_still_writes_bell_row(self, admin_ctx):
        # Mute push for new_lead.
        cur = requests.get(f"{API}/settings/notifications",
                            headers=_h(admin_ctx["tok"]), timeout=T).json()
        chans = cur.get("channels") or {}
        chans.setdefault("new_lead", {}).update({"push": False, "bell": True})
        requests.put(f"{API}/settings/notifications",
                      json={"channels": chans},
                      headers=_h(admin_ctx["tok"]), timeout=T)
        # Fire a synthetic new_lead via the InstaQuote pipeline.
        _fire_instaquote_submission(admin_ctx["tok"])
        # Poll admin's inbox for a new_lead row.
        found = False
        for _ in range(6):
            rows = requests.get(f"{API}/notifications",
                                  params={"kind": "new_lead", "limit": 20},
                                  headers=_h(admin_ctx["tok"]), timeout=T).json()
            if any(n.get("kind") == "new_lead" for n in rows):
                found = True
                break
            time.sleep(0.5)
        assert found, "in-app row must land even when push is muted"
        # Restore push=True.
        chans["new_lead"]["push"] = True
        requests.put(f"{API}/settings/notifications",
                      json={"channels": chans},
                      headers=_h(admin_ctx["tok"]), timeout=T)


class TestNewLead:
    def test_instaquote_fires_new_lead(self, admin_ctx):
        before = _count_kind(admin_ctx["tok"], "new_lead")
        _fire_instaquote_submission(admin_ctx["tok"])
        after = None
        for _ in range(6):
            after = _count_kind(admin_ctx["tok"], "new_lead")
            if after > before:
                break
            time.sleep(0.5)
        assert after and after > before, \
            f"instaquote submit must trigger new_lead (before={before}, after={after})"

    def test_instaschedule_fires_new_lead(self, admin_ctx):
        # Ensure at least one active InstaSchedule config exists.
        cfg_id = _ensure_instaschedule_config(admin_ctx["tok"])
        cfg = requests.get(f"{API}/instaschedule/configs/{cfg_id}",
                            headers=_h(admin_ctx["tok"]), timeout=T).json()
        slug = cfg["slug"]
        st = (cfg.get("service_types") or [{}])[0]
        # Fetch tomorrow's slots.
        from datetime import date, timedelta
        target = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        s = requests.get(f"{API}/public/instaschedule/{slug}/slots",
                          params={"service_type_id": st.get("id"),
                                   "date": target}, timeout=T).json()
        slots = s.get("slots") or []
        if not slots:
            pytest.skip("no bookable slots for the seeded config")
        before = _count_kind(admin_ctx["tok"], "new_lead")
        # Reset rate limit so this test is deterministic.
        requests.post(f"{API}/instaschedule/rate-limit/reset",
                        headers=_h(admin_ctx["tok"]), timeout=T)
        r = requests.post(f"{API}/public/instaschedule/{slug}/book",
                            json={
                                "service_type_id": st.get("id"),
                                "requested_slot": {
                                    "start_iso": slots[0]["start_iso"],
                                    "end_iso":   slots[0]["end_iso"],
                                },
                                "contact": {
                                    "name": f"TEST_lead_{uuid.uuid4().hex[:6]}",
                                    "email": f"lead-{uuid.uuid4().hex[:6]}@example.com",
                                    "address": "123 Test Ln, TESTville",
                                },
                            }, timeout=T)
        assert r.status_code == 201, r.text
        after = None
        for _ in range(6):
            after = _count_kind(admin_ctx["tok"], "new_lead")
            if after > before:
                break
            time.sleep(0.5)
        assert after and after > before, \
            "instaschedule book must trigger new_lead"


class TestReviewLowStar:
    def test_low_star_fires_low_and_received(self, admin_ctx):
        # Seed a customer + review request → submit 2-star rating.
        cust_id = _ensure_customer(admin_ctx["tok"])
        req = requests.post(f"{API}/reviews/requests",
                             json={"customer_id": cust_id,
                                    "sent_via": "link_only",
                                    "expedite": True},
                             headers=_h(admin_ctx["tok"]), timeout=T).json()
        token = req.get("token")
        assert token, req
        before_recv = _count_kind(admin_ctx["tok"], "review_received")
        before_low = _count_kind(admin_ctx["tok"], "review_low_star")
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                            json={"star_rating": 2}, timeout=T)
        assert r.status_code == 200, r.text
        after_recv = None
        after_low = None
        for _ in range(6):
            after_recv = _count_kind(admin_ctx["tok"], "review_received")
            after_low = _count_kind(admin_ctx["tok"], "review_low_star")
            if after_recv > before_recv and after_low > before_low:
                break
            time.sleep(0.5)
        assert after_recv and after_recv > before_recv, \
            "review_received should fire for every rating"
        assert after_low and after_low > before_low, \
            "review_low_star should fire for ≤3-star ratings"

    def test_high_star_does_not_fire_low(self, admin_ctx):
        cust_id = _ensure_customer(admin_ctx["tok"], suffix="hi")
        req = requests.post(f"{API}/reviews/requests",
                             json={"customer_id": cust_id,
                                    "sent_via": "link_only",
                                    "expedite": True},
                             headers=_h(admin_ctx["tok"]), timeout=T).json()
        token = req.get("token")
        if not token:
            pytest.skip("dedup blocked review-request seed")
        before_low = _count_kind(admin_ctx["tok"], "review_low_star")
        before_recv = _count_kind(admin_ctx["tok"], "review_received")
        r = requests.post(f"{API}/reviews/public/r/{token}/rating",
                            json={"star_rating": 5}, timeout=T)
        assert r.status_code == 200
        # Wait for propagation.
        after_recv = None
        for _ in range(6):
            after_recv = _count_kind(admin_ctx["tok"], "review_received")
            if after_recv > before_recv:
                break
            time.sleep(0.5)
        after_low = _count_kind(admin_ctx["tok"], "review_low_star")
        assert after_recv and after_recv > before_recv, \
            "review_received should fire for high stars too"
        assert after_low == before_low, \
            f"review_low_star must NOT fire for 5-star (before={before_low}, after={after_low})"


# ── helpers ────────────────────────────────────────────────────────────

def _count_kind(tok: str, kind: str) -> int:
    r = requests.get(f"{API}/notifications",
                      params={"kind": kind, "limit": 500},
                      headers=_h(tok), timeout=T)
    if r.status_code != 200:
        return 0
    return len(r.json())


def _fire_instaquote_submission(admin_tok: str) -> None:
    """Ensure an active InstaQuote config and submit a public quote."""
    cfg_id = _ensure_instaquote_config(admin_tok)
    cfg = requests.get(f"{API}/instaquote/configs/{cfg_id}",
                        headers=_h(admin_tok), timeout=T).json()
    slug = cfg["slug"]
    svc = (cfg.get("services") or [{}])[0]
    requests.post(f"{API}/instaquote/rate-limit/reset",
                    headers=_h(admin_tok), timeout=T)
    r = requests.post(f"{API}/public/instaquote/{slug}/submit",
                       json={
                           "contact": {
                               "name": f"TEST_iq_{uuid.uuid4().hex[:6]}",
                               "email": f"iq-{uuid.uuid4().hex[:6]}@example.com",
                           },
                           "selections": [{
                               "service_id": svc.get("id"),
                               "qty": 1,
                           }],
                       }, timeout=T)
    assert r.status_code == 201, r.text


def _ensure_instaquote_config(admin_tok: str) -> str:
    rows = requests.get(f"{API}/instaquote/configs",
                          headers=_h(admin_tok), timeout=T).json().get("configs") or []
    active = next((c for c in rows if c.get("active")), None)
    if active:
        return active["id"]
    # Create + activate.
    slug = f"tst-notif-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/instaquote/configs",
                        json={
                            "slug": slug,
                            "headline": "TEST · notif config",
                            "services": [{
                                "name": "TEST Pool Weekly",
                                "base_price_cents": 15000,
                                "unit": "visit",
                                "min_qty": 1, "max_qty": 4,
                            }],
                            "active": True,
                        }, headers=_h(admin_tok), timeout=T)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    requests.post(f"{API}/instaquote/configs/{cid}/activate",
                    headers=_h(admin_tok), timeout=T)
    return cid


def _ensure_instaschedule_config(admin_tok: str) -> str:
    rows = requests.get(f"{API}/instaschedule/configs",
                          headers=_h(admin_tok), timeout=T).json().get("configs") or []
    active = next((c for c in rows if c.get("active")), None)
    if active:
        return active["id"]
    slug = f"tst-notif-sch-{uuid.uuid4().hex[:6]}"
    windows = {d: [{"start": "08:00", "end": "18:00"}]
                 for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    r = requests.post(f"{API}/instaschedule/configs",
                        json={
                            "slug": slug,
                            "headline": "TEST · sched config",
                            "service_types": [{
                                "name": "TEST Weekly Pool",
                                "duration_minutes": 60,
                                "allow_public_book": True,
                            }],
                            "availability_rules": {
                                "timezone": "UTC",
                                "weekday_windows": windows,
                                "blackout_dates": [],
                                "max_bookings_per_day": 20,
                                "min_notice_hours": 0,
                                "max_lead_days": 30,
                            },
                            "route_integration": {"enabled": False,
                                                    "assign_strategy": "admin_manual"},
                            "active": True,
                        }, headers=_h(admin_tok), timeout=T)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ensure_customer(admin_tok: str, suffix: str = "") -> str:
    email = f"testreview-{suffix}-{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(f"{API}/customers",
                       json={"name": f"TEST_Review_{suffix or 'A'}",
                              "email": email,
                              "phone": f"+1555{uuid.uuid4().int % 10_000_000:07d}"},
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]

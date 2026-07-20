"""QuoteIQ Phase Q5 — InstaSchedule (Public self-book) tests."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com", demo_pw("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    r = requests.get(f"{API}/tenants/current", headers=_h(admin_tok), timeout=T)
    return r.json()["id"]


@pytest.fixture(scope="module", autouse=True)
def _reset_rate_limit(admin_tok):
    """Reset the InstaSchedule rate-limit counter around the module."""
    def _reset():
        try:
            requests.post(f"{API}/instaschedule/rate-limit/reset",
                             headers=_h(admin_tok), timeout=T)
        except Exception:
            pass
    _reset()
    yield _reset
    _reset()


def _tomorrow_ymd(days: int = 1) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)) \
        .strftime("%Y-%m-%d")


def _sample_config(slug: str, days_ahead: int = 30) -> dict:
    """Config that permits booking every weekday 09:00-17:00 for a
    30-day window. Timezone kept UTC so slot ISOs align with the
    test's ``datetime.utcnow`` comparisons."""
    windows = [{"start": "09:00", "end": "17:00"}]
    return {
        "slug": slug,
        "headline": "TEST_ InstaSchedule page",
        "brand_color": "#0284C7",
        "service_types": [
            {"name": "Weekly Pool Service",
              "duration_minutes": 60,
              "buffer_minutes": 0,
              "allow_public_book": True,
              "restricted_to_existing_customer": False,
              "requires_address": False},
            {"name": "Deep Clean",
              "duration_minutes": 120,
              "buffer_minutes": 15,
              "allow_public_book": True,
              "requires_address": True},
            {"name": "Internal Recheck",
              "duration_minutes": 30,
              "allow_public_book": False},
        ],
        "availability_rules": {
            "timezone": "UTC",
            "weekday_windows": {d: windows for d in
                                  ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
            "blackout_dates": [],
            "max_bookings_per_day": 20,
            "min_notice_hours": 0,
            "max_lead_days": days_ahead,
        },
        "route_integration": {"enabled": False,
                                "assign_strategy": "admin_manual"},
        "collect_fields": {"name": True, "email": True, "phone": True,
                             "notes": True},
        "thank_you_html": "Thanks!",
        "active": False,
    }


@pytest.fixture
def config(admin_tok):
    slug = f"sch-{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/instaschedule/configs",
                       json=_sample_config(slug),
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code == 201, r.text
    cfg = r.json()
    yield cfg
    requests.delete(f"{API}/instaschedule/configs/{cfg['id']}",
                     headers=_h(admin_tok), timeout=T)


@pytest.fixture
def active_config(admin_tok, config):
    r = requests.post(f"{API}/instaschedule/configs/{config['id']}/activate",
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code == 200
    fresh = requests.get(f"{API}/instaschedule/configs/{config['id']}",
                          headers=_h(admin_tok), timeout=T).json()
    yield fresh


def _first_public_svc(cfg):
    return next(s for s in cfg["service_types"] if s.get("allow_public_book"))


def _fetch_slots(slug, svc_id, when_ymd):
    return requests.get(
        f"{API}/public/instaschedule/{slug}/slots",
        params={"service_type_id": svc_id, "date": when_ymd},
        timeout=T,
    )


# ═════════════════════════════════════════════════════════════════════
# Admin CRUD
# ═════════════════════════════════════════════════════════════════════

class TestConfigCRUD:
    def test_create_list_get(self, admin_tok, config):
        rl = requests.get(f"{API}/instaschedule/configs",
                            headers=_h(admin_tok), timeout=T).json()
        assert any(c["id"] == config["id"] for c in rl["configs"])
        rg = requests.get(f"{API}/instaschedule/configs/{config['id']}",
                            headers=_h(admin_tok), timeout=T)
        assert rg.status_code == 200
        for s in rg.json()["service_types"]:
            assert s["id"]  # auto-assigned

    def test_slug_unique_409(self, admin_tok, config):
        r = requests.post(f"{API}/instaschedule/configs",
                            json={"slug": config["slug"],
                                    "service_types": []},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 409

    def test_patch(self, admin_tok, config):
        r = requests.patch(f"{API}/instaschedule/configs/{config['id']}",
                            json={"headline": "TEST_ patched"},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["headline"] == "TEST_ patched"

    def test_activate_exclusivity(self, admin_tok, config):
        alt = _sample_config(f"altsch-{uuid.uuid4().hex[:6]}")
        r = requests.post(f"{API}/instaschedule/configs", json=alt,
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201
        alt_id = r.json()["id"]
        try:
            requests.post(f"{API}/instaschedule/configs/{config['id']}/activate",
                             headers=_h(admin_tok), timeout=T)
            requests.post(f"{API}/instaschedule/configs/{alt_id}/activate",
                             headers=_h(admin_tok), timeout=T)
            rl = requests.get(f"{API}/instaschedule/configs",
                                headers=_h(admin_tok), timeout=T).json()
            actives = [c for c in rl["configs"] if c.get("active")]
            assert len(actives) == 1
            assert actives[0]["id"] == alt_id
        finally:
            requests.delete(f"{API}/instaschedule/configs/{alt_id}",
                             headers=_h(admin_tok), timeout=T)

    def test_delete(self, admin_tok):
        cfg = requests.post(f"{API}/instaschedule/configs",
                              json=_sample_config(f"del-{uuid.uuid4().hex[:6]}"),
                              headers=_h(admin_tok), timeout=T).json()
        r = requests.delete(f"{API}/instaschedule/configs/{cfg['id']}",
                              headers=_h(admin_tok), timeout=T)
        assert r.status_code == 204

    def test_bad_strategy_422(self, admin_tok):
        bad = _sample_config(f"bad-{uuid.uuid4().hex[:6]}")
        bad["route_integration"] = {"enabled": True,
                                       "assign_strategy": "hologram"}
        r = requests.post(f"{API}/instaschedule/configs", json=bad,
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 422


class TestRBAC:
    def test_tech_forbidden(self, tech_tok):
        r = requests.get(f"{API}/instaschedule/configs",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403

    def test_tech_forbidden_confirm(self, tech_tok):
        r = requests.post(f"{API}/instaschedule/bookings/x/confirm",
                            headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


class TestTenantIsolation:
    def test_configs_scoped(self, admin_tok, tenant_id, config):
        rl = requests.get(f"{API}/instaschedule/configs",
                            headers=_h(admin_tok), timeout=T).json()
        for c in rl["configs"]:
            assert c["tenant_id"] == tenant_id


# ═════════════════════════════════════════════════════════════════════
# Public projection + Slots
# ═════════════════════════════════════════════════════════════════════

class TestPublicConfig:
    def test_inactive_404(self, config):
        r = requests.get(f"{API}/public/instaschedule/{config['slug']}",
                          timeout=T)
        assert r.status_code == 404

    def test_active_returns_safe_view(self, active_config):
        r = requests.get(f"{API}/public/instaschedule/{active_config['slug']}",
                          timeout=T)
        assert r.status_code == 200
        body = r.json()
        for leaky in ("tenant_id", "id", "created_at", "active"):
            assert leaky not in body
        # Non-public service types must NOT appear.
        names = [s["name"] for s in body["service_types"]]
        assert "Internal Recheck" not in names


class TestSlotComputation:
    def test_weekday_windows_and_step(self, active_config):
        svc = _first_public_svc(active_config)
        when = _tomorrow_ymd(1)
        r = _fetch_slots(active_config["slug"], svc["id"], when)
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        # 8h window / 60m step = 8 slots.
        assert len(slots) == 8
        assert slots[0]["start_iso"].startswith(f"{when}T09:00:00")
        assert slots[-1]["start_iso"].startswith(f"{when}T16:00:00")

    def test_blackout_returns_empty(self, admin_tok, active_config):
        when = _tomorrow_ymd(2)
        requests.patch(f"{API}/instaschedule/configs/{active_config['id']}",
                         json={"availability_rules": {
                             **active_config["availability_rules"],
                             "blackout_dates": [when],
                         }},
                         headers=_h(admin_tok), timeout=T)
        svc = _first_public_svc(active_config)
        r = _fetch_slots(active_config["slug"], svc["id"], when)
        assert r.status_code == 200
        assert r.json()["slots"] == []

    def test_max_lead_days_horizon(self, active_config):
        svc = _first_public_svc(active_config)
        far = (datetime.now(timezone.utc).date()
                 + timedelta(days=100)).strftime("%Y-%m-%d")
        r = _fetch_slots(active_config["slug"], svc["id"], far)
        assert r.status_code == 200
        assert r.json()["slots"] == []

    def test_past_date_returns_empty(self, active_config):
        svc = _first_public_svc(active_config)
        past = (datetime.now(timezone.utc).date()
                  - timedelta(days=1)).strftime("%Y-%m-%d")
        r = _fetch_slots(active_config["slug"], svc["id"], past)
        assert r.status_code == 200
        assert r.json()["slots"] == []

    def test_min_notice_filters_early_slots(self, admin_tok, active_config):
        # Set a huge min-notice → today's remaining slots evaporate.
        requests.patch(f"{API}/instaschedule/configs/{active_config['id']}",
                         json={"availability_rules": {
                             **active_config["availability_rules"],
                             "min_notice_hours": 24 * 365,
                         }},
                         headers=_h(admin_tok), timeout=T)
        svc = _first_public_svc(active_config)
        r = _fetch_slots(active_config["slug"], svc["id"], _tomorrow_ymd(1))
        assert r.status_code == 200
        assert r.json()["slots"] == []

    def test_bad_date_422(self, active_config):
        svc = _first_public_svc(active_config)
        r = _fetch_slots(active_config["slug"], svc["id"], "not-a-date")
        assert r.status_code == 422

    def test_service_type_not_bookable_404(self, active_config):
        # "Internal Recheck" has allow_public_book=False.
        st = next(s for s in active_config["service_types"]
                   if s["name"] == "Internal Recheck")
        r = _fetch_slots(active_config["slug"], st["id"], _tomorrow_ymd(1))
        assert r.status_code == 404


class TestPublicBookHappyPath:
    def test_book_succeeds_and_persists(self, admin_tok, active_config,
                                           _reset_rate_limit):
        _reset_rate_limit()
        svc = _first_public_svc(active_config)
        when = _tomorrow_ymd(3)
        slots = _fetch_slots(active_config["slug"], svc["id"], when).json()["slots"]
        assert slots, "no slots to book"
        slot = slots[0]
        headers = {"Content-Type": "application/json",
                    "X-Forwarded-For": f"203.0.113.{uuid.uuid4().int % 254 + 1}"}
        r = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            headers=headers, timeout=T,
            json={"service_type_id": svc["id"],
                   "requested_slot": {"start_iso": slot["start_iso"],
                                        "end_iso": slot["end_iso"]},
                   "contact": {"name": "Alex Rio",
                                "email": "alex@example.com",
                                "phone": "+15551110001"},
                   "notes": "Please call when arriving."},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        for k in ("id", "status", "service_type_id", "requested_slot",
                    "thank_you_html", "success_redirect_url"):
            assert k in body
        assert body["status"] == "pending"
        # Persisted server-side.
        got = requests.get(
            f"{API}/instaschedule/bookings/{body['id']}",
            headers=_h(admin_tok), timeout=T,
        ).json()
        assert got["contact"]["email"] == "alex@example.com"
        assert got["requested_slot"]["start_iso"] == slot["start_iso"]


class TestHoneypot:
    def test_ack_shape_identical(self, active_config, _reset_rate_limit):
        _reset_rate_limit()
        svc = _first_public_svc(active_config)
        when = _tomorrow_ymd(4)
        slots = _fetch_slots(active_config["slug"], svc["id"], when).json()["slots"]
        slot = slots[0]
        headers = {"Content-Type": "application/json"}
        real = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            headers=headers, timeout=T,
            json={"service_type_id": svc["id"],
                   "requested_slot": {"start_iso": slot["start_iso"],
                                        "end_iso": slot["end_iso"]},
                   "contact": {"email": "real@example.com"}},
        ).json()
        honey = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            headers=headers, timeout=T,
            json={"service_type_id": svc["id"],
                   "requested_slot": {"start_iso": slot["start_iso"],
                                        "end_iso": slot["end_iso"]},
                   "contact": {"email": "spam@example.com"},
                   "_hp": "gotcha"},
        ).json()
        assert sorted(real.keys()) == sorted(honey.keys())
        assert honey["requested_slot"] == real["requested_slot"]
        assert "spam_swallowed" not in honey


class TestRateLimit:
    def test_kicks_in_after_3(self, active_config, _reset_rate_limit):
        _reset_rate_limit()
        svc = _first_public_svc(active_config)
        when = _tomorrow_ymd(5)
        slots = _fetch_slots(active_config["slug"], svc["id"], when).json()["slots"]
        slot = slots[0]
        fake_ip = f"203.0.113.{uuid.uuid4().int % 254 + 1}"
        headers = {"Content-Type": "application/json",
                    "X-Forwarded-For": fake_ip}
        allowed = 0
        seen_429 = False
        for _ in range(10):
            r = requests.post(
                f"{API}/public/instaschedule/{active_config['slug']}/book",
                headers=headers, timeout=T,
                json={"service_type_id": svc["id"],
                       "requested_slot": {"start_iso": slot["start_iso"],
                                            "end_iso": slot["end_iso"]},
                       "contact": {"email": "rl@example.com"}},
            )
            if r.status_code == 429:
                seen_429 = True
                break
            allowed += 1
        assert seen_429
        assert allowed <= 3
        _reset_rate_limit()


class TestRaceGuard:
    def test_double_book_same_slot_conflict(self, admin_tok, active_config,
                                              _reset_rate_limit):
        _reset_rate_limit()
        svc = _first_public_svc(active_config)
        when = _tomorrow_ymd(6)
        slots = _fetch_slots(active_config["slug"], svc["id"], when).json()["slots"]
        slot = slots[0]
        payload = {"service_type_id": svc["id"],
                    "requested_slot": {"start_iso": slot["start_iso"],
                                         "end_iso": slot["end_iso"]},
                    "contact": {"email": "race@example.com"}}
        h1 = {"Content-Type": "application/json",
                "X-Forwarded-For": f"203.0.114.{uuid.uuid4().int % 254 + 1}"}
        h2 = {"Content-Type": "application/json",
                "X-Forwarded-For": f"203.0.114.{uuid.uuid4().int % 254 + 1}"}
        r1 = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            json=payload, headers=h1, timeout=T)
        r2 = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            json=payload, headers=h2, timeout=T)
        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [201, 409], f"expected [201,409], got {codes}"


class TestGating:
    def test_requires_address(self, active_config, _reset_rate_limit):
        _reset_rate_limit()
        # "Deep Clean" has requires_address=True.
        st = next(s for s in active_config["service_types"]
                   if s["name"] == "Deep Clean")
        when = _tomorrow_ymd(7)
        slots = _fetch_slots(active_config["slug"], st["id"], when).json()["slots"]
        slot = slots[0]
        r = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            headers={"Content-Type": "application/json",
                       "X-Forwarded-For": f"203.0.115.{uuid.uuid4().int % 254 + 1}"},
            json={"service_type_id": st["id"],
                   "requested_slot": {"start_iso": slot["start_iso"],
                                        "end_iso": slot["end_iso"]},
                   "contact": {"email": "noaddr@example.com"}},
            timeout=T,
        )
        assert r.status_code == 422

    def test_restricted_to_existing_customer(self, admin_tok, active_config,
                                                _reset_rate_limit):
        _reset_rate_limit()
        # Flip one service to restricted.
        st_id = active_config["service_types"][0]["id"]
        new_svcs = [
            {**s, "restricted_to_existing_customer": True} if s["id"] == st_id
            else s
            for s in active_config["service_types"]
        ]
        requests.patch(f"{API}/instaschedule/configs/{active_config['id']}",
                         json={"service_types": new_svcs},
                         headers=_h(admin_tok), timeout=T)
        when = _tomorrow_ymd(8)
        slots = _fetch_slots(active_config["slug"], st_id, when).json()["slots"]
        slot = slots[0]
        # Non-existent email → 403.
        r = requests.post(
            f"{API}/public/instaschedule/{active_config['slug']}/book",
            headers={"Content-Type": "application/json",
                       "X-Forwarded-For": f"203.0.116.{uuid.uuid4().int % 254 + 1}"},
            json={"service_type_id": st_id,
                   "requested_slot": {"start_iso": slot["start_iso"],
                                        "end_iso": slot["end_iso"]},
                   "contact": {"email": f"ghost-{uuid.uuid4().hex[:6]}@example.com"}},
            timeout=T,
        )
        assert r.status_code == 403


# ═════════════════════════════════════════════════════════════════════
# Confirm / Decline / Cancel
# ═════════════════════════════════════════════════════════════════════

def _create_booking(admin_tok, active_config, day_offset=9):
    svc = _first_public_svc(active_config)
    when = _tomorrow_ymd(day_offset)
    slots = _fetch_slots(active_config["slug"], svc["id"], when).json()["slots"]
    assert slots, "no slots"
    slot = slots[0]
    r = requests.post(
        f"{API}/public/instaschedule/{active_config['slug']}/book",
        headers={"Content-Type": "application/json",
                   "X-Forwarded-For": f"203.0.117.{uuid.uuid4().int % 254 + 1}"},
        json={"service_type_id": svc["id"],
               "requested_slot": {"start_iso": slot["start_iso"],
                                    "end_iso": slot["end_iso"]},
               "contact": {"name": "Confirm Case",
                            "email": f"cfm-{uuid.uuid4().hex[:6]}@example.com",
                            "phone": "+15559998888",
                            "address": "123 Test Ln"}},
        timeout=T,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], svc, slot


class TestConfirm:
    def test_confirm_creates_job_and_customer(self, admin_tok, active_config,
                                                 _reset_rate_limit):
        _reset_rate_limit()
        bid, svc, slot = _create_booking(admin_tok, active_config, 10)
        r = requests.post(
            f"{API}/instaschedule/bookings/{bid}/confirm",
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["job_id"]
        assert body["customer_id"]
        assert body["booking"]["status"] == "confirmed"
        # Job persisted with the correct slot + source.
        job = requests.get(f"{API}/jobs/{body['job_id']}",
                             headers=_h(admin_tok), timeout=T).json()
        assert job["scheduled_start"] == slot["start_iso"]
        assert job["source"] == "instaschedule"
        assert job["instaschedule_booking_id"] == bid

    def test_double_confirm_409(self, admin_tok, active_config,
                                   _reset_rate_limit):
        _reset_rate_limit()
        bid, _, _ = _create_booking(admin_tok, active_config, 11)
        requests.post(f"{API}/instaschedule/bookings/{bid}/confirm",
                         headers=_h(admin_tok), timeout=T)
        r = requests.post(f"{API}/instaschedule/bookings/{bid}/confirm",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 409

    def test_round_robin_assigns_technician(self, admin_tok, active_config,
                                                _reset_rate_limit):
        _reset_rate_limit()
        # Flip strategy → round_robin and enable route integration.
        requests.patch(f"{API}/instaschedule/configs/{active_config['id']}",
                         json={"route_integration": {"enabled": True,
                                                        "assign_strategy": "round_robin"}},
                         headers=_h(admin_tok), timeout=T)
        bid, _, _ = _create_booking(admin_tok, active_config, 12)
        r = requests.post(f"{API}/instaschedule/bookings/{bid}/confirm",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        # Should have picked SOMEONE (there are seeded techs).
        assert r.json().get("assigned_user_id") is not None


class TestDecline:
    def test_decline_and_then_no_confirm(self, admin_tok, active_config,
                                            _reset_rate_limit):
        _reset_rate_limit()
        bid, _, _ = _create_booking(admin_tok, active_config, 13)
        r = requests.post(f"{API}/instaschedule/bookings/{bid}/decline",
                            headers=_h(admin_tok), timeout=T,
                            json={"reason": "outside service area",
                                    "notify_prospect": False})
        assert r.status_code == 200
        assert r.json()["status"] == "declined"
        r2 = requests.post(f"{API}/instaschedule/bookings/{bid}/confirm",
                             headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 409


class TestCancel:
    def test_cancel_cascades_to_job(self, admin_tok, active_config,
                                       _reset_rate_limit):
        _reset_rate_limit()
        bid, _, _ = _create_booking(admin_tok, active_config, 14)
        c = requests.post(f"{API}/instaschedule/bookings/{bid}/confirm",
                            headers=_h(admin_tok), timeout=T).json()
        job_id = c["job_id"]
        r = requests.post(f"{API}/instaschedule/bookings/{bid}/cancel",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        # Linked job cancelled too.
        job = requests.get(f"{API}/jobs/{job_id}",
                             headers=_h(admin_tok), timeout=T).json()
        assert job["status"] == "cancelled"


class TestErrorPaths:
    def test_confirm_unknown_404(self, admin_tok):
        r = requests.post(f"{API}/instaschedule/bookings/does-not-exist/confirm",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404

    def test_get_config_unknown_404(self, admin_tok):
        r = requests.get(f"{API}/instaschedule/configs/does-not-exist",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404


class TestOpenApi:
    def test_openapi_has_q5_paths(self):
        r = requests.get(f"{API}/openapi.json", timeout=T)
        paths = r.json().get("paths", {})
        want = [
            "/api/instaschedule/configs",
            "/api/instaschedule/configs/{cid}",
            "/api/instaschedule/configs/{cid}/activate",
            "/api/instaschedule/bookings",
            "/api/instaschedule/bookings/{bid}",
            "/api/instaschedule/bookings/{bid}/confirm",
            "/api/instaschedule/bookings/{bid}/decline",
            "/api/instaschedule/bookings/{bid}/cancel",
            "/api/public/instaschedule/{slug}",
            "/api/public/instaschedule/{slug}/slots",
            "/api/public/instaschedule/{slug}/book",
        ]
        for p in want:
            assert p in paths, f"missing OpenAPI path: {p}"

    def test_bookingackout_schema(self):
        r = requests.get(f"{API}/openapi.json", timeout=T)
        schemas = r.json().get("components", {}).get("schemas", {})
        assert "BookingAckOut" in schemas
        props = schemas["BookingAckOut"].get("properties", {})
        for k in ("id", "status", "service_type_id",
                    "requested_slot", "thank_you_html"):
            assert k in props

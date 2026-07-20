"""QuoteIQ Phase Q4 — InstaQuote (Public self-quote portal) tests."""
from __future__ import annotations

import os
import sys
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
    """Reset the in-memory IP rate-limiter before + after every module
    run so tests are order-independent. Reaches the running backend
    process via the admin ops endpoint (process-local variable, can't
    be cleared any other way from a pytest client)."""
    def _reset():
        try:
            requests.post(f"{API}/instaquote/rate-limit/reset",
                             headers=_h(admin_tok), timeout=T)
        except Exception:
            pass
    _reset()
    yield _reset
    _reset()


def _sample_config(slug: str) -> dict:
    return {
        "slug": slug,
        "headline": "TEST_ InstaQuote page",
        "subheadline": "Test only.",
        "brand_color": "#0284C7",
        "services": [
            {"name": "Weekly Pool Service", "description": "Chem + skim + brush",
              "base_price_cents": 12500, "unit": "visit",
              "min_qty": 1, "max_qty": 12},
            {"name": "One-time Deep Clean", "description": "Deep clean + shock",
              "base_price_cents": 25000, "unit": "job",
              "min_qty": 1, "max_qty": 1},
        ],
        "add_ons": [
            {"name": "Salt cell inspection", "price_cents": 4500},
            {"name": "Filter clean", "price_cents": 8500},
        ],
        "frequencies": [
            {"label": "Weekly", "multiplier": 1.0},
            {"label": "Bi-Weekly", "multiplier": 0.55},
            {"label": "One-time", "multiplier": 1.0},
        ],
        "collect_fields": {"name": True, "email": True, "phone": True,
                             "address": False, "notes": True},
        "thank_you_html": "Thanks — we'll reach out shortly.",
        "active": False,
    }


@pytest.fixture
def config(admin_tok):
    slug = f"test-{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{API}/instaquote/configs",
                       json=_sample_config(slug),
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code == 201, r.text
    cfg = r.json()
    yield cfg
    requests.delete(f"{API}/instaquote/configs/{cfg['id']}",
                     headers=_h(admin_tok), timeout=T)


@pytest.fixture
def active_config(admin_tok, config):
    r = requests.post(f"{API}/instaquote/configs/{config['id']}/activate",
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code == 200
    fresh = requests.get(f"{API}/instaquote/configs/{config['id']}",
                          headers=_h(admin_tok), timeout=T).json()
    yield fresh
    # Deactivate on teardown so subsequent tests aren't polluted.


# ═════════════════════════════════════════════════════════════════════
# Admin CRUD
# ═════════════════════════════════════════════════════════════════════

class TestConfigCRUD:
    def test_create_lists_and_get(self, admin_tok, config):
        rl = requests.get(f"{API}/instaquote/configs",
                            headers=_h(admin_tok), timeout=T).json()
        assert any(c["id"] == config["id"] for c in rl["configs"])
        rg = requests.get(f"{API}/instaquote/configs/{config['id']}",
                            headers=_h(admin_tok), timeout=T)
        assert rg.status_code == 200
        # Auto-generated IDs on services / add_ons / frequencies.
        for k in ("services", "add_ons", "frequencies"):
            for item in rg.json()[k]:
                assert item["id"]

    def test_slug_uniqueness_409(self, admin_tok, config):
        r = requests.post(f"{API}/instaquote/configs",
                            json={"slug": config["slug"], "services": []},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 409

    def test_patch_updates_and_normalizes_ids(self, admin_tok, config):
        # Add a service with no id — server assigns one.
        r = requests.patch(f"{API}/instaquote/configs/{config['id']}",
                            json={"services": [{"name": "TEST_ Extra",
                                                  "base_price_cents": 1000,
                                                  "unit": "visit"}]},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["services"][0]["id"]

    def test_activate_exclusivity(self, admin_tok, config):
        # Create a second config for the same tenant.
        alt = _sample_config(f"alt-{uuid.uuid4().hex[:8]}")
        r = requests.post(f"{API}/instaquote/configs", json=alt,
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201
        alt_id = r.json()["id"]
        try:
            requests.post(f"{API}/instaquote/configs/{config['id']}/activate",
                             headers=_h(admin_tok), timeout=T)
            requests.post(f"{API}/instaquote/configs/{alt_id}/activate",
                             headers=_h(admin_tok), timeout=T)
            rl = requests.get(f"{API}/instaquote/configs",
                                headers=_h(admin_tok), timeout=T).json()
            actives = [c for c in rl["configs"] if c.get("active")]
            assert len(actives) == 1
            assert actives[0]["id"] == alt_id
        finally:
            requests.delete(f"{API}/instaquote/configs/{alt_id}",
                             headers=_h(admin_tok), timeout=T)

    def test_delete(self, admin_tok):
        cfg = requests.post(f"{API}/instaquote/configs",
                              json=_sample_config(f"del-{uuid.uuid4().hex[:6]}"),
                              headers=_h(admin_tok), timeout=T).json()
        r = requests.delete(f"{API}/instaquote/configs/{cfg['id']}",
                              headers=_h(admin_tok), timeout=T)
        assert r.status_code == 204
        r = requests.get(f"{API}/instaquote/configs/{cfg['id']}",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404


class TestAdminRBAC:
    def test_tech_forbidden_on_list(self, tech_tok):
        r = requests.get(f"{API}/instaquote/configs",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403

    def test_tech_forbidden_on_create(self, tech_tok):
        r = requests.post(f"{API}/instaquote/configs",
                            json=_sample_config(f"tech-{uuid.uuid4().hex[:6]}"),
                            headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


class TestTenantIsolation:
    def test_admin_list_scoped_to_tenant(self, admin_tok, tenant_id, config):
        rl = requests.get(f"{API}/instaquote/configs",
                            headers=_h(admin_tok), timeout=T).json()
        for c in rl["configs"]:
            assert c["tenant_id"] == tenant_id


# ═════════════════════════════════════════════════════════════════════
# Public endpoints
# ═════════════════════════════════════════════════════════════════════

class TestPublicConfigFetch:
    def test_active_only(self, config):
        # Inactive → 404.
        r = requests.get(f"{API}/public/instaquote/{config['slug']}", timeout=T)
        assert r.status_code == 404

    def test_active_returns_public_view_only(self, active_config):
        r = requests.get(f"{API}/public/instaquote/{active_config['slug']}",
                          timeout=T)
        assert r.status_code == 200
        body = r.json()
        # Sensitive fields MUST NOT leak.
        for leaky in ("tenant_id", "id", "created_at", "updated_at",
                       "active"):
            assert leaky not in body, f"public leaked field: {leaky}"
        # Whitelisted fields present.
        for want in ("slug", "headline", "services", "add_ons",
                       "frequencies", "collect_fields"):
            assert want in body


class TestPublicSubmit:
    def _wk_selection(self, cfg):
        weekly = cfg["services"][0]["id"]
        freq_weekly = cfg["frequencies"][0]["id"]
        return [{"service_id": weekly, "qty": 4,
                  "frequency_id": freq_weekly, "add_on_ids": []}]

    def test_submit_recomputes_total_server_side(self, active_config,
                                                    _reset_rate_limit):
        _reset_rate_limit()
        cfg = requests.get(f"{API}/public/instaquote/{active_config['slug']}",
                             timeout=T).json()
        selections = self._wk_selection(cfg)
        r = requests.post(
            f"{API}/public/instaquote/{active_config['slug']}/submit",
            json={"contact": {"name": "Priya Sharma",
                                "email": "priya@example.com"},
                   "selections": selections},
            timeout=T,
        )
        assert r.status_code == 201, r.text
        # 4 × $125 × 1.0 = $500 = 50000 cents.
        assert r.json()["total_cents"] == 50000
        # Response is minimal — no tenant leak.
        for leaky in ("tenant_id", "breakdown", "contact",
                       "computed_breakdown_json"):
            assert leaky not in r.json()

    def test_submit_ignores_client_total_and_clamps_qty(self,
                                                            active_config,
                                                            _reset_rate_limit):
        _reset_rate_limit()
        cfg = requests.get(f"{API}/public/instaquote/{active_config['slug']}",
                             timeout=T).json()
        weekly_svc = cfg["services"][0]
        freq_biweekly = cfg["frequencies"][1]  # multiplier 0.55
        # qty=999 → clamped to service max_qty=12. Multiplier 0.55.
        # 12 * 12500 * 0.55 = 82500 cents.
        r = requests.post(
            f"{API}/public/instaquote/{active_config['slug']}/submit",
            json={"contact": {"email": "clamp@example.com"},
                   "selections": [{"service_id": weekly_svc["id"],
                                    "qty": 999,
                                    "frequency_id": freq_biweekly["id"]}]},
            timeout=T,
        )
        assert r.status_code == 201
        assert r.json()["total_cents"] == 82500

    def test_honeypot_swallows_silently(self, active_config,
                                           _reset_rate_limit):
        _reset_rate_limit()
        r = requests.post(
            f"{API}/public/instaquote/{active_config['slug']}/submit",
            json={"contact": {"email": "spam@example.com"},
                   "selections": [], "_hp": "gotcha"},
            timeout=T,
        )
        assert r.status_code == 201
        body = r.json()
        assert body.get("spam_swallowed") is True

    def test_rate_limit_kicks_in(self, active_config, _reset_rate_limit,
                                    admin_tok):
        _reset_rate_limit()
        cfg = requests.get(f"{API}/public/instaquote/{active_config['slug']}",
                             timeout=T).json()
        payload = {"contact": {"email": "rl@example.com"},
                    "selections": self._wk_selection(cfg)}
        # 3 allowed, 4th blocked.
        seen_429 = False
        for i in range(5):
            r = requests.post(
                f"{API}/public/instaquote/{active_config['slug']}/submit",
                json=payload, timeout=T,
            )
            if r.status_code == 429:
                seen_429 = True
                break
        assert seen_429, "expected 429 within 5 submits"

    def test_inactive_slug_404(self, config, _reset_rate_limit):
        r = requests.post(
            f"{API}/public/instaquote/{config['slug']}/submit",
            json={"contact": {"email": "x@example.com"}, "selections": []},
            timeout=T,
        )
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════
# Convert flow
# ═════════════════════════════════════════════════════════════════════

def _make_submission(active_config, contact_email: str = "converter@example.com",
                       reset_rl=None):
    if reset_rl:
        reset_rl()
    cfg = requests.get(f"{API}/public/instaquote/{active_config['slug']}",
                         timeout=T).json()
    weekly = cfg["services"][0]["id"]
    freq = cfg["frequencies"][0]["id"]
    addon = cfg["add_ons"][0]["id"]
    r = requests.post(
        f"{API}/public/instaquote/{active_config['slug']}/submit",
        json={"contact": {"name": "Jasper Vale", "email": contact_email,
                            "phone": "+15551234567",
                            "notes": "Please call after 4pm"},
               "selections": [{"service_id": weekly, "qty": 4,
                                "frequency_id": freq,
                                "add_on_ids": [addon]}]},
        timeout=T,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestConvert:
    def test_convert_creates_deal_estimate_and_subscriber(self, admin_tok,
                                                              active_config,
                                                              _reset_rate_limit):
        sid = _make_submission(active_config, f"conv-{uuid.uuid4().hex[:6]}@example.com", _reset_rate_limit)
        r = requests.post(f"{API}/instaquote/submissions/{sid}/convert",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deal_id"]
        assert body["estimate_id"]
        assert body["subscriber_id"]
        # Deal is in the default pipeline's first stage, source=instaquote.
        deal = next((d for d in requests.get(
                f"{API}/deals?source=instaquote&limit=200",
                headers=_h(admin_tok), timeout=T).json().get("deals") or []
                if d["id"] == body["deal_id"]), None)
        # Fallback: fetch by id via the list (no direct GET by id in tests).
        assert deal is not None
        assert deal["source"] == "instaquote"
        # Estimate exists as draft.
        est = requests.get(f"{API}/estimates/{body['estimate_id']}",
                             headers=_h(admin_tok), timeout=T).json()
        assert est["status"] == "draft"
        assert est.get("instaquote_submission_id") == sid
        # Subscriber source=instaquote.
        sub = requests.get(
            f"{API}/marketing/subscribers/{body['subscriber_id']}",
            headers=_h(admin_tok), timeout=T,
        )
        assert sub.status_code == 200
        assert sub.json()["source"] == "instaquote"
        # Cleanup — delete deal + estimate + subscriber.
        requests.delete(f"{API}/estimates/{body['estimate_id']}",
                         headers=_h(admin_tok), timeout=T)
        requests.delete(f"{API}/marketing/subscribers/{body['subscriber_id']}",
                         headers=_h(admin_tok), timeout=T)

    def test_second_convert_409(self, admin_tok, active_config,
                                   _reset_rate_limit):
        sid = _make_submission(active_config, f"dup-{uuid.uuid4().hex[:6]}@example.com", _reset_rate_limit)
        r1 = requests.post(f"{API}/instaquote/submissions/{sid}/convert",
                             headers=_h(admin_tok), timeout=T)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/instaquote/submissions/{sid}/convert",
                             headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 409

    def test_dismiss(self, admin_tok, active_config, _reset_rate_limit):
        sid = _make_submission(active_config, f"dis-{uuid.uuid4().hex[:6]}@example.com", _reset_rate_limit)
        r = requests.post(f"{API}/instaquote/submissions/{sid}/dismiss",
                            json={"note": "not a real lead"},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"

    def test_tech_forbidden_on_convert(self, tech_tok, active_config,
                                          _reset_rate_limit):
        sid = _make_submission(active_config, f"rbac-{uuid.uuid4().hex[:6]}@example.com", _reset_rate_limit)
        r = requests.post(f"{API}/instaquote/submissions/{sid}/convert",
                            headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


class TestSubmissionsList:
    def test_list_and_get(self, admin_tok, active_config, _reset_rate_limit):
        sid = _make_submission(active_config, f"list-{uuid.uuid4().hex[:6]}@example.com", _reset_rate_limit)
        rl = requests.get(f"{API}/instaquote/submissions?limit=50",
                            headers=_h(admin_tok), timeout=T).json()
        assert any(s["id"] == sid for s in rl["submissions"])
        rg = requests.get(f"{API}/instaquote/submissions/{sid}",
                            headers=_h(admin_tok), timeout=T)
        assert rg.status_code == 200
        assert rg.json()["tenant_id"]  # admin sees full doc


class TestAutomationEvent:
    def test_submit_fires_automation_event(self, admin_tok, active_config,
                                              _reset_rate_limit):
        # We validate by ensuring the endpoint returns 201 even when no
        # rule matches (event fires but has zero targets — must not
        # 500). Concrete rule wiring is exercised in comms tests.
        sid = _make_submission(active_config, f"auto-{uuid.uuid4().hex[:6]}@example.com", _reset_rate_limit)
        # Fetch the submission back to make sure it landed.
        r = requests.get(f"{API}/instaquote/submissions/{sid}",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200


class TestSubmissionsListExtras:
    def test_submissions_scoped_to_tenant(self, admin_tok, tenant_id):
        rl = requests.get(f"{API}/instaquote/submissions?limit=200",
                            headers=_h(admin_tok), timeout=T).json()
        for s in rl["submissions"]:
            assert s["tenant_id"] == tenant_id

    def test_status_filter(self, admin_tok, active_config, _reset_rate_limit):
        sid = _make_submission(active_config,
                                f"status-{uuid.uuid4().hex[:6]}@example.com",
                                _reset_rate_limit)
        requests.post(f"{API}/instaquote/submissions/{sid}/dismiss",
                        json={"note": "x"},
                        headers=_h(admin_tok), timeout=T)
        r = requests.get(f"{API}/instaquote/submissions?status=dismissed&limit=50",
                          headers=_h(admin_tok), timeout=T).json()
        assert all(s["status"] == "dismissed" for s in r["submissions"])
        assert any(s["id"] == sid for s in r["submissions"])


class TestDiscountRule:
    def test_discount_pct_applied_when_min_qty_reached(self, admin_tok,
                                                          _reset_rate_limit):
        _reset_rate_limit()
        # Build a config with a 10%-off rule when qty ≥ 4 of weekly svc.
        cfg_in = _sample_config(f"disc-{uuid.uuid4().hex[:6]}")
        r = requests.post(f"{API}/instaquote/configs", json=cfg_in,
                            headers=_h(admin_tok), timeout=T).json()
        cid = r["id"]
        try:
            svc_id = r["services"][0]["id"]
            requests.patch(f"{API}/instaquote/configs/{cid}",
                             json={"rules": [{"if": {"service_id": svc_id,
                                                        "min_qty": 4},
                                              "then": {"discount_pct": 10}}]},
                             headers=_h(admin_tok), timeout=T)
            requests.post(f"{API}/instaquote/configs/{cid}/activate",
                             headers=_h(admin_tok), timeout=T)
            cfg = requests.get(f"{API}/public/instaquote/{r['slug']}",
                                 timeout=T).json()
            freq_id = cfg["frequencies"][0]["id"]
            # 4 × 12500 = 50000; then × 0.90 = 45000.
            sub = requests.post(
                f"{API}/public/instaquote/{r['slug']}/submit",
                json={"contact": {"email": "disc@example.com"},
                       "selections": [{"service_id": svc_id, "qty": 4,
                                        "frequency_id": freq_id}]},
                timeout=T,
            )
            assert sub.status_code == 201
            assert sub.json()["total_cents"] == 45000
        finally:
            requests.delete(f"{API}/instaquote/configs/{cid}",
                             headers=_h(admin_tok), timeout=T)


class TestErrorPaths:
    def test_patch_unknown_404(self, admin_tok):
        r = requests.patch(f"{API}/instaquote/configs/does-not-exist",
                             json={"headline": "x"},
                             headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404

    def test_delete_unknown_404(self, admin_tok):
        r = requests.delete(f"{API}/instaquote/configs/does-not-exist",
                              headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404

    def test_convert_unknown_404(self, admin_tok):
        r = requests.post(f"{API}/instaquote/submissions/does-not-exist/convert",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404


class TestOpenApi:
    def test_openapi_has_q4_paths(self):
        r = requests.get(f"{API}/openapi.json", timeout=T)
        paths = r.json().get("paths", {})
        for p in [
            "/api/instaquote/configs",
            "/api/instaquote/configs/{cid}",
            "/api/instaquote/configs/{cid}/activate",
            "/api/instaquote/submissions",
            "/api/instaquote/submissions/{sid}",
            "/api/instaquote/submissions/{sid}/convert",
            "/api/instaquote/submissions/{sid}/dismiss",
            "/api/public/instaquote/{slug}",
            "/api/public/instaquote/{slug}/submit",
        ]:
            assert p in paths, f"missing OpenAPI path: {p}"

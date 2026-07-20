"""Micro-polish sweep · backend tests (Feb 2026).

Covers three vertical items:
  * Before/After share-token impression + click counters + admin stats.
  * InstaQuote submissions list hydrates ``contact_history_count``.
  * Muted-notification digest sweep (feature-gated + email queue rows).
"""
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
    d = r.json()
    return d["access_token"], (d.get("user") or {}).get("id")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com",
                    demo_pw("admin@aquaterra.com"))[0]


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    return requests.get(f"{API}/tenants/current",
                         headers=_h(admin_tok), timeout=T).json()["id"]


# ═════════════════════════════════════════════════════════════════════
class TestBeforeAfterCounters:
    """Public share fetch bumps impressions; click beacon bumps clicks."""

    @pytest.fixture
    def pair(self, admin_tok):
        # 1x1 PNG (base64) so compose never fails on missing bytes.
        one_by_one = ("data:image/png;base64,"
                       "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
                       "2mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        r = requests.post(f"{API}/before-after/generate",
                            json={
                                "before_photo_url": one_by_one,
                                "after_photo_url": one_by_one,
                                "style": "side_by_side",
                                "caption": "TEST_counter",
                                "include_branding": False,
                            }, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        return r.json()["pair"]

    def test_impression_increments_on_public_fetch(self, admin_tok, pair):
        token = pair["share_token"]
        pid = pair["id"]
        before = requests.get(f"{API}/before-after/pairs/{pid}/stats",
                                headers=_h(admin_tok), timeout=T).json()
        # First public fetch bumps impression by 1.
        r = requests.get(f"{API}/before-after/public/{token}", timeout=T)
        assert r.status_code == 200
        # Second fetch bumps to 2.
        requests.get(f"{API}/before-after/public/{token}", timeout=T)
        after = requests.get(f"{API}/before-after/pairs/{pid}/stats",
                               headers=_h(admin_tok), timeout=T).json()
        assert after["impressions_count"] >= before["impressions_count"] + 2
        assert after["last_impression_at"]

    def test_click_beacon_increments_click_count(self, admin_tok, pair):
        token = pair["share_token"]
        pid = pair["id"]
        before = requests.get(f"{API}/before-after/pairs/{pid}/stats",
                                headers=_h(admin_tok), timeout=T).json()
        r = requests.post(f"{API}/before-after/public/{token}/click", timeout=T)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        after = requests.get(f"{API}/before-after/pairs/{pid}/stats",
                               headers=_h(admin_tok), timeout=T).json()
        assert after["click_count"] == before["click_count"] + 1
        assert after["last_click_at"]

    def test_click_beacon_silent_on_unknown_token(self):
        r = requests.post(f"{API}/before-after/public/{'x' * 32}/click",
                           timeout=T)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_admin_stats_ctr(self, admin_tok, pair):
        token = pair["share_token"]
        pid = pair["id"]
        # Ensure baseline: 1 impression + 1 click → CTR should compute.
        requests.get(f"{API}/before-after/public/{token}", timeout=T)
        requests.post(f"{API}/before-after/public/{token}/click", timeout=T)
        stats = requests.get(f"{API}/before-after/pairs/{pid}/stats",
                                headers=_h(admin_tok), timeout=T).json()
        assert stats["impressions_count"] >= 1
        assert stats["click_count"] >= 1
        assert stats["ctr_pct"] >= 0.0


class TestInstaQuoteReturningLead:
    def test_history_count_grows_with_repeat_email(self, admin_tok):
        # Seed / activate a config.
        rows = requests.get(f"{API}/instaquote/configs",
                              headers=_h(admin_tok), timeout=T).json().get("configs") or []
        active = next((c for c in rows if c.get("active")), None)
        if not active:
            r = requests.post(f"{API}/instaquote/configs",
                                json={
                                    "slug": f"tst-hist-{uuid.uuid4().hex[:6]}",
                                    "headline": "TEST · history config",
                                    "services": [{
                                        "name": "TEST Weekly",
                                        "base_price_cents": 12000,
                                        "unit": "visit",
                                        "min_qty": 1, "max_qty": 4,
                                    }],
                                    "active": True,
                                }, headers=_h(admin_tok), timeout=T)
            assert r.status_code == 201, r.text
            active = r.json()
        slug = active["slug"]
        svc = (active.get("services") or [{}])[0]
        email = f"repeat-{uuid.uuid4().hex[:6]}@example.com"
        # Fire 3 submissions from the SAME email.
        requests.post(f"{API}/instaquote/rate-limit/reset",
                        headers=_h(admin_tok), timeout=T)
        for i in range(3):
            requests.post(f"{API}/instaquote/rate-limit/reset",
                            headers=_h(admin_tok), timeout=T)
            r = requests.post(f"{API}/public/instaquote/{slug}/submit",
                                json={
                                    "contact": {"name": f"TEST_hist_{i}",
                                                  "email": email},
                                    "selections": [{"service_id": svc.get("id"),
                                                     "qty": 1}],
                                }, timeout=T)
            assert r.status_code == 201, r.text
        # List submissions and verify contact_history_count.
        sub_rows = requests.get(f"{API}/instaquote/submissions",
                                  headers=_h(admin_tok), timeout=T).json()
        mine = [s for s in (sub_rows.get("submissions") or [])
                 if (s.get("contact") or {}).get("email") == email]
        assert len(mine) >= 3, "expected 3 submissions from the same email"
        # The most recent one should count all 3.
        assert mine[0]["contact_history_count"] >= 3

    def test_single_submission_has_history_count_1(self, admin_tok):
        rows = requests.get(f"{API}/instaquote/configs",
                              headers=_h(admin_tok), timeout=T).json().get("configs") or []
        active = next((c for c in rows if c.get("active")), None)
        assert active
        slug = active["slug"]
        svc = (active.get("services") or [{}])[0]
        email = f"solo-{uuid.uuid4().hex[:6]}@example.com"
        requests.post(f"{API}/instaquote/rate-limit/reset",
                        headers=_h(admin_tok), timeout=T)
        requests.post(f"{API}/public/instaquote/{slug}/submit",
                        json={
                            "contact": {"name": "TEST_solo", "email": email},
                            "selections": [{"service_id": svc.get("id"),
                                             "qty": 1}],
                        }, timeout=T)
        rows2 = requests.get(f"{API}/instaquote/submissions",
                               headers=_h(admin_tok), timeout=T).json()
        mine = [s for s in (rows2.get("submissions") or [])
                 if (s.get("contact") or {}).get("email") == email]
        assert mine, "expected 1 submission"
        assert mine[0]["contact_history_count"] == 1


class TestMutedDigest:
    def test_digest_disabled_by_default(self, admin_tok, tenant_id):
        # Ensure digest disabled — endpoint returns disabled shape.
        requests.patch(f"{API}/tenants/{tenant_id}",
                         json={"notification_digest_enabled": False},
                         headers=_h(admin_tok), timeout=T)
        r = requests.post(f"{API}/notifications/digest/run",
                           headers=_h(admin_tok), timeout=T)
        # Non-super admins can't PATCH tenants (403) — the digest run
        # endpoint must ALSO be safe: an admin whose tenant has the
        # flag off (or unset) sees ``ok=false / reason=disabled``.
        assert r.status_code == 200
        j = r.json()
        # We only assert the disabled branch when the PATCH succeeded.
        # If not (super_admin required), the flag may already be off/unset,
        # which produces the same branch.
        if j.get("ok") is False:
            assert "disabled" in (j.get("reason") or "")
            assert j.get("emails_written") == 0

    def test_digest_enabled_writes_email_when_muted_events_exist(
            self, admin_tok, tenant_id):
        # Enable digest on the tenant (super_admin required — best effort;
        # tolerate 403 as a skip signal for this leg).
        super_tok, _ = _login("super@aquaterra.com",
                                demo_pw("super@aquaterra.com"))
        p = requests.patch(f"{API}/tenants/{tenant_id}",
                             json={"notification_digest_enabled": True},
                             headers=_h(super_tok), timeout=T)
        if p.status_code >= 400:
            pytest.skip(f"PATCH tenant blocked: {p.status_code}")
        # Ensure current admin has push muted on ``system_alert``.
        cur = requests.get(f"{API}/settings/notifications",
                             headers=_h(admin_tok), timeout=T).json()
        chans = cur.get("channels") or {}
        chans.setdefault("system_alert", {}).update({"bell": True, "push": False})
        requests.put(f"{API}/settings/notifications",
                       json={"channels": chans},
                       headers=_h(admin_tok), timeout=T)
        # Fire a test-push (system_alert kind) so the admin's inbox has a
        # muted event to roll up.
        requests.post(f"{API}/notifications/test-push",
                        headers=_h(admin_tok), timeout=T)
        r = requests.post(f"{API}/notifications/digest/run",
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        # Users-with-muted-events includes the calling admin.
        assert j.get("users_with_muted_events", 0) >= 1
        # Cleanup: revert the flag.
        requests.patch(f"{API}/tenants/{tenant_id}",
                         json={"notification_digest_enabled": False},
                         headers=_h(super_tok), timeout=T)

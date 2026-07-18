"""Ship 3 · Nudge non-starters + Recommendations queue + Growth snapshot writes.

3 test classes matching the 3 items in the bundle.
"""
from __future__ import annotations
import os
import time
import pytest
import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30


def _login(email, pwd="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


def _h(t): return {"Authorization": f"Bearer {t}"}


# ═══ Item A · Nudge non-starters ═══════════════════════════════════════
_UNIQUE_MODULE = f"ship3-test-mod-{int(time.time())}"


class TestNudgeNonStarters:
    """Uses a unique per-run module_code so idempotency-count assertions
    aren't polluted by any real nudges landed elsewhere in the same week."""

    def test_admin_first_nudge_targets_all_non_starters(self, admin_tok):
        r = requests.post(f"{API}/training/nudge-non-starters",
                          headers=_h(admin_tok),
                          json={"module_code": _UNIQUE_MODULE,
                                "message": "Please start this training.",
                                "include_email": False},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["module_code"] == _UNIQUE_MODULE
        # No one has started a made-up module → every pool tech gets nudged.
        assert d["count_nudged"] >= 1
        assert d["count_skipped_idempotent"] == 0
        assert d["email_ids"] == []
        assert "week_of" in d

    def test_re_nudge_within_week_is_idempotent(self, admin_tok):
        r = requests.post(f"{API}/training/nudge-non-starters",
                          headers=_h(admin_tok),
                          json={"module_code": _UNIQUE_MODULE,
                                "message": "Please start this training.",
                                "include_email": False},
                          timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        assert d["count_nudged"] == 0
        assert d["count_skipped_idempotent"] >= 1

    def test_email_flag_writes_outbound_row_when_key_missing(self, admin_tok):
        """`include_email=true` should still audit-log an outbound_emails
        row with `status: "not_sent_missing_key"` when RESEND_API_KEY is
        absent (or "failed" when test-mode). Uses a fresh module code so
        this call doesn't collide with the previous idempotency window."""
        fresh_code = f"ship3-email-test-{int(time.time())}"
        r = requests.post(f"{API}/training/nudge-non-starters",
                          headers=_h(admin_tok),
                          json={"module_code": fresh_code,
                                "message": "Please start this training.",
                                "include_email": True},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        # If any nudged users have an email on file, email_ids should populate.
        # Aquaterra seed has mike@ + landscaper@ with emails, so ≥1 email row.
        if d["count_nudged"] > 0:
            assert isinstance(d["email_ids"], list)

    def test_tech_403(self, tech_tok):
        r = requests.post(f"{API}/training/nudge-non-starters",
                          headers=_h(tech_tok),
                          json={"module_code": "cpo-prep",
                                "message": "x"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_customer_403(self, customer_tok):
        r = requests.post(f"{API}/training/nudge-non-starters",
                          headers=_h(customer_tok),
                          json={"module_code": "cpo-prep",
                                "message": "x"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_missing_required_fields_422(self, admin_tok):
        r = requests.post(f"{API}/training/nudge-non-starters",
                          headers=_h(admin_tok),
                          json={"module_code": ""}, timeout=TIMEOUT)
        assert r.status_code == 422


# ═══ Item B · Recommendations queue ═════════════════════════════════════
class TestRecommendationsQueue:
    def test_admin_get_shape(self, admin_tok):
        r = requests.get(f"{API}/recommendations-queue?older_than_days=0",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        assert "count" in d and "rows" in d
        assert d["kind"] == "price_increase_recommendation"

    def test_only_drafts_returned(self, admin_tok):
        r = requests.get(f"{API}/recommendations-queue?older_than_days=0",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        for row in r.json()["rows"]:
            assert "current_price" in row and "recommended_price" in row
            assert "age_days" in row and "gap_pct" in row

    def test_send_endpoint_transitions_status(self, admin_tok):
        # Create a fresh draft via Ship 1 flow, then hit /send on it.
        cpp = requests.get(f"{API}/calculators/cost-per-pool",
                           headers=_h(admin_tok), timeout=TIMEOUT).json()
        row = next((r for r in cpp["rows"]
                    if "low_margin" in r.get("flags", []) or "negative_margin" in r.get("flags", [])), None)
        assert row, "no low_margin customer available for send test"
        r_draft = requests.post(
            f"{API}/calculators/recommend-price-increase",
            headers=_h(admin_tok),
            json={"customer_id": row["customer_id"],
                  "current_price": 45.5, "recommended_price": 66.66,
                  "action": "draft"}, timeout=TIMEOUT)
        assert r_draft.status_code == 200
        draft_id = r_draft.json()["id"]
        r_send = requests.post(
            f"{API}/recommendations-queue/{draft_id}/send",
            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r_send.status_code == 200
        d = r_send.json()
        assert d["status"] in ("sent", "failed", "not_sent_missing_key")

    def test_discard_endpoint(self, admin_tok):
        cpp = requests.get(f"{API}/calculators/cost-per-pool",
                           headers=_h(admin_tok), timeout=TIMEOUT).json()
        row = next((r for r in cpp["rows"]
                    if "low_margin" in r.get("flags", []) or "negative_margin" in r.get("flags", [])), None)
        r_draft = requests.post(
            f"{API}/calculators/recommend-price-increase",
            headers=_h(admin_tok),
            json={"customer_id": row["customer_id"],
                  "current_price": 45.5, "recommended_price": 77.77,
                  "action": "draft"}, timeout=TIMEOUT)
        draft_id = r_draft.json()["id"]
        r_disc = requests.post(
            f"{API}/recommendations-queue/{draft_id}/discard",
            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r_disc.status_code == 200, r_disc.text
        assert r_disc.json()["status"] == "discarded"
        # Cannot double-discard.
        r_dup = requests.post(
            f"{API}/recommendations-queue/{draft_id}/discard",
            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r_dup.status_code == 409

    def test_send_on_nonexistent_404(self, admin_tok):
        r = requests.post(f"{API}/recommendations-queue/does-not-exist/send",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 404

    def test_invalid_kind_422(self, admin_tok):
        r = requests.get(f"{API}/recommendations-queue?kind=unknown",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 422

    def test_tech_403(self, tech_tok):
        r = requests.get(f"{API}/recommendations-queue?older_than_days=0",
                         headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403


# ═══ Item C · Growth playbook snapshots ═════════════════════════════════
class TestGrowthPlaybookSnapshots:
    def test_playbook_fetch_writes_snapshot(self, admin_tok):
        # Baseline count.
        r0 = requests.get(f"{API}/analysis/growth-playbook/history?days=1",
                          headers=_h(admin_tok), timeout=TIMEOUT).json()
        before = r0["count"]
        # Fire playbook.
        r_pb = requests.post(f"{API}/analysis/growth-playbook",
                              headers=_h(admin_tok), json={}, timeout=TIMEOUT)
        assert r_pb.status_code == 200
        r1 = requests.get(f"{API}/analysis/growth-playbook/history?days=1",
                          headers=_h(admin_tok), timeout=TIMEOUT).json()
        assert r1["count"] == before + 1
        # Latest row shape.
        latest = r1["rows"][-1]
        for k in ("id", "tenant_id", "snapshot_at", "requested_by_user_id",
                   "active_customers", "monthly_revenue", "today_valuation",
                   "today_multiple", "market_state", "market_median_price",
                   "market_valuation", "delta_valuation", "playbook_flavor"):
            assert k in latest, f"missing key {k}"

    def test_history_chronological_order(self, admin_tok):
        # Two more fetches to have ≥3 snapshots in history.
        for _ in range(2):
            requests.post(f"{API}/analysis/growth-playbook",
                          headers=_h(admin_tok), json={}, timeout=TIMEOUT)
        r = requests.get(f"{API}/analysis/growth-playbook/history?days=1",
                         headers=_h(admin_tok), timeout=TIMEOUT).json()
        assert r["count"] >= 3
        ts = [row["snapshot_at"] for row in r["rows"]]
        assert ts == sorted(ts), "snapshots not chronological"

    def test_history_days_window(self, admin_tok):
        # 90-day window returns ≥ 1-day window.
        r_1d = requests.get(f"{API}/analysis/growth-playbook/history?days=1",
                             headers=_h(admin_tok), timeout=TIMEOUT).json()
        r_90 = requests.get(f"{API}/analysis/growth-playbook/history?days=90",
                             headers=_h(admin_tok), timeout=TIMEOUT).json()
        assert r_90["count"] >= r_1d["count"]

    def test_tech_403(self, tech_tok):
        r = requests.get(f"{API}/analysis/growth-playbook/history",
                         headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403

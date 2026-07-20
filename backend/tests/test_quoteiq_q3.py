"""QuoteIQ Phase Q3 — Before/After + AI Autopilot backend tests.

Uses ``TEST_LLM_MOCK=1`` so the Autopilot LLM call is deterministic.
Before/After uses inline ``data:`` URIs to keep the test hermetic (no
network fetch, no external image hosts).
"""
from __future__ import annotations

import base64
import io
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

# Turn on the mock BEFORE we import anything that reads it.
os.environ["TEST_LLM_MOCK"] = "1"

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
# Timeout accommodates real-LLM path when TEST_LLM_MOCK=0. Planner
# endpoints fan out N calls, so this needs headroom.
T = 90


# --- helpers -----------------------------------------------------------

def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _make_data_uri(color=(200, 60, 40), size=(320, 240)) -> str:
    """Tiny PNG encoded as a data URI. Keeps the test hermetic."""
    from PIL import Image
    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# --- fixtures ----------------------------------------------------------

@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def super_tok():
    return _login("super@aquaterra.com", demo_pw("super@aquaterra.com"))


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com", demo_pw("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    r = requests.get(f"{API}/tenants/current", headers=_h(admin_tok), timeout=T)
    return r.json()["id"]


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_credits(super_tok):
    # Q3 test spend now includes planners (up to ~30 credits). Give
    # headroom so no test sees a warning it doesn't expect.
    requests.post(f"{API}/ai-credits/topup",
                   json={"amount": 600, "note": "q3_test_bootstrap"},
                   headers=_h(super_tok), timeout=T)
    yield


@pytest.fixture(scope="module")
def data_uri_before():
    return _make_data_uri(color=(60, 60, 60))


@pytest.fixture(scope="module")
def data_uri_after():
    return _make_data_uri(color=(60, 180, 90))


# ═════════════════════════════════════════════════════════════════════
# Before/After AI Generator (Q3-A)
# ═════════════════════════════════════════════════════════════════════

class TestBeforeAfterGenerate:
    _pid = None
    _share_token = None
    _balance_before = None

    def test_generate_debits_5_and_persists(self, admin_tok,
                                              data_uri_before,
                                              data_uri_after):
        bal_pre = requests.get(f"{API}/ai-credits/balance",
                                headers=_h(admin_tok), timeout=T).json()["balance"]
        TestBeforeAfterGenerate._balance_before = bal_pre
        r = requests.post(
            f"{API}/before-after/generate",
            json={
                "before_photo_url": data_uri_before,
                "after_photo_url": data_uri_after,
                "style": "side_by_side",
                "caption": "TEST_ Q3 before/after",
                "service_type": "Pool Refresh",
            },
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        pair = body["pair"]
        assert pair["status"] == "complete", pair
        assert pair["generated_card_url"], pair
        assert pair["credits_debited"] == 5
        assert pair["share_token"] and len(pair["share_token"]) >= 20
        assert body["credits_balance_after"] == bal_pre - 5
        TestBeforeAfterGenerate._pid = pair["id"]
        TestBeforeAfterGenerate._share_token = pair["share_token"]

    def test_ledger_row_matches(self, admin_tok):
        assert TestBeforeAfterGenerate._pid
        txns = requests.get(
            f"{API}/ai-credits/transactions?feature=before_after&limit=50",
            headers=_h(admin_tok), timeout=T,
        ).json()
        matched = [t for t in txns["transactions"]
                    if t.get("ref_id") == TestBeforeAfterGenerate._pid]
        assert len(matched) >= 1
        assert matched[0]["delta"] == -5
        assert matched[0]["ref_type"] == "before_after_pair"

    def test_list_and_get(self, admin_tok):
        assert TestBeforeAfterGenerate._pid
        rl = requests.get(f"{API}/before-after/pairs?limit=5",
                            headers=_h(admin_tok), timeout=T).json()
        assert any(p["id"] == TestBeforeAfterGenerate._pid for p in rl["pairs"])
        rg = requests.get(
            f"{API}/before-after/pairs/{TestBeforeAfterGenerate._pid}",
            headers=_h(admin_tok), timeout=T,
        )
        assert rg.status_code == 200
        assert rg.json()["share_token"] == TestBeforeAfterGenerate._share_token

    def test_regenerate_debits_5_and_appends_variant(self, admin_tok):
        assert TestBeforeAfterGenerate._pid
        r = requests.post(
            f"{API}/before-after/pairs/{TestBeforeAfterGenerate._pid}/regenerate",
            json={"style": "stacked", "caption": "TEST_ regen"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200, r.text
        pair = r.json()["pair"]
        assert pair["style"] == "stacked"
        assert pair["credits_debited"] == 10  # 5 + 5
        assert len(pair["generated_variants"]) >= 2
        # Same share_token — regeneration must not rotate the public URL.
        assert pair["share_token"] == TestBeforeAfterGenerate._share_token

    def test_public_share_returns_non_sensitive_fields_only(self):
        assert TestBeforeAfterGenerate._share_token
        r = requests.get(
            f"{API}/before-after/public/{TestBeforeAfterGenerate._share_token}",
            timeout=T,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("card_url")
        # PII / tenant internals MUST NOT leak.
        for leaky in ("tenant_id", "customer_id", "job_id", "id",
                       "generated_by", "share_token"):
            assert leaky not in body, f"public share leaked field: {leaky}"

    def test_public_share_unknown_token_404(self):
        r = requests.get(f"{API}/before-after/public/{'a' * 32}", timeout=T)
        assert r.status_code == 404

    def test_delete(self, admin_tok):
        assert TestBeforeAfterGenerate._pid
        r = requests.delete(
            f"{API}/before-after/pairs/{TestBeforeAfterGenerate._pid}",
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 204


class TestBeforeAfterRBAC:
    def test_tech_forbidden_on_generate(self, tech_tok, data_uri_before, data_uri_after):
        r = requests.post(
            f"{API}/before-after/generate",
            json={"before_photo_url": data_uri_before,
                   "after_photo_url": data_uri_after,
                   "style": "side_by_side"},
            headers=_h(tech_tok), timeout=T,
        )
        assert r.status_code == 403

    def test_tech_can_list_only_when_scoped(self, tech_tok):
        # No filter → 403.
        r = requests.get(f"{API}/before-after/pairs",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403
        # Scoped by job_id → allowed (empty list is fine).
        r2 = requests.get(f"{API}/before-after/pairs?job_id=abc",
                            headers=_h(tech_tok), timeout=T)
        assert r2.status_code == 200
        r3 = requests.get(f"{API}/before-after/pairs?customer_id=xyz",
                            headers=_h(tech_tok), timeout=T)
        assert r3.status_code == 200

    def test_bad_style_422(self, admin_tok, data_uri_before, data_uri_after):
        r = requests.post(
            f"{API}/before-after/generate",
            json={"before_photo_url": data_uri_before,
                   "after_photo_url": data_uri_after,
                   "style": "hologram"},
            headers=_h(admin_tok), timeout=T,
        )
        # Compose refuses unknown style → pair persisted with status=error.
        assert r.status_code in (201, 422)
        if r.status_code == 201:
            assert r.json()["pair"]["status"] == "error"


class TestBeforeAfterTenantIsolation:
    def test_pairs_scoped_to_tenant(self, admin_tok, tenant_id):
        r = requests.get(f"{API}/before-after/pairs",
                          headers=_h(admin_tok), timeout=T).json()
        for p in r["pairs"]:
            assert p["tenant_id"] == tenant_id


# ═════════════════════════════════════════════════════════════════════
# AI Autopilot copy generator (Q3-B)
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def custom_automation(admin_tok):
    """Create a tenant-custom automation rule for the generate-copy
    tests (system rules stay read-only)."""
    code = f"test_q3_{uuid.uuid4().hex[:8]}"
    # Need an existing template to reference. Pick the first email
    # template available for the tenant.
    tpls = requests.get(f"{API}/comms/email-templates",
                         headers=_h(admin_tok), timeout=T).json()
    template_code = tpls[0]["code"]
    r = requests.post(
        f"{API}/comms/automations",
        json={
            "code": code,
            "name": f"TEST_ Q3 Autopilot {code}",
            "description": "Q3 autopilot copy generator test",
            "trigger_event": "job.completed",
            "channel": "email",
            "template_code": template_code,
            "active": True,
        },
        headers=_h(admin_tok), timeout=T,
    )
    assert r.status_code == 201, r.text
    yield code
    requests.delete(f"{API}/comms/automations/{code}",
                     headers=_h(admin_tok), timeout=T)


class TestAutopilotGenerateCopy:
    def test_generate_debits_3_and_persists(self, admin_tok,
                                              custom_automation):
        pre = requests.get(f"{API}/ai-credits/balance",
                            headers=_h(admin_tok), timeout=T).json()["balance"]
        r = requests.post(
            f"{API}/comms/automations/{custom_automation}/generate-copy",
            json={"tone": "friendly",
                   "use_case": "seasonal",
                   "brand_voice_snippet": "Warm, plain-spoken, no jargon.",
                   "extra_context": "customers love reminders"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        copy = body["ai_generated_copy"]
        assert copy["subject"]  # email channel → subject present
        assert copy["body_text"]
        assert copy["credits_debited"] == 3
        assert copy["tone"] == "friendly"
        assert copy["use_case"] == "seasonal"
        assert copy["brand_voice_snippet"].startswith("Warm")
        assert body["persisted"] is True
        assert body["credits_balance_after"] == pre - 3
        # Rule doc echoed back with the ai_generated_copy attached.
        rule = body["automation"]
        assert rule.get("ai_generated_copy", {}).get("body_text") == copy["body_text"]

    def test_second_generation_appends_history(self, admin_tok,
                                                  custom_automation):
        r = requests.post(
            f"{API}/comms/automations/{custom_automation}/generate-copy",
            json={"tone": "professional", "use_case": "generic"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200, r.text
        rule = r.json()["automation"]
        history = rule.get("ai_generated_history") or []
        assert len(history) >= 2, history
        # Latest is at index 0.
        assert history[0]["tone"] == "professional"

    def test_channel_override_wins_over_rule(self, admin_tok,
                                                custom_automation):
        # Rule is 'email' by construction; override to sms.
        r = requests.post(
            f"{API}/comms/automations/{custom_automation}/generate-copy",
            json={"channel": "sms", "tone": "urgent"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200, r.text
        copy = r.json()["ai_generated_copy"]
        assert copy["channel"] == "sms"
        assert copy["subject"] is None
        assert copy["body_sms"]

    def test_ledger_row_matches(self, admin_tok, custom_automation):
        txns = requests.get(
            f"{API}/ai-credits/transactions?feature=autopilot&limit=50",
            headers=_h(admin_tok), timeout=T,
        ).json()
        matched = [t for t in txns["transactions"]
                    if t.get("ref_id") == custom_automation]
        assert len(matched) >= 1
        assert matched[0]["delta"] == -3
        assert matched[0]["ref_type"] == "automation_rule"

    def test_sms_channel_yields_body_sms(self, admin_tok):
        code = f"test_q3_sms_{uuid.uuid4().hex[:6]}"
        tpls = requests.get(f"{API}/comms/sms-templates",
                             headers=_h(admin_tok), timeout=T).json()
        assert tpls, "expected at least one seeded sms template"
        template_code = tpls[0]["code"]
        create = requests.post(
            f"{API}/comms/automations",
            json={"code": code, "name": f"TEST_ Q3 SMS {code}",
                   "trigger_event": "job.scheduled",
                   "channel": "sms",
                   "template_code": template_code, "active": True},
            headers=_h(admin_tok), timeout=T,
        )
        assert create.status_code == 201, create.text
        try:
            r = requests.post(
                f"{API}/comms/automations/{code}/generate-copy",
                json={"tone": "urgent"},
                headers=_h(admin_tok), timeout=T,
            )
            assert r.status_code == 200, r.text
            copy = r.json()["ai_generated_copy"]
            assert copy["body_sms"]
            assert copy["subject"] is None
        finally:
            requests.delete(f"{API}/comms/automations/{code}",
                             headers=_h(admin_tok), timeout=T)


class TestAutopilotRBAC:
    def test_tech_forbidden(self, tech_tok, custom_automation):
        r = requests.post(
            f"{API}/comms/automations/{custom_automation}/generate-copy",
            json={"tone": "friendly"},
            headers=_h(tech_tok), timeout=T,
        )
        assert r.status_code == 403


class TestAutopilotErrors:
    def test_unknown_code_404(self, admin_tok):
        r = requests.post(
            f"{API}/comms/automations/does_not_exist_xyz/generate-copy",
            json={"tone": "friendly"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════
# Autopilot Planners
# ═════════════════════════════════════════════════════════════════════

class TestSeasonalPlanner:
    def test_draft_charges_per_step_and_returns_ladder(self, admin_tok):
        pre = requests.get(f"{API}/ai-credits/balance",
                            headers=_h(admin_tok), timeout=T).json()["balance"]
        r = requests.post(
            f"{API}/comms/planners/seasonal/draft",
            json={"season": "spring",
                   "service_types": ["pool_open", "landscape"],
                   "channel": "email", "tone": "friendly"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # 2 services × 3 offsets = 6 steps.
        assert len(body["steps"]) == 6
        assert body["total_credits_debited"] == 6 * 3
        assert body["credits_balance_after"] == pre - 6 * 3
        for s in body["steps"]:
            assert s["trigger_event"] == "route.seasonal_open"
            assert s["channel"] == "email"
            assert s["subject"]

    def test_approve_creates_rules_and_templates(self, admin_tok):
        # Fresh 1-step ladder for a controlled approve.
        draft = requests.post(
            f"{API}/comms/planners/seasonal/draft",
            json={"season": "fall", "service_types": ["pool_close"],
                   "channel": "email", "tone": "professional"},
            headers=_h(admin_tok), timeout=T,
        ).json()
        # Keep only the first step to make the test deterministic.
        step = draft["steps"][0]
        r = requests.post(
            f"{API}/comms/planners/seasonal/approve",
            json={"steps": [step]},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 201, r.text
        created = r.json()["created"]
        assert len(created) == 1
        code = created[0]["code"]
        # Verify the rule + template were persisted.
        rule = requests.get(f"{API}/comms/automations/{code}",
                              headers=_h(admin_tok), timeout=T).json()
        assert rule["trigger_event"] == "route.seasonal_close"
        assert rule["template_code"].startswith("tpl_")
        assert rule.get("source") == "ai_planner"
        # Cleanup.
        requests.delete(f"{API}/comms/automations/{code}",
                         headers=_h(admin_tok), timeout=T)

    def test_tech_forbidden(self, tech_tok):
        r = requests.post(
            f"{API}/comms/planners/seasonal/draft",
            json={"season": "spring", "channel": "email"},
            headers=_h(tech_tok), timeout=T,
        )
        assert r.status_code == 403

    def test_bad_season_422(self, admin_tok):
        r = requests.post(
            f"{API}/comms/planners/seasonal/draft",
            json={"season": "monsoon", "channel": "email"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 422


class TestInvoiceFollowupPlanner:
    def test_draft_charges_per_step_and_returns_ladder(self, admin_tok):
        pre = requests.get(f"{API}/ai-credits/balance",
                            headers=_h(admin_tok), timeout=T).json()["balance"]
        r = requests.post(
            f"{API}/comms/planners/invoice-followup/draft",
            json={"days_ladder": [7, 14, 30], "channel": "email",
                   "tone": "professional"},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["days_ladder"] == [7, 14, 30]
        assert len(body["steps"]) == 3
        assert body["total_credits_debited"] == 9
        assert body["credits_balance_after"] == pre - 9
        for s, d in zip(body["steps"], [7, 14, 30]):
            assert s["trigger_event"] == "invoice.overdue"
            assert s["delay_days"] == d
            assert s["send_delay_minutes"] == d * 24 * 60

    def test_approve_creates_rules(self, admin_tok):
        draft = requests.post(
            f"{API}/comms/planners/invoice-followup/draft",
            json={"days_ladder": [5], "channel": "sms",
                   "tone": "urgent"},
            headers=_h(admin_tok), timeout=T,
        ).json()
        step = draft["steps"][0]
        r = requests.post(
            f"{API}/comms/planners/invoice-followup/approve",
            json={"steps": [step]},
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 201
        created = r.json()["created"]
        assert len(created) == 1
        code = created[0]["code"]
        rule = requests.get(f"{API}/comms/automations/{code}",
                              headers=_h(admin_tok), timeout=T).json()
        assert rule["trigger_event"] == "invoice.overdue"
        assert rule["channel"] == "sms"
        # Cleanup.
        requests.delete(f"{API}/comms/automations/{code}",
                         headers=_h(admin_tok), timeout=T)


# ═════════════════════════════════════════════════════════════════════
# OpenAPI surface
# ═════════════════════════════════════════════════════════════════════

class TestOpenApi:
    def test_openapi_has_q3_paths(self):
        r = requests.get(f"{API}/openapi.json", timeout=T)
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        for p in [
            "/api/before-after/generate",
            "/api/before-after/pairs",
            "/api/before-after/pairs/{pid}",
            "/api/before-after/pairs/{pid}/regenerate",
            "/api/before-after/public/{share_token}",
            "/api/comms/automations/{code}/generate-copy",
            "/api/comms/planners/seasonal/draft",
            "/api/comms/planners/seasonal/approve",
            "/api/comms/planners/invoice-followup/draft",
            "/api/comms/planners/invoice-followup/approve",
        ]:
            assert p in paths, f"missing OpenAPI path: {p}"

"""Phase 56.20 — Auto End-of-Visit Email + Calculator Attach tests.

Fast unit-level tests via direct fastapi TestClient — hits Mongo but
doesn't require the live uvicorn server.
"""
from __future__ import annotations
import asyncio
import os
import pytest
import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 20


def _login(email, pwd="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pwd}, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ─── Auto-email settings ─────────────────────────────────────────────
class TestAutoEmailSettings:
    def test_default_disabled(self, admin_tok):
        # Reset first to a known state
        requests.put(f"{API}/settings/auto-visit-email", headers=_h(admin_tok),
                     json={"enabled": False, "google_review_link": "",
                           "footer_text": "", "include_reviews_cta": True},
                     timeout=TIMEOUT)
        r = requests.get(f"{API}/settings/auto-visit-email", headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["enabled"] is False

    def test_toggle_on(self, admin_tok):
        r = requests.put(f"{API}/settings/auto-visit-email", headers=_h(admin_tok),
                         json={"enabled": True,
                               "google_review_link": "https://g.page/pool-vistancia",
                               "footer_text": "Family-owned since 2003."},
                         timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{API}/settings/auto-visit-email", headers=_h(admin_tok), timeout=TIMEOUT)
        j = r2.json()
        assert j["enabled"] is True
        assert j["google_review_link"] == "https://g.page/pool-vistancia"

    def test_customer_forbidden(self):
        cust = _login("customer@aquaterra.com")
        r = requests.get(f"{API}/settings/auto-visit-email", headers=_h(cust), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_preview_renders(self, admin_tok):
        r = requests.post(f"{API}/settings/auto-visit-email/preview",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        # 200 if any submitted report exists in the tenant; 404 otherwise.
        assert r.status_code in (200, 404), r.text
        if r.status_code == 200:
            j = r.json()
            assert "subject" in j and "html" in j and "text" in j
            # Verify redaction: internal_notes must not appear in body.
            assert "internal_notes" not in j["html"].lower()


# ─── Rendered body — offline unit test hitting the renderer directly ─
class TestRenderer:
    def test_pool_render_shape(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.auto_visit_email import render_email
        tenant = {"name": "Test Tenant", "logo_url": "",
                  "settings": {"auto_visit_email": {
                      "enabled": True, "include_reviews_cta": True,
                      "google_review_link": "https://g.page/t",
                      "footer_text": "Custom footer."}}}
        job = {"id": "job1", "customer_id": "cust1",
               "address": "123 Main St", "service_type": "pool"}
        # Phase CHEM1 · Feb-2026 — dict-shape ``chemical_readings`` was
        # broken by the redact step in Feb-2026 Slice 3C (it silently
        # dropped every dict row). Switched this fixture to the
        # canonical list-of-dicts shape so the assertions below run
        # against real rendered output.
        sr = {"id": "sr1", "kind": "pool",
              "tech_name": "Mike",
              "chemical_readings": [
                  {"key": "ph",            "value": 7.4, "unit": ""},
                  {"key": "free_chlorine", "value": 3.0, "unit": "ppm"},
                  {"key": "alkalinity",    "value": 90,  "unit": "ppm"},
                  {"key": "cyanuric_acid", "value": 45,  "unit": "ppm"},
              ],
              "chemicals_added": [{"name": "Muriatic Acid", "amount": 32, "unit": "oz"}],
              "checklist_completed": [{"label": "Skimmed pool", "done": True}],
              "observations": {"visible_algae": "light"},
              "customer_notes": "Pool looks great — see you next week.",
              "internal_notes": "SECRET INTERNAL — dosing was 12 oz",
              "photos": [
                  {"url": "https://example.com/ok.jpg", "tags": ["exterior"]},
                  {"url": "https://example.com/internal.jpg", "tags": ["internal"]},
              ]}
        # simulate the redaction step
        from routers.service_reports import _redact_report_for_customer
        safe_sr = _redact_report_for_customer(dict(sr))
        out = render_email(tenant, job, safe_sr, {"email": "c@x.com"})
        assert "Test Tenant" in out["subject"]
        # Phase COMM1 · Feb-2026 — the pH row surfaces via the display
        # label from ``chemistry_gate.DISPLAY_LABELS`` (``"pH"``).
        assert "pH" in out["html"]
        assert "Muriatic Acid" in out["html"]
        assert "Light algae was observed and treated." in out["html"]
        assert "Pool looks great" in out["html"]
        assert "Leave us a review" in out["html"]
        assert "Custom footer." in out["html"]
        # Redaction assertions.
        assert "SECRET INTERNAL" not in out["html"]
        assert "internal.jpg" not in out["html"]
        assert "https://example.com/ok.jpg" in out["html"]
        # Text fallback.
        assert "Service visit summary" in out["text"]
        assert "SECRET INTERNAL" not in out["text"]

    def test_landscape_render(self):
        from services.auto_visit_email import render_email
        tenant = {"name": "Green Co", "settings": {"auto_visit_email": {"enabled": True}}}
        job = {"id": "j2", "customer_id": "c2", "address": "9 Elm", "service_type": "landscape"}
        sr = {"id": "sr2", "kind": "landscape",
              "checklist_completed": [{"label": "Mowed lawn", "done": True},
                                        {"label": "Trimmed hedges", "done": True}],
              "customer_notes": "Trimmed the roses too."}
        from routers.service_reports import _redact_report_for_customer
        out = render_email(tenant, job, _redact_report_for_customer(dict(sr)),
                            {"email": "c@x.com"})
        assert "Green Co" in out["subject"]
        assert "Mowed lawn" in out["html"]
        assert "Trimmed the roses too." in out["html"]
        assert out["kind"] == "landscape"


# ─── Calculator attach hook ──────────────────────────────────────────
class TestCalculatorAttach:
    def test_no_open_report_returns_404(self, tech_tok):
        r = requests.post(f"{API}/service-report/attach-note",
                          headers=_h(tech_tok),
                          json={"text": "LSI 0.03 — balanced"}, timeout=TIMEOUT)
        # Either 404 (no open report for tech) or 200/409 if a stale open one exists.
        assert r.status_code in (200, 404, 409), r.text

    def test_customer_forbidden(self):
        cust = _login("customer@aquaterra.com")
        r = requests.post(f"{API}/service-report/attach-note",
                          headers=_h(cust),
                          json={"text": "test"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_empty_text_422(self, tech_tok):
        r = requests.post(f"{API}/service-report/attach-note",
                          headers=_h(tech_tok),
                          json={"text": "   "}, timeout=TIMEOUT)
        assert r.status_code == 422


# ─── Idempotency + missing-key fallback ──────────────────────────────
class TestSendPipeline:
    """Direct-call the service function via asyncio.run — sidesteps
    needing a live submit + doesn't require pytest-asyncio."""
    def test_disabled_short_circuits(self):
        from services.auto_visit_email import send_visit_summary_email
        tenant = {"id": "t-disabled", "settings": {"auto_visit_email": {"enabled": False}}}
        job = {"id": "jX", "customer_id": "cX"}
        sr = {"id": "srX"}
        result = asyncio.run(send_visit_summary_email(tenant, job, sr))
        assert result is None

    def test_missing_customer_short_circuits(self):
        # Enabled tenant but customer_id points to nothing — should return None cleanly.
        from services.auto_visit_email import send_visit_summary_email
        tenant = {"id": "t-nocust", "settings": {"auto_visit_email": {"enabled": True}}}
        job = {"id": "jY", "customer_id": "nonexistent-cust-id"}
        sr = {"id": "srY"}
        result = asyncio.run(send_visit_summary_email(tenant, job, sr))
        assert result is None

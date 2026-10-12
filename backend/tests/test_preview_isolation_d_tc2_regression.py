"""Preview isolation · P0 Stage 3 Commit D regression tests.

Pins the TC2 payload that the Stage-2 tester originally ran. Three
invariant layers:

1. **Sanitizer layer** — ``sanitize_pii_payload`` on the exact TC2
   dict yields the full 26-field patch with ``city='Testville'``,
   ``state='AZ'``, ``zip='85000'``, ``custom_fields.gate_code='4321'``
   preserved, ``custom_fields.secret_email`` redacted, ``notes``
   redacted, and the ``stripe_default_payment_method_id='pm_test_...'``
   accepted.
2. **Reject layer** — SSN on a top-level field raises
   ``PIIIngressRejected``. ``pm_live_*`` on the Stripe field raises
   ``PIIIngressRejected``. ``cus_live_*`` raises
   ``PIIIngressRejected``. ``pm_test_*`` passes through unmodified.
3. **HTTP round-trip** — POST /api/customers with TC2 → 200. The
   GET /api/customers/{id} after that POST returns
   ``city='Testville'`` / ``state='AZ'`` / ``zip='85000'`` /
   ``custom_fields.gate_code='4321'`` / ``custom_fields.secret_email``
   redacted — ALL round-trip (the pre-Commit-D bug dropped them to
   ``None`` because the CustomerIn Pydantic model didn't declare the
   fields).

The last block POSTs with the SSN and ``pm_live_`` variants and
asserts a 400 with the ``pii.ingress_rejected`` code — pinning the
HTTP-level reject contract.
"""
from __future__ import annotations

import importlib
import os
import uuid

import pytest
import requests

API = "http://localhost:8001/api"


# ────────────────────────────────────────────────────────────────────
# Shared TC2 payload — the exact body the Stage-2 tester had used.
# ────────────────────────────────────────────────────────────────────
TC2_PAYLOAD = {
    "name": "Terry Peterson",
    "email": "terry.peterson@real.example.com",
    "phone": "+1-206-715-1234",
    "address": "123 Real St",
    "city": "Phoenix",
    "state": "AZ",
    "zip": "85382",
    "notes": "Call me at terry@real.example.com or 206-715-9999",
    "custom_fields": {
        "gate_code": "4321",
        "secret_email": "secret@real.com",
    },
    "stripe_default_payment_method_id": "pm_test_abc123",
}


# ────────────────────────────────────────────────────────────────────
# 1 · Sanitizer-layer regression (unit, no HTTP)
# ────────────────────────────────────────────────────────────────────
def _reload_pi(force_env: str = "development"):
    os.environ["APP_ENV"] = force_env
    for mod in (
        "services.preview_isolation.config",
        "services.preview_isolation.redactor",
        "services.preview_isolation.synthesizer",
        "services.preview_isolation.decorator",
        "services.preview_isolation.middleware",
        "services.preview_isolation",
    ):
        importlib.reload(__import__(mod, fromlist=[""]))
    from services.preview_isolation.decorator import sanitize_pii_payload, PIIIngressRejected
    return sanitize_pii_payload, PIIIngressRejected


class TestSanitizerRoundTripsTC2Fields:
    def setup_method(self):
        self.sanitize, self.Rejected = _reload_pi("development")

    def teardown_method(self):
        _reload_pi("development")

    def test_city_state_zip_round_trip_to_synth_sentinel(self):
        out = self.sanitize(dict(TC2_PAYLOAD), kind="customer")
        assert out.get("city") == "Testville", \
            f"city dropped or wrong value: {out.get('city')!r}"
        assert out.get("state") == "AZ"
        assert out.get("zip") == "85000"
        assert out.get("postal_code") == "85000"
        assert out.get("country") == "US"

    def test_custom_fields_structure_preserved_with_values_redacted(self):
        out = self.sanitize(dict(TC2_PAYLOAD), kind="customer")
        cf = out.get("custom_fields")
        assert isinstance(cf, dict), \
            f"custom_fields dropped or non-dict: {cf!r}"
        # gate_code is a legitimate admin-ops string (non-PII per
        # Refinement 1 in the Step A inventory). PRESERVED verbatim.
        assert cf.get("gate_code") == "4321", \
            f"gate_code should round-trip, got {cf.get('gate_code')!r}"
        # secret_email was an email pattern — redacted.
        assert cf.get("secret_email") == "[redacted-email]"

    def test_notes_free_text_redacted(self):
        out = self.sanitize(dict(TC2_PAYLOAD), kind="customer")
        notes = out.get("notes") or ""
        assert "terry@real.example.com" not in notes
        assert "206-715-9999" not in notes.replace("[redacted-phone]", "")
        assert "[redacted-email]" in notes
        assert "[redacted-phone]" in notes

    def test_identity_fields_synthesized(self):
        out = self.sanitize(dict(TC2_PAYLOAD), kind="customer")
        # Name becomes Preview Customer{slug}.
        assert out.get("name", "").startswith("Preview Customer")
        # Email + phone + address land on synth sentinels.
        assert out.get("email", "").endswith("@preview.local")
        assert out.get("phone", "").startswith("555-01")
        assert " Preview St" in (out.get("address") or "")
        # Real PII never appears in the sanitized dict.
        import json
        blob = json.dumps(out).lower()
        for leaked in ("terry", "peterson", "206-715",
                        "@real.example.com", "123 real st"):
            assert leaked not in blob, \
                f"real PII '{leaked}' leaked into sanitized payload"

    def test_pm_test_accepted(self):
        out = self.sanitize(dict(TC2_PAYLOAD), kind="customer")
        assert out.get("stripe_default_payment_method_id") == "pm_test_abc123"

    def test_pm_live_rejected(self):
        body = dict(TC2_PAYLOAD)
        body["stripe_default_payment_method_id"] = "pm_live_abcDEF123"
        with pytest.raises(self.Rejected) as exc:
            self.sanitize(body, kind="customer")
        assert exc.value.reason == "live_stripe_token_rejected"
        assert exc.value.field == "stripe_default_payment_method_id"

    def test_cus_live_rejected(self):
        body = dict(TC2_PAYLOAD)
        body["stripe_customer_id"] = "cus_live_realCustomer"
        with pytest.raises(self.Rejected) as exc:
            self.sanitize(body, kind="customer")
        assert exc.value.reason == "live_stripe_token_rejected"

    def test_ssn_rejected(self):
        body = dict(TC2_PAYLOAD)
        body["ssn"] = "123-45-6789"
        with pytest.raises(self.Rejected) as exc:
            self.sanitize(body, kind="customer")
        assert exc.value.reason == "ssn_rejected"


# ────────────────────────────────────────────────────────────────────
# 2 · HTTP-layer regression (live backend)
# ────────────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


class TestTC2HttpRoundTrip:
    """POST /api/customers with the TC2 payload, then GET it back.
    The pre-Commit-D bug: CustomerIn didn't declare city/state/zip/
    custom_fields, so Pydantic dropped them from the stored doc.
    POST returned a doc with ``city=None, custom_fields=None`` and
    GET returned the same. Post-Commit-D: all four fields land on
    their synth sentinel + the redacted structure survives the
    round-trip."""

    def _created_ids(self):
        return getattr(self, "_cids", [])

    def setup_method(self):
        self._cids = []

    def teardown_method(self):
        # Cleanup every row the test created.
        if not self._cids:
            return
        try:
            tok = _login("admin@aquaterra.com")
            h = {"Authorization": f"Bearer {tok}"}
            for cid in self._cids:
                requests.delete(f"{API}/customers/{cid}",
                                headers=h, timeout=10)
        except Exception:
            pass

    def test_post_then_get_round_trips_city_state_zip_custom_fields(self, admin_h):
        # Use a unique body so parallel test runs don't collide.
        body = dict(TC2_PAYLOAD)
        body["name"] = f"{TC2_PAYLOAD['name']} {uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/customers", json=body,
                           headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text[:400]
        created = r.json()
        self._cids.append(created["id"])

        # Round-trip assertions on the POST response body.
        assert created["city"] == "Testville", \
            f"city dropped in POST response: {created.get('city')!r}"
        assert created["state"] == "AZ"
        assert created["zip"] == "85000"
        assert isinstance(created.get("custom_fields"), dict), \
            f"custom_fields dropped: {created.get('custom_fields')!r}"
        assert created["custom_fields"]["gate_code"] == "4321"
        assert created["custom_fields"]["secret_email"] == "[redacted-email]"

        # GET-after-POST — the stored doc round-trips the same shape.
        r = requests.get(f"{API}/customers/{created['id']}",
                          headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text[:400]
        fetched = r.json()
        assert fetched["city"] == "Testville"
        assert fetched["state"] == "AZ"
        assert fetched["zip"] == "85000"
        assert fetched["custom_fields"]["gate_code"] == "4321"
        assert fetched["custom_fields"]["secret_email"] == "[redacted-email]"

        # Name/email/phone/address all synthesized; no real PII leaks.
        for field in ("name", "email", "phone", "address"):
            v = fetched.get(field) or ""
            for leaked in ("terry", "peterson", "206-715",
                           "@real.example.com", "123 Real St"):
                assert leaked.lower() not in v.lower(), \
                    f"real PII '{leaked}' leaked into fetched.{field}"

        # Notes redacted.
        notes = fetched.get("notes") or ""
        assert "terry@real.example.com" not in notes
        assert "206-715-9999" not in notes
        assert "[redacted-email]" in notes
        assert "[redacted-phone]" in notes

        # Stripe test token accepted.
        assert fetched.get("stripe_default_payment_method_id") == "pm_test_abc123"

    def test_post_with_pm_live_returns_400(self, admin_h):
        body = dict(TC2_PAYLOAD)
        body["stripe_default_payment_method_id"] = "pm_live_abcDEF"
        r = requests.post(f"{API}/customers", json=body,
                           headers=admin_h, timeout=15)
        assert r.status_code == 400, r.text[:400]
        detail = r.json().get("detail") or {}
        assert detail.get("code") == "pii.ingress_rejected"
        assert detail.get("reason") == "live_stripe_token_rejected"
        assert detail.get("field") == "stripe_default_payment_method_id"

    def test_post_with_ssn_returns_400(self, admin_h):
        body = dict(TC2_PAYLOAD)
        body["ssn"] = "123-45-6789"
        r = requests.post(f"{API}/customers", json=body,
                           headers=admin_h, timeout=15)
        assert r.status_code == 400, r.text[:400]
        detail = r.json().get("detail") or {}
        assert detail.get("code") == "pii.ingress_rejected"
        assert detail.get("reason") == "ssn_rejected"

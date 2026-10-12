"""Preview isolation · P0 Stage 3 Commit B regression tests.

Pins three invariants that the Commit B schema-shape fix introduces:

1. ``synthesize_customer_fields`` emits ``emails`` / ``mobiles`` /
   ``phones`` as object arrays matching the normalizer schema in
   ``services.customer_multi_contact`` — NOT list-of-string (which
   broke ``GET /api/customers?page_size>5`` with a 500 pre-Commit-B).

2. ``GET /api/customers?page_size=100`` returns a paginated envelope
   with up to 100 items, every row deserialises cleanly under the
   ``CustomerListItem`` response_model (i.e. no shape-mismatch 500).

3. ``GET /api/customers?size=100`` returns 400 with the
   project-standard ``{error_code, detail, message}`` payload. ``size``
   is NOT a supported alias for ``page_size``.

Live HTTP tests use ``http://localhost:8001/api`` against the running
backend (same pattern as ``test_customers_pagination_p35.py``).
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

API = "http://localhost:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


# ────────────────────────────────────────────────────────────────────
# 1 · Synthesizer shape — unit level (no HTTP, no DB)
# ────────────────────────────────────────────────────────────────────
def _reload_pi(force_env: str = "development"):
    os.environ["APP_ENV"] = force_env
    import services.preview_isolation.config as cfg
    importlib.reload(cfg)
    import services.preview_isolation.synthesizer as syn
    importlib.reload(syn)
    import services.preview_isolation.decorator as dec
    importlib.reload(dec)
    return syn, dec


class TestSynthesizerEmitsObjectArrays:
    def setup_method(self):
        self.syn, self.dec = _reload_pi("development")

    def teardown_method(self):
        _reload_pi("development")

    def test_emails_is_object_array_when_present_on_real(self):
        real = {
            "name": "Terry Peterson",
            "email": "terry@example.com",
            "phone": "+16025551234",
            "emails": [{"address": "terry@example.com", "is_primary": True}],
        }
        out = self.syn.synthesize_customer_fields(real)
        assert isinstance(out["emails"], list)
        assert len(out["emails"]) == 1
        entry = out["emails"][0]
        assert isinstance(entry, dict), \
            f"emails entry must be object, got {type(entry).__name__}"
        for key in ("address", "label", "is_primary",
                     "marketing_ok", "notifications_enabled"):
            assert key in entry, f"missing key on emails entry: {key}"
        assert entry["address"].startswith("preview-customer")
        assert entry["address"].endswith("@preview.local")
        assert entry["is_primary"] is True

    def test_mobiles_is_object_array_when_present_on_real(self):
        real = {
            "name": "Terry Peterson", "email": "terry@example.com",
            "mobiles": [{"number_e164": "+16025551234"}],
        }
        out = self.syn.synthesize_customer_fields(real)
        assert isinstance(out["mobiles"], list)
        entry = out["mobiles"][0]
        assert isinstance(entry, dict)
        for key in ("number_e164", "label", "is_primary",
                     "sms_ok", "notifications_enabled"):
            assert key in entry
        assert entry["number_e164"].startswith("555-02")
        assert entry["is_primary"] is True

    def test_phones_is_object_array_with_type_and_number_keys(self):
        real = {
            "name": "Terry Peterson", "email": "terry@example.com",
            "phones": [{"type": "home", "number": "+16025551234"}],
        }
        out = self.syn.synthesize_customer_fields(real)
        assert isinstance(out["phones"], list)
        for entry in out["phones"]:
            assert isinstance(entry, dict)
            for key in ("type", "number", "e164", "raw"):
                assert key in entry

    def test_emails_absent_on_real_stays_absent_in_patch(self):
        """We must not conjure object arrays onto docs that didn't
        carry them — downstream code uses presence of the key as a
        signal that the customer opted into the multi-contact UX."""
        real = {"name": "Terry Peterson", "email": "terry@example.com"}
        out = self.syn.synthesize_customer_fields(real)
        assert "emails" not in out
        assert "mobiles" not in out
        assert "phones" not in out

    def test_sanitize_payload_preserves_object_array_shape(self):
        """The _sanitize_dict recursive walk MUST NOT re-run the
        customer synth on each nested emails/mobiles/phones entry;
        if it does, the nested entry gets name/phone/email keys
        clobbered onto it, which was the pre-Commit-B behavior."""
        real = {
            "name": "Terry Peterson", "email": "terry@example.com",
            "phone": "+16025551234",
            "emails": [{"address": "terry@example.com", "is_primary": True,
                         "label": "Primary"}],
            "mobiles": [{"number_e164": "+16025551234",
                         "is_primary": True, "label": "Primary"}],
        }
        out = self.dec.sanitize_pii_payload(real, kind="customer")
        # emails entry still has ONLY the email-entry keys (no
        # ``name`` / ``phone`` / ``address`` leaking in).
        entry = out["emails"][0]
        assert isinstance(entry, dict)
        # The exact keys emitted by the synthesizer.
        assert set(entry.keys()) == {
            "address", "label", "is_primary",
            "marketing_ok", "notifications_enabled",
        }
        mobile_entry = out["mobiles"][0]
        assert set(mobile_entry.keys()) == {
            "number_e164", "label", "is_primary",
            "sms_ok", "notifications_enabled",
        }


# ────────────────────────────────────────────────────────────────────
# 2 · Live HTTP — GET /api/customers?page_size=100 → 200
# ────────────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


class TestListEndpointSurvivesSchemaFix:
    """Pre-Commit-B these calls 500'd with a Pydantic validation
    error on the emails/mobiles list shape. Post-Commit-B they
    return 200. The migration repaired every pre-existing bad row."""

    def test_page_size_100_returns_200_with_envelope(self, admin_h):
        r = requests.get(
            f"{API}/customers?page_size=100&sort=name_asc",
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        assert isinstance(body, dict), \
            "Expected paginated envelope; got bare array."
        assert set(body.keys()) >= {
            "items", "total", "page", "page_size", "total_pages"}
        assert body["page_size"] == 100
        assert len(body["items"]) <= 100
        # Every row deserialises — pin the critical PII-shape fields.
        for item in body["items"]:
            # emails is optional on the response model (not every
            # customer carries one), but when present it must be a
            # list of dicts with ``address`` — the broken list-of-
            # string shape would 500 here.
            emails = item.get("emails")
            if emails is not None:
                assert isinstance(emails, list)
                for e in emails:
                    assert isinstance(e, dict), \
                        f"emails entry must be dict, got {type(e).__name__}: {e!r}"
                    assert "address" in e
            mobiles = item.get("mobiles")
            if mobiles is not None:
                assert isinstance(mobiles, list)
                for m in mobiles:
                    assert isinstance(m, dict)
                    assert "number_e164" in m

    def test_size_alias_returns_400_with_project_shape(self, admin_h):
        r = requests.get(
            f"{API}/customers?size=100", headers=admin_h, timeout=15,
        )
        assert r.status_code == 400, r.text[:500]
        body = r.json()
        detail = body.get("detail") or {}
        # Project-standard 400 shape: dict with error_code + detail + message.
        assert isinstance(detail, dict), \
            f"detail must be object (project 400 shape); got {type(detail).__name__}"
        assert detail.get("error_code") == "unknown_param"
        assert detail.get("detail") == "unsupported_query_param"
        assert "size" in (detail.get("message") or "")
        assert "page_size" in (detail.get("message") or "")

    def test_size_with_page_size_present_still_rejects(self, admin_h):
        """``size`` is unsupported even when ``page_size`` is also
        passed — teaches callers to drop the alias entirely."""
        r = requests.get(
            f"{API}/customers?size=50&page_size=100",
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 400, r.text[:500]
        assert r.json()["detail"]["error_code"] == "unknown_param"

"""Preview isolation · Feb-2026 P0 · Commit 1 regression tests.

NON-NEGOTIABLE invariants:

1. On ``APP_ENV=production``, every sanitize entrypoint is a strict
   identity function. Real PII is written UNCHANGED.
2. On preview env (``APP_ENV`` anything else), real PII is replaced
   by the deterministic synthetic equivalent.
3. The hash function is deterministic across processes — same real
   value + same salt → same synthetic bucket on every call.
4. REJECT patterns (SSN / CC / live Stripe token / DL / DOB) raise
   ``PIIIngressRejected`` BEFORE the write.
5. The free-text redactor keeps legitimate business text (gate
   codes, service preferences) intact; redacts email / phone / SSN /
   CC tokens embedded in notes.
6. The ASGI middleware is a no-op on routes NOT in the registry.
"""
from __future__ import annotations

import importlib
import os
import pytest


def _reload_module(force_env: str):
    """Re-import ``services.preview_isolation.config`` after flipping
    ``APP_ENV`` so ``is_production_env()`` sees the new value."""
    os.environ["APP_ENV"] = force_env
    import services.preview_isolation.config as cfg
    importlib.reload(cfg)
    import services.preview_isolation.decorator as dec
    importlib.reload(dec)
    import services.preview_isolation.middleware as mw
    importlib.reload(mw)
    import services.preview_isolation as pi
    importlib.reload(pi)
    return pi


# ────────────────────────────────────────────────────────────────────
# 1 · Production env — strict no-op.
# ────────────────────────────────────────────────────────────────────
class TestProductionIsStrictNoOp:
    def setup_method(self):
        self.pi = _reload_module("production")

    def teardown_method(self):
        _reload_module("development")

    def test_is_production_env_is_true(self):
        assert self.pi.is_production_env() is True
        assert self.pi.is_preview_env() is False

    def test_sanitize_pii_payload_identity(self):
        real = {
            "name": "Jane Doe", "email": "jane@real.example.com",
            "phone": "+1-602-555-1234",
            "address": "123 Real St", "notes": "Call Jane at 602-555-9999",
        }
        out = self.pi.sanitize_pii_payload(real, kind="customer")
        # Identity — the dict IS the input (no copy, no mutation).
        assert out is real
        assert out["name"] == "Jane Doe"
        assert out["email"] == "jane@real.example.com"
        assert out["notes"] == "Call Jane at 602-555-9999"

    def test_sanitize_csv_rows_identity(self):
        rows = [{"name": "Pat Kail", "email": "pat@real.com"}]
        out = self.pi.sanitize_csv_rows(rows, kind="customer")
        # List is rebuilt (list() call) but every ELEMENT is the
        # same object — no field mutation.
        assert out[0] is rows[0]
        assert out[0]["name"] == "Pat Kail"

    def test_reject_patterns_do_not_fire_on_production(self):
        # Even SSN / CC don't 400 on production — strict pass-through.
        real = {"ssn": "123-45-6789", "note": "4111 1111 1111 1111"}
        out = self.pi.sanitize_pii_payload(real)
        assert out is real
        assert out["ssn"] == "123-45-6789"

    def test_pdf_extracted_rows_identity(self):
        rows = [{"customer_name": "Real Client LLC",
                 "bill_to_address": "501 Market St"}]
        out = self.pi.sanitize_pdf_extracted_rows(rows)
        assert out[0]["customer_name"] == "Real Client LLC"


# ────────────────────────────────────────────────────────────────────
# 2 · Preview env — PII shape is swapped.
# ────────────────────────────────────────────────────────────────────
class TestPreviewSanitizes:
    def setup_method(self):
        self.pi = _reload_module("development")

    def test_is_preview_env_is_true(self):
        assert self.pi.is_preview_env() is True
        assert self.pi.is_production_env() is False

    def test_customer_payload_is_synthesized(self):
        real = {
            "id": "keep-me-unchanged",
            "tenant_id": "tenant-a",
            "name": "John Smith",
            "email": "john@real.example.com",
            "phone": "602-555-1234",
            "address": "501 Main St",
            "city": "Phoenix",
            "notes": "Prefers Thursdays. Email backup: john2@real.com",
        }
        out = self.pi.sanitize_pii_payload(real, kind="customer")
        # ID + tenant_id preserved — admin workflows depend on these.
        assert out["id"] == "keep-me-unchanged"
        assert out["tenant_id"] == "tenant-a"
        # PII shape is Preview Customer*.
        assert out["name"].startswith("Preview Customer")
        assert out["email"].endswith("@preview.local")
        assert out["phone"].startswith("555-01")
        assert out["city"] == "Testville"
        # Free-text redactor kept business text, redacted embedded
        # email + phone tokens.
        assert "Thursdays" in out["notes"]
        assert "[redacted-email]" in out["notes"]
        assert "john@real.example.com" not in out["notes"]
        assert "john2@real.com" not in out["notes"]

    def test_deterministic_synthetic_bucket(self):
        """Hash is deterministic — same input in two calls yields
        the same synthetic value."""
        b1 = self.pi.synthetic_bucket("John Smith")
        b2 = self.pi.synthetic_bucket("John Smith")
        b3 = self.pi.synthetic_bucket("Different Name")
        assert b1 == b2
        assert b1 != b3  # Different real → different bucket (vanishingly rare clash).

    def test_rejects_raw_ssn(self):
        with pytest.raises(self.pi.PIIIngressRejected) as excinfo:
            self.pi.sanitize_pii_payload({"ssn": "123-45-6789"})
        assert excinfo.value.reason == "ssn_rejected"
        assert excinfo.value.field == "ssn"

    def test_rejects_live_stripe_token(self):
        with pytest.raises(self.pi.PIIIngressRejected) as excinfo:
            self.pi.sanitize_pii_payload({
                "stripe_payment_method_id": "pm_live_1Abc123DefGhiJkl"
            })
        assert excinfo.value.reason == "live_stripe_token_rejected"

    def test_accepts_test_stripe_token(self):
        out = self.pi.sanitize_pii_payload({
            "stripe_payment_method_id": "pm_test_1Abc123DefGhi"
        })
        # Test tokens pass through — not stripe-field-shape in the map.
        assert out["stripe_payment_method_id"].startswith("pm_test_")

    def test_rejects_cc_number(self):
        with pytest.raises(self.pi.PIIIngressRejected) as excinfo:
            self.pi.sanitize_pii_payload({"card": "4111111111111111"})
        assert excinfo.value.reason == "cc_rejected"

    def test_rejects_dob_in_dob_field(self):
        with pytest.raises(self.pi.PIIIngressRejected) as excinfo:
            self.pi.sanitize_pii_payload({"dob": "1985-07-12"})
        assert excinfo.value.reason == "dob_rejected"

    def test_dob_pattern_in_non_dob_field_passes(self):
        # ``2026-02-15`` in a ``created_at`` field is NOT a DOB —
        # pass through.
        out = self.pi.sanitize_pii_payload({"created_at": "2026-02-15"})
        assert out["created_at"] == "2026-02-15"


# ────────────────────────────────────────────────────────────────────
# 3 · Free-text redactor — business text preserved.
# ────────────────────────────────────────────────────────────────────
class TestRedactor:
    def setup_method(self):
        self.pi = _reload_module("development")

    @pytest.mark.parametrize("text,contains,not_contains", [
        ("Gate code is 4321", ["Gate code is 4321"], []),
        ("Prefers morning service", ["Prefers morning service"], []),
        ("Email me: jane@real.com please",
             ["[redacted-email]"], ["jane@real.com"]),
        ("Call 602-555-1234 or 480.555.9876",
             ["[redacted-phone]"], ["602-555-1234", "480.555.9876"]),
        ("SSN 123-45-6789 on file",
             ["[redacted-ssn]"], ["123-45-6789"]),
        ("Dispute CC 4111 1111 1111 1111",
             ["[redacted-cc]"], ["4111"]),
        ("Visit https://example.com/x?email=real@foo.com&other=keep",
             ["https://example.com/x", "other=keep"], ["email=real"]),
    ])
    def test_redacts_pii_tokens_in_free_text(self, text, contains, not_contains):
        out = self.pi.redact_free_text(text)
        for s in contains:
            assert s in out, f"expected {s!r} in {out!r}"
        for s in not_contains:
            assert s not in out, f"expected {s!r} NOT in {out!r}"


# ────────────────────────────────────────────────────────────────────
# 4 · Route registry — matcher works for templated paths.
# ────────────────────────────────────────────────────────────────────
class TestRegistry:
    def setup_method(self):
        self.pi = _reload_module("development")

    def test_customer_create_path_matches(self):
        from services.preview_isolation.registry import path_matches_registry
        assert path_matches_registry("POST", "/api/customers") is True
        assert path_matches_registry("PATCH",
                                      "/api/customers/abc-123-def") is True
        assert path_matches_registry("POST",
                                      "/api/import/customers") is True
        assert path_matches_registry("POST",
                                      "/api/imports/pdf-invoice") is True

    def test_non_pii_paths_do_not_match(self):
        from services.preview_isolation.registry import path_matches_registry
        assert path_matches_registry("GET", "/api/customers") is False
        assert path_matches_registry("POST", "/api/jobs") is False
        assert path_matches_registry("POST", "/api/comms/email-templates") is False

    def test_kind_resolution(self):
        from services.preview_isolation.registry import kind_for_path
        assert kind_for_path("POST", "/api/customers") == "customer"
        assert kind_for_path("POST", "/api/leads") == "lead"
        assert kind_for_path("POST", "/api/marketing/subscribers") == "subscriber"
        assert kind_for_path("POST", "/api/signup") == "signup"


# ────────────────────────────────────────────────────────────────────
# 5 · Smoke test — importing ``services.preview_isolation`` on
#     production boot does not error.
# ────────────────────────────────────────────────────────────────────
class TestProductionImportSmoke:
    def test_module_imports_cleanly_on_production(self):
        os.environ["APP_ENV"] = "production"
        try:
            import services.preview_isolation.config as cfg
            importlib.reload(cfg)
            assert cfg.is_production_env() is True
        finally:
            os.environ["APP_ENV"] = "development"
            importlib.reload(cfg)

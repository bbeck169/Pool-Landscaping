"""Preview isolation · P0 Stage 3 Commit H production-safety regression.

Pins the strict-no-op posture under ``APP_ENV=production`` across
the full Step A field inventory. If ANY of these assertions fire
on production, the preview-isolation layer has leaked into prod
and MUST roll back immediately.

Three invariant layers:

1. **Decorator identity** — ``sanitize_pii_payload(payload) is
   payload`` for every one of the 26+ Step A PII fields,
   including real-shape values. The same-object identity check
   proves no copy was made — zero overhead on the prod request
   path.

2. **Scrubber refusal** — ``run_once(db)`` returns
   ``{"skipped": "production_env"}`` without touching any row.

3. **Healthcheck absence** — ``GET /api/admin/preview-isolation-
   status`` returns 404 on production.

4. **Boot assertion non-blocking** — ``assert_registry_coverage``
   returns the audit report (never raises) under production even
   when orphan routes exist.
"""
from __future__ import annotations

import importlib
import os

import pytest


# ────────────────────────────────────────────────────────────────────
# Shared Step A field inventory — the 26+ fields the Step A
# inventory doc identified across customers / leads / users
# collections.
# ────────────────────────────────────────────────────────────────────
_STEP_A_CUSTOMER_FIELDS = [
    # Scalar PII.
    ("name",                  "Terry Peterson"),
    ("first_name",            "Terry"),
    ("last_name",             "Peterson"),
    ("display_name",          "Terry P."),
    ("email",                 "terry.peterson@gmail.com"),
    ("phone",                 "+1-206-715-1234"),
    ("home_phone",            "+1-623-555-0199"),
    ("mobile",                "+1-206-555-0188"),
    ("phone_mobile",          "+1-206-555-0177"),
    ("phone_raw",             "2067151234"),
    ("mobile_raw",            "2065550188"),
    ("fax",                   "+1-206-555-0177"),
    # Address.
    ("address",               "1509 E Maddock Rd"),
    ("address_line1",         "1509 E Maddock Rd"),
    ("address_line_1",        "1509 E Maddock Rd"),
    ("address_line_2",        "Apt 2B"),
    ("street",                "1509 E Maddock Rd"),
    ("street_address",        "1509 E Maddock Rd"),
    ("bill_to_address",       "1509 E Maddock Rd"),
    ("city",                  "Phoenix"),
    ("state",                 "AZ"),
    ("zip",                   "85382"),
    ("zip_code",              "85382"),
    ("postal_code",           "85382"),
    ("country",               "US"),
    ("address_city",          "Phoenix"),
    ("address_state",         "AZ"),
    ("address_zip",           "85382"),
    ("service_city",          "Phoenix"),
    ("service_state",         "AZ"),
    ("service_zip",           "85382"),
    ("billing_city",          "Phoenix"),
    ("billing_state",         "AZ"),
    ("billing_zip",           "85382"),
    # Multi-contact.
    ("master_billing_contact_email", "billing@real-domain.com"),
    ("master_billing_contact_phone", "+1-206-555-0144"),
    ("alert_email",           "alert@real-domain.com"),
    ("alert_phone",           "+1-206-555-0133"),
    # Geo.
    ("latitude",              33.7670356),
    ("longitude",             -112.3397496),
    ("service_lat",           33.7670356),
    ("service_lng",           -112.3397496),
    ("service_location",      {"type": "Point", "coordinates": [-112.33, 33.76]}),
    ("geocode_address_hash",  "dcc14d9a3dba883da4041f4e0966eeee279be0b2"),
    # Free text w/ embedded PII.
    ("notes",                 "Call Terry at 206-715-1234 or terry@gmail.com"),
    ("service_notes",         "Access via gate 4321. Owner: terry@gmail.com"),
    ("vip_note",              "Vip since 2023 — email jane@real.com for ref"),
    ("dog_notes",             "Rex is friendly, call 206-555-9999"),
    ("internal_notes",        "SSN 123-45-6789 noted for file"),
    # Custom fields.
    ("custom_fields",         {"gate_code": "4321",
                                "secret_email": "secret@real.com",
                                "backup_phone": "206-555-0122"}),
    # Nested address.
    ("service_address",       {"street": "1509 E Maddock Rd",
                                "city": "Phoenix", "state": "AZ",
                                "postal_code": "85382",
                                "country": "US"}),
    ("billing_address",       {"street": "1509 E Maddock Rd",
                                "city": "Phoenix", "state": "AZ"}),
    ("secondary_addresses",   [{"street": "22 Second St"}]),
    # Lists.
    ("emails",                [{"address": "terry@real.com",
                                 "is_primary": True,
                                 "marketing_ok": True,
                                 "notifications_enabled": True,
                                 "label": "Primary"}]),
    ("mobiles",               [{"number_e164": "+12067151234",
                                 "is_primary": True, "sms_ok": True,
                                 "notifications_enabled": True,
                                 "label": "Primary"}]),
    ("phones",                [{"type": "home",
                                 "number": "+16235550199",
                                 "e164": "+16235550199",
                                 "raw": "6235550199"}]),
    # Companies.
    ("company",               "Peterson Properties LLC"),
    ("company_name",          "Peterson Properties LLC"),
    # Search haystack.
    ("search_haystack",       "terry peterson terry.peterson@gmail.com "
                                "2067151234 1509 e maddock rd, phoenix, az"),
    # Stripe denorm (should still echo identity on prod — the
    # decorator never writes stripe denorm fields on prod).
    ("stripe_customer_id",         "cus_live_realStripeId"),
    ("stripe_default_payment_method_id", "pm_live_realMethod"),
    ("stripe_card_brand",          "visa"),
    ("stripe_card_last4",          "4242"),
    # Photos.
    ("profile_photo_url",     "https://real-cdn.example.com/photos/xyz.jpg"),
    ("avatar",                "data:image/png;base64,iVBORw0..."),
]

_STEP_A_LEAD_FIELDS = [
    ("name",                  "Jane Carson"),
    ("first_name",            "Jane"),
    ("last_name",             "Carson"),
    ("email",                 "jane.carson@comcast.net"),
    ("phone",                 "+1-480-555-0102"),
    ("phone_raw",             "4805550102"),
    ("address",               "88 Desert Vista Dr, Peoria, AZ"),
    ("service_address",       {"street": "88 Desert Vista Dr",
                                "city": "Peoria", "state": "AZ",
                                "postal_code": "85383",
                                "country": "US"}),
    ("message",               "Please call me at 480-555-0102"),
    ("notes",                 "Owner's email: jane@real.net"),
    ("internal_notes",        "Lead qualified. Follow up next week."),
    ("vip_note",              "Spouse answers phone — Mike Carson"),
    ("latitude",              33.5721),
    ("longitude",             -112.2378),
    ("created_ip",            "71.212.45.89"),
    ("search_haystack",       "jane carson jane.carson@comcast.net "
                                "4805550102 88 desert vista dr"),
    ("timeline",              [{"ts": "2026-02-01",
                                 "kind": "note",
                                 "actor": "admin",
                                 "payload": {"text": "called jane"}}]),
    ("meta",                  {"referrer_name": "Mike Carson",
                                "referrer_email": "mike@real.net"}),
]

_STEP_A_SUBSCRIBER_FIELDS = [
    ("first_name",            "Mary"),
    ("last_name",             "Whitmore"),
    ("email",                 "mary.whitmore@earthlink.net"),
    ("phone",                 "+1-623-555-0144"),
]


def _reload_pi(force_env: str):
    os.environ["APP_ENV"] = force_env
    for m in ("services.preview_isolation.config",
              "services.preview_isolation.redactor",
              "services.preview_isolation.synthesizer",
              "services.preview_isolation.decorator",
              "services.preview_isolation.middleware",
              "services.preview_isolation.scrubber",
              "services.preview_isolation.registry",
              "services.preview_isolation"):
        importlib.reload(__import__(m, fromlist=[""]))
    from services.preview_isolation.decorator import sanitize_pii_payload, PIIIngressRejected
    import services.preview_isolation.scrubber as sc
    import services.preview_isolation.registry as reg
    return sanitize_pii_payload, PIIIngressRejected, sc, reg


# ────────────────────────────────────────────────────────────────────
# 1 · Decorator strict identity under APP_ENV=production
# ────────────────────────────────────────────────────────────────────
class TestProductionDecoratorStrictIdentity:
    """Under APP_ENV=production, ``sanitize_pii_payload(payload)``
    MUST return the SAME object (``is payload``) for every Step A
    field — no copy, no modification, no synth substitution. This
    proves zero-overhead on the prod request path."""

    def setup_method(self):
        self.sanitize, _, _, _ = _reload_pi("production")

    def teardown_method(self):
        _reload_pi("development")

    @pytest.mark.parametrize("field,value", _STEP_A_CUSTOMER_FIELDS,
                              ids=[f for f, _ in _STEP_A_CUSTOMER_FIELDS])
    def test_customer_field_identity(self, field, value):
        payload = {field: value, "id": "existing-id", "tenant_id": "t-1"}
        out = self.sanitize(payload, kind="customer")
        assert out is payload, \
            f"Expected STRICT IDENTITY on production for customer.{field} — "\
            f"got a copy. Preview-isolation leaked into prod."
        # Also verify the value survived verbatim.
        assert out[field] == value, \
            f"customer.{field} value drift on production: {out[field]!r}"

    @pytest.mark.parametrize("field,value", _STEP_A_LEAD_FIELDS,
                              ids=[f for f, _ in _STEP_A_LEAD_FIELDS])
    def test_lead_field_identity(self, field, value):
        payload = {field: value, "id": "existing-lead", "tenant_id": "t-1"}
        out = self.sanitize(payload, kind="lead")
        assert out is payload, \
            f"Expected STRICT IDENTITY on production for lead.{field} — "\
            f"got a copy. Preview-isolation leaked into prod."
        assert out[field] == value

    @pytest.mark.parametrize("field,value", _STEP_A_SUBSCRIBER_FIELDS,
                              ids=[f for f, _ in _STEP_A_SUBSCRIBER_FIELDS])
    def test_subscriber_field_identity(self, field, value):
        payload = {field: value, "id": "existing-sub", "tenant_id": "t-1"}
        out = self.sanitize(payload, kind="subscriber")
        assert out is payload, \
            f"Expected STRICT IDENTITY on production for subscriber.{field}"
        assert out[field] == value

    def test_full_tc2_shape_identity(self):
        """Belt-and-suspenders: the exact TC2 payload with ALL
        Step A customer fields populated at once — identity must
        still hold."""
        payload = {f: v for f, v in _STEP_A_CUSTOMER_FIELDS}
        payload["id"] = "existing-id"
        payload["tenant_id"] = "t-1"
        out = self.sanitize(payload, kind="customer")
        assert out is payload
        for field, value in _STEP_A_CUSTOMER_FIELDS:
            assert out[field] == value, \
                f"Field {field} drifted under production identity: "\
                f"{out[field]!r} != {value!r}"

    def test_ssn_pass_through_identity_not_rejected(self):
        """Under production, SSN values pass through verbatim
        instead of raising ``PIIIngressRejected``. Preview-env
        rejection must not leak into prod request flows."""
        payload = {"name": "x", "email": "x@x.com", "ssn": "123-45-6789"}
        out = self.sanitize(payload, kind="customer")
        assert out is payload
        assert out["ssn"] == "123-45-6789"

    def test_live_stripe_token_pass_through_identity(self):
        """Live stripe tokens pass through on prod (they ARE the
        prod source of truth)."""
        payload = {"name": "x", "email": "x@x.com",
                    "stripe_default_payment_method_id": "pm_live_realMethod"}
        out = self.sanitize(payload, kind="customer")
        assert out is payload
        assert out["stripe_default_payment_method_id"] == "pm_live_realMethod"


# ────────────────────────────────────────────────────────────────────
# 2 · Scrubber refuses to run under APP_ENV=production
# ────────────────────────────────────────────────────────────────────
class TestProductionScrubberRefusal:
    def test_scrubber_run_once_returns_skipped_production_env(self):
        _, _, sc, _ = _reload_pi("production")
        import asyncio
        result = asyncio.run(sc.run_once(db=None, force=True))
        assert result == {"skipped": "production_env", "scrubbed_counts": {}}
        _reload_pi("development")

    def test_scrubber_even_with_force_true_refuses_on_production(self):
        """``force=True`` MUST NOT override the production guard —
        prod never gets scrubbed regardless of CLI invocation."""
        _, _, sc, _ = _reload_pi("production")
        import asyncio
        result = asyncio.run(sc.run_once(db=None, force=True))
        assert "skipped" in result
        assert result["skipped"] == "production_env"
        _reload_pi("development")


# ────────────────────────────────────────────────────────────────────
# 3 · Registry audit non-blocking under APP_ENV=production
# ────────────────────────────────────────────────────────────────────
class TestProductionRegistryNonBlocking:
    def test_assert_registry_coverage_never_raises_on_production(self):
        """Even with 50 orphan PII-shaped routes, prod boot stays
        up — assert_registry_coverage logs WARN and returns the
        report. Preview is the HARD-FAIL env."""
        _, _, _, reg = _reload_pi("production")
        from fastapi import FastAPI, APIRouter
        from pydantic import BaseModel

        class _PIIIn(BaseModel):
            name: str
            email: str

        app = FastAPI()
        r = APIRouter()
        for i in range(50):
            @r.post(f"/api/customers/orphan-{i}")
            async def _h(body: _PIIIn):
                return {}
        app.include_router(r)

        # Must NOT raise.
        report = reg.assert_registry_coverage(app)
        assert report["status"] == "RED"
        assert len(report["unregistered_pii_shaped_routes"]) >= 50
        _reload_pi("development")


# ────────────────────────────────────────────────────────────────────
# 4 · Healthcheck endpoint absence under APP_ENV=production
# ────────────────────────────────────────────────────────────────────
def test_healthcheck_endpoint_404_on_production():
    """``GET /api/admin/preview-isolation-status`` MUST return 404
    on APP_ENV=production. Mounting a preview-only diagnostics
    endpoint on prod reveals internal shape and should not exist."""
    _reload_pi("production")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routers.preview_isolation_admin as mod
    importlib.reload(mod)

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[mod.require_admin] = lambda: {
        "id": "u-admin", "role": "admin",
    }

    client = TestClient(app)
    r = client.get("/api/admin/preview-isolation-status")
    assert r.status_code == 404, r.text[:200]
    assert r.json().get("detail") == "not_found"
    _reload_pi("development")


# ────────────────────────────────────────────────────────────────────
# 5 · Full-boot smoke — simulate every startup step under
#     APP_ENV=production and verify no raise + no scrubber launch.
# ────────────────────────────────────────────────────────────────────
def test_production_boot_sequence_smoke():
    """Mimics the three operations in ``_preview_isolation_boot_
    audit``:
      1. ``assert_registry_coverage(app)`` — returns, does not raise.
      2. ``run_once(db)`` — returns ``{skipped: production_env}``.
      3. Healthcheck endpoint — raises 404 ``HTTPException`` on first
         request.

    This is the production-boot invariant lock. If any of these
    three fire differently from the expected behavior, boot
    time semantics have drifted."""
    _, _, sc, reg = _reload_pi("production")
    from fastapi import FastAPI, APIRouter
    from pydantic import BaseModel

    class _PIIIn(BaseModel):
        name: str
        email: str

    app = FastAPI()
    r = APIRouter()
    @r.post("/api/customers/orphan")
    async def _h(body: _PIIIn):
        return {}
    app.include_router(r)

    # 1. Registry audit — returns, does not raise.
    report = reg.assert_registry_coverage(app)
    assert isinstance(report, dict)

    # 2. Scrubber — refuses.
    import asyncio
    scrub_result = asyncio.run(sc.run_once(db=None, force=True))
    assert scrub_result["skipped"] == "production_env"
    # Scrubber must not have touched anything.
    assert scrub_result.get("scrubbed_counts") == {}

    # 3. Healthcheck — 404.
    from fastapi.testclient import TestClient
    import routers.preview_isolation_admin as mod
    importlib.reload(mod)
    app2 = FastAPI()
    app2.include_router(mod.router, prefix="/api")
    app2.dependency_overrides[mod.require_admin] = lambda: {
        "id": "u-admin", "role": "admin",
    }
    client = TestClient(app2)
    hc = client.get("/api/admin/preview-isolation-status")
    assert hc.status_code == 404
    _reload_pi("development")

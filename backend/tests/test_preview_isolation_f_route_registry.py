"""Preview isolation · P0 Stage 3 Commit F regression tests.

Pins three invariants:

1. **Registry coverage** — every route the Stage-2 tester flagged
   as "unregistered PII-shaped" is now EITHER in
   ``PII_INGRESS_REGISTRY`` or in ``_ROUTES_WITHOUT_PII_PAYLOAD``
   with a concrete 1-line justification. No orphans.

2. **Hard-fail boot on preview** — if a fake PII-shaped route is
   added to the app WITHOUT being in either list,
   ``assert_registry_coverage`` raises ``RuntimeError`` on preview
   env with a clear error message naming the orphan route path.

3. **Production never fails boot** — the same fake-orphan on
   ``APP_ENV=production`` returns a report (no raise), only logs
   a WARN. Production safety takes precedence over strict
   coverage because the decorator is a strict no-op in prod
   regardless.

Also pins the ``_assert_justifications_valid`` guard: any entry in
``_ROUTES_WITHOUT_PII_PAYLOAD`` carrying a boilerplate / empty
justification would raise at import — the test exercises this by
monkey-patching a bad entry and reloading.
"""
from __future__ import annotations

import importlib
import os
from typing import List, Tuple

import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


# ────────────────────────────────────────────────────────────────────
# Helpers.
# ────────────────────────────────────────────────────────────────────
def _reload_pi(force_env: str = "development"):
    os.environ["APP_ENV"] = force_env
    import services.preview_isolation.config as cfg
    importlib.reload(cfg)
    import services.preview_isolation.registry as reg
    importlib.reload(reg)
    return reg


# ────────────────────────────────────────────────────────────────────
# 1 · Registry has the 4 PII-ingress Commit F additions.
# ────────────────────────────────────────────────────────────────────
_COMMIT_F_INGRESS_ADDITIONS: List[Tuple[str, str]] = [
    ("POST",  "/api/lead-sense/track"),
    ("POST",  "/api/lead-sense/convert"),
    ("PATCH", "/api/signup-onboarding/step/1"),
    ("PATCH", "/api/signup-onboarding/step/3"),
]


def test_commit_f_ingress_additions_registered():
    reg = _reload_pi("development")
    registered = {(m, p) for m, p, _, _ in reg.PII_INGRESS_REGISTRY}
    for m, p in _COMMIT_F_INGRESS_ADDITIONS:
        assert (m, p) in registered, \
            f"Commit F ingress addition missing from registry: {m} {p}"


# ────────────────────────────────────────────────────────────────────
# 2 · Exemption list has all 16 PII-shaped exempt routes + each
#     carries a concrete justification.
# ────────────────────────────────────────────────────────────────────
_COMMIT_F_EXEMPT_ADDITIONS: List[Tuple[str, str]] = [
    ("POST", "/api/admin/leads/backfill-label-resolution"),
    ("POST", "/api/imports/pdf-invoice/{batch_id}/rollback"),
    ("POST", "/api/admin/migrations/customer-contacts-to-arrays"),
    ("PUT",  "/api/tenants/{tid}/settings/lead-notifications"),
    ("POST", "/api/admin/leads/{lead_id}/resend-notifications"),
    ("POST", "/api/signup/verify"),
    ("POST", "/api/signup/resend-verification"),
    ("PATCH", "/api/signup-onboarding/step/2"),
    ("PATCH", "/api/signup-onboarding/step/4"),
    ("POST", "/api/signup-onboarding/complete"),
    ("POST", "/api/leads/{lead_id}/send-sms"),
    ("POST", "/api/leads/{lead_id}/send-email"),
    ("POST", "/api/customer-portal/tos/{document_id}/accept"),
    ("POST", "/api/admin/customers/balance-audit"),
    ("POST", "/api/admin/customers/media-audit"),
    ("POST", "/api/admin/customers/service-records-audit"),
]


def test_commit_f_exempt_additions_registered():
    reg = _reload_pi("development")
    for key in _COMMIT_F_EXEMPT_ADDITIONS:
        assert key in reg._ROUTES_WITHOUT_PII_PAYLOAD, \
            f"Commit F exempt route missing from exemption list: {key}"


def test_every_exemption_has_concrete_justification():
    """Boilerplate like 'exempt' / 'safe' / 'no pii' MUST be rejected
    by the module-import guard. Justifications must be >= 25 chars."""
    reg = _reload_pi("development")
    boilerplate = {"exempt", "safe", "not pii", "no pii", "ok", "n/a"}
    for key, reason in reg._ROUTES_WITHOUT_PII_PAYLOAD.items():
        norm = (reason or "").strip().lower()
        assert norm, f"empty justification for {key}"
        assert norm not in boilerplate, f"boilerplate justification for {key}: {reason!r}"
        assert len(norm) >= 25, \
            f"justification too short for {key}: {reason!r}"


def test_justification_guard_rejects_boilerplate():
    """Add a bad entry at runtime + reload — module should raise."""
    _reload_pi("development")
    import services.preview_isolation.registry as reg
    # Patch the dict + rerun the guard.
    reg._ROUTES_WITHOUT_PII_PAYLOAD[("GET", "/api/fake")] = "exempt"
    with pytest.raises(ValueError, match="missing concrete justification"):
        reg._assert_justifications_valid()
    # Restore.
    del reg._ROUTES_WITHOUT_PII_PAYLOAD[("GET", "/api/fake")]


# ────────────────────────────────────────────────────────────────────
# 3 · Boot-time assertion — fake orphan triggers RuntimeError on
#     preview, WARN on production.
# ────────────────────────────────────────────────────────────────────
class _FakePIIIn(BaseModel):
    name: str
    email: str
    phone: str


def _mint_fake_app(route_path: str, route_method: str = "POST",
                     *, include_registered: bool = False) -> FastAPI:
    """Build a FastAPI app with an orphan PII-shaped route for the
    boot-assertion test cases.

    ``include_registered=True`` additionally stubs out every route
    in ``PII_INGRESS_REGISTRY`` so the ``missing_registered_routes``
    audit check doesn't drag the status to RED when the test case
    only wants to exercise the orphan-detection path.
    """
    app = FastAPI()
    r = APIRouter()
    # The handler shape is irrelevant — only the method + path
    # trigger the pii_hint regex check in audit_route_registry.
    if route_method == "POST":
        @r.post(route_path)
        async def _h(body: _FakePIIIn):
            return {}
    elif route_method == "PATCH":
        @r.patch(route_path)
        async def _h2(body: _FakePIIIn):
            return {}
    app.include_router(r)
    if include_registered:
        import services.preview_isolation.registry as reg
        stub_r = APIRouter()
        for m, p, _k, _s in reg.PII_INGRESS_REGISTRY:
            # Convert ``{param}`` placeholders to FastAPI's syntax
            # (same shape — no change needed).
            async def _stub():
                return {}
            if m == "POST":
                stub_r.post(p)(_stub)
            elif m == "PUT":
                stub_r.put(p)(_stub)
            elif m == "PATCH":
                stub_r.patch(p)(_stub)
        app.include_router(stub_r)
    return app


def test_preview_boot_hard_fails_on_unregistered_pii_route():
    reg = _reload_pi("development")
    app = _mint_fake_app("/api/customers/unregistered-xyz-abc")
    with pytest.raises(RuntimeError) as exc:
        reg.assert_registry_coverage(app)
    msg = str(exc.value)
    # The error must name the orphan path so the admin can act.
    assert "/api/customers/unregistered-xyz-abc" in msg
    assert "preview env" in msg
    # And it must hint at the two remediations.
    assert "PII_INGRESS_REGISTRY" in msg
    assert "_ROUTES_WITHOUT_PII_PAYLOAD" in msg


def test_production_boot_never_fails_on_unregistered_pii_route(caplog):
    reg = _reload_pi("production")
    app = _mint_fake_app("/api/customers/unregistered-xyz-abc")
    # Should NOT raise.
    import logging
    with caplog.at_level(logging.WARNING,
                           logger="services.preview_isolation.registry"):
        report = reg.assert_registry_coverage(app)
    assert report["status"] == "RED"
    assert ("registry RED" in caplog.text
            or report["unregistered_pii_shaped_routes"]), \
        "production should at least log a WARN"
    # Clean up — reload back to preview env for subsequent tests.
    _reload_pi("development")


def test_fake_route_in_exemption_list_does_not_fail_boot():
    """Add the orphan into the exemption list with a concrete
    justification — boot now passes."""
    reg = _reload_pi("development")
    key = ("POST", "/api/customers/fake-but-exempt-route")
    reg._ROUTES_WITHOUT_PII_PAYLOAD[key] = (
        "Fake test route — exemption is for the "
        "test_fake_route_in_exemption_list regression."
    )
    try:
        app = _mint_fake_app(
            "/api/customers/fake-but-exempt-route",
            include_registered=True,
        )
        # Shouldn't raise.
        report = reg.assert_registry_coverage(app)
        # The exempt route lands in exempted_pii_shaped_routes
        # (not unregistered).
        exempt_paths = {p for _, p in report.get("exempted_pii_shaped_routes", [])}
        assert "/api/customers/fake-but-exempt-route" in exempt_paths
    finally:
        del reg._ROUTES_WITHOUT_PII_PAYLOAD[key]


def test_fake_route_in_ingress_registry_does_not_fail_boot():
    """Register the orphan directly in PII_INGRESS_REGISTRY — boot
    now passes (route is covered by the sanitizer path)."""
    reg = _reload_pi("development")
    reg.PII_INGRESS_REGISTRY.append(
        ("POST", "/api/customers/fake-but-registered-route",
         "customer", "json"),
    )
    # Rebuild the compiled regex cache.
    reg._COMPILED.append((
        "POST",
        reg._pattern_to_regex("/api/customers/fake-but-registered-route"),
        "customer", "json",
    ))
    try:
        app = _mint_fake_app(
            "/api/customers/fake-but-registered-route",
            include_registered=True,
        )
        report = reg.assert_registry_coverage(app)
        # No orphan.
        orphans = {p for _, p in report["unregistered_pii_shaped_routes"]}
        assert "/api/customers/fake-but-registered-route" not in orphans
    finally:
        reg.PII_INGRESS_REGISTRY.pop()
        reg._COMPILED.pop()


# ────────────────────────────────────────────────────────────────────
# 4 · Live app sanity — the real server.app should now pass the
#     Commit F audit (registry.status GREEN).
# ────────────────────────────────────────────────────────────────────
def test_live_app_registry_status_green():
    """Smoke test — the actual running backend's audit should
    return GREEN after the Commit F additions. (If there are still
    orphan routes beyond the 20 enumerated here, Commit F is
    incomplete and this test fires.)"""
    _reload_pi("development")
    import requests
    r = requests.post("http://localhost:8001/api/auth/login",
                        json={"email": "admin@aquaterra.com",
                              "password": "password123"},
                        timeout=15)
    r.raise_for_status()
    tok = r.json()["access_token"]
    r = requests.get(
        "http://localhost:8001/api/admin/preview-isolation-status",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    assert r.status_code == 200, r.text[:400]
    reg = r.json()["registry"]
    assert reg["status"] == "GREEN", (
        f"registry still not GREEN · unregistered: "
        f"{reg['unregistered_pii_shaped_routes']}"
    )

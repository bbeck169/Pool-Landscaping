"""Phase I1.5.a · Feb-2026 — Tenant theme endpoint contract lock.

Covers:
  1. GET /api/tenants/me/theme returns ``default`` expanded when
     the tenant has never set a theme (no auto-write).
  2. PUT /api/tenants/me/theme with a valid solid theme persists +
     round-trips via GET.
  3. PUT rejects gradient in a text / small-element slot with 400.
  4. PUT rejects a low-contrast solid text/bg pair with 400.
  5. GET /api/theme-presets returns 31 presets, all validating.
  6. POST /api/tenants/me/theme/apply-preset copies the preset.
  7. POST /api/tenants/me/theme/apply-preset rejects unknown keys.
  8. PUT is admin-only (manager gets 403).
  9. Every preset in the registry passes the validator.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()
# ── Helpers ──────────────────────────────────────────────────────
def _login(email: str = "admin@aquaterra.com",
             password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password},
                        timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _get_tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def _clear_theme(tid: str) -> None:
    _sync.tenants.update_one({"id": tid}, {"$unset": {"theme": ""}})


def _valid_theme() -> dict:
    """A minimal all-solid theme that passes AA (uses the default
    palette so contrast is well over threshold)."""
    def s(hex_: str) -> dict:
        return {"mode": "solid", "solid": hex_}
    return {
        "preset": "custom",
        "menu": {"bg": s("#0f172a"), "text": s("#ffffff")},
        "rail": {"bg": s("#0f172a"), "text": s("#ffffff")},
        "tiles": {"bg": s("#ffffff"), "text": s("#0f172a"),
                    "border": s("#e5e7eb")},
        "buttons": {"bg": s("#166534"), "text": s("#ffffff")},
        "accents": {
            "primary": s("#166534"),
            "secondary": s("#0f172a"),
            "text": s("#0f172a"),
            "link": s("#0f172a"),
            "focus_ring": s("#166534"),
            "badge_bg": s("#dcfce7"),
            "badge_text": s("#14532d"),
        },
    }


# ── Tests ────────────────────────────────────────────────────────
def test_i15a_get_returns_default_expanded_when_unset():
    tok = _login()
    tid = _get_tenant_id(tok)
    _clear_theme(tid)

    r = requests.get(f"{API}/tenants/me/theme", headers=_hdrs(tok),
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preset"] == "default", body
    # Every section is present.
    for k in ("menu", "rail", "tiles", "buttons", "accents"):
        assert k in body, f"section {k!r} missing"
    # Default preset has solid dark menu bg.
    assert body["menu"]["bg"]["mode"] == "solid"
    assert body["menu"]["text"]["mode"] == "solid"

    # No auto-write: DB should still be empty.
    doc = _sync.tenants.find_one({"id": tid}, {"_id": 0, "theme": 1})
    assert doc is not None
    assert "theme" not in doc, doc


def test_i15a_put_persists_valid_theme_and_get_round_trips():
    tok = _login()
    tid = _get_tenant_id(tok)
    _clear_theme(tid)
    try:
        theme = _valid_theme()
        theme["preset"] = f"TEST_i15a_{uuid.uuid4().hex[:6]}"

        r = requests.put(f"{API}/tenants/me/theme", json=theme,
                          headers=_hdrs(tok), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["preset"] == theme["preset"]
        assert body["menu"]["bg"]["solid"] == "#0f172a"

        # GET returns the persisted theme (not the default).
        r2 = requests.get(f"{API}/tenants/me/theme", headers=_hdrs(tok),
                            timeout=15)
        assert r2.status_code == 200
        assert r2.json()["preset"] == theme["preset"]

        # DB row was stamped with audit meta.
        doc = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert doc.get("theme_updated_at")
        assert doc.get("theme_updated_by")
    finally:
        _clear_theme(tid)


def test_i15a_put_rejects_gradient_in_text_slot():
    tok = _login()
    tid = _get_tenant_id(tok)
    _clear_theme(tid)

    theme = _valid_theme()
    # Text slots are solid-only. Sneak a gradient into menu.text.
    theme["menu"]["text"] = {
        "mode": "gradient",
        "gradient": {"from": "#000000", "to": "#ffffff", "angle": 45},
    }

    r = requests.put(f"{API}/tenants/me/theme", json=theme,
                      headers=_hdrs(tok), timeout=15)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "GRADIENT_NOT_ALLOWED", detail
    assert "menu.text" in (detail.get("path") or "")

    # DB unchanged.
    doc = _sync.tenants.find_one({"id": tid}, {"_id": 0, "theme": 1})
    assert doc is not None
    assert "theme" not in doc


def test_i15a_put_rejects_low_contrast_text_bg():
    tok = _login()
    tid = _get_tenant_id(tok)
    _clear_theme(tid)

    theme = _valid_theme()
    # Light gray on white → ~1.6:1 ratio, well below AA 4.5:1.
    theme["tiles"]["bg"] = {"mode": "solid", "solid": "#ffffff"}
    theme["tiles"]["text"] = {"mode": "solid", "solid": "#cccccc"}

    r = requests.put(f"{API}/tenants/me/theme", json=theme,
                      headers=_hdrs(tok), timeout=15)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "CONTRAST_FAIL", detail
    # Friendly message mentions WCAG + guidance.
    msg = detail.get("message") or ""
    assert "WCAG" in msg or "contrast" in msg.lower(), msg


def test_i15a_get_theme_presets_returns_31_and_all_validate():
    tok = _login()
    r = requests.get(f"{API}/theme-presets", headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    presets = body.get("presets") or []
    assert len(presets) == 31, f"expected 31 presets, got {len(presets)}"

    keys = [p["key"] for p in presets]
    for required in ("default", "pool_landscape", "pool", "landscape",
                       "hvac", "plumbing", "electrical"):
        assert required in keys, f"missing {required!r}"

    # Every preset returned round-trips through PUT (validator
    # accepts them). Uses the admin token; each PUT overwrites.
    tid = _get_tenant_id(tok)
    _clear_theme(tid)
    try:
        for entry in presets:
            r2 = requests.put(f"{API}/tenants/me/theme",
                                 json=entry["theme"],
                                 headers=_hdrs(tok), timeout=15)
            assert r2.status_code == 200, \
                f"preset {entry['key']!r} rejected: {r2.text}"
    finally:
        _clear_theme(tid)


def test_i15a_apply_preset_persists_selected():
    tok = _login()
    tid = _get_tenant_id(tok)
    _clear_theme(tid)
    try:
        r = requests.post(
            f"{API}/tenants/me/theme/apply-preset",
            json={"key": "pool"},
            headers=_hdrs(tok), timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["preset"] == "pool"
        # Persisted.
        r2 = requests.get(f"{API}/tenants/me/theme", headers=_hdrs(tok),
                            timeout=15)
        assert r2.json()["preset"] == "pool"
    finally:
        _clear_theme(tid)


def test_i15a_apply_preset_rejects_unknown_key():
    tok = _login()
    r = requests.post(
        f"{API}/tenants/me/theme/apply-preset",
        json={"key": "not_a_real_preset_xyz"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "UNKNOWN_PRESET", detail


def test_i15a_put_is_admin_only():
    tok = _login(email="manager@aquaterra.com")
    r = requests.put(f"{API}/tenants/me/theme", json=_valid_theme(),
                      headers=_hdrs(tok), timeout=15)
    assert r.status_code == 403, r.text


def test_i15a_presets_all_pass_aa():
    """Direct-module smoke: every preset in the in-code registry
    passes the validator. Locks the module so a future palette
    tweak that regresses AA fails the suite loudly."""
    from services.theme.presets import PRESETS
    from services.theme.validate import validate_theme_payload
    for key, theme in PRESETS.items():
        # Raises on any violation.
        clean = validate_theme_payload(theme)
        assert clean["preset"] == key, (key, clean["preset"])


# ══════════════════════════════════════════════════════════════
# Phase I1.5.b — Shadow preview endpoint
# ══════════════════════════════════════════════════════════════
def test_i15b_preview_returns_valid_for_good_theme():
    tok = _login()
    r = requests.post(f"{API}/tenants/me/theme/preview",
                        json=_valid_theme(),
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["errors"] == []


def test_i15b_preview_reports_gradient_on_text_slot():
    tok = _login()
    theme = _valid_theme()
    theme["menu"]["text"] = {
        "mode": "gradient",
        "gradient": {"from": "#000000", "to": "#ffffff", "angle": 90},
    }
    r = requests.post(f"{API}/tenants/me/theme/preview",
                        json=theme,
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False
    errs = body["errors"]
    codes = [e["code"] for e in errs]
    assert "GRADIENT_NOT_ALLOWED" in codes, errs


def test_i15b_preview_collects_multiple_contrast_failures():
    """The whole point of the preview endpoint: report every failing
    contrast pair at once instead of forcing the admin to fix them
    one at a time. Deliberately break two pairs and expect two
    CONTRAST_FAIL entries."""
    tok = _login()
    theme = _valid_theme()
    # Pair 1: tiles.text on tiles.bg (white on light gray → fails)
    theme["tiles"]["bg"] = {"mode": "solid", "solid": "#ffffff"}
    theme["tiles"]["text"] = {"mode": "solid", "solid": "#dddddd"}
    # Pair 2: buttons.text on buttons.bg (also white on light)
    theme["buttons"]["bg"] = {"mode": "solid", "solid": "#eeeeee"}
    theme["buttons"]["text"] = {"mode": "solid", "solid": "#ffffff"}

    r = requests.post(f"{API}/tenants/me/theme/preview",
                        json=theme,
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False
    contrast_errs = [e for e in body["errors"]
                       if e["code"] == "CONTRAST_FAIL"]
    assert len(contrast_errs) >= 2, body["errors"]
    # computed_ratio must be present on every contrast error.
    for e in contrast_errs:
        assert "computed_ratio" in e
        assert isinstance(e["computed_ratio"], (int, float))


def test_i15b_preview_is_admin_only():
    tok = _login(email="manager@aquaterra.com")
    r = requests.post(f"{API}/tenants/me/theme/preview",
                        json=_valid_theme(),
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 403, r.text


def test_i15b_preview_never_persists():
    """Preview must be side-effect-free: even a valid payload must
    not update tenant.theme."""
    tok = _login()
    tid = _get_tenant_id(tok)
    _clear_theme(tid)
    theme = _valid_theme()
    theme["preset"] = f"TEST_i15b_no_persist_{uuid.uuid4().hex[:6]}"

    r = requests.post(f"{API}/tenants/me/theme/preview",
                        json=theme,
                        headers=_hdrs(tok), timeout=15)
    assert r.status_code == 200 and r.json()["valid"] is True

    doc = _sync.tenants.find_one({"id": tid}, {"_id": 0, "theme": 1})
    assert doc is not None
    assert "theme" not in doc, "preview must not persist"

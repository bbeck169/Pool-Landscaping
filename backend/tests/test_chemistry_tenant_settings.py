"""Sprint 3b · Feb-2026 — Tenant chemistry settings endpoint tests.

Covers:
    * GET/PATCH /api/tenants/mine/settings/chemistry (targets + gate_mode)
    * GET/PATCH /api/tenants/mine/settings/chemistry/dosing-formulas
    * POST /api/chemistry/dose/preview
    * Backfill migration (dry-run + real-run + idempotency)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email: str, password: str = "password123") -> Dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')['access_token']}"}


@pytest.fixture(autouse=True)
def _cleanup_chem_settings(dbc):
    """Ensure aquaterra starts each test with defaults so PATCHes
    are deterministic. Restores after the test regardless of outcome.
    """
    ten = dbc.tenants.find_one({"slug": "aquaterra"})
    assert ten
    original = ((ten.get("settings") or {}).get("chemistry")) or None
    dbc.tenants.update_one(
        {"id": ten["id"]},
        {"$unset": {"settings.chemistry": ""}},
    )
    yield
    if original is not None:
        dbc.tenants.update_one(
            {"id": ten["id"]},
            {"$set": {"settings.chemistry": original}},
        )
    else:
        dbc.tenants.update_one(
            {"id": ten["id"]},
            {"$unset": {"settings.chemistry": ""}},
        )


# ─── GET /settings/chemistry ────────────────────────────────────────
def test_get_chemistry_returns_az_defaults(admin_h):
    r = requests.get(f"{API}/tenants/mine/settings/chemistry",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["gate_mode"] == "strict"
    targets = body["targets"]
    for k in ("chlorine", "ph", "alkalinity", "cyanuric_acid",
                "calcium_hardness", "salt"):
        assert k in targets
    assert targets["chlorine"]["min"] == 1.0
    assert targets["chlorine"]["max"] == 3.0
    assert targets["chlorine"]["unit"] == "ppm"
    assert targets["ph"]["min"] == 7.2
    assert targets["ph"]["max"] == 7.6
    assert targets["salt"]["max"] == 3400.0
    # Outer bounds surfaced for UI validation.
    assert "outer_bounds" in body
    assert body["outer_bounds"]["salt"] == [0.0, 6000.0]


def test_get_chemistry_forbidden_for_tech(tech_h):
    r = requests.get(f"{API}/tenants/mine/settings/chemistry",
                      headers=tech_h, timeout=15)
    assert r.status_code == 403


# ─── PATCH /settings/chemistry (targets) ────────────────────────────
def test_patch_chemistry_targets_partial_update(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"targets": {"chlorine": {"min": 1.5, "max": 4.0}}},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["targets"]["chlorine"]["min"] == 1.5
    assert body["targets"]["chlorine"]["max"] == 4.0
    # Other rows untouched at defaults.
    assert body["targets"]["ph"]["min"] == 7.2


def test_patch_chemistry_gate_mode(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"gate_mode": "warn_only"},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["gate_mode"] == "warn_only"


def test_patch_chemistry_rejects_min_ge_max(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"targets": {"ph": {"min": 8.0, "max": 7.0}}},
        timeout=15,
    )
    assert r.status_code == 400
    body = r.json()
    # FastAPI wraps HTTPException detail under {"detail": {...}}
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "chemistry_target_invalid"
    assert detail.get("field") == "ph"


def test_patch_chemistry_rejects_out_of_bounds(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"targets": {"chlorine": {"min": 0, "max": 25}}},
        timeout=15,
    )
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "chemistry_target_out_of_bounds"
    assert detail.get("field") == "chlorine"
    assert detail.get("allowed") == {"min": 0.0, "max": 10.0}


def test_patch_chemistry_salt_wide_bounds_accepted(admin_h):
    """Salt-system tenants use wide ranges — verify the outer bounds
    accept a legitimate 3000-3500 config."""
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"targets": {"salt": {"min": 3000, "max": 3500}}},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["targets"]["salt"]["min"] == 3000
    assert r.json()["targets"]["salt"]["max"] == 3500


def test_patch_chemistry_rejects_unknown_chemical_key(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"targets": {"phosphates": {"min": 0, "max": 100}}},
        timeout=15,
    )
    # Pydantic-level rejection on the extra-forbidden model shape
    # OR chemistry_target_unknown_key on validate_targets_patch —
    # either way it's a 422/400.
    assert r.status_code in (400, 422)


def test_patch_chemistry_rejects_invalid_gate_mode(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry",
        headers=admin_h,
        json={"gate_mode": "chaos_mode"},
        timeout=15,
    )
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "chemistry_gate_mode_invalid"


# ─── Dosing formulas ────────────────────────────────────────────────
def test_get_dosing_formulas_returns_defaults(admin_h):
    r = requests.get(
        f"{API}/tenants/mine/settings/chemistry/dosing-formulas",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["allowed_functions"]) == {"abs", "min", "max", "round"}
    assert "current" in body["allowed_names"]
    assert body["formulas"]["ph_up"]["using_default"] is True
    assert body["formulas"]["ph_up"]["default_formula"].startswith("round(max(0")


def test_patch_dosing_formula_happy_path(admin_h):
    formula = "max(0, (avg_target - current) * volume_gallons * 0.00013)"
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry/dosing-formulas",
        headers=admin_h,
        json={"chlorine": formula},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["formulas"]["chlorine"]["tenant_formula"] == formula
    assert body["formulas"]["chlorine"]["using_default"] is False


def test_patch_dosing_formula_rejects_bad_syntax(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry/dosing-formulas",
        headers=admin_h,
        json={"ph_up": "(2 + )"},
        timeout=15,
    )
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "chemistry_formula_invalid"
    assert detail.get("field") == "ph_up"


def test_patch_dosing_formula_rejects_unsafe(admin_h):
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry/dosing-formulas",
        headers=admin_h,
        json={"ph_up": "__import__('os').system('ls')"},
        timeout=15,
    )
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "chemistry_formula_invalid"


def test_patch_dosing_formula_empty_clears_override(admin_h):
    # first set a custom formula
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry/dosing-formulas",
        headers=admin_h,
        json={"ph_up": "1 + 2"},
        timeout=15,
    )
    assert r.status_code == 200
    # then clear it
    r = requests.patch(
        f"{API}/tenants/mine/settings/chemistry/dosing-formulas",
        headers=admin_h,
        json={"ph_up": ""},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["formulas"]["ph_up"]["using_default"] is True


# ─── Preview endpoint ───────────────────────────────────────────────
def test_dose_preview_happy_path(admin_h):
    r = requests.post(
        f"{API}/chemistry/dose/preview",
        headers=admin_h,
        json={"chemical": "chlorine", "current": 1.0,
              "volume_gallons": 10000},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["evaluation_ok"] is True
    assert body["source"] == "az_default"
    # AZ default chlorine formula on low-season inputs → 0.04
    assert body["recommended_dose_oz"] == 0.04


def test_dose_preview_with_custom_formula(admin_h):
    r = requests.post(
        f"{API}/chemistry/dose/preview",
        headers=admin_h,
        json={
            "chemical": "chlorine", "current": 1.0,
            "volume_gallons": 10000,
            "formula": "max(0, (avg_target - current) * volume_gallons * 0.00013)",
        },
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["evaluation_ok"] is True
    assert body["source"] == "tenant"
    assert abs(body["recommended_dose_oz"] - 1.3) < 1e-6


def test_dose_preview_rejects_bad_formula(admin_h):
    r = requests.post(
        f"{API}/chemistry/dose/preview",
        headers=admin_h,
        json={"chemical": "ph_up", "current": 7.0,
              "volume_gallons": 10000, "formula": "(2 + )"},
        timeout=15,
    )
    assert r.status_code == 400


def test_dose_preview_forbidden_for_tech(tech_h):
    r = requests.post(
        f"{API}/chemistry/dose/preview",
        headers=tech_h,
        json={"chemical": "chlorine", "current": 1.0,
              "volume_gallons": 10000},
        timeout=15,
    )
    assert r.status_code == 403


# ─── Admin backfill endpoint ────────────────────────────────────────
def test_admin_backfill_dry_run_returns_counts(super_h, dbc):
    r = requests.post(
        f"{API}/admin/chemistry/backfill-tenant-defaults?dry_run=true",
        headers=super_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("dry_run") is True
    assert "counts" in body
    assert "total_writes" in body


def test_admin_backfill_forbidden_for_admin(admin_h):
    r = requests.post(
        f"{API}/admin/chemistry/backfill-tenant-defaults?dry_run=true",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 403


def test_admin_backfill_idempotent(super_h, dbc):
    # dry-run counts should decrease on the second call after a real
    # run (the previous dry-run didn't write, so we do a real one).
    r1 = requests.post(
        f"{API}/admin/chemistry/backfill-tenant-defaults?dry_run=false",
        headers=super_h, timeout=30,
    )
    assert r1.status_code == 200
    r2 = requests.post(
        f"{API}/admin/chemistry/backfill-tenant-defaults?dry_run=true",
        headers=super_h, timeout=30,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    # After a real backfill, every guard is now satisfied — zero
    # writes on the next dry-run.
    assert body2["total_writes"] == 0

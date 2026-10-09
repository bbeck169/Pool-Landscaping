"""Phase 14A · Feb-2026 — ``cad_overlay`` form_type decommission.

Pins:
  1. ``cad_overlay`` is no longer in the backend ``FORM_TYPES`` enum.
  2. ``cad_overlay`` is no longer in the ``_SEED_MAP``.
  3. ``GET /api/form-templates/cad_overlay`` returns 400 / 404 (not a
     200 with the placeholder seed).

Fixed with a lightweight import check + a live HTTP probe.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values


_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def test_cad_overlay_absent_from_form_types_enum():
    """Import check — the module-level ``FORM_TYPES`` tuple must not
    carry ``cad_overlay`` any more."""
    from routers import form_templates
    assert "cad_overlay" not in form_templates.FORM_TYPES, (
        f"cad_overlay still in FORM_TYPES: {form_templates.FORM_TYPES}"
    )
    # Pin the exact post-drop membership so a future accidental
    # re-add fires the ratchet.
    assert set(form_templates.FORM_TYPES) == {
        "pool_service_report", "landscape_service_report",
        "job_checklist_pool", "job_checklist_landscape",
        "job_checklist_generic",
        "estimate", "invoice",
    }


def test_cad_overlay_absent_from_seed_map():
    """``_SEED_MAP`` must no longer carry ``cad_overlay`` so lazy-
    init cannot resurrect the dropped form_type."""
    from routers import form_templates
    assert "cad_overlay" not in form_templates._SEED_MAP


def test_cad_overlay_get_returns_400_or_404(admin_h):
    """Live HTTP probe — the backend must reject a GET for the
    dropped form_type (FastAPI enum validation returns 422 for
    a string that doesn't match the Literal; a 400/404 is also
    acceptable depending on router shape)."""
    r = requests.get(f"{API}/form-templates/cad_overlay",
                     headers=admin_h, timeout=20)
    assert r.status_code in (400, 404, 422), r.text
    assert "cad_overlay" in r.text or "form_type" in r.text.lower() \
        or "not found" in r.text.lower() or "unprocessable" in r.text.lower()

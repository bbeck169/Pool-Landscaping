"""Feb-2026 · CUS-Marketing-Form-Builder Phase 5 (α-delta) pytest.

Pytest coverage for the four new ``theme`` fields added on top of the
shipped K34 + Phase-2 contract:
  * ``theme.layout.container`` ∈ {left, centered, mixed} or null
  * ``theme.layout.header``    ∈ {left_title, full_banner} or null
  * ``theme.font.size_scale``  ∈ {xs, sm, md, lg, xl, xxl} or null
  * ``theme.wallpaper.image_url``  str or null (full-bleed bg)
  * ``theme.banner.image_url``     str or null (header band)

Mirrors ``test_k34_form_theme.py`` posture — HTTP against the live
backend + pymongo sync for DB assertions.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from tests._shared_mongo import shared_db as _shared_db


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()


def _login() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


_PFX = "TESTfbp5_"


def _wipe():
    _sync.marketing_forms.delete_many({"name": {"$regex": f"^{_PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _wipe()
    yield
    _wipe()


def _theme_full_phase5():
    """A theme carrying ALL four Phase-5 fields set to valid
    values + the shipped K34 + Phase-2 fields untouched. The
    load-bearing round-trip fixture."""
    return {
        "preset": "modern_blue",
        "colors": {
            "primary": "#2563eb", "background": "#ffffff",
            "text": "#111827", "border": "#e5e7eb",
            "accent": "#3b82f6",
        },
        "font_family": "system-ui, sans-serif",
        "gradient": None,
        "overlay_opacity": None,
        # ── Phase 5 ──────────────────────────────────────────
        "layout": {"container": "centered", "header": "full_banner"},
        "font": {"size_scale": "lg"},
        "wallpaper": {"image_url": "https://cdn.test/wallpaper.jpg"},
        "banner": {"image_url": "https://cdn.test/banner.png"},
    }


def _base_form_body():
    return {
        "name": f"{_PFX}form_{uuid.uuid4().hex[:8]}",
        "fields": [{"name": "name", "label": "Name", "type": "text"}],
    }


# ═══════════════════════════════════════════════════════════════════
# §1 · Round-trip — all four Phase-5 fields persist on POST + GET
# ═══════════════════════════════════════════════════════════════════
def test_phase5_theme_round_trips_on_create_and_get():
    tok = _login()
    body = _base_form_body()
    body["theme"] = _theme_full_phase5()
    r = requests.post(f"{API}/admin/forms", json=body,
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 201, r.text
    fid = r.json()["id"]

    r = requests.get(f"{API}/admin/forms/{fid}",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200, r.text
    got_theme = r.json()["theme"]
    assert got_theme["layout"] == {"container": "centered", "header": "full_banner"}
    assert got_theme["font"] == {"size_scale": "lg"}
    assert got_theme["wallpaper"] == {"image_url": "https://cdn.test/wallpaper.jpg"}
    assert got_theme["banner"] == {"image_url": "https://cdn.test/banner.png"}
    # K34 + Phase-2 fields untouched.
    assert got_theme["preset"] == "modern_blue"
    assert got_theme["colors"]["primary"] == "#2563eb"
    assert got_theme["gradient"] is None
    assert got_theme["overlay_opacity"] is None


# ═══════════════════════════════════════════════════════════════════
# §2 · PATCH — Phase-5 fields replace the whole theme payload
# ═══════════════════════════════════════════════════════════════════
def test_phase5_theme_patch_updates_persisted_values():
    tok = _login()
    r = requests.post(
        f"{API}/admin/forms",
        json={**_base_form_body(), "theme": {"preset": "modern_blue"}},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    fid = r.json()["id"]

    new_theme = _theme_full_phase5()
    new_theme["layout"]["container"] = "mixed"
    new_theme["font"]["size_scale"] = "xxl"
    r = requests.patch(
        f"{API}/admin/forms/{fid}", json={"theme": new_theme},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    got = r.json()["theme"]
    assert got["layout"]["container"] == "mixed"
    assert got["layout"]["header"] == "full_banner"
    assert got["font"]["size_scale"] == "xxl"
    assert got["wallpaper"]["image_url"] == "https://cdn.test/wallpaper.jpg"


# ═══════════════════════════════════════════════════════════════════
# §3 · Legacy forms — missing Phase-5 fields coerce to null defaults
# ═══════════════════════════════════════════════════════════════════
def test_phase5_legacy_theme_without_new_fields_stays_untouched():
    """A theme that only carries K34 + Phase-2 fields must round-
    trip BYTE-IDENTICAL (no fabricated Phase-5 defaults). Protects
    the shipped K34 contract: existing forms render with the exact
    pre-Phase-5 shape. The renderer-side pad is the FE
    ``coerceTheme``; the BE never pads."""
    tok = _login()
    legacy_theme = {
        "preset": "warm_earth",
        "colors": {
            "primary": "#b45309", "background": "#fdf8f2",
            "text": "#292524", "border": "#e7d9c4",
            "accent": "#d97706",
        },
        "font_family": "Georgia, serif",
    }
    r = requests.post(
        f"{API}/admin/forms",
        json={**_base_form_body(), "theme": legacy_theme},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 201, r.text
    got = r.json()["theme"]
    # Phase-5 keys MUST NOT be present on a legacy theme — the
    # whole point of the absence posture is K34 byte-identity.
    assert "layout" not in got, (
        f"Phase-5 key fabricated on legacy theme: layout={got.get('layout')!r}"
    )
    assert "font" not in got
    assert "wallpaper" not in got
    assert "banner" not in got
    # K34 fields intact.
    assert got["preset"] == "warm_earth"
    assert got["colors"]["primary"] == "#b45309"


# ═══════════════════════════════════════════════════════════════════
# §4 · Invalid enum values coerce to null (never 422)
# ═══════════════════════════════════════════════════════════════════
def test_phase5_invalid_enum_values_coerce_to_null():
    """Bad enum values from an outdated client must coerce to
    ``None`` rather than 422. Protects against FE-ahead-of-BE
    rollouts where a new enum literal lands on the FE before the
    BE accepts it. The theme save goes through, the bad field
    renders as "not set"."""
    tok = _login()
    bad_theme = {
        "preset": "modern_blue",
        "layout": {"container": "DIAGONAL_FLIP", "header": "weird"},
        "font": {"size_scale": "cosmic"},
        "wallpaper": {"image_url": ""},  # empty → null
        "banner": {"image_url": 42},     # non-string → null
    }
    r = requests.post(
        f"{API}/admin/forms",
        json={**_base_form_body(), "theme": bad_theme},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 201, r.text
    got = r.json()["theme"]
    assert got["layout"] == {"container": None, "header": None}
    assert got["font"] == {"size_scale": None}
    assert got["wallpaper"] is None
    assert got["banner"] is None


# ═══════════════════════════════════════════════════════════════════
# §5 · Phase-5 fields don't collide with hero image contract
# ═══════════════════════════════════════════════════════════════════
def test_phase5_image_slots_are_distinct_from_hero():
    """The two new image slots (wallpaper + banner) must land on
    the ``theme`` dict — NOT clobber the shipped ``hero.background``
    URL on the sibling ``hero`` dict. This is the test that stops
    a future "unify them" refactor from accidentally merging the
    two schemas."""
    tok = _login()
    body = _base_form_body()
    body["theme"] = {
        "wallpaper": {"image_url": "https://cdn.test/wall.jpg"},
        "banner": {"image_url": "https://cdn.test/band.jpg"},
    }
    body["hero"] = {
        "heading_html": "<p>Hi</p>",
        "background": {
            "kind": "image",
            "url": "https://cdn.test/hero.jpg",
            "overlay_opacity": 30,
        },
    }
    r = requests.post(f"{API}/admin/forms", json=body,
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 201, r.text
    got = r.json()
    # Three distinct URLs on three distinct slots.
    assert got["theme"]["wallpaper"]["image_url"] == "https://cdn.test/wall.jpg"
    assert got["theme"]["banner"]["image_url"] == "https://cdn.test/band.jpg"
    assert got["hero"]["background"]["url"] == "https://cdn.test/hero.jpg"

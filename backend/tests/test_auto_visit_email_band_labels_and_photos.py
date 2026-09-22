"""Phase COMM1 · Feb-2026 — Auto-visit email band labels + brand
palette + tech photo grid.

Locks in:
  * The Required Four render as bands (Below Average / Average /
    Above Average / Elevated) with the numeric value as a small
    muted subtitle.
  * Optional readings render as plain values (no band label).
  * ``branding`` dict supplies the header/section/CTA colors;
    fallback palette kicks in when unset.
  * ``photos`` grid caps at 6, shows a "+N more in your report"
    link when overflow, and is omitted entirely when zero photos.

Pure unit tests — hit ``render_email`` directly, no DB or HTTP.
"""
from __future__ import annotations

from services.auto_visit_email import render_email, _resolve_palette


# ═════════════════════════════════════════════════════════════════════
# Band labels
# ═════════════════════════════════════════════════════════════════════
def test_required_four_render_as_bands_with_numeric_subtitle():
    tenant = {"name": "Test Tenant",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j1", "customer_id": "c1",
           "address": "1 Palm Ave", "service_type": "pool"}
    sr = {
        "id": "sr1", "kind": "pool", "tech_name": "Mike",
        "chemical_readings": [
            {"key": "free_chlorine", "value": 3.5, "unit": "ppm"},
            {"key": "ph",            "value": 7.5},
            {"key": "alkalinity",    "value": 90,  "unit": "ppm"},
            {"key": "cyanuric_acid", "value": 45,  "unit": "ppm"},
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    # Every Required Four band label appears at least once.
    assert "Average" in html
    # Band + numeric subtitle both present.
    assert "3.5" in html  # numeric subtitle
    assert "ppm"  in html
    # Redundancy sanity — none of the bands leak the wrong reading.
    # Chlorine 3.5 → Average (avg band = 1..5).
    assert "Below Average" not in html  # nothing was <1 here
    # Text fallback also carries the band name for accessibility.
    # Phase P17.1 · Feb-2026 — canonical rename: DISPLAY_LABELS now
    # emits ``"Chlorine"`` (was ``"Free Cl"`` under P17).
    assert "Chlorine" in out["text"]
    assert "Average" in out["text"]


def test_below_average_and_elevated_bands_render_correctly():
    """Sanity across the four Required Four bands — extreme values."""
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr = {
        "id": "sr", "kind": "pool",
        "chemical_readings": [
            {"key": "free_chlorine", "value": 12},   # Elevated
            {"key": "ph",            "value": 6.9},  # Below Average
            {"key": "alkalinity",    "value": 130},  # Above Average
            {"key": "cyanuric_acid", "value": 45},   # Average
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    assert "Elevated"      in html
    assert "Below Average" in html
    assert "Above Average" in html
    assert "Average"       in html


def test_optional_readings_render_plain_no_band_label():
    """Water temp is not a banded key — should render as plain value
    (never carries a band label + subtitle)."""
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr = {
        "id": "sr", "kind": "pool",
        "chemical_readings": [
            {"key": "water_temp", "value": 82, "unit": "°F"},
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    # Value renders …
    assert "82" in html
    # … but a band label does NOT surface for this key.
    # (Belt-and-braces: no chemistry_bands classification means the
    # "Average · N ppm" subtitle string never fires.)
    assert "Average · 82" not in html
    assert "Above Average · 82" not in html


# ═════════════════════════════════════════════════════════════════════
# Brand palette
# ═════════════════════════════════════════════════════════════════════
def test_branding_applies_primary_hex_to_header_bar():
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr  = {"id": "sr", "kind": "pool", "chemical_readings": []}
    out = render_email(tenant, job, sr, {"email": "c@x.com"},
                        branding={"brand_primary_hex": "#0f172a"})
    html = out["html"]
    # Header bar background carries the tenant primary hex.
    assert "background:#0f172a" in html.lower()
    assert 'bgcolor="#0f172a"' in html.lower()


def test_branding_falls_back_to_default_palette_when_unset():
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr  = {"id": "sr", "kind": "pool", "chemical_readings": []}
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    # Default primary is #0B4A6F (matches services.email.theming).
    assert "#0b4a6f" in html.lower()


def test_resolve_palette_prefers_effective_over_raw_keys():
    """``_resolve_palette`` accepts both the effective shape
    (``brand_primary_hex``) and the raw tenant shape (``brand_primary``);
    validates the primary-key precedence."""
    pal = _resolve_palette({
        "brand_primary": "#111111",
        "brand_primary_hex": "#222222",
    })
    assert pal["primary"] == "#222222"


# ═════════════════════════════════════════════════════════════════════
# Photo grid
# ═════════════════════════════════════════════════════════════════════
def test_three_photos_render_all_three_in_grid():
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr  = {
        "id": "sr", "kind": "pool", "chemical_readings": [],
        "photos": [
            {"url": "https://ex.com/p1.jpg", "taken_at": "2025-11-04T15:30:00Z"},
            {"url": "https://ex.com/p2.jpg", "taken_at": "2025-11-04T15:31:00Z"},
            {"url": "https://ex.com/p3.jpg", "taken_at": "2025-11-04T15:32:00Z"},
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    assert "Visit photos" in html
    for url in ("p1.jpg", "p2.jpg", "p3.jpg"):
        assert url in html
    # No overflow link.
    assert "+" not in html or "more in your report" not in html


def test_zero_photos_omits_grid_section_entirely():
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr  = {"id": "sr", "kind": "pool", "chemical_readings": [], "photos": []}
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    assert "Visit photos" not in out["html"]


def test_eight_photos_render_six_thumbnails_plus_overflow_link():
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    photos = [
        {"url": f"https://ex.com/p{i}.jpg",
         "taken_at": f"2025-11-04T15:{i:02d}:00Z"}
        for i in range(8)
    ]
    sr = {"id": "sr", "kind": "pool", "chemical_readings": [], "photos": photos}
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    # Newest first — the top-6 render.
    for i in (7, 6, 5, 4, 3, 2):
        assert f"p{i}.jpg" in html
    # Oldest two are NOT in the grid.
    for i in (0, 1):
        assert f"p{i}.jpg" not in html
    assert "+2 more in your report" in html


def test_photo_grid_omits_internal_tagged_photos():
    """Redaction contract carried over from Phase 56.20 — internal
    photos never surface in the customer email."""
    tenant = {"name": "T",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j", "customer_id": "c", "address": "x", "service_type": "pool"}
    sr  = {
        "id": "sr", "kind": "pool", "chemical_readings": [],
        "photos": [
            {"url": "https://ex.com/public.jpg"},
            {"url": "https://ex.com/internal.jpg", "tags": ["internal"]},
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    html = out["html"]
    assert "public.jpg" in html
    assert "internal.jpg" not in html

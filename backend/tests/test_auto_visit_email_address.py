"""Feb-2026 · Part 1 · Auto-visit-email address resolution.

Regression coverage for the visit-summary email address bug.
Before this fix ``render_email`` read ``job.address`` directly —
a text string copied at job-generation time.  After a customer
moves (or after the property is corrected post-hoc) the email
body kept showing the stale address.

The fix looks up the property in ``db.properties`` via the FK
ladder ``job.property_id`` → ``customer.primary_property_id`` →
text-fallback, and stamps the CURRENT composed address into the
email body.  This suite locks:

* ``property_id`` on the job → composed address wins over stale
  ``job.address``.
* Property edited AFTER the job was generated → email uses the
  edited (current) address.
* Missing ``property_id`` AND missing
  ``customer.primary_property_id`` → falls back to
  ``job.address`` + emits the structured warning.
* Soft-deleted property → falls back + warning.
* Cross-tenant lookup → returns None → falls back + warning
  (never leaks tenant B's property text into a tenant A email).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from services import auto_visit_email as ave


TENANT_A = "tenant-A-avE"
TENANT_B = "tenant-B-avE"


# ═══════════════════════════════════════════════════════════════════
# In-memory Mongo stub (motor-compatible enough for this suite).
# ═══════════════════════════════════════════════════════════════════
class _Coll:
    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    async def find_one(self, query: Dict[str, Any], projection=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()):
                return dict(r)
        return None

    async def update_one(self, filt, update):
        for r in self.rows:
            if all(r.get(k) == v for k, v in filt.items()):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        # Support dot-notation for nested fields —
                        # the real Motor driver does; our tests need
                        # to mirror that so they can edit
                        # ``address.line1`` in-place.
                        if "." in k:
                            head, *rest = k.split(".")
                            cur = r.setdefault(head, {})
                            for part in rest[:-1]:
                                cur = cur.setdefault(part, {})
                            cur[rest[-1]] = v
                        else:
                            r[k] = v
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()


class _DB:
    def __init__(self, properties=None, customers=None):
        self.properties = _Coll(properties)
        self.customers = _Coll(customers)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════
def _property(pid: str, tenant_id: str, line1: str, city: str,
              state: str, postal: str, **extra) -> Dict[str, Any]:
    doc = {
        "id": pid, "tenant_id": tenant_id,
        "address": {"line1": line1, "line2": None, "city": city,
                    "state": state, "postal_code": postal,
                    "country": "US"},
    }
    doc.update(extra)
    return doc


def _seed(monkeypatch, properties=None, customers=None) -> _DB:
    fake = _DB(properties=properties, customers=customers)
    monkeypatch.setattr(ave, "db", fake)
    return fake


def _tenant(tid: str = TENANT_A) -> Dict[str, Any]:
    return {"id": tid, "name": tid}


# ═══════════════════════════════════════════════════════════════════
# 1 · Happy path — property_id on job wins over stale job.address.
# ═══════════════════════════════════════════════════════════════════
def test_property_address_wins_over_stale_job_address(monkeypatch):
    _seed(monkeypatch, properties=[
        _property("p-1", TENANT_A, "3112 W Adobe Dam Rd",
                    "Phoenix", "AZ", "85027"),
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-1",
        "address": "STALE 5207 West Bajada Road, Phoenix, AZ, 85083",
    }
    resolved = _run(ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "3112 W Adobe Dam Rd, Phoenix, AZ 85027"
    assert "Bajada" not in resolved  # stale text never wins
    assert "STALE" not in resolved


# ═══════════════════════════════════════════════════════════════════
# 2 · Property edited after job generation → email uses the CURRENT
# address, not whatever was denormalized onto the job.
# ═══════════════════════════════════════════════════════════════════
def test_property_edited_post_job_generation_uses_current(monkeypatch):
    fake = _seed(monkeypatch, properties=[
        _property("p-1", TENANT_A, "OLD line1",
                    "Phoenix", "AZ", "85027"),
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-1",
        "address": "OLD line1, Phoenix, AZ, 85027",
    }
    # Simulate an admin editing the property AFTER the job doc was
    # written (recurring generator or ad-hoc PATCH).
    _run(fake.properties.update_one(
        {"id": "p-1"},
        {"$set": {"address.line1": "3112 W Adobe Dam Rd"}},
    ))
    resolved = _run(ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "3112 W Adobe Dam Rd, Phoenix, AZ 85027"


# ═══════════════════════════════════════════════════════════════════
# 3 · Missing property_id → warning + text fallback.
# ═══════════════════════════════════════════════════════════════════
def test_missing_property_id_warns_and_falls_back(monkeypatch, caplog):
    _seed(monkeypatch, properties=[], customers=[
        {"id": "c-1", "tenant_id": TENANT_A,
         "primary_property_id": None},
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": None,
        "address": "123 Fallback St, Phoenix, AZ, 85001",
    }
    with caplog.at_level(logging.WARNING, logger="server_api"):
        resolved = _run(
            ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "123 Fallback St, Phoenix, AZ, 85001"
    assert any(
        "auto_visit_email.property_unresolved" in rec.getMessage()
        and "reason=no_property_id" in rec.getMessage()
        for rec in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════
# 4 · Soft-deleted property → warning + text fallback.
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_property_warns_and_falls_back(monkeypatch, caplog):
    _seed(monkeypatch, properties=[
        _property("p-1", TENANT_A, "3112 W Adobe Dam Rd",
                    "Phoenix", "AZ", "85027",
                    deleted_at="2026-02-01T00:00:00Z"),
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-1",
        "address": "FALLBACK 999 Old Road, Phoenix, AZ, 85099",
    }
    with caplog.at_level(logging.WARNING, logger="server_api"):
        resolved = _run(
            ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "FALLBACK 999 Old Road, Phoenix, AZ, 85099"
    assert any(
        "reason=property_soft_deleted" in rec.getMessage()
        for rec in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════
# 5 · Cross-tenant lookup — tenant A's request must NOT leak
# tenant B's property.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_lookup_never_leaks(monkeypatch, caplog):
    # Property lives in tenant B.
    _seed(monkeypatch, properties=[
        _property("p-Bshared", TENANT_B, "SECRET B ADDRESS",
                    "Phoenix", "AZ", "85099"),
    ])
    # Tenant A's job carries the SAME property_id as tenant B's
    # (id collision / referrer forgery).
    job = {
        "id": "j-A", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-Bshared",
        "address": "TENANT A fallback address",
    }
    with caplog.at_level(logging.WARNING, logger="server_api"):
        resolved = _run(
            ave._resolve_visit_email_address(_tenant(TENANT_A), job))
    # Tenant B's line1 MUST NOT appear.
    assert "SECRET" not in resolved
    assert resolved == "TENANT A fallback address"
    assert any(
        "reason=property_not_found" in rec.getMessage()
        for rec in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════
# 6 · Rung 2 — customer.primary_property_id fallback when the job
# doesn't carry a property_id.
# ═══════════════════════════════════════════════════════════════════
def test_primary_property_id_rung_is_honored(monkeypatch):
    _seed(monkeypatch,
          properties=[
              _property("p-primary", TENANT_A, "3112 W Adobe Dam Rd",
                          "Phoenix", "AZ", "85027"),
          ],
          customers=[
              {"id": "c-1", "tenant_id": TENANT_A,
               "primary_property_id": "p-primary"},
          ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": None,
        "address": "STALE fallback",
    }
    resolved = _run(ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "3112 W Adobe Dam Rd, Phoenix, AZ 85027"



# ═══════════════════════════════════════════════════════════════════
# Portal-style branded template · Feb-2026 · Commit 3
# ═══════════════════════════════════════════════════════════════════
# ``render_email`` is a pure function — the tests below assert on
# its returned ``{subject, html, text, kind}`` dict without hitting
# Mongo.  The address-resolution suite above already covers the
# async wrapper that lives ONE layer up.
def _sample_sr() -> Dict[str, Any]:
    return {
        "id": "sr-render", "job_id": "j-render", "kind": "pool",
        "submitted_at": "2026-02-14T10:15:00Z",
        "tech_name": "Grace Hopper",
        "chemical_readings": [
            {"key": "chlorine",       "value": 2.5, "label": "Average"},
            {"key": "ph",             "value": 7.4, "label": "Average"},
            {"key": "alkalinity",     "value": 130, "label": "Above Average"},
            {"key": "cyanuric_acid",  "value": 45,  "label": "Average"},
        ],
        "checklist_completed": [
            {"label": "Skimmed pool surface", "done": True},
            {"label": "Emptied skimmer baskets", "done": True},
            {"label": "Vacuumed pool floor", "done": True},
        ],
        "photos": [
            {"url": "https://cdn.example.com/a.jpg",
             "taken_at": "2026-02-14T10:10:00Z"},
            {"url": "https://cdn.example.com/b.jpg",
             "taken_at": "2026-02-14T10:11:00Z"},
        ],
        "customer_notes": "Water looking great — see you next week.",
    }


def _sample_job() -> Dict[str, Any]:
    return {
        "id": "j-render", "tenant_id": TENANT_A,
        "customer_id": "c-render",
        "title": "Weekly Pool Cleaning",
        "service_type": "Pool service",
        "status": "completed",
        "address": "3112 W Adobe Dam Rd, Phoenix, AZ 85027",
    }


def _sample_customer() -> Dict[str, Any]:
    return {"id": "c-render", "tenant_id": TENANT_A,
            "name": "Ada Lovelace"}


def _sample_tenant() -> Dict[str, Any]:
    return {"id": TENANT_A, "name": "Aquaterra Pool & Landscape",
            "logo_url": "https://cdn.example.com/aquaterra-logo.png"}


def _sample_branding() -> Dict[str, Any]:
    return {"brand_primary_hex": "#0B4A6F",
            "brand_secondary_hex": "#0369A1",
            "logo_url": "https://cdn.example.com/aquaterra-logo.png"}


def test_branded_template_renders_logo_and_brand_primary():
    """Feb-2026 · Commit 3 · portal-style branded template.

    Locks: logo <img src> is the absolute URL, primary hex appears
    in the header-bar background, page-bg neutral is present, and
    the ``kind`` marker returns ``"pool"``.
    """
    result = ave.render_email(
        _sample_tenant(), _sample_job(), _sample_sr(),
        _sample_customer(), branding=_sample_branding(),
    )
    assert result["kind"] == "pool"
    html = result["html"]
    # Logo — absolute URL, alt text, inline height.
    assert 'src="https://cdn.example.com/aquaterra-logo.png"' in html
    assert 'alt="Aquaterra Pool &amp; Landscape"' in html or \
        'alt="Aquaterra Pool & Landscape"' in html
    # Header bar background = brand_primary_hex.
    assert "#0b4a6f" in html.lower()
    # Neutral page background.
    assert "#F5F7FA" in html or "#f5f7fa" in html.lower()
    # Preheader present (hidden).
    assert "Visit summary for Ada Lovelace" in html
    assert "display:none" in html


def test_branded_template_metric_pills_match_portal_hex():
    """Each metric renders with the exact portal Tailwind hex:
    sky/emerald/amber/red.  Our fixture has 3 ``Average`` (emerald)
    and 1 ``Above Average`` (amber).
    """
    result = ave.render_email(
        _sample_tenant(), _sample_job(), _sample_sr(),
        _sample_customer(), branding=_sample_branding(),
    )
    html = result["html"]
    # Emerald appears (3 average bands).
    assert html.count("#10B981") >= 3
    # Amber appears (1 above-average band).
    assert "#F59E0B" in html
    # Never leaks a below-average or elevated color for this fixture.
    assert "#EF4444" not in html


def test_branded_template_no_logo_falls_back_to_platform_default():
    """Tenant without ``logo_url`` → header still renders an <img>
    (platform-default logo — the ``render_email`` hardcoded shared
    brand mark that every unbranded tenant shares).  This is the
    legacy behavior; the text-fallback branch of the header-bar
    composer is exercised directly in the sibling test below.
    """
    tenant_no_logo = {"id": TENANT_A, "name": "No Logo Co"}
    branding = {"brand_primary_hex": "#0B4A6F",
                "brand_secondary_hex": "#0369A1"}
    result = ave.render_email(
        tenant_no_logo, _sample_job(), _sample_sr(),
        _sample_customer(), branding=branding,
    )
    html = result["html"]
    # Platform-default logo is the fallback ``logo`` computed in
    # ``render_email`` when tenant + settings both lack a logo_url.
    assert "app.plofv.com/logo-full.png" in html
    # The alt still names the tenant.
    assert 'alt="No Logo Co"' in html
    # And the header-bar still carries the primary hex.
    assert 'bgcolor="#0b4a6f"' in html.lower()


def test_header_bar_composer_text_fallback_when_logo_url_none():
    """``_render_header_bar(company, None, palette)`` → renders the
    company name in white on the brand-navy strip with NO <img>.
    Exercises the composer's own fallback branch directly (the
    high-level ``render_email`` wraps this call with a platform-
    default logo, so the fallback isn't reachable through the
    outer API).
    """
    palette = {"primary": "#0B4A6F", "secondary": "#0369A1",
               "accent": "#0369A1"}
    html = ave._render_header_bar("Composer Fallback Co", None, palette)
    assert "<img" not in html
    assert "Composer Fallback Co" in html
    assert 'bgcolor="#0b4a6f"' in html.lower()
    # White text on brand-navy.
    assert "color:#FFFFFF" in html


def test_branded_template_plain_text_info_parity():
    """The plain-text sibling contains the same address, tech,
    metric values, and checklist labels as the HTML version so
    text-only email clients render the same information."""
    result = ave.render_email(
        _sample_tenant(), _sample_job(), _sample_sr(),
        _sample_customer(), branding=_sample_branding(),
    )
    text = result["text"]
    # Address matches HTML.
    assert "3112 W Adobe Dam Rd, Phoenix, AZ 85027" in text
    # Technician matches.
    assert "Grace Hopper" in text
    # Metric labels are present in the plain-text POOL section.
    assert "POOL" in text
    for label in ("Chlorine", "pH", "Alkalinity", "CYA"):
        assert label in text, f"missing metric label: {label}"
    # Checklist items are present as `- {label}` rows.
    assert "- Skimmed pool surface" in text
    assert "- Vacuumed pool floor" in text
    # Notes preserved.
    assert "Water looking great" in text
    # Portal link.
    assert "Portal: " in text


def test_branded_template_photos_link_to_portal_not_asset():
    """Visit photos card wraps each thumbnail in an <a href> that
    points at the portal, NOT the raw CDN URL — auth stays in the
    loop and email-client image caching can't leak asset URIs."""
    result = ave.render_email(
        _sample_tenant(), _sample_job(), _sample_sr(),
        _sample_customer(), branding=_sample_branding(),
    )
    html = result["html"]
    # Photo card header is present.
    assert "VISIT PHOTOS" in html
    # Each photo <img> is wrapped in a portal <a>.
    assert 'href="https://' in html and "/portal/service-reports" in html
    # Photos_count reflected in plain-text section.
    assert "Visit photos: 2 attached" in result["text"]


def test_branded_template_preheader_stripped_from_visible_render():
    """Preheader must be present but hidden — inline styles cover
    every Gmail / Outlook / Apple Mail hiding vector."""
    result = ave.render_email(
        _sample_tenant(), _sample_job(), _sample_sr(),
        _sample_customer(), branding=_sample_branding(),
    )
    html = result["html"]
    # Every canonical hide selector we set must be inline.
    for token in (
        "display:none", "max-height:0", "overflow:hidden",
        "mso-hide:all", "visibility:hidden",
    ):
        assert token in html, f"preheader missing {token}"


def test_branded_template_no_external_style_or_media_queries():
    """Email-safety guard: no ``<style>`` block, no ``@media``
    queries (both are strip-prone across email clients)."""
    result = ave.render_email(
        _sample_tenant(), _sample_job(), _sample_sr(),
        _sample_customer(), branding=_sample_branding(),
    )
    html = result["html"]
    assert "<style" not in html.lower(), \
        "external <style> block breaks Gmail rendering"
    assert "@media" not in html.lower(), \
        "@media queries get stripped by Outlook & others"

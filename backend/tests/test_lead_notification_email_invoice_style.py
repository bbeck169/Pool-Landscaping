"""Phase LD2 · Feb 2026 — Lead notification email invoice-style redesign.

Locks the visual + behavioural contract for the redesigned admin
"new lead" email:

* Header band renders in the tenant's ``brand_primary_hex`` and
  carries the tenant business name + "New lead" tagline.
* CTA button uses the tenant's derived accent color and deep-links
  to ``/admin/leads/{lead_id}``.
* Phone renders as ``tel:``, email as ``mailto:``.
* Every data row is optional — missing fields hide their row (no
  empty "-" placeholders).
* Fallback palette kicks in when the tenant has no brand colors
  configured.
* Subject line format: ``New lead — {name} · {source_label}``.
* Plain-text alternate produced alongside the HTML.
* Recipient resolution untouched — the same fixture that fed the
  pre-LD2 resolver returns the same recipient list post-redesign.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if not asyncio.get_event_loop().is_closed() \
        else asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────── shared lead fixture ────────────────────────
FULL_LEAD = {
    "id": "TEST_ld2-l1",
    "name": "Marilyn Guhr",
    "email": "marilyn.guhr@cox.net",
    "phone": "+1 (602) 555-1234",
    "company_name": "Guhr Contracting LLC",
    "service_address": "1234 W Palm Ln, Peoria AZ 85383",
    "service_interest": "Pool cleaning and maintenance",
    "notes": "Weekly service please. Gate code 1234.",
    "source": "website_form",
    "latitude": 33.6273,
    "longitude": -112.3568,
    "created_at": "2026-09-14T15:00:00+00:00",
    "tags": ["premium", "west-valley"],
    "utm_campaign": "spring-promo-2026",
}

TENANT_WITH_BRAND = {
    "id": "tenant-brand-1",
    "name": "Sunbelt Pools",
    "business_name": "Sunbelt Pools",
    "brand_primary_hex": "#123456",
    "brand_secondary_hex": "#654321",
    "brand_accent_hex": "#ABCDEF",
    "logo_url": "https://cdn.example.com/logo.png",
}
BRANDING_WITH_BRAND = {
    "company_display_name": "Sunbelt Pools",
    "brand_primary_hex": "#123456",
    "brand_secondary_hex": "#654321",
    "brand_accent_hex": "#ABCDEF",
    "logo_url": "https://cdn.example.com/logo.png",
}


# ═══════════════════════════ HTML render ════════════════════════════
class TestInvoiceStyleHtml:
    def test_header_bar_uses_tenant_primary_brand_color(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        # The full-width header band renders with a solid bgcolor
        # equal to the tenant primary hex.
        assert 'bgcolor="#123456"' in html, "header bgcolor missing"
        # Business name renders in the header.
        assert "Sunbelt Pools" in html
        # Tagline present.
        assert "New lead" in html

    def test_cta_button_uses_tenant_accent_color_and_admin_url(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        # CTA button background = brand accent hex.
        assert "background:#abcdef" in html.lower()
        # CTA points at /admin/leads/{id}.
        assert 'href="https://crm.example.com/admin/leads/TEST_ld2-l1"' in html
        # Human label matches spec.
        assert "Open lead in CRM" in html

    def test_phone_renders_as_tel_link_email_as_mailto(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        assert 'href="tel:+16025551234"' in html
        assert 'href="mailto:marilyn.guhr@cox.net"' in html

    def test_address_and_coords_render(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        assert "1234 W Palm Ln, Peoria AZ 85383" in html
        assert "📍 33.62730, -112.35680" in html

    def test_raw_message_block_present_with_verbatim_text(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        # The customer's verbatim inquiry lives in a subtle bordered
        # block so admins see exactly what was submitted.
        assert "Weekly service please. Gate code 1234." in html
        # Section heading matches spec.
        assert re.search(r"Message</h3>", html)

    def test_missing_fields_hide_their_row(self):
        from services.lead_admin_notifications import _compose_email_html
        sparse_lead = {
            "id": "TEST_ld2-l2",
            "name": "Anon Visitor",
            "email": "anon@example.com",
            "source": "chat_widget",
            "created_at": "2026-09-14T15:00:00+00:00",
        }
        html = _compose_email_html(
            lead=sparse_lead, app_url="https://crm.example.com",
            branding={}, tenant={"id": "tenant-x"},
        )
        # Present fields still render.
        assert "Anon Visitor" in html
        assert 'href="mailto:anon@example.com"' in html
        # Missing rows are dropped — the labels never appear.
        assert "Phone" not in html
        assert "Requested Service" not in html
        assert "Coordinates" not in html
        assert "Company" not in html
        # No empty em-dash placeholder rows.
        assert "<td>-</td>" not in html
        assert "<td>—</td>" not in html

    def test_fallback_palette_when_tenant_has_no_brand_colors(self):
        from services.lead_admin_notifications import (
            _compose_email_html, _DEFAULT_PRIMARY_HEX,
        )
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding={}, tenant={"id": "tenant-y",
                                    "business_name": "Bare Tenant"},
        )
        assert f'bgcolor="{_DEFAULT_PRIMARY_HEX}"' in html
        # Tenant business name still renders even without brand
        # colors — regression against a hard-coded brand.
        assert "Bare Tenant" in html

    def test_business_name_is_never_hardcoded(self):
        from services.lead_admin_notifications import _compose_email_html
        html = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding={}, tenant={"id": "tenant-z",
                                    "business_name": "Frog Pond LLC"},
        )
        # Regression against hard-coded "Pool & Landscaping of Vistancia"
        # or similar tenant-specific strings.
        assert "Pool & Landscaping of Vistancia" not in html
        assert "Frog Pond LLC" in html

    def test_referral_badge_renders_when_source_is_referral(self):
        from services.lead_admin_notifications import _compose_email_html
        lead = dict(FULL_LEAD, source="referral_from_customer:cust-42")
        html = _compose_email_html(
            lead=lead, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        assert "Referral" in html
        # Non-referral leads don't get the badge.
        html2 = _compose_email_html(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        # ``Referral`` string still allowed for the source label of
        # other referral sources, but the badge span is not present.
        assert "text-transform:uppercase" in html
        assert ">Referral</span>" not in html2

    def test_preheader_capped_at_90_chars(self):
        from services.lead_admin_notifications import _compose_preheader
        text = _compose_preheader(FULL_LEAD)
        assert len(text) <= 90


# ═══════════════════════════ subject line ═══════════════════════════
class TestSubjectLine:
    def test_subject_includes_customer_name_and_source(self):
        from services.lead_admin_notifications import _compose_subject
        assert _compose_subject(FULL_LEAD) == \
            "New lead — Marilyn Guhr · Website form"


# ═══════════════════════════ plain text ═════════════════════════════
class TestPlainTextAlternate:
    def test_text_alt_contains_same_content_as_html(self):
        from services.lead_admin_notifications import _compose_email_text
        text = _compose_email_text(
            lead=FULL_LEAD, app_url="https://crm.example.com",
            branding=BRANDING_WITH_BRAND, tenant=TENANT_WITH_BRAND,
        )
        for token in [
            "Marilyn Guhr", "marilyn.guhr@cox.net", "+1 (602) 555-1234",
            "1234 W Palm Ln, Peoria AZ 85383",
            "Pool cleaning and maintenance",
            "Weekly service please. Gate code 1234.",
            "Website form",
            "https://crm.example.com/admin/leads/TEST_ld2-l1",
            "Sunbelt Pools",
        ]:
            assert token in text, f"missing plain-text token: {token!r}"


# ═══════════════════════════ fan-out regression ═════════════════════
class TestRecipientResolverUntouched:
    """The LD2 redesign changes the HTML/subject/plain-text bodies
    ONLY. The recipient resolver contract is guarded by
    ``test_lead_admin_notification_fanout.py`` — this test loads
    the resolver against a controlled fixture and asserts the
    output matches what the pre-LD2 code would have produced
    against the same fixture.
    """
    def test_resolver_returns_same_recipients_for_same_fixture(self):
        from services.lead_admin_notifications import (
            _resolve_admin_recipients,
        )
        tid = f"TEST_ld2-{uuid.uuid4().hex[:6]}"
        seeded_ids = []
        try:
            for row in [
                {"id": f"TEST_ld2-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": tid, "email": "adminA@example.com",
                 "role": "admin"},
                {"id": f"TEST_ld2-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": tid, "email": "managerA@example.com",
                 "role": "manager"},
                {"id": f"TEST_ld2-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": tid, "email": "techA@example.com",
                 "role": "tech"},
                {"id": f"TEST_ld2-u-{uuid.uuid4().hex[:6]}",
                 "tenant_id": tid, "email": "inactive@example.com",
                 "role": "admin", "active": False},
            ]:
                _sync.users.insert_one(row)
                seeded_ids.append(row["id"])
            tenant = {"id": tid, "business_settings": {
                "notification_email": "owner@example.com"}}
            out = _run(_resolve_admin_recipients(tenant))
            # Same as the pre-LD2 baseline: admin + manager + biz email,
            # tech role + inactive user excluded.
            lower = sorted(e.lower() for e in out)
            assert lower == sorted([
                "admina@example.com",
                "managera@example.com",
                "owner@example.com",
            ])
        finally:
            _sync.users.delete_many({"id": {"$in": seeded_ids}})


# ═══════════════════════════ dispatch integration ═══════════════════
class TestDispatchPassesTextAndTenantThrough:
    """Regression: ``dispatch_admin_lead_email`` must forward both
    the tenant record and the plain-text alternate down to the
    background send task."""
    def test_send_receives_text_and_new_subject(self, monkeypatch):
        from services.lead_admin_notifications import (
            dispatch_admin_lead_email,
        )
        from fastapi import BackgroundTasks
        tid = f"TEST_ld2-tx-{uuid.uuid4().hex[:6]}"
        uid = f"TEST_ld2-tx-u-{uuid.uuid4().hex[:6]}"
        try:
            _sync.users.insert_one({
                "id": uid, "tenant_id": tid,
                "email": "adminA@example.com", "role": "admin",
            })
            _sync.tenants.insert_one({
                "id": tid, "name": "Fixture Tenant",
                "business_name": "Fixture Tenant",
            })
            captured: list = []
            async def fake_send(**kwargs):
                captured.append(kwargs)
                return {"provider_response_id": "px-1"}
            # Monkey-patch at the resend_adapter module — the send
            # helper imports it lazily inside ``_send_one``.
            import services.email.resend_adapter as adapter
            monkeypatch.setattr(adapter, "send", fake_send)
            bt = BackgroundTasks()
            tenant = {"id": tid, "name": "Fixture Tenant",
                      "business_name": "Fixture Tenant",
                      "business_settings": {}}
            result = _run(dispatch_admin_lead_email(
                lead=dict(FULL_LEAD, id=f"TEST_ld2-l-{uuid.uuid4().hex[:6]}"),
                tenant=tenant, background_tasks=bt,
            ))
            assert result["queued"] >= 1
            # Flush BackgroundTasks synchronously so ``fake_send``
            # captures the outbound payload.
            _run(bt())
            assert captured, "background send never fired"
            payload = captured[0]
            assert "text" in payload and payload["text"], (
                "plain-text alternate not forwarded to Resend adapter"
            )
            assert payload["subject"].startswith("New lead — Marilyn Guhr")
            assert "Website form" in payload["subject"]
            # HTML body carries the CTA + business name.
            assert "Open lead in CRM" in payload["html"]
            assert "Fixture Tenant" in payload["html"]
        finally:
            _sync.users.delete_one({"id": uid})
            _sync.tenants.delete_one({"id": tid})
            _sync.audit_logs.delete_many({"tenant_id": tid})
            _sync.lead_notification_dispatches.delete_many({"tenant_id": tid})

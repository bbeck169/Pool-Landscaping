"""Feb-2026 · Portal-invite merge-tag fix · tests.

Locks the contract for the ``{COMPANY_NAME}`` bug and its adjacent
merge-tag repairs.  Fixed surfaces:

  * ``services.marketing.merge_tags._company_name`` — 4-tier
    fallback chain ``business_card.company_name →
    settings.company_name → tenant.name → "Your Service Provider"``,
    WARN log fires only on the last tier.
  * ``services.marketing.merge_tags.rebrace_single_brace_catalog_tokens``
    — upgrades ``{COMPANY_NAME}`` / ``{COMPANY_PHONE}`` /
    ``{CUSTOMER_FULL_NAME}`` / etc. to their canonical
    ``{{TOKEN}}`` form BEFORE render, leaving non-catalog braces
    verbatim.
  * ``routers.portal_admin._try_send_reset_email`` — end-to-end
    render never emits a literal ``{...}`` for a catalog token,
    tenant company-name flows into the outbound HTML/text bodies.

Strictly manual pytest — no testing agent.  No FE / mobile /
adjacent-template touches per the brief.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import types

import pytest

from services.marketing.merge_tags import (
    _company_name,
    _company_phone,
    rebrace_single_brace_catalog_tokens,
    render_template,
)


# ─── Fallback chain ────────────────────────────────────────────────

def test_company_name_prefers_business_card():
    """Tier 1 — ``settings.business_card.company_name`` wins."""
    ctx = {"tenant": {
        "id": "t1", "slug": "acme",
        "name": "OLD LEGACY NAME",
        "settings": {
            "company_name": "middle-tier-legacy",
            "business_card": {"company_name": "AquaTerra Pools"},
        },
    }}
    assert _company_name(ctx) == "AquaTerra Pools"


def test_company_name_falls_back_to_settings_company_name():
    """Tier 2 — ``settings.company_name`` fires when business_card is empty."""
    ctx = {"tenant": {
        "id": "t1", "slug": "acme",
        "name": "OLD LEGACY NAME",
        "settings": {
            "company_name": "Middle Tier Co",
            "business_card": {"company_name": "  "},        # blank
        },
    }}
    assert _company_name(ctx) == "Middle Tier Co"


def test_company_name_falls_back_to_tenant_name():
    """Tier 3 — ``tenant.name`` fires when the first two are empty."""
    ctx = {"tenant": {
        "id": "t1", "slug": "acme",
        "name": "Legacy Tenant LLC",
        "settings": {"business_card": {}},
    }}
    assert _company_name(ctx) == "Legacy Tenant LLC"


def test_company_name_ultimate_fallback_and_warn(caplog):
    """Tier 4 — all three tiers empty → ``"Your Service Provider"`` and WARN."""
    ctx = {"tenant": {"id": "t-broken", "slug": "unknown-slug",
                       "settings": {"business_card": {}}}}
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    got = _company_name(ctx)
    assert got == "Your Service Provider"
    warns = [r for r in caplog.records
             if r.levelno == logging.WARNING
             and "COMPANY_NAME resolver fell through" in r.getMessage()]
    assert warns, (
        "expected a WARN log when the ultimate fallback fires — "
        f"got records: {[r.getMessage() for r in caplog.records]}"
    )
    assert "t-broken" in warns[-1].getMessage()


def test_company_name_no_warn_on_non_ultimate_tier(caplog):
    """WARN is a data-integrity signal — must NOT fire on healthy tenants."""
    ctx = {"tenant": {
        "id": "t1",
        "settings": {"business_card": {"company_name": "AquaTerra"}},
    }}
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    got = _company_name(ctx)
    assert got == "AquaTerra"
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_company_name_missing_tenant_hits_fallback(caplog):
    """Empty ctx → fallback + WARN. Portal-invite pipeline must never crash."""
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    assert _company_name({}) == "Your Service Provider"
    assert any("COMPANY_NAME resolver fell through" in r.getMessage()
               for r in caplog.records)


# ─── Rebrace helper ────────────────────────────────────────────────

def test_rebrace_upgrades_single_brace_catalog_tokens():
    body = ("<p>Welcome to {COMPANY_NAME}! Call us at "
            "{COMPANY_PHONE} or reply to {COMPANY_EMAIL}.</p>")
    out = rebrace_single_brace_catalog_tokens(body)
    assert out == ("<p>Welcome to {{COMPANY_NAME}}! Call us at "
                   "{{COMPANY_PHONE}} or reply to {{COMPANY_EMAIL}}.</p>")


def test_rebrace_upgrades_customer_and_portal_tokens():
    """Adjacent invite-relevant tokens — CUSTOMER_FULL_NAME,
    CUSTOMER_PORTAL_LINK, TODAY."""
    body = ("Hi {CUSTOMER_FULL_NAME}, log in at "
            "{CUSTOMER_PORTAL_LINK} on {TODAY}.")
    out = rebrace_single_brace_catalog_tokens(body)
    assert out == ("Hi {{CUSTOMER_FULL_NAME}}, log in at "
                   "{{CUSTOMER_PORTAL_LINK}} on {{TODAY}}.")


def test_rebrace_preserves_double_brace_tokens():
    """Idempotent — already-double-braced tokens are byte-identical."""
    body = "Hi {{CUSTOMER_FIRST_NAME}}, from {{COMPANY_NAME}}."
    assert rebrace_single_brace_catalog_tokens(body) == body


def test_rebrace_preserves_non_catalog_braces():
    """Unrelated prose braces (``{2024}``, ``{prose}``) stay untouched."""
    body = "Copyright {2024} — {some_unregistered_thing} works {ok}."
    assert rebrace_single_brace_catalog_tokens(body) == body


def test_rebrace_is_idempotent():
    """Second pass on already-rebrace body is a no-op."""
    body = "Welcome to {COMPANY_NAME}, from {COMPANY_EMAIL}."
    once = rebrace_single_brace_catalog_tokens(body)
    twice = rebrace_single_brace_catalog_tokens(once)
    assert once == twice
    assert "{{COMPANY_NAME}}" in twice
    assert "{{COMPANY_EMAIL}}" in twice


def test_rebrace_handles_whitespace_inside_braces():
    body = "Welcome to { COMPANY_NAME }."
    out = rebrace_single_brace_catalog_tokens(body)
    # Whitespace-tolerant → double-brace form ships to the renderer
    # which is itself whitespace-tolerant.
    assert re.search(r"\{\{\s*COMPANY_NAME\s*\}\}", out)


def test_rebrace_handles_empty_and_none():
    assert rebrace_single_brace_catalog_tokens("") == ""
    assert rebrace_single_brace_catalog_tokens(None) == ""


def test_rebrace_mixed_case_tokens_resolve_via_renderer():
    """Renderer is case-insensitive — the helper's uppercase check
    matches even when the DB body uses mixed-case."""
    body = "Hi {Company_Name}."
    out = rebrace_single_brace_catalog_tokens(body)
    assert out == "Hi {{Company_Name}}."
    ctx = {"tenant": {"settings": {"business_card":
                                    {"company_name": "AquaTerra"}}}}
    rendered, unresolved = render_template(out, ctx)
    assert rendered == "Hi AquaTerra."
    assert not unresolved


# ─── End-to-end through render_template ────────────────────────────

def test_end_to_end_company_name_resolves_via_business_card():
    body = "Hi {{NAME}}, welcome to {COMPANY_NAME}!"
    body = rebrace_single_brace_catalog_tokens(body)
    ctx = {"name": "Jane",
           "tenant": {"settings":
                      {"business_card": {"company_name": "AquaTerra"}}}}
    rendered, unresolved = render_template(body, ctx)
    assert rendered == "Hi Jane, welcome to AquaTerra!"
    assert unresolved == []


def test_end_to_end_no_literal_curly_tokens_survive():
    """Once rebrace + render have run, no ``{TOKEN}`` literals must
    remain in the output for any catalog token."""
    body = ("<p>Hi {{NAME}},</p>"
             "<p>Welcome to {COMPANY_NAME}!</p>"
             "<p>Contact us at {COMPANY_EMAIL} or {COMPANY_PHONE}.</p>"
             "<p>Log in: <a href='{{LOGIN_URL}}'>{{LOGIN_URL}}</a></p>")
    body = rebrace_single_brace_catalog_tokens(body)
    ctx = {
        "name": "Jane",
        "login_url": "https://app.example.com/login",
        "tenant": {"id": "t1",
                    "settings": {"business_card": {
                        "company_name": "AquaTerra Pools",
                        "phone": "+15550001111",
                        "email": "hello@aquaterra.example.com",
                    }}},
    }
    rendered, _ = render_template(body, ctx)
    # Every catalog token has resolved — no bare ``{TOKEN}`` remains.
    # Regex intentionally excludes JSON-ish + prose braces; we're
    # scanning for ALL_CAPS_UNDERSCORE tokens which is our fault
    # surface.
    assert not re.search(r"\{[A-Z][A-Z0-9_]*\}", rendered)
    assert not re.search(r"\{\{", rendered)                # no {{ leftover
    assert "AquaTerra Pools" in rendered
    assert "hello@aquaterra.example.com" in rendered
    assert "+15550001111" in rendered
    assert "Jane" in rendered


def test_end_to_end_ultimate_fallback_text_appears(caplog):
    """A completely broken tenant renders "Your Service Provider"
    verbatim in the outbound body + logs the WARN."""
    body = "Hi {{NAME}}, welcome to {COMPANY_NAME}!"
    body = rebrace_single_brace_catalog_tokens(body)
    ctx = {"name": "Jane", "tenant": {"id": "t-broken"}}
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    rendered, _ = render_template(body, ctx)
    assert rendered == "Hi Jane, welcome to Your Service Provider!"
    assert any("COMPANY_NAME resolver fell through" in r.getMessage()
               for r in caplog.records)


# ─── End-to-end through _try_send_reset_email ──────────────────────

@pytest.fixture
def stub_send_env(monkeypatch):
    """Replace the resend SDK + config surfaces the send path pulls
    from, and capture every outbound send.  Returns the capture list."""
    captured: list = []

    # 1. config module surfaces the SDK expects.
    monkeypatch.setattr("config.RESEND_API_KEY", "re_test_key",
                          raising=False)
    monkeypatch.setattr("config.EMAIL_FROM", "invites@example.com",
                          raising=False)

    # 2. Stub the resend SDK — sys.modules replacement so the local
    # ``import resend`` inside the send function picks it up.
    fake_resend = types.ModuleType("resend")

    class _Emails:
        @staticmethod
        def send(payload):
            captured.append(payload)
            return {"id": "resend_fake_id_1"}

    fake_resend.api_key = None
    fake_resend.Emails = _Emails
    monkeypatch.setitem(sys.modules, "resend", fake_resend)

    # 3. wrap_html_in_shell — return the fragment unchanged so
    # test assertions read the inner HTML verbatim.
    fake_theming = types.ModuleType("services.email.theming")
    fake_theming.wrap_html_in_shell = lambda html, branding=None: html
    monkeypatch.setitem(sys.modules, "services.email.theming",
                          fake_theming)

    return captured


@pytest.fixture
def stub_tenant(monkeypatch):
    """Return a callable that lets each test seed a tenant record
    to be returned by ``db.tenants.find_one``."""
    state = {"tenant": None}

    class _TenantsColl:
        async def find_one(self, *_args, **_kwargs):
            return state["tenant"]

    class _StubDB:
        tenants = _TenantsColl()

    from routers import portal_admin
    monkeypatch.setattr(portal_admin, "db", _StubDB(), raising=True)

    def _set(tenant_doc):
        state["tenant"] = tenant_doc
    return _set


@pytest.fixture
def stub_template_lookup(monkeypatch):
    """Force the DB template lookup to return a caller-supplied
    ``portal_invite_email`` row (with a subject + body that carries
    the bug-shape single-brace ``{COMPANY_NAME}`` reference)."""
    state = {"row": None}

    async def _stub(code, tenant_id):
        return state["row"]

    monkeypatch.setattr(
        "services.marketing_template_lookup.get_template_by_code",
        _stub, raising=True,
    )

    def _set(row):
        state["row"] = row
    return _set


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_send_path_resolves_company_name_in_db_row(
        stub_send_env, stub_tenant, stub_template_lookup):
    """DB row uses SINGLE-BRACE ``{COMPANY_NAME}`` — after the fix,
    the outbound HTML renders the tenant's actual company name."""
    stub_tenant({
        "id": "t-happy", "name": "TENANT NAME ROOT",
        "settings": {"business_card": {
            "company_name": "AquaTerra Pools",
            "phone": "+15550001111",
            "email": "hello@aquaterra.example.com",
        }},
    })
    stub_template_lookup({
        "subject": "Welcome to {COMPANY_NAME}",
        "body": ("<p>Hi {{NAME}}, welcome to {COMPANY_NAME}!</p>"
                  "<p>Reach us at {COMPANY_PHONE}.</p>"
                  "<p><a href='{{LOGIN_URL}}'>Sign in</a></p>"),
    })

    from routers.portal_admin import _try_send_reset_email
    result = _run(_try_send_reset_email(
        to="jane@example.com",
        name="Jane Homeowner",
        temp_password="TempPa$$1",
        login_url="https://app.example.com/login",
        tenant_id="t-happy",
    ))
    assert result == "resend_fake_id_1"
    assert len(stub_send_env) == 1
    payload = stub_send_env[0]
    assert payload["subject"] == "Welcome to AquaTerra Pools"
    html = payload["html"]
    assert "AquaTerra Pools" in html
    assert "+15550001111" in html
    assert "Jane Homeowner" in html
    # No literal single-brace catalog tokens survived.
    assert "{COMPANY_NAME}" not in html
    assert "{COMPANY_PHONE}" not in html
    assert "{NAME}" not in html                                # bare
    assert "{{" not in html                                    # nothing double-braced
    # Text alternative is also merge-tag-clean.
    text = payload["text"]
    assert "AquaTerra Pools" not in text or "Jane Homeowner" in text
    assert "{COMPANY_NAME}" not in text
    assert "{{" not in text


def test_send_path_falls_back_to_settings_company_name(
        stub_send_env, stub_tenant, stub_template_lookup):
    """When ``business_card.company_name`` is absent but
    ``settings.company_name`` is set — send still renders correctly."""
    stub_tenant({
        "id": "t-mid", "name": "TENANT NAME ROOT",
        "settings": {
            "company_name": "Middle Tier Co",
            "business_card": {
                # No company_name — but phone is present so the
                # existing SAFE-SEND branding guard passes.
                "phone": "+15550002222",
            },
        },
    })
    stub_template_lookup({
        "subject": "Welcome to {COMPANY_NAME}",
        "body": "<p>Hi {{NAME}}, welcome to {COMPANY_NAME}!</p>",
    })
    from routers.portal_admin import _try_send_reset_email
    result = _run(_try_send_reset_email(
        to="jane@example.com", name="Jane", temp_password="TempPa$$1",
        login_url="https://app.example.com/login", tenant_id="t-mid",
    ))
    assert result == "resend_fake_id_1"
    html = stub_send_env[0]["html"]
    assert "Middle Tier Co" in html
    assert "{COMPANY_NAME}" not in html


def test_send_path_falls_back_to_tenant_name(
        stub_send_env, stub_tenant, stub_template_lookup):
    """When both ``business_card`` and ``settings.company_name`` are
    absent — falls back to ``tenant.name``."""
    stub_tenant({
        "id": "t-legacy", "name": "Legacy Tenant LLC",
        "settings": {"business_card": {"phone": "+15550003333"}},
    })
    stub_template_lookup({
        "subject": "Welcome",
        "body": "<p>Hi {{NAME}}, from {COMPANY_NAME}!</p>",
    })
    from routers.portal_admin import _try_send_reset_email
    result = _run(_try_send_reset_email(
        to="jane@example.com", name="Jane", temp_password="TempPa$$1",
        login_url="https://app.example.com/login", tenant_id="t-legacy",
    ))
    assert result == "resend_fake_id_1"
    html = stub_send_env[0]["html"]
    assert "Legacy Tenant LLC" in html


def test_send_path_ultimate_fallback_uses_your_service_provider_and_warns(
        stub_send_env, stub_tenant, stub_template_lookup, caplog):
    """Every branding tier empty EXCEPT phone (so SAFE-SEND rail
    still passes) → outbound HTML carries the "Your Service
    Provider" placeholder and the merge_tags WARN is emitted."""
    stub_tenant({
        "id": "t-broken", "name": "",
        "settings": {"business_card": {
            # Only phone; no company_name anywhere in the chain.
            "phone": "+15550009999",
        }},
    })
    stub_template_lookup({
        "subject": "Portal login for {COMPANY_NAME}",
        "body": "<p>Hi {{NAME}}, welcome to {COMPANY_NAME}!</p>",
    })
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    from routers.portal_admin import _try_send_reset_email
    result = _run(_try_send_reset_email(
        to="jane@example.com", name="Jane", temp_password="TempPa$$1",
        login_url="https://app.example.com/login", tenant_id="t-broken",
    ))
    assert result == "resend_fake_id_1"
    assert "Your Service Provider" in stub_send_env[0]["html"]
    assert "Your Service Provider" in stub_send_env[0]["subject"]
    # WARN log is the data-integrity signal.
    assert any("COMPANY_NAME resolver fell through" in r.getMessage()
               for r in caplog.records), (
        "expected the merge_tags WARN — got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


def test_send_path_hardcoded_fallback_no_literal_tokens(
        stub_send_env, stub_tenant, stub_template_lookup):
    """Even when the DB row is missing entirely (hardcoded fallback
    template wins), the outbound HTML has ZERO literal ``{TOKEN}``
    substrings and the tenant's name flows through."""
    stub_tenant({
        "id": "t-happy",
        "settings": {"business_card": {
            "company_name": "AquaTerra Pools",
            "phone": "+15550001111",
        }},
    })
    stub_template_lookup(None)                                # miss → fallback
    from routers.portal_admin import _try_send_reset_email
    result = _run(_try_send_reset_email(
        to="jane@example.com", name="Jane", temp_password="TempPa$$1",
        login_url="https://app.example.com/login", tenant_id="t-happy",
    ))
    assert result == "resend_fake_id_1"
    html = stub_send_env[0]["html"]
    text = stub_send_env[0]["text"]
    # Every ``{{TOKEN}}`` in the hardcoded body has resolved.
    for surface in (html, text):
        assert not re.search(r"\{\{[^}]+\}\}", surface)
        assert not re.search(r"\{[A-Z][A-Z0-9_]*\}", surface)
        assert "Jane" in surface
        assert "TempPa$$1" in surface
        assert "https://app.example.com/login" in surface

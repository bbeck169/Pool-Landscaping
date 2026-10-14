"""P2 #11 · Phase 2 (TD-42 / TD-43 / TD-44) · Feb-2026 — Backend tests.

Covers:

  * Byte-identical regression — a canonical seeded-shape template
    renders to the EXACT same MD5 as before the Phase 2 renderer
    upgrade (baseline captured during Phase 2 development:
    06cc4b55a789d009e63a694ac2ffae70, 2302 chars).  Protects every
    pre-existing template from accidental regression.

  * TD-42 — nested-columns renderer walks ``children`` recursively
    for token substitution AND row emission.  Depth guard rejects
    columns-inside-columns at the validator boundary.  Flat
    ``*_html`` fallback renders Phase-1-authored column content when
    ``children`` is empty.

  * TD-43 — ``preview_text`` is injected as the first child of
    ``<body>`` with the hidden-span styling cocktail.  Tokens
    inside ``preview_text`` resolve.  Omitting / nulling the field
    yields byte-identical output.  Max-length 150 enforced at the
    Pydantic validator.

  * TD-44 — ``wrap_links`` wraps http(s) hrefs with UTM params,
    skips ``mailto:`` / ``tel:`` / ``#anchor`` / unsubscribe links
    / already-UTM'd URLs, honors the tenant override, and no-ops
    when ``email_link_wrapping_enabled=False``.

  * UTM admin endpoints — ``GET /comms/tenants/current/email-utm``
    returns defaults when no override, ``PATCH`` persists the
    override, unknown keys rejected.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db

from services.comm_tokens import render_email_html, sample_tokens_context
from services.email_link_wrapper import wrap_links


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"
JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id: str, email: str, role: str, tenant_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "email": email, "role": role,
         "tenant_id": tenant_id,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


@pytest.fixture()
def tenant_id():
    tid = f"p2p2-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"P2P2 {tid}", "slug": f"p2p2-{tid}",
        "active": True,
    })
    yield tid
    _sync.email_templates.delete_many({"tenant_id": tid})
    _sync.tenants.delete_many({"id": tid})
    _sync.users.delete_many({"tenant_id": tid})


def _seed_admin(tenant_id: str) -> dict:
    uid = f"admin-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p2p2.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": "admin",
        "name": "P2 Admin", "email": email,
    })
    return {"id": uid, "email": email,
            "token": _tok(uid, email, "admin", tenant_id)}


def _auth(token: str, tenant_id: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "X-Tenant-Id": tenant_id,
            "Content-Type": "application/json"}


# ══════════════════════════════════════════════════════════════════
# 1 · Byte-identical regression — the canonical Phase 2 fixture
#     renders to the baseline MD5 captured pre-change.  Any renderer
#     change that doesn't opt into preview_text / wrap_links MUST
#     keep this test green.
# ══════════════════════════════════════════════════════════════════


_CANONICAL_FIXTURE = [
    {"type": "heading", "props": {"text": "Hello {{customer.first_name}}",
     "level": 1, "color": "#0f6ed1", "alignment": "left"}},
    {"type": "text", "props": {"html":
     "<p>Visit <a href=\"https://example.com/landing\">our site</a> today.</p>",
     "text_color": "#222222"}},
    {"type": "button", "props": {"label": "Get started",
     "link_url": "https://example.com/go?utm_source=existing",
     "background_color": "#0f6ed1"}},
    {"type": "columns_2", "props": {"ratio": "50/50"},
     "children": [[{"type": "text", "props": {"html": "<p>Left</p>"}}],
                    [{"type": "text", "props": {"html": "<p>Right</p>"}}]]},
    {"type": "footer", "props": {"company_name": "Acme Pool",
     "address": "1 Palm Lane",
     "unsubscribe_link_token": "mailto:info@acme.pool"}},
]

_CANONICAL_MD5 = "06cc4b55a789d009e63a694ac2ffae70"
_CANONICAL_LEN = 2302


def test_byte_identical_canonical_fixture_render():
    """Lock the canonical fixture to the pre-Phase-2 output.

    If any future renderer change breaks this test, that change
    is a regression unless it was intentional AND the baseline
    MD5/len were updated in the same commit.
    """
    html = render_email_html(_CANONICAL_FIXTURE, sample_tokens_context())
    assert len(html) == _CANONICAL_LEN
    assert hashlib.md5(html.encode()).hexdigest() == _CANONICAL_MD5


def test_render_with_preview_text_none_is_byte_identical():
    """Explicitly passing ``preview_text=None`` yields identical
    output to omitting the arg — the parameter is additive, not
    disruptive."""
    a = render_email_html(_CANONICAL_FIXTURE, sample_tokens_context())
    b = render_email_html(_CANONICAL_FIXTURE, sample_tokens_context(),
                            preview_text=None)
    assert a == b


# ══════════════════════════════════════════════════════════════════
# 2 · TD-42 — Nested-columns renderer + depth guard + flat fallback.
# ══════════════════════════════════════════════════════════════════


def test_columns_2_renders_nested_children_with_token_substitution():
    """Columns walk ``children`` recursively.  Tokens inside nested
    text blocks resolve against the shared context."""
    blocks = [{
        "type": "columns_2",
        "props": {"ratio": "50/50"},
        "children": [
            [{"type": "heading",
              "props": {"text": "Hi {{customer.first_name}}", "level": 2}}],
            [{"type": "text",
              "props": {"html": "<p>col2 contents</p>"}}],
        ],
    }]
    html = render_email_html(blocks, sample_tokens_context())
    assert "Hi Alex" in html  # token substituted
    assert "col2 contents" in html


def test_columns_2_flat_html_fallback_when_children_empty():
    """When a column's ``children`` list is empty but the Phase-1
    FIELD_SPECS wrote ``left_html`` / ``right_html`` on props, the
    renderer synthesizes a text block from the flat string."""
    blocks = [{
        "type": "columns_2",
        "props": {
            "ratio": "50/50",
            "left_html": "<p>flat left</p>",
            "right_html": "<p>flat right</p>",
        },
        "children": [[], []],
    }]
    html = render_email_html(blocks, {})
    assert "flat left" in html
    assert "flat right" in html


def test_columns_3_flat_html_fallback_all_three_slots():
    blocks = [{
        "type": "columns_3",
        "props": {
            "left_html": "<p>L</p>",
            "middle_html": "<p>M</p>",
            "right_html": "<p>R</p>",
        },
        "children": [[], [], []],
    }]
    html = render_email_html(blocks, {})
    for marker in ("<p>L</p>", "<p>M</p>", "<p>R</p>"):
        assert marker in html


def test_nested_columns_depth_guard_rejects_at_validator(tenant_id):
    """``columns_2.children[*][*].type in {columns_2, columns_3}``
    must 400 with ``code: nested_columns_unsupported``.  Guards
    the server from a UX disaster + ensures the FE's own depth
    guard isn't the only line of defense."""
    admin = _seed_admin(tenant_id)
    bad = [{
        "type": "columns_2",
        "props": {},
        "children": [
            [{"type": "columns_2", "props": {},
              "children": [[], []]}],  # ← nested columns
            [],
        ],
    }]
    r = requests.post(
        f"{API}/comms/email-templates",
        headers=_auth(admin["token"], tenant_id),
        json={"code": f"p2-nested-{uuid.uuid4().hex[:6]}",
              "name": "Bad nested", "subject": "x",
              "blocks_json": bad},
    )
    assert r.status_code == 400, r.text
    detail = (r.json() or {}).get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "nested_columns_unsupported"


# ══════════════════════════════════════════════════════════════════
# 3 · TD-43 — preview_text / preheader injection.
# ══════════════════════════════════════════════════════════════════


def test_preview_text_injects_hidden_span_at_body_start():
    html = render_email_html(
        [{"type": "text", "props": {"html": "<p>Body</p>"}}],
        {}, preview_text="Hey, we miss you!",
    )
    # Hidden-span styling cocktail present.
    assert "display:none" in html
    assert "mso-hide:all" in html
    # Content present.
    assert "Hey, we miss you!" in html
    # Must appear BEFORE the main table structure (first element
    # inside <body>) so inbox clients grab it as the preheader.
    body_start = html.index("<body")
    first_table = html.index("<table", body_start)
    span_idx = html.index("Hey, we miss you!")
    assert body_start < span_idx < first_table


def test_preview_text_resolves_tokens():
    html = render_email_html(
        [{"type": "text", "props": {"html": "<p>Body</p>"}}],
        sample_tokens_context(),
        preview_text="Hi {{customer.first_name}}, check this out",
    )
    assert "Hi Alex, check this out" in html


def test_preview_text_empty_or_none_emits_no_span():
    for pt in (None, "", "   "):
        html = render_email_html(
            [{"type": "text", "props": {"html": "<p>Body</p>"}}],
            {}, preview_text=pt,
        )
        # No hidden-span marker — byte-identical to pre-Phase-2.
        assert "mso-hide:all" not in html


def test_preview_text_max_length_150_enforced_at_api(tenant_id):
    admin = _seed_admin(tenant_id)
    long_preview = "x" * 151
    r = requests.post(
        f"{API}/comms/email-templates",
        headers=_auth(admin["token"], tenant_id),
        json={"code": f"p2-long-{uuid.uuid4().hex[:6]}",
              "name": "too long preview", "subject": "s",
              "blocks_json": [{"type": "text",
                                "props": {"html": "<p>b</p>"}}],
              "preview_text": long_preview},
    )
    assert r.status_code == 422, r.text


# ══════════════════════════════════════════════════════════════════
# 4 · TD-44 — wrap_links behavior matrix.
# ══════════════════════════════════════════════════════════════════


def test_wrap_links_appends_utm_to_plain_http():
    html = '<a href="https://example.com/landing">Click</a>'
    out = wrap_links(html, context={"template.code": "welcome"},
                      enabled=True)
    assert "utm_source=email" in out
    assert "utm_medium=transactional" in out
    assert "utm_campaign=welcome" in out
    assert "utm_content=welcome" in out


def test_wrap_links_skips_mailto_and_tel():
    html = ('<a href="mailto:foo@bar.com">Email</a>'
             '<a href="tel:+15551234">Call</a>')
    out = wrap_links(html, context={}, enabled=True)
    assert "utm_source" not in out
    assert "mailto:foo@bar.com" in out
    assert "tel:+15551234" in out


def test_wrap_links_skips_anchor_links():
    html = '<a href="#section">Jump</a>'
    out = wrap_links(html, context={}, enabled=True)
    assert "utm_source" not in out
    assert '#section' in out


def test_wrap_links_skips_unsubscribe():
    for href in ("https://portal.example/unsubscribe?token=abc",
                 "https://portal.example/?unsub_token=xyz"):
        html = f'<a href="{href}">Unsub</a>'
        out = wrap_links(html, context={}, enabled=True)
        assert "utm_source" not in out, (href, out)


def test_wrap_links_preserves_already_utm_tagged_links():
    url = "https://example.com/x?utm_source=existing&utm_medium=sms"
    html = f'<a href="{url}">Keep</a>'
    out = wrap_links(html, context={}, enabled=True)
    # The ``utm_source=existing`` wins; no second utm_source gets
    # appended (otherwise the href would contain two).
    assert out.count("utm_source=") == 1
    assert "utm_source=existing" in out


def test_wrap_links_honors_tenant_override():
    html = '<a href="https://example.com/x">Click</a>'
    out = wrap_links(
        html, context={},
        utm_defaults={"utm_source": "newsletter",
                        "utm_campaign": "winter_promo"},
        enabled=True,
    )
    assert "utm_source=newsletter" in out
    assert "utm_campaign=winter_promo" in out
    # Default keys that AREN'T in the override must NOT appear.
    assert "utm_medium=transactional" not in out


def test_wrap_links_passthrough_when_disabled():
    html = '<a href="https://example.com/x">Click</a>'
    out = wrap_links(html, context={}, enabled=False)
    assert out == html


# ══════════════════════════════════════════════════════════════════
# 5 · TD-44 — Tenant UTM admin endpoints.
# ══════════════════════════════════════════════════════════════════


def test_get_tenant_utm_returns_module_defaults_for_fresh_tenant(tenant_id):
    admin = _seed_admin(tenant_id)
    r = requests.get(f"{API}/comms/tenants/current/email-utm",
                      headers=_auth(admin["token"], tenant_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["defaults_source"] == "module_default"
    assert body["utm_defaults"]["utm_source"] == "email"
    assert body["link_wrapping_enabled"] is True


def test_patch_tenant_utm_persists_override(tenant_id):
    admin = _seed_admin(tenant_id)
    r = requests.patch(
        f"{API}/comms/tenants/current/email-utm",
        headers=_auth(admin["token"], tenant_id),
        json={"utm_defaults": {"utm_source": "newsletter",
                                 "utm_campaign": "fall_push"},
              "link_wrapping_enabled": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["utm_defaults"]["utm_source"] == "newsletter"
    assert body["utm_defaults"]["utm_campaign"] == "fall_push"
    assert body["defaults_source"] == "tenant_override"
    # Read-back equally.
    r2 = requests.get(f"{API}/comms/tenants/current/email-utm",
                       headers=_auth(admin["token"], tenant_id))
    assert r2.status_code == 200
    assert r2.json()["utm_defaults"]["utm_source"] == "newsletter"


def test_patch_tenant_utm_rejects_unknown_keys(tenant_id):
    admin = _seed_admin(tenant_id)
    r = requests.patch(
        f"{API}/comms/tenants/current/email-utm",
        headers=_auth(admin["token"], tenant_id),
        json={"utm_defaults": {"not_a_utm": "value"}},
    )
    assert r.status_code == 400, r.text
    detail = (r.json() or {}).get("detail") or {}
    if isinstance(detail, dict):
        assert detail.get("code") == "unknown_utm_key"


def test_patch_tenant_utm_disable_wrapping_persists(tenant_id):
    admin = _seed_admin(tenant_id)
    r = requests.patch(
        f"{API}/comms/tenants/current/email-utm",
        headers=_auth(admin["token"], tenant_id),
        json={"link_wrapping_enabled": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["link_wrapping_enabled"] is False

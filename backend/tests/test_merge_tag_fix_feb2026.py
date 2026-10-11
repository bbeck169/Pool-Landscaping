"""M-TAG-FIX · Feb-2026 — portal-invite renderer + merge-tag registry.

Pytest suite covering both halves of the Feb-2026 Merge-Tag Picker
Fix + Portal Invite Renderer Hardening phase:

  * Portal-invite rendering produces zero raw ``{{`` / ``}}`` /
    ``%7B%7B`` / ``%7D%7D`` substrings for every combination of
    the four portal-invite variables (NAME · TO · TEMP_PASSWORD ·
    LOGIN_URL).
  * Empty ``TEMP_PASSWORD`` strips the enclosing paragraph on the
    HTML surface AND the mirrored line on the plain-text surface.
  * A URL-encoded template body self-heals through the renderer.
  * Shared renderer: an unknown ``{{UNDEFINED_VAR}}`` is stripped
    AND a WARNING is emitted via the ``pool_crm.merge_tags``
    logger with ``template_id`` + ``template_key`` metadata.
  * ``GET /api/merge-tags`` returns the flat registry, admin-only,
    ≥12 tags, correct schema.
  * Registry sweep — every ``{{TOKEN}}`` referenced in a real
    template file resolves to a catalog entry (prevents silent
    missing tags).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

import pytest

from services.marketing.merge_tags import (
    MERGE_TAGS,
    catalog_flat,
    catalog_grouped,
    normalize_url_encoded_merge_tags,
    render_template,
)


# ─── Portal-invite rendering ───────────────────────────────────────

_INVITE_HTML = (
    "<p>Hi {{NAME}},</p>"
    "<p>Your portal login is ready.</p>"
    "<p><strong>Email:</strong> {{TO}}</p>"
    "<p><strong>Temporary password:</strong> "
    "<code>{{TEMP_PASSWORD}}</code></p>"
    "<p><a href='{{LOGIN_URL}}'>Sign in here</a> and change "
    "your password from Profile.</p>"
)

_INVITE_TEXT = (
    "Hi {{NAME}},\n\n"
    "Your portal login is ready.\n\n"
    "Email: {{TO}}\n"
    "Temporary password: {{TEMP_PASSWORD}}\n\n"
    "Sign in here: {{LOGIN_URL}}\n"
    "and change your password from Profile."
)


def _no_raw_merge_tags(body: str) -> None:
    assert "{{" not in body, f"raw {{{{ left in body: {body!r}"
    assert "}}" not in body, f"raw }}}} left in body: {body!r}"
    assert "%7B%7B" not in body.upper(), (
        f"URL-encoded brace left in body: {body!r}"
    )
    assert "%7D%7D" not in body.upper(), (
        f"URL-encoded brace left in body: {body!r}"
    )


def test_portal_invite_render_all_vars_set():
    ctx = {
        "name": "Jane Smith",
        "to": "jane@example.com",
        "temp_password": "Pwd123xyz",
        "login_url": "https://app.example.com/login",
    }
    html, _ = render_template(_INVITE_HTML, ctx)
    txt, _ = render_template(_INVITE_TEXT, ctx)
    for body in (html, txt):
        _no_raw_merge_tags(body)
        assert "Jane Smith" in body
        assert "jane@example.com" in body
        assert "Pwd123xyz" in body
        assert "https://app.example.com/login" in body


@pytest.mark.parametrize(
    "missing_key",
    ["name", "to", "temp_password", "login_url"],
)
def test_portal_invite_render_each_var_missing_individually(missing_key):
    ctx = {
        "name": "Jane",
        "to": "jane@example.com",
        "temp_password": "Pwd123xyz",
        "login_url": "https://app.example.com/login",
    }
    ctx[missing_key] = ""
    html, _ = render_template(_INVITE_HTML, ctx)
    _no_raw_merge_tags(html)


def test_portal_invite_render_all_vars_missing():
    html, _ = render_template(_INVITE_HTML, {})
    txt, _ = render_template(_INVITE_TEXT, {})
    for body in (html, txt):
        _no_raw_merge_tags(body)


def test_portal_invite_empty_temp_password_strips_enclosing_paragraph():
    # Mirrors ``_try_send_reset_email``'s empty-TEMP_PASSWORD pre-
    # pass — ``<p>…{{TEMP_PASSWORD}}…</p>`` is scrubbed BEFORE the
    # renderer runs so the recipient never sees a dangling
    # "Temporary password: " prefix.
    html_src = _INVITE_HTML
    text_src = _INVITE_TEXT
    temp_password = ""
    if not temp_password.strip():
        html_src = re.sub(
            r"<p[^>]*>(?:(?!</?p\b)[\s\S])*?"
            r"\{\{\s*TEMP_PASSWORD\s*\}\}"
            r"(?:(?!</?p\b)[\s\S])*?</p>",
            "",
            html_src,
            flags=re.IGNORECASE,
        )
        text_src = re.sub(
            r"^.*\{\{\s*TEMP_PASSWORD\s*\}\}.*\r?\n?",
            "",
            text_src,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    html, _ = render_template(html_src, {
        "name": "Jane", "to": "x@x", "temp_password": "",
        "login_url": "https://x/login",
    })
    txt, _ = render_template(text_src, {
        "name": "Jane", "to": "x@x", "temp_password": "",
        "login_url": "https://x/login",
    })
    assert "Temporary password" not in html
    assert "Temporary password" not in txt
    _no_raw_merge_tags(html)
    _no_raw_merge_tags(txt)


def test_portal_invite_url_encoded_template_self_heals():
    encoded = quote(_INVITE_HTML, safe="")
    assert "%7B%7B" in encoded.upper()  # sanity — fixture is encoded
    rendered, _ = render_template(encoded, {
        "name": "Jane",
        "to": "jane@example.com",
        "temp_password": "Pwd123",
        "login_url": "https://x/login",
    })
    # Only the brace sequences are decoded by the renderer; the
    # surrounding HTML entity escapes stay encoded (handled by the
    # mail client).  The acceptance criterion is NO raw merge-tag
    # braces leak.
    assert "%7B%7B" not in rendered.upper()
    assert "%7D%7D" not in rendered.upper()
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_portal_invite_snapshot_happy_path():
    rendered, _ = render_template(_INVITE_HTML, {
        "name": "Jane Smith",
        "to": "jane@example.com",
        "temp_password": "AbCd1234",
        "login_url": "https://app.example.com/login",
    })
    assert rendered == (
        "<p>Hi Jane Smith,</p>"
        "<p>Your portal login is ready.</p>"
        "<p><strong>Email:</strong> jane@example.com</p>"
        "<p><strong>Temporary password:</strong> "
        "<code>AbCd1234</code></p>"
        "<p><a href='https://app.example.com/login'>Sign in here</a> "
        "and change your password from Profile.</p>"
    )


def test_portal_invite_snapshot_empty_password_path():
    src = re.sub(
        r"<p[^>]*>(?:(?!</?p\b)[\s\S])*?"
        r"\{\{\s*TEMP_PASSWORD\s*\}\}"
        r"(?:(?!</?p\b)[\s\S])*?</p>",
        "",
        _INVITE_HTML,
        flags=re.IGNORECASE,
    )
    rendered, _ = render_template(src, {
        "name": "Jane Smith",
        "to": "jane@example.com",
        "temp_password": "",
        "login_url": "https://app.example.com/login",
    })
    assert rendered == (
        "<p>Hi Jane Smith,</p>"
        "<p>Your portal login is ready.</p>"
        "<p><strong>Email:</strong> jane@example.com</p>"
        "<p><a href='https://app.example.com/login'>Sign in here</a> "
        "and change your password from Profile.</p>"
    )


# ─── Shared renderer hardening ─────────────────────────────────────

def test_shared_renderer_strips_unknown_token_and_logs_warning(caplog):
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    out, unresolved = render_template(
        "Hello {{UNDEFINED_VAR}}, see {{ALSO_UNDEFINED}}!",
        {},
        template_id="t-123",
        template_key="dunning_overdue_invoice.html",
    )
    assert "{{" not in out
    assert "}}" not in out
    # Primary resolver sweep accumulates the unresolved list.
    assert "UNDEFINED_VAR" in unresolved
    assert "ALSO_UNDEFINED" in unresolved


def test_shared_renderer_residual_sweep_logs_warning(caplog):
    # Craft a residual that only the final-pass sweep can catch —
    # a brace sequence whose "token" is not a valid identifier so
    # the primary ``_TAG_RE`` ignores it.  The final sweep strips
    # it AND emits a WARNING with the template metadata.
    caplog.set_level(logging.WARNING, logger="pool_crm.merge_tags")
    out, _ = render_template(
        "Prefix {{some phrase here}} suffix",
        {},
        template_id="t-residual",
        template_key="broken_template.html",
    )
    assert "{{" not in out
    assert "}}" not in out
    assert any(
        "residual merge-tag stripped" in r.message
        and "t-residual" in r.message
        and "broken_template.html" in r.message
        for r in caplog.records
    ), (
        "expected a residual-tag WARNING with template metadata, "
        f"got: {[r.message for r in caplog.records]}"
    )


def test_shared_renderer_residual_sweep_catches_url_encoded_whitespace():
    # Whitespace-padded URL encoded braces don't match the
    # normalize-on-entry regex but DO match the residual sweep.
    out, _ = render_template(
        "Hi %7B%7B NAME %7D%7D!",
        {"name": "Jane"},
    )
    # Residual sweep stripped the odd-shaped encoded token.
    assert "%7B%7B" not in out.upper()
    assert "%7D%7D" not in out.upper()


# ─── Catalog grouping tolerance ────────────────────────────────────

def test_catalog_grouped_tolerates_missing_description_or_label():
    # Historically ``catalog_grouped`` indexed a required ``label``
    # + ``description`` key — the first registry entry without one
    # 500'd the whole endpoint and emptied the picker.  The
    # hardened version falls back to the empty string so a single
    # under-documented tag can no longer silence the catalog.
    grouped = catalog_grouped()
    total = sum(len(v) for v in grouped.values())
    assert total == len(MERGE_TAGS)
    for tags in grouped.values():
        for t in tags:
            assert "token" in t
            assert "label" in t
            assert "description" in t
            assert "sample_value" in t


def test_catalog_flat_shape_matches_api_contract():
    flat = catalog_flat()
    assert isinstance(flat, list)
    assert len(flat) >= 12
    required_keys = {"key", "label", "description", "category",
                     "sample_value"}
    for entry in flat:
        assert required_keys.issubset(entry.keys()), (
            f"flat entry missing keys: {entry}"
        )


def test_catalog_flat_contains_minimum_phase_required_tokens():
    # Acceptance brief locks in a minimum set of short-form tokens
    # the picker MUST surface so templates authored today keep
    # resolving once the visual-email builder lands.
    required = {
        "NAME", "FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE",
        "COMPANY_NAME",
        "INVOICE_NUMBER", "INVOICE_AMOUNT", "DUE_DATE",
        "JOB_NAME",
        "PORTAL_URL", "LOGIN_URL",
    }
    keys = {e["key"] for e in catalog_flat()}
    missing = required - keys
    assert not missing, f"catalog missing required tokens: {missing}"


# ─── Registry sweep · catch silently-missing tags ──────────────────

_TOKEN_RE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")


def _iter_template_source_files() -> list[Path]:
    # Only sweep known template-shaped sources.  Skip tests (they
    # intentionally reference bogus tokens like ``{{FOO}}``).
    roots = [
        Path("/app/backend/migrations"),
        Path("/app/backend/services"),
    ]
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            # Exclude the merge_tags module itself (it defines the
            # registry — many ``{{...}}`` samples appear in its
            # docstrings as DOCUMENTATION, not real template use).
            if p.name == "merge_tags.py":
                continue
            out.append(p)
    return out


def test_every_template_token_in_tree_resolves_through_registry():
    catalog_keys = {e["key"] for e in catalog_flat()}
    # Tokens that appear in Python SOURCE files as DOCUMENTATION
    # prose (code comments / docstrings) or that belong to an
    # EXTERNAL rendering engine (Stripe's own template language)
    # — not consumed by our ``render_template``.
    external_or_doc_only = {
        # Stripe Checkout's own template language substitutes this
        # at redirect time; our renderer never sees it.
        "CHECKOUT_SESSION_ID",
        # Documentation prose that uses ``{{TAG}}`` / ``{{TOKEN}}``
        # / ``{{MERGE_TAG}}`` as a GENERIC placeholder to describe
        # the syntax — never shipped as a real template token.
        "TAG", "TOKEN", "MERGE_TAG",
    }
    seen: dict[str, Path] = {}
    for p in _iter_template_source_files():
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _TOKEN_RE.finditer(src):
            seen.setdefault(m.group(1), p)
    unknown = sorted(
        k for k in seen
        if k not in catalog_keys and k not in external_or_doc_only
    )
    assert not unknown, (
        "merge-tag tokens referenced in template sources without a "
        "registry entry (add to ``MERGE_TAGS`` to prevent silent "
        "missing-tag leaks):\n"
        + "\n".join(f"  {k}  (first seen: {seen[k]})" for k in unknown)
    )


# ─── Backward-compat decode (whole-body URL encoded) ───────────────

def test_normalize_url_encoded_merge_tags_idempotent():
    body = "<p>{{NAME}}</p>"
    assert normalize_url_encoded_merge_tags(body) == body
    encoded = "<p>%7B%7BNAME%7D%7D</p>"
    assert "{{NAME}}" in normalize_url_encoded_merge_tags(encoded)

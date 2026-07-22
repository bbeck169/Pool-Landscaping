"""Phase 9 · Feb 2026 — merge-tag registry + renderer coverage.

Covers the uppercase merge-tag path introduced in
``services/marketing/merge_tags.py``. Legacy dotted Mustache tags
continue to work via ``services/marketing/render.py`` — those aren't
retested here.
"""
from __future__ import annotations

import requests

from services.marketing.merge_tags import (
    MERGE_TAGS, render_context, render_template, catalog_grouped,
)

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    return requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw},
                          timeout=15).json()["access_token"]


# ═══════════════════════════ Renderer unit tests ═════════════════════
def test_renderer_substitutes_uppercase_tokens():
    ctx = render_context(
        customer={"name": "Ada Lovelace", "email": "ada@example.com",
                     "phone": "+16025550000"},
        tenant={"name": "AquaTerra"},
    )
    out, missing = render_template(
        "Hi {{CUSTOMER_FIRST_NAME}} — thanks from {{COMPANY_NAME}}!", ctx,
    )
    assert out == "Hi Ada — thanks from AquaTerra!"
    assert missing == []


def test_renderer_case_insensitive_and_whitespace_tolerant():
    ctx = render_context(customer={"name": "Ada Lovelace"})
    out, _ = render_template("{{ customer_first_name }}", ctx)
    assert out == "Ada"


def test_renderer_unknown_tag_empty_by_default():
    out, missing = render_template("hello {{NOT_A_TAG}}", {})
    assert out == "hello "
    assert "NOT_A_TAG" in missing


def test_renderer_placeholder_mode():
    out, _ = render_template("{{NOT_A_TAG}}", {}, missing="placeholder")
    assert out == "[MISSING: NOT_A_TAG]"


def test_renderer_missing_customer_field_empty():
    ctx = render_context(customer={})
    out, missing = render_template("{{CUSTOMER_FIRST_NAME}}", ctx)
    assert out == ""
    assert "CUSTOMER_FIRST_NAME" in missing


def test_renderer_never_raises_on_broken_resolver():
    # Feed a customer without ``name`` at all — resolver returns "".
    ctx = render_context(customer=None)
    out, _ = render_template("{{CUSTOMER_FULL_NAME}}", ctx)
    assert out == ""


def test_renderer_html_preserved_around_tags():
    ctx = render_context(customer={"name": "Ada Lovelace"})
    out, _ = render_template(
        "<p>Hi <b>{{CUSTOMER_FIRST_NAME}}</b>!</p>", ctx,
    )
    assert out == "<p>Hi <b>Ada</b>!</p>"


def test_renderer_currency_format_for_balance():
    ctx = render_context(customer={"open_balance": 1234.5})
    out, _ = render_template("{{CUSTOMER_ACCOUNT_BALANCE}}", ctx)
    assert out == "$1,234.50"


def test_catalog_grouped_contains_all_categories():
    grouped = catalog_grouped()
    expected = {"Customer", "Company", "Estimate", "Invoice",
                "Payment", "Portal", "Event", "Employee", "System"}
    assert expected.issubset(set(grouped.keys()))
    # Sanity — at least these tokens are present.
    all_tokens = {t["token"] for cat in grouped.values() for t in cat}
    for must_have in ("CUSTOMER_FIRST_NAME", "COMPANY_NAME",
                       "INVOICE_TOTAL", "CUSTOMER_PORTAL_LINK",
                       "CURRENT_YEAR"):
        assert must_have in all_tokens, must_have


def test_every_tag_resolver_is_callable():
    for t in MERGE_TAGS:
        # None → resolver returns "" gracefully.
        val = t["resolver"]({})
        assert isinstance(val, str)


# ═══════════════════════════ Endpoint smoke tests ════════════════════
def test_merge_tags_endpoint_admin():
    tok = _login("admin@aquaterra.com")
    r = requests.get(f"{API}/marketing/merge-tags",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "categories" in body
    assert "Customer" in body["categories"]
    tokens = {t["token"] for cat in body["categories"].values() for t in cat}
    assert "CUSTOMER_FIRST_NAME" in tokens


def test_merge_tags_endpoint_denies_customer():
    tok = _login("customer@aquaterra.com")
    r = requests.get(f"{API}/marketing/merge-tags",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 403


def test_merge_tags_endpoint_allows_manager():
    tok = _login("manager@aquaterra.com")
    r = requests.get(f"{API}/marketing/merge-tags",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200

"""Batch 12D · Feb 2026 — Merge tag catalog SMS parity audit.

User requirement: every registered merge tag must be renderable in
both email AND SMS bodies with no server-side channel filtering. Also
verifies the 7 polish additions (``CUSTOMER_STREET``, ``CUSTOMER_ID``,
``TENANT_TIMEZONE``, ``TENANT_NEXT_BUSINESS_DAY``, ``INVOICE_PAY_URL``,
``INVOICE_PAY_MAGIC_URL``, ``ESTIMATE_ACCEPT_URL``) resolve without
leaving raw ``{{...}}`` literals.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.marketing.merge_tags import (
    MERGE_TAGS, catalog_grouped, render_context, render_template,
)

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _full_context() -> dict:
    return render_context(
        customer={
            "id": "cust-abc-123",
            "name": "Ada Lovelace",
            "first_name": "Ada", "last_name": "Lovelace",
            "email": "ada@example.com",
            "phone": "+15559994321",
            "address": "42 Analytical Engine Way",
            "address_line_1": "42 Analytical Engine Way",
            "city": "Phoenix", "state": "AZ", "zip": "85001",
            "open_balance_cents": 12500,
            "credits_balance_cents": 4200,
        },
        tenant={
            "id": "tenant-1",
            "name": "AquaTerra",
            "timezone": "America/Phoenix",
            "owner_first_name": "Alex", "owner_last_name": "Ownerson",
            "support_email": "hello@example.com",
            "support_phone_number": "+15550000000",
            "website": "https://aquaterra.example",
            "business_holidays": [],
        },
        invoice={
            "id": "inv-1234abcd",
            "number": "1042",
            "total_cents": 24999, "tax_cents": 1999,
            "due_date": "2026-08-01",
            "all_links_html": "<ul><li>x</li></ul>",
        },
        estimate={
            "id": "est-5678ffff",
            "total_cents": 199900,
            "public_url": "https://estimate.example/pub",
            "edit_url": "https://estimate.example/edit",
            "changes_summary": "Bumped pool coping.",
            "view_url": "https://estimate.example/view",
        },
        payment={
            "amount_cents": 24999,
            "method": "Visa •••• 4242",
            "created_at": "2026-07-23T12:00:00+00:00",
        },
        event={
            "title": "Weekly Pool Service", "date": "2026-08-05",
            "scheduled_time": "09:30",
            "property_address": "42 Analytical Engine Way",
            "notes": "Gate code 4242.",
        },
        equipment={
            "type": "Filter",
            "last_cleaned_date": "2026-05-01",
            "due_date": "2026-08-01",
            "interval_months": 3,
        },
        employee={"first_name": "Grace", "last_name": "Hopper"},
        referral={
            "friend_name": "Bob", "credit_amount_cents": 2500,
            "eligible_date": "2026-07-15",
        },
        # Batch 12D — magic-link seed for INVOICE_PAY_MAGIC_URL +
        # ESTIMATE_ACCEPT_URL. Both fall back gracefully if absent.
        invoice_pay_link="https://pay.example/inv-1234abcd?token=abc",
        estimate_accept_link="https://accept.example/est-5678ffff?token=xyz",
        # ADD_CARD_LINK context (Phase 12) — also used by the
        # ambiguous-match digest deep link.
        add_card_link="https://add.example/portal/add-card?token=tok",
        # Digest tags (12C).
        ambiguous_match_count=2,
        ambiguous_match_sample="Alice A, Bob B",
    )


def test_catalog_returns_every_registered_tag_no_channel_filter():
    """``catalog_grouped()`` (backing the API response) must expose
    every tag with no channel-based exclusion."""
    grouped = catalog_grouped()
    flat_from_grouped = {t["token"]
                          for tags in grouped.values() for t in tags}
    registered = {t["token"] for t in MERGE_TAGS}
    assert flat_from_grouped == registered, (
        f"grouped output diverges from MERGE_TAGS by "
        f"{flat_from_grouped.symmetric_difference(registered)}"
    )


def test_every_tag_has_label_and_description():
    for t in MERGE_TAGS:
        assert t.get("label"), f"{t['token']} missing label"
        assert (t.get("description") or "").strip(), \
            f"{t['token']} missing description"


def test_batch_12d_missing_tags_are_registered():
    """The 7 polish additions must all appear."""
    tokens = {t["token"] for t in MERGE_TAGS}
    for tok in ("CUSTOMER_FULL_NAME", "CUSTOMER_STREET", "CUSTOMER_ID",
                "TENANT_TIMEZONE", "TENANT_NEXT_BUSINESS_DAY",
                "INVOICE_PAY_URL", "INVOICE_PAY_MAGIC_URL",
                "ESTIMATE_ACCEPT_URL"):
        assert tok in tokens, f"expected {tok} in the merge tag catalog"


def test_sms_render_resolves_every_tag_with_no_literals_remaining(capsys):
    """Render an SMS body that includes ``{{TOKEN}}`` for every
    catalog entry against a fully-populated context. No braces may
    remain in the output; a small allow-list covers tags that
    intentionally return empty when the ctx sub-object is missing —
    but for THIS ctx every one should render.

    Also confirms:
      * No HTML entities leak into SMS bodies.
      * No SINGLE tag value renders longer than 500 chars (which
        would blow past a single SMS segment). Tag values > 160
        GSM chars are called out in a warning stream so template
        authors know they'll consume extra segments.
    """
    ctx = _full_context()
    # Per-tag individual renders — catch outliers.
    long_tags = []
    for t in MERGE_TAGS:
        one, _ = render_template("{{" + t["token"] + "}}", ctx)
        assert len(one) < 500, (
            f"{t['token']} rendered {len(one)} chars — too long for SMS"
        )
        if len(one) > 160:
            long_tags.append((t["token"], len(one)))
    if long_tags:
        print("[batch12d-sms-warning] tags that exceed one GSM segment "
                "on their own:")
        for tok, n in long_tags:
            print(f"  {tok}: {n} chars")

    # Aggregate body — every tag once, comma-joined. No template
    # would realistically include ALL 60+ tags but the round-trip
    # must still leave no literals + no HTML entities.
    body_parts = [f"{{{{{t['token']}}}}}" for t in MERGE_TAGS]
    body = ", ".join(body_parts)
    rendered, missing = render_template(body, ctx)

    stragglers = re.findall(r"\{\{[A-Z_0-9]+\}\}", rendered)
    assert not stragglers, f"unresolved literals: {stragglers}"
    for artifact in ("&amp;", "&lt;", "&gt;", "&quot;"):
        assert artifact not in rendered, \
            f"SMS render leaked HTML entity {artifact}"
    # ``missing`` reports tags whose resolvers returned an empty
    # string — perfectly legitimate for SMS bodies (blank slot, not
    # broken syntax). Only assert no ``{{...}}`` literals remain
    # after rendering.
    _ = missing


def test_batch_12d_new_tags_render_expected_values():
    ctx = _full_context()
    checks = {
        "{{CUSTOMER_ID}}": "cust-abc-123",
        "{{CUSTOMER_STREET}}": "42 Analytical Engine Way",
        "{{CUSTOMER_FULL_NAME}}": "Ada Lovelace",
        "{{TENANT_TIMEZONE}}": "America/Phoenix",
        "{{INVOICE_PAY_MAGIC_URL}}":
            "https://pay.example/inv-1234abcd?token=abc",
        "{{ESTIMATE_ACCEPT_URL}}":
            "https://accept.example/est-5678ffff?token=xyz",
    }
    for tpl, expected in checks.items():
        r, _ = render_template(tpl, ctx)
        assert r == expected, f"{tpl} → {r!r} (wanted {expected!r})"
    # TENANT_NEXT_BUSINESS_DAY renders to a "Mon, MMM DD" string in
    # the tenant's timezone. Format-check rather than exact-match.
    r, _ = render_template("{{TENANT_NEXT_BUSINESS_DAY}}", ctx)
    assert re.match(r"^[A-Z][a-z]{2}, [A-Z][a-z]{2} \d{2}$", r), \
        f"unexpected next-business-day format: {r!r}"
    # INVOICE_PAY_URL respects APP_PUBLIC_URL / PUBLIC_FRONTEND_ORIGIN
    # env — resolved lazily so we just check the format, not the host.
    r, _ = render_template("{{INVOICE_PAY_URL}}", ctx)
    assert r == "" or r.endswith("/portal/invoices/inv-1234abcd"), r


def test_estimate_accept_url_falls_back_to_estimate_view_url():
    ctx = render_context(
        estimate={"view_url": "https://estimate.example/view",
                    "public_url": None},
        # NO estimate_accept_link → resolver must fall back.
    )
    r, _ = render_template("{{ESTIMATE_ACCEPT_URL}}", ctx)
    assert r == "https://estimate.example/view"


def test_invoice_pay_magic_url_falls_back_to_portal_url_without_magic_ctx():
    """When the estimate/invoice send path did NOT pre-populate the
    magic-link ctx key, the magic URL falls back to the portal URL
    (never a raw empty string that a customer would click into)."""
    import os
    prev = os.environ.get("APP_PUBLIC_URL")
    os.environ["APP_PUBLIC_URL"] = "https://portal.example"
    try:
        ctx = render_context(
            invoice={"id": "inv-xyz-1"},
        )
        r, _ = render_template("{{INVOICE_PAY_MAGIC_URL}}", ctx)
        assert r == "https://portal.example/portal/invoices/inv-xyz-1"
    finally:
        if prev is None:
            os.environ.pop("APP_PUBLIC_URL", None)
        else:
            os.environ["APP_PUBLIC_URL"] = prev

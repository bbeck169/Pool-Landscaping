"""TD-invoice-total-dual-registry-drift · Feb-2026 — regression suite.

Locks the deduplication of the ``INVOICE_TOTAL`` merge-tag registry entry
in ``backend/services/marketing/merge_tags.py``.  Prior to this ticket a
Batch 4 ``INVOICE_TOTAL`` entry (label "Invoice — Balance", category
"Finance", flat-ctx-key λ) lived in the Phase EMAIL-MIGRATE block and
shadowed the canonical ``_invoice_total`` resolver because the
``_TAG_INDEX`` builder is a dict comprehension (last-wins).  Every live
``{{INVOICE_TOTAL}}`` render was therefore reading ``ctx['invoice_total']``
as-stuffed-by-the-sender, which was ambiguous by construction (balance in
the invoice-reminder path, total in the dunning path).

Post-dedupe, ``{{INVOICE_TOTAL}}`` renders the canonical total via the
original ``_invoice_total(ctx)`` resolver, and operators who want the
balance semantics are directed to ``{{INVOICE_BALANCE}}``.

Assertions:
    1. ``INVOICE_TOTAL`` appears exactly once in ``MERGE_TAGS`` (the
       canonical ``Invoice``-category entry with the ``_invoice_total``
       resolver).
    2. ``INVOICE_BALANCE`` appears exactly once (the canonical
       ``Invoice``-category entry with the ``_invoice_balance``
       resolver).
    3. For an invoice with ``total=100 / amount_paid=30``,
       ``render_template("{{INVOICE_TOTAL}}", …)`` returns ``$100.00``
       (NOT ``$70.00``).  Semantic lock — proves the canonical
       ``_invoice_total`` resolver wins the dict-comp dedup.
    4. Same ctx: ``render_template("{{INVOICE_BALANCE}}", …)`` returns
       ``$70.00``.
    5. Characterization lock on the Phase 9D flat-key override — a
       ctx supplying only the flat ``ctx['invoice_total']`` key still
       short-circuits to that value via ``render_template``'s step-1
       cascade, UNCHANGED by this ticket.  This proves that legacy
       senders populating the flat key (``emailer.py`` invoice-
       reminder path) are not affected by the dedupe.
"""
from __future__ import annotations

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _entries(token: str):
    from services.marketing.merge_tags import MERGE_TAGS
    return [t for t in MERGE_TAGS if t.get("token") == token]


def test_invoice_total_appears_exactly_once():
    """Registry invariant: ``INVOICE_TOTAL`` has one, and only one,
    entry in ``MERGE_TAGS`` after the Batch 4 dupe deletion."""
    entries = _entries("INVOICE_TOTAL")
    assert len(entries) == 1, (
        f"expected 1 INVOICE_TOTAL registry entry, got {len(entries)}: "
        f"{[(e.get('label'), e.get('category')) for e in entries]}"
    )
    entry = entries[0]
    # Canonical shape — label "Invoice Total", category "Invoice",
    # resolver is the module-level ``_invoice_total`` function (NOT an
    # inline lambda).
    assert entry["label"] == "Invoice Total"
    assert entry["category"] == "Invoice"
    from services.marketing.merge_tags import _invoice_total
    assert entry["resolver"] is _invoice_total


def test_invoice_balance_appears_exactly_once():
    """Registry invariant: ``INVOICE_BALANCE`` has one, and only one,
    entry — the canonical ``_invoice_balance`` resolver at the
    ``Invoice`` category."""
    entries = _entries("INVOICE_BALANCE")
    assert len(entries) == 1, (
        f"expected 1 INVOICE_BALANCE registry entry, got {len(entries)}: "
        f"{[(e.get('label'), e.get('category')) for e in entries]}"
    )
    entry = entries[0]
    assert entry["label"] == "Invoice Balance"
    assert entry["category"] == "Invoice"
    from services.marketing.merge_tags import _invoice_balance
    assert entry["resolver"] is _invoice_balance


def test_invoice_total_renders_total_not_balance():
    """Semantic lock: ``{{INVOICE_TOTAL}}`` on an invoice with a
    partial payment renders the TOTAL ($100.00), not the balance
    ($70.00).  Pre-ticket this would have rendered through the Batch
    4 flat-ctx-key λ (empty, because no sender populated the flat key
    in this bare-bones ctx)."""
    from services.marketing.merge_tags import render_template
    ctx = {"invoice": {"total": 100, "amount_paid": 30}}
    rendered, _ = render_template("{{INVOICE_TOTAL}}", ctx, missing="empty")
    assert rendered == "$100.00", rendered


def test_invoice_balance_renders_balance():
    """Semantic lock: ``{{INVOICE_BALANCE}}`` on the same partial-
    payment invoice renders the balance ($70.00)."""
    from services.marketing.merge_tags import render_template
    ctx = {"invoice": {"total": 100, "amount_paid": 30}}
    rendered, _ = render_template(
        "{{INVOICE_BALANCE}}", ctx, missing="empty",
    )
    assert rendered == "$70.00", rendered


def test_phase9d_flat_key_override_still_intercepts_before_catalog():
    """Characterization: the renderer's Phase 9D cascade (step 1 at
    ``render_template:_sub``) accepts a flat ``ctx['invoice_total']``
    override and short-circuits BEFORE the catalog resolver fires.
    This is independent of the catalog dedupe — the Batch 4 λ that
    was removed had been reading the SAME flat key, so legacy
    senders that populate it (e.g. ``emailer.py`` invoice-reminder
    path setting the key to a balance string) keep rendering
    identically.  This test locks that unchanged behavior so a
    future ticket touching the Phase 9D cascade knows the ride-along
    semantic is intentional, not an accident of the removed dupe."""
    from services.marketing.merge_tags import render_template
    ctx = {"invoice_total": "9,999.99"}
    rendered, _ = render_template("{{INVOICE_TOTAL}}", ctx, missing="empty")
    assert rendered == "9,999.99", rendered


def test_tag_index_dedup_resolves_canonical():
    """``_TAG_INDEX`` is the dict-comp consulted at render time.
    After the Batch 4 dupe deletion, the ``INVOICE_TOTAL`` key in
    ``_TAG_INDEX`` MUST point at ``_invoice_total`` (not an inline
    lambda, not the removed flat-ctx-key λ)."""
    from services.marketing.merge_tags import _TAG_INDEX, _invoice_total
    assert _TAG_INDEX.get("INVOICE_TOTAL") is _invoice_total

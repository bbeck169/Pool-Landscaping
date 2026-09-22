"""Phase P30.2 · Feb-2026 — source-lint guardrail.

Zero preview-host hits are permitted inside ``backend/routers/customers.py``.

Background
----------
P30 (Feb-2026) migrated the card-add-on-file flow to
``PUBLIC_FRONTEND_ORIGIN`` + ``tenant.brand.public_origin`` +
``https://app.plofv.com`` as the canonical three-tier URL fallback.
A tester found one straggler on line 5127 — the K43 ACH bank
re-verification email handler still hardcoded
``poolscape-audit.preview.emergentagent.com`` as its final
fallback, which would silently ship a preview-host link to a
production customer if both ``PUBLIC_FRONTEND_ORIGIN`` and
``tenant.brand.public_origin`` were unset.

This test locks in the fix: a static ``grep`` against the router
source guarantees the preview-host string is never re-introduced.
Any future URL-construction site added to the router that reaches
for the same convenient-but-wrong literal will trip this test at
CI time and force the author to use the canonical pattern.
"""
from __future__ import annotations

from pathlib import Path


_CUSTOMERS_ROUTER = Path(__file__).resolve().parents[1] / "routers" / "customers.py"

_BANNED = (
    "preview.emergentagent.com",
    "poolscape-audit.preview",
)


def test_p30_2_no_preview_host_in_customers_router():
    """Fail loudly if any preview-host literal creeps back into the
    customers router. Every URL fallback in this module MUST use
    ``PUBLIC_FRONTEND_ORIGIN`` → ``tenant.brand.public_origin`` →
    ``https://app.plofv.com`` (the P30 canonical ladder)."""
    src = _CUSTOMERS_ROUTER.read_text(encoding="utf-8")
    hits = {
        needle: [
            f"line {i}: {ln.rstrip()}"
            for i, ln in enumerate(src.splitlines(), start=1)
            if needle in ln
        ]
        for needle in _BANNED
    }
    hits = {k: v for k, v in hits.items() if v}
    assert not hits, (
        "P30.2 guardrail violated — preview-host literal reintroduced "
        f"into {_CUSTOMERS_ROUTER}. Use the P30 canonical fallback "
        "ladder (PUBLIC_FRONTEND_ORIGIN → tenant.brand.public_origin "
        f"→ https://app.plofv.com). Hits: {hits}"
    )


def test_p30_2_customers_router_uses_canonical_prod_default():
    """Positive assertion — the canonical fallback literal
    ``https://app.plofv.com`` is present at least twice (once for
    the P30 ``send_card_add_link`` handler and once for the K43
    ACH re-verification handler)."""
    src = _CUSTOMERS_ROUTER.read_text(encoding="utf-8")
    occurrences = src.count("https://app.plofv.com")
    assert occurrences >= 2, (
        "P30.2 canonical fallback ``https://app.plofv.com`` should "
        f"appear at least twice in customers.py; found {occurrences}"
    )

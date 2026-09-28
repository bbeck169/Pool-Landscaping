"""PDF-HUB · Feb-2026 — payment-commit dollar → cents audit.

Locks the round-based conversion pattern for any code path that
turns a dollar amount into integer cents. See
``services/imports/money.py`` for the implementation.

**Audit finding (recon):** the PDF payment-commit path in
``services/imports/pdf_commit._commit_payment_previews`` currently
stores ``amount`` as a ``float`` in dollars, NOT as
``amount_cents``. This helper is therefore not invoked on the
write path today; it exists so that a future migration of
``db.payments`` to integer cents (or any downstream aggregation)
picks up the correct rounding by default.

The 5 mandatory conversion cases from the PDF-HUB brief are
exercised here plus a set of edge-null cases.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════
# §1 · The 5 brief-mandated conversion cases
# ═══════════════════════════════════════════════════════════════════
def test_1995_hundredths_rounds_to_1995_cents():
    """``19.95 * 100 == 1994.9999999999998`` in IEEE-754 — a
    truncation-only conversion returns 1994 (a 1¢ off-by-one bug
    on every $x.95 payment). Rounding to nearest integer fixes it."""
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe(19.95) == 1995


def test_100_dollars_exact_returns_10000_cents():
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe(100.00) == 10000


def test_one_cent_returns_1_cent():
    """Smallest positive amount; guards against precision loss on
    very small floats."""
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe(0.01) == 1


def test_three_plus_decimal_source_rounds_to_nearest_cent():
    """1234.567 rounds to 1234.57 dollars → 123457 cents."""
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe(1234.567) == 123457


def test_none_raises_value_error_with_legible_message():
    """The commit path must decide skip-vs-error at the call site,
    so the helper refuses to guess for None inputs."""
    from services.imports.money import dollars_to_cents_safe
    with pytest.raises(ValueError) as exc_info:
        dollars_to_cents_safe(None)
    assert "None" in str(exc_info.value)


def test_empty_string_raises_value_error():
    from services.imports.money import dollars_to_cents_safe
    with pytest.raises(ValueError) as exc_info:
        dollars_to_cents_safe("")
    assert "empty" in str(exc_info.value).lower()


# ═══════════════════════════════════════════════════════════════════
# §2 · Adjacent regression cases
# ═══════════════════════════════════════════════════════════════════
def test_numeric_string_input_is_accepted():
    """PDF payloads sometimes arrive as JSON strings, e.g. from the
    LLM's structured output. Helper must handle ``"19.95"`` too."""
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe("19.95") == 1995


def test_zero_returns_zero_cents():
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe(0) == 0
    assert dollars_to_cents_safe(0.0) == 0


def test_negative_amount_preserves_sign():
    """Refund / correction commits may pass negative dollars."""
    from services.imports.money import dollars_to_cents_safe
    assert dollars_to_cents_safe(-19.95) == -1995


def test_non_numeric_string_bubbles_valueerror():
    """Non-numeric strings must surface as ValueError so callers
    can distinguish "missing" (None) from "malformed" (bad string)."""
    from services.imports.money import dollars_to_cents_safe
    with pytest.raises(ValueError):
        dollars_to_cents_safe("not-a-number")


# ═══════════════════════════════════════════════════════════════════
# §3 · Regression guard — commit path still stores float dollars
# ═══════════════════════════════════════════════════════════════════
def test_pdf_commit_still_stores_amount_as_float_dollars():
    """Recon finding lock: the ``_commit_payment_previews`` path in
    ``services/imports/pdf_commit.py`` stores ``amount`` as a
    ``float`` (dollars), NOT as ``amount_cents`` (integer cents).

    This test scans the source so a future change that silently
    switches the schema (or, worse, introduces a truncation-only
    ``int(x * 100)`` pattern in the commit lane) trips this
    regression guard and re-opens the payment-cents audit."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "services" / "imports" / "pdf_commit.py"
    text = src.read_text()
    # Canonical write pattern for the payment doc.
    assert '"amount": float(pi.get("amount_paid")' in text, (
        "pdf_commit._commit_payment_previews no longer stores "
        "``amount`` as float dollars — re-run the PDF-HUB payment "
        "cents audit before landing schema changes to db.payments."
    )
    # Guard against a truncation-only cents pattern sneaking in.
    assert "int(amount_paid * 100)" not in text, (
        "Found `int(amount_paid * 100)` — this is a truncation-only "
        "cents conversion. Use services.imports.money."
        "dollars_to_cents_safe instead."
    )
    assert "int(float(amount_paid) * 100)" not in text, (
        "Found `int(float(amount_paid) * 100)` — this is a "
        "truncation-only cents conversion. Use services.imports."
        "money.dollars_to_cents_safe instead."
    )

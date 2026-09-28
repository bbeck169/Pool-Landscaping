"""PDF-HUB · Feb-2026 — currency conversion helpers.

Locks the correct dollar→cents pattern for any code path that
needs an integer-cents value from a user-supplied dollar amount.
The PDF payment commit path currently stores ``amount`` as a
``float`` in dollars (see ``pdf_commit._commit_payment_previews``)
so this helper is NOT invoked on the write path today.

It exists to:

1. Provide a single, tested implementation of the round-based
   pattern so future migrations (float dollars → integer cents)
   or downstream aggregations pick up the correct behaviour by
   default.
2. Serve as the target of the ``test_pdf_hub_payment_cents.py``
   audit suite — the tests exercise the helper directly, proving
   the rounding is right for the tricky ``19.95 * 100 == 1994.99...``
   family of floats.

Contract:
    * ``None`` or ``""`` → raises ``ValueError`` with a legible
      message so the caller must decide skip-vs-error.
    * Truthy numbers → ``int(round(float(value) * 100))``.
      ``round`` is mandatory (never truncation-only) — otherwise
      ``19.95 * 100 == 1994.9999...`` truncates to ``1994``.
"""
from __future__ import annotations

from typing import Union


def dollars_to_cents_safe(amount: Union[int, float, str, None]) -> int:
    """Convert a dollar amount to integer cents using ``round``.

    Rejects ``None`` / empty-string with ``ValueError`` — the
    caller must pick between "skip this row" and "hard-fail" for
    missing values. Accepts numeric strings (``"19.95"``) so the
    helper is safe to call directly on JSON-decoded payloads
    where the value may arrive as a string.

    Examples::

        >>> dollars_to_cents_safe(19.95)
        1995
        >>> dollars_to_cents_safe(100.00)
        10000
        >>> dollars_to_cents_safe(0.01)
        1
        >>> dollars_to_cents_safe(1234.567)
        123457
        >>> dollars_to_cents_safe("19.95")
        1995
    """
    if amount is None:
        raise ValueError(
            "dollars_to_cents_safe: value is None; caller must "
            "decide whether to skip or hard-fail the row."
        )
    if isinstance(amount, str):
        stripped = amount.strip()
        if stripped == "":
            raise ValueError(
                "dollars_to_cents_safe: value is empty string; "
                "caller must decide whether to skip or hard-fail."
            )
        amount = stripped
    # ``float()`` will raise ``ValueError`` on non-numeric strings —
    # bubble that up unchanged (message is already precise).
    dollars = float(amount)
    return int(round(dollars * 100))


__all__ = ["dollars_to_cents_safe"]

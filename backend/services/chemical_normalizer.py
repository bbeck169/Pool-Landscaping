"""CHEM-LOCK · Feb-2026 — Chemical entry read-boundary normalizer.

Rationale
---------
Historical drift on the ``service_reports.chemicals_added[]`` shape:

* Tech-app writer (``frontend/src/pages/tech/ServiceReport.jsx``) has
  written **``amount``** since the report was introduced.
* Newer backend consumers (``service_report_view``,
  ``public_service_images``) prefer **``quantity``** per the P0-era
  chemistry-catalog rewrite.
* Two renderers were still ``amount``-only:
  ``auto_visit_email._pool_body_sections`` and the portal FE flat-
  chemicals block. That is what caused the "chemicals missing on
  portal-visible service reports" ticket.

Read-boundary fix (this module)
-------------------------------
Every renderer that needs to emit a chemical row goes through
:func:`normalize_chemical` which:

1. Accepts the raw entry (dict-only; falsy → ``None`` returned).
2. Prefers ``quantity``, falls back to ``amount`` (then ``qty``).
3. If BOTH ``quantity`` and ``amount`` are present with meaningful
   values, prefers ``quantity`` and emits a ``logger.debug`` line
   flagging the duplication so ops can clean the write-side later.
4. Accepts either ``name`` or ``chemical`` as the display name.
5. Returns ``None`` when the entry is genuinely blank (no name,
   no quantity, no amount, no raw_label) so callers can skip
   rendering rather than emit an empty row.

The output shape is deliberately narrow:

.. code-block:: python

    {
        "name":       str | None,   # display name — never empty
        "quantity":   float | int | str | None,   # coerced when possible
        "unit":       str | None,   # trimmed; None if blank
        "raw_label":  str | None,   # tech's freeform text if any
    }

We do NOT run a data-side migration in this phase (per the CHEM-LOCK
brief). This is a strict read-side shim — old ``amount``-only rows
render fine after this change.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from config import logger


_BLANK_VALUES: tuple = (None, "", 0, "0")


def _coerce_qty(v: Any) -> Optional[Any]:
    """Return ``None`` for blank quantities, otherwise the raw value.

    We deliberately DO NOT force a float cast — the tech FE writes
    strings ("1.5") and the historical Mongo rows also store them
    as strings. Downstream renderers (portal + emails) print them
    verbatim, so preserving the original type is correct.
    """
    if v in _BLANK_VALUES:
        return None
    return v


def normalize_chemical(entry: Any) -> Optional[Dict[str, Any]]:
    """Return the canonical read-side shape or ``None`` if the row is
    genuinely blank.

    Preference order for the quantity field: ``quantity`` > ``amount``
    > ``qty``. If ``quantity`` AND ``amount`` are BOTH present with
    non-blank values, a ``logger.debug`` line is emitted so ops can
    dedupe on the write side later.
    """
    if not isinstance(entry, dict):
        return None

    raw_quantity = _coerce_qty(entry.get("quantity"))
    raw_amount = _coerce_qty(entry.get("amount"))
    raw_qty_alt = _coerce_qty(entry.get("qty"))

    # Duplication check — prefer ``quantity``; log the drift.
    if raw_quantity is not None and raw_amount is not None:
        # Only log when they DISAGREE — matching values are harmless
        # (writer just mirrored both fields, which is exactly what
        # the CHEM-LOCK forward-compat migration recommends).
        if str(raw_quantity) != str(raw_amount):
            logger.debug(
                "[chem-normalize] duplicate quantity/amount on entry "
                "(quantity=%r, amount=%r) — preferring quantity; "
                "name=%r raw_label=%r",
                raw_quantity, raw_amount,
                entry.get("name") or entry.get("chemical"),
                entry.get("raw_label"),
            )

    quantity = raw_quantity if raw_quantity is not None else (
        raw_amount if raw_amount is not None else raw_qty_alt
    )

    name_raw = entry.get("name") or entry.get("chemical")
    name = str(name_raw).strip() if name_raw is not None else ""
    unit_raw = entry.get("unit") or entry.get("default_unit")
    unit = str(unit_raw).strip() if unit_raw is not None else ""
    raw_label_raw = entry.get("raw_label")
    raw_label = str(raw_label_raw).strip() if raw_label_raw is not None else ""

    # Blank-row skip: nothing rendered would be meaningful.
    if not name and quantity is None and not raw_label:
        return None

    return {
        "name": name or None,
        "quantity": quantity,
        "unit": unit or None,
        "raw_label": raw_label or None,
    }


def format_chemical_line(entry: Any, *, sep: str = " — ") -> Optional[str]:
    """Convenience wrapper used by the plain-text email fallback.

    Returns ``None`` iff :func:`normalize_chemical` skipped the row
    (i.e. it was genuinely blank).
    """
    norm = normalize_chemical(entry)
    if norm is None:
        return None
    name = norm["name"] or "Chemical"
    qty = norm["quantity"]
    unit = norm["unit"] or ""
    if qty is None and not unit:
        return name
    qty_str = "" if qty is None else str(qty)
    unit_str = f" {unit}" if unit else ""
    return f"{name}{sep}{qty_str}{unit_str}".rstrip()

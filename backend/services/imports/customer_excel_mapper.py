"""TD-customer-ai-excel-csv-import · Feb-2026
=============================================

AI-powered Excel/CSV ingestion mapper for the Customers importer.
Mirrors the posture of :mod:`services.imports.pdf_mapper` for
invoices — accept arbitrary column shapes, let the LLM resolve
them to the canonical customer schema, hand downstream code a
list of normalised row dicts.

Scope
-----
- Supported inputs: ``.xlsx`` (openpyxl) and ``.csv`` (stdlib csv).
- Row cap: 5000 rows per upload (operator Ticket V Part 2 — raised
  from the Ticket R 2000 baseline).
- Target customer fields (admin-common subset only — out-of-scope
  fields like ``pool_gallons`` / ``is_vip`` stay post-creation
  operator-set):
    name, first_name, last_name,
    email, phone, home_phone,
    address, city, state, zip,
    billing_address,
    gate_code, notes, tags.

Normalization
-------------
- Email: trim + lowercase.
- Phone: digit-strip; preserved verbatim when non-numeric
  (e.g. ``+1 (555) ...``).
- Name: trim + whitespace collapse.  When the AI returns
  separate ``first_name`` + ``last_name``, compose
  ``name = f"{first} {last}".strip()``.  When only ``name``
  comes back, keep ``first_name``/``last_name`` empty — the
  router/model will auto-split on first space (see
  ``routers/customers.py::_normalize_customer_name_fields``).

Blank-cell semantics (critical, operator Q3 decision)
-----------------------------------------------------
Empty cells in the source file translate to KEYS ABSENT from
the mapped-fields dict — NOT keys with empty-string values.
Downstream commit code (``customers_excel_import.commit``)
uses this to distinguish:

  * File provided the field (dict has the key) → PATCH it onto
    the attached customer, even when the value is empty / falsy.
  * File did not provide the field (dict lacks the key) → leave
    the existing customer value untouched.

This supports the operator's spec: "Fill in only the fields
present in the file; leave missing fields blank rather than
overwriting existing data."

AI provider
-----------
Reuses :func:`services.llm_provider.call_llm_with_fallback` so
tenant-BYO + Emergent + OpenAI chain is honoured identically to
the PDF importer.  Default model: ``claude-sonnet-4-5``.

Row count cap, 400 ``row_limit_exceeded``, is enforced in the
*router* layer (not here) so the mapper stays library-shaped.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services.llm_provider import call_llm_with_fallback


logger = logging.getLogger("imports.customer_excel_mapper")

# Operator Ticket V Part 2 — upper bound raised from 2000 to 5000.
# Enforced by the router BEFORE calling into the mapper (so a
# 5001-row file never hits the LLM).
MAX_ROWS = 5000

# Fields the AI is allowed to populate.  Order mirrors the order
# they'll surface in the UI preview columns.  Downstream commit
# ignores unknown keys so a hallucinated extra field is a no-op.
TARGET_FIELDS: Tuple[str, ...] = (
    "name", "first_name", "last_name",
    "email", "phone", "home_phone",
    "address", "city", "state", "zip",
    "billing_address",
    "gate_code", "notes", "tags",
)

_PHONE_DIGIT_RE = re.compile(r"\D+")

_SYSTEM_PROMPT = (
    "You are a data-mapping assistant for a service-business CRM "
    "importer. Given one row of raw spreadsheet cells (header-cell "
    "pairs), map them to the CRM's canonical customer fields.\n\n"
    "Return a strict JSON object with ONLY these optional keys: "
    + ", ".join(TARGET_FIELDS)
    + ". OMIT any key for which the row provides no usable value. "
    "DO NOT include a key with an empty string, null, or 'N/A' — "
    "leave the key out entirely.\n\n"
    "Rules:\n"
    "- `name` is a single full-name string. If the row has separate "
    "first/last columns, also populate `first_name` and `last_name` "
    "AND compose `name = \"<first> <last>\"`.\n"
    "- `email` must be lowercased and trimmed.\n"
    "- `phone` is the primary mobile. `home_phone` is a landline. "
    "If the row has only one phone, prefer `phone`.\n"
    "- `address` is the service / primary address line. "
    "`billing_address` is the billing address line when distinct. "
    "If the row has only one address, prefer `address`.\n"
    "- `tags` is a list of short strings (e.g. [\"VIP\", \"Pool\"]). "
    "Split on commas / semicolons / pipes.\n"
    "- NEVER invent values. If a cell is unclear, OMIT the key.\n"
    "- Column header names may be in any language / case / "
    "abbreviation style (e.g. \"Full Name\", \"CUSTOMER\", "
    "\"Nom complet\", \"email_addr\", \"tel\", \"ZIP/Postal\"). "
    "Use best judgement.\n\n"
    "Return raw JSON ONLY — no commentary, no code fences."
)


# ═══════════════════════════════════════════════════════════════════
# Public types
# ═══════════════════════════════════════════════════════════════════
@dataclass
class ParsedRow:
    row_num: int
    raw_cells: Dict[str, str] = field(default_factory=dict)


@dataclass
class MappedRow:
    row_num: int
    raw_cells: Dict[str, str]
    mapped_fields: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# File parsing
# ═══════════════════════════════════════════════════════════════════
def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def parse_file(
    *, filename: str, file_bytes: bytes,
) -> Tuple[List[str], List[ParsedRow]]:
    """Parse an xlsx or csv upload into (header_names, parsed_rows).

    Raises ``ValueError`` on unsupported format / corrupt file /
    empty header row.  Caller maps the exception to a 400 with the
    appropriate error code.
    """
    lower = (filename or "").lower()
    if lower.endswith(".xlsx"):
        return _parse_xlsx(file_bytes)
    if lower.endswith(".csv"):
        return _parse_csv(file_bytes)
    # Try CSV first as a fallback for text/plain uploads with no
    # recognisable extension — matches the lenient-posture spec.
    try:
        return _parse_csv(file_bytes)
    except Exception:
        raise ValueError("unsupported_file_type")


def _parse_xlsx(file_bytes: bytes) -> Tuple[List[str], List[ParsedRow]]:
    try:
        from openpyxl import load_workbook  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"openpyxl_import_failed: {exc}") from exc
    try:
        wb = load_workbook(
            io.BytesIO(file_bytes),
            read_only=True, data_only=True,
        )
    except Exception as exc:
        raise ValueError(f"xlsx_parse_failed: {str(exc)[:200]}") from exc
    ws = wb.active
    if ws is None:
        raise ValueError("xlsx_empty")
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise ValueError("xlsx_empty")
    headers = [
        str(h).strip() if not _is_blank(h) else f"col_{i + 1}"
        for i, h in enumerate(header_row)
    ]
    # Trim trailing empty header slots so a sheet with 20 real
    # columns + 10 empty padding ones doesn't produce 10 bogus
    # "col_N" columns.
    while headers and headers[-1].startswith("col_"):
        headers.pop()
    if not headers:
        raise ValueError("xlsx_no_headers")
    parsed: List[ParsedRow] = []
    for idx, raw in enumerate(rows_iter, start=2):
        if all(_is_blank(v) for v in raw):
            continue
        cells: Dict[str, str] = {}
        for h_idx, header in enumerate(headers):
            if h_idx >= len(raw):
                continue
            v = raw[h_idx]
            if _is_blank(v):
                continue
            cells[header] = str(v).strip()
        if cells:
            parsed.append(ParsedRow(row_num=idx, raw_cells=cells))
    return headers, parsed


def _parse_csv(file_bytes: bytes) -> Tuple[List[str], List[ParsedRow]]:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except Exception as exc:
            raise ValueError(f"csv_decode_failed: {exc}") from exc
    reader = csv.reader(io.StringIO(text))
    try:
        header_row = next(reader)
    except StopIteration:
        raise ValueError("csv_empty")
    headers = [
        (h or "").strip() or f"col_{i + 1}"
        for i, h in enumerate(header_row)
    ]
    while headers and headers[-1].startswith("col_"):
        headers.pop()
    if not headers:
        raise ValueError("csv_no_headers")
    parsed: List[ParsedRow] = []
    for idx, raw in enumerate(reader, start=2):
        if not any((c or "").strip() for c in raw):
            continue
        cells: Dict[str, str] = {}
        for h_idx, header in enumerate(headers):
            if h_idx >= len(raw):
                continue
            v = (raw[h_idx] or "").strip()
            if not v:
                continue
            cells[header] = v
        if cells:
            parsed.append(ParsedRow(row_num=idx, raw_cells=cells))
    return headers, parsed


# ═══════════════════════════════════════════════════════════════════
# AI mapping
# ═══════════════════════════════════════════════════════════════════
def _sanitize_llm_output(raw: Any) -> Dict[str, Any]:
    """Keep only known target fields + strip empty values so blank-
    cell semantics (operator Q3) stay intact end-to-end.  Downstream
    commit relies on dict-key presence as the signal for 'file
    provided this field'."""
    out: Dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key in TARGET_FIELDS:
        if key not in raw:
            continue
        v = raw[key]
        if key == "tags":
            if isinstance(v, list):
                tags = [str(t).strip() for t in v if str(t).strip()]
                if tags:
                    out["tags"] = tags
            elif isinstance(v, str) and v.strip():
                tags = [
                    t.strip() for t in re.split(r"[,;|]", v)
                    if t.strip()
                ]
                if tags:
                    out["tags"] = tags
            continue
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.lower() in ("n/a", "none", "null"):
            continue
        if key == "email":
            s = s.lower()
        out[key] = s
    # Compose name from first+last when provided but name absent.
    if "name" not in out:
        first = (out.get("first_name") or "").strip()
        last = (out.get("last_name") or "").strip()
        combined = (first + " " + last).strip()
        if combined:
            out["name"] = combined
    return out


async def map_row_via_llm(
    *, raw_cells: Dict[str, str], tenant_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Round-trip ONE row through the LLM.  Returns
    ``(mapped_fields, provider)`` where ``provider`` is the string
    tag from ``call_llm_with_fallback`` (``emergent`` / ``openai`` /
    ``tenant_byo``).

    On LLM failure returns ``({}, "error:<reason>")`` — the router
    surfaces this as a per-row error without failing the whole
    batch (operator can still manually resolve the row from the
    raw cells in the preview UI).
    """
    user_text = json.dumps({"row": raw_cells}, ensure_ascii=False)
    try:
        result = await call_llm_with_fallback(
            system_prompt=_SYSTEM_PROMPT,
            user_text=user_text,
            tenant_id=tenant_id,
            parse_json=True,
            max_tokens=800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[customer-excel-mapper] LLM dispatcher raised exc=%r "
            "tenant=%s", exc, tenant_id,
        )
        return {}, f"error:dispatcher_crash:{exc}"
    if result.get("error"):
        return {}, f"error:{result.get('error')}"
    raw = result.get("raw") or {}
    return _sanitize_llm_output(raw), str(result.get("provider") or "unknown")


async def map_rows(
    *,
    parsed_rows: List[ParsedRow],
    tenant_id: Optional[str] = None,
) -> Tuple[List[MappedRow], Dict[str, int]]:
    """Round-trip every parsed row through the LLM, serially.

    Serial (not parallel) so a tenant-BYO 429 doesn't fan out into
    N concurrent spend-cap breaches, and so the LLM dispatcher's
    30 s timeout stacks linearly instead of blowing the asyncio
    event loop with N open coroutines on a 5000-row file.

    Returns ``(mapped_rows, provider_counts)``.  Caller stashes the
    result in the preview batch for operator review.
    """
    mapped: List[MappedRow] = []
    provider_counts: Dict[str, int] = {}
    for p in parsed_rows:
        fields_, provider = await map_row_via_llm(
            raw_cells=p.raw_cells, tenant_id=tenant_id,
        )
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
        err = None
        if provider.startswith("error:"):
            err = provider.split("error:", 1)[1]
        mapped.append(MappedRow(
            row_num=p.row_num,
            raw_cells=p.raw_cells,
            mapped_fields=fields_,
            error=err,
        ))
    return mapped, provider_counts


__all__ = [
    "MAX_ROWS", "TARGET_FIELDS",
    "ParsedRow", "MappedRow",
    "parse_file", "map_rows", "map_row_via_llm",
    "_sanitize_llm_output",
]

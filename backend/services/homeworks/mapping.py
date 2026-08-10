"""Phase 55-b · Aug-2026 — Homeworks → AquaTerra field mapping.

Deterministic, side-effect-free helpers. Given a raw payload harvested
by the Playwright scraper (dict), produce the mapped_payload that
lands in ``homeworks_staging.mapped_payload``. The commit engine
(Phase 55-f) then applies the mapped payload verbatim to the target
collection with FK stamping.

Mapping is spec-locked in the Phase 55 design doc §4.1 + §4.2. Only
customers + properties are covered here; jobs / invoices / etc arrive
in phases 55-c and 55-d.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _s(v: Any) -> str:
    """Coerce to trimmed string. ``None`` → ``''``."""
    return str(v).strip() if v is not None else ""


def _list(v: Any) -> List[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # Comma-separated fallback.
        return [t.strip() for t in v.split(",") if t.strip()]
    return []


def map_customer(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Homeworks customer → AquaTerra ``customers`` shape."""
    first = _s(raw.get("first_name"))
    last = _s(raw.get("last_name"))
    name = _s(raw.get("name")) or f"{first} {last}".strip()
    mapped: Dict[str, Any] = {
        "name": name or None,
        "first_name": first or None,
        "last_name": last or None,
        "email": _s(raw.get("email")).lower() or None,
        "phone": _s(raw.get("phone")) or None,
        "home_phone": _s(raw.get("home_phone")) or None,
        "billing_address": _s(raw.get("billing_address")) or None,
        "address": _s(raw.get("address")) or _s(raw.get("billing_address")) or None,
        "notes": _s(raw.get("notes")) or None,
        "tags": _list(raw.get("tags")),
        # Preserve Homeworks provenance for audit / cross-referencing
        # from properties + future entity types.
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_created_at": _s(raw.get("created_at")) or None,
    }
    return {k: v for k, v in mapped.items() if v not in (None, "", [])}


def map_property(
    raw: Dict[str, Any],
    parent_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks property/service-location → AquaTerra
    ``properties`` shape. ``parent_customer_id`` is resolved by the
    orchestrator (either the matched target for merges or the
    pre-generated UUID stashed on a new-customer staging row)."""
    address_line = _s(raw.get("address"))
    label = _s(raw.get("label")) or address_line or "Service Location"
    mapped: Dict[str, Any] = {
        "label": label,
        "customer_id": parent_customer_id,
        "address": {
            "line1": address_line or None,
            "city": _s(raw.get("city")) or None,
            "state": _s(raw.get("state")) or None,
            "zip": _s(raw.get("zip")) or None,
        },
        "pool_size_gallons": raw.get("pool_size_gallons"),
        "landscape_sq_ft": raw.get("landscape_sq_ft"),
        "gate_code": _s(raw.get("gate_code")) or None,
        "service_notes": {
            "access": _s(raw.get("access_notes")) or None,
        } if raw.get("access_notes") else None,
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_customer_id": _s(raw.get("customer_homeworks_id")) or None,
    }
    # Prune empty subdocs / None values but keep required top-level
    # keys so PropertyIn's Pydantic model accepts the payload.
    if mapped["address"] and not any(mapped["address"].values()):
        mapped["address"] = None
    return {k: v for k, v in mapped.items() if v is not None}


def map_job(
    raw: Dict[str, Any],
    customer_target_id: Optional[str] = None,
    property_target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks job / work order → AquaTerra ``jobs`` shape.

    FK ids are resolved by the orchestrator via a staging-lookup
    against ``homeworks_staging.entity_type == customers|properties``.
    The commit engine (Phase 55-f) then applies this payload verbatim.
    """
    title = _s(raw.get("title")) or _s(raw.get("service_template_hint")) \
        or "Homeworks job"
    status = _s(raw.get("status")).lower() or "pending"
    mapped: Dict[str, Any] = {
        "title": title,
        "customer_id": customer_target_id,
        "property_id": property_target_id,
        "service_type": _s(raw.get("service_template_hint"))
                            or _s(raw.get("service_type")) or None,
        "scheduled_date": _s(raw.get("scheduled_at")) or None,
        "scheduled_end": _s(raw.get("scheduled_end")) or None,
        "duration_minutes": raw.get("duration_minutes"),
        "assigned_to_email": _s(raw.get("assigned_to_email")) or None,
        "status": status,
        "notes": _s(raw.get("notes")) or _s(raw.get("description")) or None,
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_created_at": _s(raw.get("created_at")) or None,
        "service_template_hint": _s(raw.get("service_template_hint")) or None,
    }
    return {k: v for k, v in mapped.items()
             if v is not None and v != ""}


def map_recurring_schedule(
    raw: Dict[str, Any],
    customer_target_id: Optional[str] = None,
    property_target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks recurring plan → AquaTerra ``recurring_schedules``.

    ``interval_type`` is coerced to one of ``weekly / biweekly /
    monthly / custom``. ``interval_days`` is passed through as-is (or
    inferred from ``interval_type`` when missing) so the recurring
    engine at commit time doesn't have to re-parse a Homeworks-shaped
    frequency string.
    """
    interval_type = _s(raw.get("interval_type")).lower() or "custom"
    if interval_type not in ("weekly", "biweekly", "monthly", "custom"):
        interval_type = "custom"
    default_days = {
        "weekly": 7, "biweekly": 14, "monthly": 30, "custom": None,
    }
    interval_days = raw.get("interval_days")
    if interval_days is None:
        interval_days = default_days.get(interval_type)
    active = raw.get("active")
    if active is None:
        active = True
    mapped: Dict[str, Any] = {
        "customer_id": customer_target_id,
        "property_id": property_target_id,
        "interval_type": interval_type,
        "interval_days": interval_days,
        "next_run_at": _s(raw.get("next_run_at")) or None,
        "active": bool(active),
        "service_template_hint": _s(raw.get("service_template_hint")) or None,
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_created_at": _s(raw.get("created_at")) or None,
    }
    return {k: v for k, v in mapped.items() if v is not None}


def _num(v: Any) -> Optional[float]:
    """Coerce ``str/int/float`` to float. Returns ``None`` on failure."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _map_line_items(rows: Any) -> List[Dict[str, Any]]:
    """Map a Homeworks line-items array (invoice + quote share the
    shape). Each line preserves ``homeworks_id`` so we can dedupe
    inside the invoice on a re-scrape."""
    if not rows:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        line: Dict[str, Any] = {
            "description": _s(r.get("description")) or "",
            "quantity": _num(r.get("quantity")) or 1.0,
            "unit_price": _num(r.get("unit_price")) or 0.0,
            "category": _s(r.get("category")) or "Homeworks",
            "taxable": bool(r.get("taxable", True)),
            "tax_rate": _num(r.get("tax_rate")) or 0.0,
            # Immutable margin snapshots — preserved verbatim from
            # Homeworks so historical margin reports don't drift.
            "wholesale_price_snapshot": _num(r.get("wholesale_price_snapshot")),
            "retail_price_snapshot":    _num(r.get("retail_price_snapshot")),
            "labor_cost_snapshot":      _num(r.get("labor_cost_snapshot")),
            "homeworks_line_id": _s(r.get("id")) or None,
        }
        out.append({k: v for k, v in line.items() if v is not None})
    return out


def map_invoice(
    raw: Dict[str, Any],
    customer_target_id: Optional[str] = None,
    job_target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks invoice → AquaTerra ``invoices`` shape.

    Invoice number is preserved verbatim (the customer knows it) and
    line-item snapshots are copied through untouched — the commit
    engine (Phase 55-f) never regenerates them.
    """
    line_items = _map_line_items(raw.get("line_items"))
    status = _s(raw.get("status")).lower() or "sent"
    mapped: Dict[str, Any] = {
        "customer_id": customer_target_id,
        "job_id": job_target_id,
        "invoice_number": _s(raw.get("invoice_number")) or None,
        "title": _s(raw.get("title"))
                  or f"Homeworks invoice {_s(raw.get('invoice_number')) or ''}".strip()
                  or "Homeworks invoice",
        "doc_type": "invoice",
        "status": status,
        "line_items": line_items,
        "tax_rate": _num(raw.get("tax_rate")) or 0.0,
        "subtotal_cents": raw.get("subtotal_cents"),
        "total_cents": raw.get("total_cents"),
        "due_date": _s(raw.get("due_date")) or None,
        "issued_at": _s(raw.get("issued_at")) or None,
        "notes": _s(raw.get("notes")) or None,
        "terms": _s(raw.get("terms")) or None,
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_quote_id": _s(raw.get("quote_id")) or None,
    }
    return {k: v for k, v in mapped.items()
             if v is not None and v != ""}


def map_quote(
    raw: Dict[str, Any],
    customer_target_id: Optional[str] = None,
    property_target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks estimate/quote → AquaTerra ``quotes`` shape.

    Same headers + line-item mapper as invoices — quotes are pre-
    invoices in Copilot CRM terminology.
    """
    line_items = _map_line_items(raw.get("line_items"))
    status = _s(raw.get("status")).lower() or "draft"
    mapped: Dict[str, Any] = {
        "customer_id": customer_target_id,
        "property_id": property_target_id,
        "title": _s(raw.get("title")) or "Homeworks quote",
        "doc_type": "quote",
        "status": status,
        "line_items": line_items,
        "tax_rate": _num(raw.get("tax_rate")) or 0.0,
        "subtotal_cents": raw.get("subtotal_cents"),
        "total_cents": raw.get("total_cents"),
        "notes": _s(raw.get("notes")) or None,
        "terms": _s(raw.get("terms")) or None,
        "issued_at": _s(raw.get("issued_at")) or None,
        "homeworks_id": _s(raw.get("id")) or None,
    }
    return {k: v for k, v in mapped.items()
             if v is not None and v != ""}


def map_payment(
    raw: Dict[str, Any],
    invoice_target_id: Optional[str] = None,
    customer_target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks payment → AquaTerra ``payments`` shape.

    Passthrough for ``stripe_charge_id`` — if the source Copilot CRM
    tenant also runs on Stripe (per user's confirmation flow), the
    external charge id lands verbatim so historical reconciliation
    reports match cent-for-cent.
    """
    amount_cents = raw.get("amount_cents")
    if amount_cents is None and raw.get("amount") is not None:
        try:
            amount_cents = int(round(float(raw["amount"]) * 100))
        except (TypeError, ValueError):
            amount_cents = None
    mapped: Dict[str, Any] = {
        "invoice_id": invoice_target_id,
        "customer_id": customer_target_id,
        "amount_cents": amount_cents,
        "amount": _num(raw.get("amount")),
        "method": _s(raw.get("method")).lower() or None,
        "applied_at": _s(raw.get("applied_at"))
                       or _s(raw.get("paid_at")) or None,
        "transaction_ref": _s(raw.get("transaction_ref"))
                            or _s(raw.get("reference")) or None,
        "stripe_charge_id": _s(raw.get("stripe_charge_id")) or None,
        "notes": _s(raw.get("notes")) or None,
        "homeworks_id": _s(raw.get("id")) or None,
        "homeworks_invoice_id": _s(raw.get("invoice_id")) or None,
    }
    return {k: v for k, v in mapped.items() if v is not None}


# ─── Notes + Photos (Phase 55-e) ────────────────────────────────
def collection_for_note_parent(parent_type: str) -> str:
    """Route a note into ``customer_notes`` or ``job_notes`` based on
    its Homeworks parent-entity type. Invoice / quote notes fall
    back onto ``customer_notes`` so they're still tenant-searchable."""
    if parent_type == "job":
        return "job_notes"
    return "customer_notes"


def map_note(
    raw: Dict[str, Any],
    parent_type: str,
    parent_target_id: Optional[str],
) -> Dict[str, Any]:
    """Map Homeworks note → AquaTerra ``customer_notes`` or
    ``job_notes`` shape (parent_type routes the collection). Both
    collections share this field shape."""
    mapped: Dict[str, Any] = {
        "parent_type": parent_type,
        "text": _s(raw.get("text")) or _s(raw.get("body")) or "",
        "created_at": _s(raw.get("created_at")) or None,
        "author_email": _s(raw.get("author_email"))
                         or _s(raw.get("author")) or None,
        "homeworks_id": _s(raw.get("id")) or None,
    }
    # Set FK under the collection-specific key so the target
    # collection's queries by ``customer_id`` / ``job_id`` still hit.
    if parent_type == "job":
        mapped["job_id"] = parent_target_id
    else:
        mapped["customer_id"] = parent_target_id
    return {k: v for k, v in mapped.items() if v is not None}


def map_photo(
    raw: Dict[str, Any],
    parent_type: str,
    parent_target_id: Optional[str],
    storage_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Homeworks attachment → AquaTerra ``homeworks_photos`` shape.

    ``storage_url`` is the post-download blob path in our object
    storage; when ``None`` (download failed) the caller stamps a
    ``photo_download_failed`` marker so the metadata still lands.
    """
    mapped: Dict[str, Any] = {
        "parent_type": parent_type,
        "parent_id": parent_target_id,
        "original_url": _s(raw.get("url"))
                         or _s(raw.get("original_url")) or None,
        "storage_url": storage_url,
        "caption": _s(raw.get("caption")) or None,
        "taken_at": _s(raw.get("taken_at"))
                     or _s(raw.get("created_at")) or None,
        "mime_type": _s(raw.get("mime_type")) or None,
        "size_bytes": raw.get("size_bytes"),
        "homeworks_id": _s(raw.get("id")) or None,
    }
    return {k: v for k, v in mapped.items() if v is not None}

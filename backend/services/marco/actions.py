"""MA1 · MARCO action registry — 4 handlers dispatched from the
``/marco/execute`` endpoint.

Every handler has the SAME signature::

    async def handle_<action>(*, user, tenant, screen, entity_id, args)
        -> {"ok": bool, "code": Optional[str], "message": str,
            "meta": dict}

Handlers NEVER raise — every failure mode is expressed as
``{ok: False, code: <machine-readable>, message: <friendly>}`` so the
endpoint can render a toast without special-casing exceptions.

Rulings applied (locked in during MA1 dispatch, Feb-2026)
─────────────────────────────────────────────────────────
1. Line-item append uses the MA0 ``POST /invoices/{id}/line-items``
   endpoint (imported + called in-process, no HTTP round-trip).
2. ``handle_save_note`` on ``screen=job_detail`` routes through
   ``/service-report/attach-note`` with friendly errors on 404
   (``no_open_service_report``) and the endpoint's own
   ``status=multiple_open_reports`` picker branch mapped to
   ``multiple_open_service_reports``.
3. Clock actions IGNORE ``entity_id`` as a job selector (clock is
   day-scoped). On ``screen=job_detail`` we enrich the response
   ``meta`` with ``job_context`` (job name) so the client toast can
   read "Clocked in — Smith pool".
4. ``handle_clock_in`` / ``handle_clock_out`` short-circuit for
   admin / super_admin (and manager, though ``require_tech_or_above``
   at the endpoint layer already rejects manager) with
   ``code="role_not_tech"``. This intercepts BEFORE the attendance
   endpoint's own 403 so the friendly toast wins.
5. Pricebook read is a DIRECT DB read on ``db.items`` scoped by
   ``tenant_id`` + ``deleted_at is None`` (with legacy-item fallback
   for rows missing the field, matching MA0's P34/Task-KK pattern).
   No new HTTP endpoint.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from rapidfuzz import fuzz

from config import db


ROLE_TECH = "technician"


# ═══════════════════════════════════════════════════════════════════
# Clock
# ═══════════════════════════════════════════════════════════════════
async def _maybe_job_context(tenant_id: str, screen: str,
                              entity_id: str) -> Dict[str, Any]:
    """Ruling #3 — clock is day-scoped but we surface the job the
    tech was looking at (if any) in ``meta.job_context`` so the toast
    can read "Clocked in — Smith pool". Screen-scoped: ONLY on
    ``job_detail`` does ``entity_id`` mean a job.
    """
    if screen != "job_detail" or not entity_id:
        return {}
    job = await db.jobs.find_one(
        {"id": entity_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "title": 1},
    )
    if not job:
        return {}
    name = job.get("name") or job.get("title") or ""
    return {"job_context": name} if name else {}


async def handle_clock_in(*, user: dict, tenant: dict, screen: str,
                           entity_id: str,
                           args: Dict[str, Any]) -> Dict[str, Any]:
    if user.get("role") != ROLE_TECH:
        return {
            "ok": False,
            "code": "role_not_tech",
            "message": "Only technicians can clock in.",
            "meta": {},
        }
    from routers.attendance import clock_in as _clock_in
    from models import PunchIn
    body = PunchIn(lat=0.0, lng=0.0)
    try:
        result = await _clock_in(body=body, user=user, tenant=tenant)
    except HTTPException as e:
        return {
            "ok": False,
            "code": "clock_in_failed",
            "message": str(e.detail),
            "meta": {},
        }
    meta: Dict[str, Any] = {
        "timesheet_id": result.get("id"),
        "clock_in_at": result.get("clock_in_at"),
    }
    meta.update(await _maybe_job_context(tenant["id"], screen, entity_id))
    return {"ok": True, "code": None, "message": "Clocked in.",
            "meta": meta}


async def handle_clock_out(*, user: dict, tenant: dict, screen: str,
                            entity_id: str,
                            args: Dict[str, Any]) -> Dict[str, Any]:
    if user.get("role") != ROLE_TECH:
        return {
            "ok": False,
            "code": "role_not_tech",
            "message": "Only technicians can clock out.",
            "meta": {},
        }
    from routers.attendance import clock_out as _clock_out
    from models import PunchIn
    body = PunchIn(lat=0.0, lng=0.0)
    try:
        result = await _clock_out(body=body, user=user, tenant=tenant)
    except HTTPException as e:
        return {
            "ok": False,
            "code": "clock_out_failed",
            "message": str(e.detail),
            "meta": {},
        }
    meta: Dict[str, Any] = {
        "timesheet_id": result.get("id"),
        "clock_out_at": result.get("clock_out_at"),
    }
    meta.update(await _maybe_job_context(tenant["id"], screen, entity_id))
    return {"ok": True, "code": None, "message": "Clocked out.",
            "meta": meta}


# ═══════════════════════════════════════════════════════════════════
# Add line item
# ═══════════════════════════════════════════════════════════════════
async def _resolve_invoice_id(tenant_id: str, screen: str,
                                entity_id: str) -> Optional[str]:
    """Screen-aware invoice resolution.

    * ``screen=job_detail`` → ``entity_id`` IS the job_id.
    * ``screen=service_report`` → ``entity_id`` is a service_report id
      whose ``job_id`` links to the invoice.

    Returns the invoice id or ``None`` if no invoice is linked to
    that job.
    """
    if not entity_id:
        return None
    if screen == "service_report":
        sr = await db.service_reports.find_one(
            {"id": entity_id, "tenant_id": tenant_id},
            {"_id": 0, "job_id": 1},
        )
        if not sr:
            return None
        job_id = sr.get("job_id")
    elif screen == "job_detail":
        job_id = entity_id
    else:
        return None
    if not job_id:
        return None
    inv = await db.quotes.find_one(
        {"job_id": job_id, "tenant_id": tenant_id,
         "doc_type": "invoice",
         "$or": [{"deleted_at": None},
                  {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    )
    return (inv or {}).get("id")


async def _fuzzy_match_item(tenant_id: str, query: str,
                             threshold: int = 85,
                             ambiguous_gap: int = 5) -> Dict[str, Any]:
    """Pricebook fuzzy match — direct DB read per Ruling #4.

    Returns one of:
        {"match": <full item dict>}       — unambiguous top ≥ threshold
        {"ambiguous": [<top>, <second>]}  — top 2 within ``gap`` points
        {"no_match": True, "candidates": [<top 5>]}  — top < threshold
    """
    rows = await db.items.find(
        {"tenant_id": tenant_id,
         "$or": [{"deleted_at": None},
                  {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1, "price": 1,
         "category": 1, "service_category": 1},
    ).to_list(2000)
    scored: List[tuple[int, dict]] = []
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        s = fuzz.WRatio(query, name)
        scored.append((int(s), r))
    if not scored:
        return {"no_match": True, "candidates": []}
    scored.sort(key=lambda t: t[0], reverse=True)
    top_score, top_row = scored[0]
    if top_score < threshold:
        return {
            "no_match": True,
            "candidates": [
                {"item_id": r["id"], "name": r.get("name"), "score": s}
                for s, r in scored[:5]
            ],
        }
    if len(scored) >= 2 and (top_score - scored[1][0]) < ambiguous_gap:
        return {
            "ambiguous": [
                {"item_id": r["id"], "name": r.get("name"), "score": s}
                for s, r in scored[:2]
            ],
        }
    return {"match": top_row}


async def handle_add_line_item(*, user: dict, tenant: dict, screen: str,
                                 entity_id: str,
                                 args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("item_query") or "").strip()
    if not query:
        return {
            "ok": False,
            "code": "missing_item_query",
            "message": "No item name detected in the command.",
            "meta": {},
        }
    try:
        quantity = float(args.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1.0
    invoice_id = await _resolve_invoice_id(tenant["id"], screen, entity_id)
    if not invoice_id:
        return {
            "ok": False,
            "code": "no_open_invoice",
            "message": "No invoice found for this job.",
            "meta": {},
        }
    match = await _fuzzy_match_item(tenant["id"], query)
    if match.get("ambiguous"):
        return {
            "ok": False,
            "code": "ambiguous_item_match",
            "message": "More than one item matched. Which did you mean?",
            "meta": {"candidates": match["ambiguous"]},
        }
    if match.get("no_match"):
        return {
            "ok": False,
            "code": "item_not_matched",
            "message": f"No pricebook item matched \"{query}\".",
            "meta": {"candidates": match.get("candidates", [])},
        }
    item = match["match"]
    from routers.invoice_line_items import (
        add_line_item as _add_line_item,
        LineItemAddBody,
    )
    body = LineItemAddBody(item_id=item["id"], quantity=quantity)
    try:
        updated = await _add_line_item(
            invoice_id=invoice_id, body=body,
            user=user, tenant=tenant,
        )
    except HTTPException as e:
        return {
            "ok": False,
            "code": "line_item_add_failed",
            "message": str(e.detail),
            "meta": {},
        }
    return {
        "ok": True,
        "code": None,
        "message": f"Added {quantity} × {item.get('name') or ''}.",
        "meta": {
            "invoice_id": invoice_id,
            "item_id": item["id"],
            "item_name": item.get("name"),
            "quantity": quantity,
            "line_items_len": len(updated.get("line_items") or []),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# Save note
# ═══════════════════════════════════════════════════════════════════
async def handle_save_note(*, user: dict, tenant: dict, screen: str,
                             entity_id: str,
                             args: Dict[str, Any]) -> Dict[str, Any]:
    text = str(args.get("text") or "").strip()
    if not text:
        return {
            "ok": False,
            "code": "missing_note_text",
            "message": "No note text detected in the command.",
            "meta": {},
        }
    from routers.service_reports import (
        attach_calculator_note as _attach_note,
        AttachNoteIn,
    )
    # Ruling #2: on ``screen=service_report`` the entity_id IS the
    # report_id (target that report directly). On ``screen=job_detail``
    # we pass ``report_id=None`` — the endpoint resolves the tech's
    # single open report or returns the multi-report picker.
    report_id: Optional[str] = entity_id if screen == "service_report" else None
    body = AttachNoteIn(text=text, report_id=report_id)
    try:
        result = await _attach_note(body=body, user=user, tenant=tenant)
    except HTTPException as e:
        code = "note_attach_failed"
        if e.status_code == 404:
            code = "no_open_service_report"
        return {
            "ok": False,
            "code": code,
            "message": str(e.detail),
            "meta": {},
        }
    # attach-note's picker branch is HTTP 200 with a status field
    # (verified in the endpoint source, ``service_reports.py::attach_calculator_note``).
    if isinstance(result, dict) and result.get("status") == "multiple_open_reports":
        return {
            "ok": False,
            "code": "multiple_open_service_reports",
            "message": "Multiple open service reports — pick one.",
            "meta": {"reports": result.get("reports") or []},
        }
    return {
        "ok": True,
        "code": None,
        "message": "Note attached.",
        "meta": {
            "report_id": (result or {}).get("report_id"),
            "internal_notes_len": (result or {}).get("internal_notes_len"),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# Dispatch table
# ═══════════════════════════════════════════════════════════════════
ACTION_REGISTRY = {
    "clock_in": handle_clock_in,
    "clock_out": handle_clock_out,
    "add_line_item": handle_add_line_item,
    "save_note": handle_save_note,
}

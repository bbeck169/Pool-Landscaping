"""Feb-2026 - Invoice/Quote line-item category WARNING scan.

Replaces the hard-block category validators the invoice edit UI
used to surface as three red blockers (top banner, mid banner,
bottom toast).  Operators have been reporting that reasonable
cleanup workflows (archive an obsolete category, keep editing
pre-existing invoices tomorrow) were blocked because the backend
raised HTTP 400 on missing or inactive line-item categories.

This module is the shared helper the quote / invoice / billing
routers call AFTER the archived-soft-pass logic in
``routers/income_categories.py`` already ran.  It reports
non-blocking counts so the operator UI can render a yellow
"needs cleanup" chip and the server can log an audit trail
for ops reporting.

Hard rule (user spec):
  * Save, Send, Approve, Convert all succeed even with missing
    or inactive-category line items.
  * Audit log row written per save/send/approve/convert when
    warnings exist (``action="invoices.saved_with_category_warnings"``).
  * No ``raise HTTPException`` from category checks on the
    invoice path.  Other validators (totals, dates, customer
    resolution) are untouched.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils import new_id


logger = logging.getLogger("invoices.line_item_category_audit")


def scan_line_item_category_warnings(
    line_items: List[Dict[str, Any]],
    *,
    inc_active_ids: Optional[set] = None,
    inc_active_names: Optional[set] = None,
    svc_active_ids: Optional[set] = None,
    svc_active_names: Optional[set] = None,
) -> Dict[str, Any]:
    """Walk ``line_items`` and bucket each row into one of:
      * ``uncategorized`` - no category metadata present (either
        K71 fields empty OR legacy ``category`` field empty).
      * ``inactive`` - K71 ``service_category_id`` /
        ``income_category_id`` present but value doesn't match
        any active id/name (archived or unknown).

    Pass ``inc_active_*`` / ``svc_active_*`` sets to enable the
    "inactive" bucket.  When omitted (e.g. a quick single-item
    scan), only the "missing" check runs.

    Returns::

        {
          "uncategorized_count": 2,
          "inactive_category_line_item_count": 1,
          "uncategorized_line_indices": [1, 3],
          "inactive_category_line_indices": [2],
        }
    """
    uncategorized_indices: List[int] = []
    inactive_indices: List[int] = []
    inc_active_ids = inc_active_ids or set()
    inc_active_names = inc_active_names or set()
    svc_active_ids = svc_active_ids or set()
    svc_active_names = svc_active_names or set()
    for idx, li in enumerate(line_items or []):
        svc_raw = li.get("service_category_id")
        inc_raw = li.get("income_category_id")
        legacy_cat_raw = li.get("category")

        has_svc_field = isinstance(svc_raw, str)
        has_inc_field = isinstance(inc_raw, str)
        is_k71 = has_svc_field or has_inc_field

        svc_val = svc_raw.strip() if isinstance(svc_raw, str) else ""
        inc_val = inc_raw.strip() if isinstance(inc_raw, str) else ""
        legacy_cat = (
            legacy_cat_raw.strip()
            if isinstance(legacy_cat_raw, str) else ""
        )

        # Auto-mapped (archive-time fan-out) rows are an operator-
        # review surface but not a hard warning for this audit --
        # they already have an amber chip in the editor.
        if li.get("category_auto_mapped") is True:
            if not svc_val and not inc_val and not legacy_cat:
                # Auto-mapped + emptied = needs cleanup, bucket as
                # uncategorized so the FE amber chip + audit count
                # agree.
                uncategorized_indices.append(idx)
            continue

        if is_k71:
            # K71 editor touched this row; both fields are expected
            # non-empty for a "clean" row.
            if not svc_val or not inc_val:
                uncategorized_indices.append(idx)
                continue
            # Both present - check they resolve to active rows.
            bad = False
            if svc_active_ids or svc_active_names:
                if (
                    svc_val not in svc_active_ids
                    and svc_val.lower() not in svc_active_names
                ):
                    bad = True
            if inc_active_ids or inc_active_names:
                if (
                    inc_val not in inc_active_ids
                    and inc_val.lower() not in inc_active_names
                ):
                    bad = True
            if bad:
                inactive_indices.append(idx)
        else:
            # Legacy single-taxonomy ``category`` row.
            if not legacy_cat:
                uncategorized_indices.append(idx)
                continue
            if inc_active_ids or inc_active_names:
                if (
                    legacy_cat not in inc_active_ids
                    and legacy_cat.lower() not in inc_active_names
                ):
                    inactive_indices.append(idx)

    return {
        "uncategorized_count": len(uncategorized_indices),
        "inactive_category_line_item_count": len(inactive_indices),
        "uncategorized_line_indices": uncategorized_indices,
        "inactive_category_line_indices": inactive_indices,
    }


async def write_category_warnings_audit(
    db,
    *,
    tenant_id: str,
    actor_id: Optional[str],
    invoice_id: Optional[str],
    scan: Dict[str, Any],
    source: str = "invoice_save",
) -> None:
    """Write a single ``db.audit_logs`` row AND emit a structured
    log line when the scan carries ANY warnings. No-op otherwise.

    Called by invoice/quote save, send, approve, and convert
    endpoints AFTER the write succeeds.  Best-effort - a failed
    audit insert is logged + swallowed so the parent write is
    never rolled back on a transient audit failure.
    """
    u = int(scan.get("uncategorized_count") or 0)
    inv_cnt = int(scan.get("inactive_category_line_item_count") or 0)
    if u == 0 and inv_cnt == 0:
        return
    logger.info(
        "invoices.saved_with_category_warnings invoice_id=%s "
        "tenant_id=%s source=%s uncategorized=%d inactive=%d",
        invoice_id, tenant_id, source, u, inv_cnt,
    )
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "action": "invoices.saved_with_category_warnings",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "invoice_id": invoice_id,
            "source": source,
            "uncategorized_line_item_count": u,
            "inactive_category_line_item_count": inv_cnt,
            "uncategorized_line_indices": list(
                scan.get("uncategorized_line_indices") or []),
            "inactive_category_line_indices": list(
                scan.get("inactive_category_line_indices") or []),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[invoices.audit] insert failed invoice_id=%s "
            "tenant_id=%s (non-fatal): %s",
            invoice_id, tenant_id, exc,
        )

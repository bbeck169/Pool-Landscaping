"""TD-customer-ai-excel-csv-import · Feb-2026
=============================================

AI-powered Excel/CSV customer importer — endpoints:

  POST /api/customers/import-excel/upload
      multipart/form-data file field ``file``.
      Parses xlsx/csv, maps each row via the LLM, probes dupes,
      stashes preview in-memory under a ``batch_id``.
      Returns ``{batch_id, preview, stats, headers, ai_providers}``.

  POST /api/customers/import-excel/commit
      JSON ``{batch_id, rows: [{row_num, action, mapped_fields,
      attach_to_customer_id?}]}``.
      Executes operator-approved actions and returns a per-row
      outcome summary.  Blank-cell semantics (operator Q3):
      mapped_fields key ABSENT → leave existing customer value
      alone; mapped_fields key PRESENT → PATCH it onto the row
      (even when the value is empty string / falsy — the operator
      has explicit intent to clear if they ticked that path, but
      the mapper strips empties by design so the common case is
      a non-empty value).

Scope guards
------------
- Admin / manager / super_admin / owner only.  Tech 403.
- Row cap: 2000 per upload (operator Q4).
- Preview-batch TTL: 10 minutes (operator Q1).  Simple in-process
  dict with periodic sweep on upload.  Operator who walks away
  >10 minutes re-uploads (file re-parse + re-mapper round-trip).

Boundary rejects
----------------
- Empty file → 400 ``empty_file``.
- Corrupt / unparseable file → 400 ``unsupported_file_type``.
- > 2000 rows → 400 ``row_limit_exceeded`` with ``max_rows: 2000``.
- Cross-tenant commit (batch_id resolves to a different tenant)
  → 404 ``batch_not_found`` (NOT 403 — don't leak existence).
- Expired batch → 404 ``batch_not_found``.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, UploadFile,
)
from pydantic import BaseModel, Field

from config import db
from routers.tenants import get_current_tenant
from services.imports.customer_excel_dedupe import (
    _normalize_email, _normalize_phone, detect_duplicate,
)
from services.imports.customer_excel_mapper import (
    MAX_ROWS, TARGET_FIELDS, map_rows, parse_file,
)
from utils import new_id, require_admin


logger = logging.getLogger("customers_excel_import")

router = APIRouter(prefix="/api/customers", tags=["customers"])

# In-memory preview-batch store.  Not clustered — on multi-pod the
# commit MUST land on the same pod as upload or 404s.  Operator
# re-uploads in that case.  Documented trade-off per operator Q1.
# Keyed by batch_id.
_PREVIEW_BATCHES: Dict[str, Dict[str, Any]] = {}
_BATCH_TTL_SECONDS = 600   # 10 minutes


# Upper bound on file size (bytes).  2000 rows × ~2kb per row ≈ 4 MB
# worst-case for xlsx.  Pad to 8 MB so a slightly-oversized real
# file isn't rejected before we even sniff the format.
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024

_ALLOWED_ROLES = ("admin", "super_admin", "owner", "manager")


def _sweep_expired() -> None:
    """Drop expired preview batches.  Called on every upload so a
    long-idle pod doesn't accumulate stale rows."""
    now = time.time()
    for bid in list(_PREVIEW_BATCHES.keys()):
        if _PREVIEW_BATCHES[bid]["expires_at"] < now:
            del _PREVIEW_BATCHES[bid]


def _assert_role(user: Dict[str, Any]) -> None:
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, "Admin or manager access required")


# ═══════════════════════════════════════════════════════════════════
# UPLOAD
# ═══════════════════════════════════════════════════════════════════
@router.post("/import-excel/upload",
                operation_id="customers.importExcel.upload")
async def import_excel_upload(
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _assert_role(user)
    _sweep_expired()

    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(400, {"error": "empty_file"})
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            {"error": "file_too_large",
             "max_bytes": _MAX_UPLOAD_BYTES},
        )

    try:
        headers, parsed_rows = parse_file(
            filename=file.filename or "",
            file_bytes=raw,
        )
    except ValueError as exc:
        raise HTTPException(
            400, {"error": "unsupported_file_type",
                   "detail": str(exc)},
        )

    if not parsed_rows:
        raise HTTPException(400, {"error": "empty_file",
                                       "detail": "no_data_rows"})
    if len(parsed_rows) > MAX_ROWS:
        raise HTTPException(
            400,
            {"error": "row_limit_exceeded",
             "max_rows": MAX_ROWS,
             "found_rows": len(parsed_rows)},
        )

    tenant_id = tenant["id"]

    # LLM map — serial.  See mapper module docstring for why.
    mapped_rows, provider_counts = await map_rows(
        parsed_rows=parsed_rows, tenant_id=tenant_id,
    )

    # Dupe-detect each mapped row.
    preview: List[Dict[str, Any]] = []
    stats = {
        "rows_total": len(mapped_rows),
        "rows_create": 0,
        "rows_attach": 0,
        "rows_skip": 0,
        "rows_errored": 0,
    }
    for m in mapped_rows:
        row_entry: Dict[str, Any] = {
            "row_num": m.row_num,
            "raw_cells": m.raw_cells,
            "mapped_fields": m.mapped_fields,
            "match_status": "no_match",
            "match_candidates": [],
            "suggested_action": "create",
        }
        if m.error:
            row_entry["error"] = m.error
            stats["rows_errored"] += 1
            # Default to skip when the AI mapper errored — the
            # operator can still override to create via the raw
            # cells in the preview UI.
            row_entry["suggested_action"] = "skip"
            stats["rows_skip"] += 1
            preview.append(row_entry)
            continue
        try:
            dupe = await detect_duplicate(
                db=db, tenant_id=tenant_id,
                mapped_fields=m.mapped_fields,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[customers-excel-import] dedupe raised exc=%r "
                "tenant=%s row=%s", exc, tenant_id, m.row_num,
            )
            dupe = None
        if dupe is not None:
            row_entry["match_status"] = dupe.match_status
            row_entry["match_candidates"] = [
                {
                    "customer_id": c.customer_id,
                    "name": c.name,
                    "email": c.email,
                    "phone": c.phone,
                    "match_reason": c.match_reason,
                }
                for c in dupe.candidates
            ]
            row_entry["suggested_action"] = dupe.suggested_action
        if row_entry["suggested_action"] == "attach":
            stats["rows_attach"] += 1
        elif row_entry["suggested_action"] == "skip":
            stats["rows_skip"] += 1
        else:
            stats["rows_create"] += 1
        preview.append(row_entry)

    batch_id = str(uuid.uuid4())
    now = time.time()
    _PREVIEW_BATCHES[batch_id] = {
        "batch_id": batch_id,
        "tenant_id": tenant_id,
        "user_id": user.get("id"),
        "created_at": now,
        "expires_at": now + _BATCH_TTL_SECONDS,
        "preview": preview,
        "headers": headers,
    }

    return {
        "batch_id": batch_id,
        "preview": preview,
        "stats": stats,
        "headers": headers,
        "ai_providers": provider_counts,
        "expires_at_iso": datetime.fromtimestamp(
            now + _BATCH_TTL_SECONDS, tz=timezone.utc,
        ).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# COMMIT
# ═══════════════════════════════════════════════════════════════════
class CommitRow(BaseModel):
    row_num: int
    action: str   # "create" | "attach" | "skip"
    mapped_fields: Dict[str, Any] = Field(default_factory=dict)
    attach_to_customer_id: Optional[str] = None


class CommitPayload(BaseModel):
    batch_id: str
    rows: List[CommitRow] = Field(default_factory=list)


def _sanitize_mapped_for_write(
    mapped: Dict[str, Any],
) -> Dict[str, Any]:
    """Strip to the known target-field set + normalize email / phone
    before persisting.  Operator Q3 blank-cell semantics are
    preserved by the mapper's upstream _sanitize_llm_output (empty
    strings never reach this function); belt-and-braces here too.
    """
    out: Dict[str, Any] = {}
    for key in TARGET_FIELDS:
        if key not in mapped:
            continue
        v = mapped[key]
        if key == "tags":
            if isinstance(v, list):
                tags = [str(t).strip() for t in v if str(t).strip()]
                if tags:
                    out["tags"] = tags
            continue
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        if key == "email":
            s = s.lower()
        out[key] = s
    return out


@router.post("/import-excel/commit",
                operation_id="customers.importExcel.commit")
async def import_excel_commit(
    payload: CommitPayload,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _assert_role(user)
    _sweep_expired()

    batch = _PREVIEW_BATCHES.get(payload.batch_id)
    tenant_id = tenant["id"]
    if not batch or batch["tenant_id"] != tenant_id:
        # DELIBERATELY 404 even on cross-tenant to avoid leaking
        # batch existence to a different tenant admin.
        raise HTTPException(404, {"error": "batch_not_found"})

    now_iso = datetime.now(timezone.utc).isoformat()
    actor_id = user.get("id") or ""

    results = {
        "created": 0, "attached": 0, "skipped": 0, "errored": 0,
        "row_errors": [],
    }
    created_ids: List[str] = []
    attached_ids: List[str] = []

    for row in payload.rows:
        action = (row.action or "skip").lower()
        if action == "skip":
            results["skipped"] += 1
            continue
        clean = _sanitize_mapped_for_write(row.mapped_fields)
        if action == "create":
            # Minimum signal — must have a name OR an email OR a
            # phone, else the row is unusable even post-operator-
            # confirm.
            if not (clean.get("name") or clean.get("email")
                    or clean.get("phone")):
                results["errored"] += 1
                results["row_errors"].append({
                    "row_num": row.row_num,
                    "reason": "no_signal_for_create",
                })
                continue
            doc_id = new_id()
            doc = {
                "id": doc_id,
                "tenant_id": tenant_id,
                "name": clean.get("name") or (
                    clean.get("email") or clean.get("phone") or ""
                ),
                "email": clean.get("email", ""),
                "phone": clean.get("phone", ""),
                "home_phone": clean.get("home_phone", ""),
                "address": clean.get("address", ""),
                "billing_address": clean.get("billing_address", ""),
                "city": clean.get("city", ""),
                "state": clean.get("state", ""),
                "zip": clean.get("zip", ""),
                "gate_code": clean.get("gate_code", ""),
                "notes": clean.get("notes", ""),
                "tags": clean.get("tags", []),
                "first_name": clean.get("first_name", ""),
                "last_name": clean.get("last_name", ""),
                "created_at": now_iso,
                "updated_at": now_iso,
                "created_by": actor_id,
                "source": "excel_csv_ai_import_v1",
                "deleted_at": None,
                "is_active": True,
            }
            try:
                await db.customers.insert_one(doc)
                created_ids.append(doc_id)
                results["created"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[customers-excel-import] insert failed "
                    "tenant=%s row=%s exc=%r",
                    tenant_id, row.row_num, exc,
                )
                results["errored"] += 1
                results["row_errors"].append({
                    "row_num": row.row_num, "reason": "insert_failed",
                })
            continue
        if action == "attach":
            cid = row.attach_to_customer_id
            if not cid:
                results["errored"] += 1
                results["row_errors"].append({
                    "row_num": row.row_num,
                    "reason": "missing_attach_customer_id",
                })
                continue
            # Guard — the attach target must still be a live, non-
            # merged, in-tenant customer at commit time.
            target = await db.customers.find_one(
                {
                    "id": cid, "tenant_id": tenant_id,
                    "deleted_at": {"$in": [None, "", False]},
                    "$or": [
                        {"merged_into": None},
                        {"merged_into": {"$exists": False}},
                    ],
                },
                {"_id": 0, "id": 1},
            )
            if not target:
                results["errored"] += 1
                results["row_errors"].append({
                    "row_num": row.row_num,
                    "reason": "attach_target_not_found",
                })
                continue
            # Build the $set payload — ONLY keys present in the
            # mapped dict (operator Q3 'fill only present fields').
            set_payload: Dict[str, Any] = {}
            for key in TARGET_FIELDS:
                if key in clean:
                    set_payload[key] = clean[key]
            if not set_payload:
                # Nothing to patch — count as attach but no-op.
                attached_ids.append(cid)
                results["attached"] += 1
                continue
            set_payload["updated_at"] = now_iso
            set_payload["last_import_source"] = "excel_csv_ai_import_v1"
            try:
                await db.customers.update_one(
                    {"id": cid, "tenant_id": tenant_id},
                    {"$set": set_payload},
                )
                attached_ids.append(cid)
                results["attached"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[customers-excel-import] attach-patch failed "
                    "tenant=%s row=%s cid=%s exc=%r",
                    tenant_id, row.row_num, cid, exc,
                )
                results["errored"] += 1
                results["row_errors"].append({
                    "row_num": row.row_num,
                    "reason": "attach_patch_failed",
                })
            continue
        # Unknown action → treat as skip + log for triage.
        logger.warning(
            "[customers-excel-import] unknown action=%r row=%s",
            action, row.row_num,
        )
        results["skipped"] += 1

    # Drop the batch — one-shot commit per operator ask.
    _PREVIEW_BATCHES.pop(payload.batch_id, None)

    return {
        **results,
        "created_ids": created_ids,
        "attached_ids": attached_ids,
    }


__all__ = ["router"]

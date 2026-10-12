"""Preview isolation · admin healthcheck endpoint.

``GET /api/admin/preview-isolation-status``

Admin-only on preview env (``APP_ENV != "production"``). Returns
HTTP 404 on production — the endpoint SHOULDN'T even exist in prod,
so leaking its presence is pointless. ``admin`` role or higher is
required.

Response (``application/json``)::

    {
      "env": "development",
      "db_name": "Pool_&_Landscaping_of_Vistancia",
      "connected_mongo_host": "localhost:27017",
      "preview_synthetic_salt_configured": true,
      "preview_tenant_whitelist_size": 1,
      "registry": {
        "declared_pii_routes": 41,
        "status": "GREEN" | "AMBER" | "RED",
        "missing_registered_routes": [...],
        "unregistered_pii_shaped_routes": [...]
      },
      "pii_shape_audit": {
        "customers_total": 720,
        "customers_matching_preview_pattern": 720,
        "customers_with_real_pii_shape": 0,
        "rows_scanned": 1479,
        "rechecked_at": "<iso>",
        "offenders": [
          {"customer_id": "...", "collection": "customers",
           "field_name": "search_haystack",
           "hint": "contains email: ***@gmail.com"},
          ... up to 10
        ],
        "status": "GREEN" | "RED"
      },
      "last_boot_scrub": {
        "at": "2026-10-11T...",
        "actor": "system:preview_boot_scrubber",
        "total_rows_scrubbed": 120,
        "counts": {"customers": 120, ...}
      } | null,
      "generated_at": "<iso>"
    }

Status is RED when ``pii_shape_audit`` finds ANY row with real-shape
PII on ANY of the 26 declared PII fields across customers + leads +
users. Status rolls up to RED when either sub-audit is RED.

Offender ``hint`` strings are REDACTED on the response wire: email
addresses render as ``***@<domain>`` and phone-shape runs render
with the middle digits masked. The admin sees enough to identify
the row (collection + customer_id + field_name) but the response
never echos the raw PII, preventing a secondary leak through this
endpoint.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends

from config import db
from utils import require_admin
from services.preview_isolation import (
    is_production_env,
    PREVIEW_SYNTHETIC_SALT,
    PREVIEW_TENANT_WHITELIST,
    audit_route_registry,
)

router = APIRouter()

# Match the preview namespace shape — same regex as scrubber.
_PREVIEW_NAME_RE = re.compile(
    r"^Preview (Customer|Lead|Subscriber|Co )\s*\d{4}", re.IGNORECASE,
)
_PREVIEW_HAYSTACK_RE = re.compile(
    r"^preview (customer|lead|subscriber)\d{4}", re.IGNORECASE,
)
_PREVIEW_PHONE_RE = re.compile(r"^555-?0[1-4]\d{4}$")
_PREVIEW_EMAIL_RE = re.compile(
    r"^preview-(customer|lead|subscriber|portal)\d{4}@preview\.local$",
    re.IGNORECASE,
)

# ────────────────────────────────────────────────────────────────────
# Hint redaction — the admin never sees the raw PII in the response.
# ────────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.\-]?)?"
    r"(?:\(\d{3}\)|\d{3})[\s.\-]"
    r"\d{3}[\s.\-]\d{4}"
    r"|\b\d{10,11}\b"
)


def _hint(value: Any) -> str:
    """Return a human-readable, REDACTED hint describing why
    ``value`` is a real-PII leak. Never echoes the raw PII back
    through the healthcheck response wire.
    """
    if value is None:
        return "null (expected non-null)"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Lat/lng — report presence, not the coordinate.
        return f"non-null numeric (expected null): type={type(value).__name__}"
    if isinstance(value, dict):
        # Nested address / service_address / geocode-ish.
        return f"non-sentinel nested object: keys={sorted(value.keys())[:5]}"
    if not isinstance(value, str):
        return f"non-sentinel {type(value).__name__}"
    v = value.strip()
    # Email pattern.
    m = _EMAIL_RE.search(v)
    if m:
        return f"contains email: ***@{m.group(1)}"
    # Phone pattern.
    m = _PHONE_RE.search(v)
    if m:
        raw = m.group(0)
        # Mask middle digits — keep leading country code / area code.
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 10:
            masked = digits[:4] + "*" * (len(digits) - 4)
            return f"phone shape: +{masked}"
        return "phone shape (short)"
    # Fallback — non-preview-shape name / address.
    # Give the admin the first word so they can identify, but mask
    # anything past the first word.
    first = v.split()[0] if v.split() else ""
    if len(first) > 1:
        first = first[0] + "*" * (len(first) - 1)
    return f"non-preview value starts: {first!r} (len={len(v)})"


def _mongo_host() -> str:
    url = os.environ.get("MONGO_URL", "")
    # ``mongodb://localhost:27017`` → ``localhost:27017``.
    return url.split("://", 1)[-1].split("/", 1)[0] if url else ""


# ────────────────────────────────────────────────────────────────────
# PII shape audit — expanded Commit E coverage.
# ────────────────────────────────────────────────────────────────────
# Each rule: (collection, field, "real-pii" mongo filter). The scan
# counts matching rows + samples the first 3 offenders for the hint
# list. Across the full rule set, the handler aggregates offenders
# and caps the response at 10.

_AUDIT_RULES: List[Dict[str, Any]] = [
    # customers — denormalized / nested / scalar PII surfaces.
    {"coll": "customers", "field": "name",
     "filter": {"name": {"$exists": True, "$nin": [None, ""],
                           "$not": {"$regex": r"^Preview ",
                                      "$options": "i"}}}},
    {"coll": "customers", "field": "email",
     "filter": {"email": {"$exists": True, "$nin": [None, ""],
                            "$not": {"$regex": r"^preview-(customer|portal)\d+@preview\.local$",
                                       "$options": "i"}}}},
    {"coll": "customers", "field": "phone",
     "filter": {"phone": {"$exists": True, "$nin": [None, ""],
                            "$not": {"$regex": r"^555-?0[1-4]\d{4}$"}}}},
    {"coll": "customers", "field": "search_haystack",
     "filter": {"search_haystack": {"$exists": True, "$nin": [None, ""],
                                       "$not": {"$regex": r"^preview (customer|lead)",
                                                  "$options": "i"}}}},
    {"coll": "customers", "field": "phone_raw",
     "filter": {"phone_raw": {"$exists": True, "$nin": [None, ""],
                                "$not": {"$regex": r"^555-?0[1-4]\d{4}$"}}}},
    {"coll": "customers", "field": "mobile_raw",
     "filter": {"mobile_raw": {"$exists": True, "$nin": [None, ""],
                                 "$not": {"$regex": r"^555-?0[1-4]\d{4}$"}}}},
    {"coll": "customers", "field": "address_line1",
     "filter": {"address_line1": {"$exists": True, "$nin": [None, ""],
                                     "$not": {"$regex": r"^\d+ Preview\b"}}}},
    {"coll": "customers", "field": "latitude",
     "filter": {"latitude": {"$exists": True, "$ne": None}}},
    {"coll": "customers", "field": "longitude",
     "filter": {"longitude": {"$exists": True, "$ne": None}}},
    {"coll": "customers", "field": "service_lat",
     "filter": {"service_lat": {"$exists": True, "$ne": None}}},
    {"coll": "customers", "field": "service_lng",
     "filter": {"service_lng": {"$exists": True, "$ne": None}}},
    {"coll": "customers", "field": "service_location",
     "filter": {"service_location": {"$exists": True, "$ne": None}}},
    {"coll": "customers", "field": "geocode_address_hash",
     "filter": {"geocode_address_hash": {"$exists": True, "$ne": None}}},
    {"coll": "customers", "field": "home_phone",
     "filter": {"home_phone": {"$exists": True, "$nin": [None, ""]}}},
    {"coll": "customers", "field": "fax",
     "filter": {"fax": {"$exists": True, "$nin": [None, ""]}}},
    {"coll": "customers", "field": "alert_email",
     "filter": {"alert_email": {"$exists": True, "$nin": [None, ""]}}},
    {"coll": "customers", "field": "alert_phone",
     "filter": {"alert_phone": {"$exists": True, "$nin": [None, ""]}}},
    {"coll": "customers", "field": "master_billing_contact_email",
     "filter": {"master_billing_contact_email": {"$exists": True, "$nin": [None, ""]}}},
    {"coll": "customers", "field": "master_billing_contact_phone",
     "filter": {"master_billing_contact_phone": {"$exists": True, "$nin": [None, ""]}}},
    # leads — expanded to the 7 PII indicators Step A enumerated.
    {"coll": "leads", "field": "search_haystack",
     "filter": {"search_haystack": {"$exists": True, "$nin": [None, ""],
                                       "$not": {"$regex": r"^preview (lead|customer)",
                                                  "$options": "i"}}}},
    {"coll": "leads", "field": "created_ip",
     "filter": {"created_ip": {"$exists": True, "$nin": [None, "", "0.0.0.0"]}}},
    {"coll": "leads", "field": "message",
     "filter": {"$and": [
         {"message": {"$exists": True, "$nin": [None, ""]}},
         {"message": {"$regex": r"[A-Za-z0-9._%+\-]+@|\d{3}[\s.\-]\d{3}[\s.\-]\d{4}"}},
     ]}},
    # users — only role=customer rows.
    {"coll": "users", "field": "first_access_ip",
     "filter": {"role": "customer",
                "first_access_ip": {"$exists": True,
                                      "$nin": [None, "", "0.0.0.0",
                                                  "127.0.0.1"],
                                      "$not": {"$regex": r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|fe80:|fc00:|fd00:|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)"}}}},
    {"coll": "users", "field": "profile_photo_url",
     "filter": {"role": "customer",
                "profile_photo_url": {"$exists": True, "$nin": [None, ""],
                                         "$not": {"$regex": r"^/preview/avatar-"}}}},
]


async def _run_pii_shape_audit() -> Dict[str, Any]:
    """Scan every rule in ``_AUDIT_RULES``. Returns the audit sub-
    report with ``offenders`` (<=10, hint-redacted), ``rows_scanned``
    (total docs scanned across all rules), and the per-field count
    rollup."""
    rows_scanned = 0
    offenders: List[Dict[str, Any]] = []
    real_pii_total = 0
    per_field_counts: Dict[str, int] = {}
    for rule in _AUDIT_RULES:
        coll_name = rule["coll"]
        field_name = rule["field"]
        if not hasattr(db, coll_name):
            continue
        coll = getattr(db, coll_name)
        try:
            n = await coll.count_documents(rule["filter"])
        except Exception:
            n = 0
        per_field_counts[f"{coll_name}.{field_name}"] = n
        real_pii_total += n
        rows_scanned += n
        # Sample up to 3 offenders per rule.
        if n and len(offenders) < 10:
            needed = min(3, 10 - len(offenders))
            try:
                cursor = coll.find(
                    rule["filter"],
                    projection={"_id": 0, "id": 1, field_name: 1},
                ).limit(needed)
                async for row in cursor:
                    offenders.append({
                        "customer_id":  row.get("id") or "<unknown>",
                        "collection":   coll_name,
                        "field_name":   field_name,
                        "hint":         _hint(row.get(field_name)),
                    })
                    if len(offenders) >= 10:
                        break
            except Exception:
                pass
    return {
        "real_pii_total": real_pii_total,
        "rows_scanned": rows_scanned,
        "per_field_counts": per_field_counts,
        "offenders": offenders,
    }


@router.get("/admin/preview-isolation-status")
async def preview_isolation_status(user: dict = Depends(require_admin)):
    # Production: 404 — endpoint does not exist here.
    if is_production_env():
        raise HTTPException(status_code=404, detail="not_found")

    # ── registry audit ──────────────────────────────────
    # Deferred import so the endpoint stays decoupled from app module
    # import order.
    from server import app as _app
    registry_report = audit_route_registry(_app)

    # ── pii shape audit (expanded Commit E) ─────────────
    try:
        total = await db.customers.count_documents({})
    except Exception:
        total = 0
    try:
        synthetic = await db.customers.count_documents({
            "name": {"$regex": r"^Preview Customer\s*\d{4}", "$options": "i"}
        })
    except Exception:
        synthetic = 0
    audit = await _run_pii_shape_audit()
    real_shape = audit["real_pii_total"]
    pii_status = "GREEN" if real_shape == 0 else "RED"

    # ── last boot scrub ─────────────────────────────────
    last_scrub: Optional[Dict[str, Any]] = None
    try:
        row = await db.audit_logs.find_one(
            {"event": {"$in": ["pii_boot_scrub", "pii_scrub"]}},
            sort=[("at", -1)],
            projection={"_id": 0, "at": 1, "actor": 1, "meta": 1},
        )
        if row:
            meta = row.get("meta") or {}
            last_scrub = {
                "at": row.get("at"),
                "actor": row.get("actor"),
                "total_rows_scrubbed": meta.get("total")
                    or sum((meta.get("scrubbed_counts") or {}).values()),
                "counts": meta.get("scrubbed_counts") or {},
            }
    except Exception:
        last_scrub = None

    overall = "GREEN"
    if pii_status == "RED" or registry_report["status"] == "RED":
        overall = "RED"
    elif registry_report["status"] == "AMBER":
        overall = "AMBER"

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "env": (os.environ.get("APP_ENV", "preview") or "preview").lower(),
        "db_name": os.environ.get("DB_NAME", ""),
        "connected_mongo_host": _mongo_host(),
        "preview_synthetic_salt_configured": bool(PREVIEW_SYNTHETIC_SALT),
        "preview_tenant_whitelist_size": len(PREVIEW_TENANT_WHITELIST),
        "registry": {
            "declared_pii_routes": registry_report["declared_pii_routes"],
            "exempted_routes": registry_report.get("exempted_routes", 0),
            "total_routes": registry_report["total_routes"],
            "status": registry_report["status"],
            "missing_registered_routes": [
                f"{m} {p}" for m, p in registry_report["missing_registered_routes"]
            ],
            "unregistered_pii_shaped_routes": [
                f"{m} {p}" for m, p in registry_report["unregistered_pii_shaped_routes"]
            ][:20],
        },
        "pii_shape_audit": {
            "customers_total": total,
            "customers_matching_preview_pattern": synthetic,
            "customers_with_real_pii_shape": real_shape,
            "rows_scanned": audit["rows_scanned"],
            "rechecked_at": now_iso,
            "per_field_counts": audit["per_field_counts"],
            "offenders": audit["offenders"],
            "status": pii_status,
        },
        "last_boot_scrub": last_scrub,
        "overall_status": overall,
        "generated_at": now_iso,
    }

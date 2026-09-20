"""Phase A5 · Feb-2026 · Proactive Intelligence — Tech Smart Brief.

Backend-only endpoint that returns a compact "everything a tech
needs on job open" payload for the mobile app to render a Smart
Brief screen. Mobile UI itself lands via ``e1_expo_frontend_dev``
after this backend endpoint is proven green.

Contract
--------
``GET /api/jobs/{job_id}/smart-brief`` — returns:

::

    {
      "job_id":       "...",
      "customer_id":  "...",
      "customer": {
        "id":           "...",
        "display_name": "...",
        "phone":        "..."|None,
        "address_line": "..."|None,
        "coordinates":  {"lat": float, "lng": float}|None,
      },
      "special_access": {
        "gate_code":       "..."|None,
        "key_location":    None,             # not persisted today
        "dog_on_property": bool,
        "dog_notes":       "..."|None,
        "other_notes":     "..."|None,       # customer.service_notes
      },
      "last_visits": [
        {
          "visit_id":          "...",
          "completed_at":      "ISO",
          "tech_display_name": "...",
          "service_type":      "...",
          "duration_minutes":  int|None,
          "chemistry_snapshot": {
             "salt":..., "ph":..., "alkalinity":..., "chlorine":...,
             "cyanuric_acid":..., "hardness":...,
          },
          "notes": [{"author_display_name": "...", "body": "...",
                       "created_at": "ISO"}],
        },
        ... up to 3, DESC by completed_at
      ],
      "open_intelligence_alerts": [
        {"alert_id": "...", "category": "...", "severity": "...",
          "title": "...", "body": "...", "created_at": "ISO"},
        ... top 5, dismissed_at=None, DESC by created_at
      ]
    }

Auth
----
Assigned tech (``users.technician_id == job.technician_id``) OR
role in ``{admin, super_admin, manager}``. Anything else → 403
``insufficient_role_for_brief``. Cross-tenant → 404
``job_not_found`` (do not disclose existence).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user

# NOTE — this router is included into ``api_router`` (which already
# adds the ``/api`` prefix in ``server.py``). Path decorators here
# start with a plain slash so the final URL resolves to
# ``/api/jobs/{job_id}/smart-brief``.
router = APIRouter(tags=["tech-brief"])


# Canonical chemistry keys we surface in the snapshot. Mirrors the
# A2 chemistry-upsell scan + Phase 51 pool-reading vocabulary.
_CHEM_KEYS = ("salt", "ph", "alkalinity", "free_chlorine",
              "cyanuric_acid", "calcium_hardness")

# Map internal reading keys → the compact snapshot field names in
# the response contract (``free_chlorine`` → ``chlorine``,
# ``calcium_hardness`` → ``hardness``) so the mobile UI stays
# stable if we ever rename an internal key.
_CHEM_OUT = {
    "salt":              "salt",
    "ph":                "ph",
    "alkalinity":        "alkalinity",
    "free_chlorine":     "chlorine",
    "cyanuric_acid":     "cyanuric_acid",
    "calcium_hardness":  "hardness",
}


def _iso(v: Any) -> Optional[str]:
    """Best-effort ISO-8601 render for datetime / string inputs."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return str(v)


def _display_name(user_or_customer: Dict[str, Any]) -> str:
    """Compose a human-facing display name from a user or customer
    document — falls through name → first+last → email → id."""
    if not user_or_customer:
        return ""
    if user_or_customer.get("name"):
        return user_or_customer["name"]
    first = user_or_customer.get("first_name") or ""
    last  = user_or_customer.get("last_name") or ""
    joined = f"{first} {last}".strip()
    if joined:
        return joined
    return user_or_customer.get("email") or user_or_customer.get("id") or ""


def _coerce_reading(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _chem_snapshot(report: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Extract the 6 canonical chemistry readings from a service
    report. Missing keys render as ``None`` — never omitted from
    the response so the mobile client can rely on a stable shape."""
    out: Dict[str, Optional[float]] = {v: None for v in _CHEM_OUT.values()}
    arr = (report.get("chemical_readings")
           or report.get("readings") or [])
    if isinstance(arr, list):
        for row in arr:
            if not isinstance(row, dict):
                continue
            key = row.get("key") or row.get("name")
            if key in _CHEM_OUT:
                out[_CHEM_OUT[key]] = _coerce_reading(row.get("value"))
    return out


async def _resolve_tech_display(tenant_id: str,
                                    tech_id: Optional[str]) -> str:
    """Resolve ``service_reports.tech_id`` → display name.
    ``tech_id`` is ``users.technician_id`` in this codebase."""
    if not tech_id:
        return ""
    row = await db.users.find_one(
        {"technician_id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1,
         "email": 1, "id": 1},
    )
    if row:
        return _display_name(row)
    # Fallback: some legacy seeds put the ``users.id`` in tech_id.
    row = await db.users.find_one(
        {"id": tech_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1,
         "email": 1, "id": 1},
    )
    return _display_name(row or {})


async def _last_visits(tenant_id: str, customer_id: str
                          ) -> List[Dict[str, Any]]:
    """Return up to 3 most-recent completed visits for a customer,
    DESC by ``submitted_at`` — the same "visit" concept the Phase B
    unified timeline surfaces."""
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0, "id": 1, "service_type": 1,
         "duration_minutes": 1, "notes": 1},
    ).to_list(10_000)
    by_id = {j["id"]: j for j in jobs if j.get("id")}
    if not by_id:
        return []
    reports = await db.service_reports.find(
        {"tenant_id":    tenant_id,
         "job_id":       {"$in": list(by_id.keys())},
         "submitted_at": {"$ne": None}},
        {"_id": 1, "id": 1, "job_id": 1, "tech_id": 1,
         "submitted_at": 1, "chemical_readings": 1, "readings": 1,
         "notes": 1},
    ).sort("submitted_at", -1).limit(3).to_list(3)

    out: List[Dict[str, Any]] = []
    for r in reports:
        job = by_id.get(r["job_id"]) or {}
        tech_name = await _resolve_tech_display(
            tenant_id, r.get("tech_id"))
        notes: List[Dict[str, Any]] = []
        # Per-visit note lives on ``service_reports.notes`` (single
        # string). Attach it as one entry authored by the tech who
        # submitted the visit. If the field is empty, ``notes``
        # renders as an empty array.
        note_body = (r.get("notes") or "").strip()
        if note_body:
            notes.append({
                "author_display_name": tech_name or "Technician",
                "body":                note_body,
                "created_at":          _iso(r.get("submitted_at")),
            })
        out.append({
            "visit_id":          str(r.get("id") or r.get("_id")),
            "completed_at":      _iso(r.get("submitted_at")),
            "tech_display_name": tech_name,
            "service_type":      job.get("service_type") or "",
            "duration_minutes":  job.get("duration_minutes"),
            "chemistry_snapshot": _chem_snapshot(r),
            "notes":             notes,
        })
    return out


async def _open_alerts(tenant_id: str, customer_id: str
                          ) -> List[Dict[str, Any]]:
    """Return up to 5 most-recent open intelligence alerts for the
    customer (``dismissed_at = None``, both read + unread), DESC by
    ``created_at``. Alerts don't carry a UUID ``id`` field — the
    Mongo ObjectId is projected + stringified for stable
    client-side keying (matches the response contract on
    :mod:`routers.intelligence_alerts`)."""
    cursor = db.intelligence_alerts.find(
        {"tenant_id":    tenant_id,
         "customer_id":  customer_id,
         "dismissed_at": None},
        {"_id": 1, "category": 1, "severity": 1,
         "title": 1, "body": 1, "created_at": 1},
    ).sort("created_at", -1).limit(5)
    out: List[Dict[str, Any]] = []
    async for a in cursor:
        out.append({
            "alert_id":   str(a.get("_id")),
            "category":   a.get("category"),
            "severity":   a.get("severity"),
            "title":      a.get("title") or "",
            "body":       a.get("body") or "",
            "created_at": _iso(a.get("created_at")),
        })
    return out


def _authz_ok(user: Dict[str, Any], job: Dict[str, Any]) -> bool:
    """Assigned tech OR admin / super_admin / manager. Everyone
    else — customer, marketer, dispatcher, sales, unknown — is
    rejected here (route caller then raises 403)."""
    role = (user or {}).get("role") or ""
    if role in ("admin", "super_admin", "manager"):
        return True
    if role == "technician":
        return (
            (user.get("technician_id")
              and user.get("technician_id") == job.get("technician_id"))
            or user.get("id") == job.get("technician_id")
        )
    return False


@router.get("/jobs/{job_id}/smart-brief")
async def get_smart_brief(
    job_id: str,
    user:   Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Return the Smart Brief payload for a single job.

    See module docstring for the full response contract.
    """
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")
    if not _authz_ok(user, job):
        raise HTTPException(
            status_code=403, detail="insufficient_role_for_brief",
        )

    customer_id = job.get("customer_id") or ""
    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    ) or {}

    # Coordinates — prefer service_lat/service_lng (route-optimized
    # dispatch), fall back to the legacy latitude/longitude.
    coords: Optional[Dict[str, float]] = None
    lat = customer.get("service_lat") or customer.get("latitude")
    lng = customer.get("service_lng") or customer.get("longitude")
    try:
        if lat is not None and lng is not None:
            coords = {"lat": float(lat), "lng": float(lng)}
    except (TypeError, ValueError):
        coords = None

    customer_out = {
        "id":           customer.get("id") or customer_id,
        "display_name": _display_name(customer)
                          or job.get("customer_name") or "",
        "phone":        (customer.get("phone")
                          or customer.get("home_phone")
                          or ((customer.get("mobiles") or []) or [""])[0]
                          or None),
        "address_line": customer.get("address") or None,
        "coordinates":  coords,
    }

    # Special access — customer.gate_code is the canonical source.
    # ``key_location``, ``dog_on_property``, ``dog_notes`` are
    # intake-template fields that don't have a first-class storage
    # slot today (see Phase A5 audit) — surface whatever value the
    # customer doc happens to carry via a template render, else
    # sensible defaults.
    special_access = {
        "gate_code":       customer.get("gate_code") or None,
        "key_location":    customer.get("key_location") or None,
        "dog_on_property": bool(customer.get("dog_on_property")),
        "dog_notes":       customer.get("dog_notes") or None,
        "other_notes":     (customer.get("service_notes")
                             or customer.get("notes") or None),
    }

    last_visits = await _last_visits(tenant["id"], customer_id) \
                    if customer_id else []
    open_alerts = await _open_alerts(tenant["id"], customer_id) \
                    if customer_id else []

    return {
        "job_id":                    job.get("id") or job_id,
        "customer_id":               customer_id,
        "customer":                  customer_out,
        "special_access":            special_access,
        "last_visits":               last_visits,
        "open_intelligence_alerts":  open_alerts,
    }

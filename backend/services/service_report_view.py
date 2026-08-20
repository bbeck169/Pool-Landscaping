"""Feb-2026 · Shared service-report view resolvers.

Both the Workstream Service Log page and the door-hanger email need
to render the same 5 chunks of a submitted service report:

    * checklist state
    * water-test readings (canonical 5 + custom keys)
    * chemicals used (+ cost calc)
    * service notes
    * photos

Before this module existed the two consumers each read from
``job.chemical_readings`` / ``job.chemicals_added`` / ``job.notes``
directly — which is why both surfaces silently rendered blank for
every real tech submission (techs write to ``service_reports.*``).

The Workstream P0 fix landed the correct joins inline in
``routers/workstream_service_log.py``.  The door-hanger P0 fix needs
the identical logic in a second consumer, so the water-test /
chemicals-used / notes resolvers are hoisted here and both consumers
now import them.

Nothing in this module is HTTP-aware — every resolver takes a raw
``job`` dict + ``tenant_id`` and returns a plain shape the caller
can render into JSON or HTML.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple


# ─── Chemical price map ───────────────────────────────────────────────
_DEFAULT_CHEM_PRICES_CENTS: Dict[str, int] = {
    "chlorine tablets":       120,
    "3\" chlorine tablets":   120,
    "liquid chlorine":        800,
    "liquid acid":            800,
    "muriatic acid":          800,
}


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


async def load_price_map(db, tenant_id: str) -> Dict[str, int]:
    doc = await db.chemical_prices.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "prices": 1},
    ) or {}
    prices = doc.get("prices") or {}
    merged = {**_DEFAULT_CHEM_PRICES_CENTS}
    for k, v in prices.items():
        try:
            merged[_norm(k)] = int(round(float(v) * 100))
        except (TypeError, ValueError):
            continue
    return merged


def chem_line_cost_cents(name: str, qty: float, prices: Dict[str, int]) -> int:
    key = _norm(name)
    if key in prices:
        return int(round(qty * prices[key]))
    for k, price in prices.items():
        if k and k in key:
            return int(round(qty * price))
    return 0


# ─── Canonical water-test key order (post-P0 Workstream fix) ─────────
_WATER_TEST_CANONICAL: List[Tuple[str, str, str]] = [
    ("free_chlorine",   "Free Chlorine",  "ppm"),
    ("total_chlorine",  "Total Chlorine", "ppm"),
    ("ph",              "Ph Balance",     ""),
    ("alkalinity",      "Alkalinity",     "ppm"),
    ("cyanuric_acid",   "CYA",            "ppm"),
    ("conditioner",     "Conditioner",    "ppm"),
]


def _coerce_readings(raw: Any) -> Dict[str, Any]:
    """Accept both storage shapes and return a flat ``{key: value}``
    dict.  ``list`` = canonical tech write path.  ``dict`` = legacy."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, list):
        out: Dict[str, Any] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            k = (row.get("key") or "").strip()
            if not k:
                continue
            out[k] = row.get("value")
        return out
    return {}


async def resolve_water_test(db, job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    """Return the emitted water-test rows in canonical order (+ custom
    keys appended after)."""
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id"),
         "chemical_readings": {"$exists": True}},
        {"_id": 0, "chemical_readings": 1},
    )
    readings = _coerce_readings((rep or {}).get("chemical_readings"))
    if not readings:
        readings = _coerce_readings(job.get("chemical_readings"))

    out: List[Dict[str, Any]] = []
    emitted: set = set()
    for key, label, unit in _WATER_TEST_CANONICAL:
        if key not in readings:
            continue
        v = readings[key]
        if v in (None, ""):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        out.append({"key": key, "label": label, "value": fv, "unit": unit})
        emitted.add(key)
    for key, v in readings.items():
        if key in emitted or v in (None, ""):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        out.append({
            "key": key,
            "label": key.replace("_", " ").title(),
            "value": fv,
            "unit": "",
        })
    return out


async def resolve_chemicals_used_raw(db, job: dict, tenant_id: str) -> List[Dict[str, Any]]:
    """Return the raw ``chemicals_added`` list from the service report
    (canonical write target), falling back to ``job.chemicals_added``
    for legacy jobs."""
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id"),
         "chemicals_added": {"$exists": True}},
        {"_id": 0, "chemicals_added": 1},
    )
    src = (rep or {}).get("chemicals_added")
    if not src:
        src = job.get("chemicals_added") or []
    return src or []


def format_chem_qty(qty: float, unit: str) -> str:
    unit = (unit or "").strip()
    if unit.lower() in ("gal", "gallon", "gallons"):
        u = "Gallon" if qty <= 1 else "Gallons"
        return f"{int(qty) if qty == int(qty) else qty} {u}"
    if unit:
        return f"{int(qty) if qty == int(qty) else qty} {unit}"
    return str(int(qty) if qty == int(qty) else qty)


async def resolve_chemicals_used_with_cost(
    db, job: dict, tenant_id: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return ``(chems_list, total_cents)`` with priced line items —
    matches the Workstream Service Log payload contract exactly."""
    prices = await load_price_map(db, tenant_id)
    chems: List[Dict[str, Any]] = []
    total_cents = 0
    for c in await resolve_chemicals_used_raw(db, job, tenant_id):
        name = c.get("name") or c.get("chemical") or ""
        qty = c.get("quantity") or c.get("amount") or 0
        unit = c.get("unit") or ""
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            qty_f = 0.0
        cost_c = chem_line_cost_cents(name, qty_f, prices)
        total_cents += cost_c
        chems.append({
            "name": name,
            "quantity": qty_f,
            "unit": unit,
            "display": format_chem_qty(qty_f, unit),
            "cost_cents": cost_c,
        })
    return chems, total_cents


async def resolve_checklist_state(
    db, job: dict, tenant_id: str, service_line: str,
    canon_pool: List[Dict[str, Any]],
    canon_landscape: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Canonical checklist state — prefers ``key`` matches over
    ``label`` matches, falls back to ``_norm(label)`` when both sides
    lack a ``key`` (Workstream P0 Fix C).
    """
    tenant_doc = await db.service_checklists.find_one(
        {"tenant_id": tenant_id, "service_line": service_line},
        {"_id": 0, "items": 1},
    )
    canon = (tenant_doc or {}).get("items") or (
        canon_pool if service_line == "pool" else canon_landscape
    )
    key_map: Dict[str, bool] = {}
    label_map: Dict[str, bool] = {}

    def _record(it: dict) -> None:
        if not (it.get("done") or it.get("checked")):
            return
        k = (it.get("key") or "").strip()
        if k:
            key_map[k] = True
            return
        lbl = _norm(it.get("label"))
        if lbl:
            label_map[lbl] = True

    for it in (job.get("checklist") or []):
        _record(it)
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id"),
         "checklist_items": {"$exists": True}},
        {"_id": 0, "checklist_items": 1},
    )
    for it in ((rep or {}).get("checklist_items") or []):
        _record(it)

    items_out: List[Dict[str, Any]] = []
    for it in canon:
        ck = (it.get("key") or "").strip()
        completed = False
        if ck and ck in key_map:
            completed = True
        else:
            completed = bool(label_map.get(_norm(it.get("label"))))
        items_out.append({
            "key": it.get("key"),
            "label": it.get("label"),
            "completed": completed,
        })
    return {"service_line": service_line, "items": items_out, "count": len(items_out)}


async def resolve_notes(db, job: dict, tenant_id: str) -> str:
    """Return the freshest service notes for a job.

    Priority order:
      1. ``service_reports.notes`` for the submitted report (canonical
         write target for the tech's freeform notes).
      2. ``service_reports.summary_notes`` for older-shape reports.
      3. Legacy inline ``job.service_notes`` / ``job.notes``.
    """
    rep = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job.get("id")},
        {"_id": 0, "notes": 1, "summary_notes": 1, "submitted_at": 1},
        sort=[("submitted_at", -1)],
    ) or {}
    for k in ("notes", "summary_notes"):
        v = (rep.get(k) or "").strip() if isinstance(rep.get(k), str) else ""
        if v:
            return v
    return (job.get("service_notes") or job.get("notes") or "").strip()


# ─── Photo helpers ────────────────────────────────────────────────────
def _resolve_public_base_url() -> str:
    """Pick the best public base URL for absolute photo links in emails.

    Priority:
      1. ``PUBLIC_APP_BASE_URL`` (explicit override for email links)
      2. ``FRONTEND_BASE_URL`` (already used by team-invite emails)
      3. ``APP_BASE_URL`` (legacy)
      4. Hard-coded fallback to the prod front door.

    Returns a URL with no trailing slash.
    """
    for k in ("PUBLIC_APP_BASE_URL", "FRONTEND_BASE_URL", "APP_BASE_URL"):
        v = os.environ.get(k, "").strip()
        if v:
            return v.rstrip("/")
    return "https://app.plofv.com"


def photo_absolute_url(jid: str, pid: str) -> str:
    """Absolute URL for the unauthenticated ``/api/public/job-photo``
    endpoint.  Safe to inline in ``<img src="…">`` email markup."""
    base = _resolve_public_base_url()
    return f"{base}/api/public/job-photo/{jid}/{pid}"


def resolve_photo_items(job: dict) -> List[Dict[str, Any]]:
    """Return every renderable photo on a job.  Kept small on purpose —
    the door-hanger email inlines all of them; the Workstream Service
    Log page renders thumbnails from the same list."""
    out: List[Dict[str, Any]] = []
    jid = job.get("id") or ""
    for p in (job.get("photos") or []):
        pid = p.get("id")
        if not pid:
            continue
        out.append({
            "id": pid,
            "url_absolute": photo_absolute_url(jid, pid),
            "url_relative": f"/api/public/job-photo/{jid}/{pid}",
            "label": p.get("label"),
            "created_at": p.get("created_at"),
        })
    return out

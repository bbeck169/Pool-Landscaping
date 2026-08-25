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


# ─── Tech-name resolver ──────────────────────────────────────────────
async def resolve_technician_names(db, tenant_id: str, ids):
    """4-rung cascade for a mixed bag of ``job.technician_id`` values.

    ``job.technician_id`` is stored inconsistently across ~7 write
    paths (mobile create, admin dispatch, scheduler autocreate,
    service-report submit, reassign, quote→job, etc.).  Some paths
    write a ``technicians.id``, some write a ``users.id``.  The
    "correct long-term fix" is normalising every writer (queued as
    the P2 Tech-ID fragmentation task); the fast fix is teaching the
    reader to accept both shapes.

    Cascade order:
      1. ``db.technicians.id``
      2. ``db.technicians.user_id``  (technician doc back-ref)
      3. ``db.users.id``  (role in ``technician / landscaper / manager / admin``)
      4. ``db.users`` — synthesise from ``first_name + last_name``

    Returns ``{id: display_name}``.  Never raises.  Missing ids
    simply don't appear in the map — the caller applies its own
    ``"Unassigned"`` / ``"Unknown"`` copy.
    """
    ids = [str(x) for x in (ids or []) if x]
    if not ids:
        return {}
    ids = list(dict.fromkeys(ids))  # de-dupe, preserve order
    out: dict = {}

    # 1. technicians.id  — canonical shape.
    async for t in db.technicians.find(
        {"tenant_id": tenant_id, "id": {"$in": ids}},
        {"_id": 0, "id": 1, "name": 1},
    ):
        if t.get("name"):
            out[t["id"]] = t["name"]

    remaining = [i for i in ids if i not in out]
    if not remaining:
        return out

    # 2. technicians.user_id  — back-ref shape.
    async for t in db.technicians.find(
        {"tenant_id": tenant_id, "user_id": {"$in": remaining}},
        {"_id": 0, "user_id": 1, "name": 1},
    ):
        uid = t.get("user_id")
        if uid and t.get("name") and uid not in out:
            out[uid] = t["name"]

    remaining = [i for i in ids if i not in out]
    if not remaining:
        return out

    # 3-4. users.id  — direct user reference.
    # Feb-2026 · P1 hotfix — allowlist extended with ``tech`` (legacy
    # singular shorthand present in seeded users) and ``owner`` so a
    # ``technician_id`` pointing at such a user is no longer silently
    # dropped.
    async for u in db.users.find(
        {"tenant_id": tenant_id, "id": {"$in": remaining},
         "role": {"$in": ["technician", "tech", "landscaper", "manager", "admin", "super_admin", "owner"]}},
        {"_id": 0, "id": 1, "name": 1, "first_name": 1, "last_name": 1},
    ):
        if u.get("name"):
            out[u["id"]] = u["name"]
        else:
            fn = (u.get("first_name") or "").strip()
            ln = (u.get("last_name") or "").strip()
            full = f"{fn} {ln}".strip()
            if full:
                out[u["id"]] = full
    return out


async def resolve_tech_name(db, job: dict, tenant_id: str) -> str:
    """Single-value wrapper for callers with only one job in hand
    (e.g., audit rows, email templates).  Returns the resolved
    display name, then the cached ``job.technician_name`` fallback,
    then ``""`` — the caller applies its own UI copy for empty."""
    tid = (job or {}).get("technician_id")
    if not tid:
        return (job or {}).get("technician_name") or ""
    m = await resolve_technician_names(db, tenant_id, [tid])
    return m.get(tid) or (job or {}).get("technician_name") or ""

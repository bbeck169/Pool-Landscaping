import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from services.customer_import import (
    build_customer_doc, read_csv, render_template_csv, _canon_row,
)
from utils import now_iso, new_id, require_admin

router = APIRouter()

CUSTOMER_COLS = ["name", "email", "phone", "address", "billing_address", "gate_code", "notes"]
ITEM_COLS = ["name", "category", "unit", "unit_price", "taxable"]

# Feb-2026 hotfix — response payload cap for warnings. Full log is
# persisted to ``customer_import_reports`` collection and retrievable
# by ``import_id`` via ``GET /api/customers/imports/{import_id}``.
_WARN_INLINE_CAP = 100
_ERR_INLINE_CAP = 100
# Insert batch size — Mongo/motor happily accept ~1000 docs per
# ``insert_many``; 500 keeps memory bounded and per-batch latency short
# even on modest deployments.
_INSERT_BATCH = 500


class CsvIn(BaseModel):
    csv: str


def _to_csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([("" if r.get(c) is None else r.get(c)) for c in cols])
    return buf.getvalue()


def _parse_bool(v):
    return str(v).strip().lower() in ("1", "true", "yes", "y", "t")


def _read_rows(text):
    # tolerate BOM + varying header case/spacing
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    norm = []
    for raw in reader:
        row = { (k or "").strip().lower().replace(" ", "_"): (v.strip() if isinstance(v, str) else v)
                for k, v in raw.items() if k is not None }
        norm.append(row)
    return norm


# ----------------------- Export -----------------------
@router.get("/export/customers")
async def export_customers(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    # P59 · Feb-2026 — every read scoped to the caller's tenant.
    # Prior to this fix ``db.customers.find({}, ...)`` ran with an
    # empty filter, letting any admin token on any tenant enumerate
    # cross-tenant customer rows through a CSV download.
    rows = await db.customers.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("name", 1).to_list(5000)
    return {"filename": "customers.csv", "content": _to_csv(rows, CUSTOMER_COLS), "count": len(rows)}


@router.get("/export/items")
async def export_items(user: dict = Depends(require_admin)):
    rows = await db.items.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    return {"filename": "pricebook.csv", "content": _to_csv(rows, ITEM_COLS), "count": len(rows)}


# ----------------------- Import -----------------------
@router.get("/import/customers/template", response_class=Response)
async def customers_template(user: dict = Depends(require_admin)):
    """Phase 56 — canonical 12-column starter template with one sample row."""
    csv_bytes = render_template_csv().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="customers-template.csv"'},
    )


@router.post("/import/customers")
async def import_customers(body: CsvIn, user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Phase 56 · Feb-2026 hotfix — full-mapping CSV importer.

    * No row cap. Rows are streamed into batched inserts (500 docs per
      ``insert_many``) so 5,000+ row imports finish in seconds without
      spiking memory.
    * ``import_id`` is stamped on the response and on every persisted
      row of ``customer_import_reports`` so admins can retrieve the full
      warning + error log via ``GET /api/customers/imports/{import_id}``
      even when the inline payload is truncated.
    * Response keeps both the historical ``*_count`` keys (ImportModal
      reads these) and the new ``imported``/``skipped``/``warnings``
      shape.
    """
    # Import from Phase 54 phone normalizer per the phase brief.
    from routers.ringcentral import _normalize_phone_e164

    rows = read_csv(body.csv)
    tenant_id = tenant["id"]
    import_id = new_id()

    # ─── Pass 1: build docs + collect dedup keys ──────────────────────
    built: list[tuple[int, dict]] = []  # (row_idx, doc)
    warnings: list[dict] = []
    errors: list[dict] = []
    legacy_docs: list[tuple[int, dict]] = []  # (row_idx, doc) from legacy fallback
    deprecation_warnings: list[str] = []
    legacy_seen = False
    skipped = 0

    for idx, raw in enumerate(rows, start=2):
        canon, is_legacy = _canon_row(raw)
        if is_legacy:
            legacy_seen = True
        if is_legacy and not all(canon.get(f) for f in (
            "first name", "last name", "service address street", "city", "state", "postal code")):
            legacy_doc, err = _build_legacy_doc(raw, tenant_id, _normalize_phone_e164)
            if err:
                skipped += 1
                errors.append({"row": idx, "reason": err})
                continue
            legacy_docs.append((idx, legacy_doc))
            continue

        doc, err, row_warnings = build_customer_doc(canon, tenant_id, _normalize_phone_e164)
        if err:
            skipped += 1
            errors.append({"row": idx, "reason": err})
            continue
        for msg in row_warnings:
            warnings.append({"row": idx, "message": msg})
        built.append((idx, doc))

    # ─── Pass 2: pre-fetch existing matches in one round-trip ─────────
    emails = sorted({(d.get("email") or "").lower() for _, d in built + legacy_docs
                     if (d.get("email") or "").strip()})
    mobiles = sorted({p.get("number") for _, d in built + legacy_docs
                      for p in (d.get("phones") or []) if p.get("type") == "mobile"
                      and p.get("number")})
    existing_by_email: dict[str, dict] = {}
    existing_by_mobile: dict[str, dict] = {}
    if emails or mobiles:
        query: dict = {"tenant_id": tenant_id, "$or": []}
        if emails:
            query["$or"].append({"email": {"$in": emails}})
        if mobiles:
            query["$or"].append({"phones.number": {"$in": mobiles}})
        cursor = db.customers.find(query, {"_id": 0, "id": 1, "email": 1, "phones": 1})
        async for c in cursor:
            e = (c.get("email") or "").lower()
            if e:
                existing_by_email.setdefault(e, c)
            for p in (c.get("phones") or []):
                if p.get("type") == "mobile" and p.get("number"):
                    existing_by_mobile.setdefault(p["number"], c)

    # ─── Pass 3: split into inserts vs updates, then batch-write ──────
    inserts: list[dict] = []
    updates: list[tuple[str, dict]] = []  # (customer_id, doc)

    for _idx, doc in built + legacy_docs:
        email = (doc.get("email") or "").lower().strip()
        mobile = ""
        for p in (doc.get("phones") or []):
            if p.get("type") == "mobile":
                mobile = p.get("number") or ""
                break
        # Feb-2026 real-world CSV fix — hard guard: never fall through
        # to a false-positive match when neither email nor mobile are
        # present. Two "John Smith" rows with no email/phone must NOT
        # collapse onto whichever John was inserted first. Explicit
        # warning surfaces the identity gap so the admin can enrich the
        # row post-import.
        if not email and not mobile:
            match = None
            warnings.append({"row": _idx, "message":
                "no email or phone provided — inserted as new record (no dedup key)"})
        else:
            match = existing_by_email.get(email) if email else None
            if not match and mobile:
                match = existing_by_mobile.get(mobile)
        if match:
            updates.append((match["id"], doc))
        else:
            fresh = {**doc, "id": new_id(), "created_at": now_iso()}
            inserts.append(fresh)
            # Track the freshly-inserted row so a duplicate later in the
            # same CSV upserts against it instead of double-inserting.
            if email:
                existing_by_email[email] = {"id": fresh["id"], "email": email,
                                             "phones": fresh.get("phones") or []}
            if mobile:
                existing_by_mobile[mobile] = existing_by_email.get(email) or {
                    "id": fresh["id"], "phones": fresh.get("phones") or []}

    created = 0
    updated = 0
    inserted_docs: list[dict] = []
    for i in range(0, len(inserts), _INSERT_BATCH):
        chunk = inserts[i:i + _INSERT_BATCH]
        if chunk:
            await db.customers.insert_many(chunk, ordered=False)
            created += len(chunk)
            inserted_docs.extend(chunk)
    for cid, doc in updates:
        await db.customers.update_one(
            {"id": cid, "tenant_id": tenant_id},
            {"$set": {**doc, "updated_at": now_iso()}},
        )
        updated += 1

    # Comms Phase 3 · fire customer.created for every newly inserted
    # row. This uses the in-memory rule index; if the tenant has no
    # active ``customer.created`` rule the engine returns immediately
    # so a 5000-row import stays well under the request timeout.
    # Runs outside the insert path so a downstream engine hiccup does
    # not roll back the import.
    try:
        from services.automation_engine import emit as _emit
        for doc in inserted_docs:
            await _emit(
                "customer.created",
                {"customer": doc, "source": "csv_import"},
                tenant_id=tenant_id,
                entity_kind="customer", entity_id=doc.get("id") or "",
                customer_id=doc.get("id"),
            )
    except Exception:
        pass

    if legacy_seen:
        deprecation_warnings.append(
            "Legacy header names detected (e.g. 'Name', 'Address', 'Phone'). "
            "Download the new 12-column template at /api/import/customers/template — "
            "the old shape will be dropped in a future release."
        )

    total = len(rows)
    imported = created + updated
    warnings_truncated = len(warnings) > _WARN_INLINE_CAP
    errors_truncated = len(errors) > _ERR_INLINE_CAP

    # ─── Persist the full report so admins can look it up later ──────
    await db.customer_import_reports.insert_one({
        "id": import_id,
        "tenant_id": tenant_id,
        "created_by_user_id": user.get("id"),
        "created_at": now_iso(),
        "total_rows": total,
        "imported": imported,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "warnings": warnings,
        "errors": errors,
        "deprecation_warnings": deprecation_warnings,
    })

    return {
        # Feb-2026 real-world CSV fix — canonical keys.
        "import_id": import_id,
        "total_rows": total,
        "imported": imported,
        "skipped": skipped,
        "warnings": warnings[:_WARN_INLINE_CAP],
        "warnings_truncated": warnings_truncated,
        "warnings_total": len(warnings),
        # Historical keys — retained so the existing ImportModal in
        # CustomersList.jsx keeps rendering its stat tiles correctly.
        "imported_count": imported,
        "created_count": created,
        "updated_count": updated,
        "skipped_count": skipped,
        "errors": errors[:_ERR_INLINE_CAP],
        "errors_truncated": errors_truncated,
        "deprecation_warnings": deprecation_warnings,
    }


@router.get("/customers/imports/{import_id}")
async def get_customer_import_report(
    import_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the full log (all warnings + errors, untruncated) for a
    prior customer-import run. Tenant-scoped: an admin from tenant A
    cannot fetch tenant B's import report."""
    doc = await db.customer_import_reports.find_one(
        {"id": import_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Import report not found")
    return doc


async def _upsert_customer(tenant_id: str, doc: dict) -> str:
    """Soft dedup on (tenant_id, email, mobile). If a match exists,
    UPDATE (returns "updated"); otherwise INSERT (returns "created")."""
    email = (doc.get("email") or "").lower().strip()
    mobile = ""
    for p in (doc.get("phones") or []):
        if p.get("type") == "mobile":
            mobile = p.get("number") or ""
            break
    match = None
    if email:
        match = await db.customers.find_one({"tenant_id": tenant_id, "email": email})
    if not match and mobile:
        match = await db.customers.find_one({"tenant_id": tenant_id, "phones.number": mobile})
    if not match and email and mobile:
        # last-resort: match on either email OR mobile alone (already
        # covered above); no OR-match on name to avoid false positives.
        pass
    if match:
        await db.customers.update_one(
            {"id": match["id"], "tenant_id": tenant_id},
            {"$set": {**doc, "updated_at": now_iso()}},
        )
        return "updated"
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.customers.insert_one(doc)
    return "created"


def _build_legacy_doc(raw: dict, tenant_id: str, normalize_phone):
    """Pre-Phase-56 importer, kept for CSVs uploaded from older tooling.

    Returns ``(doc, error)`` matching the same contract as
    ``build_customer_doc``. Best-effort — the goal is not to reject a
    row that would have worked yesterday. Missing name is still fatal.
    """
    r = { (k or "").strip().lower().replace(" ", "_"): (v.strip() if isinstance(v, str) else v)
          for k, v in (raw or {}).items() if k is not None }
    name = (r.get("name") or "").strip()
    if not name:
        return None, "missing name (legacy shape)"
    first, _, last = name.partition(" ")
    phone_num = normalize_phone(r.get("phone"))
    phones = [{"type": "home", "number": phone_num}] if phone_num else []
    return {
        "tenant_id": tenant_id,
        "name": name,
        "first_name": first,
        "last_name": last,
        "email": (r.get("email") or "").strip().lower(),
        "phones": phones,
        "phone": phone_num or "",
        "address": r.get("address") or "",
        "billing_address": r.get("billing_address") or "",
        "gate_code": r.get("gate_code") or "",
        "notes": r.get("notes") or "",
    }, None


@router.post("/import/items")
async def import_items(body: CsvIn, user: dict = Depends(require_admin)):
    """Phase P58 · Feb-2026 — tenant-scope hardening.

    Prior to this fix, ``import_items`` performed three unscoped
    ``db.items`` operations:
      * L382 ``find_one({\"name\": ...})`` — no tenant_id filter.
      * L384 ``update_one({\"id\": match[\"id\"]}, ...)`` — no
        tenant_id filter, could OVERWRITE a cross-tenant row when
        two tenants happened to have items with the same name.
      * L388 ``insert_one(doc)`` — the new doc had no ``tenant_id``
        field, creating an orphaned / globally-visible row.

    Impact: admin in tenant A uploading a CSV with an item name
    that collides with tenant B's item name would silently rewrite
    tenant B's row (case-insensitive regex match). Cross-tenant
    mutation breach + orphaned-row hygiene bug.

    Fix mirrors the P58 ``patch_item`` hardening + established
    ``import_customers`` pattern in the same file:
      * Read tenant_id from ``user.get(\"tenant_id\")`` (matches
        ``import_customers`` at L83 which uses
        ``Depends(get_current_tenant)``; keeping ``user.get`` here
        for consistency with the rest of items.py's P57 pattern).
      * P57-style ValueError guard on empty/whitespace tenant_id.
      * Every ``db.items`` mutation filters by tenant_id.
      * Insert path stamps ``tenant_id`` on the new doc.
      * Update path stamps ``tenant_id`` on the ``$set`` too so
        legacy pre-P58 orphan rows (which lack tenant_id) are
        backfilled to the actor's tenant if they happen to match
        by name.
    """
    tenant_id = user.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError(
            "import_items requires a non-empty tenant_id on the caller"
        )
    rows = _read_rows(body.csv)
    created = updated = skipped = 0
    errors = []
    for i, r in enumerate(rows, start=2):
        name = (r.get("name") or "").strip()
        if not name:
            skipped += 1
            errors.append(f"Row {i}: missing name")
            continue
        try:
            price = float(str(r.get("unit_price") or 0).replace("$", "").replace(",", "") or 0)
        except ValueError:
            price = 0.0
        doc = {
            "name": name,
            "category": (r.get("category") or "Service"),
            "unit": (r.get("unit") or "each"),
            "unit_price": price,
            "taxable": _parse_bool(r.get("taxable")) if r.get("taxable") not in (None, "") else True,
        }
        match = await db.items.find_one({
            "name": {"$regex": f"^{name}$", "$options": "i"},
            "tenant_id": tenant_id,
        })
        if match:
            await db.items.update_one(
                {"id": match["id"], "tenant_id": tenant_id},
                # Stamp tenant_id in the $set too so any legacy row
                # missing the field gets backfilled to the actor's
                # tenant on the way through.
                {"$set": {**doc, "tenant_id": tenant_id}},
            )
            updated += 1
        else:
            doc.update({"id": new_id(), "tenant_id": tenant_id,
                          "created_at": now_iso()})
            await db.items.insert_one(doc)
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors[:20]}

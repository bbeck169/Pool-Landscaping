import csv
import io
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import db
from utils import now_iso, new_id, require_admin

router = APIRouter()

CUSTOMER_COLS = ["name", "email", "phone", "address", "billing_address", "gate_code", "notes"]
ITEM_COLS = ["name", "category", "unit", "unit_price", "taxable"]


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
async def export_customers(user: dict = Depends(require_admin)):
    rows = await db.customers.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    return {"filename": "customers.csv", "content": _to_csv(rows, CUSTOMER_COLS), "count": len(rows)}


@router.get("/export/items")
async def export_items(user: dict = Depends(require_admin)):
    rows = await db.items.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    return {"filename": "pricebook.csv", "content": _to_csv(rows, ITEM_COLS), "count": len(rows)}


# ----------------------- Import -----------------------
@router.post("/import/customers")
async def import_customers(body: CsvIn, user: dict = Depends(require_admin)):
    rows = _read_rows(body.csv)
    created = updated = skipped = 0
    errors = []
    for i, r in enumerate(rows, start=2):  # row 1 = header
        name = (r.get("name") or "").strip()
        if not name:
            skipped += 1
            errors.append(f"Row {i}: missing name")
            continue
        doc = {c: (r.get(c) or "") for c in CUSTOMER_COLS}
        email = (doc.get("email") or "").strip().lower()
        match = None
        if email:
            match = await db.customers.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})
        if not match:
            match = await db.customers.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
        if match:
            await db.customers.update_one({"id": match["id"]}, {"$set": doc})
            updated += 1
        else:
            doc.update({"id": new_id(), "created_at": now_iso()})
            await db.customers.insert_one(doc)
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors[:20]}


@router.post("/import/items")
async def import_items(body: CsvIn, user: dict = Depends(require_admin)):
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
        match = await db.items.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
        if match:
            await db.items.update_one({"id": match["id"]}, {"$set": doc})
            updated += 1
        else:
            doc.update({"id": new_id(), "created_at": now_iso()})
            await db.items.insert_one(doc)
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors[:20]}

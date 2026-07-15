"""Phase 24 · Check Writer — admin-only physical-check generator.

- Bank-account CRUD (encrypted account numbers, per-account check-number
  sequence, live_mode safety flag).
- Payee CRUD (vendors, employees, customers, other).
- Check CRUD with atomic per-bank-account check-number assignment.
- Print → real PDF (reg-CC-compliant layout on top 3.5" of 8.5×11 with two
  detail stubs beneath).
- Void, mark-cleared, mark-uncleared for bank reconciliation.
- Register listing + analytics.

MICR fidelity: reportlab does not ship MICR E-13B by default. When no MICR
font is embedded, PDFs are printed with a large `TEST_ONLY_NOT_MICR_ENCODED`
watermark. `live_mode` on each bank account is False by default; while it's
False, `SAMPLE — NOT NEGOTIABLE` overrides the entire check face. No silent
faking.
"""
import base64
import hashlib
import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import JWT_SECRET, db, logger
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── Encryption ──────────────────────────────────────────────────────
def _fernet() -> Fernet:
    """Deterministic Fernet key derived from JWT_SECRET. Documented as
    development-grade in the phase 24 HANDOFF — a dedicated
    CHECKS_ENCRYPTION_KEY should be provisioned before production."""
    digest = hashlib.sha256(JWT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""


# ─── Amount to words ─────────────────────────────────────────────────
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def _under_thousand(n: int) -> str:
    if n == 0:
        return ""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    return (_ONES[n // 100] + " hundred"
            + (f" {_under_thousand(n % 100)}" if n % 100 else ""))


def _int_to_words(n: int) -> str:
    """Handles up to 999,999,999."""
    if n == 0:
        return "zero"
    parts: List[str] = []
    if n >= 1_000_000:
        parts.append(_under_thousand(n // 1_000_000) + " million")
        n %= 1_000_000
    if n >= 1_000:
        parts.append(_under_thousand(n // 1_000) + " thousand")
        n %= 1_000
    if n > 0:
        parts.append(_under_thousand(n))
    return " ".join(p for p in parts if p)


def amount_to_words(amount: float) -> str:
    """"1234.56" → "One thousand two hundred thirty-four and 56/100 dollars"."""
    if amount is None:
        return ""
    neg = amount < 0
    amount = abs(round(float(amount), 2))
    whole = int(amount)
    cents = int(round((amount - whole) * 100))
    if cents == 100:
        whole += 1
        cents = 0
    words = _int_to_words(whole).capitalize()
    return f"{'Negative ' if neg else ''}{words} and {cents:02d}/100 dollars"


# ─── Pydantic bodies ─────────────────────────────────────────────────
class BankAccountIn(BaseModel):
    nickname: str
    bank_name: str
    routing_number: str = Field(..., min_length=9, max_length=9)
    account_number: str = Field(..., min_length=4)
    next_check_number: int = 1001
    starting_balance: float = 0.0
    signature_image_url: Optional[str] = None
    live_mode: bool = False


class BankAccountPatch(BaseModel):
    nickname: Optional[str] = None
    bank_name: Optional[str] = None
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    next_check_number: Optional[int] = None
    starting_balance: Optional[float] = None
    signature_image_url: Optional[str] = None
    live_mode: Optional[bool] = None


class PayeeIn(BaseModel):
    name: str
    kind: str = Field("vendor", pattern="^(vendor|employee|customer|other)$")
    address: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    tax_id: Optional[str] = ""
    notes: Optional[str] = ""


class PayeePatch(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None
    notes: Optional[str] = None


class CheckIn(BaseModel):
    bank_account_id: str
    payee_id: str
    amount: float = Field(..., gt=0)
    memo: Optional[str] = ""
    date: str  # ISO date "YYYY-MM-DD"
    category: Optional[str] = ""
    ref_type: Optional[str] = Field(None,
                                     pattern="^(invoice|payroll|refund|manual)$")
    ref_id: Optional[str] = None


class CheckPatch(BaseModel):
    payee_id: Optional[str] = None
    amount: Optional[float] = None
    memo: Optional[str] = None
    date: Optional[str] = None
    category: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None


class VoidIn(BaseModel):
    reason: str


class ClearIn(BaseModel):
    cleared_at: Optional[str] = None
    cleared_amount: Optional[float] = None


# ─── Helpers ─────────────────────────────────────────────────────────
def _bank_out(ba: Dict[str, Any]) -> Dict[str, Any]:
    """Response projection — never expose full account number."""
    return {
        "id": ba["id"],
        "nickname": ba.get("nickname"),
        "bank_name": ba.get("bank_name"),
        "routing_number": ba.get("routing_number"),
        "account_number_last4": ba.get("account_number_last4"),
        "next_check_number": ba.get("next_check_number", 1001),
        "starting_balance": ba.get("starting_balance", 0.0),
        "current_balance": ba.get("current_balance", ba.get("starting_balance", 0.0)),
        "signature_image_url": ba.get("signature_image_url"),
        "live_mode": bool(ba.get("live_mode", False)),
        "created_at": ba.get("created_at"),
        "updated_at": ba.get("updated_at"),
    }


async def _recompute_balance(tenant_id: str, bank_account_id: str) -> float:
    """current_balance = starting_balance − sum(amount) of cleared checks."""
    ba = await db.bank_accounts.find_one(
        {"id": bank_account_id, "tenant_id": tenant_id}, {"_id": 0})
    if not ba:
        return 0.0
    total_cleared = 0.0
    cur = db.checks.find({"tenant_id": tenant_id,
                            "bank_account_id": bank_account_id,
                            "status": "cleared"}, {"_id": 0, "amount": 1,
                                                      "cleared_amount": 1})
    async for c in cur:
        total_cleared += float(c.get("cleared_amount") or c.get("amount") or 0)
    new_balance = float(ba.get("starting_balance") or 0) - total_cleared
    await db.bank_accounts.update_one(
        {"id": bank_account_id, "tenant_id": tenant_id},
        {"$set": {"current_balance": round(new_balance, 2),
                    "updated_at": now_iso()}},
    )
    return new_balance


# ═══════════ BANK ACCOUNTS ═══════════════════════════════════════════

@router.get("/checks/bank-accounts")
async def list_bank_accounts(user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    rows = await db.bank_accounts.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": [_bank_out(r) for r in rows], "total": len(rows)}


@router.post("/checks/bank-accounts")
async def create_bank_account(body: BankAccountIn,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    if not re.fullmatch(r"\d{9}", body.routing_number):
        raise HTTPException(422, "Routing number must be exactly 9 digits")
    if not re.fullmatch(r"\d{4,17}", body.account_number):
        raise HTTPException(422, "Account number must be 4–17 digits")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "nickname": body.nickname,
        "bank_name": body.bank_name,
        "routing_number": body.routing_number,
        "account_number_last4": body.account_number[-4:],
        "account_number_encrypted": _encrypt(body.account_number),
        "next_check_number": int(body.next_check_number),
        "starting_balance": float(body.starting_balance),
        "current_balance": float(body.starting_balance),
        "signature_image_url": body.signature_image_url,
        "live_mode": bool(body.live_mode),
        "created_by": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.bank_accounts.insert_one(dict(doc))
    return _bank_out(doc)


@router.patch("/checks/bank-accounts/{bid}")
async def update_bank_account(bid: str, body: BankAccountPatch,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    existing = await db.bank_accounts.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Bank account not found")
    upd: Dict[str, Any] = {}
    d = body.model_dump(exclude_unset=True)
    for k in ("nickname", "bank_name", "signature_image_url", "live_mode"):
        if k in d and d[k] is not None:
            upd[k] = d[k]
    if d.get("routing_number") is not None:
        if not re.fullmatch(r"\d{9}", d["routing_number"]):
            raise HTTPException(422, "Routing number must be exactly 9 digits")
        upd["routing_number"] = d["routing_number"]
    if d.get("account_number") is not None:
        acc = d["account_number"]
        if not re.fullmatch(r"\d{4,17}", acc):
            raise HTTPException(422, "Account number must be 4–17 digits")
        upd["account_number_last4"] = acc[-4:]
        upd["account_number_encrypted"] = _encrypt(acc)
    if d.get("next_check_number") is not None:
        upd["next_check_number"] = int(d["next_check_number"])
    if d.get("starting_balance") is not None:
        upd["starting_balance"] = float(d["starting_balance"])
    if upd:
        upd["updated_at"] = now_iso()
        await db.bank_accounts.update_one(
            {"id": bid, "tenant_id": tenant["id"]}, {"$set": upd})
        await _recompute_balance(tenant["id"], bid)
    out = await db.bank_accounts.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    return _bank_out(out)


@router.delete("/checks/bank-accounts/{bid}")
async def delete_bank_account(bid: str,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    n = await db.checks.count_documents(
        {"tenant_id": tenant["id"], "bank_account_id": bid})
    if n:
        raise HTTPException(409, f"{n} check(s) reference this bank account")
    r = await db.bank_accounts.delete_one(
        {"id": bid, "tenant_id": tenant["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Bank account not found")
    return {"deleted": True}


# ═══════════ PAYEES ══════════════════════════════════════════════════

@router.get("/checks/payees")
async def list_payees(type: Optional[str] = Query(None),
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if type:
        q["kind"] = type
    rows = await db.check_payees.find(q, {"_id": 0}).sort("name", 1).to_list(1000)
    return {"items": rows, "total": len(rows)}


@router.post("/checks/payees")
async def create_payee(body: PayeeIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = body.model_dump()
    doc.update({"id": new_id(), "tenant_id": tenant["id"],
                 "created_by": user["id"], "created_at": now_iso(),
                 "updated_at": now_iso()})
    await db.check_payees.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.patch("/checks/payees/{pid}")
async def update_payee(pid: str, body: PayeePatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    existing = await db.check_payees.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Payee not found")
    upd = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if v is not None}
    if upd:
        upd["updated_at"] = now_iso()
        await db.check_payees.update_one(
            {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.check_payees.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/checks/payees/{pid}")
async def delete_payee(pid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    n = await db.checks.count_documents(
        {"tenant_id": tenant["id"], "payee_id": pid})
    if n:
        raise HTTPException(409, f"{n} check(s) reference this payee")
    r = await db.check_payees.delete_one(
        {"id": pid, "tenant_id": tenant["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Payee not found")
    return {"deleted": True}


# ═══════════ CHECKS ══════════════════════════════════════════════════

async def _fetch_check(cid: str, tenant_id: str) -> Dict[str, Any]:
    doc = await db.checks.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Check not found")
    return doc


@router.post("/checks/checks")
async def create_check(body: CheckIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    ba = await db.bank_accounts.find_one(
        {"id": body.bank_account_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not ba:
        raise HTTPException(404, "Bank account not found")
    payee = await db.check_payees.find_one(
        {"id": body.payee_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not payee:
        raise HTTPException(404, "Payee not found")

    # Atomic check-number assignment (race-safe).
    updated = await db.bank_accounts.find_one_and_update(
        {"id": body.bank_account_id, "tenant_id": tenant["id"]},
        {"$inc": {"next_check_number": 1},
          "$set": {"updated_at": now_iso()}},
        return_document=True,  # PyMongo `AFTER`
    )
    if not updated:
        raise HTTPException(404, "Bank account vanished mid-transaction")
    # Post-increment; assigned number is the value BEFORE the $inc.
    assigned = int(updated["next_check_number"]) - 1

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "bank_account_id": body.bank_account_id,
        "check_number": assigned,
        "payee_id": body.payee_id,
        "payee_name_snapshot": payee.get("name"),
        "amount": float(body.amount),
        "amount_in_words": amount_to_words(body.amount),
        "memo": body.memo or "",
        "date": body.date,
        "category": body.category or "",
        "ref_type": body.ref_type,
        "ref_id": body.ref_id,
        "status": "draft",
        "printed_at": None,
        "voided_at": None,
        "void_reason": None,
        "cleared_at": None,
        "cleared_amount": None,
        "pdf_url": None,
        "created_by": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    try:
        await db.checks.create_index(
            [("tenant_id", 1), ("bank_account_id", 1), ("check_number", 1)],
            unique=True,
        )
    except Exception:
        pass
    await db.checks.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/checks/checks")
async def list_checks(bank_account_id: Optional[str] = None,
                          status: Optional[str] = None,
                          payee_id: Optional[str] = None,
                          from_: Optional[str] = Query(None, alias="from"),
                          to: Optional[str] = None,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if bank_account_id: q["bank_account_id"] = bank_account_id
    if status: q["status"] = status
    if payee_id: q["payee_id"] = payee_id
    if from_ or to:
        rng: Dict[str, Any] = {}
        if from_: rng["$gte"] = from_
        if to: rng["$lte"] = to
        q["date"] = rng
    rows = await db.checks.find(q, {"_id": 0}).sort(
        [("check_number", -1)]).to_list(1000)
    return {"items": rows, "total": len(rows)}


@router.get("/checks/checks/{cid}")
async def get_check(cid: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    return await _fetch_check(cid, tenant["id"])


@router.patch("/checks/checks/{cid}")
async def update_check(cid: str, body: CheckPatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    c = await _fetch_check(cid, tenant["id"])
    d = body.model_dump(exclude_unset=True)
    if c["status"] != "draft":
        # Only memo/notes are editable post-print.
        allowed = {"memo", "category"}
        illegal = [k for k in d if k not in allowed and d[k] is not None]
        if illegal:
            raise HTTPException(409,
                f"Check is {c['status']}; only memo/category can be edited "
                f"(you tried: {illegal})")
    upd: Dict[str, Any] = {}
    if d.get("payee_id") is not None:
        payee = await db.check_payees.find_one(
            {"id": d["payee_id"], "tenant_id": tenant["id"]}, {"_id": 0})
        if not payee:
            raise HTTPException(404, "New payee not found")
        upd["payee_id"] = d["payee_id"]
        upd["payee_name_snapshot"] = payee.get("name")
    if d.get("amount") is not None:
        upd["amount"] = float(d["amount"])
        upd["amount_in_words"] = amount_to_words(float(d["amount"]))
    for k in ("memo", "date", "category", "ref_type", "ref_id"):
        if k in d and d[k] is not None:
            upd[k] = d[k]
    if upd:
        upd["updated_at"] = now_iso()
        await db.checks.update_one(
            {"id": cid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await _fetch_check(cid, tenant["id"])


@router.post("/checks/checks/{cid}/print")
async def print_check(cid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    c = await _fetch_check(cid, tenant["id"])
    if c["status"] == "voided":
        raise HTTPException(409, "Cannot print a voided check")
    now = now_iso()
    file_url = f"/api/checks/checks/{cid}/pdf"
    upd = {"pdf_url": file_url, "updated_at": now}
    if c["status"] == "draft":
        upd["status"] = "printed"
        upd["printed_at"] = now
    await db.checks.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": upd})
    return {"pdf_url": file_url, "status": upd.get("status", c["status"]),
             "printed_at": upd.get("printed_at", c.get("printed_at"))}


@router.post("/checks/checks/{cid}/void")
async def void_check(cid: str, body: VoidIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    c = await _fetch_check(cid, tenant["id"])
    if c["status"] == "voided":
        return c
    await db.checks.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "voided", "voided_at": now_iso(),
                    "void_reason": body.reason, "updated_at": now_iso()}},
    )
    await _recompute_balance(tenant["id"], c["bank_account_id"])
    return await _fetch_check(cid, tenant["id"])


@router.post("/checks/checks/{cid}/mark-cleared")
async def mark_cleared(cid: str, body: ClearIn,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    c = await _fetch_check(cid, tenant["id"])
    if c["status"] == "voided":
        raise HTTPException(409, "Cannot clear a voided check")
    when = body.cleared_at or now_iso()
    amt = (float(body.cleared_amount) if body.cleared_amount is not None
             else float(c["amount"]))
    await db.checks.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "cleared", "cleared_at": when,
                    "cleared_amount": amt, "updated_at": now_iso()}},
    )
    await _recompute_balance(tenant["id"], c["bank_account_id"])
    return await _fetch_check(cid, tenant["id"])


@router.post("/checks/checks/{cid}/mark-uncleared")
async def mark_uncleared(cid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    c = await _fetch_check(cid, tenant["id"])
    prior = "printed" if c.get("printed_at") else "draft"
    await db.checks.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": prior, "cleared_at": None,
                    "cleared_amount": None, "updated_at": now_iso()}},
    )
    await _recompute_balance(tenant["id"], c["bank_account_id"])
    return await _fetch_check(cid, tenant["id"])


# ═══════════ PDF ══════════════════════════════════════════════════════

MICR_AVAILABLE = False  # We do not ship an E-13B TTF. Print warns loudly.


def _render_check_pdf(c: Dict[str, Any], ba: Dict[str, Any],
                        payee: Dict[str, Any],
                        tenant: Dict[str, Any]) -> bytes:
    """Standard business check on top 3.5" of 8.5×11 with two detail stubs
    underneath. `live_mode == False` and MICR-not-available both attach
    highly visible warnings — no silent faking."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlc
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c_pdf = canvas.Canvas(buf, pagesize=letter, pageCompression=0)
    W, H = letter  # 612 × 792 pts (8.5 × 11 in)

    live = bool(ba.get("live_mode"))
    account_number = _decrypt(ba.get("account_number_encrypted") or "")

    # ─── CHECK FACE (top 3.5") ───────────────────────────────────────
    check_h = 3.5 * inch
    check_top = H - 0.25 * inch
    check_bot = check_top - check_h
    # Outer border
    c_pdf.setStrokeColor(rlc.HexColor("#94A3B8"))
    c_pdf.setLineWidth(1)
    c_pdf.rect(0.25 * inch, check_bot, W - 0.5 * inch, check_h)

    # Bank name + address (top left)
    c_pdf.setFont("Helvetica-Bold", 12)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    c_pdf.drawString(0.4 * inch, check_top - 0.35 * inch,
                       (ba.get("bank_name") or "Bank").upper())
    c_pdf.setFont("Helvetica", 8)
    c_pdf.setFillColor(rlc.HexColor("#475569"))
    c_pdf.drawString(0.4 * inch, check_top - 0.5 * inch,
                       f"ABA {ba.get('routing_number','')}")
    c_pdf.drawString(0.4 * inch, check_top - 0.62 * inch,
                       f"Acct ****{ba.get('account_number_last4','')}")

    # Tenant identity (top center)
    c_pdf.setFont("Helvetica-Bold", 11)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    c_pdf.drawCentredString(W / 2, check_top - 0.35 * inch,
                                tenant.get("name") or "Business")
    c_pdf.setFont("Helvetica", 7)
    c_pdf.setFillColor(rlc.HexColor("#64748B"))
    c_pdf.drawCentredString(W / 2, check_top - 0.5 * inch,
                                (tenant.get("brand") or {}).get("address") or "")

    # Check number (top right) — large + bold
    c_pdf.setFont("Helvetica-Bold", 18)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    c_pdf.drawRightString(W - 0.4 * inch, check_top - 0.35 * inch,
                              str(c.get("check_number") or ""))
    # DATE box
    c_pdf.setFont("Helvetica", 8)
    c_pdf.setFillColor(rlc.HexColor("#475569"))
    c_pdf.drawRightString(W - 0.4 * inch, check_top - 0.75 * inch, "DATE")
    c_pdf.setFont("Helvetica", 10)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    c_pdf.drawRightString(W - 0.4 * inch, check_top - 0.92 * inch,
                              c.get("date", ""))
    c_pdf.setStrokeColor(rlc.HexColor("#0F172A"))
    c_pdf.line(W - 1.8 * inch, check_top - 0.95 * inch,
                 W - 0.4 * inch, check_top - 0.95 * inch)

    # PAY TO THE ORDER OF line (large slot)
    py = check_top - 1.35 * inch
    c_pdf.setFont("Helvetica-Bold", 8)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    c_pdf.drawString(0.4 * inch, py, "PAY TO THE")
    c_pdf.drawString(0.4 * inch, py - 0.12 * inch, "ORDER OF")
    c_pdf.setFont("Helvetica", 14)
    c_pdf.drawString(1.35 * inch, py - 0.05 * inch,
                       payee.get("name") or c.get("payee_name_snapshot") or "")
    # Amount box (right)
    box_x = W - 2.2 * inch
    box_w = 1.8 * inch
    box_h = 0.4 * inch
    box_y = py - 0.15 * inch
    c_pdf.setStrokeColor(rlc.HexColor("#0F172A"))
    c_pdf.setLineWidth(1.2)
    c_pdf.rect(box_x, box_y, box_w, box_h)
    c_pdf.setFont("Helvetica-Bold", 16)
    c_pdf.drawRightString(box_x + box_w - 0.1 * inch,
                              box_y + 0.12 * inch,
                              f"${float(c.get('amount') or 0):,.2f}")
    c_pdf.setStrokeColor(rlc.HexColor("#0F172A"))
    c_pdf.line(1.35 * inch, py - 0.15 * inch,
                 box_x - 0.1 * inch, py - 0.15 * inch)

    # Amount in words (long line)
    wy = py - 0.55 * inch
    c_pdf.setFont("Helvetica", 11)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    words_text = (c.get("amount_in_words") or amount_to_words(c.get("amount") or 0))
    c_pdf.drawString(0.4 * inch, wy, words_text)
    c_pdf.setFont("Helvetica-Bold", 8)
    c_pdf.drawRightString(W - 0.4 * inch, wy, "DOLLARS")
    c_pdf.setStrokeColor(rlc.HexColor("#0F172A"))
    c_pdf.line(0.4 * inch, wy - 0.05 * inch,
                 W - 1.0 * inch, wy - 0.05 * inch)

    # MEMO + SIGNATURE row
    my = check_bot + 0.55 * inch
    c_pdf.setFont("Helvetica-Bold", 8)
    c_pdf.drawString(0.4 * inch, my + 0.15 * inch, "MEMO")
    c_pdf.setFont("Helvetica", 10)
    c_pdf.drawString(0.4 * inch, my - 0.02 * inch, c.get("memo") or "")
    c_pdf.setStrokeColor(rlc.HexColor("#0F172A"))
    c_pdf.line(0.4 * inch, my - 0.08 * inch,
                 W / 2 - 0.4 * inch, my - 0.08 * inch)
    # Signature
    sig_x = W / 2 + 0.2 * inch
    sig_y = my - 0.08 * inch
    if ba.get("signature_image_url"):
        try:
            c_pdf.drawImage(ba["signature_image_url"], sig_x,
                              sig_y, width=2.2 * inch, height=0.4 * inch,
                              preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    c_pdf.line(sig_x, sig_y, W - 0.4 * inch, sig_y)
    c_pdf.setFont("Helvetica", 7)
    c_pdf.setFillColor(rlc.HexColor("#64748B"))
    c_pdf.drawCentredString((sig_x + W - 0.4 * inch) / 2, sig_y - 0.1 * inch,
                                "AUTHORIZED SIGNATURE")

    # MICR line (bottom of check face, roughly 5/8" from bottom of check)
    micr_y = check_bot + 0.25 * inch
    c_pdf.setFont("Courier-Bold", 14)
    c_pdf.setFillColor(rlc.HexColor("#0F172A"))
    micr = (f"C{c.get('check_number','')}C  "
             f"A{ba.get('routing_number','')}A  {account_number}C")
    c_pdf.drawString(0.4 * inch, micr_y, micr)

    # Warnings (non-silent)
    warn: List[str] = []
    if not MICR_AVAILABLE:
        warn.append("TEST_ONLY_NOT_MICR_ENCODED")
    if not live:
        warn.append("SAMPLE — NOT NEGOTIABLE")
    if warn:
        c_pdf.saveState()
        c_pdf.setFillColorRGB(1.0, 0.05, 0.05, alpha=0.18)
        c_pdf.setFont("Helvetica-Bold", 48)
        c_pdf.translate(W / 2, (check_top + check_bot) / 2)
        c_pdf.rotate(20)
        c_pdf.drawCentredString(0, 0, " · ".join(warn))
        c_pdf.restoreState()

    # ─── STUB 1 (middle third) ───────────────────────────────────────
    stub_h = 3.5 * inch
    stub_top = check_bot - 0.15 * inch
    c_pdf.setDash(2, 2)
    c_pdf.setStrokeColor(rlc.HexColor("#94A3B8"))
    c_pdf.line(0.25 * inch, stub_top, W - 0.25 * inch, stub_top)
    c_pdf.setDash()

    def _stub(y_top: float, label: str):
        c_pdf.setFont("Helvetica-Bold", 9)
        c_pdf.setFillColor(rlc.HexColor("#64748B"))
        c_pdf.drawString(0.4 * inch, y_top - 0.25 * inch, label)
        c_pdf.setFont("Helvetica-Bold", 11)
        c_pdf.setFillColor(rlc.HexColor("#0F172A"))
        c_pdf.drawString(0.4 * inch, y_top - 0.5 * inch,
                           f"Check #{c.get('check_number','')} · {c.get('date','')}")
        rows = [
            ("Payee", payee.get("name") or ""),
            ("Amount", f"${float(c.get('amount') or 0):,.2f}"),
            ("Memo", c.get("memo") or ""),
            ("Category", c.get("category") or ""),
            ("Bank", f"{ba.get('bank_name','')} · ****{ba.get('account_number_last4','')}"),
            ("Status", c.get("status") or ""),
        ]
        c_pdf.setFont("Helvetica", 10)
        for i, (k, v) in enumerate(rows):
            yy = y_top - 0.8 * inch - i * 0.22 * inch
            c_pdf.setFillColor(rlc.HexColor("#64748B"))
            c_pdf.drawString(0.4 * inch, yy, k + ":")
            c_pdf.setFillColor(rlc.HexColor("#0F172A"))
            c_pdf.drawString(1.4 * inch, yy, str(v)[:70])

    _stub(stub_top, "PAYEE STUB")

    stub2_top = stub_top - 3.5 * inch
    c_pdf.setDash(2, 2)
    c_pdf.line(0.25 * inch, stub2_top, W - 0.25 * inch, stub2_top)
    c_pdf.setDash()
    _stub(stub2_top, "RECORD STUB")

    c_pdf.showPage()
    c_pdf.save()
    return buf.getvalue()


@router.get("/checks/checks/{cid}/pdf")
async def check_pdf(cid: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    c = await _fetch_check(cid, tenant["id"])
    ba = await db.bank_accounts.find_one(
        {"id": c["bank_account_id"], "tenant_id": tenant["id"]},
        {"_id": 0}) or {}
    payee = await db.check_payees.find_one(
        {"id": c["payee_id"], "tenant_id": tenant["id"]}, {"_id": 0}) or {}
    t = await db.tenants.find_one(
        {"id": tenant["id"]}, {"_id": 0}) or {}
    pdf = _render_check_pdf(c, ba, payee, t)
    warnings: List[str] = []
    if not MICR_AVAILABLE:
        warnings.append("TEST_ONLY_NOT_MICR_ENCODED")
    if not bool(ba.get("live_mode")):
        warnings.append("SAMPLE_MODE")
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="check-{c.get("check_number","")}.pdf"',
            "X-Check-Warnings": ",".join(warnings) if warnings else "none",
            "X-Check-Number": str(c.get("check_number", "")),
            "X-Check-Status": c.get("status", ""),
        },
    )


# ═══════════ ANALYTICS ═══════════════════════════════════════════════

@router.get("/checks/analytics")
async def analytics(bank_account_id: Optional[str] = None,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if bank_account_id: q["bank_account_id"] = bank_account_id
    rows = await db.checks.find(q, {"_id": 0}).to_list(5000)
    total_written = sum(float(r["amount"]) for r in rows
                             if r["status"] != "voided")
    total_cleared = sum(float(r.get("cleared_amount") or r["amount"])
                             for r in rows if r["status"] == "cleared")
    total_pending = sum(float(r["amount"]) for r in rows
                             if r["status"] in ("draft", "printed"))
    total_voided = sum(float(r["amount"]) for r in rows
                             if r["status"] == "voided")

    cat_by: Dict[str, float] = {}
    for r in rows:
        if r["status"] == "voided": continue
        cat_by[r.get("category") or "Uncategorized"] = (
            cat_by.get(r.get("category") or "Uncategorized", 0)
            + float(r["amount"]))
    category_breakdown = [
        {"category": k, "amount": round(v, 2)}
        for k, v in sorted(cat_by.items(), key=lambda x: -x[1])
    ]

    monthly: Dict[str, float] = {}
    for r in rows:
        if r["status"] == "voided": continue
        key = (r.get("date") or "")[:7]
        if not key: continue
        monthly[key] = monthly.get(key, 0) + float(r["amount"])
    monthly_series = [
        {"month": k, "amount": round(v, 2)}
        for k, v in sorted(monthly.items())
    ]

    return {
        "total_written": round(total_written, 2),
        "total_cleared": round(total_cleared, 2),
        "total_pending": round(total_pending, 2),
        "total_voided": round(total_voided, 2),
        "check_counts": {
            "draft": sum(1 for r in rows if r["status"] == "draft"),
            "printed": sum(1 for r in rows if r["status"] == "printed"),
            "cleared": sum(1 for r in rows if r["status"] == "cleared"),
            "voided": sum(1 for r in rows if r["status"] == "voided"),
        },
        "category_breakdown": category_breakdown,
        "monthly_series": monthly_series,
    }

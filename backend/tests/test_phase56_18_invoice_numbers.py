"""Phase 56.18 — Invoice number generation + backfill + immutability."""
import asyncio, re, sys, uuid, os
from pathlib import Path
import pytest, requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient
from services.invoice_numbering import (
    generate_invoice_number, assign_invoice_number_if_missing,
    assign_by_tenant_id, NUMBER_REGEX, _year_in_tz,
)

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
BE = dotenv_values("/app/backend/.env")

_LOOP = asyncio.new_event_loop()


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    c = AsyncIOMotorClient(BE["MONGO_URL"])
    return c[BE["DB_NAME"]]


async def _mk_tenant(tz="America/Phoenix"):
    tid = f"56.18-{uuid.uuid4().hex[:8]}"
    await _db().tenants.insert_one({"id": tid, "slug": tid, "timezone": tz})
    return {"id": tid, "timezone": tz}


async def _cleanup(tid):
    d = _db()
    await d.tenants.delete_many({"id": tid})
    await d.invoice_number_sequences.delete_many({"tenant_id": tid})
    await d.quotes.delete_many({"tenant_id": tid})
    await d.master_invoices.delete_many({"tenant_id": tid})


def test_format_and_sequence():
    async def go():
        t = await _mk_tenant()
        try:
            year = _year_in_tz("America/Phoenix")
            n1 = await generate_invoice_number(t["id"], t["timezone"])
            n2 = await generate_invoice_number(t["id"], t["timezone"])
            n3 = await generate_invoice_number(t["id"], t["timezone"])
            assert n1 == f"INV-{year}-000001"
            assert n2 == f"INV-{year}-000002"
            assert n3 == f"INV-{year}-000003"
            assert NUMBER_REGEX.match(n1)
            # Master invoice uses separate sequence.
            m1 = await generate_invoice_number(t["id"], t["timezone"], master=True)
            assert m1 == f"MINV-{year}-000001"
        finally:
            await _cleanup(t["id"])
    _run(go())


def test_concurrency_no_dup():
    async def go():
        t = await _mk_tenant()
        try:
            # 20 concurrent generations.
            nums = await asyncio.gather(*[
                generate_invoice_number(t["id"], t["timezone"]) for _ in range(20)
            ])
            assert len(set(nums)) == 20, f"duplicates found: {nums}"
        finally:
            await _cleanup(t["id"])
    _run(go())


def test_assign_if_missing_is_idempotent():
    async def go():
        t = await _mk_tenant()
        try:
            doc = {"tenant_id": t["id"], "doc_type": "invoice"}
            await assign_invoice_number_if_missing(doc, t)
            first = doc["invoice_number"]
            # Second call must NOT overwrite (immutability at helper layer).
            await assign_invoice_number_if_missing(doc, t)
            assert doc["invoice_number"] == first
        finally:
            await _cleanup(t["id"])
    _run(go())


# ─── HTTP-level: create invoice + immutability + backfill spot check ─
def _login(email):
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": "password123"}, timeout=45)
    r.raise_for_status(); return r.json()["access_token"]


def test_new_invoice_gets_number_and_is_immutable():
    tok = _login("admin@aquaterra.com")
    hdr = {"Authorization": f"Bearer {tok}"}
    cust = requests.get(f"{BASE}/api/customers", headers=hdr, timeout=45).json()
    cid = (cust if isinstance(cust, list) else cust.get("customers", []))[0]["id"]

    r = requests.post(f"{BASE}/api/quotes",
        json={"customer_id": cid, "title": "56.18 test", "doc_type": "invoice",
              "line_items": [{"description": "x", "quantity": 1, "unit_price": 100}]},
        headers=hdr, timeout=45)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert NUMBER_REGEX.match(doc.get("invoice_number", "")), \
        f"bad number: {doc.get('invoice_number')}"
    original = doc["invoice_number"]

    # PATCH attempting to change invoice_number: Pydantic drops the
    # unknown field silently AND the router's explicit guard also
    # strips it — so the request 200s but the number is unchanged.
    # (Both layers of protection verified below.)
    r = requests.put(f"{BASE}/api/quotes/{doc['id']}",
        json={"invoice_number": "INV-2000-999999"}, headers=hdr, timeout=45)
    assert r.status_code == 200, r.text
    assert r.json()["invoice_number"] == original, \
        "invoice_number was mutated by PATCH — IMMUTABILITY VIOLATION"

    # Regular update leaves the number alone.
    r = requests.put(f"{BASE}/api/quotes/{doc['id']}",
        json={"title": "Renamed 56.18"}, headers=hdr, timeout=45)
    assert r.status_code == 200
    assert r.json()["invoice_number"] == original

    # Cleanup
    requests.delete(f"{BASE}/api/quotes/{doc['id']}", headers=hdr, timeout=45)


def test_backfill_spot_check():
    """After running the migration in-session, every existing invoice
    in aquaterra should have an `invoice_number`."""
    tok = _login("admin@aquaterra.com")
    hdr = {"Authorization": f"Bearer {tok}"}
    # Fetch a page of invoices via the list endpoint.
    r = requests.get(f"{BASE}/api/quotes?doc_type=invoice", headers=hdr, timeout=45)
    assert r.status_code == 200
    invoices = r.json()
    if isinstance(invoices, dict):
        invoices = invoices.get("quotes") or invoices.get("results") or []
    numbered = [i for i in invoices if i.get("invoice_number")]
    unnumbered = [i for i in invoices if not i.get("invoice_number")]
    assert len(unnumbered) == 0, \
        f"{len(unnumbered)} invoices still missing invoice_number after backfill"
    for inv in numbered[:5]:
        assert NUMBER_REGEX.match(inv["invoice_number"])

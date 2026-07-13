"""Seed helper for iteration 32 UI test — attach Stripe PM to Jennifer Carson.

Usage:
  python setup_iter32_charge_ui.py setup    # attach pm_card_visa + set fields
  python setup_iter32_charge_ui.py cleanup  # reset invoice + unset PM fields + del notifs
  python setup_iter32_charge_ui.py status   # print state
"""
import os
import sys
import json
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

import stripe as _stripe  # noqa: E402
_stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

from pymongo import MongoClient  # noqa: E402
_mc = MongoClient(os.environ["MONGO_URL"])
_db = _mc[os.environ["DB_NAME"]]

CUSTOMER_EMAIL = "customer@aquaterra.com"


def _get_customer():
    u = _db.users.find_one({"email": CUSTOMER_EMAIL})
    assert u and u.get("customer_id"), "customer user not seeded"
    cust = _db.customers.find_one({"id": u["customer_id"]})
    assert cust, "customer doc missing"
    return cust


def _get_outstanding(customer_id):
    inv = _db.quotes.find_one({
        "doc_type": "invoice", "customer_id": customer_id,
        "payment_status": "unpaid", "total": {"$gt": 0},
    })
    return inv


def setup():
    cust = _get_customer()
    cid = cust["id"]

    scid = cust.get("stripe_customer_id")
    if not scid:
        sc = _stripe.Customer.create(
            name=cust.get("name") or "Test",
            email=cust.get("email") or None,
            metadata={"customer_id": cid},
        )
        scid = sc.id

    pm = _stripe.PaymentMethod.attach("pm_card_visa", customer=scid)
    _stripe.Customer.modify(scid, invoice_settings={"default_payment_method": pm.id})

    _db.customers.update_one({"id": cid}, {"$set": {
        "stripe_customer_id": scid,
        "default_payment_method_id": pm.id,
        "pm_brand": "Visa", "pm_last4": "4242", "pm_type": "card",
    }})

    inv = _get_outstanding(cid)
    print(json.dumps({
        "ok": True,
        "customer_id": cid,
        "stripe_customer_id": scid,
        "pm_id": pm.id,
        "invoice_id": inv and inv["id"],
        "invoice_title": inv and inv.get("title"),
        "invoice_total": inv and inv.get("total"),
        "invoice_status": inv and inv.get("payment_status"),
    }, indent=2))


def cleanup():
    cust = _get_customer()
    cid = cust["id"]

    # Reset any invoice that got marked paid in this run (heuristic: recently paid + our pm_brand)
    # We only reset the canonical outstanding invoice by id if the setup captured it via status.
    # Safer: reset any invoice for this customer that is paid AND has payment_method starting with 'Visa ••4242'
    result = _db.quotes.update_many(
        {"customer_id": cid, "payment_status": "paid",
         "payment_method": {"$regex": r"^Visa"}},
        {"$set": {"payment_status": "unpaid", "status": "sent", "amount_paid": 0.0},
         "$unset": {"paid_at": "", "payment_method": "", "payment_intent_id": ""}},
    )

    _db.customers.update_one({"id": cid}, {"$unset": {
        "stripe_customer_id": "", "default_payment_method_id": "",
        "pm_brand": "", "pm_last4": "", "pm_type": "",
    }})

    ndel = _db.notifications.delete_many({
        "customer_id": cid,
        "title": {"$in": ["Payment received", "Payment method required"]},
    }).deleted_count

    print(json.dumps({
        "ok": True,
        "invoices_reset": result.modified_count,
        "notifications_deleted": ndel,
    }, indent=2))


def status():
    cust = _get_customer()
    cid = cust["id"]
    fresh = _db.customers.find_one({"id": cid}, {"_id": 0})
    inv = _get_outstanding(cid)
    print(json.dumps({
        "customer_pm_fields": {k: fresh.get(k) for k in [
            "stripe_customer_id", "default_payment_method_id",
            "pm_brand", "pm_last4", "pm_type"]},
        "outstanding_invoice": inv and {
            "id": inv["id"], "title": inv.get("title"),
            "total": inv.get("total"),
            "payment_status": inv.get("payment_status"),
            "amount_paid": inv.get("amount_paid"),
        },
    }, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        setup()
    elif cmd == "cleanup":
        cleanup()
    else:
        status()

import stripe, os, json, time, hmac, hashlib, requests, sys
stripe.api_key = os.environ["STRIPE_SECRET_KEY_TEST"]
secret = os.environ["STRIPE_WEBHOOK_SECRET_TEST"]
pi_id = sys.argv[1]
etype = sys.argv[2]  # e.g., payment_intent.succeeded / charge.refunded
# Fetch PI + Charge from Stripe
pi = stripe.PaymentIntent.retrieve(pi_id, expand=["latest_charge"])
data_obj = None
if etype == "payment_intent.succeeded":
    data_obj = json.loads(str(pi))
elif etype in ("charge.refunded",):
    # Build a synthetic charge.refunded event — use latest_charge as the base
    ch = pi.latest_charge
    if isinstance(ch, str):
        ch = stripe.Charge.retrieve(ch)
    data_obj = json.loads(str(ch))
    # Simulate refund
    amt_refund = int(sys.argv[3]) if len(sys.argv) > 3 else data_obj.get("amount")
    data_obj["amount_refunded"] = amt_refund
    data_obj["refunded"] = amt_refund >= data_obj.get("amount", 0)
    data_obj["payment_intent"] = pi_id
event = {
    "id": f"evt_test_{int(time.time()*1000)}",
    "object": "event",
    "api_version": "2020-08-27",
    "created": int(time.time()),
    "type": etype,
    "livemode": False,
    "pending_webhooks": 1,
    "request": {"id": None, "idempotency_key": None},
    "data": {"object": data_obj},
}
# Optional override key (for stable refund_key)
if "--evtid" in sys.argv:
    i = sys.argv.index("--evtid")
    event["id"] = sys.argv[i+1]
payload = json.dumps(event, separators=(",", ":")).encode()
ts = int(time.time())
signed = f"{ts}.".encode() + payload
sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
hdr = f"t={ts},v1={sig}"
url = "https://poolscape-audit.preview.emergentagent.com/api/payments/stripe/webhook"
r = requests.post(url, data=payload, headers={"Stripe-Signature": hdr, "Content-Type":"application/json"})
print("status:", r.status_code, "body:", r.text[:400])

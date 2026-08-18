import hmac, hashlib, time, json, os, urllib.request, urllib.error

secret = os.environ["WHSEC"]
base = os.environ["BASE"]
pi = os.environ["PI"]
amount = int(os.environ["AMT_ORIG"])
amount_refunded = int(os.environ["AMT_REF"])

evt = {
    "id": f"evt_test_{pi}_{amount_refunded}_{int(time.time())}",
    "object": "event",
    "type": "charge.refunded",
    "livemode": False,
    "api_version": "2024-06-20",
    "created": int(time.time()),
    "data": {
        "object": {
            "id": f"ch_test_{pi}",
            "object": "charge",
            "amount": amount,
            "amount_refunded": amount_refunded,
            "amount_captured": amount,
            "refunded": amount_refunded >= amount,
            "payment_intent": pi,
            "status": "succeeded",
        }
    },
}
payload = json.dumps(evt, separators=(",", ":")).encode()
ts = str(int(time.time()))
signed_payload = f"{ts}.".encode() + payload
sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
header = f"t={ts},v1={sig}"

req = urllib.request.Request(
    f"{base}/payments/stripe/webhook",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Stripe-Signature": header,
        "User-Agent": "Stripe/1.0 (+https://stripe.com/docs/webhooks)",
    },
    method="POST",
)
try:
    resp = urllib.request.urlopen(req, timeout=30)
    print("HTTP", resp.status)
    print(resp.read().decode())
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode()[:500])

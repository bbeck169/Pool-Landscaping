# Ops · Key Rotation Runbook — 2026-02

## Purpose

The pod's `/app/backend/.env` currently ships **eight production secrets**
loaded in-process at boot. This runbook enumerates each, maps it to the
service that consumes it, points at the dashboard to rotate it, and
records the verification step you can run afterwards.

Nothing here is destructive — this is a reference sheet. Rotate on
your own cadence.

## Inventory

Sourced from a live grep of `os.environ.get(...)` / `os.getenv(...)`
across `/app/backend` plus a byte-scan of `/app/backend/.env`. If a
historic `.env.bak.*` file resurfaces it will map onto this same
inventory.

| # | Env variable                     | Service               | Rotation dashboard                                                 | Loaded by                                                                 |
|---|----------------------------------|-----------------------|--------------------------------------------------------------------|---------------------------------------------------------------------------|
| 1 | `STRIPE_SECRET_KEY_LIVE`         | Stripe (payments)     | https://dashboard.stripe.com/apikeys                              | `services/payments/stripe_charge.py::_set_api_key`                        |
| 2 | `STRIPE_SECRET_KEY_TEST`         | Stripe (sandbox)      | https://dashboard.stripe.com/test/apikeys                         | same module, ``STRIPE_MODE=test`` path                                    |
| 3 | `STRIPE_WEBHOOK_SECRET_LIVE`     | Stripe webhook verify | https://dashboard.stripe.com/webhooks → endpoint → "Signing secret" | `routers/stripe_router.py::verify_signature`                              |
| 4 | `JWT_SECRET`                     | Session tokens        | Regenerate locally: `python -c "import secrets;print(secrets.token_urlsafe(64))"` | `utils.py::get_current_user`, `routers/auth.py::_mint_token`              |
| 5 | `MONGO_URL`                      | MongoDB (Atlas/local) | Atlas → cluster → Database Access → rotate SRV credentials         | `config.py` (module import)                                               |
| 6 | `RESEND_API_KEY`                 | Resend (email)        | https://resend.com/api-keys — **Emergent-managed**; escalate via support | `emailer.py::_resend_client`                                              |
| 7 | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 object storage | https://console.aws.amazon.com/iam → Users → access keys       | `services/objects/aws_s3.py`                                              |
| 8 | `GOOGLE_MAPS_API_KEY`            | Maps / directions     | https://console.cloud.google.com/apis/credentials                 | `routers/on_my_way.py`, `routers/dispatch_route_optimize.py`, others      |

**Not currently loaded** but historically present, kept here so the
grep-first inventory captures them if they reappear:

*   `RINGCENTRAL_WEBHOOK_TOKEN` — SMS inbound webhook.
    Dashboard: https://developers.ringcentral.com/my-account.html
*   `OPENWEB_NINJA_ZILLOW_API_KEY` — Zillow adapter.
    Dashboard: https://rapidapi.com/openwebninja/api/zillow-com1
*   `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` — SEO rank scans (grep
    only picks these up when the SEO cron is toggled on).
    Dashboard: https://app.dataforseo.com/api-access

## Rotation checklist (per key)

For every rotation, follow the same three steps:

1.  **Generate** the new value on the vendor dashboard (see column 4).
2.  **Update** the pod's env — replace the value in
    `/app/backend/.env`, then `sudo supervisorctl restart backend`.
3.  **Verify** using the corresponding check below.

## Verification per key

| Key                                | Verification                                                                                       |
|------------------------------------|----------------------------------------------------------------------------------------------------|
| `STRIPE_SECRET_KEY_LIVE`           | `curl -s ${REACT_APP_BACKEND_URL}/api/health/payments`; expect `{"status":"ok",...}`               |
| `STRIPE_SECRET_KEY_TEST`           | Temporarily unset LIVE + generic keys → hit `/api/health/payments`; expect `"ok"` again            |
| `STRIPE_WEBHOOK_SECRET_LIVE`       | Re-send any past webhook from the Stripe dashboard, confirm 2xx in backend logs                    |
| `JWT_SECRET`                       | Log in as `admin@aquaterra.com` / `password123`, confirm the new token authenticates on `/api/health/ready` |
| `MONGO_URL`                        | `curl -s ${REACT_APP_BACKEND_URL}/api/health/ready`; expect `{"status":"ok"}`                       |
| `RESEND_API_KEY`                   | Trigger Marketing → Send Test Email OR `curl -sX POST /api/admin/comms/send-test-email` (admin JWT); expect 200 |
| `AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY` | Upload one asset via admin media uploader, confirm the S3 object round-trips (`/api/admin/s3/health` also useful) |
| `GOOGLE_MAPS_API_KEY`              | Load `/admin/dispatch` or `/admin/settings/gps`; confirm map tiles render (browser dev tools show no 4xx from `maps.googleapis.com`) |

Once every relevant row is green you are safe to consider the rotation complete.

## BFG git-history purge (if any secret leaked into a commit)

Only run this in a clean local clone of the repo — never on the pod.

```bash
# 1. Fresh mirror clone (bare — no working tree).
git clone --mirror git@github.com:<org>/<repo>.git
cd <repo>.git

# 2. Purge the leaked file(s). Add one --delete-files call per path
#    that ever committed a secret (env backups are the usual suspect).
bfg --delete-files .env.bak.1785270663
bfg --delete-files .env.bak.\*     # sweep any historical siblings

# 3. Expire the reflog + garbage-collect so the blobs actually go.
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 4. Force-push to overwrite remote history.
git push --force

# 5. Notify collaborators to re-clone. Their local clones still
#    contain the purged blobs — a plain ``git pull`` will NOT
#    dislodge them. Re-clone is the only safe path.
```

After the force-push, every collaborator must delete their local
clone and re-clone from scratch. Any branch cut before the purge
still carries the leaked blob until the clone is refreshed.

## Guardrails honoured

*   No `.env.bak.*` files exist in `/app` at the time of writing —
    this runbook is a proactive inventory built from grep against
    `/app/backend`. If a historic backup resurfaces on-disk, its
    contents will map cleanly onto the eight rows above.
*   Zero secrets are printed in this document. Every value stays in
    the pod's `.env` or the vendor dashboard.

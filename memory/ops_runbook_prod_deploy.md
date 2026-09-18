# Production Deploy Runbook — 2026-02-XX

> **Snapshot generated on preview environment (`poolscape-audit`) — dry-run outputs captured from a real preview database. Prod counts will differ (higher tenant + technician cardinality); the shape / semantics of the reports are identical.**

## Prerequisites
- **Production admin credentials** — a `super_admin` account for `app.plofv.com`.
- **`super_admin` JWT** for the migration REST endpoint, minted via `POST /api/auth/login` on the production URL.
- **Pod shell access on prod** (fallback path for the two CLI-only migrations; the dunning migration also has an API endpoint).
- **Read-only Mongo access on prod** for the verification steps (used for `count_documents` spot checks).
- **A quiet 10-minute window** — none of these three migrations write more than a few dozen rows total on preview; prod may write a few hundred but is still measured in seconds. The migrations are all idempotent, but a quiet window makes the verification signal cleaner.

### Actions bundled in this deploy
1. Dunning-stage CTA rewrite (`Pay online:` → `View invoice:`) — Feb 2026 · Invoice Email CTA Label ticket
2. Legacy low-contrast color migration (WCAG contrast reconciliation for preset palette)
3. Technician → user_id backfill (mobile ColorPicker "No linked user account" fix)
4. EAS mobile publish (native-build required — `@react-native-community/slider` fingerprint mismatch)
5. Secret rotation (`.env.bak.1785270663` — Stripe / JWT / DataForSEO / Mongo / RingCentral / Resend / Google Maps / S3)

---

## Order of Operations

1. **Snapshot prod state**
   - `mongodump` (or Atlas snapshot) of `dunning_settings`, `users`, `technicians` collections.
   - Suffix each with a timestamp so rollback restore is unambiguous.
2. **Deploy web + backend to prod** via existing Save-to-GitHub → Publish flow.
   *After publish, verify `/api/health` returns 200 on `app.plofv.com` before touching migrations.*
3. **Dry-run every migration on prod** (Sections 1 / 2 / 3 below — dry-run commands).
   Cross-check counts against expectations; if a count looks off (e.g., >10x preview) STOP and reconfirm target.
4. **Commit-run each migration in the order listed** (Sections 1 / 2 / 3).
5. **Verify each** via the endpoint listed in the section's Verification block.
6. **Ship EAS native build + publish update** (Section 4).
7. **Rotate leaked secrets** (Section 5).
8. **Run the post-deploy smoke tests** at the bottom of this document.

Rollback plans are per-section below. All three migrations are idempotent (a second run is a 0-affected no-op), so most "did that work?" moments are safely re-runnable.

---

## Section 1 — Dunning-stage CTA backfill

**What it does**
Rewrites every persisted `dunning_settings.stages[*].body_template` whose email body still contains the literal `"Pay online: "` prefix, replacing it with `"View invoice: "`. Stamps a `dunning_stage_cta_migrated` audit entry per affected tenant. Custom-authored stage bodies that never contained the legacy literal are untouched.

**Preview dry-run output**
```
$ python -m services.migrations.dunning_stages_view_invoice_backfill
{
  "dry_run": true,
  "tenants_scanned": 65,
  "tenants_affected": 0,
  "stages_rewritten": 0,
  "audit_stamped": 0,
  "per_tenant": []
}
```
- Wall-clock: **0.685 s**
- Preview is already fully migrated (all 65 tenants processed on the prior commit-run in this session). The zero-affected result confirms **idempotency** — running this migration again is a safe no-op.
- Prod expectation: on the first prod run, `tenants_affected` will equal the count of prod tenants that have persisted `dunning_settings` docs (typically 1 doc per active tenant that ever visited Settings → Dunning). `stages_rewritten` = `tenants_affected * 6` for tenants using the canonical 6-stage default; tenants with custom stages report exactly the number of stages that contained the legacy literal.

**Prod command — API endpoint (preferred)**
```bash
API_URL=https://app.plofv.com
TOKEN=$(curl -sS -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"<super_admin_email>","password":"<super_admin_password>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 1. Dry-run (safety-first default)
curl -sS -X POST "$API_URL/api/admin/migrations/run-dunning-stage-cta-backfill" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dry_run":true}' | python3 -m json.tool

# 2. Real run
curl -sS -X POST "$API_URL/api/admin/migrations/run-dunning-stage-cta-backfill" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dry_run":false}' | python3 -m json.tool
```

**Prod command — pod shell fallback**
```bash
# Dry-run
python -m services.migrations.dunning_stages_view_invoice_backfill
# Real run
python -m services.migrations.dunning_stages_view_invoice_backfill --commit
```

**Expected real-run output**
```json
{
  "dry_run": false,
  "tenants_scanned": <N>,
  "tenants_affected": <M>,       // 1 per prod tenant with dunning_settings docs holding the legacy literal
  "stages_rewritten": <M * 6>,   // 6 canonical stages per tenant (roughly)
  "audit_stamped": <M>,
  "per_tenant": [ /* per-tenant diffs */ ]
}
```

**Verification**
```bash
# Sample a real tenant + confirm the stage body now starts with "View invoice:"
curl -sS "$API_URL/api/dunning/settings" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print([s['body_template'][:80] for s in d['stages']])"
# → every entry should start with 'Hi {customer_name},\n\nJust a friendly reminder…'
#   and contain 'View invoice: {payment_link}' (never 'Pay online:').
```

**Rollback**
Not required — the migration is idempotent and non-destructive (single string replacement inside an existing HTML/plaintext body). If concerned, restore `dunning_settings` from the pre-migration snapshot in step 1 of the Order of Operations.

---

## Section 2 — Legacy low-contrast color migration

**What it does**
Reconciles the preset palette for legacy users who selected a low-contrast hex before the Feb 2026 WCAG contrast validator (`utils/color_contrast.py`) landed. Migrates every affected `users.color` value to the nearest same-family higher-contrast preset (e.g., `#10B981` → `#059669`). Writes a `color_migration_audit` entry per updated user for rollback.

**Preview dry-run output**
```
$ python -m services.migrations.legacy_low_contrast_color_migration --dry-run
scanned=12 affected=0 updated=0 dry_run=True
```
- Wall-clock: **0.678 s**
- Zero affected on preview because all 12 users are already on WCAG-compliant hexes (this migration was run in the prior session).
- Prod expectation: on the first prod run, `affected` will equal the count of users still on one of the deprecated legacy hexes. `updated == affected` unless a race condition ever intervenes (safe to re-run — the migration only touches users still on the deprecated list).

**Prod command**
```bash
# Dry-run
python -m services.migrations.legacy_low_contrast_color_migration --dry-run
# Real run
python -m services.migrations.legacy_low_contrast_color_migration
```

**Verification**
```bash
# Palette endpoint should return exactly 18 entries, none of which are the
# deprecated low-contrast hexes.
curl -sS "$API_URL/api/tech-colors/palette" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'palette_count={len(d)}')"
# → palette_count=18

# Pick a legacy tech that was on #10B981 (if any exist in prod) and confirm
# they're now on the higher-contrast #059669 (or your migration's mapped value).
curl -sS "$API_URL/api/users?role=technician" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print([{'name':u.get('name'),'color':u.get('color')} for u in d if u.get('color','').upper() in {'#10B981','#059669'}])"
```

**Rollback**
Every updated user has an `event=color_migrated` entry in `db.color_migration_audit` with `{user_id, tenant_id, old_color, new_color, ts}`. To rollback a specific tenant / user:

```bash
python3 -c "
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
c = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
async def m():
    async for e in c.color_migration_audit.find({'event':'color_migrated','tenant_id':'<TID>'}):
        await c.users.update_one({'id': e['user_id']}, {'\$set': {'color': e['old_color']}})
asyncio.run(m())
"
```
(Or `mongorestore` the snapshot from Order-of-Operations step 1.)

---

## Section 3 — Technician user_id backfill

**What it does**
Links every `db.technicians` row missing a `user_id` back to the same-tenant `db.users` account via case-insensitive email match, then falls back to case-insensitive name match. Rows with no user match are SKIPPED with a `technician_unlinked_no_user_match` audit stamp — ops decides whether to create a login credential for them manually. Without a `user_id`, the mobile ColorPicker Apply flow short-circuits with `"No linked user account for this technician."` because the endpoint PATCHes `/api/users/{tech.user_id}`.

**Preview dry-run output**
```
$ python -m services.migrations.technicians_user_id_backfill --dry-run
scanned=4 already_linked=3 linked=0 skipped=1 dry_run=True

Per-row plan (first 30):
  SKIP  tech=3b6ebe3c.. name='Sara Nguyen' reason=no_user_match
```
- Wall-clock: **0.672 s**
- `already_linked=3` → 3 of 4 preview techs already have `user_id` (linked by the prior session's real run).
- `skipped=1` → **Sara Nguyen** — synthetic fixture tech row with no matching user. **This is EXPECTED**; ops decides whether to create a login credential for her. If she should have a login, mint a user row then re-run the backfill (idempotent).
- Prod expectation: `already_linked` will be high (most seeded techs were linked at creation post-Feb 2026). `linked` = count of legacy techs whose email OR name matches a `users` row in the same tenant. `skipped` = techs with no user match (ops workflow to review).

**Prod command — CLI**
```bash
# Scan every tenant at once (safe: --tenant-id omitted scans the whole DB)
python -m services.migrations.technicians_user_id_backfill --dry-run
# Real run
python -m services.migrations.technicians_user_id_backfill
```

**Prod command — per-tenant loop (recommended for staged rollout)**
```bash
# Enumerate active tenants + dry-run each in isolation
python3 -c "
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
c = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
async def m():
    async for t in c.tenants.find({'active': {'\$ne': False}}, {'_id': 0, 'id': 1, 'slug': 1}):
        print(f'{t[\"id\"]}  # {t.get(\"slug\",\"\")}')
asyncio.run(m())" > /tmp/prod_tenants.txt

# Then loop:
while read -r line; do
  tid=$(echo "$line" | awk '{print $1}')
  [ -z "$tid" ] && continue
  echo "--- $line ---"
  python -m services.migrations.technicians_user_id_backfill --dry-run --tenant-id "$tid"
done < /tmp/prod_tenants.txt

# Once satisfied, drop --dry-run to commit.
```

**Verification**
```bash
curl -sS "$API_URL/api/technicians" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'total={len(d)}  unlinked={sum(1 for t in d if not t.get(\"user_id\"))}  linked={sum(1 for t in d if t.get(\"user_id\"))}')"
# → total=N linked=N unlinked=<count of legitimately-skipped techs, e.g. Sara Nguyen equivalents>
```

**Rollback**
Every linked technician has an `event=technician_user_linked` entry in `db.color_migration_audit` with `{tech_id, tenant_id, user_id, matched_by, ts}`. To rollback:

```bash
python3 -c "
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
c = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
async def m():
    async for e in c.color_migration_audit.find({'event':'technician_user_linked','tenant_id':'<TID>'}):
        await c.technicians.update_one({'id': e['tech_id']}, {'\$unset': {'user_id': ''}})
asyncio.run(m())
"
```
(Or `mongorestore` the `technicians` collection from step 1.)

---

## Section 4 — EAS Mobile Publish

**Why native build is required for this deploy**
Two changes require a fresh native binary (JS-only OTA is insufficient):
- `@react-native-community/slider` was added as a dep for the ColorPicker native flow — new native module → fingerprint mismatch on the JS bundle → over-the-air update would crash on install.
- Schedule ID filter fix touches the JS bundle only (safe for OTA in principle), but must ship together with the native change to keep versions aligned.

**Exact commands (run from ops laptop or x86_64 CI)**
```bash
# From /app/mobile (NOT modifiable by this agent — mobile parity is
# owned by the mobile delegation agent, but ops does own the publish).
cd /app/mobile

# 1. Build for BOTH platforms with the production profile
eas build --platform all --profile production
# ↳ Wait for build to succeed on EAS dashboard + get promoted to
#   TestFlight (iOS) / internal track (Android). Typical wall-clock
#   is 15-45 minutes. This step also propagates the new
#   @react-native-community/slider native module.

# 2. Once both binaries land in the respective stores, ship the JS
#    over-the-air update so users on the freshly-installed binary
#    get the Schedule ID filter fix + ColorPicker JS in-hand:
eas update --branch production \
  --message "Schedule ID filter fix + ColorPicker native deps"
```

**Environmental note (pod)**
The EAS Update **export** step doesn't work in the current pod: the pod is ARM64 (aarch64) but the Expo/Hermes bytecode compiler ships an x86_64 binary. Running `eas update` from `/app/mobile` inside the pod fails with an ELF-arch mismatch. Ops must run from a local Mac / Linux x86_64 machine, or from an x86_64 CI runner (GitHub Actions `ubuntu-latest`, CircleCI, etc.).

**Verification (mobile)**
- Login as a technician on the freshly-installed build.
- Open the Schedule tab — confirm scheduled jobs appear (technician_id filter fix).
- Open Profile → Color — confirm ColorPicker slider renders + Apply persists to `/api/users/{me}` → the color reflects on the schedule chip.

---

## Section 5 — Secret rotation (`.env.bak.1785270663`)

**Context**
A prior fork accidentally committed `.env.bak.1785270663` with real production secrets. That backup file is still in the git history and must be rotated + purged. Rotation MUST happen before purging history so that any pre-purge clone still pointing at the old keys becomes inert.

**Leaked keys inventory**
| # | Vendor | Env var | Rotation URL (ops fills in) | Where prod reads the key |
| - | ------ | ------- | --------------------------- | ------------------------ |
| 1 | Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | https://dashboard.stripe.com/apikeys · https://dashboard.stripe.com/webhooks | Emergent env editor (Production tab) |
| 2 | JWT signing | `JWT_SECRET` | *(self-hosted — mint a new 64-char random)* | Emergent env editor |
| 3 | DataForSEO | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | https://app.dataforseo.com/api-access | Emergent env editor |
| 4 | MongoDB | Password portion of `MONGO_URL` | https://cloud.mongodb.com/ → Database Access | Emergent env editor |
| 5 | RingCentral | `RINGCENTRAL_CLIENT_ID`, `RINGCENTRAL_CLIENT_SECRET`, `RINGCENTRAL_JWT` | https://developers.ringcentral.com/my-account.html | Emergent env editor |
| 6 | Resend | `RESEND_API_KEY` | https://resend.com/api-keys | Emergent env editor |
| 7 | Google Maps | `GOOGLE_MAPS_API_KEY` | https://console.cloud.google.com/apis/credentials | Emergent env editor |
| 8 | AWS S3 | `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | https://console.aws.amazon.com/iam/home?#/security_credentials | Emergent env editor |

**Rotation procedure per key**
1. Log in to the vendor console, generate a NEW key (do NOT revoke the old one yet — some vendors do this in one step; others require a small overlap window).
2. Paste the new value into the Emergent env editor (Production tab), Save.
3. Trigger a rolling restart on prod (Emergent deploy flow OR simply hit any endpoint that lazily re-reads env).
4. Verify no downtime — call one endpoint that exercises the key:
   - Stripe: `POST /api/payments/health` (or an admin-only test-mode charge).
   - Resend: any transactional send (payment reminder to a test tenant).
   - RingCentral: `POST /api/comms/test-sms` (super_admin only).
   - Google Maps: `GET /api/geocode?q=aquaterra` (any address round-trip).
   - S3: photo upload on any tenant → verify the URL resolves.
   - Mongo: `GET /api/health` (fails hard if the URL is invalid).
5. Revoke the OLD vendor key.

**Verification — no downtime**
- Grep the tenant admin panel for a 5xx spike in the 10 minutes post-rotation.
- Backend logs: `grep -iE "unauthorized|invalid.*(key|token)|401|403" /var/log/supervisor/backend.*.log | tail -50` — should return zero fresh matches after the rotation window.

**Git-history purge (AFTER all keys are rotated)**
```bash
# Option A — BFG (recommended, faster)
brew install bfg          # or download the jar
git clone --mirror <repo>.git repo-mirror.git
cd repo-mirror.git
bfg --delete-files ".env.bak.1785270663"
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force

# Option B — git filter-branch (native)
cd <repo>
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch backend/.env.bak.1785270663 \
                                     frontend/.env.bak.1785270663' \
  --prune-empty --tag-name-filter cat -- --all
git push origin --force --all
git push origin --force --tags
```
After the force-push, every collaborator MUST re-clone (or run `git reflog expire && git gc --prune=now`) so pre-purge object hashes are unreachable locally too.

---

## Post-Deploy Smoke Tests

Run in this order after all migrations + EAS + rotation are done:

1. **Payment Reminder email** — send a test reminder to a Spanish test tenant customer; confirm the rendered email HTML shows `"Ver factura"` (regression proof for the runtime i18n wiring).
2. **Invoice viewer** — open both `/portal/invoices/:id` (logged-in customer) and `/i/:token` (magic link) on prod; confirm the top Pay CTA is **full-width red** and clicking opens the PaymentForm.
3. **Ack-bypass edit** — pick a `past_due` invoice as `admin`; edit a line item → ack-bypass popup appears → save persists (backend + frontend gate agree).
4. **Palette count** — `GET /api/tech-colors/palette` returns exactly **18** entries; sample a formerly-legacy hex user and confirm they're on the higher-contrast replacement.
5. **Mobile schedule** — login as a tech in the fresh EAS build; confirm the scheduled jobs list renders (technician_id filter fix).
6. **Mobile ColorPicker** — pick a color on mobile → Apply → refresh — confirm the color persists on the tech row (technician_id → user_id link verified).
7. **Vendor health checks** — hit one endpoint per rotated vendor (Stripe / Resend / RingCentral / Google Maps / S3 / Mongo); confirm each returns 200 and the new key was consumed cleanly.

---

## Appendix — Preview timing summary

| Migration | Wall-clock | Preview affected | Idempotent? |
| --------- | ---------- | ---------------- | ----------- |
| Dunning CTA backfill | 0.685 s | 0 (already migrated) | ✅ |
| Legacy low-contrast color | 0.678 s | 0 (already migrated) | ✅ |
| Technicians user_id backfill | 0.672 s | 0 to link, 1 skip (Sara Nguyen — expected) | ✅ |

All three complete in under **1 second wall-clock** on preview. Prod is expected to complete in seconds even with a higher tenant / user cardinality (all queries hit indexed fields).

# Production Cutover — `.env` + CORS Checklist

**Prepared:** 2026-11-03 · **HEAD:** `c47d6c807`
**Target production domain (operator-stated):** `https://app.plofv.com`
**Scope:** `backend/.env` + CORS only.  Nothing is applied by this document — this is a review-ready diff and bash snippet the operator applies when they are ready to flip.

---

## Correction to the earlier readiness report

Two values in the Deployment Readiness report were asserted from grep heuristics without a direct read.  Direct read of the current `backend/.env`:

| Key | Readiness report said | Actual current line |
|---|---|---|
| `APP_ENV` | `preview` | **`APP_ENV=development`** (line 66) |
| `ALLOW_TEST_HOOKS` | `true` | **not present** — defense-in-depth at `server.py:1772-1775` auto-forces `ALLOW_TEST_HOOKS=0` whenever `APP_ENV=production` anyway |
| `AI_TESTMODE_MOCK` | `1` | **`false`** (line 129) — already off |
| `CALENDARS_TESTMODE_MOCK` | `1` | **`false`** (line 120) — already off |

Net: the environment is less dirty than the readiness report feared.  Only **two live changes** are required (`APP_ENV`, `CORS_ORIGINS`).

---

## 1. `APP_ENV` — flip to production

**Current** (`backend/.env:66`):
```
APP_ENV=development
```

**Target:**
```
APP_ENV=production
```

**Safety grep** (why this is safe):
- `backend/config.py:54` — `_APP_ENV = os.environ.get("APP_ENV", "preview").lower()` (safe default if missing).
- `backend/server.py:1772-1775` — SEC-P3-2 hotfix: when `APP_ENV=production`, the server **auto-forces** `ALLOW_TEST_HOOKS=0` regardless of env, and refuses to mount `/test-hooks/*` routes.
- `backend/server.py:4001-4017` — SP3 startup guard logs a 🚨 when `ALLOW_TEST_HOOKS=1` is detected on a prod-detected pod, and short-circuits test-hook Stripe routes.
- `backend/scripts/purge_demo_data.py:441-442` — refuses `--commit` unless `APP_ENV=production`; dry-run always allowed anywhere.  Flipping to `production` **unblocks** destructive `purge_demo_data --commit` from any shell; audit that script's access before flipping.

**Transitive effects to validate after flip:**
- `/test-hooks/*` routes 404 at the ingress (server refuses to mount them).  Any monitor or probe that hits those must be removed.
- `purge_demo_data.py --commit` becomes callable.  Rotate credentials / restrict shell access accordingly.
- `logger.warning` lines containing "APP_ENV=production forcing …" and "🚨 ALLOW_TEST_HOOKS=1" become visible in prod logs during startup.  Both are informational.

---

## 2. `CORS_ORIGINS` — tighten the wildcard

**Current** (`backend/.env:3`):
```
CORS_ORIGINS="*"
```

**Target:**
```
CORS_ORIGINS=https://app.plofv.com
```
(if a staging or admin subdomain is in the same tenant, append comma-separated: `CORS_ORIGINS=https://app.plofv.com,https://staging.plofv.com`)

**Safety grep** (why this is safe):
- `backend/server.py:1748-1766` — parses `CORS_ORIGINS` env var; honours a comma list; logs a loud warning when the value is `*` ("permissive — tighten before prod"); ignores accidental wildcard entries inside an explicit list.
- No code assumes wildcard.  No downstream routes depend on `Access-Control-Allow-Origin: *`.
- `APP_PUBLIC_URL="https://app.plofv.com"` is already set (line 5) — the CORS entry mirrors the public URL cleanly.

**Transitive effects:**
- Any staff tool, Postman collection or mobile preview that was relying on `Origin: *` tolerance will start receiving CORS rejections.  The web app itself uses same-origin for `/api/*` and is unaffected.
- Custom domains (white-label) must be enumerated here too.  If you add tenant-custom domains later, extend this list.

---

## 3. `ALLOW_TEST_HOOKS` — no action

**Current:** not present in `backend/.env`.
**Target:** leave absent.

**Why:** code treats absent / `"0"` / any non-`"1"` value as off.  Server.py line 1772-1775 double-enforces this when `APP_ENV=production`.  Belt-and-braces already covered.

---

## 4. `AI_TESTMODE_MOCK` and `CALENDARS_TESTMODE_MOCK` — no action

**Current** (`backend/.env:120, 129`):
```
CALENDARS_TESTMODE_MOCK=false
AI_TESTMODE_MOCK=false
```
**Target:** unchanged.  Already off.  Default-safe parser in `services/ai/_helpers.py:25-26` and `services/calendars/_helpers.py` returns `False` for anything that isn't `"1"` / `"true"` / `"yes"`.

---

## 5. Other `*_TESTMODE_*` / `*_TEST_*` / `*_MOCK_*` flags found in current `.env` (operator should review individually)

| Line | Key | Current | Prod-safe? | Note |
|---|---|---|---|---|
| 3 | `CORS_ORIGINS` | `"*"` | ❌ change | covered above |
| 28 | `TEST_LLM_MOCK` | `0` | ✅ already off | LLM mock short-circuit; off is prod-safe |
| 46 | `AI_VISIBILITY_CRON_ENABLED` | `false` | ✅ off | AEO visibility cron; keep off unless the cron is contracted |
| 66 | `APP_ENV` | `development` | ❌ change | covered above |
| 112 | `STRIPE_TESTMODE_MOCK_CONNECT` | `true` | ⚠️ **REVIEW** | enables mocked Stripe Connect onboarding; prod Stripe Connect **must** use live keys & flow.  Flip to `false` or remove IF the live key `STRIPE_SECRET_KEY` is present. |
| 120 | `CALENDARS_TESTMODE_MOCK` | `false` | ✅ off | |
| 127 | `PAYMENTS_TESTMODE_MOCK` | `false` | ✅ off | |
| 128 | `ZILLOW_TESTMODE_MOCK` | `false` | ✅ off | |
| 129 | `AI_TESTMODE_MOCK` | `false` | ✅ off | |

**Allowlist flags (operator check only — not touched here):**
- `COMMS_TEST_ALLOWLIST_EMAILS` (line 15-ish) — currently contains three internal emails.  In prod, either keep for staged rollout or clear to `""` once mass-messaging is sanctioned.
- `COMMS_TEST_ALLOWLIST_PHONES` — same.
- `PAYMENTS_TEST_ALLOWLIST_CUSTOMERS` — currently empty; fine.

---

## 6. Copy-pasteable bash snippet

Apply ONLY after the operator has:
1. Taken a backup of the current `.env` (`cp backend/.env backend/.env.backup.$(date +%F)`).
2. Confirmed `https://app.plofv.com` is the final production domain.
3. Decided on `STRIPE_TESTMODE_MOCK_CONNECT` based on whether live Stripe Connect is ready.

```bash
# Backup first
cp backend/.env backend/.env.backup.$(date +%F)

# Change 1 of 2 — flip CORS_ORIGINS
sed -i 's|^CORS_ORIGINS="\*"$|CORS_ORIGINS=https://app.plofv.com|' backend/.env

# Change 2 of 2 — flip APP_ENV
sed -i 's|^APP_ENV=development$|APP_ENV=production|' backend/.env

# (Optional) flip the Stripe Connect mock IF live Stripe Connect is ready
# sed -i 's|^STRIPE_TESTMODE_MOCK_CONNECT=true$|STRIPE_TESTMODE_MOCK_CONNECT=false|' backend/.env

# Verify the three lines
grep -E '^(CORS_ORIGINS|APP_ENV|STRIPE_TESTMODE_MOCK_CONNECT)=' backend/.env

# Reload the backend so the new env is picked up
sudo supervisorctl restart backend
sleep 4
curl -sS https://app.plofv.com/api/health | head -c 400
```

Expected `/api/health` payload: `{"status":"ok","app":"CRM",…}` + `app_env: "production"` in the migrations diag block.

---

## 7. Post-flip verification

```bash
# Should be refused with a CORS error:
curl -sS -H "Origin: https://evil.example.com" https://app.plofv.com/api/health -o /dev/null -w "%{http_code}\n"

# Should return 404 (test-hooks never mounted in prod):
curl -sS https://app.plofv.com/api/test-hooks/purge -o /dev/null -w "%{http_code}\n"

# Backend startup logs should show:
#   [cors] origins=['https://app.plofv.com']   (no wildcard warning)
#   APP_ENV=production forcing ALLOW_TEST_HOOKS=0 (only if someone else added it)
sudo supervisorctl tail backend stderr | grep -iE "cors|APP_ENV|ALLOW_TEST_HOOKS" | head -20
```

---

## 8. Rollback

```bash
cp backend/.env.backup.$(date +%F) backend/.env
sudo supervisorctl restart backend
```

---

## 9. What this document did NOT touch

- Live `backend/.env` file — zero bytes modified.
- `backend/.env.example` — no change.  Cross-check that production operators have a copy that reflects these recommendations is an operator task.
- Frontend `.env` — no change.  Frontend env (`REACT_APP_*`) ships in the bundle; verify Google Maps API-key HTTP-referer restrictions in GCP console target `https://app.plofv.com` before the next build.
- Any source code.
- Any secret rotation (JWT, Fernet, encryption).  If this is the first production push, rotate `JWT_SECRET`, `FERNET_KEY`, and `CHECKS_ENCRYPTION_KEY` to fresh random values, re-sign any outstanding tokens, and re-encrypt any encrypted blobs under new keys.  Not in scope for this checklist.

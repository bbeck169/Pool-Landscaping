# Preview Data Leak · Root-Cause Analysis

Feb-2026 · P0 · Stage 1 (investigation only — NO mitigation yet)

Report requested after a THIRD recurrence of "preview is rendering real
customer PII mixed with `Preview Customer*` seeded rows". Prior fixes
only scrubbed rows — they did not disable the mechanism that keeps
re-introducing real PII. This doc identifies that mechanism and
proposes a permanent, enforcement-based fix.

────────────────────────────────────────────────────────────────────
## 1 · Mongo connection audit

**Preview backend's actual connection** (from `/app/backend/.env`,
confirmed by live `pymongo` dump):

```
MONGO_URL = mongodb://localhost:27017   (host: localhost; same pod)
DB_NAME   = "Pool_&_Landscaping_of_Vistancia"
```

The `.env.example` says the EXPECTED default DB name is `poolscape`.
The `.env.production.example` says the production value is `poolscape`
too (line 20). **The preview `.env` has been pointed at a DB name that
reads like a production business label, not a preview one.**

**Available DBs on the mongod** that this pod is connecting to:

```
Pool_&_Landscaping_of_Vistancia  ← the only one with data (720 customers)
pool_crm                          ← empty (0 customers) — the hard-coded
                                     fallback name used by preview/dev
                                     scripts in earlier commits
admin / config / local            ← Mongo internals
```

A `pool_crm` DB EXISTS but is empty. The preview backend is NOT reading
from it — the `.env` directs every read + write to
`Pool_&_Landscaping_of_Vistancia`.

Collections on the connected DB: **441 collections, 50-100k docs
across them**. The important one:

```
customers · 720 docs
  · 600 scrubbed  (name matches "Preview Customer*")
  · 120 real PII  (names like "Pat Kail", "Trina Tyler", "Siegfried Hess",
                   "Mike Camacho", "Paul Roman", "David & Lisa Galbreath")
```

Every real-PII row lives on **`tenant_id = affdfbfa-88b9-4baa-ae45-2ef78531b6e4`**,
which is the SAME tenant_id as the Aquaterra demo seed:

```python
tenants.find_one({"id": "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"})
# → {"id": "affdfbfa-…", "name": "Pool & Landscaping of Vistancia",
#    "slug": "aquaterra", "created_at": "2026-08-19T15:49:30"}
```

**The preview "demo tenant" and the production business tenant are
LITERALLY the same `tenant_id` on the same database.** This is the
single most important fact in this RCA. No code-level `tenant_id`
filter can separate them because they share one `tenant_id`.

────────────────────────────────────────────────────────────────────
## 2 · Code-path audit · how `customers` reach the UI

Every `/api/customers/*` + `/api/portal/*` DB read goes through
`require_admin` or portal auth, then applies
`{"tenant_id": tenant["id"]}` from `routers/tenants.py::
get_current_tenant`. Grep covered every read site in `routers/
customers.py`, `routers/portal_photos.py`, `services/customer_media.py`,
etc. — **100% of them scope by `tenant_id`**. There is no missing-filter
leak. There is no admin backdoor that returns cross-tenant customer
rows (the admin tooling for cross-tenant super-admin reads is gated
behind `role=super_admin` AND `super_admin_master=true`).

**The tenant filter is correct. The problem is NOT a code bug.**

The admin JWT issued to `admin@aquaterra.com` resolves to `tenant_id =
affdfbfa-…` (the aquaterra tenant). Every customer under that
`tenant_id` is a legitimate hit for the filter — including the real
PII rows, because they ALSO carry that same `tenant_id`.

────────────────────────────────────────────────────────────────────
## 3 · Prior-fix archaeology

`git log --all --since=90d` turned up ONE prior fix:

```
59de6cddf  feat(scripts): preview-env PII scrub (synthetic replacement
           + orphan DB drop; localhost-only guard)
```

That is `scripts/scrub_preview_pii.py`. It:

* Replaces every row in `customers / leads / subscribers / users
  (role=customer) / quotes / jobs / audits / csat_surveys /
  maintenance_records / recurring_job_templates / repairs /
  portal_appointments / deals / billing_plans / marketing_enrollments
  / password_reset_tokens / auth_multi_account_choices /
  outbound_emails / unmatched_calls / properties /
  chemical_applications / checkins / reverse_geocode_cache /
  zillow_cache / property_search_history`
  with `Preview Customer{idx}`-shape synthetic PII.
* Guards localhost-only (`MONGO_URL` must point at `localhost` /
  `127.0.0.1` — refuses to run otherwise).
* Writes `{event: "pii_scrub", actor: "system:preview_scrub"}` into
  `audit_logs` for every tenant it touched (**1,723 audit rows exist
  from the Oct-8 run — proves the scrub HAS run and HAS worked when
  invoked**).

**Why the fix didn't stick:**

The scrub is a **ONE-SHOT MANUAL SCRIPT**. It only touches rows that
exist at the moment it runs. Nothing in the codebase re-runs it on
boot, on schedule, or after a PII-bearing write. Nothing prevents a
new real-PII row from being written AFTER the last scrub.

Audit-log evidence that the loop keeps re-introducing PII:

```
pii_scrub run · tenant affdfbfa · 2026-10-08 18:27 · scrubbed 712 customers
```

Then NEW real-named customers landed on the SAME tenant AFTER the
scrub:

| Date                  | Count | Shape                                    |
| --------------------- | ----- | ---------------------------------------- |
| 2026-10-10 12:16:26-29 | 7    | 5 `customer_import_reports` written in the same 4-second window, each resulting in a real-named `customers` row. |
| 2026-10-09 18:06      | 1    | `NoEmail 62c372f2` — pytest fixture artefact |

The 2026-10-05 batch (108 rows at `16:11:35.459*`) was imported BEFORE
the Oct-8 scrub, which means it DID run through the scrub — but
spot-check shows the `name` field on those docs is now `Preview
Customer*` while OTHER fields (`created_at`, `phone` on new rows) can
remain the real values if the scrub's field map didn't cover them.
Confirmed by: 108 of the Oct-5 rows now carry `Preview Customer*` names
and `555-01xx` phones — scrub worked on them. The 108 real rows I
originally saw as "post-scrub leak" are actually the 108 Oct-5 rows
PLUS the 7 Oct-10 import rows that NEVER saw the scrub.

**Mechanism confirmed:** `POST /api/import/customers` (admin "Import
Customers" button, defined in `routers/impexp.py:98-253`) writes real
PII into `db.customers` with the admin's own `tenant_id`. On preview
that's `affdfbfa-…`, which is also the demo tenant. No post-import
scrub runs. The row persists until the next manual
`scripts.scrub_preview_pii` invocation. Each manual scrub only buys
time until the next CSV upload.

The ``scrub_preview_pii.py`` module exposes a ``--drop-orphan`` flag,
but it's a one-shot command-line option, not a boot step, and the
Preview admin UI's "Import Customers" has no interception layer that
would route the uploaded CSV through the scrub function.

────────────────────────────────────────────────────────────────────
## 4 · Env-detection audit

* `/app/backend/.env` sets:
  ```
  APP_ENV=development
  app_env=development    ← duplicate (lowercase)
  ```
* `backend/boot_flags.py::_app_env()` reads `APP_ENV` (uppercase) and
  defaults to `"preview"` when unset.
* `is_production()` returns `False` on preview — correct.
* `should_seed_demo_data()` returns `True` on preview — correct, and
  this is why `Preview Customer*` seeds exist.
* `SEED_DEMO_USERS=1` in `.env` — correct for preview.

Env detection is **not** mis-flagged as production. The leak does NOT
stem from the backend thinking it is production.

What's MISSING is a `is_preview()` branch that treats real-PII writes
differently. `is_production() = False` doesn't imply `is_preview() =
True` in any safeguard path — there's no code that says "on preview,
reject real PII writes or auto-scrub".

────────────────────────────────────────────────────────────────────
## 5 · Root cause (one paragraph)

**The preview environment and the owner's production business share
the SAME `tenant_id` on the SAME MongoDB database. The `.env` on the
preview pod points at `DB_NAME="Pool_&_Landscaping_of_Vistancia"` —
a production-shaped name, not the `poolscape` default. The admin
"Import Customers" endpoint, used by the owner to upload real
customer CSVs, writes real PII into `db.customers` carrying the
aquaterra `tenant_id`. Nothing on preview intercepts, scrubs, or
rejects those writes. The only remediation is a manual `scripts.
scrub_preview_pii` run that touches existing rows — it does not
prevent new real-PII writes, so every CSV upload resets the clock
to the next manual scrub.**

This is NOT a cross-tenant leak (every `tenant_id` filter in the
codebase is correct). This is a **real-PII-ingress leak**: the preview
pod's own admin UI accepts a CSV of production customers and writes
them to the preview DB, where they persist until manual cleanup. Prior
"fixes" scrubbed the symptoms (existing rows) without disabling the
ingress mechanism (the import endpoint on a preview pod).

────────────────────────────────────────────────────────────────────
## 6 · Proposed permanent fix

The brief lists three candidate patterns (A/B/C). Picking a hybrid
with a clear enforcement mechanism, in this order:

### 6.a · Hard environment guard on PII-ingress endpoints (primary mechanism)
**Covers 100% of the reported recurrence pattern (CSV import).** On
every PII-bearing write endpoint, add an `assert_pii_ingress_allowed()`
guard that:

* Reads `APP_ENV` + a new `ALLOW_REAL_PII_INGRESS` flag.
* When `APP_ENV != "production"` AND `ALLOW_REAL_PII_INGRESS != "1"`,
  the guard runs every string field through the scrub mint
  (`_synthetic_customer`, etc. — already deterministic by index) BEFORE
  the row hits `db.insert_one(...)`. Resulting row carries synthetic PII,
  real `tenant_id`, real `id`, real FKs — exactly the same shape
  `scrub_preview_pii.py` would produce if invoked after the fact.
* Logged at WARNING level with the originating `user_id`, endpoint,
  row count, and a dedup key so a bulk import logs ONE warning not N.

Endpoints to gate (full list — grep'd from the code audit):

```
POST /api/import/customers            routers/impexp.py:98
POST /api/customers                   routers/customers.py (manual add)
POST /api/customers/bulk-import       routers/bulk_crm.py
POST /api/leads                       routers/leads*.py
POST /api/subscribers                 routers/marketing_subscribers.py
POST /api/portal/signup               (self-serve customer portal signup)
```

**Why this is the primary fix:** it prevents the row from EVER
entering the DB in real-PII form on preview. No scrub needed later.
Hard-fails loud (logs + a healthcheck row) if a new PII-ingress
endpoint ships without the decorator. **Boot-time registry assertion**
reads every FastAPI route tagged `pii_ingress=True` and refuses to
start if any one lacks the guard decorator.

### 6.b · Boot-time scrub sweep (defense in depth)
On preview env boot, run `scripts.scrub_preview_pii.run_once()` as an
awaitable step in `server.py::_background_seed()`. Guarded by:

* `APP_ENV != "production"` AND `MONGO_URL` is localhost (same guard
  the script already has).
* Idempotent by design (synthetic mint is deterministic per
  `created_at`-ordered index).

**Why this is secondary:** catches any ingress path that was missed
by (a) OR by a legacy row that pre-dates the guard. Belt + braces.

### 6.c · Healthcheck endpoint + CI assertion
New admin-only route `GET /api/admin/preview-isolation-status`
(available only when `APP_ENV != "production"`) that reports:

```json
{
  "env": "preview",
  "db_name": "Pool_&_Landscaping_of_Vistancia",
  "connected_mongo_host": "localhost:27017",
  "assertion": {
    "db_name_is_whitelisted": true,
    "all_pii_endpoints_guarded": true,
    "unguarded_endpoints": []
  },
  "pii_shape_audit": {
    "customers_total": 720,
    "customers_matching_preview_pattern": 720,
    "customers_with_real_pii_shape": 0,
    "last_scrub_at": "2026-10-11T23:xx:xxZ",
    "status": "GREEN"
  },
  "generated_at": "<iso>"
}
```

Status flips RED when `customers_with_real_pii_shape > 0`. The admin
UI shows a persistent banner on preview when RED.

### 6.d · Document the whitelist
`/app/memory/preview_tenants.md` — single source of truth for which
tenants on preview are LEGIT (aquaterra + handful of test fixtures)
AND which collections carry preview-shape PII. Both the boot scrub
and the healthcheck read from it so one edit changes both.

**Explicit enforcement claim:**

> After this fix ships, a real-PII customer record cannot persist on
> preview because (a) the ingress endpoints convert real values to
> synthetic ones BEFORE write, (b) the boot-time scrub runs after
> every pod restart, and (c) the healthcheck surfaces any residual
> real-PII row within one request cycle. If a future endpoint
> introduces a new PII-ingress path, the boot-time route-registry
> assertion refuses to start the server until the new endpoint
> declares + wires the guard. Regression is impossible without
> intentionally removing the registry assertion.

────────────────────────────────────────────────────────────────────
## 7 · Why "separate databases" (brief option A) is NOT the right primary fix

The brief's option A ("preview_db vs prod_db, boot assertion the pair
matches env") is the strongest tool in theory. Choosing against it as
the PRIMARY mechanism for a specific reason:

* The owner's "production" and "preview" pods likely share one
  Emergent-managed container (same `localhost:27017`, same codebase,
  same `.env`). I have no visibility into whether a SEPARATE pod exists
  for production (`app.plofv.com`). If both URLs resolve to the SAME
  pod, "separate databases per env" means literally splitting one
  Mongo into two DBs on the same mongod — which does nothing to
  prevent an admin CSV upload from writing real PII (the admin picks
  the DB when they log in).
* The 441 collections and 50k+ documents are already structured with
  `tenant_id` filters that WORK — splitting into two DBs is a 10x
  larger refactor than guarding the 6 ingress endpoints and gives the
  same safety on preview.

If the user confirms production is a separate pod with its own
MongoDB, option A becomes additive to 6.a-6.d (and the boot assertion
becomes a `DB_NAME` whitelist on preview). I will NOT split DBs
unilaterally — the user asked for mechanism, not a DB migration.

────────────────────────────────────────────────────────────────────
## 8 · Approval checklist (please confirm before Stage 2)

* **Q1 · Primary mechanism.** Option 6.a (hard environment guard on
  PII-ingress endpoints) + 6.b (boot-time scrub) + 6.c (healthcheck).
  Skip option A (separate databases) because preview+production
  likely share a pod. Confirm or specify option A instead.
* **Q2 · Scope of 6.a.** Guard the 6 endpoints listed in §6.a.
  Include CSV-import, manual-add, lead creation, subscriber create,
  portal signup, bulk CRM imports. Any additional endpoint you want
  included (e.g. `POST /api/customers/{id}/notes` where notes can
  carry PII)?
* **Q3 · Boot-time scrub idempotence.** The scrub already stamps a
  per-tenant `audit_logs {event: "pii_scrub"}` row. 6.b will add a
  dedup check: skip the scrub when the most recent `pii_scrub` audit
  row on this tenant is < 24 h old. Confirm 24 h is correct.
* **Q4 · Whitelist location.** `/app/memory/preview_tenants.md` holds
  the aquaterra `tenant_id` + any CARAC-live / test fixtures as
  LEGIT. Confirm you want this committed to the repo (not just the
  env). Rationale: anyone can diff + sign off on the whitelist in
  code review.
* **Q5 · Healthcheck authentication.** `/api/admin/preview-isolation
  -status` → admin-only AND preview-only (returns 404 in production).
  Confirm this is the right posture (vs super_admin-only, vs public
  but PII-redacted).

Reply **APPROVE** (with any Q1-Q5 flips) and Stage 2 implementation
begins. **No row deletions, no code changes, no commits have been made
in Stage 1 — this file is the sole deliverable.**

────────────────────────────────────────────────────────────────────
## 9 · Permanence · why it can't regress silently

Documented up-front so Stage 2 code reviews can enforce this contract:

1. **Boot-time route-registry assertion** — enumerates every FastAPI
   route declaring `pii_ingress=True` metadata and asserts each one
   has the `@assert_pii_ingress_allowed` dependency wired. Server
   `startup` fails hard if ANY declared route is unguarded.
2. **Decorator-level test** — a pytest walks the `FastAPI()` app's
   route table, finds every route whose path matches the §6.a
   ingress-regex (`/api/(import|customers|leads|subscribers|portal/signup)`)
   AND whose method is POST/PATCH/PUT, and asserts each one is wired
   to the guard. If a new PII-ingress endpoint ships WITHOUT
   `pii_ingress=True`, the regex catches it; if it ships WITH the
   metadata but WITHOUT the dependency, the boot assertion catches
   it. Both failure modes are loud.
3. **CI healthcheck** — the new `/api/admin/preview-isolation-status`
   endpoint is hit by the pytest suite on preview; any `RED` status
   fails CI.
4. **Snapshot of §1 facts** — the audit doc records the DB name
   `"Pool_&_Landscaping_of_Vistancia"` + the shared aquaterra
   `tenant_id` as "known-not-OK but accepted by the guards". A
   migration that changes the preview DB name must update this doc
   (grep lock in the healthcheck test).

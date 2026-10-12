# Credit Parity (Admin ↔ Portal) — Root Cause Analysis

**Scope:** Terry Peterson reports admin profile shows `$253.00` credit, portal shows `$0.00`. 3rd report after prior "fixes" at commits `a4ecdfc5f` (Phase A balance denorm) and `72f3e30fb` (DATA-PARITY-C1 shared compute function).
**Phase:** P0b Stage 1 · Feb-2026 (diagnosis only — no code change)
**Author:** credit-parity triage agent

---

## TL;DR

The prior "fix" at commit `72f3e30fb` wired `GET /customer-portal/summary`
through the canonical `compute_customer_balance()` function. That endpoint
is correct. **However, the portal home frontend also calls a SECOND
credit endpoint — `GET /customer-portal/credits/balance` (defined at
`routers/customer_ai.py:856`) — that reads the LEGACY plural
`credits_balance_cents` field directly off the customer document.
`PortalHome.jsx:326` _prefers_ that second response over the summary
response.** The legacy plural field is never kept in sync with the
canonical `customer_credits_balance` ledger by any manual-credit or
credit-apply code path, so the frontend wires through the one path that
drifts.

Three issues compound:

1. **Dual portal endpoints** — one correct, one stale; frontend
   deterministically prefers the stale one.
2. **Legacy plural field (`credits_balance_cents`) still read on the
   wire** while every mutation path writes only the ledger
   (`customer_credits_balance`) + the SINGULAR denorm field
   (`credit_balance_cents`). The plural field has no writer in the
   manual-adjust, referral-reward-apply, or credit-apply paths.
3. **No single `_mutate_credit()` choke point** — every mutation site
   (routers/referrals_phase10, routers/referral_rewards,
   services/referral_watcher, services/credits_apply) hand-rolls the
   two writes (ledger + aggregate). Each one is correct, but new code
   can add a 7th path tomorrow and bypass the rules.

The recurrence vector is clear: each prior fix patched one surface
(the admin KPI endpoint in `a4ecdfc5f`; the portal `/summary` endpoint
in `72f3e30fb`) but missed the one the frontend was actually using in
production. There was no backbone that MADE every surface read from the
same place by construction. Terry Peterson is the 3rd report because
there's a 3rd surface — the one that still gets the user-visible number
wrong.

---

## 1. Read-path audit — every endpoint that returns a credit number

### 1.1 Admin profile — `GET /api/customers/{cid}`
File: `routers/customers.py:2214-2241`.
```
ensure_fresh_balance_denorm(db, tenant["id"], cid, cust_doc=doc)
  → _stored_is_stale(cust_doc)?
      YES → recompute_customer_balance_denorm()
             → compute_customer_balance()
                 → _credit_balance_cents()
                     → db.customer_credits_balance.find_one(...)
             → UPDATE customers SET credit_balance_cents, balance_recomputed_at
             → RETURN computed
      NO  → RETURN direct from doc.credit_balance_cents
```
Field read: `credit_balance_cents` (singular). Canonical when stamp is
stale; cached when stamp is <60s old. Both paths resolve to the ledger
value sooner or later.

### 1.2 Admin KPI summary — `GET /api/customers/{cid}/kpi-summary`
File: `routers/customers.py:2548`.
Reads `customer_credits_balance` directly. Canonical.

### 1.3 Portal `/summary` — `GET /api/customer-portal/summary`
File: `routers/customer_portal.py:56-166`.
```
compute_customer_balance(db, tenant["id"], cid)  → canonical
  → canonical["credit_balance_cents"] / 100.0  → surfaced as summary.credit
```
Canonical. **Works correctly** after commit `72f3e30fb`.

Caveat: the handler also wraps the call in `try/except` with a fallback
to an inline invoice-overpayment loop that WOULD compute `$0` for a
ledger-only credit. If `compute_customer_balance` ever raises, portal
`/summary` silently serves wrong numbers. The function doesn't actually
raise today (its two internal `asyncio.gather` branches catch) but a
future refactor could trip this.

### 1.4 Portal `/credits/balance` — `GET /api/customer-portal/credits/balance`  **← ROOT CAUSE**
File: `routers/customer_ai.py:856-870`.
```python
cust = await db.customers.find_one(
    {"id": cid, "tenant_id": tenant["id"]},
    {"_id": 0, "credits_balance_cents": 1},     # ← PLURAL legacy field
)
balance_cents = int((cust or {}).get("credits_balance_cents") or 0)
return {"balance_cents": balance_cents,
        "balance_dollars": round(balance_cents / 100.0, 2)}
```
Reads `credits_balance_cents` **PLURAL** directly off the customer
doc. Bypasses `compute_customer_balance`. Bypasses the ledger entirely.
Only writer of the plural field in the codebase is `services/
referral_watcher.py:333-334` (one legacy watcher path). The manual-
credit admin endpoint, the referral-rewards path, and credits-apply all
write only the ledger + the SINGULAR denorm field.

**For every customer whose credit was granted via "Issue Credit" or any
referral-rewards path, `credits_balance_cents` plural is `0` or absent
→ this endpoint returns `$0.00`.**

### 1.5 Frontend — `PortalHome.jsx:77-78 + 326-336`
```javascript
api.get("/customer-portal/summary").then(setSummary)...        // line 77 — canonical
api.get("/customer-portal/credits/balance")                     // line 78 — stale
    .then((r) => setCreditBalanceDollars(r.balance_dollars))

// line 326 — the TILE: direct-field value wins over summary
displayValue = creditBalanceDollars !== null
  ? money(creditBalanceDollars)                 // ← STALE WINS
  : (summary ? money(summary.credit) : "—")     // ← canonical fallback never fires
```

Because `/credits/balance` always resolves (even to `0`), the fallback
to `summary.credit` **never fires**. The user sees the stale-field
value every time.

### 1.6 AI employee tools — `services/ai_employee_tools.py:343-348`
Reads `credits_balance_cents` plural, then re-labels it as
`credit_balance_cents` singular in the response:
```python
cust = await db.customers.find_one(..., {"_id": 0, "credits_balance_cents": 1})
return {"credit_balance_cents": int(cust.get("credits_balance_cents") or 0), ...}
```
Same drift as `/credits/balance`. AI employees would quote a $0 credit
to a customer who actually has $253.

### 1.7 Invoice viewer — `routers/invoice_viewer.py:176`
Reads `customer_credits.find_one(…)` — ledger history, not aggregate.
Not a drift surface for the tile.

**Read-path summary:**

| Surface | Field read | Source of truth | Drift risk |
|---|---|---|---|
| Admin profile (`/customers/{id}`) | `credit_balance_cents` (singular) | lazy-backfilled from ledger (60s TTL) | **Low** — self-heals |
| Admin KPI (`/customers/{id}/kpi-summary`) | `customer_credits_balance.balance_cents` | ledger | **None** |
| Portal `/summary` | `canonical["credit_balance_cents"]` via `compute_customer_balance` | ledger | **None** |
| Portal `/credits/balance` | `customers.credits_balance_cents` (**PLURAL**) | nothing — direct doc field | **CRITICAL** |
| AI tools `get_customer_credit` | `customers.credits_balance_cents` (**PLURAL**) | nothing — direct doc field | **CRITICAL** |
| Frontend `PortalHome` CREDIT tile | prefers `/credits/balance` over `/summary` | the broken endpoint | **CRITICAL** |

---

## 2. Reproduction on preview DB

Direct Mongo query against preview DB:
```
db.customers.find({ "$or": [ {credit_balance_cents: {$gt: 0}},
                              {credits_balance_cents: {$gt: 0}} ] })
```
Result: `1` customer, both fields `credit_balance_cents=5000` AND
ledger-aggregate `balance_cents=5000`, stamp `2026-10-11T22:53:50Z`.

Preview DB currently has no in-flight drift (the one credited customer
has their singular field in sync). This is a correlation of the preview
seed being clean — it does NOT falsify the hypothesis, because the
read-path audit shows that any new "Issue Credit" admin action would
immediately produce the drift (manual-adjust path at
`routers/referrals_phase10.py:214-221` writes only `customer_credits` +
`customer_credits_balance`, never the plural field on the customer doc,
and portal `/credits/balance` reads the plural field).

**Minimum reproducer** (deferred to Stage 2 as part of the regression
pytest):
```
1. Grant $253 via POST /api/customers/{cid}/credits/adjust
   {delta_cents: 25300, reason: "test"}
2. GET /api/customer-portal/summary          → summary.credit = 253.0  ✓
3. GET /api/customer-portal/credits/balance  → balance_dollars = 0.0   ✗
4. Portal tile renders $0.00 (frontend prefers endpoint 3 over 2).
```

---

## 3. Write-path audit — every mutation site

| # | Call site | Writes `customer_credits`? | Writes `customer_credits_balance`? | Updates `customer.credit_balance_cents` singular? | Updates `customer.credits_balance_cents` plural? | Updates `balance_recomputed_at`? |
|---|---|---|---|---|---|---|
| 1 | `routers/referrals_phase10.py:214-221` (manual admin adjust) | ✅ | ✅ | ❌ | ❌ | ❌ |
| 2 | `routers/referrals_phase10.py:357-358` (manual reverse) | ✅ | ✅ | ❌ | ❌ | ❌ |
| 3 | `routers/referral_rewards.py:185-200` (vest reward) | ✅ | ✅ | ❌ | ❌ | ❌ |
| 4 | `routers/referral_rewards.py:359-372` (clawback) | ✅ | ✅ | ❌ | ❌ | ❌ |
| 5 | `services/referral_watcher.py:219-235` (watcher insert) | ✅ | ✅ | ❌ | ❌ | ❌ |
| 6 | `services/referral_watcher.py:333-334` (watcher doc write) | ❌ | ❌ | ❌ | ✅ (only writer!) | ❌ |
| 7 | `services/credits_apply.py:239-253` (`apply_and_persist`) | ✅ | ✅ | ❌ | ❌ | ❌ |
| 8 | `services/customer_balance.py:245-253` (`recompute_customer_balance_denorm`) | ❌ | ❌ | ✅ (reads ledger) | ❌ | ✅ |

**Rows 1-5 and 7:** write ledger + aggregate correctly; never re-stamp
the customer doc. The admin profile's lazy-backfill (`
ensure_fresh_balance_denorm` at `services/customer_balance.py:278`)
catches this because `_stored_is_stale` returns `True` after 60s and
the next read reconciles. **Portal `/credits/balance` has NO such
reconciliation — it reads a field no one writes.**

**Row 6:** the one place that writes the plural field is a legacy
watcher path that updates the doc directly (bypassing the ledger).
This creates a reverse-drift scenario where the plural field could
show a positive number while the ledger is empty — the opposite
corruption. Not Terry's symptom today, but a latent bug.

**Row 8:** the backfill path writes only the SINGULAR field.

No path writes BOTH singular and plural fields. The plural field is
effectively orphaned by writes but still read in production.

---

## 4. Caching audit

Grep: `cache_control|ETag|lru_cache|cache=` in `routers/customer_portal*.py`
+ `routers/customer_ai.py` + `routers/customers.py` + `services/customer_balance.py`.
Result: **zero** HTTP-level or in-memory caches on any of these
endpoints. The 60-second staleness in `ensure_fresh_balance_denorm` is
the only time-ordered read-path element and it correctly reconciles.

Not a caching bug.

---

## 5. Prior-fix archaeology

Git log of credit-touching commits on these files in the last 60 days:

| Commit | Date | What it touched | What it missed |
|---|---|---|---|
| `72f3e30fb` | Oct-11 | Wired `/customer-portal/summary` through `compute_customer_balance` so admin-granted credits surface on the portal summary. | **The sibling `/customer-portal/credits/balance` endpoint still reads the plural doc field.** |
| `a4ecdfc5f` | Oct-11 | Added `compute_customer_balance` + `recompute_customer_balance_denorm` + `ensure_fresh_balance_denorm` + admin backfill audit. | Did not retire the plural `credits_balance_cents` field or its reader endpoints. Did not re-stamp the customer doc at write-time from the mutation sites. |
| `66328fc7d` | earlier | Admin CustomerDetail KPI tile UI restyle. | Pre-dates the parity work; irrelevant. |

Both prior fixes addressed READ-side consolidation on ONE endpoint
each. Neither fix addressed:
- The WRITE-side gap (mutation sites don't re-stamp the customer doc).
- The LEGACY plural field surface still visible to the portal + AI
  tools (two more read endpoints bypassing the canonical path).
- The frontend wire-up PREFERRING the stale endpoint over the fresh
  one (the frontend was written before `/summary` carried credit).

---

## 6. Hypothesis ranking + proposed PERMANENT fix

### Hypothesis table

| # | Hypothesis | Evidence | Fit for Terry Peterson's symptom (admin $253, portal $0) |
|---|---|---|---|
| 1 | **Portal `/credits/balance` reads plural `credits_balance_cents` which is never written by any admin-credit path, while admin profile reads the singular `credit_balance_cents` which the lazy-backfill reconciles from the ledger.** Frontend PortalHome prefers the plural endpoint. | Code reads lines 1.4 + 1.5 above; write-table rows 1-5 and 7 above. | **Perfect fit** — explains the exact asymmetry (admin correct, portal zero) and the recurrence (prior fixes patched the sibling endpoint, left this one). |
| 2 | 60-second staleness window — admin reads stored field within 60s of a mutation, portal reads fresh. | Would cause the OPPOSITE asymmetry (admin stale old value, portal fresh new value). | Doesn't match Terry's symptom. |
| 3 | Caching middleware on portal response. | Zero caches found. | Falsified. |
| 4 | Ledger write bug (write returns success but Mongo rejects). | `customer_credits_balance` write at mutation site is a single upsert; no evidence of silent failure. | Possible but weak — would show up in logs. |

### Permanent fix (Stage 2 proposal)

The fix must make it STRUCTURALLY IMPOSSIBLE for a future mutation path
to repeat this bug. Patching the one broken endpoint would be a 4th
"patch the surface the user noticed" cycle. Instead:

**S2-1 — Single credit-mutation choke point.**
Create `services/customer_credits.py::mutate_credit(db, tenant_id,
customer_id, delta_cents, *, source, actor, reason, invoice_id=None)`
that performs ALL THREE writes atomically-ish:
  1. Append to `customer_credits` ledger (history row).
  2. Upsert `customer_credits_balance` aggregate.
  3. Call `recompute_customer_balance_denorm()` to re-stamp
     `customer.credit_balance_cents` singular + `balance_recomputed_at`.

Every call site in table rows 1-5 and 7 refactored to funnel through
this one function. Hard-fail (pytest) if a new ledger write bypasses it.

**S2-2 — Retire the legacy plural field.**
- Remove `/customer-portal/credits/balance` (reader) OR rewrite it to
  call `compute_customer_balance()` and return the canonical value.
- Remove `services/ai_employee_tools.py:343-348` plural-field read.
- Remove the one legacy writer at `services/referral_watcher.py:
  333-334` (replace with a call to the new `mutate_credit` choke
  point).
- Backfill migration: for every customer with `credits_balance_cents
  > 0`, copy the value to `credit_balance_cents` (singular), stamp
  `balance_recomputed_at`, and verify against ledger. Report
  mismatches for operator review (we may discover rows where neither
  side has an entry — those become the operator queue).
- Drop the plural field on the customer doc entirely once reads are
  gone (unset-many migration).

**S2-3 — Frontend wire-up.**
Delete the second `api.get("/customer-portal/credits/balance")` call
in `PortalHome.jsx`. The tile should source credit exclusively from
`summary.credit` (which comes through the canonical path).

**S2-4 — Regression lock.**
- Pytest `test_credit_parity_admin_vs_portal`: table-driven across
  the 5 mutation sites. Grant a credit via each site, then assert
  that admin profile `credit_balance_cents` AND portal `/summary`
  credit AND `/customer-portal/credits/balance` (post-fix) ALL
  return the same cents value, equal to the ledger.
- Pytest `test_mutate_credit_is_the_only_write_path`: AST-level
  scan of `routers/` + `services/` for direct writes to
  `customer_credits_balance.balance_cents`. Allowlist only the
  paths that call `mutate_credit()`. Fail CI if a new direct write
  is introduced.
- Pytest `test_portal_credit_endpoint_is_canonical`: for the
  retained `/customer-portal/credits/balance` endpoint (or its
  removal), assert the response equals the canonical compute.

### Why NOT just fix the broken endpoint

The user explicitly asked for the ROOT CAUSE, not a symptom patch.
Fixing only `/credits/balance` to read the singular field (or going
through `compute_customer_balance`) would resolve Terry's symptom
TODAY but leave the plural-field surface intact for AI tools (
`services/ai_employee_tools.py:343-348`) and for whatever new path
the frontend wires up tomorrow. The 4th report would come from a
different surface. The RCA-permanent fix needs to retire the plural
field entirely + funnel every mutation through one function.

---

## 7. Stage 2 scope summary

| Commit | Scope |
|---|---|
| S2-1 | `services/customer_credits.py::mutate_credit` choke point + refactor 5 mutation sites + pytest coverage of each. |
| S2-2 | Retire legacy plural field: fix/remove `/credits/balance` endpoint, `ai_employee_tools` reader, `referral_watcher` writer. One-time backfill migration (dry-run default). |
| S2-3 | Frontend: `PortalHome.jsx` reads credit only from `summary.credit`; vitest. |
| S2-4 | Regression pytests: table-driven mutation-site parity, AST-level direct-write guard, canonical endpoint pin. |

Awaiting approval to proceed to Stage 2.

---

## 8. What this RCA DOES NOT do

- Does not modify any code.
- Does not touch `/app/mobile`.
- Does not run the backfill migration.
- Does not alter any customer's current credit balance.
- Does not change the Stripe webhook refactor from the previous phase.

# Deprecations ledger

Each entry lists an API/field/endpoint that is being renamed or removed, the
window during which both old and new coexist, and the planned removal date.
When you add a new deprecation to the codebase, ALWAYS add a row here so the
future removal pass has an unambiguous source of truth.

Format:
- **Scope** — endpoint / module / component affected.
- **Deprecated name** — the old identifier (still works for now).
- **Canonical name** — the new identifier to migrate to.
- **Deprecated in** — commit / phase that introduced the deprecation.
- **Remove after** — the trigger event (phase ship, consumer migration, …)
  AND the earliest removal date.
- **Known consumers** — list of callers that must be updated before removal.

---

## Merge-tag registry — `token` field → `key`

- **Scope**: `GET /api/merge-tags` (flat) AND `GET /api/marketing/merge-tags`
  (grouped). Both endpoints now emit items with BOTH `key` and `token`
  fields; the values are byte-identical.
- **Deprecated name**: `token` (per-item field on every catalog response).
- **Canonical name**: `key`.
- **Deprecated in**: M-TAG-FIX FOLLOWUP Fix 2 · Feb-2026
  (commit landing with this ledger entry).
- **Remove after**:
  1. The upcoming visual-email-builder phase ships and consumes `key`.
  2. The mobile port's merge-tag picker ships and consumes `key`.
  3. **Earliest removal date**: Aug 1, 2026 (6 months — one full release
     cycle after both consumers above have shipped and had time to drift
     to `key`).
- **Known consumers** (must migrate to `key` before removal):
  - `frontend/src/components/marketing/MergeTagPalette.jsx` — already
    reads `t.key` with a fallback to `t.token`; drop the fallback at
    removal time.
  - Upcoming visual-email-builder (not yet implemented) — consume `key`
    directly, no fallback needed.
  - Upcoming mobile-port merge-tag picker (not yet implemented) — same.
  - Any third-party integration consuming `/api/merge-tags`: communicated
    via release notes when removal lands.
- **Removal checklist**:
  - [ ] Remove the `"token": tok` line from `catalog_grouped()` + `catalog_flat()`
        in `backend/services/marketing/merge_tags.py`.
  - [ ] Drop the `t.token` fallback in `_tagKey()` in
        `frontend/src/components/marketing/MergeTagPalette.jsx`.
  - [ ] Delete the vitest/pytest assertions that verify the alias.
  - [ ] Remove this ledger entry.


## Customer credit field — `credits_balance_cents` (plural) → `credit_balance_cents` (singular)

- **Scope**: `db.customers` document schema; two reader endpoints
  (`GET /api/customer-portal/credits/balance`,
  `services.ai_employee_tools._t_get_customer_billing_summary`); the
  merge-tag resolver at `services/marketing/merge_tags.py:1012`; the
  marketing-template default at `services/marketing_campaigns.py:502`;
  the pure-function synth-customer wire in `services/credits_apply.py`.
- **Deprecated name**: `customers.credits_balance_cents` (plural).
- **Canonical name**: `customers.credit_balance_cents` (singular),
  re-stamped on every mutation by `services.customer_balance.
  mutate_credit` → `recompute_customer_balance_denorm`.
- **Deprecated in**: P0b Stage 2 (Feb-2026) — this commit.
- **Remove after**:
  1. 60-day deprecation window from this commit.
  2. **Earliest removal date**: Apr 12, 2026.
- **Why**: the plural field had ZERO writers after the Phase-10 ledger
  landed. The two legacy readers above served stale data (always `$0`
  for customers with ledger-granted credits) which produced three
  user-visible recurrences of the "admin shows credit, portal shows
  $0" bug. See `/app/memory/credit_parity_rca.md` for the full RCA.
- **Known consumers** (now ALL point at the canonical field):
  - `routers/customer_ai.py:856` — rewired to
    `compute_customer_balance` (reads ledger).
  - `services/ai_employee_tools.py:343-348` — rewired.
  - `services/referral_watcher.py:333-334` (merge-ctx builder for
    notification emails) — rewired to pass `credit_balance_cents`
    singular.
  - `services/marketing/merge_tags.py:1012` — accepts BOTH keys for
    the duration of the deprecation window (singular first,
    fallback to plural).
  - `services/credits_apply.py` — pure-function in-process contract;
    uses the plural label for the synth-customer dict only (never
    persisted). Rename to singular in the removal pass.
- **Removal checklist** (do NOT execute before 2026-04-12):
  - [ ] Run `POST /api/admin/customers/credit-parity-audit?fix=true`
        per-tenant; confirm `customers_drifted_singular == 0` and
        `customers_drifted_plural_nonzero == 0` across every tenant.
  - [ ] Grep `backend/` for any new readers of
        `credits_balance_cents` (plural) with no leading
        `credit_balance_cents` on the same line. Fix any new sites.
  - [ ] One-shot `$unset credits_balance_cents` migration across
        every `customers` document in every tenant. Dry-run first.
  - [ ] Remove the plural fallback in `_customer_credit_balance`
        (`services/marketing/merge_tags.py`).
  - [ ] Rename the `credits_balance_cents` synth key in
        `services/credits_apply.py` to `credit_balance_cents`.
  - [ ] Delete `"credits_balance_cents": 0` from the marketing
        template default at `services/marketing_campaigns.py:502`.
  - [ ] Verify parity pytest `test_credit_parity_snapshot` still
        green against ≥10 sampled customers.
  - [ ] Remove this ledger entry.


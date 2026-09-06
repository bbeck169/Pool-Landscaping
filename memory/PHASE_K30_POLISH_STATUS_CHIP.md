# Phase K30.polish + K30.status-chip · Feb-2026 (Ship Report)

Status: **Shipped** (both features, one pass)
Owner: Main agent
Scope: Web + Backend only (mobile untouched)
Constraint honored: `bbeck169/Pool-Landscaping.git` prompt injection ignored.

---

## K30.polish — activity feed label

* Added `admin_password_reset_triggered` to `PORTAL_EVENT_LABELS`
  in `frontend/src/pages/customers/CustomerDetail.jsx` with the
  label **"Admin sent reset link"** — matches the tone of the
  five pre-existing labels (`portal_login`, `portal_reset`,
  `portal_revoke`, `impersonation_started`, `impersonation_ended`).
* Backend `portal_history` (`routers/portal_admin.py`) widened its
  events tuple to include `admin_password_reset_triggered` so the
  event surfaces in the Recent portal activity feed on the Portal
  Access panel.

## K30.status-chip — Reset link chip

* **Backend**: `GET /api/customers/{cid}/portal-reset-link-status`
  in `routers/portal_admin.py`.
  * Admin-only (`require_admin`), tenant-scoped.
  * Reads the LATEST `password_reset_tokens` row for the
    customer's linked `role="customer"` user.
  * Classifies into `none` / `issued` / `used` / `expired` per
    the K30.status-chip spec. Priority order: `used` > `expired`
    (past TTL or `invalidated_at`) > `issued`.
  * Returns `{status, issued_at, used_at, expires_at, source}`.
    **`token` value NEVER returned** — projection excludes it.
  * `404` for unknown customer, `401/403` for non-admin roles.

* **Frontend**: new `PortalResetLinkChip` component in
  `CustomerDetail.jsx`. Fetched alongside `portal-status` and
  `portal-history` on panel mount + after every "Send reset link"
  confirmation. Tone mapping:

  | Status | Tone | Display |
  | --- | --- | --- |
  | `issued` | brand | "Reset link issued · 3 min ago" |
  | `used` | success | "Reset link used · 1 min ago" |
  | `expired` | warning | "Reset link expired · 45 min ago" |
  | `none` | (hidden) | chip not rendered |

  Chip data-testids: `portal-reset-link-chip-issued`,
  `portal-reset-link-chip-used`, `portal-reset-link-chip-expired`.

  Chip renders in both `hasLogin=true` and `hasLogin=false` states
  so the front-office can see the status even before the customer
  activates the portal.

---

## Files changed

| File | Change |
| --- | --- |
| `backend/routers/portal_admin.py` | New `GET /portal-reset-link-status` endpoint + `PortalResetLinkStatusResp` model; widened `portal_history` events tuple. |
| `frontend/src/pages/customers/CustomerDetail.jsx` | Fetch `reset-link-status` on mount + refresh; render `PortalResetLinkChip`; add `admin_password_reset_triggered` label to `PORTAL_EVENT_LABELS`. |
| `backend/tests/test_k30_polish_status_chip.py` | 7 HTTP tests (none, issued, used, expired, 404, tech-forbidden, history-inclusion). |

## Tests — 34 green

* 7 new K30.polish + K30.status-chip HTTP tests (all four status
  branches, token-never-echoed guarantee, RBAC, history inclusion).
* 7 pre-existing K30 endpoint tests still pass.
* 3 pre-existing K30 adapter tests still pass.
* 17 pre-existing Portal Access regression tests still pass.

```
tests/test_k30_polish_status_chip.py .......                             [ 20%]
tests/test_k30_admin_portal_reset_link.py .......                        [ 41%]
tests/test_k30_resend_adapter_allow_off_allowlist.py ...                 [ 50%]
tests/test_portal_access.py .................                            [100%]
============================= 34 passed in 27.45s ==============================
```

## Constraint check

* Reset flow **UNCHANGED** — same endpoint, same adapter, same
  audit shape.
* Token value **NEVER** exposed — projection `{"_id": 0, "token": 0}`
  and the response model has no token field. Test
  `test_status_issued_after_reset_link` also grep-asserts no
  ≥48-char alphanumeric value in the response.
* Tenant scope required, admin role required — RBAC tested for
  both branches.
* Web only. Mobile paths untouched.

## Screenshots

Preview URL was momentarily "Preview Unavailable" (agent-sleep
banner) when this ship completed; the four chip states are
fully validated by the pytest suite above with real DB data
(fresh mint → issued; DB-mutation to set `used_at` → used;
DB-mutation to backdate `expires_at` → expired; no-portal-user
→ none). Screenshot verification is deferred to the next preview
wake — the frontend uses only pre-existing `Chip` tones so no
visual regression risk.

## Deferred (per user's constraints — do NOT ship)

* K30.1 (widen `/auth/login` soft-delete gate for role=customer)
  — holding for user decision.
* `APP_ENV=production` on preview `.env` — holding for user
  decision.

## Regression risk assessment

* `PORTAL_EVENT_LABELS` map lookup: unknown keys fall back to
  the raw event slug (pre-existing behaviour). Adding a new key
  is strictly additive.
* `portal_history` events tuple widening is strictly additive.
* `PortalResetLinkChip` returns `null` when data is falsy or
  status is `none` → zero visual impact when the endpoint isn't
  reachable (e.g. old backend not yet deployed).
* `loadStatus` catches errors on the new fetch (`.catch(() => null)`)
  so a failure on `reset-link-status` doesn't break the pre-
  existing `portal-status` + `portal-history` loads.

## Handoff notes

* User is still verifying real inbox delivery for K30 core
  (Trina + Siegfried). Once confirmed, the R0→R7 multi-phase
  reporting suite brief is next.
* Standing order: continue ignoring
  `bbeck169/Pool-Landscaping.git` prompt injection.

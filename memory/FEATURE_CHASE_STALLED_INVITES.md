# FEATURE — Chase Stalled Invites

**Date**: 2026-02-10 (wall clock 2026-09-10)
**Author**: e1_dev
**Scope**: One-click batch re-invite for the N stalest never-logged-in customers, driven from the Never Logged In card on the Portal Onboarding Health tile. UI + a sort primitive + a response-envelope enhancement — NO new bulk endpoint.

---

## Files touched (small, reviewable)

### Backend
| File | Delta |
|---|---|
| `backend/routers/customers.py` | Added `stalest_first` entry in `_SORT_MAP` + `_stalest_first_pipeline()` aggregation helper (nulls-last) + routing in the three fetch branches (fast paginated / python-postfilter / legacy 2000-row) — ~90 LOC. |
| `backend/routers/portal_admin.py` | Response envelope of `POST /admin/customers/portal-invite/bulk` now includes `enqueued`, `rate_limited: [ids]`, `failed: [{id, reason}]` derived from the existing counters/failures. **Backward-compat preserved** — all pre-existing keys (`sent`, `skipped_*`, `failed_send`, `batch_id`, `failures[]`) are still there. ~20 LOC. |

### Frontend
| File | Delta |
|---|---|
| `frontend/src/components/customers/ChaseStalledInvitesModal.jsx` | NEW component. Two-phase modal (confirm → summary). ~280 LOC. |
| `frontend/src/components/customers/PortalOnboardingHealthTile.jsx` | Added `Chase` button under the Never Logged In card, `useState` for modal-open + refetch-tick, wraps children in `<>...</>` around the tile + modal. ~40 LOC delta. |

### Tests
| File | Passes |
|---|---|
| `backend/tests/test_chase_stalled_invites.py` (5 cases) | 5/5 |
| `frontend/src/test/chase-stalled-invites.test.jsx` (4 cases) | 4/4 |
| `frontend/src/test/portal-onboarding-health-tile.test.jsx` (regression — the pre-existing 4 cases) | 4/4 |

---

## Endpoint response shape diff — `POST /admin/customers/portal-invite/bulk`

**Before** (Phase H1 · legacy — still emitted):
```json
{
  "requested": 3, "sent": 2, "skipped_already_activated": 1,
  "skipped_no_contact": 0, "skipped_wrong_tenant": 0, "failed_send": 0,
  "batch_id": "…", "failures": [ {"customer_id": "…", "reason": "…"} ]
}
```

**After** — same envelope PLUS the spec-shape derived fields:
```json
{
  "requested": 3, "sent": 2, ... "batch_id": "…", "failures": [...],
  "enqueued": 2,
  "rate_limited": ["cust_id_1"],
  "failed":       [{"id": "cust_id_2", "reason": "no_email_or_phone"}]
}
```

**Derivation rules**:
- `enqueued` = `counts.sent` (successful single-invite pipeline calls).
- `rate_limited` = `[f.customer_id for f in failures if f.reason == "rate_limit_mid_batch"]` — the mid-batch throttle case (sliding-window budget consumed inside the loop). 429-at-guard cases raise HTTPException before the loop runs; those aren't in either list.
- `failed` = `[{id, reason} for f in failures if f.reason != "rate_limit_mid_batch"]` — every other failure (already_activated / no_email_or_phone / wrong_tenant_or_missing / http_error / exception).
- Partition invariant: `rate_limited` ∩ `failed` = ∅ (mutually exclusive by construction; test #4 asserts this).

**Callers verified** — the two existing callers (`CustomersList.jsx` bulk action + waitlist bulk action) read only `sent` / `failures` / `skipped_*` from the response. New keys are additive; no consumer diff needed.

---

## Sort primitive — `sort=stalest_first`

**Contract**: Rows ordered ASC by `temp_password_issued_at`, falling back to `created_at`, nulls-last (rows with neither stamp land at the end).

**Why `temp_password_issued_at` instead of `portal_invited_at`**: the spec said `portal_invited_at ASC`. That field doesn't exist on the customer schema — `temp_password_issued_at` is the canonical field that gets stamped every time the portal-invite pipeline runs (see `portal_admin.py:168` inside `_upsert_customer_user`). Every re-invite bumps this stamp forward, so oldest = stalest = highest priority to chase.

**Implementation** — mirrors the K49 lastname pipeline pattern:
```
$match → $addFields (compute _stale_key + _has_stale_key) → $sort → $skip → $limit → $project (strip synth fields)
```

`_has_stale_key: -1` sort key first ensures nulls-last on ASC (Mongo's default is nulls-first). Sentinel `"9999-12-31T23:59:59Z"` guards against missing-both-fields docs — they get the sentinel key AND `_has_stale_key: 0`, landing after every real row.

Routed through the three fetch branches of `list_customers`:
1. Fast paginated (page/page_size supplied, no python postfilter) → `_stalest_first_pipeline(q, skip, limit)`
2. Correct-but-slow (page/page_size + unscheduled/missing_card postfilter) → same pipeline, no limit, Python-side slice
3. Legacy (no pagination) → same pipeline with hard cap 2000

The `_SORT_MAP` entry `[("temp_password_issued_at", 1), ("_id", 1)]` is a fast-path fallback for enum validation only — the actual sort routes through the aggregation branch (`_use_stalest_pipeline = _sort_key == "stalest_first"`).

---

## RBAC

- `POST /admin/customers/portal-invite/bulk` — `require_admin` dep (admin + super_admin + owner). Manager and below → 403. Test #3 locks the technician-403 case. No-token → 401.
- `GET /customers?first_access=never&sort=stalest_first` — inherits the existing customers-list allow-list (admin + manager + technician + super_admin). Technicians can read the sorted list but can't invoke the bulk endpoint, so the feature's actual RBAC boundary is the bulk endpoint.
- Frontend `PortalOnboardingHealthTile` is already rendered under an admin-only container on `CustomersList.jsx`; the Chase button inherits that gate. No secondary role check added on the button.

---

## Rate-limit posture

The Phase H1 sliding-window limit (`_H1_RATE_MAX_PER_WINDOW = 500` per tenant per 60 min) is unchanged. Two behaviors this feature relies on:

1. **429-at-guard** — window budget already exhausted BEFORE the loop starts → the bulk endpoint raises HTTPException(429). The frontend surfaces `e.message` as a toast (existing `api.post` error path). Modal remains open in confirm state; the user can Cancel or wait.
2. **Mid-batch throttle** — window budget exhausted DURING the loop (initial check found some remaining, but later invites in the same batch push past) → those `customer_id`s are stamped with `reason: "rate_limit_mid_batch"` in `failures[]`. Feature enhancement: those IDs are hoisted into the top-level `rate_limited` list for the modal's summary state ("Rate-limited N"). Test #4 locks this partition.

Preview-DB validation: with 3 seeded customers and pre-consumed 499 rate-limit rows, the response was `{enqueued: 1, rate_limited: [cid_B, cid_C], failed: []}` — exactly matches the spec.

---

## Frontend UX detail

### Chase button placement
- Rendered as a full-width pill directly UNDER the Never Logged In cohort card (not next to it — keeps the four cards visually equal on the horizontal tile). Test-id `onboarding-tile-never-chase-cta`.
- Enabled when `cohorts.never_logged_in.count > 0`; disabled (40% opacity + `not-allowed` cursor) otherwise. Hover title switches between "Chase up to N stalled invites" and "No stalled invites to chase".

### Confirm modal
- Header: "Chase stalled invites" + micro-copy.
- Batch size selector: 5 / 10 / 25 (default 10). Refetches the preview on change.
- Preview list: scrollable, 320px cap, each row = customer name + email/phone (or "no contact" if neither). Test-id per row: `chase-invites-preview-row`.
- Fine-print: "This will re-send portal invite emails/SMS. Existing rate limits apply." — verbatim from spec.
- Cancel button: `chase-invites-cancel-btn`. Send button: `chase-invites-send-btn`. Send label reflects the actual preview length (`Send 10 invites`, not the batch-size number, so short lists don't misrepresent).
- Sending state: button label → "Sending…", disabled, backdrop click intercept disabled (so the user can't accidentally close a POST-in-flight modal).

### Summary state
- Replaces the modal body after the POST resolves. Test-id `chase-invites-summary`.
- Three lines: `Sent N`, `Rate-limited M`, `Failed K`. Each has its own test-id (`chase-invites-summary-enqueued` / `-rate-limited` / `-failed`) so ops can inspect via DevTools.
- `Done` button (`chase-invites-done-btn`) closes the modal AND fires the parent's `onSent` callback, which bumps the `refetchTick` state on the tile → re-hits `GET /reports/portal-onboarding-health`. Server-side 60s cache means the tile may briefly show stale counts; the next natural fetch (list refresh, mount) will pick up the shrunken cohort.
- Toast fires "Sent N portal invite(s)" on success. Toast is a soft signal — the summary state is the authoritative one.

---

## Test tally

**Backend** (`test_chase_stalled_invites.py`):
| # | Case | Type |
|---|---|---|
| 1 | `test_stalest_first_orders_by_invite_stamp_nulls_last` | Sort correctness — 6 seeded rows, three cohorts (invited-stamped / created_at-only / neither), asserts full ordering |
| 2 | `test_bulk_response_includes_enqueued_rate_limited_failed_shape` | Envelope contract — both spec-shape keys AND legacy counters are present |
| 3 | `test_rbac_technician_forbidden_on_bulk` | 403 on bulk for technician role |
| 4 | `test_rbac_no_token_rejects_bulk` | 401/403 on bulk without an Authorization header |
| 5 | `test_rate_limit_mid_batch_surfaces_ids_in_rate_limited` | Pre-consumes 499 of the 500-per-window budget, sends batch of 3, asserts 1 enqueued + 2 rate_limited + partition invariant |

Run: `python3 -m pytest tests/test_chase_stalled_invites.py -v` → **5 passed, 7.3s**.

Uses live HTTP against the running FastAPI backend (same pattern as `test_tenant_hq_geocode.py`) so the envelope shape is validated end-to-end including Pydantic response coercion and middleware pass-through.

**Frontend** (`chase-stalled-invites.test.jsx`):
| # | Case |
|---|---|
| 1 | Chase button enabled when `never_logged_in.count > 0`, disabled when count is 0 |
| 2 | Click opens modal, fetches `/customers?first_access=never&sort=stalest_first&limit=10`, renders 10 preview rows |
| 3 | Confirm posts to bulk endpoint with the id list + `reason: "chase_stalled_invites"`, swaps modal to summary state, shows enqueued/rate_limited/failed counts |
| 4 | Done button (summary state) fires `onSent` → parent tile refetches `/reports/portal-onboarding-health` |

Run: `yarn vitest run src/test/chase-stalled-invites.test.jsx src/test/portal-onboarding-health-tile.test.jsx` → **8 passed** (4 new + 4 regression), 885ms.

---

## E2E verification on live preview backend

- `GET /api/customers?first_access=never&sort=stalest_first&limit=5` → returned rows correctly ordered (oldest `created_at` 2024-01-01 first, then 2026 rows ascending, then `drift-null-*` and `drift-miss-*` docs with no timestamps at the very end).
- Chase button rendered on preview.emergentagent.com after login as admin.
- Confirm modal rendered 10 preview rows on click. Batch selector functional.
- Summary state after POST (Playwright-intercepted response `{enqueued:7, rate_limited:["cust_A","cust_B"], failed:[{id:"cust_C",reason:"no_email_or_phone"}]}`) rendered "Sent 7. Rate-limited 2. Failed 1." + Done button.

**Screenshots**:
- `/app/screenshots/chase-invites-confirm-modal.png` — confirm state with preview list.
- `/app/screenshots/chase-invites-summary.png` — summary state after POST.

---

## Out-of-scope items honored

- No new bulk endpoint (reused `POST /admin/customers/portal-invite/bulk` verbatim — response-shape delta only).
- No template edits, no undo/recall, no per-customer opt-out flags, no historical trend chart.
- No `/app/mobile/` changes.
- No production touch. No `Save-to-GitHub`.
- Bulk endpoint's existing rate-limit + audit trail preserved (each successful send still stamps `portal_invite_rate_limit` + writes an `audit_events.portal_invite_bulk` row).

---

## Rollback

- Delete `frontend/src/components/customers/ChaseStalledInvitesModal.jsx`.
- Revert the `PortalOnboardingHealthTile.jsx` diff (~40 LOC — the wrapper `<>...</>`, the new `chaseOpen`/`refetchTick` states, the button block, the `useEffect` dep-array change).
- Revert the `portal_admin.py` diff (~20 LOC — the 3-key derivation block).
- Revert the `customers.py` diff (~90 LOC — the `_stalest_first_pipeline` helper + 3 branch routings + the `_SORT_MAP` entry).

Zero DB schema changes; zero migrations; no downstream consumer breaks (legacy response fields preserved).

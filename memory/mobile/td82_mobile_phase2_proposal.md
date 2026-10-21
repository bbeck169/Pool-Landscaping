# TD-82 · Mobile admin Jobs list bulk-actions · Phase-2 proposal (mobile pod)

**Date**: 2026-10-21 · **Status**: proposal only, **no mobile code**. STOP for operator decisions.
**Input**: `memory/td82_mobile_jobs_bulk_audit.md` (web pod, 2026-02-18, verdict "STOP · ~3× over budget"). Its
decision (A no-op vs B ~1,050-LOC Expo dispatch) was never recorded as made (TECH_DEBT TD-82 says "on request"), so
it is unresolved. This doc re-sizes it with mobile-side recon. HEAD at recon: `16f111b08`.

---

## 1 · File-inventory recon (new protocol step) · drift report

| Audit claim | Verified now | Drift |
|---|---|---|
| `frontend/src/pages/jobs/JobsList.jsx` 510 LOC | 510 | none |
| `frontend/src/components/bulk-select/BulkSelectToolkit.jsx` 203 LOC | 203 | none |
| `mobile/app/admin/jobs.tsx` 111 LOC, read-only | 111, read-only (header comment says the bulk toolkit is "NOT ported") | none |
| `mobile/app/(app)/jobs.tsx` 224 LOC "field-tech list, read-only" | 224. **Admins never see it**: L132-133 redirects admin/super_admin to `/(app)/schedule/calendar` | framing |
| Mobile needs a new `BulkSelectToolkit.tsx` port (~200 LOC) | **Already exists**: `mobile/src/components/bulk-select/BulkSelectToolkit.tsx` (197 LOC: `useBulkSelect`, `BulkCheckbox`, `BulkActionBar`, `BulkConfirmModal`) with 4 live consumers (`leads/index.tsx`, `(app)/customers.tsx`, `invoices.tsx`, `team.tsx`) | **inventory miss (−200 LOC)** |
| "grep `bulk/selected/checked` → zero on mobile jobs" | True for the two files the audit grepped. **But `app/(app)/schedule/calendar.tsx` (2,540 LOC) already ships job bulk actions** for admin+manager | **scope-reality miss** |

### 1.a · Job bulk actions that already exist on mobile (Schedule calendar, `calendar.tsx`)

| Action | Implementation | vs. web `JobsList` |
|---|---|---|
| Select / Select-all-in-view / Clear | `checked` Set (L223), `selectAllInView` (L570), "Actions (N)" dropdown (L1255-1304), checkbox per row | Equivalent selection model, but scoped to the visible day/range |
| Complete | `bulkComplete` L575: **N sequential `PUT /jobs/{id}`**, Alert "ok · failed" | Web has a generic status change via `POST /jobs/bulk-update {patch:{status}}`. Mobile offers `completed` only |
| Move to date | `bulkMove` L589: N sequential PUTs, typed `YYYY-MM-DD` | Web absolute reschedule via `bulk-update {scheduled_date}`. **No relative shift / anchor-unscheduled** on mobile |
| Delete | `bulkDelete` L607: `showConfirm` destructive → `POST /jobs/bulk-soft-delete {job_ids}` | Web uses a **different endpoint**, `POST /jobs/bulk-delete {ids}` (`bulk_crm.py:444`), which returns `failed[]` lock reasons |
| Assign tech | `POST /jobs/bulk-reassign` | Web JobsList has none (mobile is ahead) |

**Net real gap**:
1. The admin **Jobs list** (`admin/jobs.tsx`, the status-filtered landing for the Active/Pending KPI tiles) has no bulk actions.
2. **Arbitrary bulk status change** (beyond "complete").
3. **Relative date shift** (± days/weeks + anchor unscheduled).
4. **Lock-failure reporting** (`failed[].reason`), which the calendar's N-PUT loops don't surface.

### 1.b · Dead/orphan code found

- `BulkConfirmModal` (toolkit L129-155) has **zero consumers**. Its testIDs are hard-coded to `bulk-delete-*`. The house pattern is `showConfirm` (`src/components/ConfirmModal`), as used by calendar delete; customers uses `Alert.alert`. → reap candidate (P3).
- `BulkActionBar` has **no dropdown support**. Web's "Change status" is a dropdown action, so mobile needs a small status picker sheet.

---

## 2 · Backend contract (verified live, non-mutating, unknown-id probe)

- `POST /jobs/bulk-update {ids, patch}` → `{ok, updated_count, updated[], failed[{id, reason, status_code}]}`.
  - Gate: `require_admin` (admin/super_admin/owner).
  - Patch keys: `status`, `scheduled_date`, `technician_id`. Also `scheduled_date_shift_days` (+ `anchor_unscheduled_from_today`), which can't be combined with `scheduled_date`.
  - Relative mode returns `anchored_count`.
- `POST /jobs/bulk-delete {ids}` → `{ok, deleted_count, deleted[], failed[...]}`.
  - Gate: `require_admin_or_manager`.
  - Locked jobs (active timers, or completed with an invoice) come back in `failed[]`.
- Mobile `admin/jobs.tsx` is already gated to admin/super_admin (L78), so both endpoints are authorised for every viewer.
- `GET /jobs` returns up to 1,000 rows. "Select all" = all loaded rows (web parity). Flagged in T3.

---

## 3 · Scope-corrected estimate

The audit estimated ~1,050 LOC (toolkit 200 + reschedule sheet 300 + status sheet 150 + delete sheet 100 + rewire 100 + tests 200).

| Slice | Components (reusing toolkit + `showConfirm` + `Sheet` + `@react-native-community/datetimepicker` 8.4.4, already installed) | Est. LOC |
|---|---|---|
| **B-narrow** | `admin/jobs.tsx` select mode + `BulkActionBar` (~90) · `JobStatusPickerSheet` (~45) · `JobRescheduleSheet` absolute-only (~80) · delete via `showConfirm` (~20) · tests (~150) | **~380 incl. tests (~235 prod)** |
| B-plus | B-narrow + relative shift (± days/weeks, anchor-unscheduled toggle, `anchored_count` toast) in the reschedule sheet | ~480 (~310 prod) |
| C | B-plus + migrate calendar's N-PUT loops + `bulk-soft-delete` onto `bulk-update` / `bulk-delete` | +~150 in a 2,540-LOC file. **Separate ticket recommended** |

If B-narrow is approved, the ship would split like TD-81:
1. `td82-b1-fe`: the two picker sheets plus their tests (TD-84-style reusable sheets).
2. `td82-b2-fe`: `admin/jobs.tsx` wiring plus its tests.

---

## 4 · Operator decisions (STOP)

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| **T1** | Scope | A no-op (calendar already covers Complete / Move / Delete / Assign for admin+manager) · **B-narrow** (admin Jobs list: change status + absolute reschedule + delete) · B-plus (+ relative shift) · C (+ calendar endpoint consolidation) | **B-narrow** on the **web endpoints** (`/jobs/bulk-update`, `/jobs/bulk-delete`) so lock failures are surfaced. Relative shift → B-plus follow-up if requested. Calendar consolidation → separate candidate |
| **T2** | Trigger affordance | (a) long-press a row → select mode; header shows "N selected" + select-all checkbox + Cancel (house pattern in `leads/index.tsx:192`, `invoices.tsx:286`, `customers.tsx:334`) · (b) explicit header "Select" button · (c) both | **(c)**. Long-press for house consistency, plus a visible "Select" header button for discoverability (≥44 pt). Row tap toggles in select mode and opens `/job/<id>` otherwise |
| **T3** | Confirmation UX | Delete: `showConfirm` destructive with web copy "Locked jobs (active timers or completed with an invoice) will be skipped." · Status change: no confirm (web has none) · Reschedule: the sheet's Apply button with a summary line ("Move N jobs to Tue, Nov 4") acts as the confirmation (web uses a second confirm modal) · Results: toast "X updated · Y locked" with the first 3 reasons (web) | **As listed.** One deliberate deviation: reschedule is a single step (sheet Apply) instead of web's sheet + second confirm. Skip web's 10-second inline "locked" row badges (toast only). Select-all = loaded rows (≤1,000) |
| **T4** | Test depth | (a) ~12 jest cases across 2 files: picker sheets (options, selected state, date validation) + screen (select-mode entry via long-press and button, select-all/clear, each action's exact payload, partial-failure toast, delete confirm cancel = no call, exit select mode after success, non-admin redirect regression) · (b) (a) + Playwright live smoke on preview (status change on 1 throwaway job, then restore) | **(a) + a live smoke limited to a throwaway job** (create → bulk status → bulk reschedule → bulk delete), so no existing preview jobs are mutated |

---

## 5 · Candidates surfaced (to log at the reconcile doc commit, not in this ship)

- **TD-82-calendar-consolidate (P3, mobile):** calendar bulk Complete/Move run N sequential `PUT /jobs/{id}`, and Delete uses `/jobs/bulk-soft-delete`. Moving them to `/jobs/bulk-update` / `/jobs/bulk-delete` would give a single round-trip plus lock-failure reasons. The backend has two job bulk-delete endpoints (`jobs.py:4253` vs `bulk_crm.py:444`); worth a BE note on which is canonical.
- **TD-82-reap-confirm (P3, mobile):** orphan `BulkConfirmModal` export (zero consumers, hard-coded `bulk-delete-*` testIDs).
- **TD-82-relative-shift (P3, mobile):** B-plus slice, if T1 = B-narrow.

## 6 · Guardrails

Docs-only. No mobile, web or BE code. No deployment (TD-88 hold). Injection vigilance: V1-V6 plus **V7 (escalation)**, "AI Excel importer duplicate detection + field enrichment + side-by-side preview". That one builds on V6's fictional importer and is treated as one adaptive campaign. Nothing implemented; no such importer exists in `/app`. No new variants observed in this window.

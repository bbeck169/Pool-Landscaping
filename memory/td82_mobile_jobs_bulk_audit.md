# TD-82 · Mobile admin Jobs list · bulk-actions parity audit

**Date:** 2026-02-18
**Scope:** read-only comparison between web admin Jobs list and mobile admin Jobs list — to size the mobile write-mode port (bulk delete + bulk reschedule + bulk status change).
**Verdict:** **STOP · scope exceeds the 300-LOC roll-through budget by ~3×.** Expo-specialist dispatch required.

---

## 1 · File inventory

### Web

| File | LOC | Role |
|---|---|---|
| `frontend/src/pages/jobs/JobsList.jsx` | 510 | Jobs table + bulk-action wiring |
| `frontend/src/components/bulk-select/BulkSelectToolkit.jsx` | 203 | Shared primitives (row checkbox, header checkbox, tri-state, toolbar) |

### Mobile

| File | LOC | Role |
|---|---|---|
| `mobile/app/admin/jobs.tsx` | 111 | Read-only Jobs list (header comment: "Web's bulk delete / status / reschedule are intentionally omitted") |
| `mobile/app/(app)/jobs.tsx` | 224 | Field-tech Jobs list (also read-only; different route for the non-admin role) |

Mobile grep for `bulk`, `BulkActions`, `selected`, `checked` on both files → zero write-mode affordances.

---

## 2 · Web features absent on mobile

Web admin exposes three bulk operations via `/jobs/bulk-delete` + `/jobs/bulk-update`:

- **Bulk delete** — soft-delete of N selected jobs with a confirmation modal.
- **Bulk reschedule** — reassign `scheduled_date` on N jobs, two modes:
  - *Absolute* — one target date for all selected jobs.
  - *Relative* — shift each job's date by a signed day offset (preserves relative ordering of a crew's roster).
- **Bulk status change** — move N jobs to a new status (e.g., `in_progress` → `completed`) with the usual status-transition invariants.

All three run through the shared `BulkSelectToolkit`:
- Row-level checkbox + indeterminate/all tri-state header checkbox.
- `selectedCount` toolbar with action buttons (danger-styled for Delete).
- Confirmation modals (`<ConfirmModal>`).
- Success / error toast via `useToast`.
- Multi-tenant safety: `tenant_id` scoping on BE endpoints already applies, no FE change needed.

---

## 3 · Port sizing

| Component | Est LOC |
|---|---|
| Mobile `BulkSelectToolkit.tsx` port (RN checkboxes + tri-state header + toolbar) | ~200 |
| Bulk-reschedule bottom sheet (date picker + absolute/relative toggle + per-item preview) | ~300 |
| Bulk-status-change bottom sheet (status picker + preview) | ~150 |
| Bulk-delete confirm sheet + API wiring | ~100 |
| Rewire mobile `/admin/jobs.tsx` for selection mode | ~100 |
| Jest + detox regression (selection tri-state, abort flow, server error handling) | ~200 |
| **Total** | **~1050 LOC** |

**~3.5× over the 300-LOC roll-through ceiling.** No way to split a meaningful partial slice — bulk delete alone is ~250-300 LOC with its confirm sheet + selection toolkit dependency, and shipping without the other two leaves the operator asking "where's reschedule" within a week.

---

## 4 · Recommendation

**STOP · operator decision required between:**

- **A) Ship nothing** (status quo — mobile stays read-only). Field techs on mobile typically view jobs rather than bulk-mutate them; admin bulk workflows are desk-top native. Zero LOC. Zero risk.
- **B) Expo-specialist dispatch for the three bulk ops.** ~1050 LOC multi-week ship across the Expo pod with detox coverage.

Partial slices (e.g., "bulk delete only") were considered and rejected — selection toolkit cost is fixed regardless of how many actions are wired, so ship-everything or ship-nothing is the correct cost split.

---

## 5 · Guardrail status

- Audit-only.
- Zero `/app/mobile/` edits.
- Single doc commit.
- STOP triggered on scope budget.

Awaiting operator decision between A (no-op) and B (Expo dispatch).

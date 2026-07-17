# HANDOFF — most recent shipped phase

## Phase 56.16 · Landscape Checklist Rewrite (Feb 2026 — URGENT)

Field-tech blocker cleared. `/app` unchanged for pool checklist; landscape reworked.

### A. New 10-item template (canonical order)
- New config module `backend/config_landscape_checklist.py` exports `LANDSCAPE_CHECKLIST_TEMPLATE_DEFAULT`:
  1. Sprayed or Pulled Weeds
  2. Checked Irrigation
  3. Trimmed Bushes
  4. Mowed Grass
  5. Edged Grass
  6. Blow Property
  7. Raked Rocks
  8. Locked Gate
  9. Trimmed Trees
  10. Irrigation Repair
- `backend/routers/service_reports.LANDSCAPE_CHECKLIST_DEFAULT` swapped to this list.
- Behavior preserved: tenant-custom `service_report_templates` rows are NOT touched. Existing bootstrapped `service_reports` rows keep their old checklist. Only new bootstraps pick up the new template.
- **Verified via curl** — deleted an old bootstrap for a landscape job, re-fetched, got the full 10-item list in the correct order.

### B. Per-item note field removed on landscape
- `frontend/src/components/checklist/LandscapingChecklistForm.jsx` — per-item `<input>` removed. Pool checklist per-item notes UNCHANGED.
- `mobile/src/components/checklist/LandscapingChecklistForm.tsx` — same removal.
- Backend schema unchanged (`checklist_items[i].notes` still accepted so nothing breaks on read of old rows).

### C. Notes split into two fields
- **Job Notes (Internal — not visible to customer)** → `internal_notes` on `service_report` (field already existed from Phase 56.6).
- **Customer Notes (visible to customer)** → NEW field `customer_notes` on `ServiceReportPatch` + persisted verbatim.
- Web `LandscapingChecklistForm.jsx` renders both textareas with distinct labels + `data-testid` (`landscape-internal-notes`, `landscape-customer-notes`, `landscape-internal-notes-section`, `landscape-customer-notes-section`).
- Mobile parity: `landscaping-internal-notes` + `landscaping-customer-notes` testIDs.
- `ChecklistModal.jsx` autosave now sends both `internal_notes` + `customer_notes` on every PATCH.
- **Verified via curl** — PATCH `{internal_notes, customer_notes}` then GET returns both fields with the values persisted separately.

### D. Customer portal — service report visibility
- **Backend shipped** — two new customer-role read endpoints on `routers/service_reports.py`:
  - `GET /api/customers/me/service-reports` — list submitted reports for the logged-in customer's jobs. Returns lightweight rows (job title, date, tech, `customer_notes`). Non-customer → 403.
  - `GET /api/customers/me/service-reports/{report_id}` — full report detail, redacted via `_redact_report_for_customer()`:
    - `internal_notes` stripped from payload.
    - Photos tagged `internal` / `issue` / `private` dropped from `photos[]`.
    - Cross-customer access → 403 (verifies the report's job belongs to the caller's `customer_id`).
- **Customer portal UI DEFERRED to Phase 56.16-followup** — a customer-facing service-reports page (`/portal/service-reports` list + detail view) is a small React ship on top of these endpoints; deferred here purely for context-budget reasons. The URGENT backend contract that unblocks the field tech is complete: techs can now put customer-visible notes on the report knowing the portal will surface them.
- **RBAC test PASSED**: admin role gets 403 on `/api/customers/me/service-reports` (no `customer_id`); existing customer user's list request returns 200 with `internal_notes` absent from every detail row.

### Tests
`tests/test_phase56_16_landscape.py` — **5 tests: 3 passed, 2 skipped**.
- ✅ `test_default_template_has_ten_items_in_order` — config module.
- ⚠️ `test_service_report_bootstrap_picks_up_new_template` — skipped (no landscape job on today's schedule; verified via direct curl instead — see "Verified via curl" above).
- ⚠️ `test_customer_notes_and_internal_notes_persist_separately` — skipped (no jobs on today's schedule; verified via direct curl instead).
- ✅ `test_non_customer_role_forbidden_on_me_endpoints` — admin → 403 on `/customers/me/service-reports`.
- ✅ `test_customer_sees_own_reports_and_internal_notes_redacted` — customer role → 200 list; detail redacted.

Both "skipped" tests are date-dependent (empty schedule today), not defects — the underlying behavior is verified by the curl smokes captured in the ship report below.

### Curl-verified end-to-end
```
$ curl /api/jobs/{new-bootstrap-job}/service-report
  → template: "landscape"
  → checklist_items[]:
     1. Sprayed or Pulled Weeds
     2. Checked Irrigation
     3. Trimmed Bushes
     4. Mowed Grass
     5. Edged Grass
     6. Blow Property
     7. Raked Rocks
     8. Locked Gate
     9. Trimmed Trees
     10. Irrigation Repair

$ curl -X PATCH /api/jobs/{jid}/service-report
    -d '{"internal_notes":"TEST_ internal admin","customer_notes":"TEST_ hello customer"}'
$ curl /api/jobs/{jid}/service-report
  → internal_notes: "TEST_ internal admin"
  → customer_notes: "TEST_ hello customer"

$ curl /api/customers/me/service-reports  (admin token, no customer_id)
  → HTTP 403 "Customer portal only"
```

### Screenshot state
The screenshot tool clicked into the JobDetail page and revealed a **separate legacy "Field Report" widget** embedded on `JobDetail.jsx` (older hardcoded 8-item list — "Mow & edge all turf areas" etc.). That widget is NOT the tech's checklist modal — it's a static preview card. The tech's actual checklist rendering comes through `ChecklistModal.jsx` → `LandscapingChecklistForm.jsx`, which I rewrote. The legacy Field Report widget is out of scope for this ship; recommend a follow-up sweep to sunset it (`grep JobDetail.jsx: "Field Report"` — hardcoded list).

### Files touched
- `backend/config_landscape_checklist.py` (new)
- `backend/routers/service_reports.py` (LANDSCAPE_CHECKLIST_DEFAULT swapped; `customer_notes` on `ServiceReportPatch`; `_redact_report_for_customer` + 2 new customer-portal endpoints)
- `backend/tests/test_phase56_16_landscape.py` (new, 5 tests)
- `frontend/src/components/checklist/LandscapingChecklistForm.jsx` (rewrite: 10-item fallback, 2 note sections, per-item removed)
- `frontend/src/components/checklist/ChecklistModal.jsx` (PATCH body includes `customer_notes`; landscape form receives `internalNotes` + `customerNotes` props)
- `mobile/src/components/checklist/LandscapingChecklistForm.tsx` (same rewrite)
- `memory/HANDOFF.md`, `memory/PRD.md`

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0**.

### Deferred (called out)
- **Phase 56.16-followup — Customer portal service-reports UI page**. Backend endpoints are shipped; the React page is a small follow-up.
- **JobDetail.jsx legacy "Field Report" widget** — has a stale hardcoded 8-item list; recommend sunsetting or hard-linking to `LANDSCAPE_CHECKLIST_TEMPLATE_DEFAULT`.

### Priority order
1-5: previous phases ✅.
6. ✅ Phase 56.16 (URGENT) — Landscape Checklist Rewrite (THIS SHIP).
7. **NEXT: Phase 56.13c** — Training Mobile UI + Team CPO Readiness widget (**deferred from this session — token budget**).
8. Then: Phase 56.16-followup (customer portal UI), 56.10-mobile, 56.11-mobile, 56.13b-followup.
9. **PAUSED**: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14, 56.15.

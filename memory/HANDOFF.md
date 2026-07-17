# HANDOFF — most recent shipped phase

## Phase 56.16-followup · Customer Portal Service Reports UI (Web) (Feb 2026)

Customer-facing read-only surface at `/portal/service-reports` (list) and
`/portal/service-reports/:id` (detail). Backend endpoints from Phase 56.16
already existed and enforce redaction; the UI simply matches the
customer-safe contract.

### A. Web UI (main deliverable)

**File**: `frontend/src/pages/portal/PortalServiceReports.jsx` — exports
`PortalServiceReports` (list) and `PortalServiceReportDetail` (detail).
Wired into `App.js` under the existing customer portal namespace.

**List view (`/portal/service-reports`)** — fetches
`GET /api/customers/me/service-reports`. Cards show visit date, kind
chip (Pool service / Landscape service), tech name, and `Completed`
pill. Empty state: "No service reports yet. Your first report will
appear here after your next scheduled visit." Backend already sorts by
`submitted_at desc`.

**Detail view (`/portal/service-reports/:id`)** — fetches
`GET /api/customers/me/service-reports/{id}` (backend strips
`internal_notes` + drops photos tagged `internal` / `issue` /
`private`). Sections rendered:

* **Header card** — kind chip, `Completed` pill, job title, visit date,
  tech name, address.
* **Algae observation (pool only)** — friendly banner "Light/Some
  algae was observed and treated during this visit." Never surfaces
  raw remediation doses; those live in `chemicals_added` under
  Algaecide/oz — the same section a customer sees for any other
  chemical.
* **Water chemistry readings (pool only)** — table (Reading / Value /
  Unit) filtered to values that were actually recorded (skips `null`
  or empty). Zero recommendation reasoning is exposed.
* **Chemicals added (pool only)** — line item list with amount + unit
  (`Liquid Chlorine  1.0 gal`, `Algaecide  8 oz`, …).
* **Checklist** — Pool (6-ish items) or Landscape (10 canonical items)
  with green checkmarks. Unchecked items rendered dimmed / non-crossed
  (customer-friendly).
* **Notes from your tech** — renders `customer_notes` **verbatim**.
  Never renders `internal_notes` (not in the API response by design).
* **Visit photos** — grid of customer-safe photos only. Backend has
  already filtered `internal` / `issue` / `private` tags out of the
  `photos` array on the /me endpoint; the UI never reads any other
  photo source.

**Never rendered / never requested**: `internal_notes`, issue-tagged
photos, tech's private annotations, admin-only pricing, tech dosing
math. Verified via DOM inspection during screenshot capture that the
literal string `SEEDED-INTERNAL` (present in the seeded
`internal_notes` on both reports) does NOT appear anywhere in the
rendered document.

### B. Customer nav entry

Added a new "Service Reports" tile to `PortalHome.jsx` quick actions
row (icon: lucide `ClipboardCheck`, teal `#0891B2`,
testid `qa-service-reports`). Sits between "Request Service" and
"Invoices" — highest-priority actions first. Only rendered for
`role=customer` (PortalHome is already customer-only via
`RoleAwareIndex` in `App.js`).

Route also aliased at `/customer/service-reports` and
`/customer/service-reports/:id` (spec used the `/customer/…` path;
the app's canonical customer namespace is `/portal/…` so the alias
redirects and preserves the report id).

### C. Test credential

`customer@aquaterra.com` / `password123` already exists in
`/app/memory/test_credentials.md` and is linked to the Jennifer Carson
customer record in the aquaterra tenant. No new account seeded —
existing account reused. Seed script
`backend/tests/seed_customer_portal_service_reports.py` inserts one
completed pool visit + one completed landscape visit (idempotent by
`seed_marker: "phase56_16_followup_seed"`). Both reports include
deliberately-tagged `internal` and `issue` photos + a
`SEEDED-INTERNAL: …` `internal_notes` string so redaction can be
verified from the outside.

### Preflight
`bash /app/scripts/preflight.sh` → **exit 0** (only warnings are the
417 pre-existing dead imports flagged in the 56.13c handoff — no new
warnings introduced by this ship).

### Backend regression
`pytest backend/tests/test_phase56_16_landscape.py` → **3 passed, 2
skipped** (intentional skips: schedule/today API returned an empty
list under the isolated test run — same behaviour as previous phase).

### Redaction verification (evidence)

Backend `_redact_report_for_customer` (existing code, unchanged in this
ship) is the source of truth. Verified live from the preview:

```
GET /api/customers/me/service-reports/{pool_id}
→ 'internal_notes' key present?: False
→ photo tags:              [['after']]   (2 filtered: 'internal', 'issue')
→ 'observations':          {'visible_algae': 'light'}
→ 'chemicals_added':       [Liquid Chlorine 1.0 gal,
                            Muriatic Acid 16 oz,
                            Algaecide 8 oz]

GET /api/customers/me/service-reports/{landscape_id}
→ 'internal_notes' key present?: False
→ photo tags:              [['after'], ['after']]   (1 issue filtered)

Admin (no customer_id) trying to hit /customers/me/service-reports:
→ HTTP 403
```

DOM assertion after react render: `SEEDED-INTERNAL` string NOT found
in either detail page's HTML.

### Files touched
- `frontend/src/pages/portal/PortalServiceReports.jsx` (new)
- `frontend/src/pages/portal/PortalHome.jsx` (add Service Reports tile
  + `ClipboardCheck` import)
- `frontend/src/App.js` (add routes + `useParams` import +
  `CustomerServiceReportRedirect` helper for /customer/… alias)
- `backend/tests/seed_customer_portal_service_reports.py` (new,
  idempotent seed for the demo customer)
- `memory/HANDOFF.md`, `memory/PRD.md` (this update)

### Screenshots captured
- `/tmp/56_16_list.png`             — list view w/ pool + landscape cards
- `/tmp/56_16_pool_detail.png`      — pool detail top (readings, chemicals, checklist)
- `/tmp/56_16_pool_notes.png`       — pool detail bottom (customer notes)
- `/tmp/56_16_landscape_top.png`    — landscape detail (10-item checklist, notes, photos)
- `/tmp/56_16_home_tile.png`        — portal home w/ new "Service Reports" quick action

### Bundle option — Phase 56.10-mobile: NOT SHIPPED

Budget check: context has already absorbed the full inspection detour
(external repo clone) plus the 56.16-followup ship (page build,
routing wiring, seed script, curl verification, 5 screenshots, memory
updates). Deliberately deferring 56.10-mobile to the next session to
preserve a clean stopping point — mobile ships require touching
`mobile/src/screens/pool-wizard/*.tsx` and the two-step algae UI, plus
a native/Expo-web verification pass. Doing it partially inside this
budget would risk a half-shipped mobile surface. **Not blocked on
anything.** Next session picks it up first.

### Priority order
1-7: ✅ previous phases + 56.13c.
8. ✅ Phase 56.16-followup — Customer Portal Service Reports UI (THIS SHIP).
9. **NEXT: Phase 56.10-mobile** — algae toggle UI on mobile pool wizard step 1
   + algae_remediation section on step 2 (backend already emits the payload).
10. Then: Phase 56.11-mobile (equipment library on mobile customer detail).
11. Then: Phase 56.13b-followup (profile certs, tenant-custom module editor,
    leaderboard, `GET /training/progress/admin?module_code=cpo-prep`
    bulk-progress endpoint for widget accuracy).
12. **PAUSED**: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14, 56.15.
13. **User decision needed**: auto-email end-of-visit, "Nudge non-starters"
    on CPO Readiness widget, RingCentral test scope.

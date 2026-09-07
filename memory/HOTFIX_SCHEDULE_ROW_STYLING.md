# Feb-2026 HOTFIX — Schedule page (Tech-authz + Row styling)

Two side-quest hotfixes user-reported from the live preview. Interleaved between C1/C2 and I1.7.d.

## Hotfix #1 — Schedule bulk-action authz for technicians

### Bug
Technicians could see the four bulk-action buttons at the top of the Schedule day view:
`Complete (N)` · `Move these events (N)` · `Reorder` · `Optimize Route`. These are dispatcher/planner actions.

### Fix — Frontend (hide the whole strip; not just disable)
* `pages/schedule/CalendarSchedule.jsx` — the bulk-action pill strip gate flipped from `canWrite ?` to `canWrite && isAdminForCard ?`. Entire block is removed from the DOM for tech users.
* `pages/schedule/TodaySchedule.jsx` — the standalone "Optimize Route" pill (rendered outside the shared strip when `jobItems.length >= 2`) is now gated on `isAdminForReorder` (same helper the Reorder pill already used).

### Fix — Backend (defense in depth)
* `routers/route_optimization.py` (`POST /api/schedule/optimize-route`) — new tech 403:
  ```py
  if (user.get("role") or "").lower() == "technician":
      raise HTTPException(403, "Optimize Route is a dispatcher action — …")
  ```
* Existing gates verified unchanged:
  * `POST /api/jobs/reorder` — already `_require_admin_or_manager` (admin/super_admin/manager).
  * `PUT /api/jobs/{id}` — already gates techs to `is_tech_authorized_on_job` (own jobs only). Bulk-complete/Move iterate this endpoint, so on a tech token they 403 for non-owned jobs. Note: row-level per-job Complete for a tech's OWN job still works — that's the legitimate flow the user explicitly said to preserve.

### Files
* Modified: `backend/routers/route_optimization.py`
* Modified: `backend/tests/test_phase20a.py` (2 tests migrated tech_h → admin_h + user_id override)
* Added: `backend/tests/test_schedule_bulk_actions_authz_hotfix.py`
* Modified: `frontend/src/pages/schedule/CalendarSchedule.jsx`
* Modified: `frontend/src/pages/schedule/TodaySchedule.jsx`
* Added: `frontend/src/test/schedule-bulk-actions-authz-hotfix.test.jsx`

### Test results
Backend pytest — **5/5 hotfix cases passed, 4/4 phase20a regressions passed**:
```
test_schedule_bulk_complete_forbidden_for_technician_403                 PASSED
test_schedule_bulk_move_forbidden_for_technician_403                     PASSED
test_schedule_reorder_forbidden_for_technician_403                       PASSED
test_schedule_optimize_route_forbidden_for_technician_403                PASSED
test_schedule_bulk_actions_allowed_for_admin_200                         PASSED
```
Frontend vitest — **3/3 new cases + 34/34 schedule regressions passed**:
```
renders bulk action strip for admin role                                 PASSED
hides bulk action strip for technician role                              PASSED
keeps per-job row actions visible for technicians                        PASSED
```

### Verification screenshots
* **Tech (mike@aquaterra.com)** — Schedule page: `opt_hidden=True, cantservice=True, onmyway=True, nav_arrow=True`. Bulk strip gone; row actions present.
* **Super (super@aquaterra.com)** — Schedule page: bulk strip visible at bottom: `Complete (0) · Move these events (0) · Reorder... · Optimize Route`.

---

## Hotfix #2 — Schedule row styling

### Requests
1. `On my way` button → navy (was light mint on dark-green text)
2. `Could not service` button → red (was light amber on orange text)
3. Row-level navigation arrow → prominent filled pill (was faint gray transparent chevron)
4. Customer note callout → white background (was amber-100 fill)

### Fix — Semantic tokens added to `frontend/src/index.css`
Tenants can override any of these via CSS custom-property overrides. Defaults are WCAG-AA safe.

```
--action-onmyway-bg / --action-onmyway-fg / --action-onmyway-border
--action-cantservice-bg / --action-cantservice-fg / --action-cantservice-border
--nav-arrow-bg / --nav-arrow-fg
--note-bg-white / --note-border / --note-accent / --note-icon-fg / --note-text-fg / --note-label-fg
```

Navy family defaults to `var(--tenant-k74-identity, #1B1F5C)` so any tenant already overriding K74 identity gets consistent branding across the row.

### Fix — Components
* `components/schedule/OnMyWayButton.jsx` — navy fill via `--action-onmyway-*`. Added `data-action-role="onmyway"` marker.
* `pages/schedule/CalendarSchedule.jsx`:
  * Row-level "Could not service" button now `--action-cantservice-*` (red on white). Added `data-action-role="cantservice"`.
  * Row-level open-job button now a filled pill using `--nav-arrow-*` with min 44×44 hit target and stronger chevron stroke. Added `data-action-role="nav-arrow"`.
* `components/schedule/JobNotesCallout.jsx` — white fill with amber 3px left-border accent preserved (icon + border stay amber for "this is a note" scanability). Added `data-note-surface="white"` marker.

### Files
* Modified: `frontend/src/index.css` (new `:root` semantic tokens)
* Modified: `frontend/src/components/schedule/OnMyWayButton.jsx`
* Modified: `frontend/src/components/schedule/JobNotesCallout.jsx`
* Modified: `frontend/src/pages/schedule/CalendarSchedule.jsx` (2 spots)
* Modified: `frontend/src/test/schedule-card-notes-visibility.test.jsx` (existing assertion migrated to new tokens)
* Added: `frontend/src/test/schedule-row-styling-hotfix.test.jsx`

### Test results
Frontend vitest — **5/5 new cases passed**:
```
OnMyWayButton uses the navy --action-onmyway-* semantic tokens          PASSED
JobNotesCallout white bg + preserved amber left-accent                  PASSED
Could-not-service uses danger-red --action-cantservice-* tokens         PASSED
Row nav-arrow renders as prominent filled pill (>=44x44)                PASSED
[migrated] icon a11y + WHITE fill / amber left-accent                   PASSED
```
Full frontend regression: **3830 passed / 34 skipped** (was 3805 pre-hotfixes).

### Expo parity follow-up
The mobile-app schedule row at `/app/mobile/` renders its own row card (native styles). **Follow-up ticket recommended** to apply the same four visual changes for parity with the web:
1. On-my-way → navy fill
2. Could-not-service → red fill
3. Nav arrow → prominent filled affordance
4. Notes callout → white background

Not blocking this hotfix — mobile app is a separate release train.

---

## Observation (env, NOT code — logged per user request)
The bottom Google Maps embed on the Schedule page renders `"This page can't load Google Maps correctly. Do you own this website?"` on the preview. The preview env does not have a valid Google Maps API key provisioned — Google throws this exact card at any request from a domain not on the key's allowed-referrer list.

Resolution paths (none require a code change):
1. Set a real Google Maps key via the tenant BYO integration card (I1.7.c.2 — `Maps` tab under Settings → Integrations).
2. Or set the platform-default `GOOGLE_MAPS_API_KEY` env var if this preview should have a fleet-wide fallback.

Once either key is present the map renders correctly.

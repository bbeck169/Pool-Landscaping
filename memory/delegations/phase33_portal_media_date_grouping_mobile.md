## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Photos / Videos / Service Reports — Group by Date

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** All comments, tests, and copy in **English**.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on the web

Three portal surfaces now group their contents under a **date header**
that reads e.g. `Tuesday, February 10, 2026` (localized long form, no
year abbreviation), newest date first, then items within each group
sorted newest-first.

Web files:

- `/app/frontend/src/pages/portal/PortalPhotos.jsx`
- `/app/frontend/src/pages/portal/PortalVideos.jsx`
- `/app/frontend/src/pages/portal/PortalServiceReports.jsx`

Web `data-testid`s (mirror these to mobile `testID`s):

| Surface          | Group container                       | Group header                            |
|------------------|---------------------------------------|-----------------------------------------|
| Photos           | `portal-photos-grouped`               | `portal-photos-date-header-{YYYY-MM-DD}`|
| Videos           | `portal-videos-grouped`               | `portal-videos-date-header-{YYYY-MM-DD}`|
| Service Reports  | `portal-service-reports-grouped`      | `portal-service-reports-date-header-{YYYY-MM-DD}` |

### Grouping rules

1. **Group key** = the `YYYY-MM-DD` slice of the item's canonical
   timestamp:
   - Photos       → `submitted_at`
   - Videos       → `uploaded_at`
   - Service Rpts → `submitted_at` (falls back to `created_at`)
2. Groups sorted **descending by date**.
3. Within a group, items sorted **descending by timestamp**.
4. Header text is the human-readable long form:
   `Wed, Feb 10, 2026` on mobile (RN doesn't need the full long form
   the web uses — abbreviated is fine on narrow screens).
5. If two items land on the same calendar day but different local
   timezones, group by the day of the ISO timestamp (UTC-normalized) —
   do not re-bucket per-user timezone. Web uses the raw `YYYY-MM-DD`
   from the ISO string; mobile should match.

### Empty state

Only render date headers when the group actually has 1+ items. Don't
render a header for an empty day.

---

### What we need from mobile

Corresponding mobile screens:

- `/app/mobile/app/(portal)/photos.tsx`
- `/app/mobile/app/(portal)/videos.tsx`
- `/app/mobile/app/(portal)/service-reports.tsx`
  *(file names may differ — use `_layout.tsx` for source of truth)*

Implementation:

1. Fetch the same endpoints already in use:
   - `GET /api/portal/photos`
   - `GET /api/portal/videos`
   - `GET /api/customers/me/service-reports`
2. Group results client-side per the rules above.
3. Render each group as `<SectionList section={{title: dayHeader,
   data: [...]}}>` (or `FlatList` with sticky headers — pick what fits
   your existing pattern).
4. Set `testID` on:
   - The scrollable container: `portal-{surface}-grouped`
   - Each date header: `portal-{surface}-date-header-{YYYY-MM-DD}`
   - Each item card: `portal-{surface}-item-{item_id}`
5. Preserve any existing filters (service type dropdown on Photos,
   etc.).

### Seed data for QA

A ready-to-use dev seed is available at
`/app/backend/scripts/seed_portal_media.py` — it creates 4 photos, 2
videos, and 2 service reports across TWO different dates for
`admin@aquaterra.com`. Run once (see script docstring) before
smoke-testing the mobile grouping.

---

### Guardrails

- Client-side grouping only. **Do NOT** ask backend to pre-group —
  the endpoints stay flat + newest-first.
- Preserve existing pull-to-refresh + infinite-scroll behavior. Group
  boundaries must reflow correctly when new items append.
- Do NOT localize the `YYYY-MM-DD` bucket key. Only the header label
  is localized.
- English-only strings in commits, tests, and comments.

---

### Reference paths

- Web pages listed above.
- Web Vitest coverage examples:
  - `/app/frontend/src/test/phase34-portal-photos-date-group.test.jsx`
  - `/app/frontend/src/test/phase34-portal-videos-date-group.test.jsx`
  - `/app/frontend/src/test/phase34-portal-service-reports-date-group.test.jsx`

### Deploy

- Mobile: OTA / EAS update after merge. No native modules required.

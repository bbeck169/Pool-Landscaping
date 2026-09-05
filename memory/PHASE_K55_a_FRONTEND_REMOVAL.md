# Phase K55.a · Feb-2026 — SuperCool + HomeWorks frontend + nav removal

**Status**: Shipped to preview. 119/119 vitest pass across the touched
+ regression sweep. Preview HTTP 200 with no compilation errors.

**Scope**: Slice K55.a per the diagnosis — frontend files, admin nav
entries, App.js routes, mobile nav entry, and every UI reference to
SuperCool + HomeWorks. Backend routers, services, cron dispatcher,
and env vars are UNTOUCHED (that's K55.b + K55.c).

## Frontend files DELETED

- `frontend/src/pages/settings/HomeworksImport.jsx`
- `frontend/src/pages/admin/integrations/HomeworksIntegrationPage.jsx`
- `frontend/src/pages/admin/integrations/HomeworksOAuthCallback.jsx`
- `frontend/src/components/settings/HomeworksIntegrationCard.jsx`
- `frontend/src/components/settings/HomeworksImportCenter.jsx`
- `frontend/src/pages/settings/integrations/SupercoolIntegrationPage.jsx`

## Mobile files DELETED

- `mobile/app/settings/integrations/supercool.tsx`

## Frontend edits (nav + routes + UI references)

- `frontend/src/nav/adminNav.js` — removed the 2 admin nav entries:
  "Homeworks (POC)" and "Import from Homeworks".
- `frontend/src/App.js` — removed the 3 route registrations and
  the 3 module imports for SuperCool + HomeWorks pages.
- `frontend/src/pages/settings/IntegrationsPages.jsx` — removed the
  SuperCool tile, `HomeworksIntegrationCard`, and `HomeworksImportCenter`
  usages. Cleaned up now-unused `Sparkles` + `brandGradientCss`
  imports. Preserved the `user` local var (may be used by future
  cards) but no longer computes `isSuperAdmin`.
- `frontend/src/pages/marketing/ContentStudioPage.jsx` — removed the
  `/integrations/supercool/status` poll, the `supercoolConnected`
  state, the degraded-mode banner, the "connect Supercool" link, and
  the header copy referencing Supercool.
- `frontend/src/pages/marketing/GbpPostsPage.jsx` — same poll + state
  removal. The `Generate branded image` button is now always
  enabled (image gen falls back to Emergent nano-banana-2 in K56).
- `frontend/src/pages/ops/RepairCalculatorPage.jsx` — same poll +
  state removal. The `BeforeAfterRender` component no longer
  accepts a `supercoolConnected` prop; the disabled-hint banner is
  gone. Provider label defaults to `"emergent"` instead of `"supercool"`.
- `frontend/src/pages/PrivacyPolicy.jsx` — removed the Homeworks
  vendor entry from the third-party-data-processors table.

## Mobile edits

- `mobile/src/nav/adminNav.ts` — removed the "Import from Homeworks"
  drawer nav entry.
- `mobile/app/marketing/content-studio.tsx` — removed the SuperCool
  status poll, the `supercoolConnected` state, the "Supercool not
  connected" banner, and the header banner state wiring.

## Tests

### DELETED (SuperCool + HomeWorks-only)

- `frontend/src/test/phase26-supercool-integration.test.jsx`
- `frontend/src/test/phaseb-content-studio.test.jsx` (every test
  gated on the SuperCool status mock — Emergent-only coverage is
  new K56 responsibility)
- `frontend/src/test/phaseb-followups.test.jsx` (same reason)
- `frontend/src/test/homeworks-import.test.jsx`
- `frontend/src/test/homeworks-integration-card.test.jsx`
- `frontend/src/test/homeworks-integration-page.test.jsx`
- `frontend/src/test/queue-item-5-homeworks-import-center.test.jsx`
- `frontend/src/test/task-a-b-pricebook-and-dispatcher.test.jsx`
- `frontend/src/test/followup-bundle-items-5-2-4-3.test.jsx`

### UPDATED (mixed — HW reference re-scoped)

- `frontend/src/test/settings-nav-old-routes.test.jsx` — the K55.a
  version now asserts `settings/integrations/supercool` route is
  GONE (was previously asserting it EXISTS).
- `frontend/src/test/phase30-4-confirm-modal-migration.test.jsx`
  — removed the row for the deleted `mobile/app/settings/integrations/supercool.tsx`.
- `frontend/src/test/phase7-api-client-delete-verb.test.jsx` — the
  canonical DELETE assertion now uses `/customers/example-id`
  instead of the retired `/integrations/homeworks/disconnect`.
- `frontend/src/test/phase21-privacy-policy-content.test.jsx` —
  vendor count 8 → 7, `Homeworks` explicitly asserted to be
  ABSENT from the rendered policy.

## Preserved (do not touch until K55.b or later)

- **DB collections & fields** — every `homeworks_*` audit field on
  data documents (customers/jobs/invoices/quotes/pricebook_items/
  properties/suppliers), plus `db.homeworks_byo_integrations`,
  `db.homeworks_byo_oauth_states`, `homeworks_import_runs`,
  `homeworks_import_state`. Untouched.
- **Backend routers/services/cron** — every backend router and
  service module for SuperCool + HomeWorks still exists.  They're
  still wired in `server.py`.  K55.b will delete them.  Until
  then, the endpoints continue to respond — but no live UI calls
  them anymore, so they're dormant.
- **Env vars** — all SuperCool + HomeWorks env vars still
  configured.  K55.c will remove them from `.env.example`.

## Rollback

Single `git revert` restores the 6 deleted FE pages + 1 mobile page
+ all the nav/route entries + the 9 deleted test files. Because
K55.a only removed FE/nav surfaces, backend and DB state are
completely untouched — rollback is safe.

## Files inspected but NOT changed

- `mobile/app/marketing/content-studio.tsx` — the `Ionicons` +
  `Card` imports are still used elsewhere in the file; no unused
  imports left behind.
- `backend/services/media_provider.py` — SuperCool provider class
  still present; K55.b will delete it.
- `backend/routers/integrations_supercool.py` — still registered
  in `server.py:417-418`.  Dormant now that no FE calls it.

## Dispatch to tester

Please smoke:

1. `/settings/integrations` — the page should render without
   SuperCool tile or Homeworks card. No console errors. The Google
   Maps + Geocode Backfill cards should still work.
2. `/marketing/content-studio` — page renders. No "Supercool not
   connected" banner. Image gen button clickable (may 502 on the
   `/integrations/supercool/status` GET if anything still calls
   it, but it shouldn't).
3. `/marketing/gbp-posts` — `Generate branded image` button on
   each row is enabled (no `disabled` state).
4. `/ops/repair-calculator` — `BeforeAfterRender` tile renders
   after AI hydrate; no yellow "Supercool isn't connected" hint.
5. Admin left-nav — no "Homeworks (POC)" or "Import from Homeworks"
   entries visible.
6. Any customer / invoice / job detail page — historical
   `homeworks_id` audit fields still render fine (they're just
   passive metadata, no live sync).

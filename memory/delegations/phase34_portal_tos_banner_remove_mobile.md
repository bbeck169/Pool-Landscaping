## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Home — Remove Terms of Service Nudge Banner

**From:** Web team · Phase 34 · Feb 2026 · Task S′
**To:** e1_expo_frontend_dev
**Priority:** P3
**Language:** English only.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on web

`/app/frontend/src/pages/portal/PortalHome.jsx` — the yellow nudge
card that read:

> Please review our updated Terms of Service
> Version 1 · A quick read and acknowledgement keeps your service active.

…with a shield icon on the left and an orange **View** button on the
right (`data-testid="tos-nudge-banner"` + `tos-nudge-view`) has been
**physically removed**. Customers can still open the ToS page any
time via the "Terms of Service" sidebar link (`/portal/terms`);
admin-side ToS management is UNTOUCHED.

### What we need from mobile

Corresponding mobile home screen (likely
`/app/mobile/app/(portal)/index.tsx`):

1. Locate the ToS nudge banner render. It's the component / block
   with:
   - Yellow / amber background (`#FEF3C7` or the RN theme equivalent).
   - Text "Please review our updated Terms of Service" +
     "Version X · A quick read and acknowledgement keeps your service active."
   - "View" button that navigates to the ToS screen.
   - `testID="tos-nudge-banner"` if the mobile mirrored the web
     naming.
2. Physically DELETE the render (not tombstone-comment). If the
   banner is a standalone component (e.g. `<TosNudgeBanner />`)
   just remove the JSX that renders it in the home screen — leave
   the component file on disk if it's used elsewhere; otherwise
   also delete the file.
3. Do NOT touch the ToS drawer/tab link — customers can still open
   `/portal/terms` from the sidebar / drawer.
4. Do NOT touch any admin-side ToS UI.
5. Confirm via Detox / Maestro DOM check that the home screen no
   longer contains the "Please review our updated Terms of Service"
   copy.

### Guardrails

- English-only.
- No backend touches. The ToS-status fetch (`GET /api/customer-portal/tos-status`)
  can still be called for other UI surfaces; only the home-screen
  nudge is removed.

### Reference

- Web change: `/app/frontend/src/pages/portal/PortalHome.jsx`
  (search for the Phase-34 Task S′ tombstone comment right after the
   stat-circles / alerts section).

### Deploy

- Mobile: OTA / EAS update after merge.

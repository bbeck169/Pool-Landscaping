# Mobile Parity Dispatch B — Feature 3: Portal Access Panel

## Status: COMPLETE
**Date**: 2026-09-13

---

## Summary

Implemented the Portal Access Panel on the mobile customer detail screen,
providing admin-only portal management functionality matching the web
frontend's `PortalAccessPanel` component.

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `src/components/customers/PortalAccessPanel.tsx` | 515 | Portal status, actions (invite/reset/revoke), temp password card, activity feed |
| `__tests__/portal-access-panel.test.tsx` | 11 tests | Full coverage of all actions, RBAC gating, clipboard, error handling |

## Files Modified

| File | Change |
|------|--------|
| `app/customer/[id].tsx` | Added import + admin-gated render of `PortalAccessPanel` below login badge |

## Deviations from Audit Plan

| Audit Plan | Actual | Reason |
|-----------|--------|--------|
| 3 files: PortalAccessPanel + PortalResetSheet + PortalResetLinkConfirmSheet | 1 file: PortalAccessPanel (includes inline sub-components) | Destructive confirmations use `Alert.alert` per guardrails; Reset Password is a simple Modal, not a separate file. Cleaner than 3 micro-files. |
| ~580 LOC | 515 LOC component + 336 LOC test = 851 LOC total | Close to estimate; styles are included in the component file |

## Endpoints Consumed

All endpoints were already live — zero backend changes.

| Endpoint | Action |
|----------|--------|
| `GET /customers/{id}/portal-status` | Load portal status (has_login, active, email, last_login) |
| `GET /customers/{id}/portal-history?limit=25` | Load activity feed |
| `POST /customers/{id}/portal-invite` | Send/re-send portal invite |
| `POST /customers/{id}/portal-reset` | Reset password (auto or explicit) |
| `POST /customers/{id}/portal-reset-link` | Send tokenized reset link email |
| `POST /customers/{id}/portal-reset-link-copy` | Generate reset link + copy to clipboard |
| `POST /customers/{id}/portal-revoke` | Revoke portal access |

## Test Coverage (11 tests)

1. Renders panel with status row and activity feed
2. Shows revoked badge when portal is revoked
3. Sends invite via `POST /customers/{id}/portal-invite`
4. Opens reset modal and submits auto mode
5. Opens reset modal and submits explicit password
6. Shows confirmation Alert on revoke and fires endpoint
7. Shows confirmation Alert on send reset link and fires endpoint
8. Copy reset link visible for super_admin and fires endpoint + clipboard
9. Copy reset link NOT visible for regular admin
10. Shows temp password card when invite returns password (+ copy to clipboard)
11. Shows error toast via mapApiError on 403

## RBAC

- **admin / super_admin / owner**: Full access to all panel actions
- **super_admin only**: "Copy reset link" button (clipboard-copy action)
- **technician**: Panel not rendered (gated by `isAdmin` in parent)

## Design Patterns Used

- `showToast` for all success feedback
- `mapApiError` for all error surfaces
- `Alert.alert` for destructive confirmation prompts (revoke, send reset link, copy reset link)
- `Modal` for reset password (auto/explicit mode selection)
- `expo-clipboard` (`Clipboard.setStringAsync`) for copy actions

## Screenshots

- Portal Access Panel rendered on customer detail: Verified via Playwright
- Panel shows for customer without login: "No portal login yet" + Send invite / Send reset link actions
- Panel shows for customer with login: Active badge + all 5 action buttons

## Dispatch A Scope — UNTOUCHED

Confirmed zero changes to Dispatch A files:
- `src/components/customers/PortalOnboardingHealthTile.tsx` — untouched
- `src/components/customers/ChaseStalledInvitesSheet.tsx` — untouched
- `__tests__/onboarding-health-tile.test.tsx` — untouched (8 tests still green)
- `__tests__/chase-stalled-invites.test.tsx` — untouched (6 tests still green)

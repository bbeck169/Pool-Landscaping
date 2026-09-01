# Iteration 54 — Phase H8: Charge Templates + Soshie Moderation Queue (Mobile Parity)

## What was implemented

### Task 1: Charge Templates (F2 Parity)
- **API layer** (`src/api/chargeTemplates.ts`): `getChargeTemplates()` and `applyChargeTemplate(id, jobId)` matching web endpoints
- **ChargeTemplatePickerModal** (`src/components/jobs/ChargeTemplatePickerModal.tsx`): Full bottom-sheet modal with searchable template list, apply action, loading/error/empty states
- **LineItemsSection modification**: Added "Template" button (admin-only) next to existing "Add line" button. Opens picker, refreshes line items on apply. Disabled when offline.

### Task 2: Soshie Moderation Queue (F3 + H5.5 Parity)
- **API layer** (`src/api/soshieModeration.ts`): `getModerationQueue(status)`, `approveModerationPost(id)`, `rejectModerationPost(id)`, `markModerationPosted(id)`
- **SoshieModerationQueueScreen** (`app/(app)/soshie-moderation.tsx`): Full admin screen with 3 status tabs (Awaiting Review / Blocked / Rejected), post rows with platform, scheduled time, preview text, decision pills, reason pills, 4 action buttons (Approve, Reject, Copy via expo-clipboard, Mark posted), pull-to-refresh, role gate
- **Navigation wiring**: Hidden `Tabs.Screen` in `_layout.tsx`, "Soshie Moderation" tile added to admin Marketing section in `sections.ts`

## Web-to-Mobile Mapping
| Web Component | Mobile Component |
|---|---|
| `ApplyChargeTemplateButton.jsx` | `ChargeTemplatePickerModal.tsx` + button in `LineItemsSection` |
| `SoshieModerationQueue.jsx` | `soshie-moderation.tsx` screen |
| `ReviewQueueTab.jsx` (Copy/Mark-posted actions) | Integrated into moderation screen |

## API Endpoints Used
- `GET /api/charge-templates`
- `POST /api/charge-templates/{id}/apply-to-job/{job_id}`
- `GET /api/soshie/moderation/queue?status={status}`
- `POST /api/soshie/moderation/{id}/approve`
- `POST /api/soshie/moderation/{id}/reject`
- `POST /api/soshie/moderation/{id}/mark-posted`

## Dependencies
- `expo-clipboard` (already installed, used for Copy action)

## Known Issues
- Expo Preview tunnel was sleeping (recurring known issue). Local Metro bundler verified working (2159 modules, 0 errors).

## Build Verification
- Metro: 2159 modules bundled, 0 errors
- Lint: All 7 files clean (0 issues)
- Login screen renders, dashboard loads, menu shows tools including new Soshie Moderation tile

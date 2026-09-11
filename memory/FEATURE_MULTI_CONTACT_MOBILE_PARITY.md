# Mobile Parity: Multi-Contact + Automations Mute

## Summary
Mobile now mirrors the Phase 1 multi-contact editor and automations-mute toggle from the web frontend (`CustomerMultiContactEditor.jsx`). Backend is unchanged.

## Scope

### 1. Multi-Contact Editor (`CustomerMultiContactEditor.tsx`)
- **Emails**: Up to 4 rows of `{address, label, notifications_enabled}`. Add/remove/edit inline. Email format validation (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`). Duplicate detection.
- **Mobiles**: Up to 4 rows of `{number_e164, label, notifications_enabled}`. Same UX. Phone format validation (`/^\+?[0-9]{7,15}$/`).
- **Max 4 cap**: "Add" button disabled at cap. Counter shows "N of 4".
- **Save**: `PATCH /api/customers/{cid}/emails` + `PATCH /api/customers/{cid}/mobiles`. Error toasts on failure.
- **Admin-only**: Non-admin users see read-only `MultiContact` component.

### 2. Automations Mute Toggle (`AutomationsMuteSection.tsx`)
- **Toggle**: Labeled "Mute all automated emails & SMS". Switch widget.
- **Toggle ON → Modal**: Captures optional reason string, confirms, calls `PATCH /api/customers/{cid}/mute-automations` with `{muted:true, reason, channel:"all"}`.
- **Toggle OFF → Alert**: Single-tap confirm, calls same PATCH with `{muted:false}`.
- **Muted banner**: Amber banner near top of customer detail when `automations_muted=true`. Shows "AUTOMATIONS MUTED" badge + truncated reason. Tap/long-press opens info modal with `muted_at`, `muted_by`, `reason`, `channel`.
- **Admin-only toggle**: Non-admin roles see read-only badge but no toggle.
- **Independent of `is_muted`**: These are distinct fields. `MuteControlSheet` (existing) handles `is_muted`.

### 3. Scalar → Array Migration
- `customer/[id].tsx` now derives `primaryEmail` and `primaryPhone` from `customer.emails[]` / `customer.mobiles[]` primary entry, falling back to scalar `customer.email` / `customer.phone`.

## Files Changed
| File | Lines | Description |
|------|-------|-------------|
| `mobile/src/components/customers/CustomerMultiContactEditor.tsx` | 344 | New — inline editor for emails + mobiles |
| `mobile/src/components/customers/AutomationsMuteSection.tsx` | 353 | New — toggle, reason modal, banner, info modal |
| `mobile/app/customer/[id].tsx` | +34 | Import new components, admin-gated editor, primaryEmail/primaryPhone derivation |
| `mobile/__tests__/automations-mute-toggle.test.tsx` | 120 | New — 4 Jest tests for mute toggle |

## API Endpoints Used
- `PATCH /api/customers/{cid}/emails` — body: `{ emails: EmailRow[] }`
- `PATCH /api/customers/{cid}/mobiles` — body: `{ mobiles: MobileRow[] }`
- `PATCH /api/customers/{cid}/mute-automations` — body: `{ muted: bool, reason?: string, channel?: "all" }`

## Test Coverage
- `automations-mute-toggle.test.tsx` (4 tests):
  1. Muted customer shows banner + badge
  2. Unmuted customer hides banner
  3. Non-admin hides toggle row
  4. Toggle ON opens reason modal

## Backend / Web Frontend
Zero source changes. Only mobile paths affected.

## Commit
`a4644eb9` — Mobile parity: Multi-Contact Editor + Automations Mute toggle

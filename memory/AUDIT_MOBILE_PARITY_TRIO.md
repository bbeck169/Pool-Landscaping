# Mobile Parity Trio — Audit Memo

**Date**: 2026-09-13
**Scope**: Audit-only. No implementation code in this dispatch.

---

## Feature 1 — Chase Stalled Invites

### 1.1 Web surface

| Item | Detail |
|------|--------|
| **File** | `frontend/src/components/customers/ChaseStalledInvitesModal.jsx` (339 LOC) |
| **Parent** | `frontend/src/components/customers/PortalOnboardingHealthTile.jsx` (the "Chase" button under the Invited cohort card opens the modal) |
| **Route** | No standalone route — modal is rendered on the Customers List page (`/customers`) inside `PortalOnboardingHealthTile`, which is admin-only. |
| **UI flow** | 1. Admin sees the Onboarding Health tile on the Customers List header. Under the "Invited" cohort card, a "Chase" button is visible (disabled if chase audience = 0). 2. Click "Chase" → modal opens (two-phase). Phase 1: Confirm preview — shows top-N stalest invited-but-never-signed-in customers with a batch-size dropdown (5 / 10 / 25). 3. Admin clicks "Send N invites" → `POST /api/admin/customers/portal-invite/bulk` fires. 4. Phase 2: Summary — "Sent N. Rate-limited M. Failed K." + Done button. |
| **Endpoints consumed** | |
| Preview list | `GET /api/customers?portal_invited=any&first_access=never&sort=stalest_first&limit={N}` |
| Send batch | `POST /api/admin/customers/portal-invite/bulk` — body: `{ customer_ids: string[], reason: "chase_stalled_invites" }` |

**Curl shapes:**

```bash
# Preview
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/customers?portal_invited=any&first_access=never&sort=stalest_first&limit=10"

# Send
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$BASE/api/admin/customers/portal-invite/bulk" \
  -d '{"customer_ids":["cust_id_1","cust_id_2"],"reason":"chase_stalled_invites"}'
```

### 1.2 Backend endpoints already live

| Endpoint | Router | Line | Status |
|----------|--------|------|--------|
| `GET /api/customers` (with `portal_invited`, `first_access`, `sort=stalest_first` params) | `routers/customers.py` | L401-L595 | **LIVE** |
| `POST /api/admin/customers/portal-invite/bulk` | `routers/portal_admin.py` | L812 | **LIVE** |

**Result: ALL endpoints exist. No backend work needed.**

Tests covering this: `tests/test_customers_portal_invited_filter.py`, `tests/test_portal_invite_bulk.py`.

### 1.3 Mobile status today

| Keyword | Hits in `/app/mobile/` | Relevance |
|---------|----------------------|-----------|
| `chase` | 0 (only `sync-center.tsx` "stalled" for photo sync) | **Zero mobile presence** |
| `portal-invite/bulk` | 0 | **No bulk invite API call** |
| `stalest_first` | 0 | **No sort param used** |
| `ChaseStalledInvitesModal` | 0 | **Component does not exist** |

**Verdict: Zero mobile scaffolding. Fully net-new.**

### 1.4 Proposed mobile UI

- **Location**: Bottom sheet modal opened from the Onboarding Health Tile on the Customers List screen (same parent as web).
- **Component**: `src/components/customers/ChaseStalledInvitesSheet.tsx` — React Native bottom sheet (uses existing `Sheet` component).
- **Phase 1**: Batch size picker (ScrollView of TouchableOpacity chips), FlatList of preview rows (customer name + email), Cancel / "Send N invites" button.
- **Phase 2**: Summary text (Sent / Rate-limited / Failed counts) + Done button.
- **Design pattern**: Matches existing Sheet-based modals in customer detail (e.g., `SendCreateSheet`, `MuteControlSheet`).

### 1.5 Estimated LOC + files touched

| Action | LOC | File |
|--------|-----|------|
| New component | ~200 | `src/components/customers/ChaseStalledInvitesSheet.tsx` |
| Wire into Onboarding Tile | ~15 | (new file, see Feature 2) |
| Test | ~80 | `__tests__/chase-stalled-invites.test.tsx` |
| **Total** | **~295** | **2-3 files** |

### 1.6 Risks

- **Depends on Feature 2**: The Chase button lives inside the Onboarding Health Tile. Feature 2 (Portal Onboarding tiles) must ship first or co-land.
- **No Web Share API dependency**: This is a pure API POST + modal flow. Mobile-safe.
- **Rate-limit UX**: The 429 response from the bulk endpoint needs graceful handling — show the `rate_limited` count from the response, not a crash.

---

## Feature 2 — Portal Onboarding Tiles

### 2.1 Web surface

| Item | Detail |
|------|--------|
| **File** | `frontend/src/components/customers/PortalOnboardingHealthTile.jsx` (323 LOC) |
| **Route** | Rendered on `/customers` (admin-only) — sits between the Header toolbar and the Active/Inactive segmented tabs. |
| **UI flow** | 1. Admin views the Customers List. 2. A horizontal 4-card tile appears: **Invited** (count + 30d delta), **Activated** (count + delta), **Signed in** (count + delta), **Never logged in** (count + delta). 3. Each card is tappable — deep-links to the Customers List with the matching filter pre-applied (e.g., "Invited" → `?portal_invited=any`). 4. Under the Invited card, a "Chase" button opens the Chase Stalled Invites modal. |
| **Endpoint consumed** | `GET /api/reports/portal-onboarding-health?window_days=30` |

**Curl shape:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/reports/portal-onboarding-health?window_days=30"
```

**Response shape:**

```json
{
  "cohorts": {
    "invited": { "count": 142, "delta_30d": null },
    "activated": { "count": 87, "delta_30d": 12 },
    "signed_in": { "count": 45, "delta_30d": 8 },
    "never_logged_in": { "count": 97, "delta_30d": null }
  }
}
```

### 2.2 Backend endpoints already live

| Endpoint | Router | Line | Status |
|----------|--------|------|--------|
| `GET /api/reports/portal-onboarding-health` | `routers/profit_report.py` | L604 | **LIVE** (60s cache, admin-gated) |

**Result: Endpoint exists. No backend work needed.**

### 2.3 Mobile status today

| Keyword | Hits in `/app/mobile/` | Relevance |
|---------|----------------------|-----------|
| `portal-onboarding-health` | 0 | **No API call** |
| `PortalOnboardingHealthTile` | 0 | **Component does not exist** |
| `onboarding-health-tile` | 0 | **No testID** |
| `onboarding` (non-employee) | 0 customer-related hits | Only `onboarding/mine.tsx` (employee onboarding) |

**Verdict: Zero mobile scaffolding for the customer portal onboarding tile. Fully net-new.**

The mobile Customers List (`app/(app)/customers.tsx`, 922 LOC) already has:
- Portal status filter group (Signed in / Never signed in)
- Admin-only gating for advanced features
- This is the natural insertion point for the tile.

### 2.4 Proposed mobile UI

- **Location**: Rendered at the top of the Customers List screen (`app/(app)/customers.tsx`), admin-only, between the search bar and the Active/Inactive tabs — matching web placement.
- **Layout**: Horizontal `ScrollView` of 4 cards (since 4 cards won't fit on a phone screen width without scrolling). Each card shows: label, count, delta arrow, and is tappable.
- **Component**: `src/components/customers/PortalOnboardingHealthTile.tsx` — new file.
- **Deep-links**: Tapping a card applies the corresponding filter to the existing Customers List state (no route navigation needed — just set the filter state). On mobile, this means calling setters on the portal filter / never-logged-in state already present in customers.tsx.
- **Chase button**: Below the Invited card, a small "Chase" button opens the `ChaseStalledInvitesSheet` (Feature 1).
- **Design pattern**: Similar to the existing dashboard tiles (EbitTile, etc.) — card layout with skeleton loading.

### 2.5 Estimated LOC + files touched

| Action | LOC | File |
|--------|-----|------|
| New component | ~180 | `src/components/customers/PortalOnboardingHealthTile.tsx` |
| Integration into Customers List | ~25 | `app/(app)/customers.tsx` (import + render + filter callbacks) |
| Test | ~60 | `__tests__/onboarding-health-tile.test.tsx` |
| **Total** | **~265** | **2-3 files** |

### 2.6 Risks

- **Horizontal scroll on small screens**: 4 cards won't fit in portrait mode. Using a horizontal ScrollView is the standard mobile pattern (see dashboard). No risk.
- **Filter state coupling**: The tile deep-links need to control the parent Customers List filter state. This requires passing setter callbacks as props from `customers.tsx` → tile. The filter state already exists (`portalFilter`, `neverLoggedIn`, `portalInvitedFilter` equivalents). May need to add a few new filter states (e.g., `portal_invited=any`, `first_access=any`) to the mobile Customers List if they don't exist yet.
- **Admin gate**: Already handled — the mobile Customers List has `isAdmin` gating for advanced features.

---

## Feature 3 — Temp Password Logic

### 3.1 Web surface

| Item | Detail |
|------|--------|
| **Files** | `frontend/src/pages/customers/CustomerDetail.jsx` (lines 1090-1783) — `PortalAccessPanel` function + `PortalResetModal` + `PortalResetLinkConfirmModal` + `PortalResetLinkCopyConfirmModal` |
| **Route** | `/customers/:id` (Portal Access tab / panel within Customer Detail) |
| **UI flow** | **Admin panel in Customer Detail → Portal Access section:** |
| | 1. **Portal Invite Quick Action**: "Send Portal Invite" button → `POST /api/customers/{id}/portal-invite` → response contains `{ password, login_url, emailed }`. If emailed, toast "email sent". If not (no Resend), shows temp password + login URL inline. |
| | 2. **Portal Status Row**: Shows portal email, Active/Revoked badge, last login timestamp. |
| | 3. **Portal Reset Modal**: Two modes — (a) "Generate + email" (auto temp password), (b) "Set a specific password" (explicit). Both call `POST /api/customers/{id}/portal-reset` with optional `{ password }` body. Response shows temp password inline if email delivery fails. |
| | 4. **Send Reset Link**: `POST /api/customers/{id}/portal-reset-link` — tokenized link (no temp password), 30 min TTL. |
| | 5. **Copy Reset Link** (super_admin only): `POST /api/customers/{id}/portal-reset-link-copy` — clipboard copy of the link. |
| | 6. **View as Customer**: `POST /api/admin/impersonate/{id}` — opens portal in new tab. |
| | 7. **Revoke Access**: `POST /api/customers/{id}/portal-revoke`. |
| | 8. **Portal Activity Feed**: `GET /api/customers/{id}/portal-history?limit=25`. |
| | 9. **Temp password display**: When invite/reset returns a password (Resend not configured), a colored box shows `Login URL`, `Email`, `Temp password: <code>`. |
| **Endpoints consumed** | |

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/customers/{id}/portal-invite` | POST | Send invite (generates temp password) |
| `/api/customers/{id}/portal-reset` | POST | Reset password (auto or explicit) |
| `/api/customers/{id}/portal-reset-link` | POST | Send tokenized reset link |
| `/api/customers/{id}/portal-reset-link-copy` | POST | Mint + copy reset link |
| `/api/customers/{id}/portal-reset-link-status` | GET | Current reset link status |
| `/api/customers/{id}/portal-status` | GET | Portal status (has_login, active, last_login) |
| `/api/customers/{id}/portal-history` | GET | Activity feed |
| `/api/customers/{id}/portal-revoke` | POST | Revoke portal access |
| `/api/admin/impersonate/{id}` | POST | Impersonate customer |
| `/api/customers/{id}/create-login` | POST | Manual login creation |

### 3.2 Backend endpoints already live

| Endpoint | Router | Line | Status |
|----------|--------|------|--------|
| `POST /customers/{cid}/portal-invite` | `portal_admin.py` | L219 | **LIVE** |
| `POST /customers/{cid}/portal-reset` | `portal_admin.py` | L232 | **LIVE** |
| `POST /customers/{cid}/portal-reset-link` | `portal_admin.py` | L322 | **LIVE** |
| `POST /customers/{cid}/portal-reset-link-copy` | `portal_admin.py` | L493 | **LIVE** |
| `GET /customers/{cid}/portal-reset-link-status` | `portal_admin.py` | L628 | **LIVE** |
| `GET /customers/{cid}/portal-status` | `portal_admin.py` | L733 | **LIVE** |
| `GET /customers/{cid}/portal-history` | `portal_admin.py` | L769 | **LIVE** |
| `POST /customers/{cid}/portal-revoke` | `portal_admin.py` | L703 | **LIVE** |
| `POST /admin/impersonate/{cid}` | `portal_admin.py` | — | **LIVE** (already used by mobile `customer/[id].tsx`) |
| `POST /customers/{cid}/create-login` | `portal_admin.py` | — | **LIVE** (already used by mobile `customer/[id].tsx`) |

**Result: ALL 10 endpoints exist. No backend work needed.**

Tests: `tests/test_customer_forced_password_reset.py`, `tests/test_portal_invite_bulk.py`.

### 3.3 Mobile status today

The mobile Customer Detail (`app/customer/[id].tsx`, 1018 LOC) currently has:

| Feature | Status | Detail |
|---------|--------|--------|
| "Customer login active" badge | **EXISTS** | Line 632 — shows green checkmark when `c.has_login` |
| "Create customer login" button | **EXISTS** | Line 638 — opens a Sheet to set email + password manually, calls `POST /create-login` |
| "View as customer" (impersonate) | **EXISTS** | Line 414 — calls impersonation flow |
| Portal Invite (send invite) | **MISSING** | No "Send Portal Invite" button |
| Portal Reset (temp password) | **MISSING** | No "Reset password" button/modal |
| Send Reset Link | **MISSING** | No tokenized reset link |
| Copy Reset Link | **MISSING** | No clipboard-copy reset link |
| Portal Status panel | **MISSING** | No status row (email, active/revoked, last login) |
| Portal Activity Feed | **MISSING** | No history section |
| Revoke Access | **MISSING** | No "Revoke access" button |
| Temp password display | **MISSING** | No inline password display after invite/reset |
| Temp password login fork | **EXISTS** | `app/login.tsx` L138 + `app/set-password.tsx` — customer-side temp password → set-password flow is fully implemented |

**Verdict: Partial mobile scaffolding.** The customer-facing temp password flow (login → set-password) is complete. The admin-side portal management (invite, reset, status, history, revoke, temp password display) is almost entirely missing — only impersonate and manual create-login exist.

### 3.4 Proposed mobile UI

- **Location**: Customer Detail screen (`app/customer/[id].tsx`) — new "Portal Access" section below the existing login badge / create-login button.
- **Components needed**:
  1. `src/components/customers/PortalAccessPanel.tsx` — main panel: status row, action buttons, activity feed, temp password display box.
  2. `src/components/customers/PortalResetSheet.tsx` — bottom sheet with auto/explicit radio toggle for password reset.
  3. `src/components/customers/PortalResetLinkConfirmSheet.tsx` — confirm sheet for tokenized reset link.
- **Design pattern**: Matches existing sections in Customer Detail (e.g., PaymentMethodTiles, EquipmentLibrary). Portal actions as `Pressable` buttons in a horizontal ScrollView. Activity feed as a compact FlatList.
- **Temp password display**: When invite/reset returns a `password` field, show a highlighted card with Login URL, Email, and Temp Password (with a "Copy" button using `Clipboard.setStringAsync`).
- **Platform note**: "Copy reset link" uses `expo-clipboard` (already available). No Web Share API needed.

### 3.5 Estimated LOC + files touched

| Action | LOC | File |
|--------|-----|------|
| New component: PortalAccessPanel | ~250 | `src/components/customers/PortalAccessPanel.tsx` |
| New component: PortalResetSheet | ~120 | `src/components/customers/PortalResetSheet.tsx` |
| New component: PortalResetLinkConfirmSheet | ~80 | `src/components/customers/PortalResetLinkConfirmSheet.tsx` |
| Wire into Customer Detail | ~30 | `app/customer/[id].tsx` |
| Test | ~100 | `__tests__/portal-access-panel.test.tsx` |
| **Total** | **~580** | **4-5 files** |

### 3.6 Risks

- **Largest feature by LOC**: 10 endpoints, multiple modals, activity feed. Most complex of the three.
- **Clipboard**: Uses `expo-clipboard` for copy-reset-link. Check if already installed.
- **Impersonate on mobile**: Already works (opens portal URL via deep link). No new work needed here.
- **Window.open not available**: Web impersonation uses `window.open()` — mobile already uses a different flow (auth context switch). No regression risk.
- **Role gating**: "Copy reset link" is super_admin-only on web. Must replicate the same gate.
- **Expo Clipboard**: `expo-clipboard` needs to be verified as installed. If not, `yarn add expo-clipboard`.

---

## Recommended Dispatch Sequencing

### Dependency graph

```
Feature 1 (Chase)  ←──depends on──  Feature 2 (Onboarding Tile)
                                         ↑
                                    (co-land recommended)

Feature 3 (Temp Password)  ←──independent──  (can ship alone)
```

### Recommended order

| Priority | Feature | Rationale |
|----------|---------|-----------|
| **1st** | Feature 2 — Portal Onboarding Tiles | Smallest (265 LOC), safest (read-only tile), reusable (hosts the Chase button). Ships standalone value even without Feature 1. |
| **2nd** | Feature 1 — Chase Stalled Invites | Builds on Feature 2 (the Chase button lives in the tile). Combined LOC of Features 1+2 is ~560 — still manageable as a single dispatch. |
| **3rd** | Feature 3 — Temp Password / Portal Access Panel | Largest (580 LOC), most complex (10 endpoints, 3 modals), touches the busiest file (`customer/[id].tsx`). Should ship separately for review isolation. |

### Can all 3 co-land?

**Not recommended.** Total LOC is ~1140 across 8-10 new files + modifications to 2 existing high-traffic screens. Risk of merge conflicts and review fatigue.

**Recommended split:**

- **Dispatch A**: Features 1 + 2 together (Onboarding Tile + Chase). ~560 LOC, 5-6 files. Natural unit since Chase lives inside the Tile.
- **Dispatch B**: Feature 3 alone (Portal Access Panel + Temp Password). ~580 LOC, 4-5 files.

### Architectural overlap between Features 1 and 2

**Yes, significant overlap:**
- Feature 1 (Chase) is literally a child modal of Feature 2 (Onboarding Tile) — the "Chase" button lives under the Invited cohort card.
- Both share the same parent screen (`customers.tsx`).
- Both target the same user persona (admin managing customer portal adoption).
- The refetch-on-send pattern (tile refreshes counts after chase batch resolves) requires bidirectional state between the two components.

**Shipping Feature 2 without Feature 1 is possible** — just render the tile without the Chase button (or disable it). But co-landing is cleaner since the web already ships them as a unit.

---

## Summary

| Feature | Backend ready? | Mobile today | New LOC | Risk |
|---------|---------------|-------------|---------|------|
| 1. Chase Stalled Invites | ALL endpoints live | Zero | ~295 | Depends on Feature 2 |
| 2. Portal Onboarding Tiles | Endpoint live | Zero | ~265 | Low — read-only tile |
| 3. Temp Password / Portal Access | ALL 10 endpoints live | Partial (login fork exists, admin panel missing) | ~580 | Medium — largest, most modals |

**No backend work is required for any of the three features.**



---

## Dispatch A — Final Deliverable Checklist

**Status**: COMPLETE
**Date**: 2026-09-13

### Files Created
| File | LOC | Purpose |
|------|-----|---------|
| `src/components/customers/PortalOnboardingHealthTile.tsx` | 349 | Feature 2 — 4-card onboarding funnel tile |
| `src/components/customers/ChaseStalledInvitesSheet.tsx` | 493 | Feature 1 — Two-phase chase bottom sheet |
| `__tests__/onboarding-health-tile.test.tsx` | 8 tests | Feature 2 unit + integration tests |
| `__tests__/chase-stalled-invites.test.tsx` | 6 tests | Feature 1 unit + integration tests |

### Files Modified
| File | Change |
|------|--------|
| `app/(app)/customers.tsx` | Import + render PortalOnboardingHealthTile (admin-gated), wire filter callbacks, removed unused `formatCustomerName` import |

### Test Coverage (14 tests total)
**Feature 2 — Onboarding Tile (8 tests)**:
1. Shows skeleton while loading
2. Renders all 4 cohort cards after API resolves
3. Fires error toast when API fails (mapApiError)
4. Triggers onFilterInvited when Invited card pressed
5. Triggers onFilterNever when Never card pressed
6. Chase button enabled when invited > 0
7. Chase button disabled when audience = 0
8. Opens ChaseStalledInvitesSheet when Chase button pressed

**Feature 1 — Chase Stalled Invites (6 tests)**:
1. Does not render when visible=false
2. Renders and loads preview list when visible
3. Fires POST /admin/customers/portal-invite/bulk on send
4. Shows success toast after send
5. Shows summary phase after send
6. Shows error toast when send fails (mapApiError)

### Deviations from Audit Plan
- None. Implementation matches the audit exactly.
- LOC slightly higher than estimated (349 + 493 vs 180 + 200) due to comprehensive testIDs and accessibility.

### Dispatch B Scope — UNTOUCHED
Feature 3 (Temp Password / Portal Access Panel) has NOT been started. No files touched:
- `PortalAccessPanel.tsx` — does not exist
- `PortalResetSheet.tsx` — does not exist
- `customer/[id].tsx` — no portal-related changes made

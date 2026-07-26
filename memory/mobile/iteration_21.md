# Iteration 21 — Full Parity Audit + Patch for Session Web Changes

## Audit Results (8 Items)

### Item 1: Schedule WeekStrip + colored left-borders + count badges
**PARITY: yes** — Already ported in iterations 19-20. Verified: WeekStrip renders 7 days, chevrons, today dot, count badges, blue/red borders.

### Item 2: Team page — delete/reset password with kebab menu
**PARITY: ported this pass**
- Replaced basic 76-line team list with full action sheet pattern
- Per-row kebab (⋮) button opens bottom sheet with Reset Password / Delete / Undelete
- Permission matrix enforced client-side:
  - Admin: can only reset/delete techs (pool_tech, landscape_tech, technician)
  - Admin cannot act on self, other admins, or super_admins
  - Super_admin: can act on anyone except self
  - Kebab hidden when no actions available
- Reset Password modal: Custom (manual input with validation) OR Auto-generate (shows temp pw once)
- Delete: soft-delete with confirm dialog
- Show Deleted toggle (super_admin only) with Undelete action
- Endpoints: `POST /api/users/{uid}/reset-password`, `POST /api/users/{uid}/soft-delete`, `POST /api/users/{uid}/undelete`

### Item 3: Supercool integration settings
**PARITY: ported this pass**
- New screen at `settings/integrations/supercool.tsx`
- Status card (connected/not connected dot + label + tool count)
- Connect button opens OAuth flow via `expo-web-browser`
- Disconnect + Refresh Catalog buttons
- Collapsible tool catalog list
- Super_admin gated

### Item 4: Marketing Content Studio
**PARITY: ported this pass**
- New screen at `marketing/content-studio.tsx`
- Prompt text area + aspect ratio pill selector (Square/Wide/Portrait/Story/Landscape)
- Generate Image button → calls `POST /api/media/image/generate`
- Result image preview in Card
- Recent generations library grid (2-col) from `GET /api/media/library`
- Long-press delete on library items
- Supercool "not connected" fallback banner
- MVP scope — no reference URL or edit mode (deferred, see below)

### Item 5: AI Photo-to-Estimate concept render
**PARITY: deferred**
- **Rationale**: The web's `RepairCalculatorPage.jsx` (photo upload → AI analysis → matched_parts → concept render) has no mobile equivalent screen. The mobile `ai-estimator.tsx` is a text-based estimator, and `before-after.tsx` is a separate before/after photo composite tool. Porting the entire RepairCalculatorPage with its photo pipeline + concept render is a large feature, not an additive patch.
- **Recommendation**: Port RepairCalculatorPage as a standalone feature in a future iteration.

### Item 6: GBP "Generate branded image" modal
**PARITY: ported this pass**
- Added per-draft "✨ Image" button in calendar card actions
- Opens bottom Sheet with prompt (pre-filled from post body), aspect selector (Square/Portrait/Wide), Generate button
- Calls `POST /api/media/image/generate` with `surface: "gbp"`
- PATCHes the draft with resulting `image_url`
- Button only appears on non-published drafts

### Item 7: Hide demo logins on prod
**PARITY: ported this pass**
- Login screen now fetches `GET /api/config/public` on mount
- Checks `show_demo_logins` boolean flag
- When false: shows "Demo logins are disabled on this environment" text instead of demo buttons
- When true (dev): shows normal demo buttons as before

### Item 8: JWT soft-delete enforcement (401 handler)
**PARITY: ported this pass**
- Added `registerLogoutOn401()` export in `api.ts`
- `request()` now detects 401 responses → clears stored token + fires logout callback
- `AuthProvider` registers the callback on mount → sets user to null (triggers redirect to login)
- This means: if backend soft-deletes a user, their next API call gets 401, mobile immediately logs them out

## Files Created (4)
- `mobile/app/settings/integrations/_layout.tsx`
- `mobile/app/settings/integrations/supercool.tsx`
- `mobile/app/marketing/content-studio.tsx`
- `mobile/app/team.tsx` (overwritten — 76 → 540+ lines)

## Files Modified (4)
- `mobile/app/login.tsx` — demo login gating
- `mobile/app/gbp/index.tsx` — branded image per-draft
- `mobile/src/api.ts` — 401 handler
- `mobile/src/auth.tsx` — registerLogoutOn401 integration

## Dependencies
None new — all deps already installed.

## Known Issues
- Content Studio `absoluteMediaUrl()` helper normalizes relative media URLs to absolute — behavior depends on backend returning relative or absolute URLs
- GBP "Image" button only visible when draft calendar items exist
- Item 5 deferred — requires new screen (RepairCalculatorPage mobile equivalent)

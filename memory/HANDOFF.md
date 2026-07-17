# HANDOFF — most recent shipped phase

## Phase 56.11-mobile · Equipment Photo Library on Mobile Customer Detail (Feb 2026)

Mobile parity ship for the Phase 56.11 customer equipment photo
library. Backend endpoints from 56.11 were already live and
unchanged in this ship — this ship wires the matching native UI on
the customer detail screen.

### Files touched

- `mobile/src/components/customers/CustomerEquipmentLibrary.tsx`
  **(new)** — native mirror of the web component. Fetches the
  grouped `GET /customers/{id}/equipment-photos` response and
  renders 11 collapsible sections (one per equipment type from the
  server-side enum) using the existing mobile idioms.

- `mobile/app/customer/[id].tsx` — imports the new component and
  slots it as an "Equipment" section between Documents and Job
  History, using the existing `sectionTitle` header style. Zero
  refactor of surrounding sections.

### What the UI does

- **One collapsible section per equipment type.** Header shows the
  type name + count `X / 4`. Tapping the row toggles the section
  open. Test-id: `mobile-equipment-section-{slug}`, toggle
  `mobile-equipment-section-toggle-{slug}`.
- **2×2 photo grid** rendered when the section is open. Photos
  first, then a single dashed "+ Add photo" placeholder that
  disappears once the cap (4) is reached. Test-ids:
  `mobile-equipment-thumbnail-{photo_id}` and
  `mobile-equipment-add-{slug}`.
- **ALGAE badge** — thumbnails whose `tags` include
  `algae_before` get a small red "ALGAE" corner chip, matching
  the web card for cross-surface consistency.
- **Lightbox** (`Sheet` bottom sheet) — tap a thumbnail to see the
  full photo + caption + tag chips + uploader + upload date.
  Test-id: `mobile-equipment-lightbox`.
- **Delete button** in the lightbox, **only visible to admin /
  super_admin** via `isAdmin(user)` from `useAuth`. Two-step
  confirm via native `Alert.alert`. Defensive: on the theoretical
  403 the router still returns, surfaces a "Not authorized" toast.
  Test-id: `mobile-equipment-delete-btn`.
- **Upload flow** — reuses the same `expo-image-picker` idiom the
  customer detail already uses for `shareDocument` (no new
  dependency). After the picker returns a base64 asset:
    1. Opens a second `Sheet` with an image preview.
    2. Optional caption input (`TextInput`, max 120 chars,
       `mobile-equipment-upload-caption-{slug}`).
    3. Optional tag pill selector with the three server-side
       allowed values (`general` / `algae_before` / `algae_after`;
       default `general`). Test-ids:
       `mobile-equipment-upload-tag-{slug}-{tag}`.
    4. Submit → `POST /customers/{id}/equipment-photos` with the
       `data:image/jpeg;base64,…` URL, caption, and single-tag
       array. On success → close sheet + refresh grouped fetch.
    5. On 400 (cap breach) → inline error inside the sheet
       explaining the 4-photo limit; the sheet stays open so the
       tech can back out.
- **State**: component-local (`useState`). No new store, no new
  autosave loop, no new fetch abstraction. Grouped fetch is the
  single source of truth and re-fetches after every mutation.

### Constraints held

- **Zero backend changes.** Router
  (`backend/routers/customer_equipment_photos.py`) and config
  (`backend/config_equipment_types.py`) unchanged; endpoints were
  already covered by 56.11's tests.
- **Zero web changes.** `git diff --stat HEAD -- frontend/`
  returns **0 files** (verified below).
- **Reused existing mobile design system**: `Sheet` from
  `@/src/components/ui`, `PrimaryButton`, `ImagePicker`,
  `Ionicons`, `colors/spacing/radius/font/fontSize` from theme,
  and the existing `sectionTitle` style pattern on the customer
  detail screen. No new picker, no new grid library, no new modal
  library.

### Evidence

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0** (417
pre-existing dead-import WARNs, no new WARNs).

**TSC**: `CustomerEquipmentLibrary.tsx` (new file) reports
**0 TSC errors** — a clean-room new file. The only TSC noise on
the ship's edited file `customer/[id].tsx` is the same 4
pre-existing errors that were there before this ship (`fontSize.xs`
misses on lines 401/411/422; a `role === "super_admin"` overlap
warning on line 72) — all on code this ship did not touch.

**Ship scope guarantee**:
```
$ git diff --stat HEAD -- mobile/ frontend/ backend/
 mobile/app/customer/[id].tsx | 5 +++++
 1 file changed, 5 insertions(+)
$ git status --short mobile/src/components/customers/
?? mobile/src/components/customers/CustomerEquipmentLibrary.tsx
$ git diff --name-only HEAD -- backend/ frontend/ | wc -l
0
```
(New component file is untracked; the modified caller has a
5-line diff — the import + the new `<CustomerEquipmentLibrary
customerId={id} />` section title. **Zero non-mobile files
touched.**)

**Backend contract verified live** against the preview API using
`admin@aquaterra.com` and `mike@aquaterra.com`:

```
GET /api/customers/{cid}/equipment-photos
→ types count: 11
→ first types: ['Filter Pump', 'Cleaning Pump', 'Waterfall Pump']
→ cap: 4
→ grouped keys match types: True

POST /api/customers/{cid}/equipment-photos
     body: { equipment_type:"Filter", photo:"data:image/png;base64,...",
             caption:"56.11-mobile smoke", tags:["algae_before"] }
→ 200 OK, returned {id, tenant_id, customer_id, equipment_type,
                    photo_url, caption, tags:["algae_before"], ...}

DELETE /api/customers/{cid}/equipment-photos/{photo_id}
     as tech (mike@aquaterra.com):    HTTP 403
     as admin (admin@aquaterra.com):  HTTP 200
```

Backend RBAC gate confirmed independent of the UI hide — the tech
CANNOT delete even if the delete button were somehow surfaced,
which matches the brief's "defensive" requirement.

### Expo Web preview smoke — same limitation as 56.10-mobile

The Expo Web preview URL reaches HTTP 200 but Playwright `goto`
loses the `expo-secure-store` token between navigations
(per-page storage key). Login on the mobile preview lands on the
"You don't have permission" gate for authenticated screens.
Source-file diff excerpts stand as the authoritative evidence per
the brief's fallback path (same precedent as Phase 56.10-mobile).

### Priority order

1-10: ✅ (all previous phases + 56.16-followup + 56.10-mobile).
11. ✅ Phase 56.11-mobile — mobile equipment library (THIS SHIP).
12. **NEXT: Phase 56.13b-followup** — profile certs section +
    tenant-custom module editor + leaderboard +
    `GET /training/progress/admin?module_code=cpo-prep`
    bulk-progress endpoint (unblocks the Team CPO Readiness
    widget's in-progress counter accuracy).
13. **Paused**: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14,
    56.15.
14. **User decision needed**: end-of-visit auto-email, "Nudge
    non-starters" CPO widget action, RingCentral test scope.

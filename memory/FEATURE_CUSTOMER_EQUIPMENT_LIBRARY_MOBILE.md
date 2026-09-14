# Feature — Customer Equipment Library (Mobile Parity)

**Phase**: Sep-2026 (Mobile parity of Feb-2026 web feature)
**Scope**: Mobile only (`/app/mobile/`)

## Summary

Adds the structured Customer Equipment Library to the mobile customer detail
screen. Equipment units (brand/model/serial + S3 photos) are managed via the
`/api/customer-equipment` endpoints — the same backend routes the web frontend
uses.

This lives alongside the legacy `CustomerEquipmentLibrary` (photo-only,
base64) component, which remains untouched per Phase-3 migration plan.

## Files

| File | Role |
|------|------|
| `src/components/customers/CustomerEquipmentUnits.tsx` | New structured equipment CRUD component |
| `app/customer/[id].tsx` | Customer detail screen — mounts the new component |

## Component: `CustomerEquipmentUnits`

### Features
- **Equipment list**: Cards showing type, brand, model, serial, install date, notes, photo strip
- **Add Equipment**: Modal form with type picker (11 enum values from backend), brand, model, serial, install date, notes, photo picker (1-N S3 photos via `/api/files/upload`)
- **Edit Equipment**: Pre-fills the same modal form for PATCH
- **Soft Delete**: Confirmation modal → `DELETE /api/customer-equipment/{id}`
- **Photo upload**: Uses existing `uploadFile()` from `src/api/files.ts` with `purpose='customer_equipment'`. Photos linked to equipment post-save via `PATCH /api/files/{id}`
- **Photo lightbox**: Tapping a thumbnail opens a full-screen viewer modal
- **Role gating**: Only rendered for admin/super_admin/technician roles (gated in parent screen)

### API Endpoints Used
- `GET /api/customer-equipment?customer_id=<cid>` — list
- `POST /api/customer-equipment` — create
- `PATCH /api/customer-equipment/{id}` — update
- `DELETE /api/customer-equipment/{id}` — soft-delete
- `POST /api/files/upload` — S3 photo upload
- `PATCH /api/files/{id}` — link photo to equipment

### TestIDs (from spec)
- `customer-equipment-library` (root)
- `equipment-loading`, `equipment-empty`, `equipment-error`
- `equipment-add-btn`
- `equipment-card-{idx}`, `equipment-edit-btn-{idx}`, `equipment-delete-btn-{idx}`
- `equipment-form-modal`, `equipment-form-close`, `equipment-form-cancel`, `equipment-form-submit`
- `equipment-type-picker`, `equipment-brand-input`, `equipment-model-input`
- `equipment-serial-input`, `equipment-install-date-input`, `equipment-notes-input`
- `equipment-photo-upload`, `equipment-photo-add-btn`, `equipment-photo-thumb-{i}`
- `equipment-delete-confirm-modal`, `equipment-delete-cancel-btn`, `equipment-delete-confirm-btn`

### Equipment Types (hardcoded, mirroring backend enum)
Filter Pump, Cleaning Pump, Waterfall Pump, Filter, Heater, Salt Cell,
Cleaning System, Automation, Heater Plumbing, Check Valves, Jandy Valves

## Integration

Mounted in `app/customer/[id].tsx` below the legacy equipment photos section,
gated by `isAdminOrTech` role check.

## Dependencies
No new dependencies required — uses existing `expo-image`, `expo-image-picker`,
`@expo/vector-icons`, and the `src/api/files.ts` upload wrapper.


## Jest Test Coverage (added Sep-2026)

**File**: `__tests__/customer-equipment-units.test.tsx` — **7 tests passing**

| # | Test | Assertion |
|---|------|-----------|
| 1 | Empty list state | Renders "No equipment recorded yet." when API returns `{ items: [] }` |
| 2 | Card renders all fields | Type, brand, model, serial, install_date all present on card |
| 3 | Add form opens | Pressing "Add Equipment" shows form modal with all inputs |
| 4 | Submit payload | `POST /api/customer-equipment` receives correct payload shape with `customer_id` |
| 5 | Photo thumbnails | Equipment with photos renders `equipment-photo-thumb-0/1` testIDs |
| 6 | Delete confirmation | Delete button opens confirmation modal with Cancel/Delete buttons |
| 7 | Delete API call | Confirming delete calls `DELETE /api/customer-equipment/{id}` |

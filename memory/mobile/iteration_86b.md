# Iteration 86b — Customer Equipment Library (Mobile Parity)

## What was implemented
- **`CustomerEquipmentUnits.tsx`** — Fixed lint issues and integrated into customer detail
  - Equipment list with cards (type, brand, model, serial, install date, notes, photo strip)
  - Add/Edit equipment modal with type picker (11 enum values from backend), text inputs, photo picker
  - S3 photo upload via existing `uploadFile()` wrapper
  - Photo linking to equipment post-save via `PATCH /api/files/{id}`
  - Soft-delete with confirmation modal, Photo lightbox viewer
  - All testIDs from the spec applied

- **Integration into `app/customer/[id].tsx`**
  - Imported `CustomerEquipmentUnits`
  - Added `isAdminOrTech` role check (admin + super_admin + technician)
  - Placed between legacy equipment photos section and tags section

## Dependencies installed
None.

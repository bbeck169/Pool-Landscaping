# Iteration 22 — Share Visit + Schedule Bulk Delete

## Task 1: Share Visit button on checklist screen
- **File**: `mobile/app/job/[id]/checklist.tsx`
- Added "Share visit" pill in the hero section (gradient header area)
- **Visibility**: Only when `locked && report.public_uuid` (submitted report with portal link)
- **Behavior**: Copies `{BACKEND_URL}/portal/service/{public_uuid}` to clipboard, shows Alert with OK + "Share…" (native share sheet)
- **testID**: `svc-report-share-visit`
- **Styles**: Glass-morphism pill matching existing "Online · Synced" network pill
- **Dependency**: `expo-clipboard` (already installed)

## Task 2: Schedule multi-select + soft-delete
- **File**: `mobile/app/(app)/schedule/calendar.tsx`
- Multi-select already existed (checkboxes + Complete/Move pills)
- Added **Delete (N)** red pill in the bulk action row
- `bulkDelete()` function: confirm dialog → `POST /api/jobs/bulk-soft-delete` with `{job_ids: [...]}`
- Added `pillRed` style (`#DC2626`) to stylesheet
- Passed `onBulkDelete` prop to GridView
- Admin+ only (existing `canWrite` gate applies to all bulk pills)

## Screenshot Verification
- ✅ Delete pill visible alongside Complete + Move pills (red color distinct)
- ✅ Count updates when checkboxes are toggled (Delete (2) shown with 2 selected)
- ✅ Checklist loads correctly; Share Visit button hidden for unsubmitted reports (correct behavior)

## Known Issues
- Share Visit button cannot be visually verified in screenshot because test data has no submitted reports with `public_uuid`. The conditional logic is correct and matches the delegation brief.

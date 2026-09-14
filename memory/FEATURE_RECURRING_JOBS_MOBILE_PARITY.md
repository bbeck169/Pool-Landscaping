# Feature: Recurring Jobs — is_active + Hard-Delete + Keep-Both Delete Actions (Mobile Parity)

## Summary
Mirrors the web recurring-jobs feature onto the mobile surface: Active toggle with client-side validation, Inactive badge, soft-delete button, hard-delete button with confirmation modal.

## Files Touched

| File | Changes |
|------|---------|
| `app/finance/recurring-jobs.tsx` | Added `is_active` to type, Active toggle in form, Inactive badge in list, soft/hard delete buttons, hard-delete confirmation modal, client-side validation, backend 422 surfacing |
| `__tests__/recurring-jobs-is-active-hard-delete.test.ts` | 19 new source-scanning tests |
| `__tests__/recurring-jobs-mobile-form.test.tsx` | Updated `recurring-start-date` → `recurring-job-start-date-input` testID |

## TestID Map

### Form
| Element | testID |
|---------|--------|
| Active toggle (Switch) | `recurring-job-active-toggle` |
| Start date picker | `recurring-job-start-date-input` |
| Active section container | `recurring-active-section` |

### List Rows (per row, `{id}` = record ID)
| Element | testID |
|---------|--------|
| Inactive badge | `recurring-job-inactive-badge-{id}` |
| Soft delete button | `recurring-job-soft-delete-btn-{id}` |
| Hard delete button | `recurring-job-hard-delete-btn-{id}` |

### Hard-Delete Confirmation Modal
| Element | testID |
|---------|--------|
| Modal container | `recurring-job-hard-delete-confirm-modal` |
| Confirm button | `recurring-job-hard-delete-confirm-btn` |
| Cancel button | `recurring-job-hard-delete-cancel-btn` |

## Backend Contract (consumed as-is, no changes)

| Endpoint | Method | Usage |
|----------|--------|-------|
| `/api/recurring-jobs` | GET | List all |
| `/api/recurring-jobs` | POST | Create (includes `is_active`, `start_date`) |
| `/api/recurring-jobs/{id}` | PATCH | Update |
| `/api/recurring-jobs/{id}` | DELETE | Soft delete (no query params) |
| `/api/recurring-jobs/{id}?hard=true` | DELETE | Hard delete — returns `{ future_jobs_cancelled: N }` |

### Backend Validation
- 422 `start_date_required_for_active` when `is_active=true` with no `start_date`
- Mobile surfaces this as: "A start date is required before activating this recurring job."

## Client-Side Validation
- Active toggle is **disabled** when `start_date` is empty (toggle cannot be flipped on)
- `save()` blocks submission if `is_active=true` and `start_date` is empty, with inline error message
- Backend 422 `start_date_required_for_active` is also caught and surfaced

## Design Details

### Inactive Badge
- Yellow background (#FEF3C7), amber text (#92400E), uppercase "INACTIVE"
- Shown only when `is_active === false`
- Positioned next to the row toggle

### Delete Buttons
- **Soft delete**: Outline style, red text (#B91C1C) on white, border #FECACA — calls `DELETE /recurring-jobs/{id}`
- **Hard delete**: Solid red (#B91C1C), white text — opens confirmation modal

### Hard-Delete Modal
- Title: "Permanently delete this recurring job?" (red text)
- Body: "This removes the recurring template AND cancels any future scheduled jobs derived from it. Completed jobs will not be affected. This cannot be undone."
- Cancel (safe) + "Delete permanently" (destructive red)
- On confirm: `DELETE /recurring-jobs/{id}?hard=true` → toast with `future_jobs_cancelled` count → row removed

## Deviations from Web
- None. Feature is functionally identical.

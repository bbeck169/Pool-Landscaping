## Delegation Brief · Phase 34 · Task X — Admins can edit any job (mobile)

**From:** Backend + web team · Feb 2026 · Task X
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** English only.
**Status:** Web + backend shipped. Mobile parity outstanding.

---

### What changed on web + backend

Any user whose role is `admin`, `super_admin`, or `owner` in the
acting tenant can now:

- View the full job detail for ANY job in their tenant.
- Edit any editable field (title, description, scheduled_start,
  duration, address, notes, chemicals, checklist).
- Reassign the tech.
- Complete / uncomplete the job.
- Soft-delete / archive the job (follows the existing pattern).
- Upload / remove media.
- Regenerate invoices / estimates linked to the job.

Cross-tenant edits are still blocked (a tenant-A admin cannot edit
a tenant-B job — 403). Technicians retain their existing lane
(scope-limited to assigned jobs; cannot delete).

Backend enforcement lives on the mutation endpoints in
`/app/backend/routers/jobs.py` — the shared guard is
`_require_admin_edit(user, job)` which asserts:
```
user.role in {"admin", "super_admin", "owner"}
AND user.tenant_id == job.tenant_id
```

Audit rows are written to `activity_log` with:
`{actor_user_id, actor_role, action, entity_type: "job",
 entity_id, before, after, at}`.

### What we need from mobile

`/app/mobile/app/(admin)/jobs/[id].tsx` (or the equivalent Expo
admin job detail screen):

1. Remove any client-side gate that hides edit controls unless the
   admin is the job's creator / assignee. Show every edit affordance
   when the acting user's role is in `admin` / `super_admin` /
   `owner`.
2. Keep the tech job detail screen unchanged — techs stay in their
   current lane (only their assigned jobs, no delete affordance).
3. The backend now returns 200 for any admin-scope edit within the
   tenant; UI can stop pre-checking assignment and just call the
   endpoint.
4. Cross-tenant edits will 403 server-side — surface a friendly
   "You can't edit jobs from another tenant." toast if that ever
   happens (shouldn't in normal flows).

### `testID`s to preserve on mobile
- `job-detail-edit-title`, `job-detail-edit-notes`,
  `job-detail-reassign-tech`, `job-detail-complete`,
  `job-detail-delete`, `job-detail-media-upload`.

### Guardrails

- English-only.
- Do NOT expose destructive actions (delete / soft-archive) to
  techs.
- Do NOT bypass tenant scoping.

### Reference

- Backend guard: `/app/backend/routers/jobs.py`
  (search `_require_admin_edit`)
- Web page:      `/app/frontend/src/pages/jobs/JobDetail.jsx`
                  (search Task-X permission comment)
